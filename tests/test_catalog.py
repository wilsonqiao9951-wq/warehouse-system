from sqlalchemy import select
from app.core.config import settings
from app.models import Organization, Part, InventoryTransaction
from app.services.catalog import entries


def test_catalog_search_and_pagination(client):
    response = client.get("/api/catalog/parts", params={"q": "3517028"})
    assert response.status_code == 200
    assert any(row["part_number"] == "3517028" for row in response.json()["items"])
    page = client.get("/api/catalog/manuals", params={"limit": 2}).json()
    assert len(page["items"]) == 2
    assert page["total"] == len(entries("manuals"))
    assert client.get("/api/catalog/parts?limit=101").status_code == 422


def test_catalog_requires_login(client):
    settings.rbac_enforce = True
    settings.legacy_header_auth = False
    assert client.get("/api/catalog/parts").status_code == 401
    assert client.get("/api/catalog/manuals").status_code == 401


def test_import_is_idempotent_and_preserves_inventory(client):
    row = next(row for row in entries("parts") if row["part_number"] == "3517028")
    path = f"/api/catalog/parts/{row['catalog_id']}/import"
    first = client.post(path)
    assert first.status_code == 200
    second = client.post(path)
    assert second.json()["id"] == first.json()["id"]
    assert first.json()["custom_fields"]["mycoke"]["cona_material_number"] == row["cona_material_number"]
    with client.app.state.testing_session_local() as db:
        assert len(db.scalars(select(Part)).all()) == 1
        assert db.scalars(select(InventoryTransaction)).all() == []


def test_import_permissions_and_tenant_scope(client):
    row = next(row for row in entries("parts") if row["part_number"] == "3517028")
    path = f"/api/catalog/parts/{row['catalog_id']}/import"
    with client.app.state.testing_session_local() as db:
        db.add(Organization(id=2, name="Other", slug="other"))
        db.add(Part(organization_id=2, part_number="3517028", name="Other tenant part"))
        db.commit()
    created = client.post("/api/users", json={"name": "Engineer", "email": "catalog@example.com", "role": "engineer", "password": "catalog-password"}).json()
    settings.rbac_enforce = True
    settings.legacy_header_auth = False
    token = client.post("/api/auth/login", data={"username": "catalog@example.com", "password": "catalog-password"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/catalog/parts", headers=headers).status_code == 200
    assert client.post(path, headers=headers).status_code == 403
    with client.app.state.testing_session_local() as db:
        from app.models import User, UserRole
        user = db.get(User, created["id"])
        user.role = UserRole.ADMIN
        db.commit()
    response = client.post(path, headers=headers)
    assert response.status_code == 200
    assert response.json()["organization_id"] == 1
    assert response.json()["name"] != "Other tenant part"


def test_verified_views_correct_links_and_separate_resource_entries(client):
    from app.services.catalog import entries
    motor = next(r for r in entries('parts') if r['part_number'] == '3508959')
    panel = next(r for r in entries('parts') if r['part_number'] == '3508178')
    assert '/product/3508959/3508959/' in motor['page_url']
    assert '/product/3508178/3508178/' in panel['page_url']
    assert motor['catalog_id'].startswith('60-')
    assert all(r['classification'] not in {'equipment','manual_section'} for r in entries('parts'))
    assert any(r['part_number'] == 'Automated Beverage System (ABS 2.0)' for r in entries('equipment'))
    assert any(r.get('manual_type') == 'parts_section' for r in entries('manuals'))
    assert client.get('/api/catalog/equipment').status_code == 200
    bad = next(r for r in entries('parts') if r['part_number'] == 'CCP 146652')
    assert bad['page_url'] is None
    assert client.post(f"/api/catalog/parts/{bad['catalog_id']}/import").status_code == 422


def test_catalog_generated_views_fail_closed_if_source_changes(tmp_path, monkeypatch):
    from app.services import catalog
    from pathlib import Path
    import json
    import pytest
    directory = tmp_path / 'data/organized'
    directory.mkdir(parents=True)
    (tmp_path / 'parts_index.json').write_text('[]')
    (directory / 'manifest.json').write_text(json.dumps({'sources': {'parts_index.json': {'sha256': 'wrong'}}}))
    catalog._catalogs.cache_clear()
    monkeypatch.setattr(catalog, 'DATA_ROOT', tmp_path)
    try:
        with pytest.raises(RuntimeError, match='Catalog sources changed'):
            catalog.entries('parts')
    finally:
        catalog._catalogs.cache_clear()
        catalog._search_rows.cache_clear()


def test_recovered_images_come_from_matched_source_products():
    import json
    from pathlib import Path
    from app.services.catalog import entries
    from scripts.audit_catalog import identifier
    recoveries = json.loads((Path(__file__).resolve().parents[1] / 'data/verification/image_recovery.json').read_text())
    indexed = {r['_organization']['source_index']: r for kind in ('parts','equipment','manuals') for r in entries(kind) if r['_organization']['source_file'] == 'parts_index.json'}
    assert recoveries
    for recovery in recoveries:
        row = indexed[recovery['source_index']]
        assert identifier(recovery['source_product_id']) == identifier(row['part_number'])
        assert row['image_url'] == recovery['patch']['image_url']
        assert any(c['url'] == row['image_url'] and c['http_status'] == 200 and c['content_type'].startswith('image/') for c in recovery['candidates'])
