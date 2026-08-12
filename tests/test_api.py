import os

os.environ["WORKSPACE_TOKEN"] = "test-token"
os.environ["POSTCALL_WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["ELEVENLABS_API_KEY"] = ""

from fastapi.testclient import TestClient

import server.main as main


def make_client(tmp_path):
    main.DATA_DIR = tmp_path
    main.DB_FILE = tmp_path / "agent.db"

    main.init_db()

    return TestClient(main.app)


def auth_headers():
    return {
        "X-Workspace-Token": "test-token",
    }


def test_health(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_protected_endpoint_rejects_missing_token(tmp_path):
    client = make_client(tmp_path)

    response = client.post(
        "/tools/check-availability",
        json={
            "service": "consultation",
            "preferred_day": "Monday",
        },
    )

    assert response.status_code == 401


def test_valid_availability(tmp_path):
    client = make_client(tmp_path)

    response = client.post(
        "/tools/check-availability",
        headers=auth_headers(),
        json={
            "service": "consultation",
            "preferred_day": "Monday",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["found"] is True
    assert "Monday 10:00" in data["slots"]


def test_invalid_day_has_no_slots(tmp_path):
    client = make_client(tmp_path)

    response = client.post(
        "/tools/check-availability",
        headers=auth_headers(),
        json={
            "service": "consultation",
            "preferred_day": "Sunday",
        },
    )

    assert response.status_code == 200
    assert response.json()["found"] is False
    assert response.json()["slots"] == []


def test_invalid_slot_is_rejected(tmp_path):
    client = make_client(tmp_path)

    response = client.post(
        "/tools/book-appointment",
        headers=auth_headers(),
        json={
            "name": "Test User",
            "phone": "0500000000",
            "service": "consultation",
            "slot": "Friday 03:00",
            "language": "en",
            "notes": "Invalid slot test",
        },
    )

    assert response.status_code == 409

    detail = response.json()["detail"]

    assert detail["error"] == "invalid_slot"
    assert "message" in detail
    assert "available_slots" in detail
    assert "Friday 03:00" not in detail["available_slots"]


def test_duplicate_booking_is_rejected(tmp_path):
    client = make_client(tmp_path)

    payload = {
        "name": "First User",
        "phone": "0500000001",
        "service": "consultation",
        "slot": "Monday 10:00",
        "language": "en",
        "notes": "",
    }

    first = client.post(
        "/tools/book-appointment",
        headers=auth_headers(),
        json=payload,
    )

    assert first.status_code == 200
    assert first.json()["confirmed"] is True

    second_payload = {
        **payload,
        "name": "Second User",
        "phone": "0500000002",
    }

    second = client.post(
        "/tools/book-appointment",
        headers=auth_headers(),
        json=second_payload,
    )

    assert second.status_code == 409

    detail = second.json()["detail"]

    assert detail["error"] == "slot_already_booked"
    assert "message" in detail


def test_booked_slot_disappears_from_availability(tmp_path):
    client = make_client(tmp_path)

    booking = client.post(
        "/tools/book-appointment",
        headers=auth_headers(),
        json={
            "name": "Booked User",
            "phone": "0500000003",
            "service": "consultation",
            "slot": "Monday 10:00",
            "language": "en",
            "notes": "",
        },
    )

    assert booking.status_code == 200

    availability = client.post(
        "/tools/check-availability",
        headers=auth_headers(),
        json={
            "service": "consultation",
            "preferred_day": "Monday",
        },
    )

    assert availability.status_code == 200
    assert "Monday 10:00" not in availability.json()["slots"]


def test_analytics_requires_auth(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/analytics/summary")

    assert response.status_code == 401


def test_analytics_with_auth(tmp_path):
    client = make_client(tmp_path)

    response = client.get(
        "/analytics/summary",
        headers=auth_headers(),
    )

    assert response.status_code == 200

    data = response.json()

    assert "total_calls" in data
    assert "outcomes" in data
    assert "languages" in data