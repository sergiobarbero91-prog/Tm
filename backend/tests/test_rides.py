"""End-to-end smoke test for /api/rides (Emisora module).

Uses the live in-container backend at http://localhost:8001. Skipped if the
backend is unreachable so CI runs on other pods don't fail.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest
import requests

API = "http://localhost:8001/api"


def _live() -> bool:
    try:
        return requests.get(f"{API}/health", timeout=2).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _live(), reason="Backend not running")


def _client_login(phone: str, first_name: str, last_name: str, qr_token: str | None = None) -> str:
    r = requests.post(f"{API}/rides/client/send-otp", json={"phone": phone}, timeout=10)
    r.raise_for_status()
    body = {"phone": phone, "code": "123456", "first_name": first_name, "last_name": last_name}
    if qr_token:
        body["associated_driver_qr"] = qr_token
    r = requests.post(f"{API}/rides/client/verify-otp", json=body, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def _driver_login(username: str = "admin", password: str = "admin") -> str:
    r = requests.post(f"{API}/auth/login", json={"username": username, "password": password}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def test_client_can_register_and_create_asap_ride():
    tok = _client_login("+34600999001", "Test", "Rider")
    r = requests.post(
        f"{API}/rides/rides",
        json={"origin": "Atocha", "destination": "Barajas T4", "ride_type": "asap"},
        headers={"Authorization": f"Bearer {tok}"},
        timeout=10,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert body["dispatch_scope"] == "open"


def test_scheduled_ride_beyond_6h_is_assigned_to_qr_associated_driver():
    dt = _driver_login()
    qr = requests.post(f"{API}/rides/driver/qr", headers={"Authorization": f"Bearer {dt}"}, timeout=10).json()
    token = qr["token"]

    ct = _client_login("+34600999002", "Reserv", "Via QR", qr_token=token)
    when = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
    r = requests.post(
        f"{API}/rides/rides",
        json={"origin": "Sol", "destination": "Barajas T1", "ride_type": "scheduled", "scheduled_at": when},
        headers={"Authorization": f"Bearer {ct}"},
        timeout=10,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["dispatch_scope"] == "assigned"
    assert body["associated_driver_id"] == qr["driver_id"]


def test_scheduled_ride_within_6h_falls_into_open_offers():
    dt = _driver_login()
    qr = requests.post(f"{API}/rides/driver/qr", headers={"Authorization": f"Bearer {dt}"}, timeout=10).json()
    ct = _client_login("+34600999003", "Reserv", "Cerca", qr_token=qr["token"])
    when = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    r = requests.post(
        f"{API}/rides/rides",
        json={"origin": "Callao", "destination": "T4", "ride_type": "scheduled", "scheduled_at": when},
        headers={"Authorization": f"Bearer {ct}"},
        timeout=10,
    )
    assert r.status_code == 200
    assert r.json()["dispatch_scope"] == "open"


def test_driver_accept_marks_ride_and_prevents_second_accept():
    ct = _client_login("+34600999004", "Ana", "Cliente")
    dt = _driver_login()
    ride = requests.post(
        f"{API}/rides/rides",
        json={"origin": "Sol", "destination": "T4", "ride_type": "asap"},
        headers={"Authorization": f"Bearer {ct}"},
        timeout=10,
    ).json()

    r1 = requests.post(
        f"{API}/rides/rides/{ride['id']}/accept",
        headers={"Authorization": f"Bearer {dt}"},
        timeout=10,
    )
    assert r1.status_code == 200
    assert r1.json()["status"] == "accepted"

    r2 = requests.post(
        f"{API}/rides/rides/{ride['id']}/accept",
        headers={"Authorization": f"Bearer {dt}"},
        timeout=10,
    )
    assert r2.status_code == 400


def test_client_can_cancel_pending_ride():
    ct = _client_login("+34600999005", "Luis", "Cancel")
    ride = requests.post(
        f"{API}/rides/rides",
        json={"origin": "Sol", "destination": "T4", "ride_type": "asap"},
        headers={"Authorization": f"Bearer {ct}"},
        timeout=10,
    ).json()
    r = requests.post(
        f"{API}/rides/rides/{ride['id']}/cancel",
        headers={"Authorization": f"Bearer {ct}"},
        timeout=10,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
