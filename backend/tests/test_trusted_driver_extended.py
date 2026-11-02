# Extended regression tests for "Pedir a mi taxista de confianza" (trusted driver) via the PUBLIC URL
from datetime import datetime, timedelta, timezone
import os

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
CREATED = []


@pytest.fixture(scope="module")
def dt():
    r = requests.post(f"{API}/auth/login", json={"username": "admin", "password": "admin"}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _client(dt, phone, fn="TEST_Trusted", ln="Ext"):
    qr = requests.post(f"{API}/rides/driver/qr", headers={"Authorization": f"Bearer {dt}"}, timeout=15).json()
    r = requests.post(f"{API}/rides/client/authenticate", json={"phone": phone, "first_name": fn, "last_name": ln,
                      "qr_token": qr["token"], "verification_code": qr["verification_code"]}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _ask(ct, prefer=True, **extra):
    body = {"origin": "TEST Atocha", "destination": "TEST Sol", "ride_type": "asap", "prefer_my_driver": prefer}
    body.update(extra)
    r = requests.post(f"{API}/rides/rides", json=body, headers={"Authorization": f"Bearer {ct}"}, timeout=15)
    if r.status_code == 200:
        CREATED.append((ct, r.json()["id"]))
    return r


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    for ct, rid in CREATED:
        requests.post(f"{API}/rides/rides/{rid}/cancel", headers={"Authorization": f"Bearer {ct}"}, timeout=15)


def test_public_create_trusted_ride(dt):
    ct = _client(dt, "+34600999401")
    r = _ask(ct)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["preferred"] is True and d["dispatch_scope"] == "assigned" and d["preferred_released"] is False
    assert d["client_name"] == "TEST_Trusted Ext"
    until = datetime.fromisoformat(d["exclusive_until"].replace("Z", "+00:00"))
    assert 29 <= (until - datetime.now(timezone.utc)).total_seconds() / 60 <= 30.1
    mine = requests.get(f"{API}/rides/rides/mine", headers={"Authorization": f"Bearer {ct}"}).json()
    assert any(x["id"] == d["id"] and x["preferred"] for x in mine)


def test_prefer_without_linked_driver_is_400(dt):
    ct = _client(dt, "+34600999402")
    db.emisora_clients.update_many({"phone": "+34600999402"}, {"$set": {"associated_driver_id": None}})
    db.clients.update_many({"phone": "+34600999402"}, {"$set": {"associated_driver_id": None}})
    me = requests.get(f"{API}/rides/client/me", headers={"Authorization": f"Bearer {ct}"})
    if me.status_code == 200 and me.json().get("associated_driver_id"):
        pytest.skip("could not unlink client in DB (collection name unknown)")
    r = _ask(ct)
    assert r.status_code == 400
    assert "taxista" in r.json()["detail"].lower()


def test_scheduled_far_future_with_prefer(dt):
    """Scheduled >12h + prefer: already exclusive; check flags are coherent for the UI."""
    ct = _client(dt, "+34600999403")
    when = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    r = _ask(ct, ride_type="scheduled", scheduled_at=when)
    assert r.status_code == 200, r.text
    d = r.json()
    print("scheduled>12h prefer ->", d["dispatch_scope"], d["preferred"], d["exclusive_until"], d["preferred_released"])
    assert d["dispatch_scope"] == "assigned"
    # UI shows 'Esperando...' only if exclusive_until is set; otherwise it wrongly shows 'no pudo aceptarlo'
    assert not (d["preferred"] and d["exclusive_until"] is None and not d["preferred_released"]), \
        "preferred=true but no exclusive_until: client UI will show 'Tu taxista no pudo aceptarlo' for a still-exclusive ride"


def test_release_then_reject_again_is_403(dt):
    ct = _client(dt, "+34600999404")
    rid = _ask(ct).json()["id"]
    H = {"Authorization": f"Bearer {dt}"}
    r1 = requests.post(f"{API}/rides/rides/{rid}/reject", headers=H, timeout=15)
    assert r1.status_code == 200 and r1.json()["preferred_released"] is True
    assert any(x["id"] == rid for x in requests.get(f"{API}/rides/driver/offers", headers=H).json())
    assert not any(x["id"] == rid for x in requests.get(f"{API}/rides/driver/assigned", headers=H).json())
    r2 = requests.post(f"{API}/rides/rides/{rid}/reject", headers=H, timeout=15)
    assert r2.status_code == 403
    mine = next(x for x in requests.get(f"{API}/rides/rides/mine", headers={"Authorization": f"Bearer {ct}"}).json() if x["id"] == rid)
    assert mine["dispatch_scope"] == "open" and mine["preferred_released"]


def test_accept_then_client_sees_driver(dt):
    ct = _client(dt, "+34600999405")
    rid = _ask(ct).json()["id"]
    a = requests.post(f"{API}/rides/rides/{rid}/accept", headers={"Authorization": f"Bearer {dt}"}, timeout=15)
    assert a.status_code == 200 and a.json()["status"] == "accepted"
    mine = next(x for x in requests.get(f"{API}/rides/rides/mine", headers={"Authorization": f"Bearer {ct}"}).json() if x["id"] == rid)
    assert mine["status"] == "accepted" and mine["accepted_by_driver_name"]
    r = requests.post(f"{API}/rides/rides/{rid}/reject", headers={"Authorization": f"Bearer {dt}"}, timeout=15)
    assert r.status_code in (400, 403)


def test_cancel_trusted_ride_removes_from_assigned(dt):
    ct = _client(dt, "+34600999406")
    rid = _ask(ct).json()["id"]
    c = requests.post(f"{API}/rides/rides/{rid}/cancel", headers={"Authorization": f"Bearer {ct}"}, timeout=15)
    assert c.status_code == 200 and c.json()["status"] == "cancelled"
    assert not any(x["id"] == rid for x in requests.get(f"{API}/rides/driver/assigned", headers={"Authorization": f"Bearer {dt}"}).json())
