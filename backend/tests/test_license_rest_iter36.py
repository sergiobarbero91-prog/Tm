# Iteration 36: available-drivers count (client), rest calendar, /me rest_soon notice
import asyncio
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
load_dotenv(os.path.join(os.path.dirname(HERE), ".env"))
load_dotenv("/app/frontend/.env")

from license_rest import MADRID, in_shift, license_status, month_calendar  # noqa: E402

BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _holidays():
    return {date.fromisoformat(h["date"]) for h in db.holidays.find({"disabled": {"$ne": True}})}


def _expected_count(at):
    hol = _holidays()
    n = 0
    for u in db.users.find({"license_number": {"$nin": [None, ""]}, "role": {"$ne": "propietario"}}):
        if license_status(u["license_number"], at, hol).get("can_work") and in_shift(u.get("preferred_shift"), at):
            n += 1
    return n


def _H(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"username": "admin", "password": "admin"}, timeout=15)
    if r.status_code != 200:
        pytest.skip("admin login failed")
    return r.json()["access_token"]


@pytest.fixture(scope="module", autouse=True)
def restore():
    orig = db.users.find_one({"username": "admin"}, {"_id": 0, "license_number": 1, "preferred_shift": 1})
    yield
    upd = {"$set": {"preferred_shift": orig.get("preferred_shift", "all")}}
    if "license_number" in orig:
        upd["$set"]["license_number"] = orig["license_number"]
    else:
        upd["$unset"] = {"license_number": ""}
    db.users.update_one({"username": "admin"}, upd)
    db.users.delete_many({"username": {"$regex": "^TEST_avail_"}})


@pytest.fixture(scope="module")
def client_token(admin_token):
    qr = requests.post(f"{API}/rides/driver/qr", headers=_H(admin_token), timeout=10).json()
    r = requests.post(f"{API}/rides/client/authenticate", json={
        "phone": "+34600999401", "first_name": "TEST_Lic", "last_name": "Rest",
        "qr_token": qr["token"], "verification_code": qr.get("verification_code") or qr.get("code")}, timeout=10)
    assert r.status_code == 200, r.text
    return r.json().get("access_token") or r.json().get("token")


def _insert_driver(lic, shift, role="user"):
    name = f"TEST_avail_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({"id": str(uuid.uuid4()), "username": name, "role": role,
                         "license_number": lic, "preferred_shift": shift})
    return name


# --- available drivers count
class TestAvailableDrivers:
    def test_no_auth_401(self):
        r = requests.get(f"{API}/rides/client/available-drivers", timeout=10)
        assert r.status_code == 401

    def test_driver_token_rejected(self, admin_token):
        r = requests.get(f"{API}/rides/client/available-drivers", headers=_H(admin_token), timeout=10)
        assert r.status_code in (401, 403)

    def test_now_matches_rules(self, client_token):
        r = requests.get(f"{API}/rides/client/available-drivers", headers=_H(client_token), timeout=10)
        assert r.status_code == 200
        assert isinstance(r.json()["count"], int)
        assert r.json()["count"] == _expected_count(datetime.now(timezone.utc))

    @pytest.mark.parametrize("iso", ["2026-11-03T10:00:00+01:00", "2026-11-03T22:00:00Z",
                                     "2026-11-07T12:00:00+01:00", "2026-11-09T12:00:00+01:00"])
    def test_at_matches_rules(self, client_token, iso):
        r = requests.get(f"{API}/rides/client/available-drivers", params={"at": iso}, headers=_H(client_token), timeout=10)
        assert r.status_code == 200
        at = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        assert r.json()["count"] == _expected_count(at), iso

    def test_count_changes_with_new_drivers(self, client_token):
        # Tue 2026-11-03 10:00 Madrid: digits 9/0 rest (weekly)
        iso = "2026-11-03T10:00:00+01:00"
        get = lambda: requests.get(f"{API}/rides/client/available-drivers", params={"at": iso},
                                   headers=_H(client_token), timeout=10).json()["count"]
        base = get()
        _insert_driver("11111", "day")     # works, in shift → +1
        assert get() == base + 1
        _insert_driver("11119", "all")     # weekly rest Tue → +0
        _insert_driver("11113", "night")   # out of shift → +0
        _insert_driver("11115", "all", role="propietario")  # owner excluded → +0
        _insert_driver("", "all")          # no licence → +0
        assert get() == base + 1
        _insert_driver("22223", "all")     # works → +1
        assert get() == base + 2

    def test_invalid_at_422(self, client_token):
        r = requests.get(f"{API}/rides/client/available-drivers", params={"at": "notadate"}, headers=_H(client_token), timeout=10)
        assert r.status_code == 422


# --- calendar
class TestCalendar:
    def test_no_licence_empty(self, admin_token):
        db.users.update_one({"username": "admin"}, {"$unset": {"license_number": ""}})
        r = requests.get(f"{API}/license-rest/calendar", params={"year": 2026, "month": 11}, headers=_H(admin_token), timeout=10)
        assert r.status_code == 200
        assert r.json() == {"known": False, "days": []}

    def test_calendar_with_licence(self, admin_token):
        db.users.update_one({"username": "admin"}, {"$set": {"license_number": "99998"}})
        r = requests.get(f"{API}/license-rest/calendar", params={"year": 2026, "month": 11}, headers=_H(admin_token), timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert d["known"] is True
        assert d["days"] == month_calendar("99998", 2026, 11, _holidays())
        mondays = [x for x in d["days"] if x["kind"] == "weekly"]
        assert all(date.fromisoformat(x["date"]).weekday() == 0 for x in mondays)
        assert all(x["start"] == "06:00" and x["end"] == "06:00" and x["ends_next_day"] for x in mondays)
        wk = [x for x in d["days"] if x["kind"] == "weekend"]
        assert wk and all(x["start"] == "07:00" and x["end"] == "20:00" and not x["ends_next_day"] for x in wk)
        # even licence rests odd dates on weekends
        assert all(date.fromisoformat(x["date"]).day % 2 == 1 for x in wk)

    def test_holiday_kind(self, admin_token):
        db.users.update_one({"username": "admin"}, {"$set": {"license_number": "99998"}})
        r = requests.get(f"{API}/license-rest/calendar", params={"year": 2026, "month": 11}, headers=_H(admin_token), timeout=10)
        kinds_9 = sorted(x["kind"] for x in r.json()["days"] if x["date"] == "2026-11-09")
        if date(2026, 11, 9) in _holidays():
            assert kinds_9 == ["holiday", "weekly"]

    @pytest.mark.parametrize("m", [0, 13])
    def test_bad_month_400(self, admin_token, m):
        r = requests.get(f"{API}/license-rest/calendar", params={"year": 2026, "month": m}, headers=_H(admin_token), timeout=10)
        assert r.status_code == 400

    def test_calendar_no_auth(self):
        r = requests.get(f"{API}/license-rest/calendar", params={"year": 2026, "month": 11}, timeout=10)
        assert r.status_code == 401


# --- /me rest_soon (unit-level with frozen clock)
class TestRestSoon:
    def _run(self, lic, now):
        import routers.license_rest as lr

        class FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return now

        async def fake_hol():
            return _holidays()

        orig_dt, orig_hol = lr.datetime, lr.get_holiday_dates
        lr.datetime, lr.get_holiday_dates = FakeDT, fake_hol
        try:
            return asyncio.run(lr.my_rest_status(user={"license_number": lic, "preferred_shift": "all"}))
        finally:
            lr.datetime, lr.get_holiday_dates = orig_dt, orig_hol

    def test_soon_45min(self):
        # Tue 2026-11-10 05:15 Madrid, licence ending 9 rests Tue 06:00
        st = self._run("12349", datetime(2026, 11, 10, 5, 15, tzinfo=MADRID).astimezone(timezone.utc))
        assert st["can_work"] is True and st.get("rest_soon") is True and st["minutes_to_rest"] == 45

    def test_soon_exact_60(self):
        st = self._run("12349", datetime(2026, 11, 10, 5, 0, tzinfo=MADRID).astimezone(timezone.utc))
        assert st.get("rest_soon") is True and st["minutes_to_rest"] == 60

    def test_not_soon_61(self):
        st = self._run("12349", datetime(2026, 11, 10, 4, 59, tzinfo=MADRID).astimezone(timezone.utc))
        assert "rest_soon" not in st

    def test_not_soon_when_resting(self):
        st = self._run("12349", datetime(2026, 11, 10, 7, 0, tzinfo=MADRID).astimezone(timezone.utc))
        assert st["can_work"] is False and "rest_soon" not in st

    def test_live_me_consistent(self, admin_token):
        db.users.update_one({"username": "admin"}, {"$set": {"license_number": "99998"}})
        r = requests.get(f"{API}/license-rest/me", headers=_H(admin_token), timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert d["known"] is True
        if d.get("rest_soon"):
            assert 0 <= d["minutes_to_rest"] <= 60
