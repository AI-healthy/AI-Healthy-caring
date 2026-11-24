from datetime import timedelta

from test_users_health import HEALTH, NOW, account, client, consent, sample, upload  # noqa: F401

POLICY = "local-wearable-v1"


def real_consent(client, auth, metric="heart_rate_bpm", granted=True):
    return client.put(
        f"{HEALTH}/consents/health_connect/{metric}", headers=auth,
        json={"granted": granted, "policy_version": POLICY},
    )


def hr(**changes):
    return sample(
        client_sample_id="hc-hr-1", metric="heart_rate_bpm", value=72,
        interval_start=None, is_demo=False,
        data_origin="nodomain.freeyourgadget.gadgetbridge", **changes,
    )


def test_real_health_is_opt_in(client, monkeypatch):
    _, auth = account(client)
    monkeypatch.delenv("SHIYI_ENABLE_REAL_HEALTH", raising=False)
    assert real_consent(client, auth).status_code == 403
    assert upload(client, auth, hr()).status_code == 403
    monkeypatch.setenv("SHIYI_ENABLE_REAL_HEALTH", "1")
    assert consent(client, auth, metric="heart_rate_bpm").status_code == 200
    assert upload(client, auth, hr()).status_code == 403
    assert real_consent(client, auth).json()["policy_version"] == POLICY
    first = upload(client, auth, hr())
    assert first.status_code == 200, first.text
    assert upload(client, auth, hr()).json()["items"][0]["duplicate"]
    items = client.get(HEALTH + "/observations", headers=auth).json()["items"]
    assert items[0]["is_demo"] is False
    assert items[0]["data_origin"] == "nodomain.freeyourgadget.gadgetbridge"
    monkeypatch.delenv("SHIYI_ENABLE_REAL_HEALTH")
    assert real_consent(client, auth, granted=False).status_code == 200
    assert upload(client, auth, hr()).status_code == 403


def test_real_health_account_isolation_and_atomicity(client, monkeypatch):
    monkeypatch.setenv("SHIYI_ENABLE_REAL_HEALTH", "1")
    _, alice = account(client)
    _, bob = account(client, "bob")
    assert real_consent(client, alice).status_code == 200
    assert real_consent(client, {"Authorization": "Bearer development-token-123"}).status_code == 403
    steps = sample(is_demo=False, data_origin="nodomain.freeyourgadget.gadgetbridge")
    assert upload(client, alice, hr(), steps).status_code == 403
    assert client.get(HEALTH + "/observations", headers=alice).json()["items"] == []
    assert upload(client, alice, hr()).status_code == 200
    assert client.get(HEALTH + "/observations", headers=bob).json()["items"] == []
    assert upload(client, bob, hr()).status_code == 403
    assert real_consent(client, alice, "steps").status_code == 200
    assert upload(client, alice, steps).status_code == 200
    assert real_consent(client, alice, "sleep_minutes").status_code == 200
    sleep = sample(
        client_sample_id="sleep-1", metric="sleep_minutes", value=420,
        interval_start=(NOW - timedelta(hours=8)).isoformat(),
        is_demo=False, data_origin="nodomain.freeyourgadget.gadgetbridge",
    )
    assert upload(client, alice, sleep).status_code == 200


def test_provenance_validation(client, monkeypatch):
    monkeypatch.setenv("SHIYI_ENABLE_REAL_HEALTH", "1")
    _, auth = account(client)
    assert real_consent(client, auth).status_code == 200
    assert upload(client, auth, {**hr(), "data_origin": None}).status_code == 422
    assert upload(client, auth, {**hr(), "source": "demo"}).status_code == 422
    assert upload(client, auth, {**hr(), "is_demo": "false"}).status_code == 422
    assert upload(client, auth, {**hr(), "is_demo": True}).status_code == 422
