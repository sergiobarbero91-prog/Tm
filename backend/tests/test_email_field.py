"""Regression tests for driver email field on register and profile edit."""
import os
import time
import pytest
import requests
from pymongo import MongoClient

API = "http://localhost:8001/api"


def _live():
    try:
        return requests.get(f"{API}/health", timeout=2).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _live(), reason="Backend not running")


@pytest.fixture(scope="module")
def db():
    c = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    return c[os.environ.get("DB_NAME", "test_database")]


@pytest.fixture(scope="module")
def admin_token():
    time.sleep(1)
    r = requests.post(f"{API}/auth/login", json={"username": "admin", "password": "admin"}, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---- Profile PUT email persistence ------------------------------------------

def test_profile_put_updates_email_and_me_reflects(db, admin_token):
    email = "admin+profileput@test.com"
    # Clear any conflicting owners
    db.users.update_many({"email": email, "username": {"$ne": "admin"}}, {"$unset": {"email": 1}})

    me = requests.get(f"{API}/auth/me", headers=_auth(admin_token), timeout=10).json()

    # Update only email (avoid license_number uniqueness self-clash)
    r = requests.put(
        f"{API}/auth/profile",
        json={"email": email},
        headers=_auth(admin_token),
        timeout=10,
    )
    assert r.status_code == 200, r.text
    assert r.json().get("email") == email

    me2 = requests.get(f"{API}/auth/me", headers=_auth(admin_token), timeout=10).json()
    assert me2.get("email") == email

    doc = db.users.find_one({"username": "admin"})
    assert doc.get("email") == email


def test_profile_put_rejects_invalid_email(admin_token):
    r = requests.put(
        f"{API}/auth/profile",
        json={"email": "not-an-email"},
        headers=_auth(admin_token),
        timeout=10,
    )
    assert r.status_code == 400, r.text
    assert "no válido" in r.text.lower() or "invalid" in r.text.lower() or "email" in r.text.lower()


def test_profile_put_rejects_duplicate_email(db, admin_token):
    other_email = "test_dup_email@test.com"
    ts = int(time.time() * 1000) % 10_000_000
    db.users.delete_many({"username": "TEST_dupuser"})
    db.users.update_many({"email": other_email, "username": {"$ne": "TEST_dupuser"}}, {"$unset": {"email": 1}})
    db.users.insert_one({
        "id": "test-dup-user-id",
        "username": "TEST_dupuser",
        "email": other_email,
        "role": "user",
        "hashed_password": "x",
        "license_number": f"88{ts}",
        "created_at": __import__("datetime").datetime.utcnow(),
    })
    try:
        r = requests.put(
            f"{API}/auth/profile",
            json={"email": other_email},
            headers=_auth(admin_token),
            timeout=10,
        )
        assert r.status_code == 400, r.text
        assert "en uso" in r.text
    finally:
        db.users.delete_many({"username": "TEST_dupuser"})


# ---- Register-with-invitation persists email --------------------------------

def _create_invitation(admin_token):
    for path in ("/auth/invitations", "/auth/invitation-codes", "/auth/create-invitation"):
        r = requests.post(f"{API}{path}", json={"role": "conductor", "max_uses": 1},
                          headers=_auth(admin_token), timeout=10)
        if r.status_code in (200, 201):
            j = r.json()
            code = j.get("code") or j.get("invitation_code") or (j.get("data") or {}).get("code")
            if code:
                return code
    # Fallback: no body
    for path in ("/auth/invitations", "/auth/invitation-codes"):
        r = requests.post(f"{API}{path}", headers=_auth(admin_token), timeout=10)
        if r.status_code in (200, 201):
            j = r.json()
            code = j.get("code") or j.get("invitation_code")
            if code:
                return code
    return None


def test_register_with_invitation_persists_email(db, admin_token):
    code = _create_invitation(admin_token)
    if not code:
        pytest.skip("Could not create invitation code from admin API")

    ts = int(time.time() * 1000) % 10_000_000
    username = f"TEST_reguser_{ts}"
    email = f"test_reguser_{ts}@example.com"
    license_num = str(700000 + (ts % 100000))
    db.users.delete_many({"username": {"$regex": "^TEST_reguser_"}})

    payload = {
        "invitation_code": code,
        "username": username,
        "password": "pw123456",
        "full_name": "Test Reg User",
        "license_number": license_num,
        "phone": None,
        "email": email,
        "preferred_shift": "all",
        "role": "conductor",
        "licencias": [],
    }
    r = requests.post(f"{API}/auth/register-with-invitation", json=payload, timeout=10)
    assert r.status_code == 200, r.text
    token = r.json().get("access_token")
    assert token

    # /me should return the email
    me = requests.get(f"{API}/auth/me", headers=_auth(token), timeout=10).json()
    assert me.get("email") == email, f"/me does not reflect email: {me}"

    # Mongo persistence
    doc = db.users.find_one({"username": username})
    assert doc and doc.get("email") == email

    db.users.delete_one({"username": username})
