"""End-to-end tests for rating, blocking and reporting rides."""
import time
import pytest
import requests

API = "http://localhost:8001/api"


def _live() -> bool:
    try:
        return requests.get(f"{API}/health", timeout=2).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _live(), reason="Backend not running")

_CACHE: dict = {}


def _admin_token() -> str:
    if "t" in _CACHE:
        return _CACHE["t"]
    r = requests.post(f"{API}/auth/login", json={"username": "admin", "password": "admin"}, timeout=10)
    r.raise_for_status()
    _CACHE["t"] = r.json()["access_token"]
    return _CACHE["t"]


def _mk_client(phone: str, password: str = "pass1234"):
    admin = _admin_token()
    requests.post(
        f"{API}/admin/clients",
        json={"phone": phone, "first_name": "T", "last_name": "T", "password": password},
        headers={"Authorization": f"Bearer {admin}"},
        timeout=10,
    )
    return requests.post(
        f"{API}/rides/client/login",
        json={"phone": phone, "password": password},
        timeout=10,
    ).json()["access_token"]


def _cleanup(phone: str):
    admin = _admin_token()
    lst = requests.get(f"{API}/admin/clients/search?q={phone[-6:]}", headers={"Authorization": f"Bearer {admin}"}, timeout=10).json()
    for c in lst:
        if c["phone"] == phone:
            requests.delete(f"{API}/admin/clients/{c['id']}", headers={"Authorization": f"Bearer {admin}"}, timeout=10)


def _run_ride(ct, dt):
    rid = requests.post(
        f"{API}/rides/rides",
        json={"origin": "A", "destination": "B", "ride_type": "asap"},
        headers={"Authorization": f"Bearer {ct}"},
        timeout=10,
    ).json()["id"]
    requests.post(f"{API}/rides/rides/{rid}/accept", headers={"Authorization": f"Bearer {dt}"}, timeout=10).raise_for_status()
    requests.post(f"{API}/rides/rides/{rid}/start", headers={"Authorization": f"Bearer {dt}"}, timeout=10).raise_for_status()
    requests.post(f"{API}/rides/rides/{rid}/complete", headers={"Authorization": f"Bearer {dt}"}, timeout=10).raise_for_status()
    return rid


def test_bidirectional_ratings_and_history():
    phone = f"+346559{int(time.time()) % 10000:04d}"
    ct = _mk_client(phone)
    dt = _admin_token()
    try:
        rid = _run_ride(ct, dt)
        # client rates driver
        requests.post(f"{API}/rides/rides/{rid}/rate", json={"stars": 5, "comment": "OK"}, headers={"Authorization": f"Bearer {ct}"}, timeout=10).raise_for_status()
        # driver rates client
        requests.post(f"{API}/rides/rides/{rid}/rate", json={"stars": 3}, headers={"Authorization": f"Bearer {dt}"}, timeout=10).raise_for_status()

        client_hist = requests.get(f"{API}/rides/client/history", headers={"Authorization": f"Bearer {ct}"}, timeout=10).json()
        hit = next(r for r in client_hist if r["id"] == rid)
        assert hit["my_rating"] == 5
        assert hit["their_rating"] == 3

        driver_hist = requests.get(f"{API}/rides/driver/history", headers={"Authorization": f"Bearer {dt}"}, timeout=10).json()
        hit = next(r for r in driver_hist if r["id"] == rid)
        assert hit["my_rating"] == 3
        assert hit["their_rating"] == 5
    finally:
        _cleanup(phone)


def test_block_prevents_new_rides_from_reaching_driver():
    phone = f"+346552{int(time.time()) % 10000:04d}"
    ct = _mk_client(phone)
    dt = _admin_token()
    try:
        # Get admin (driver) id
        me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {dt}"}, timeout=10).json()
        drv_id = me["id"]
        # Client blocks driver
        requests.post(
            f"{API}/rides/blocks",
            json={"target_id": drv_id, "target_role": "driver"},
            headers={"Authorization": f"Bearer {ct}"},
            timeout=10,
        ).raise_for_status()

        # New ride from this client should NOT appear in driver's offers
        rid = requests.post(
            f"{API}/rides/rides",
            json={"origin": "Sol", "destination": "T4", "ride_type": "asap"},
            headers={"Authorization": f"Bearer {ct}"},
            timeout=10,
        ).json()["id"]
        offers = requests.get(f"{API}/rides/driver/offers", headers={"Authorization": f"Bearer {dt}"}, timeout=10).json()
        assert rid not in [o["id"] for o in offers]

        # After unblock, it reappears
        requests.delete(f"{API}/rides/blocks/{drv_id}", headers={"Authorization": f"Bearer {ct}"}, timeout=10).raise_for_status()
        offers = requests.get(f"{API}/rides/driver/offers", headers={"Authorization": f"Bearer {dt}"}, timeout=10).json()
        assert rid in [o["id"] for o in offers]
    finally:
        _cleanup(phone)


def test_ride_report_creates_moderation_report():
    phone = f"+346553{int(time.time()) % 10000:04d}"
    ct = _mk_client(phone)
    dt = _admin_token()
    try:
        rid = _run_ride(ct, dt)
        r = requests.post(
            f"{API}/rides/rides/{rid}/report",
            json={"report_type": "harassment", "description": "Comportamiento inadecuado durante todo el trayecto"},
            headers={"Authorization": f"Bearer {ct}"},
            timeout=10,
        )
        assert r.status_code == 200
        report_id = r.json()["report_id"]
        # Admin sees it in pending-mod
        pending = requests.get(
            f"{API}/moderation/reports/pending-moderator",
            headers={"Authorization": f"Bearer {dt}"},
            timeout=10,
        ).json()
        assert any(x["id"] == report_id for x in pending["reports"])
    finally:
        _cleanup(phone)


def test_third_party_cannot_rate_ride():
    phone1 = f"+346554{int(time.time()) % 10000:04d}"
    phone2 = f"+346555{int(time.time()) % 10000:04d}"
    ct1 = _mk_client(phone1)
    ct2 = _mk_client(phone2)
    dt = _admin_token()
    try:
        rid = _run_ride(ct1, dt)
        r = requests.post(
            f"{API}/rides/rides/{rid}/rate",
            json={"stars": 5},
            headers={"Authorization": f"Bearer {ct2}"},
            timeout=10,
        )
        assert r.status_code == 403
    finally:
        _cleanup(phone1)
        _cleanup(phone2)
