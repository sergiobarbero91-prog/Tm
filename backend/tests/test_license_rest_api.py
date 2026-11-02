# API tests: licence rest status (/license-rest/me), holidays admin CRUD, client driver-availability, send_to_pool
import os
import sys
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

from license_rest import MADRID, in_shift, license_status  # noqa: E402

BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
TEST_LIC_REST = "99998"  # ends in 8 → Monday weekly rest
TEST_LIC_HOL = "99997"


def _holidays():
    return {date.fromisoformat(h["date"]) for h in db.holidays.find({"disabled": {"$ne": True}})}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"username": "admin", "password": "admin"}, timeout=15)
    if r.status_code != 200:
        pytest.skip(f"admin login failed {r.status_code}")
    return r.json()["access_token"]


@pytest.fixture(scope="module", autouse=True)
def restore_admin():
    orig = db.users.find_one({"username": "admin"}, {"_id": 0, "license_number": 1, "preferred_shift": 1})
    yield
    upd = {"$set": {"preferred_shift": orig.get("preferred_shift", "all")}}
    if "license_number" in orig:
        upd["$set"]["license_number"] = orig["license_number"]
    else:
        upd["$unset"] = {"license_number": ""}
    db.users.update_one({"username": "admin"}, upd)
    db.holidays.delete_many({"name": {"$regex": "^TEST_"}})


@pytest.fixture(scope="module")
def client_token(admin_token):
    H = {"Authorization": f"Bearer {admin_token}"}
    qr = requests.post(f"{API}/rides/driver/qr", headers=H, timeout=10).json()
    r = requests.post(f"{API}/rides/client/authenticate", json={
        "phone": "+34600999401", "first_name": "TEST_Lic", "last_name": "Rest",
        "qr_token": qr["token"], "verification_code": qr.get("verification_code") or qr.get("code")}, timeout=10)
    assert r.status_code == 200, r.text
    return r.json().get("access_token") or r.json().get("token")


def _H(t):
    return {"Authorization": f"Bearer {t}"}


def _set_admin(lic=None, shift=None, unset_lic=False):
    upd = {}
    if lic is not None:
        upd.setdefault("$set", {})["license_number"] = lic
    if shift is not None:
        upd.setdefault("$set", {})["preferred_shift"] = shift
    if unset_lic:
        upd["$unset"] = {"license_number": ""}
    db.users.update_one({"username": "admin"}, upd)


# --- /license-rest/me
class TestMe:
    def test_unknown_without_licence(self, admin_token):
        _set_admin(unset_lic=True, shift="all")
        r = requests.get(f"{API}/license-rest/me", headers=_H(admin_token), timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["known"] is False and d["can_work"] is None
        assert d["in_shift"] is True and d["shift_label"] == "Todo el día"

    def test_unauth(self):
        r = requests.get(f"{API}/license-rest/me", timeout=10)
        assert r.status_code in (401, 403)

    @pytest.mark.parametrize("lic", [TEST_LIC_REST, TEST_LIC_HOL, "99992"])
    def test_profile_licence_reflects_rules(self, admin_token, lic):
        r = requests.put(f"{API}/auth/profile", json={"license_number": lic}, headers=_H(admin_token), timeout=10)
        assert r.status_code == 200, r.text
        d = requests.get(f"{API}/license-rest/me", headers=_H(admin_token), timeout=10).json()
        exp = license_status(lic, datetime.now(timezone.utc), _holidays())
        assert d["known"] is True and d["license_number"] == lic
        assert d["can_work"] == exp["can_work"], (d, exp)
        assert d["label"] == exp["label"]
        if not d["can_work"]:
            assert d["reason"] == exp["reason"]
        print(lic, d["can_work"], d["label"], d.get("reason"))


# --- holidays admin
class TestHolidays:
    def test_list_2026(self, admin_token):
        r = requests.get(f"{API}/license-rest/holidays?year=2026", headers=_H(admin_token), timeout=10)
        assert r.status_code == 200
        hs = r.json()["holidays"]
        assert 12 <= len(hs) <= 20 and all(h["date"].startswith("2026-") for h in hs)
        assert all("_id" not in h for h in hs)

    def test_add_disable_and_non_admin(self, admin_token, client_token):
        d = "2026-12-30"
        r = requests.post(f"{API}/license-rest/holidays", json={"date": d, "name": "TEST_Fest"}, headers=_H(admin_token), timeout=10)
        assert r.status_code == 200, r.text
        hs = requests.get(f"{API}/license-rest/holidays?year=2026", headers=_H(admin_token)).json()["holidays"]
        h = next(x for x in hs if x["date"] == d)
        assert h["name"] == "TEST_Fest" and h["disabled"] is False and h["source"] == "manual"
        assert requests.post(f"{API}/license-rest/holidays", json={"date": "bad", "name": "x"}, headers=_H(admin_token)).status_code == 400
        # non-admin (client token) / no token
        assert requests.post(f"{API}/license-rest/holidays", json={"date": d, "name": "x"}, headers=_H(client_token)).status_code in (401, 403)
        assert requests.delete(f"{API}/license-rest/holidays/{d}").status_code in (401, 403)
        r = requests.delete(f"{API}/license-rest/holidays/{d}", headers=_H(admin_token), timeout=10)
        assert r.status_code == 200
        hs = requests.get(f"{API}/license-rest/holidays?year=2026", headers=_H(admin_token)).json()["holidays"]
        assert next(x for x in hs if x["date"] == d)["disabled"] is True
        assert requests.delete(f"{API}/license-rest/holidays/2026-02-30", headers=_H(admin_token)).status_code == 404

    def test_sync(self, admin_token):
        r = requests.post(f"{API}/license-rest/holidays/sync", headers=_H(admin_token), timeout=60)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] and r.json()["synced"] > 0
        # disabled flag survives a re-sync
        assert db.holidays.find_one({"date": "2026-12-30"})["disabled"] is True


# --- client driver availability
class TestAvailability:
    def test_no_auth(self):
        assert requests.get(f"{API}/rides/client/driver-availability", timeout=10).status_code in (401, 403)

    def test_unknown_licence(self, client_token):
        _set_admin(unset_lic=True, shift="all")
        d = requests.get(f"{API}/rides/client/driver-availability", headers=_H(client_token), timeout=10).json()
        assert d["has_driver"] is True and d["known"] is False and d["available"] is None
        assert "licencia" in d["message"]

    def test_rest_and_shift(self, client_token):
        _set_admin(lic=TEST_LIC_REST, shift="all")
        hol = _holidays()
        # find next weekday where licence ending 8 rests (Monday) at 12:00 Madrid, ≥1 day ahead
        day = datetime.now(MADRID).date() + timedelta(days=1)
        while day.weekday() != 0:
            day += timedelta(days=1)
        at = datetime(day.year, day.month, day.day, 12, tzinfo=MADRID)
        exp = license_status(TEST_LIC_REST, at, hol)
        assert exp["can_work"] is False
        r = requests.get(f"{API}/rides/client/driver-availability", params={"at": at.isoformat()}, headers=_H(client_token), timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["available"] is False and d["license_ok"] is False and "libranza" in d["message"], d
        # Tuesday 22:00 with 'day' shift → outside shift
        tue = at + timedelta(days=1, hours=10)
        assert license_status(TEST_LIC_REST, tue, hol)["can_work"] is True
        _set_admin(shift="day")
        d = requests.get(f"{API}/rides/client/driver-availability", params={"at": tue.isoformat()}, headers=_H(client_token)).json()
        assert d["available"] is False and d["in_shift"] is False and "turno" in d["message"], d
        # Tuesday 10:00 'day' → available
        ok = at + timedelta(days=1, hours=-2)
        d = requests.get(f"{API}/rides/client/driver-availability", params={"at": ok.isoformat()}, headers=_H(client_token)).json()
        assert d["available"] is True and d["in_shift"] is True, d
        # 'Z' suffix ISO
        z = ok.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        d = requests.get(f"{API}/rides/client/driver-availability", params={"at": z}, headers=_H(client_token)).json()
        assert d["available"] is True, d


# --- ride creation send_to_pool / prefer_my_driver
class TestRideCreate:
    def _ride(self, ct, **kw):
        body = {"origin": "TEST_Atocha", "destination": "Sol", "ride_type": "asap", **kw}
        return requests.post(f"{API}/rides/rides", json=body, headers=_H(ct), timeout=10)

    def test_scheduled_far_send_to_pool_is_open(self, client_token):
        at = (datetime.now(timezone.utc) + timedelta(hours=30)).isoformat()
        r = self._ride(client_token, ride_type="scheduled", scheduled_at=at, send_to_pool=True, prefer_my_driver=True)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["dispatch_scope"] == "open" and d["preferred"] is False and d["exclusive_until"] is None

    def test_scheduled_far_default_assigned(self, client_token):
        at = (datetime.now(timezone.utc) + timedelta(hours=30)).isoformat()
        av = requests.get(f"{API}/rides/client/driver-availability", params={"at": at}, headers=_H(client_token)).json()
        d = self._ride(client_token, ride_type="scheduled", scheduled_at=at).json()
        # reserved for the trusted driver only if they can work then; otherwise straight to the pool
        assert d["dispatch_scope"] == ("open" if av["available"] is False else "assigned")

    def test_asap_send_to_pool(self, client_token):
        d = self._ride(client_token, send_to_pool=True, prefer_my_driver=True).json()
        assert d["dispatch_scope"] == "open" and d["preferred"] is False

    def test_prefer_my_driver_exclusive_30(self, client_token):
        d = self._ride(client_token, prefer_my_driver=True).json()
        assert d["dispatch_scope"] == "assigned" and d["preferred"] is True
        until = datetime.fromisoformat(d["exclusive_until"].replace("Z", "+00:00"))
        assert 29 <= (until - datetime.now(timezone.utc)).total_seconds() / 60 <= 30.1

    @classmethod
    def teardown_class(cls):
        db.rides.delete_many({"origin": "TEST_Atocha"})
