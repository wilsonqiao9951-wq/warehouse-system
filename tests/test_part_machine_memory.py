def test_employee_photo_observation_is_remembered_by_machine(client):
    part = client.post("/api/parts", json={"part_number": "FILTER-1", "name": "Filter"}).json()
    first = client.post(
        "/api/parts/recognition/observations",
        data={"machine_model": "ACME-9000", "part_id": str(part["id"])},
    )
    assert first.status_code == 200
    second = client.post(
        "/api/parts/recognition/observations",
        data={"machine_model": "ACME-9000", "part_id": str(part["id"])},
    )
    assert second.status_code == 200
    assert second.json()["confirmed_count"] == 2
    suggestions = client.get("/api/parts/recognition/suggestions?machine_model=ACME-9000")
    assert suggestions.status_code == 200
    assert suggestions.json()[0]["part_id"] == part["id"]
