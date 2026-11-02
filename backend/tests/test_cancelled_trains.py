# Cancelled-trains dropdown: parse_siv_payload unit tests + GET /api/trains cancelled_trains field
import os
import sys
from datetime import datetime

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from adif_siv import MADRID_TZ, parse_siv_payload  # noqa: E402

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "").rstrip("/")
NOW = MADRID_TZ.localize(datetime(2026, 11, 1, 22, 5))
FIELDS = {"scheduled_time", "day_label", "origin", "train_type", "train_number", "operator"}


def _train(number, arrival, status="cancelled", product="OUIGO", company="Ouigo", also=None, traffic="L"):
    return {
        "commercial_id": [{"numbers": [number] + (also or []), "product": product}],
        "company": company, "traffic_type": traffic, "class_stop": "destination", "status": status,
        "arrival_time": arrival, "delay_in": 0, "platform_in": "5", "origins": [{"code": "71801"}],
    }


def _payload(trains):
    return {"station_settings": {"code": "17000"}, "trains": trains,
            "stations": {"71801": {"name": ["Barcelona Sants"]}}, "station_alerts": []}


# Parser: day label, sorting, window, fields
def test_next_day_label_and_sorting():
    trains = [
        _train("06999", "2026-11-02T07:10:00+01:00"),   # tomorrow, within 12h
        _train("06535", "2026-11-01T23:23:00+01:00"),
        _train("06944", "2026-11-01T22:00:00+01:00"),   # 5 min ago -> still in window
    ]
    res = parse_siv_payload(_payload(trains), now=NOW)
    ct = res["cancelled_trains"]
    assert res["cancelled"] == len(ct) == 3
    assert [c["train_number"] for c in ct] == ["06944", "06535", "06999"]
    assert ct[2]["day_label"] == "mañana" and ct[2]["scheduled_time"] == "07:10"
    assert ct[0]["day_label"] == "" and ct[1]["day_label"] == ""
    assert ct[0]["origin"] == "Barcelona Sants" and ct[0]["operator"] == "Ouigo" and ct[0]["train_type"] == "OUIGO"
    assert not res["arrivals"]


def test_window_excludes_old_and_far_and_cercanias():
    trains = [
        _train("00001", "2026-11-01T21:00:00+01:00"),   # >30 min ago
        _train("00002", "2026-11-02T11:00:00+01:00"),   # >12h ahead
        _train("00003", "2026-11-01T22:30:00+01:00", traffic="C"),
        _train("00004", "2026-11-01T22:30:00+01:00", also=["00005"]),
        _train("00005", "2026-11-01T22:30:00+01:00"),  # coupled half
    ]
    res = parse_siv_payload(_payload(trains), now=NOW)
    assert [c["train_number"] for c in res["cancelled_trains"]] == ["00004"]
    assert res["cancelled"] == 1


# API: /api/trains exposes cancelled_trains consistent with cancelled_count
@pytest.fixture(scope="module")
def trains_data():
    if not BASE_URL:
        pytest.skip("no BASE_URL")
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"username": "admin", "password": "admin"}, timeout=20)
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"} if r.status_code == 200 else {}
    resp = requests.get(f"{BASE_URL}/api/trains", params={"shift": "all"}, headers=headers, timeout=60)
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.parametrize("station", ["atocha", "chamartin"])
def test_api_cancelled_trains_field(trains_data, station):
    s = trains_data[station]
    assert "cancelled_trains" in s and isinstance(s["cancelled_trains"], list)
    if s.get("source") != "siv":
        pytest.skip(f"{station} source is not siv right now")
    assert len(s["cancelled_trains"]) == s["cancelled_count"]
    for c in s["cancelled_trains"]:
        assert FIELDS <= set(c)
        assert "sched_iso" not in c
        assert len(c["scheduled_time"]) == 5 and c["scheduled_time"][2] == ":"
        assert c["day_label"] in ("", "mañana")
        assert c["train_number"] and c["train_type"]
