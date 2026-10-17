import base64
import hashlib
import io
import json
import tarfile

import pytest

from scripts.install_catalog_bundle import install


def bundle(root, name='parts_index.json', payload=b'[]', symlink=False):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as tar:
        member = tarfile.TarInfo(name)
        if symlink:
            member.type = tarfile.SYMTYPE
            member.linkname = '/etc/passwd'
            tar.addfile(member)
        else:
            member.size = len(payload)
            tar.addfile(member, io.BytesIO(payload))
    archive = buffer.getvalue()
    encoded = base64.b64encode(archive)
    output = root / 'catalog-bundle'
    output.mkdir()
    (output / 'catalog-000.b64').write_bytes(encoded)
    manifest = {'archive_sha256': hashlib.sha256(archive).hexdigest(),
                'chunks': [{'name': 'catalog-000.b64', 'sha256': hashlib.sha256(encoded).hexdigest()}],
                'files': [{'path': name, 'sha256': hashlib.sha256(payload).hexdigest()}]}
    (output / 'manifest.json').write_text(json.dumps(manifest))


def test_bundle_restores_clean_checkout_and_is_idempotent(tmp_path):
    bundle(tmp_path)
    assert install(tmp_path) == 1
    assert (tmp_path / 'parts_index.json').read_bytes() == b'[]'
    assert install(tmp_path) == 1


@pytest.mark.parametrize('name', ['../outside.json', '/parts_index.json', '.env', 'uploads/file.json'])
def test_bundle_rejects_unapproved_paths(tmp_path, name):
    bundle(tmp_path, name=name)
    with pytest.raises(ValueError):
        install(tmp_path)


def test_bundle_rejects_tar_symlinks(tmp_path):
    bundle(tmp_path, symlink=True)
    with pytest.raises(ValueError, match='Only public'):
        install(tmp_path)


def test_bundle_rejects_tampering_and_preserves_existing_data(tmp_path):
    bundle(tmp_path)
    (tmp_path / 'parts_index.json').write_bytes(b'keep me')
    with pytest.raises(ValueError, match='Existing catalog differs'):
        install(tmp_path)
    assert (tmp_path / 'parts_index.json').read_bytes() == b'keep me'
    (tmp_path / 'catalog-bundle/catalog-000.b64').write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='chunk checksum'):
        install(tmp_path)
