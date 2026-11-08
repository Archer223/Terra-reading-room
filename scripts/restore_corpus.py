#!/usr/bin/env python3
"""Restore the committed story bundle without downloading external story text."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify(folder, receipt):
    raw = (folder / 'manifest.json').read_bytes()
    if sha(raw) != receipt['source_manifest_sha256']:
        raise ValueError('Corpus manifest checksum mismatch')
    manifest = json.loads(raw)
    if len(manifest['bodies']) != receipt['bodies']:
        raise ValueError('Corpus story count mismatch')
    for item in manifest['bodies'].values():
        if not re.fullmatch(r'[0-9a-f]{24}\.json', item['file']):
            raise ValueError('Unexpected corpus filename')
        if sha((folder / item['file']).read_bytes()) != item['sha256']:
            raise ValueError('Corpus checksum mismatch: ' + item['file'])


def main():
    archives = ROOT / 'corpus/archives'
    receipt = json.loads((archives / 'manifest.json').read_text(encoding='utf-8'))
    if receipt['format'] != 'tar.gz.parts.v1':
        raise ValueError('Unsupported corpus bundle format')
    destination = ROOT / 'corpus/provided'
    if destination.exists() and any(destination.iterdir()):
        verify(destination, receipt)
        print(f"Verified {receipt['bodies']} existing story files.")
        return
    destination.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryFile() as bundle:
        digest = hashlib.sha256()
        for item in receipt['parts']:
            if not re.fullmatch(r'provided-\d{3}\.part', item['file']):
                raise ValueError('Unexpected archive filename')
            data = (archives / item['file']).read_bytes()
            if len(data) != item['bytes'] or sha(data) != item['sha256']:
                raise ValueError('Archive part checksum mismatch: ' + item['file'])
            digest.update(data)
            bundle.write(data)
        if digest.hexdigest() != receipt['sha256']:
            raise ValueError('Combined archive checksum mismatch')
        bundle.seek(0)
        with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
            staging = Path(temporary) / 'provided'
            staging.mkdir()
            with tarfile.open(fileobj=bundle, mode='r:gz') as archive:
                seen = set()
                for member in archive:
                    if not member.isfile() or not re.fullmatch(r'(?:[0-9a-f]{24}|manifest)\.json', member.name) or member.name in seen:
                        raise ValueError('Unsafe or duplicate archive member')
                    seen.add(member.name)
                    with archive.extractfile(member) as source, (staging / member.name).open('wb') as output:
                        shutil.copyfileobj(source, output)
            verify(staging, receipt)
            if len(seen) != receipt['bodies'] + 1:
                raise ValueError('Unexpected archive file count')
            if destination.exists():
                destination.rmdir()
            staging.rename(destination)
    print(f"Restored and verified {receipt['bodies']} story files.")


if __name__ == '__main__':
    main()
