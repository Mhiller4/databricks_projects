"""WP1 web-app additions: LiveKit token endpoint, location type-ahead, /api/config,
session-tagged broadcasts. Offline: tokens are minted and decoded locally, no network."""

import base64
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app, token_limiter


@pytest.fixture()
def client():
    token_limiter.clear()
    with TestClient(app) as c:
        yield c
    token_limiter.clear()


@pytest.fixture()
def voice_env(monkeypatch):
    monkeypatch.setenv("LIVEKIT_URL", "wss://demo.example.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "test-secret-value-0123456789abcdef")


def _decode_jwt(token: str) -> dict:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def test_token_decodes_with_role_attributes_and_ttl(client, voice_env):
    r = client.post("/api/livekit/token", json={"role": "provider", "language": "en"})
    assert r.status_code == 200
    body = r.json()
    assert body["server_url"] == "wss://demo.example.livekit.cloud"
    assert body["room_name"].startswith("web-") and len(body["room_name"]) == 12
    assert body["identity"] == "web-user-" + body["room_name"][4:]
    claims = _decode_jwt(body["participant_token"])
    assert claims["sub"] == body["identity"]  # LiveKit carries the participant identity in `sub`
    assert claims["video"]["room"] == body["room_name"]
    assert claims["video"]["roomJoin"] is True
    assert claims["video"]["canPublish"] and claims["video"]["canSubscribe"] and claims["video"]["canPublishData"]
    assert claims["attributes"]["care_finder.role"] == "provider"
    assert claims["attributes"]["care_finder.language"] == "en"
    assert claims["exp"] - claims["nbf"] == 15 * 60
    # the secret never leaves the endpoint
    assert "test-secret-value" not in json.dumps(body) and "test-key" not in json.dumps(body)


def test_token_without_role_uses_empty_attribute(client, voice_env):
    body = client.post("/api/livekit/token", json={}).json()
    claims = _decode_jwt(body["participant_token"])
    assert claims["attributes"]["care_finder.role"] == ""
    assert claims["attributes"]["care_finder.language"] == ""


def test_token_unconfigured_is_503(client, monkeypatch):
    for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.delenv(k, raising=False)
    assert client.post("/api/livekit/token", json={}).status_code == 503


def test_token_rate_limited_after_ten(client, voice_env):
    codes = [client.post("/api/livekit/token", json={}).status_code for _ in range(12)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


def test_location_typeahead_from_two_characters(client):
    assert client.get("/api/locations", params={"q": "B"}).json() == []
    rows = client.get("/api/locations", params={"q": "Ban"}).json()
    assert 0 < len(rows) <= 8
    names = " | ".join(x["display_name"] for x in rows).lower()
    assert "bandra" in names or "bengaluru" in names or "bangalore" in names, names
    for x in rows:
        assert {"kind", "display_name", "district", "state", "lat", "lon", "precision", "is_precise"} <= set(x)
    # near-duplicates collapsed: no two same-named points
    bases = [x["display_name"].split(" (")[0].split(",")[0].lower() for x in rows]
    assert len(bases) == len(set(bases))


def test_location_typeahead_matches_pins(client):
    rows = client.get("/api/locations", params={"q": "8000"}).json()
    assert rows and all(x["kind"] == "pin" for x in rows)
    assert all("PIN 8000" in x["display_name"] for x in rows)
    assert len(rows) <= 8


def test_config_endpoint(client, monkeypatch):
    monkeypatch.delenv("CARE_FINDER_PHONE", raising=False)
    for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.delenv(k, raising=False)
    r = client.get("/api/config").json()
    assert set(r) >= {"phone_number", "services", "funnel_base", "livekit_enabled"}
    assert r["phone_number"] == ""
    assert r["livekit_enabled"] is False
    assert r["services"] and r["services"][0]["key"] and r["services"][0]["label"]
    assert r["funnel_base"]


def test_broadcast_is_tagged_with_session(client):
    with client.websocket_connect("/ws/live") as ws:
        r = client.post("/api/recommend", json={"service": "dialysis", "location": "Patna, Bihar",
                                                "broadcast_to_ui": True, "source": "voice", "session": "web-3f9a1c2e"})
        assert r.status_code == 200
        msg = ws.receive_json()
        while msg.get("session") != "web-3f9a1c2e":  # skip the pre-session last broadcast replayed on connect
            msg = ws.receive_json()
        assert msg["type"] == "recommendation" and msg["source"] == "voice"
        assert msg["session"] == "web-3f9a1c2e"
        assert msg["payload"]["status"] == "ok"
