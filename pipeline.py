from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import multiprocessing
import os
import resource
import time
from collections import Counter, deque
from concurrent.futures import Future, ProcessPoolExecutor
from pathlib import Path
from typing import Any, Iterable, Iterator

ROOT: Path = Path(__file__).resolve().parent
BUCKET: str = 'hw3-ml-rnd'
ENDPOINT: str = 'http://127.0.0.1:19010'
ACCESS_KEY: str = 'hw3local'
SECRET_KEY: str = 'hw3-local-experiment-only'
EXTENSIONS: Path = ROOT / '.duckdb-extensions'


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def s3_client() -> Any:
    import boto3
    from botocore.config import Config

    return boto3.client('s3', endpoint_url=ENDPOINT, aws_access_key_id=ACCESS_KEY,
                        aws_secret_access_key=SECRET_KEY, region_name='us-east-1',
                        config=Config(s3={'addressing_style': 'path'},
                                      connect_timeout=2, read_timeout=60,
                                      retries={'max_attempts': 2}))


def duck_connection(threads: int = 2) -> Any:
    import duckdb

    connection = duckdb.connect(config={'threads': threads, 'memory_limit': '1GB',
                                        'extension_directory': str(EXTENSIONS),
                                        'temp_directory': str(ROOT / 'runtime/duckdb-tmp')})
    connection.execute('LOAD httpfs')
    connection.execute(f"""CREATE SECRET local_s3 (
        TYPE s3, KEY_ID '{ACCESS_KEY}', SECRET '{SECRET_KEY}', REGION 'us-east-1',
        ENDPOINT '127.0.0.1:19010', URL_STYLE 'path', USE_SSL false
    )""")
    return connection


def load_sql_input(connection: Any, key: str) -> None:
    connection.execute("""CREATE TABLE vacancies AS
        SELECT * EXCLUDE (skills), list_sort(list_distinct(skills)) AS skills
        FROM read_json(?, format='newline_delimited', columns={
            id: 'VARCHAR', title: 'VARCHAR', region: 'VARCHAR', skills: 'VARCHAR[]',
            salary: 'DOUBLE', salary_low: 'DOUBLE', salary_high: 'DOUBLE',
            currency: 'VARCHAR', gross: 'BOOLEAN', experience: 'VARCHAR'
        })""", [f's3://{BUCKET}/{key}'])
    unique, total = connection.execute('SELECT count(DISTINCT id), count(*) FROM vacancies').fetchone()
    if unique != total:
        raise ValueError('Vacancy ids must be unique and non-null')


def batches(records: Iterable[dict[str, Any]], batch_rows: int) -> Iterator[list[list[str]]]:
    if batch_rows < 1:
        raise ValueError('batch_rows must be positive')
    current: list[list[str]] = []
    for record in records:
        current.append(record['skills'])
        if len(current) == batch_rows:
            yield current
            current = []
    if current:
        yield current


def map_batch(batch: list[list[str]]) -> Counter[tuple[str, ...]]:
    counts: Counter[tuple[str, ...]] = Counter()
    for raw_skills in batch:
        skills = sorted(set(raw_skills))
        for size in (1, 2, 3):
            counts.update(itertools.combinations(skills, size))
    return counts


def map_reduce(records: Iterable[dict[str, Any]], batch_rows: int,
               workers: int) -> tuple[Counter[tuple[str, ...]], int]:
    """Map bounded batches to local counters and reduce them with bounded in-flight work.

    Args:
        records: Iterable[dict[str, Any]] - Stream of canonical vacancy records.
        batch_rows: int - Maximum vacancies in one map task.
        workers: int - Number of independent map processes; one uses the current process.

    Return:
        tuple[Counter[tuple[str, ...]], int]: Frequencies and processed map task count.
    """
    if workers < 1:
        raise ValueError('workers must be positive')
    counts: Counter[tuple[str, ...]] = Counter()
    tasks: int = 0
    if workers == 1:
        for batch in batches(records, batch_rows):
            counts.update(map_batch(batch))
            tasks += 1
        return counts, tasks
    pending: deque[Future[Counter[tuple[str, ...]]]] = deque()
    with ProcessPoolExecutor(max_workers=workers,
                             mp_context=multiprocessing.get_context('spawn')) as pool:
        for batch in batches(records, batch_rows):
            pending.append(pool.submit(map_batch, batch))
            tasks += 1
            if len(pending) >= 2 * workers:
                counts.update(pending.popleft().result())
        for future in pending:
            counts.update(future.result())
    return counts, tasks


def streamed_records(key: str, chunk_bytes: int, stats: dict[str, Any]) -> Iterator[dict[str, Any]]:
    response = s3_client().get_object(Bucket=BUCKET, Key=key)
    body = response['Body']
    value = hashlib.sha256()
    carry: bytes = b''
    stats.update({'rows': 0, 'bytes': 0, 'chunks': 0, 'http': response['ResponseMetadata']['HTTPStatusCode']})
    try:
        for chunk in body.iter_chunks(chunk_size=chunk_bytes):
            value.update(chunk)
            stats['bytes'] += len(chunk)
            stats['chunks'] += 1
            lines = (carry + chunk).split(b'\n')
            carry = lines.pop()
            for line in lines:
                if line:
                    stats['rows'] += 1
                    yield json.loads(line)
        if carry:
            stats['rows'] += 1
            yield json.loads(carry)
        stats['sha256'] = value.hexdigest()
    finally:
        body.close()


def count_rows(counts: Counter[tuple[str, ...]]) -> list[dict[str, Any]]:
    return [{'size': len(skills), 'skills': list(skills), 'frequency': frequency}
            for skills, frequency in sorted(counts.items(), key=lambda item: (len(item[0]), item[0]))]


def sql_counts(connection: Any) -> list[dict[str, Any]]:
    connection.execute((ROOT / 'sql/combinations.sql').read_text())
    rows = connection.execute('SELECT size, skills, count(*) FROM combinations GROUP BY ALL').fetchall()
    return sorted([{'size': size, 'skills': skills, 'frequency': frequency}
                   for size, skills, frequency in rows], key=lambda row: (row['size'], row['skills']))


def cpu_seconds() -> float:
    return sum(getattr(resource.getrusage(kind), field)
               for kind in (resource.RUSAGE_SELF, resource.RUSAGE_CHILDREN)
               for field in ('ru_utime', 'ru_stime'))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('method', choices=['mapreduce', 'duckdb'])
    parser.add_argument('--key', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--batch-rows', type=int, default=250)
    parser.add_argument('--chunk-bytes', type=int, default=65536)
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    start: float = time.perf_counter()
    cpu_start: float = cpu_seconds()
    stats: dict[str, Any] = {'method': args.method, 'pid': os.getpid(), 'workers': args.workers}
    if args.chunk_bytes < 1:
        raise ValueError('chunk_bytes must be positive')
    if args.method == 'mapreduce':
        counts, tasks = map_reduce(streamed_records(args.key, args.chunk_bytes, stats),
                                   args.batch_rows, args.workers)
        rows = count_rows(counts)
        stats.update({'map_tasks': tasks, 'batch_rows': args.batch_rows, 'chunk_bytes': args.chunk_bytes})
    else:
        with duck_connection(args.workers) as connection:
            connection.execute('PRAGMA enable_profiling=\'json\'')
            connection.execute('SET profiling_output = ?', [str(args.output.with_suffix('.duckdb-profile.json'))])
            load_sql_input(connection, args.key)
            stats['rows'] = connection.execute('SELECT count(*) FROM vacancies').fetchone()[0]
            rows = sql_counts(connection)
    stats.update({'core_seconds': time.perf_counter() - start,
                  'cpu_seconds': cpu_seconds() - cpu_start,
                  'distinct_combinations': {str(size): sum(r['size'] == size for r in rows) for size in (1, 2, 3)}})
    save_json(args.output, rows)
    save_json(args.output.with_suffix('.stats.json'), stats)
    print(json.dumps(stats, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
