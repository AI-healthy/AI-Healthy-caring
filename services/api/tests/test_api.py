from fastapi.testclient import TestClient
from shiyi_api.main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["mode"] == "local_demo"


def test_recommendations_with_missing_observations():
    response = client.post(
        "/api/v1/recommendations",
        json={"context": {"available_minutes": 6}, "preference_tags": ["gentle"]},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["is_demo"] is True
    assert len(result["options"]) > 0
    assert all(x["duration_minutes"] <= 6 for x in result["options"])


def test_recommendations_do_not_infer_mood_from_heart_rate():
    response = client.post(
        "/api/v1/recommendations",
        json={"context": {"energy_level": 2, "available_minutes": 10}},
    )
    assert response.status_code == 200
    assert "疾病" in response.json()["explanation"]


def test_invalid_energy_fails_validation():
    response = client.post(
        "/api/v1/recommendations", json={"context": {"energy_level": 99}}
    )
    assert response.status_code == 422


def test_feedback_is_idempotent_in_demo_process():
    payload = {"activity_id": "stretch", "completed": True, "client_event_id": "test-unique-e1"}
    one = client.post("/api/v1/activities/feedback", json=payload)
    two = client.post("/api/v1/activities/feedback", json=payload)
    assert one.status_code == two.status_code == 200
    assert one.json()["duplicate"] is False
    assert two.json()["duplicate"] is True


def test_season_is_clearly_marked_demo():
    data = client.get("/api/v1/seasons/current").json()
    assert data["calendar_status"] == "sample_only"
    assert data["is_demo"] is True
