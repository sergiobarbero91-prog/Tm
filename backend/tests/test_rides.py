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


def _client_login(phone: str, first_name: str, last_name: str, driver_token: str | None = None) -> str:
    """Register/login a client via the driver-code path.

    If a driver_token is supplied we generate a fresh QR + code from that driver
    and use it. Otherwise we spin up a temporary QR from the admin driver.
    """
    dt = driver_token or _driver_login()
    qr = requests.post(f"{API}/rides/driver/qr", headers={"Authorization": f"Bearer {dt}"}, timeout=10).json()
    r = requests.post(
        f"{API}/rides/client/authenticate",
        json={
            "phone": phone,
            "first_name": first_name,
            "last_name": last_name,
            "qr_token": qr["token"],
            "verification_code": qr["verification_code"],
        },
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _driver_login(username: str = "admin", password: str = "admin") -> str:
    r = requests.post(f"{API}/auth/login", json={"username": username, "password": password}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def test_client_rejected_when_verification_code_is_wrong():
    dt = _driver_login()
    qr = requests.post(f"{API}/rides/driver/qr", headers={"Authorization": f"Bearer {dt}"}, timeout=10).json()
    r = requests.post(
        f"{API}/rides/client/authenticate",
        json={
            "phone": "+34600555000",
            "first_name": "Bad",
            "last_name": "Code",
            "qr_token": qr["token"],
            "verification_code": "000000",
        },
        timeout=10,
    )
    assert r.status_code == 400


def test_driver_qr_rotate_generates_new_code():
    dt = _driver_login()
    q1 = requests.post(f"{API}/rides/driver/qr", headers={"Authorization": f"Bearer {dt}"}, timeout=10).json()
    q2 = requests.post(f"{API}/rides/driver/qr/rotate", headers={"Authorization": f"Bearer {dt}"}, timeout=10).json()
    assert q1["token"] == q2["token"], "same driver keeps same QR token"
    assert q1["verification_code"] != q2["verification_code"], "rotating changes the code"


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
    ct = _client_login("+34600999002", "Reserv", "Via QR", driver_token=dt)
    driver_id = requests.get(f"{API}/rides/client/me", headers={"Authorization": f"Bearer {ct}"}).json()["associated_driver_id"]

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
    assert body["associated_driver_id"] == driver_id


def test_scheduled_ride_within_6h_falls_into_open_offers():
    dt = _driver_login()
    ct = _client_login("+34600999003", "Reserv", "Cerca", driver_token=dt)
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
    body = r1.json()
    assert body["status"] == "accepted"
    # accepted response includes the driver's phone so the client can dial them
    assert "accepted_by_driver_phone" in body

    r2 = requests.post(
        f"{API}/rides/rides/{ride['id']}/accept",
        headers={"Authorization": f"Bearer {dt}"},
        timeout=10,
    )
    assert r2.status_code == 400


def test_client_sees_driver_phone_after_accept():
    """Client polling /rides/mine after acceptance should see the driver's
    phone so the "Llamar al taxista" button can dial it."""
    ct = _client_login("+34600999009", "Call", "Me")
    dt = _driver_login()
    ride = requests.post(
        f"{API}/rides/rides",
        json={"origin": "Sol", "destination": "T4", "ride_type": "asap"},
        headers={"Authorization": f"Bearer {ct}"},
        timeout=10,
    ).json()
    requests.post(
        f"{API}/rides/rides/{ride['id']}/accept",
        headers={"Authorization": f"Bearer {dt}"},
        timeout=10,
    )
    mine = requests.get(f"{API}/rides/rides/mine", headers={"Authorization": f"Bearer {ct}"}, timeout=10).json()
    match = [r for r in mine if r["id"] == ride["id"]][0]
    assert match["status"] == "accepted"
    assert match["accepted_by_driver_phone"], "driver phone must be exposed after accept"


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
