"""Contract tests for POST /api/behavior-event.

The frontend's useBehaviorTracking hook posts here; until this route existed it
got a 404. The endpoint accepts + logs (no DB); policy-engine consumption is a
follow-up, so the tests lock the accepted contract and the validation rejects.
"""


def test_behavior_event_accepts_all_types(client):
    for event_type in ("replay", "skip", "listen"):
        r = client.post(
            "/api/behavior-event",
            json={"session_id": "11111111-1111-1111-1111-111111111111",
                  "event_type": event_type, "listen_time": 3.5},
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"status": "accepted"}


def test_behavior_event_listen_time_optional(client):
    r = client.post(
        "/api/behavior-event",
        json={"session_id": "s1", "event_type": "skip"},
    )
    assert r.status_code == 200, r.text


def test_behavior_event_rejects_bad_values(client):
    r = client.post("/api/behavior-event",
                    json={"session_id": "s1", "event_type": "rewind"})
    assert r.status_code == 422
    r = client.post("/api/behavior-event",
                    json={"session_id": "s1", "event_type": "listen",
                          "listen_time": -1})
    assert r.status_code == 422
    r = client.post("/api/behavior-event",
                    json={"event_type": "skip"})
    assert r.status_code == 422
