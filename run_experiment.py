from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psutil
from botocore.exceptions import BotoCoreError, ClientError

from pipeline import ACCESS_KEY, BUCKET, ENDPOINT, ROOT, SECRET_KEY, save_json, s3_client, sha256


def upload(path: Path, key: str) -> dict[str, Any]:
    client = s3_client()
    client.upload_file(str(path), BUCKET, key)
    response = client.get_object(Bucket=BUCKET, Key=key)
    actual = hashlib.sha256()
    downloaded: int = 0
    body = response['Body']
    with body:
        for chunk in body.iter_chunks(chunk_size=65536):
            actual.update(chunk)
            downloaded += len(chunk)
    expected: str = sha256(path)
    if actual.hexdigest() != expected or downloaded != path.stat().st_size:
        raise AssertionError('S3 upload round trip failed')
    return {'key': key, 'bytes': downloaded, 'sha256': expected, 'http': 200,
            'etag': client.head_object(Bucket=BUCKET, Key=key)['ETag']}


def profile(command: list[str], output: Path, server_pid: int) -> dict[str, Any]:
    """Measure one fresh client process and its descendant processes while it runs.

    Args:
        command: list[str] - Command executed without a shell.
        output: Path - Worker result path, also used for its log and timing evidence.
        server_pid: int - RustFS process monitored separately from the clients.

    Return:
        dict[str, Any]: End-to-end time, sampled process-tree RSS and worker statistics.
    """
    start: float = time.perf_counter()
    peak: int = 0
    server_peak: int = 0
    samples: int = 0
    with output.with_suffix('.log').open('w') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
        monitored = psutil.Process(process.pid)
        server = psutil.Process(server_pid)
        while process.poll() is None:
            try:
                members = [monitored, *monitored.children(recursive=True)]
                rss: int = 0
                for member in members:
                    try:
                        rss += member.memory_info().rss
                    except psutil.NoSuchProcess:
                        pass
                peak = max(peak, rss)
                server_peak = max(server_peak, server.memory_info().rss)
                samples += 1
            except psutil.NoSuchProcess:
                pass
            time.sleep(0.005)
        if process.returncode:
            raise RuntimeError(f'Worker failed ({process.returncode}): {output.with_suffix(".log").read_text()}')
    stats: dict[str, Any] = json.loads(output.with_suffix('.stats.json').read_text())
    stats.update({'end_to_end_seconds': time.perf_counter() - start,
                  'client_tree_peak_rss_bytes': peak, 'rustfs_peak_rss_bytes': server_peak,
                  'rss_samples': samples, 'sampling_interval_seconds': 0.005,
                  'result_path': str(output.relative_to(ROOT)), 'command': command})
    return stats


def compare(paths: list[Path], expected_sha: str) -> dict[str, Any]:
    baseline: list[dict[str, Any]] = json.loads(paths[0].read_text())
    for path in paths:
        actual = json.loads(path.read_text())
        if actual != baseline:
            raise AssertionError(f'Full frequency table mismatch: {path}')
        stats = json.loads(path.with_suffix('.stats.json').read_text())
        if stats['method'] == 'mapreduce' and stats['sha256'] != expected_sha:
            raise AssertionError('MapReduce did not read the expected S3 object')
    return {'equal': True, 'compared_runs': len(paths), 'rows_in_each_result': len(baseline),
            'comparison': 'Exact equality of every (size, skills, frequency) row; no tolerances',
            'distinct_combinations': {str(size): sum(row['size'] == size for row in baseline)
                                      for size in (1, 2, 3)},
            'result_sha256': sha256(paths[0])}


def main() -> None:
    """Run pilot and full S3 experiments while owning the local RustFS lifecycle.

    Args:
        None

    Return:
        None: Captured outputs, resource measurements and verification evidence are saved.
    """
    parser = argparse.ArgumentParser()
    default_binary: Path = ROOT / 'bin/rustfs' if (ROOT / 'bin/rustfs').exists() else ROOT.parent / 'hw-2/bin/rustfs'
    parser.add_argument('--rustfs', type=Path, default=default_binary)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--pilot-only', action='store_true')
    args = parser.parse_args()
    if args.repeats < 1:
        raise ValueError('repeats must be positive')
    root = ROOT / 'artifacts'
    runs = root / 'runs'
    runs.mkdir(parents=True, exist_ok=True)
    environment: dict[str, str] = dict(os.environ)
    environment.update({'RUSTFS_UNSAFE_BYPASS_DISK_CHECK': 'true', 'RUSTFS_STORAGE_CLASS_STANDARD': 'EC:2',
                        'RUSTFS_ERASURE_SET_DRIVE_COUNT': '4', 'RUSTFS_OBS_LOGGER_LEVEL': 'warn',
                        'RUSTFS_CONSOLE_ENABLE': 'false'})
    disks: list[str] = []
    for number in range(1, 5):
        disk = ROOT / f'runtime/disk{number}'
        disk.mkdir(parents=True, exist_ok=True)
        disks.append(str(disk))
    command: list[str] = [str(args.rustfs.resolve()), 'server', '--address', '127.0.0.1:19010',
                          '--access-key', ACCESS_KEY, '--secret-key', SECRET_KEY, *disks]
    measurements: list[dict[str, Any]] = []
    uploads: list[dict[str, Any]] = []
    verification: dict[str, Any] = {}
    with (root / 'server.log').open('w') as log:
        server = subprocess.Popen(command, env=environment, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
        try:
            for _ in range(80):
                if server.poll() is not None:
                    raise RuntimeError(f'RustFS exited: {(root / "server.log").read_text()[-4000:]}')
                try:
                    s3_client().list_buckets()
                    break
                except (BotoCoreError, ClientError):
                    time.sleep(0.25)
            else:
                raise TimeoutError('RustFS readiness timed out')
            try:
                s3_client().create_bucket(Bucket=BUCKET)
            except ClientError as error:
                if error.response['Error']['Code'] not in ('BucketAlreadyOwnedByYou', 'BucketAlreadyExists'):
                    raise
            sources: list[str] = ['pilot'] if args.pilot_only else ['pilot', 'full']
            for source in sources:
                key: str = f'{source}.jsonl'
                metadata = upload(ROOT / 'data' / key, key)
                uploads.append(metadata)
                paths: list[Path] = []
                repeats: int = 1 if source == 'pilot' else args.repeats
                for repetition in range(repeats):
                    methods: list[tuple[str, int]] = [('mapreduce', 1), ('mapreduce', 2), ('duckdb', 2)]
                    if repetition % 2:
                        methods.reverse()
                    for method, workers in methods:
                        output: Path = runs / f'{source}-{method}-{workers}-{repetition + 1}.json'
                        command = [sys.executable, str(ROOT / 'pipeline.py'), method, '--key', key,
                                   '--output', str(output), '--workers', str(workers)]
                        stats = profile(command, output, server.pid)
                        stats.update({'source': source, 'repetition': repetition + 1})
                        measurements.append(stats)
                        paths.append(output)
                        print(json.dumps(stats, ensure_ascii=False), flush=True)
                        save_json(root / 'measurements.json', measurements)
                verification[source] = compare(paths, metadata['sha256'])
                if s3_client().head_object(Bucket=BUCKET, Key=key)['ETag'] != metadata['etag']:
                    raise AssertionError('S3 object changed during benchmark')
                if source == 'full':
                    shutil.copyfile(paths[0], root / 'frequencies.json')
                    subprocess.run([sys.executable, str(ROOT / 'analyze.py')], cwd=ROOT, check=True)
            save_json(root / 'uploads.json', uploads)
            save_json(root / 'verification.json', verification)
            import duckdb

            save_json(root / 'environment.json', {
                'platform': platform.platform(), 'machine': platform.machine(), 'python': platform.python_version(),
                'logical_cpus': psutil.cpu_count(), 'physical_cpus': psutil.cpu_count(logical=False),
                'ram_bytes': psutil.virtual_memory().total, 'duckdb': duckdb.__version__,
                'rustfs_version': subprocess.check_output([str(args.rustfs.resolve()), '--version'], text=True).strip(),
                'rustfs_binary_sha256': sha256(args.rustfs), 'endpoint': ENDPOINT,
                'scope': 'One machine; client process tree and RustFS measured separately',
            })
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
    print('Experiment complete; the owned RustFS process has stopped.', flush=True)


if __name__ == '__main__':
    main()
