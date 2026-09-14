"""End-to-end tests for the email-based password recovery flow.

The SMTP config is empty in the pod, so the backend runs in DEV email mode
and just logs the reset link. These tests bypass the email step by grabbing
the token directly from Mongo (which is what a real e2e would do after
receiving the email).
"""
import os

import pytest
import requests
from pymongo import MongoClient

API = "http://localhost:8001/api"


def _live() -> bool:
    try:
        return requests.get(f"{API}/health", timeout=2).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _live(), reason="Backend not running")


@pytest.fixture
def db():
    c = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    return c[os.environ.get("DB_NAME", "test_database")]


def _grab_token(db, email: str, role: str) -> str:
    doc = db.password_reset_tokens.find_one(
        {"email": email, "role": role, "used": False},
        sort=[("created_at", -1)],
    )
    assert doc, f"No fresh reset token found for {email} ({role})"
    return doc["token"]


def test_driver_forgot_password_creates_token_and_reset_works(db):
    # Guarantee admin has an email on file
    db.users.update_one({"username": "admin"}, {"$set": {"email": "admin@test.com"}})

    r = requests.post(f"{API}/auth/forgot-password", json={"email": "admin@test.com"}, timeout=10)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    token = _grab_token(db, "admin@test.com", "driver")

    r = requests.post(
        f"{API}/auth/reset-password",
        json={"token": token, "new_password": "admin"},
        timeout=10,
    )
    assert r.status_code == 200

    # Re-using the token is refused
    r2 = requests.post(
        f"{API}/auth/reset-password",
        json={"token": token, "new_password": "admin"},
        timeout=10,
    )
    assert r2.status_code == 400


def test_driver_forgot_password_hides_whether_email_exists():
    r = requests.post(
        f"{API}/auth/forgot-password",
        json={"email": "does-not-exist-9821@example.com"},
        timeout=10,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_client_forgot_password_end_to_end(db):
    # Get a fresh QR to onboard a client (with email) via the /rides API
    login = requests.post(f"{API}/auth/login", json={"username": "admin", "password": "admin"}, timeout=10).json()
    dt = login["access_token"]
    qr = requests.post(f"{API}/rides/driver/qr/rotate", headers={"Authorization": f"Bearer {dt}"}, timeout=10).json()

    email = "client-reset@test.com"
    # Cleanup so this test is repeatable
    db.clients.delete_many({"email": email})
    db.password_reset_tokens.delete_many({"email": email})

    signup = requests.post(
        f"{API}/rides/client/authenticate",
        json={
            "phone": "+34600123457",
            "first_name": "Reset",
            "last_name": "Client",
            "qr_token": qr["token"],
            "verification_code": qr["verification_code"],
            "password": "oldpass",
            "email": email,
        },
        timeout=10,
    )
    assert signup.status_code == 200
    assert signup.json()["client"]["email"] == email

    r = requests.post(f"{API}/rides/client/forgot-password", json={"email": email}, timeout=10)
    assert r.status_code == 200
    token = _grab_token(db, email, "client")

    r = requests.post(
        f"{API}/rides/client/reset-password",
        json={"token": token, "new_password": "newpass123"},
        timeout=10,
    )
    assert r.status_code == 200

    # Old password rejected, new one works
    bad = requests.post(
        f"{API}/rides/client/login",
        json={"phone": "+34600123457", "password": "oldpass"},
        timeout=10,
    )
    assert bad.status_code == 401
    good = requests.post(
        f"{API}/rides/client/login",
        json={"phone": "+34600123457", "password": "newpass123"},
        timeout=10,
    )
    assert good.status_code == 200
