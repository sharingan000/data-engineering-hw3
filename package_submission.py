from __future__ import annotations

import zipfile
from pathlib import Path

from pipeline import ROOT, sha256


def main() -> None:
    files: list[Path] = sorted(ROOT.glob('*.py'))
    files.extend(ROOT / name for name in ['README.md', 'DATA_SOURCES.md', 'LICENSE-DATA.txt',
                                          'requirements.lock', '.gitignore',
                                          'data/full.jsonl', 'data/pilot.jsonl',
                                          'output/pdf/ml_rnd_vacancies_report.pdf'])
    files.extend(sorted((ROOT / 'sql').glob('*.sql')))
    files.extend(sorted(path for path in (ROOT / 'artifacts').rglob('*') if path.is_file()))
    files = sorted(set(files))
    sums: Path = ROOT / 'SHA256SUMS'
    sums.write_text(''.join(f'{sha256(path)}  {path.relative_to(ROOT).as_posix()}\n' for path in files))
    files.append(sums)
    output: Path = ROOT / 'submission/ml_rnd_homework_3.zip'
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, arcname='homework-3/' + path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError('Archive verification failed')
    print(f'{output}: {output.stat().st_size} bytes; {len(files)} files; SHA256={sha256(output)}')


if __name__ == '__main__':
    main()
