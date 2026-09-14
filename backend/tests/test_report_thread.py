"""End-to-end tests for the new report thread messaging system."""
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


_TOKEN_CACHE: dict = {}


def _admin_token() -> str:
    if "t" in _TOKEN_CACHE:
        return _TOKEN_CACHE["t"]
    r = requests.post(f"{API}/auth/login", json={"username": "admin", "password": "admin"}, timeout=10)
    r.raise_for_status()
    tok = r.json()["access_token"]
    _TOKEN_CACHE["t"] = tok
    return tok


def _make_reporter_and_report():
    """Creates a temp user + report, returns (reporter_token, report_id, admin_token, user_id)."""
    admin = _admin_token()
    username = f"reptest{int(time.time() * 1000) % 1_000_000}"
    r = requests.post(
        f"{API}/admin/users",
        json={"username": username, "password": "pass1234", "role": "user", "phone": "+34611000009"},
        headers={"Authorization": f"Bearer {admin}"},
        timeout=10,
    )
    r.raise_for_status()
    reporter = requests.post(
        f"{API}/auth/login",
        json={"username": username, "password": "pass1234"},
        timeout=10,
    ).json()["access_token"]
    # user_id lookup
    users = requests.get(f"{API}/admin/users", headers={"Authorization": f"Bearer {admin}"}, timeout=10).json()
    user_id = next(u["id"] for u in users if u["username"] == username)

    rep = requests.post(
        f"{API}/moderation/reports",
        json={"report_type": "spam", "description": "Un usuario esta enviando spam en el chat"},
        headers={"Authorization": f"Bearer {reporter}"},
        timeout=10,
    ).json()
    return reporter, rep["report_id"], admin, user_id


def _cleanup(admin: str, user_id: str):
    try:
        requests.delete(f"{API}/admin/users/{user_id}", headers={"Authorization": f"Bearer {admin}"}, timeout=10)
    except Exception:
        pass


def test_admin_can_open_thread_and_message_reporter():
    reporter, rid, admin, user_id = _make_reporter_and_report()
    try:
        # Admin fetches detail + messages (marks as read from staff side)
        detail = requests.get(
            f"{API}/moderation/reports/{rid}",
            headers={"Authorization": f"Bearer {admin}"},
            timeout=10,
        ).json()
        assert detail["id"] == rid

        # Admin sends message
        r = requests.post(
            f"{API}/moderation/reports/{rid}/messages",
            json={"body": "Puedes darnos mas contexto?"},
            headers={"Authorization": f"Bearer {admin}"},
            timeout=10,
        )
        assert r.status_code == 200

        # Reporter sees unread=1 in their list
        my = requests.get(
            f"{API}/moderation/reports/my-reports",
            headers={"Authorization": f"Bearer {reporter}"},
            timeout=10,
        ).json()
        me = next(x for x in my["reports"] if x["id"] == rid)
        assert me["unread_for_viewer"] == 1
        assert me["message_count"] == 1

        # Reporter opens and replies
        msgs = requests.get(
            f"{API}/moderation/reports/{rid}/messages",
            headers={"Authorization": f"Bearer {reporter}"},
            timeout=10,
        ).json()
        assert len(msgs["messages"]) == 1

        r = requests.post(
            f"{API}/moderation/reports/{rid}/messages",
            json={"body": "Se llama baduser y publica links varias veces por hora"},
            headers={"Authorization": f"Bearer {reporter}"},
            timeout=10,
        )
        assert r.status_code == 200

        # Now admin has unread=1
        detail = requests.get(
            f"{API}/moderation/reports/{rid}",
            headers={"Authorization": f"Bearer {admin}"},
            timeout=10,
        ).json()
        assert detail["unread_for_viewer"] == 1
    finally:
        _cleanup(admin, user_id)


def test_staff_can_change_status_and_close_thread():
    reporter, rid, admin, user_id = _make_reporter_and_report()
    try:
        # Move to awaiting_reporter
        r = requests.put(
            f"{API}/moderation/reports/{rid}/status",
            json={"status": "awaiting_reporter", "note": "Necesitamos capturas"},
            headers={"Authorization": f"Bearer {admin}"},
            timeout=10,
        )
        assert r.status_code == 200

        # Reporter sees system message in the thread
        msgs = requests.get(
            f"{API}/moderation/reports/{rid}/messages",
            headers={"Authorization": f"Bearer {reporter}"},
            timeout=10,
        ).json()["messages"]
        assert any(m["is_system"] and "informacion" in m["body"].lower() for m in msgs)

        # Admin resolves
        r = requests.put(
            f"{API}/moderation/reports/{rid}/status",
            json={"status": "resolved", "note": "Todo aclarado"},
            headers={"Authorization": f"Bearer {admin}"},
            timeout=10,
        )
        assert r.status_code == 200

        # Reporter cannot send more messages
        r = requests.post(
            f"{API}/moderation/reports/{rid}/messages",
            json={"body": "gracias"},
            headers={"Authorization": f"Bearer {reporter}"},
            timeout=10,
        )
        assert r.status_code == 400
    finally:
        _cleanup(admin, user_id)


def test_third_party_cannot_read_thread():
    reporter, rid, admin, user_id = _make_reporter_and_report()
    try:
        # Create a second unrelated user
        intruder_name = f"intruder{int(time.time() * 1000) % 1_000_000}"
        requests.post(
            f"{API}/admin/users",
            json={"username": intruder_name, "password": "pass1234", "role": "user", "phone": "+34611000010"},
            headers={"Authorization": f"Bearer {admin}"},
            timeout=10,
        ).raise_for_status()
        intruder = requests.post(
            f"{API}/auth/login",
            json={"username": intruder_name, "password": "pass1234"},
            timeout=10,
        ).json()["access_token"]

        r = requests.get(
            f"{API}/moderation/reports/{rid}/messages",
            headers={"Authorization": f"Bearer {intruder}"},
            timeout=10,
        )
        assert r.status_code == 403

        # Cleanup intruder
        users = requests.get(f"{API}/admin/users", headers={"Authorization": f"Bearer {admin}"}, timeout=10).json()
        intruder_id = next(u["id"] for u in users if u["username"] == intruder_name)
        requests.delete(f"{API}/admin/users/{intruder_id}", headers={"Authorization": f"Bearer {admin}"}, timeout=10)
    finally:
        _cleanup(admin, user_id)


def test_moderator_cannot_resolve_admin_only():
    """Only admins can mark 'resolved'; moderators are limited."""
    reporter, rid, admin, user_id = _make_reporter_and_report()
    try:
        # Promote a fresh user to moderator
        mod_name = f"mod{int(time.time() * 1000) % 1_000_000}"
        requests.post(
            f"{API}/admin/users",
            json={"username": mod_name, "password": "pass1234", "role": "moderator", "phone": "+34611000011"},
            headers={"Authorization": f"Bearer {admin}"},
            timeout=10,
        ).raise_for_status()
        mod_tok = requests.post(
            f"{API}/auth/login",
            json={"username": mod_name, "password": "pass1234"},
            timeout=10,
        ).json()["access_token"]

        r = requests.put(
            f"{API}/moderation/reports/{rid}/status",
            json={"status": "resolved"},
            headers={"Authorization": f"Bearer {mod_tok}"},
            timeout=10,
        )
        assert r.status_code == 403

        # But can set awaiting_reporter
        r = requests.put(
            f"{API}/moderation/reports/{rid}/status",
            json={"status": "awaiting_reporter"},
            headers={"Authorization": f"Bearer {mod_tok}"},
            timeout=10,
        )
        assert r.status_code == 200

        users = requests.get(f"{API}/admin/users", headers={"Authorization": f"Bearer {admin}"}, timeout=10).json()
        mod_id = next(u["id"] for u in users if u["username"] == mod_name)
        requests.delete(f"{API}/admin/users/{mod_id}", headers={"Authorization": f"Bearer {admin}"}, timeout=10)
    finally:
        _cleanup(admin, user_id)
