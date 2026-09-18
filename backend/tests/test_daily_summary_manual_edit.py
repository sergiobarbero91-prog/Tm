"""Manual edition of the daily AI summary by admin/moderator."""
import requests

API = "http://localhost:8001/api"


def _admin_token() -> str:
    r = requests.post(f"{API}/auth/login", json={"username": "admin", "password": "admin"}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def test_put_daily_summary_requires_auth():
    r = requests.put(f"{API}/events/daily-summary", json={"summary": "x" * 15}, timeout=10)
    assert r.status_code == 401


def test_admin_can_edit_daily_summary_and_persists():
    tk = _admin_token()
    edited = "[METEO HOY]\n- Cielo despejado.\n\n[GRANDES EVENTOS]\n- Se ha cancelado el evento de IFEMA."
    r = requests.put(
        f"{API}/events/daily-summary",
        json={"summary": edited},
        headers={"Authorization": f"Bearer {tk}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["manually_edited"] is True
    assert body["edited_by"] == "admin"
    assert "cancelado el evento de IFEMA" in body["summary"]

    # Subsequent GET must return the manually-edited version.
    r2 = requests.get(f"{API}/events/daily-summary", headers={"Authorization": f"Bearer {tk}"}, timeout=15)
    assert r2.status_code == 200
    assert r2.json()["manually_edited"] is True
    assert "cancelado el evento de IFEMA" in r2.json()["summary"]


def test_short_summary_is_rejected():
    tk = _admin_token()
    r = requests.put(
        f"{API}/events/daily-summary",
        json={"summary": "too short"},
        headers={"Authorization": f"Bearer {tk}"},
        timeout=10,
    )
    assert r.status_code == 422
