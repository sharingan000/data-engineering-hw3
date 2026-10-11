from __future__ import annotations

import platform
import shutil
import urllib.request
import zipfile
from pathlib import Path

import duckdb

from pipeline import EXTENSIONS, ROOT, sha256

RUSTFS_ARCHIVE_SHA256: str = '18aac7101c3484b98f93de64a0609aaa8e02aba072ba7927172c4b2eae7d4843'
RUSTFS_URL: str = 'https://github.com/rustfs/rustfs/releases/download/1.0.1/rustfs-macos-aarch64-v1.0.1.zip'


def main() -> None:
    EXTENSIONS.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(config={'extension_directory': str(EXTENSIONS)}) as connection:
        connection.execute("INSTALL httpfs FROM 'https://extensions.duckdb.org'")
        connection.execute('LOAD httpfs')
    binary = ROOT / 'bin/rustfs'
    reused = ROOT.parent / 'hw-2/bin/rustfs'
    if binary.exists() or reused.exists():
        print(f'RustFS: {binary if binary.exists() else reused}')
        return
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise SystemExit('Provide a RustFS 1.0.1 binary using run_experiment.py --rustfs PATH on this platform')
    binary.parent.mkdir(exist_ok=True)
    archive = binary.parent / 'rustfs.zip'
    with urllib.request.urlopen(RUSTFS_URL, timeout=90) as source, archive.open('wb') as target:
        shutil.copyfileobj(source, target)
    if sha256(archive) != RUSTFS_ARCHIVE_SHA256:
        raise ValueError('RustFS archive checksum mismatch')
    with zipfile.ZipFile(archive) as zipped:
        with zipped.open('rustfs') as source, binary.open('wb') as target:
            shutil.copyfileobj(source, target)
    binary.chmod(0o755)
    print(f'RustFS: {binary}')


if __name__ == '__main__':
    main()
