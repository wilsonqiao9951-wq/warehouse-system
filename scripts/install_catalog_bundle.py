"""Restore the versioned public catalog; never extract operational data."""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def allowed_path(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        not path.is_absolute()
        and '..' not in path.parts
        and (name in {'parts_index.json', 'manuals_index.json'} or
             len(path.parts) == 3 and path.parts[:2] in
             {('data', 'organized'), ('data', 'verification')} and path.suffix == '.json')
    )


def install(root: Path = ROOT, bundle_relative: str = 'catalog-bundle') -> int:
    bundle = root / bundle_relative
    manifest = json.loads((bundle / 'manifest.json').read_text())
    archive = bytearray()
    for chunk in manifest['chunks']:
        name = chunk['name']
        if PurePosixPath(name).name != name or not name.endswith('.b64'):
            raise ValueError('Invalid bundle chunk path')
        encoded = (bundle / name).read_bytes()
        if hashlib.sha256(encoded).hexdigest() != chunk['sha256']:
            raise ValueError(f'Bundle chunk checksum mismatch: {name}')
        archive.extend(base64.b64decode(encoded, validate=True))
    if hashlib.sha256(archive).hexdigest() != manifest['archive_sha256']:
        raise ValueError('Catalog archive checksum mismatch')
    expected = {row['path']: row['sha256'] for row in manifest['files']}
    if len(expected) != len(manifest['files']) or not all(allowed_path(p) for p in expected):
        raise ValueError('Invalid catalog manifest paths')
    # Validate every member and existing destination before writing anything.
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
        members = tar.getmembers()
        if len(members) != len(expected) or {m.name for m in members} != set(expected):
            raise ValueError('Unexpected catalog archive members')
        for member in members:
            if not member.isfile() or not allowed_path(member.name):
                raise ValueError('Only public catalog JSON files may be restored')
            target = root / member.name
            if any(parent.is_symlink() for parent in [target, *target.parents]):
                raise ValueError('Refusing symbolic link destination')
            payload = tar.extractfile(member).read()
            if hashlib.sha256(payload).hexdigest() != expected[member.name]:
                raise ValueError(f'Catalog checksum mismatch: {member.name}')
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != expected[member.name]:
                raise ValueError(f'Existing catalog differs: {member.name}; move it aside explicitly first')
        for member in members:
            target = root / member.name
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tar.extractfile(member).read())
    extra = sum(install(root, 'catalog-bundle/'+family) for family in ('quest','abs','ed','md','df','db','icecombo','crewserve','selfserve','tj','wbk','series37','multiplex','lancer','cornelius','mccann','wunderbar','bargun') if (root/'catalog-bundle'/family/'manifest.json').exists()) if bundle_relative == 'catalog-bundle' else 0
    return len(expected) + extra


if __name__ == '__main__':
    print(f'Public catalog restored and verified: {install()} files')
