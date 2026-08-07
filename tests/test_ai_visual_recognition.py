from hashlib import sha256
from pathlib import Path

import httpx

from app.api import routes
from app.core.config import settings
from app.models import (
    AuditLog,
    InventoryTransaction,
    OrganizationUsagePeriod,
    PartRecognitionAnalysis,
    PartRecognitionObservation,
)
from app.services.visual_recognition import (
    VisionAPIResult,
    VisionAnalysisResult,
    VisionConfigurationError,
    VisionPartHint,
    VisionRequestError,
    request_visual_analysis,
    require_vision_configuration,
)


PNG = b"\x89PNG\r\n\x1a\n" + b"ai-visual-recognition"


def _stored_image_path(client, observation_id: int) -> Path:
    with client.app.state.testing_session_local() as db:
        reference = db.get(PartRecognitionObservation, observation_id).image_url
    if reference.startswith("private:"):
        return Path(settings.data_export_private_files_root) / reference.removeprefix("private:")
    return Path(settings.data_export_public_files_root) / reference.removeprefix("/uploads/")


def _enable_vision(monkeypatch):
    monkeypatch.setattr(settings, "vision_recognition_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-" + "x" * 32)
    monkeypatch.setattr(settings, "openai_api_base_url", "https://api.openai.com")
    monkeypatch.setattr(settings, "vision_recognition_model", "gpt-5.6-terra")
    monkeypatch.setattr(settings, "vision_recognition_image_detail", "original")


def _create_observation(client, **data):
    response = client.post(
        "/api/parts/recognition/candidates",
        data=data,
        files={"file": ("part.png", PNG, "image/png")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _fake_result(part_id: int, part_number: str) -> VisionAPIResult:
    output = VisionAnalysisResult(
        visible_label_text=f"RELAY {part_number}",
        manufacturer="ACME",
        machine_model="ACME-9000",
        visual_description="A black compressor relay with a printed label.",
        part_hints=[
            VisionPartHint(
                catalog_part_id=part_id,
                part_number=part_number,
                name="Compressor relay",
                confidence=0.93,
                reason="The printed part number matches the tenant catalog.",
            )
        ],
    )
    return VisionAPIResult(
        analysis=output,
        request_id="req_visual_success",
        request_sha256="a" * 64,
        output_sha256="b" * 64,
    )


def test_ai_photo_analysis_is_audited_idempotent_and_human_controlled(
    client, monkeypatch
):
    _enable_vision(monkeypatch)
    part = client.post(
        "/api/parts",
        json={
            "part_number": "OCR-RELAY-42",
            "name": "Compressor relay",
            "machine_type": "ACME-9000",
        },
    ).json()
    observation = _create_observation(client)
    assert observation["analysis_status"] == "not_requested"
    assert observation["analysis_version"] == 0
    assert observation["candidates"] == []
    assert observation["can_analyze"] is True

    monkeypatch.setattr(
        routes,
        "request_visual_analysis",
        lambda **_kwargs: _fake_result(part["id"], part["part_number"]),
    )
    analyzed = client.post(
        f"/api/parts/recognition/observations/{observation['id']}/analyze",
        json={
            "client_request_id": "phone-photo-attempt-0001",
            "expected_analysis_version": 0,
        },
    )
    assert analyzed.status_code == 200, analyzed.text
    payload = analyzed.json()
    assert payload["analysis_status"] == "succeeded"
    assert payload["analysis_version"] == 1
    assert payload["latest_analysis"]["status"] == "succeeded"
    assert payload["latest_analysis"]["provider"] == "openai"
    assert payload["latest_analysis"]["external_request_id"] == "req_visual_success"
    assert payload["latest_analysis"]["result_json"]["manufacturer"] == "ACME"
    assert payload["candidates"][0]["part_id"] == part["id"]
    assert "vision model selected" in payload["candidates"][0]["reason"]
    assert payload["candidates"][0]["status"] == "ai_candidate"
    assert payload["can_analyze"] is True

    repeated = client.post(
        f"/api/parts/recognition/observations/{observation['id']}/analyze",
        json={
            "client_request_id": "phone-photo-attempt-0001",
            "expected_analysis_version": 0,
        },
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["analysis_version"] == 1

    with client.app.state.testing_session_local() as db:
        attempt = db.query(PartRecognitionAnalysis).one()
        assert attempt.image_sha256 == sha256(PNG).hexdigest()
        assert attempt.output_sha256 == "b" * 64
        assert attempt.candidate_count == 1
        usage = db.query(OrganizationUsagePeriod).one()
        assert usage.ai_requests == 1
        assert db.query(InventoryTransaction).count() == 0
        actions = {
            row.action
            for row in db.query(AuditLog)
            .filter(AuditLog.entity_type == "part_recognition_analysis")
            .all()
        }
        assert actions == {
            "part_recognition_analysis_started",
            "part_recognition_analysis_succeeded",
        }

    candidate = payload["candidates"][0]
    confirmed = client.post(
        f"/api/parts/recognition/candidates/{candidate['id']}/actions",
        json={"action": "employee_confirm", "expected_version": candidate["version"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    blocked = client.post(
        f"/api/parts/recognition/observations/{observation['id']}/analyze",
        json={
            "client_request_id": "phone-photo-attempt-0002",
            "expected_analysis_version": 1,
        },
    )
    assert blocked.status_code == 409
    assert "human confirmation" in blocked.text
    _stored_image_path(client, observation["id"]).unlink()


def test_ai_failure_preserves_safe_evidence_and_can_retry(client, monkeypatch):
    _enable_vision(monkeypatch)
    part = client.post(
        "/api/parts",
        json={"part_number": "RETRY-PART-1", "name": "Retry relay"},
    ).json()
    observation = _create_observation(client)

    def fail(**_kwargs):
        raise VisionRequestError(503, "openai_unavailable", "req_visual_failed")

    monkeypatch.setattr(routes, "request_visual_analysis", fail)
    failed = client.post(
        f"/api/parts/recognition/observations/{observation['id']}/analyze",
        json={
            "client_request_id": "phone-photo-failure-0001",
            "expected_analysis_version": 0,
        },
    )
    assert failed.status_code == 503
    assert "openai_unavailable" in failed.text

    listed = client.get("/api/parts/recognition/candidates").json()[0]
    assert listed["analysis_status"] == "failed"
    assert listed["analysis_version"] == 1
    assert listed["latest_analysis"]["failure_code"] == "openai_unavailable"
    assert listed["latest_analysis"]["result_json"] is None
    assert listed["can_analyze"] is True

    monkeypatch.setattr(
        routes,
        "request_visual_analysis",
        lambda **_kwargs: _fake_result(part["id"], part["part_number"]),
    )
    retried = client.post(
        f"/api/parts/recognition/observations/{observation['id']}/analyze",
        json={
            "client_request_id": "phone-photo-retry-0002",
            "expected_analysis_version": 1,
        },
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["analysis_version"] == 2
    with client.app.state.testing_session_local() as db:
        attempts = db.query(PartRecognitionAnalysis).order_by(
            PartRecognitionAnalysis.attempt_number
        ).all()
        assert [row.status for row in attempts] == ["failed", "succeeded"]
        assert db.query(OrganizationUsagePeriod).one().ai_requests == 2
    _stored_image_path(client, observation["id"]).unlink()


def test_disabled_ai_does_not_consume_quota(client, monkeypatch):
    monkeypatch.setattr(settings, "vision_recognition_enabled", False)
    observation = _create_observation(client)
    config = client.get("/api/parts/recognition/config")
    assert config.status_code == 200
    assert config.json()["available"] is False
    denied = client.post(
        f"/api/parts/recognition/observations/{observation['id']}/analyze",
        json={
            "client_request_id": "disabled-photo-attempt",
            "expected_analysis_version": 0,
        },
    )
    assert denied.status_code == 503
    with client.app.state.testing_session_local() as db:
        assert db.query(PartRecognitionAnalysis).count() == 0
        assert db.query(OrganizationUsagePeriod).count() == 0
        row = db.get(PartRecognitionObservation, observation["id"])
        assert row.analysis_status == "not_requested"
    _stored_image_path(client, observation["id"]).unlink()


def test_work_order_ai_analysis_requires_claim_owner_bound_phone_and_version(
    client, monkeypatch
):
    _enable_vision(monkeypatch)
    password = "visual-analysis-security-password"
    owner = client.post(
        "/api/users",
        json={
            "name": "analysis-owner",
            "email": "analysis-owner@example.com",
            "role": "engineer",
            "password": password,
        },
    ).json()
    other = client.post(
        "/api/users",
        json={
            "name": "analysis-other",
            "email": "analysis-other@example.com",
            "role": "engineer",
            "password": password,
        },
    ).json()
    part = client.post(
        "/api/parts",
        json={"part_number": "PHONE-BOUND-1", "name": "Phone-bound relay"},
    ).json()
    work_order = client.post(
        "/api/work-orders",
        json={
            "ticket_number": "VISION-PHONE-WO",
            "engineer_id": owner["id"],
            "assigned_user_id": owner["id"],
        },
    ).json()

    monkeypatch.setattr(settings, "rbac_enforce", True)
    monkeypatch.setattr(settings, "legacy_header_auth", True)

    def login(user, device_id, token):
        response = client.post(
            "/api/auth/login",
            data={"username": user["email"], "password": password},
            headers={
                "X-Device-Id": device_id,
                "X-Device-Token": token,
                "X-Device-Name": device_id,
            },
        )
        assert response.status_code == 200, response.text
        return {
            "Authorization": f"Bearer {response.json()['access_token']}",
            "X-Device-Token": token,
        }

    owner_headers = login(owner, "analysis-owner-phone", "c" * 64)
    other_headers = login(other, "analysis-other-phone", "d" * 64)
    claimed = client.post(
        f"/api/work-orders/{work_order['id']}/claim",
        headers=owner_headers,
    )
    assert claimed.status_code == 200, claimed.text
    claim_version = str(claimed.json()["claim_version"])
    owner_claim_headers = {**owner_headers, "X-Claim-Version": claim_version}
    created = client.post(
        "/api/parts/recognition/candidates",
        headers=owner_claim_headers,
        data={"work_order_id": str(work_order["id"])},
        files={"file": ("phone-bound.png", PNG, "image/png")},
    )
    assert created.status_code == 200, created.text
    observation = created.json()
    monkeypatch.setattr(
        routes,
        "request_visual_analysis",
        lambda **_kwargs: _fake_result(part["id"], part["part_number"]),
    )
    request = {
        "client_request_id": "phone-bound-attempt-0001",
        "expected_analysis_version": 0,
    }
    denied_other = client.post(
        f"/api/parts/recognition/observations/{observation['id']}/analyze",
        headers={**other_headers, "X-Claim-Version": claim_version},
        json=request,
    )
    assert denied_other.status_code == 403
    missing_version = client.post(
        f"/api/parts/recognition/observations/{observation['id']}/analyze",
        headers=owner_headers,
        json=request,
    )
    assert missing_version.status_code == 428
    analyzed = client.post(
        f"/api/parts/recognition/observations/{observation['id']}/analyze",
        headers=owner_claim_headers,
        json=request,
    )
    assert analyzed.status_code == 200, analyzed.text
    assert analyzed.json()["candidates"][0]["part_id"] == part["id"]
    _stored_image_path(client, observation["id"]).unlink()


def test_openai_request_uses_private_key_image_input_and_strict_schema(monkeypatch):
    _enable_vision(monkeypatch)
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        output = {
            "visible_label_text": "PART-1",
            "manufacturer": "ACME",
            "machine_model": "MODEL-1",
            "visual_description": "A service part.",
            "part_hints": [],
        }
        return httpx.Response(
            200,
            headers={"x-request-id": "req_contract"},
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": __import__("json").dumps(output)}
                        ],
                    }
                ],
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    result = request_visual_analysis(
        image_data=PNG,
        media_type="image/png",
        machine_model=None,
        label_text=None,
        notes=None,
        catalog=[],
        client_request_id="contract-attempt-0001",
    )
    assert result.request_id == "req_contract"
    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["json"]["store"] is False
    image_input = captured["json"]["input"][0]["content"][1]
    assert image_input["type"] == "input_image"
    assert image_input["image_url"].startswith("data:image/png;base64,")
    assert image_input["detail"] == "original"
    output_format = captured["json"]["text"]["format"]
    assert output_format["type"] == "json_schema"
    assert output_format["strict"] is True
    assert output_format["schema"]["additionalProperties"] is False
    assert settings.openai_api_key not in str(captured["json"])
    assert captured["headers"]["Authorization"].endswith(settings.openai_api_key)

    monkeypatch.setattr(settings, "openai_api_base_url", "https://example.com")
    try:
        require_vision_configuration()
    except VisionConfigurationError as exc:
        assert "api.openai.com" in str(exc)
    else:
        raise AssertionError("Non-OpenAI API base URL should be rejected")
