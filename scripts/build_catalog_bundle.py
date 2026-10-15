"""Package only allowlisted public catalog JSON; operational databases stay local."""
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def build():
    files = sorted({ROOT / 'parts_index.json', ROOT / 'manuals_index.json',
                    *(ROOT / 'data/organized').glob('*.json'),
                    *(ROOT / 'data/verification').glob('*.json')})
    output = ROOT / 'catalog-bundle'
    output.mkdir(exist_ok=True)
    buffer = io.BytesIO()
    inventory = []
    with gzip.GzipFile(fileobj=buffer, mode='wb', mtime=0, filename='') as gz:
        with tarfile.open(fileobj=gz, mode='w') as tar:
            for path in files:
                data = path.read_bytes()
                name = path.relative_to(ROOT).as_posix()
                member = tarfile.TarInfo(name)
                member.size = len(data)
                member.mode = 0o644
                tar.addfile(member, io.BytesIO(data))
                inventory.append({'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    archive = buffer.getvalue()
    chunks = []
    # Each base64 text file is below 1 MiB and can be transported by the connector.
    for offset in range(0, len(archive), 576 * 1024):
        name = f'catalog-{len(chunks):03d}.b64'
        data = base64.b64encode(archive[offset:offset + 576 * 1024])
        (output / name).write_bytes(data)
        chunks.append({'name': name, 'sha256': hashlib.sha256(data).hexdigest()})
    for stale in output.glob('catalog-*.b64'):
        if stale.name not in {c['name'] for c in chunks}:
            stale.unlink()
    manifest = {'format': 1, 'archive_sha256': hashlib.sha256(archive).hexdigest(),
                'archive_bytes': len(archive), 'chunks': chunks, 'files': inventory,
                'excluded': ['databases', 'uploads', 'credentials', 'HTML snapshots', 'frontend']}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(f'Bundled {len(files)} public JSON files in {len(chunks)} chunks ({len(archive)} compressed bytes)')


if __name__ == '__main__':
    build()
