from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
import zipfile

from sqlalchemy import func, select

from app.core.config import settings
from app.models import AuditLog, Organization, WorkOrder, WorkOrderMedia
from app.services.data_exports import build_organization_data_export


PASSWORD = "work-order-media-password"
PNG = b"\x89PNG\r\n\x1a\nwork-order-media-evidence"
MP4 = b"\x00\x00\x00\x18ftypmp42work-order-video"


def _create_user(client, name: str, role: str) -> dict:
    response = client.post(
        "/api/users",
        json={
            "name": name,
            "email": f"{name}@work-order-media.test",
            "role": role,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _login(
    client,
    user: dict,
    *,
    device_id: str | None = None,
    device_token: str | None = None,
) -> dict[str, str]:
    login_headers: dict[str, str] = {}
    if device_id:
        assert device_token
        login_headers = {
            "X-Device-Id": device_id,
            "X-Device-Token": device_token,
            "X-Device-Name": device_id,
        }
    response = client.post(
        "/api/auth/login",
        data={"username": user["email"], "password": PASSWORD},
        headers=login_headers,
    )
    assert response.status_code == 200, response.text
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    if device_token:
        headers["X-Device-Token"] = device_token
    return headers


@contextmanager
def _enforced_rbac():
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    settings.rbac_enforce = True
    settings.legacy_header_auth = True
    try:
        yield
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy


def _upload(
    client,
    work_order_id: int,
    headers: dict[str, str],
    *,
    request_id: str,
    data: bytes = PNG,
    filename: str = "field.png",
    category: str = "before",
    caption: str = "Arrival condition documented",
):
    return client.post(
        f"/api/work-orders/{work_order_id}/media",
        headers=headers,
        data={
            "category": category,
            "caption": caption,
            "client_request_id": request_id,
        },
        files={"file": (filename, data, "application/octet-stream")},
    )


def test_work_order_media_owner_device_visibility_idempotency_and_integrity(
    client,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        settings,
        "data_export_private_files_root",
        str(tmp_path / "private"),
    )
    admin = _create_user(client, "media-admin", "admin")
    manager = _create_user(client, "media-manager", "manager")
    warehouse = _create_user(client, "media-warehouse", "warehouse")
    owner = _create_user(client, "media-owner", "engineer")
    other_engineer = _create_user(client, "media-other", "engineer")
    work_order_response = client.post(
        "/api/work-orders",
        json={"ticket_number": "MEDIA-OWNER-1", "status": "open"},
    )
    assert work_order_response.status_code == 200
    work_order = work_order_response.json()

    with _enforced_rbac():
        admin_headers = _login(client, admin)
        manager_headers = _login(client, manager)
        warehouse_headers = _login(client, warehouse)
        owner_headers = _login(
            client,
            owner,
            device_id="media-owner-phone",
            device_token="a" * 64,
        )
        other_headers = _login(
            client,
            other_engineer,
            device_id="media-other-phone",
            device_token="b" * 64,
        )
        claimed = client.post(
            f"/api/work-orders/{work_order['id']}/claim",
            headers=owner_headers,
        )
        assert claimed.status_code == 200, claimed.text
        write_headers = {
            **owner_headers,
            "X-Claim-Version": str(claimed.json()["claim_version"]),
        }

        created = _upload(
            client,
            work_order["id"],
            write_headers,
            request_id="media-owner-request-0001",
            filename="../customer-site.png",
        )
        assert created.status_code == 200, created.text
        media = created.json()
        assert media["category"] == "before"
        assert media["media_type"] == "photo"
        assert media["mime_type"] == "image/png"
        assert media["size_bytes"] == len(PNG)
        assert media["file_sha256"] == sha256(PNG).hexdigest()
        assert media["created_by"] == owner["id"]
        assert media["claim_version"] == claimed.json()["claim_version"]
        assert "media_storage_key" not in media

        exact_retry = _upload(
            client,
            work_order["id"],
            write_headers,
            request_id="media-owner-request-0001",
            filename="../customer-site.png",
        )
        assert exact_retry.status_code == 200
        assert exact_retry.json()["id"] == media["id"]
        conflicting_retry = _upload(
            client,
            work_order["id"],
            write_headers,
            request_id="media-owner-request-0001",
            filename="../customer-site.png",
            category="damage",
        )
        assert conflicting_retry.status_code == 409

        assert _upload(
            client,
            work_order["id"],
            {**other_headers, "X-Claim-Version": str(claimed.json()["claim_version"])},
            request_id="media-other-request-0001",
        ).status_code == 403
        assert _upload(
            client,
            work_order["id"],
            manager_headers,
            request_id="media-manager-request-0001",
        ).status_code == 403
        assert _upload(
            client,
            work_order["id"],
            warehouse_headers,
            request_id="media-warehouse-request-0001",
        ).status_code == 403
        admin_created = _upload(
            client,
            work_order["id"],
            admin_headers,
            request_id="media-admin-request-0001",
            category="arrival",
            caption="Administrator evidence",
        )
        assert admin_created.status_code == 200, admin_created.text
        assert admin_created.json()["created_by"] == admin["id"]
        assert admin_created.json()["created_device_id"] is None

        for headers in (
            admin_headers,
            manager_headers,
            warehouse_headers,
            owner_headers,
            other_headers,
        ):
            listed = client.get(
                f"/api/work-orders/{work_order['id']}/media",
                headers=headers,
            )
            assert listed.status_code == 200, listed.text
            assert {row["id"] for row in listed.json()} == {
                media["id"],
                admin_created.json()["id"],
            }

        peer_list = client.get(
            f"/api/work-orders/{work_order['id']}/media",
            headers=other_headers,
        ).json()
        owner_row_for_peer = next(row for row in peer_list if row["id"] == media["id"])
        assert owner_row_for_peer["created_by"] == owner["id"]
        assert owner_row_for_peer["created_device_id"] is None
        assert owner_row_for_peer["original_filename"] is None

        owner_list = client.get(
            f"/api/work-orders/{work_order['id']}/media",
            headers=owner_headers,
        ).json()
        owner_row_for_owner = next(row for row in owner_list if row["id"] == media["id"])
        assert owner_row_for_owner["created_device_id"] is not None
        assert owner_row_for_owner["original_filename"] == "customer-site.png"

        content = client.get(media["content_url"], headers=other_headers)
        assert content.status_code == 200
        assert content.content == PNG
        assert content.headers["content-type"] == "image/png"
        assert content.headers["cache-control"] == "private, no-store"
        assert content.headers["x-content-type-options"] == "nosniff"
        assert "customer-site" not in content.headers["content-disposition"]
        assert client.get(media["content_url"]).status_code == 401

    with client.app.state.testing_session_local() as db:
        stored = db.get(WorkOrderMedia, media["id"])
        assert stored is not None
        assert stored.original_filename == "customer-site.png"
        assert stored.media_storage_key.startswith(
            f"work-order-media/1/{work_order['id']}/"
        )
        assert db.scalar(select(func.count(WorkOrderMedia.id))) == 2
        audit = db.scalar(
            select(AuditLog)
            .where(
                AuditLog.entity_type == "work_order_media",
                AuditLog.entity_id == media["id"],
            )
            .order_by(AuditLog.id.desc())
        )
        assert audit is not None
        assert "Arrival condition" not in audit.metadata_json
        assert "customer-site" not in audit.metadata_json
        assert "media_storage_key" not in audit.metadata_json
        target = tmp_path / "private" / stored.media_storage_key
        assert target.read_bytes() == PNG
        target.write_bytes(b"tampered")
        assert client.get(f"/uploads/{stored.media_storage_key}").status_code == 404

    with _enforced_rbac():
        owner_headers = _login(
            client,
            owner,
            device_id="media-owner-phone",
            device_token="a" * 64,
        )
        assert client.get(media["content_url"], headers=owner_headers).status_code == 409


def test_work_order_media_video_photo_completion_freeze_and_portable_export(
    client,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        settings,
        "data_export_private_files_root",
        str(tmp_path / "private"),
    )
    work_order = client.post(
        "/api/work-orders",
        json={"ticket_number": "MEDIA-COMPLETION-1", "status": "open"},
    ).json()
    policy = client.post(
        "/api/completion-policies",
        json={"require_completion_photo": True},
    )
    assert policy.status_code == 200

    invalid = _upload(
        client,
        work_order["id"],
        {},
        request_id="media-invalid-request-0001",
        data=b"not-media",
        filename="fake.jpg",
    )
    assert invalid.status_code == 400
    unknown_category = _upload(
        client,
        work_order["id"],
        {},
        request_id="media-unknown-request-0001",
        category="secret",
    )
    assert unknown_category.status_code == 422
    configured_limit = settings.max_knowledge_media_upload_bytes
    monkeypatch.setattr(settings, "max_knowledge_media_upload_bytes", len(PNG) - 1)
    oversized = _upload(
        client,
        work_order["id"],
        {},
        request_id="media-oversized-request-0001",
    )
    assert oversized.status_code == 413
    monkeypatch.setattr(settings, "max_knowledge_media_upload_bytes", configured_limit)
    video = _upload(
        client,
        work_order["id"],
        {},
        request_id="media-video-request-0001",
        data=MP4,
        filename="repair.mov",
        category="during",
        caption="Repair sequence",
    )
    assert video.status_code == 200, video.text
    assert video.json()["media_type"] == "video"
    assert video.json()["mime_type"] == "video/mp4"

    video_only_completion = client.post(
        f"/api/work-orders/{work_order['id']}/complete",
        json={},
    )
    assert video_only_completion.status_code == 422
    assert "completion_photo" in video_only_completion.text

    photo = _upload(
        client,
        work_order["id"],
        {},
        request_id="media-photo-request-0001",
        category="after",
        caption="Completed repair",
    )
    assert photo.status_code == 200, photo.text

    with client.app.state.testing_session_local() as db:
        organization = db.get(Organization, 1)
        bundle = build_organization_data_export(
            db,
            organization,
            include_files=True,
        )
        with zipfile.ZipFile(bundle.stream) as archive:
            rows = [
                json.loads(line)
                for line in archive.read("data/work_order_media.jsonl").splitlines()
            ]
            assert {row["id"] for row in rows} == {
                video.json()["id"],
                photo.json()["id"],
            }
            for row in rows:
                assert archive.read(f"files/private/{row['media_storage_key']}")
        bundle.stream.close()

    completed = client.post(
        f"/api/work-orders/{work_order['id']}/complete",
        json={},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["is_locked"] is True
    frozen = _upload(
        client,
        work_order["id"],
        {},
        request_id="media-frozen-request-0001",
        category="after",
    )
    assert frozen.status_code == 409


def test_work_order_media_cross_tenant_reads_fail_closed(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        settings,
        "data_export_private_files_root",
        str(tmp_path / "private"),
    )
    admin = _create_user(client, "media-tenant-admin", "admin")
    with client.app.state.testing_session_local() as db:
        other = Organization(name="Other media tenant", slug="other-media-tenant")
        db.add(other)
        db.flush()
        work_order = WorkOrder(
            organization_id=other.id,
            ticket_number="OTHER-MEDIA-1",
            wo_number="OTHER-MEDIA-1",
            status="open",
        )
        db.add(work_order)
        db.flush()
        row = WorkOrderMedia(
            organization_id=other.id,
            work_order_id=work_order.id,
            category="before",
            media_type="photo",
            mime_type="image/png",
            size_bytes=len(PNG),
            file_sha256=sha256(PNG).hexdigest(),
            request_fingerprint="f" * 64,
            media_storage_key=f"work-order-media/{other.id}/{work_order.id}/other.png",
            client_request_id="other-media-request-0001",
            claim_version=0,
        )
        db.add(row)
        db.commit()
        other_work_order_id = work_order.id
        other_media_id = row.id

    with _enforced_rbac():
        headers = _login(client, admin)
        assert client.get(
            f"/api/work-orders/{other_work_order_id}/media",
            headers=headers,
        ).status_code == 404
        assert client.get(
            f"/api/work-orders/{other_work_order_id}/media/{other_media_id}/content",
            headers=headers,
        ).status_code == 404
