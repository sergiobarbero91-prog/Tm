"""End-to-end smoke test for /api/admin extended endpoints."""
import pytest
import requests

API = "http://localhost:8001/api"


def _live() -> bool:
    try:
        return requests.get(f"{API}/health", timeout=2).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _live(), reason="Backend not running")


_TOKEN_CACHE: dict = {}


def _admin_token() -> str:
    if "t" in _TOKEN_CACHE:
        return _TOKEN_CACHE["t"]
    r = requests.post(f"{API}/auth/login", json={"username": "admin", "password": "admin"}, timeout=10)
    r.raise_for_status()
    tok = r.json()["access_token"]
    _TOKEN_CACHE["t"] = tok
    return tok


def _hdr():
    return {"Authorization": f"Bearer {_admin_token()}"}


# ------------------------- USERS -------------------------
def test_admin_can_update_all_user_fields():
    tk = _admin_token()
    users = requests.get(f"{API}/admin/users", headers={"Authorization": f"Bearer {tk}"}, timeout=10).json()
    admin = next(u for u in users if u["username"] == "admin")
    r = requests.put(
        f"{API}/admin/users/{admin['id']}",
        json={
            "full_name": "Admin Total",
            "email": "admin@test.com",
            "preferred_shift": "day",
        },
        headers={"Authorization": f"Bearer {tk}"},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    users = requests.get(f"{API}/admin/users", headers={"Authorization": f"Bearer {tk}"}, timeout=10).json()
    admin = next(u for u in users if u["username"] == "admin")
    assert admin["full_name"] == "Admin Total"
    assert admin["email"] == "admin@test.com"
    assert admin["preferred_shift"] == "day"


def test_admin_can_manage_licencias():
    tk = _admin_token()
    users = requests.get(f"{API}/admin/users", headers={"Authorization": f"Bearer {tk}"}, timeout=10).json()
    admin = next(u for u in users if u["username"] == "admin")
    # Set two licencias
    r = requests.put(
        f"{API}/admin/users/{admin['id']}",
        json={"licencias": [{"numero": "888001", "alias": "Uno"}, {"numero": "888002", "alias": None}]},
        headers={"Authorization": f"Bearer {tk}"},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    users = requests.get(f"{API}/admin/users", headers={"Authorization": f"Bearer {tk}"}, timeout=10).json()
    admin = next(u for u in users if u["username"] == "admin")
    licencias = admin.get("licencias") or []
    numeros = sorted(l["numero"] for l in licencias)
    assert "888001" in numeros and "888002" in numeros
    # Duplicated licencias must fail
    r = requests.put(
        f"{API}/admin/users/{admin['id']}",
        json={"licencias": [{"numero": "777001"}, {"numero": "777001"}]},
        headers={"Authorization": f"Bearer {tk}"},
        timeout=10,
    )
    assert r.status_code == 400
    # Non-digit licencia must fail
    r = requests.put(
        f"{API}/admin/users/{admin['id']}",
        json={"licencias": [{"numero": "abc"}]},
        headers={"Authorization": f"Bearer {tk}"},
        timeout=10,
    )
    assert r.status_code == 400


def test_admin_role_rejects_invalid_value():
    tk = _admin_token()
    users = requests.get(f"{API}/admin/users", headers={"Authorization": f"Bearer {tk}"}, timeout=10).json()
    admin = next(u for u in users if u["username"] == "admin")
    r = requests.put(
        f"{API}/admin/users/{admin['id']}",
        json={"role": "hacker"},
        headers={"Authorization": f"Bearer {tk}"},
        timeout=10,
    )
    assert r.status_code == 422


# ------------------------- CLIENTS -------------------------
def _cleanup_client(phone: str):
    tk = _admin_token()
    lst = requests.get(f"{API}/admin/clients/search?q={phone[-6:]}", headers={"Authorization": f"Bearer {tk}"}, timeout=10).json()
    for c in lst:
        if c["phone"] == phone:
            requests.delete(f"{API}/admin/clients/{c['id']}", headers={"Authorization": f"Bearer {tk}"}, timeout=10)


def test_admin_full_client_crud():
    phone = "+34655900001"
    _cleanup_client(phone)
    tk = _admin_token()
    hdr = {"Authorization": f"Bearer {tk}"}

    # Create
    r = requests.post(
        f"{API}/admin/clients",
        json={
            "phone": phone, "first_name": "Pepe", "last_name": "Cliente",
            "email": "pepe-crud@example.com", "password": "pass1234",
        },
        headers=hdr, timeout=10,
    )
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    assert r.json()["has_password"] is True

    # Duplicate phone -> 400
    r = requests.post(
        f"{API}/admin/clients",
        json={"phone": phone, "first_name": "Otro", "last_name": "Cliente"},
        headers=hdr, timeout=10,
    )
    assert r.status_code == 400

    # Search
    r = requests.get(f"{API}/admin/clients/search?q=Pepe", headers=hdr, timeout=10)
    assert r.status_code == 200
    assert any(c["id"] == cid for c in r.json())

    # Update
    r = requests.put(
        f"{API}/admin/clients/{cid}",
        json={"first_name": "PepePepe", "email": "pepe-nuevo@example.com"},
        headers=hdr, timeout=10,
    )
    assert r.status_code == 200
    assert r.json()["first_name"] == "PepePepe"
    assert r.json()["email"] == "pepe-nuevo@example.com"

    # Change password
    r = requests.put(
        f"{API}/admin/clients/{cid}/password",
        json={"new_password": "otro5678"},
        headers=hdr, timeout=10,
    )
    assert r.status_code == 200

    # Client can log in with the new password
    r = requests.post(
        f"{API}/rides/client/login",
        json={"phone": phone, "password": "otro5678"},
        timeout=10,
    )
    assert r.status_code == 200

    # Delete
    r = requests.delete(f"{API}/admin/clients/{cid}", headers=hdr, timeout=10)
    assert r.status_code == 200
    # 404 on delete twice
    r = requests.delete(f"{API}/admin/clients/{cid}", headers=hdr, timeout=10)
    assert r.status_code == 404


def test_admin_client_invalid_phone_rejected():
    tk = _admin_token()
    r = requests.post(
        f"{API}/admin/clients",
        json={"phone": "612345678", "first_name": "X", "last_name": "Y"},
        headers={"Authorization": f"Bearer {tk}"}, timeout=10,
    )
    assert r.status_code == 400


def test_admin_endpoints_require_admin_role():
    r = requests.get(f"{API}/admin/clients", timeout=10)
    assert r.status_code in (401, 403)
