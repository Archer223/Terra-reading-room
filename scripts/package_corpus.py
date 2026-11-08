#!/usr/bin/env python3
"""Package the explicitly provided corpus into reproducible, verified Git blobs."""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNK_SIZE = 2 * 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    source = ROOT / 'corpus/provided'
    raw_manifest = (source / 'manifest.json').read_bytes()
    manifest = json.loads(raw_manifest)
    names = {'manifest.json'}
    for item in manifest['bodies'].values():
        name = item['file']
        if not re.fullmatch(r'[0-9a-f]{24}\.json', name):
            raise ValueError('Unexpected corpus filename')
        if sha((source / name).read_bytes()) != item['sha256']:
            raise ValueError('Corpus checksum mismatch: ' + name)
        names.add(name)
    temporary = ROOT / '.local/provided-corpus.tar.gz'
    temporary.parent.mkdir(exist_ok=True)
    with temporary.open('wb') as output:
        with gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as archive:
                for name in sorted(names):
                    path = source / name
                    info = archive.gettarinfo(str(path), arcname=name)
                    info.uid = info.gid = 0
                    info.uname = info.gname = ''
                    info.mtime = 0
                    info.mode = 0o644
                    info.pax_headers = {}
                    with path.open('rb') as content:
                        archive.addfile(info, content)
    destination = ROOT / 'corpus/archives'
    destination.mkdir(parents=True, exist_ok=True)
    parts = []
    digest = hashlib.sha256()
    with temporary.open('rb') as bundle:
        while data := bundle.read(CHUNK_SIZE):
            name = f'provided-{len(parts):03d}.part'
            (destination / name).write_bytes(data)
            parts.append({'file': name, 'bytes': len(data), 'sha256': sha(data)})
            digest.update(data)
    expected = {item['file'] for item in parts}
    for path in destination.glob('provided-*.part'):
        if re.fullmatch(r'provided-\d{3}\.part', path.name) and path.name not in expected:
            path.unlink()
    receipt = {'format': 'tar.gz.parts.v1', 'bodies': len(manifest['bodies']),
               'cutoff': manifest.get('cutoff'), 'source_manifest_sha256': sha(raw_manifest),
               'sha256': digest.hexdigest(), 'parts': parts}
    (destination / 'manifest.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"Packaged {receipt['bodies']} stories into {len(parts)} verified parts ({temporary.stat().st_size / 1024**2:.1f} MiB).")


if __name__ == '__main__':
    main()
