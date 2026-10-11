from __future__ import annotations

import argparse
import csv
import json
import math
import re
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from pipeline import ROOT, save_json, sha256

SOURCE_URL: str = ('https://www.kaggle.com/api/v1/datasets/download/'
                   'ilyazawilsiv/it-vacancies-from-headhunter-website/IT_vacancies.csv?datasetVersionNumber=1')
SOURCE_PAGE: str = 'https://www.kaggle.com/datasets/ilyazawilsiv/it-vacancies-from-headhunter-website'
SOURCE_SHA256: str = '42b443e48059459b3d69393200628052e1168ea97833a3ea5769658fb166751e'
TITLE_PATTERN: str = (r'(?i)(\bml\b|\bai\b|data\s*scien|machine\s*learn|deep\s*learn|'
                      r'\br\s*&\s*d\b|\brnd\b|research\s*(engineer|scientist)|'
                      r'машинн\w*\s+обуч|нейронн\w*\s+сет|компьютерн\w*\s+зрен|computer\s*vision)')
TITLE_REGEX: re.Pattern[str] = re.compile(TITLE_PATTERN)


def download() -> Path:
    data = ROOT / 'data'
    data.mkdir(exist_ok=True)
    path = data / 'IT_vacancies.csv'
    if path.exists():
        return path
    archive = data / 'source.zip'
    temporary = archive.with_suffix('.part')
    with urllib.request.urlopen(SOURCE_URL, timeout=90) as response, temporary.open('wb') as target:
        while block := response.read(1024 * 1024):
            target.write(block)
    temporary.replace(archive)
    with zipfile.ZipFile(archive) as zipped:
        members = [item for item in zipped.infolist() if Path(item.filename).name == 'IT_vacancies.csv']
        if len(members) != 1:
            raise ValueError('Expected one IT_vacancies.csv in the source archive')
        with zipped.open(members[0]) as source, path.open('wb') as target:
            while block := source.read(1024 * 1024):
                target.write(block)
    return path


def parse_skills(value: str) -> list[str]:
    if not value or value == '{}':
        return []
    if not (value.startswith('{') and value.endswith('}')):
        raise ValueError(f'Invalid PostgreSQL skills array: {value[:80]}')
    values = next(csv.reader([value[1:-1]], escapechar='\\', doublequote=False))
    return [skill.strip().casefold() for skill in values if skill.strip()]


def positive(value: str | None) -> float | None:
    if not value:
        return None
    try:
        number: float = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) and number > 0 else None


def parse_boolean(value: str) -> bool | None:
    if value.lower() in ('t', 'true', '1'):
        return True
    if value.lower() in ('f', 'false', '0'):
        return False
    if not value:
        return None
    raise ValueError(f'Unknown boolean: {value}')


def canonical(row: dict[str, str]) -> dict[str, Any]:
    low: float | None = positive(row.get('salary_from'))
    high: float | None = positive(row.get('salary_to'))
    if low is not None and high is not None and low > high:
        low, high = None, None
    salary: float | None = (low + high) / 2 if low is not None and high is not None else low or high
    return {'id': row['id'], 'title': row['name'].strip(), 'region': row['area_name'].strip(),
            'skills': parse_skills(row['key_skills']), 'salary': salary,
            'salary_low': low, 'salary_high': high,
            'currency': row.get('salary_currency') or None,
            'gross': parse_boolean(row.get('salary_gross', '')),
            'experience': row.get('experience') or None}


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open('w') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n')


def main() -> None:
    """Create the frozen ML/RnD subset from a checksum-verified source snapshot.

    Args:
        None

    Return:
        None: Canonical JSONL data and a provenance manifest are written to disk.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--source', type=Path, default=ROOT / 'data/IT_vacancies.csv')
    args = parser.parse_args()
    source: Path = download() if args.download else args.source
    if sha256(source) != SOURCE_SHA256:
        raise ValueError('Source checksum differs from the frozen Kaggle version 1 snapshot')
    latest: dict[str, dict[str, str]] = {}
    total: int = 0
    duplicate_rows: int = 0
    with source.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            total += 1
            if row['id'] in latest:
                duplicate_rows += 1
            previous: dict[str, str] | None = latest.get(row['id'])
            rank: tuple[str, str] = (row.get('published_at', ''), json.dumps(row, sort_keys=True))
            if previous is None or rank > (previous.get('published_at', ''), json.dumps(previous, sort_keys=True)):
                latest[row['id']] = row
    selected: list[dict[str, Any]] = []
    for row in latest.values():
        if TITLE_REGEX.search(row['name']) or 'Дата-сайентист' in row.get('professional_roles_name', ''):
            selected.append(canonical(row))
    selected.sort(key=lambda row: row['id'])
    if not selected:
        raise ValueError('The ML/RnD selection is empty')
    (ROOT / 'data').mkdir(exist_ok=True)
    write_jsonl(ROOT / 'data/full.jsonl', selected)
    write_jsonl(ROOT / 'data/pilot.jsonl', selected[:min(100, len(selected))])
    audit: dict[str, Any] = {
        'variant': 'ML, RnD', 'source_url': SOURCE_URL, 'source_page': SOURCE_PAGE,
        'source_version': 1, 'source_author': 'ilyazawilsiv', 'license': 'Apache-2.0',
        'source_period': '2023-09-18 to 2023-10-17',
        'source_bytes': source.stat().st_size, 'source_sha256': sha256(source),
        'source_rows': total, 'source_unique_ids': len(latest), 'duplicates_removed': duplicate_rows,
        'title_regex': TITLE_PATTERN,
        'selection': 'Latest deterministic row per id, then title regex OR professional role Дата-сайентист',
        'skill_normalization': 'Unicode casefold and trim; no synonym merging or skill filtering',
        'selected_rows': len(selected), 'rows_with_skills': sum(bool(row['skills']) for row in selected),
        'rows_with_salary': sum(row['salary'] is not None for row in selected),
        'regions': dict(Counter(row['region'] for row in selected).most_common()),
        'salary_groups': dict(Counter(f"{row['currency']}|{row['gross']}" for row in selected
                                      if row['salary'] is not None).most_common()),
        'full_sha256': sha256(ROOT / 'data/full.jsonl'),
        'full_bytes': (ROOT / 'data/full.jsonl').stat().st_size,
        'pilot_rows': min(100, len(selected)), 'columns': reader.fieldnames,
    }
    save_json(ROOT / 'artifacts/dataset.json', audit)
    print(json.dumps(audit, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
