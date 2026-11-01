# Tests for POST /api/trains/siv-snapshot (driver-device relay of Adif SIV panels)
import os
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
URL = f"{BASE_URL}/api/trains/siv-snapshot"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"username": "admin", "password": "admin"}, timeout=30)
    if r.status_code != 200:
        pytest.skip("login failed")
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}"}


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "0Z"  # 7 fractional digits like Adif


def _payload(data_time, alerts=None):
    return {"station_settings": {"code": "60000", "data_time": data_time}, "trains": [], "stations": {},
            "station_alerts": alerts or []}


# Auth
def test_no_auth_401():
    r = requests.post(URL, json={"station_id": "60000", "payload": _payload(_iso(datetime.now(timezone.utc)))}, timeout=30)
    assert r.status_code == 401


# Validation
def test_invalid_station_400(h):
    r = requests.post(URL, json={"station_id": "99999", "payload": _payload(_iso(datetime.now(timezone.utc)))}, headers=h, timeout=30)
    assert r.status_code == 400
    assert "detail" in r.json()


def test_missing_payload_422(h):
    r = requests.post(URL, json={"station_id": "60000"}, headers=h, timeout=30)
    assert r.status_code == 422


def test_too_many_trains_413(h):
    p = _payload(_iso(datetime.now(timezone.utc)))
    p["trains"] = [{}] * 401
    r = requests.post(URL, json={"station_id": "60000", "payload": p}, headers=h, timeout=30)
    assert r.status_code == 413


def test_missing_data_time_rejected(h):
    r = requests.post(URL, json={"station_id": "60000", "payload": {"trains": []}}, headers=h, timeout=30)
    assert r.status_code == 200 and r.json() == {"accepted": False}


def test_bad_data_time_rejected(h):
    r = requests.post(URL, json={"station_id": "60000", "payload": _payload("not-a-date")}, headers=h, timeout=30)
    assert r.status_code == 200 and r.json() == {"accepted": False}


def test_stale_rejected(h):
    old = _iso(datetime.now(timezone.utc) - timedelta(minutes=6))
    r = requests.post(URL, json={"station_id": "60000", "payload": _payload(old)}, headers=h, timeout=30)
    assert r.status_code == 200 and r.json() == {"accepted": False}


# Duplicate: first accepted, second identical rejected. Keeps current alerts so the UI stays consistent.
def test_duplicate_rejected(h):
    cur = requests.get(f"{BASE_URL}/api/trains", timeout=60).json()["atocha"]
    alerts = [{"id": a["id"], "level": a["level"], "filter": {"traffic_types": ["L"]},
               "message": {"ESP": {"header": a["header"], "description": a["text"]}}} for a in cur.get("alerts") or []]
    alerts.append({"id": "TEST_relay", "level": "info", "filter": {"traffic_types": ["C"]},
                   "message": {"ESP": {"header": "TEST cercanias only", "description": "x"}}})
    body = {"station_id": "60000", "payload": _payload(_iso(datetime.now(timezone.utc) - timedelta(seconds=5)), alerts)}
    r1 = requests.post(URL, json=body, headers=h, timeout=30)
    assert r1.status_code == 200
    j1 = r1.json()
    assert j1["accepted"] is True, j1
    assert j1["alerts"] == len(alerts) - 1  # cercanías-only alert filtered out
    r2 = requests.post(URL, json=body, headers=h, timeout=30)
    assert r2.json() == {"accepted": False}
    after = requests.get(f"{BASE_URL}/api/trains", timeout=60).json()["atocha"]
    assert after["source"] == "siv"
    assert "TEST cercanias only" not in [a["header"] for a in after["alerts"]]
