"""Scenario tests against the real Parquet exports (backend/data). Run from backend/: .venv/bin/pytest -q"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def post(client, **body):
    r = client.post("/api/recommend", json=body)
    assert r.status_code == 200
    return r.json()


def test_darbhanga_dialysis_cited_and_near(client):
    r = post(client, service="dialysis", location="Darbhanga, Bihar")
    assert r["status"] == "ok"
    recs = r["recommendations"]
    assert len(recs) == 3 and len({x["facility_id"] for x in recs}) == 3
    assert [x["tier"] for x in recs] == ["best_balanced", "nearest_verified", "highest_confidence"]
    assert recs[0]["distance_km"] < 10
    assert all(x["citations"] for x in recs), "every recommendation cites text"
    counts = [s["count"] for s in r["funnel"]]
    assert counts == sorted(counts, reverse=True), "funnel only narrows"
    assert r["elapsed_ms"] < 500


def test_nanded_csection_is_a_care_desert(client):
    r = post(client, service="emergency c-section", location="Nanded", urgency="emergency")
    assert r["medical_desert_alert"]["triggered"]
    assert r["recommendations"] == []
    far = r["nearest_beyond_radius"]
    assert far and far[0]["distance_km"] == min(x["distance_km"] for x in far)
    assert any("no direct evidence" in x["reasons"][0] for x in r["skipped_nearby"])
    assert "could not find" in r["spoken_summary"]


def test_gates_hold_under_any_weights(client):
    r = post(client, service="nicu", location="Lucknow", weights={"proximity": 1, "evidence": 0, "trust": 0, "depth": 0})
    for x in r["recommendations"] + r["ranked"]:
        assert x["score_breakdown"]["raw"]["trust_score"] >= 0.5
        assert x["score_breakdown"]["raw"]["type_fit"] >= 0.5
        assert x["citations"]


def test_pin_and_coordinates(client):
    assert post(client, service="mri", location="302001")["query"]["location"]["kind"] == "pin"
    r = post(client, service="trauma", location={"lat": 27.18, "lon": 78.02}, urgency="emergency")
    assert r["query"]["location"]["kind"] == "coordinates" and "your location" in r["spoken_summary"]


def test_ambiguous_place_asks(client):
    r = post(client, service="dialysis", location="Aurangabad")
    assert r["status"] == "needs_clarification"
    assert {o["state"] for o in r["options"]} >= {"Bihar", "Maharashtra"}


def test_unknown_service_and_place(client):
    assert post(client, service="quantum healing", location="Patna")["status"] == "unknown_service"
    assert post(client, service="dialysis", location="Xyzzyville")["status"] == "unresolved_location"


def test_free_text_service(client):
    r = post(client, service="kidney machine", location="Patna, Bihar")
    assert r["query"]["service"]["key"] == "dialysis"


def test_broadcast_reaches_websocket(client):
    with client.websocket_connect("/ws/live") as ws:
        post(client, service="dialysis", location="Patna, Bihar", broadcast_to_ui=True, source="voice")
        msg = ws.receive_json()
        while msg.get("payload", {}).get("query", {}).get("location", {}).get("input") != "Patna, Bihar":
            msg = ws.receive_json()
        assert msg["type"] == "recommendation" and msg["source"] == "voice"


def test_locality_with_city_qualifier(client):
    r = post(client, service="dialysis", location="Bandra, Mumbai")
    assert r["status"] == "ok" and "Bandra" in r["query"]["location"]["display_name"]
    assert r["query"]["location"]["is_precise"]
    assert post(client, service="dialysis", location="Koramangala")["status"] == "ok"
    assert post(client, service="dialysis", location="Patna")["status"] == "ok"  # villages named Patna don't compete


def test_big_city_asks_for_more_detail(client):
    r = post(client, service="dialysis", location="Mumbai")
    assert r["query"]["location"]["ask_for_more_detail"]
    assert "PIN code" in r["spoken_summary"]
    assert not post(client, service="dialysis", location="400053")["query"]["location"]["ask_for_more_detail"]


def test_audience_summaries_share_the_same_facts(client):
    body = dict(service="dialysis", location="Darbhanga, Bihar")
    prov, pat = post(client, audience="provider", **body), post(client, audience="patient", **body)
    assert prov["recommendations"] == pat["recommendations"], "audience changes wording only, never the ranking"
    top = prov["recommendations"][0]["name"]
    assert top in prov["spoken_summary"] and top in pat["spoken_summary"]
    assert "confidence" in prov["spoken_summary"] and "Second" in prov["spoken_summary"]
    assert len(pat["spoken_summary"].split()) < len(prov["spoken_summary"].split())
    em = post(client, service="trauma", location="Lucknow", urgency="emergency", audience="patient")
    assert em["spoken_summary"].startswith("If this is life-threatening, call 108")
