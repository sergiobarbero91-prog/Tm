"""Activity heartbeats: middleware writes, admin endpoints read."""
import time
import requests

API = "http://localhost:8001/api"


def _admin_token() -> str:
    r = requests.post(f"{API}/auth/login", json={"username": "admin", "password": "admin"}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def test_admin_activity_stats_requires_auth():
    r = requests.get(f"{API}/admin/activity/stats", timeout=10)
    assert r.status_code == 401


def test_admin_activity_stats_structure():
    tk = _admin_token()
    # Trigger at least one heartbeat for the admin.
    requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {tk}"}, timeout=10)
    time.sleep(0.5)
    r = requests.get(f"{API}/admin/activity/stats", headers={"Authorization": f"Bearer {tk}"}, timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert "periods" in body and "roles" in body
    for p in ("day", "week", "month"):
        assert p in body["periods"]
        for kind in ("users", "clients"):
            assert kind in body["periods"][p]
            assert "active_users" in body["periods"][p][kind]
            assert "total_hours" in body["periods"][p][kind]
    assert body["periods"]["day"]["users"]["active_users"] >= 1


def test_admin_user_activity_endpoint():
    tk = _admin_token()
    me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {tk}"}, timeout=10).json()
    time.sleep(0.5)
    r = requests.get(
        f"{API}/admin/activity/user/{me['id']}",
        headers={"Authorization": f"Bearer {tk}"},
        timeout=10,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "user"
    assert body["periods"]["day"]["active_users"] == 1
    assert body["periods"]["day"]["total_hours"] > 0


def test_admin_user_rides_lookup():
    tk = _admin_token()
    me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {tk}"}, timeout=10).json()
    r = requests.get(
        f"{API}/admin/activity/user/{me['id']}/rides",
        headers={"Authorization": f"Bearer {tk}"},
        timeout=10,
    )
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_activity_unknown_id():
    tk = _admin_token()
    r = requests.get(
        f"{API}/admin/activity/user/does-not-exist",
        headers={"Authorization": f"Bearer {tk}"},
        timeout=10,
    )
    assert r.status_code == 404
