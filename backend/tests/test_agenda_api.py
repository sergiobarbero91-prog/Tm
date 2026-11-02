# Madrid automatic agenda API (GET /api/events/agenda) + community events regression
import os
from datetime import datetime, timedelta

import pytest
import requests
import pytz
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", os.environ.get("EXPO_PUBLIC_BACKEND_URL", "")).rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
MADRID = pytz.timezone("Europe/Madrid")
SOURCES = {"futbol", "movistar_arena", "vistalegre", "riviera", "ifema", "ayuntamiento"}
FIELDS = ["uid", "source", "name", "place", "date", "start", "end", "start_at", "end_at", "category", "hot", "url"]


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"username": "admin", "password": "admin"}, timeout=20)
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code}")
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}"}


def get_agenda(h, days=None):
    params = {} if days is None else {"days": days}
    return requests.get(f"{BASE_URL}/api/events/agenda", headers=h, params=params, timeout=30)


class TestAgenda:
    def test_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/events/agenda", timeout=20)
        assert r.status_code == 401

    def test_shape_and_fields(self, h):
        r = get_agenda(h, 7)
        assert r.status_code == 200
        d = r.json()
        assert set(["events", "count", "sources"]) <= set(d)
        assert d["count"] == len(d["events"]) > 0
        for e in d["events"]:
            for k in FIELDS:
                assert k in e, f"missing {k} in {e}"
            assert "_id" not in e and "updated_at" not in e
            assert e["source"] in SOURCES
            assert e["uid"].startswith(e["source"] + ":")
            assert isinstance(e["hot"], bool)

    def test_sorted_and_window(self, h):
        d = get_agenda(h, 7).json()
        now = datetime.now(MADRID)
        starts = [datetime.fromisoformat(e["start_at"]) for e in d["events"]]
        assert starts == sorted(starts)
        for e in d["events"]:
            assert datetime.fromisoformat(e["end_at"]) >= now - timedelta(minutes=1), f"ended: {e}"
            assert datetime.fromisoformat(e["start_at"]) <= now + timedelta(days=7, minutes=1)

    def test_days_param_and_cap(self, h):
        c1 = get_agenda(h, 1).json()["count"]
        c7 = get_agenda(h, 7).json()["count"]
        c21 = get_agenda(h, 21).json()["count"]
        c99 = get_agenda(h, 99).json()["count"]
        c0 = get_agenda(h, 0).json()["count"]
        assert c1 <= c7 <= c21
        assert c99 == c21
        assert c0 == c1
        now = datetime.now(MADRID)
        for e in get_agenda(h, 1).json()["events"]:
            assert datetime.fromisoformat(e["start_at"]) <= now + timedelta(days=1, minutes=1)

    def test_default_days(self, h):
        assert get_agenda(h).json()["count"] == get_agenda(h, 7).json()["count"]

    def test_invalid_days(self, h):
        assert get_agenda(h, "abc").status_code == 422

    def test_hot_rules(self, h):
        for e in get_agenda(h, 21).json()["events"]:
            if e["source"] in ("futbol", "movistar_arena", "vistalegre"):
                assert e["hot"] is True, e
            if e["source"] == "futbol":
                assert e["category"] == "futbol"

    def test_no_duplicates_in_db(self):
        mongo = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        dbn = os.environ.get("DB_NAME")
        if not dbn:
            for line in open("/app/backend/.env"):
                if line.startswith("DB_NAME="):
                    dbn = line.split("=", 1)[1].strip().strip('"')
        coll = mongo[dbn]["agenda_events"]
        total = coll.count_documents({})
        assert total > 0
        dup = list(coll.aggregate([{"$group": {"_id": "$uid", "n": {"$sum": 1}}}, {"$match": {"n": {"$gt": 1}}}]))
        assert dup == []
        idx = coll.index_information()
        assert any(v.get("unique") and v["key"][0][0] == "uid" for v in idx.values())


class TestCommunityEventsRegression:
    created = []

    def test_create_and_list(self, h):
        now = datetime.now(MADRID)
        t = (now + timedelta(minutes=30)).strftime("%H:%M") if now.hour < 23 else now.strftime("%H:%M")
        r = requests.post(f"{BASE_URL}/api/events", headers=h,
                          json={"location": "TEST_Atocha", "description": "TEST_agenda regression", "event_time": t}, timeout=20)
        assert r.status_code == 200, r.text
        eid = r.json()["event_id"]
        TestCommunityEventsRegression.created.append(eid)
        lst = requests.get(f"{BASE_URL}/api/events", headers=h, timeout=20)
        assert lst.status_code == 200
        ev = [e for e in lst.json()["events"] if e["event_id"] == eid]
        assert ev and ev[0]["location"] == "TEST_Atocha"

    def test_invalid_time(self, h):
        r = requests.post(f"{BASE_URL}/api/events", headers=h,
                          json={"location": "TEST_x", "description": "x", "event_time": "bad"}, timeout=20)
        assert r.status_code == 400

    def test_delete(self, h):
        for eid in TestCommunityEventsRegression.created:
            r = requests.delete(f"{BASE_URL}/api/events/{eid}", headers=h, timeout=20)
            assert r.status_code == 200
