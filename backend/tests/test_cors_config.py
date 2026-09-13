"""
Iter_19 tests — CORS configuration safety.

Rationale:
  The user could not upload photos in production because the backend was
  emitting the invalid CORS combo `allow_credentials=True` + `allow_origins=['*']`,
  which every modern browser REJECTS silently. The fix in server.py auto-disables
  credentials when the wildcard is used AND emits a startup WARNING.

These tests hit the BACKEND DIRECTLY on http://localhost:8001 to bypass the
Kubernetes ingress, which layers its own `Access-Control-Allow-Origin: *`
header on top of FastAPI's response. Only the direct backend response reflects
the actual CORSMiddleware behavior we care about.

Coverage:
  - Wildcard mode: allow_credentials MUST be absent (or false)
  - Specific-origin mode: allow_credentials=true AND allow_origin echoes the request
  - Retry-After MUST be in access-control-expose-headers
  - /api/journal/start accepts multipart with a real Origin (no CORS block)
"""
import io
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import requests
from PIL import Image


DIRECT_BASE = "http://localhost:8001"
PREVIEW_BASE = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
                or "https://tariff-tool.preview.emergentagent.com").rstrip("/")
ENV_PATH = Path("/app/backend/.env")
BACKUP_PATH = Path("/tmp/env.iter19.backup")

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"


# ============================================================================
# Helpers
# ============================================================================
def _read_env() -> str:
    return ENV_PATH.read_text(encoding="utf-8")


def _write_env(text: str) -> None:
    ENV_PATH.write_text(text, encoding="utf-8")


def _set_allowed_origins(value: str | None) -> None:
    """
    Set (or unset) ALLOWED_ORIGINS in /app/backend/.env, then restart backend
    via supervisor and wait for it to come back up.
    """
    lines = _read_env().splitlines()
    new_lines = [ln for ln in lines if not ln.strip().startswith("ALLOWED_ORIGINS")]
    if value is not None:
        new_lines.append(f'ALLOWED_ORIGINS="{value}"')
    _write_env("\n".join(new_lines) + "\n")
    subprocess.run(["sudo", "supervisorctl", "restart", "backend"],
                   check=True, capture_output=True)
    # Wait for backend to be responsive
    for _ in range(30):
        try:
            r = requests.get(f"{DIRECT_BASE}/api/health", timeout=2)
            if r.status_code < 500:
                return
        except requests.exceptions.RequestException:
            pass
        time.sleep(1)
    raise RuntimeError("backend failed to come up after restart")


@pytest.fixture(scope="module", autouse=True)
def _preserve_env():
    """Snapshot .env before the module runs, restore + restart at teardown."""
    shutil.copy(str(ENV_PATH), str(BACKUP_PATH))
    yield
    shutil.copy(str(BACKUP_PATH), str(ENV_PATH))
    subprocess.run(["sudo", "supervisorctl", "restart", "backend"],
                   check=True, capture_output=True)
    for _ in range(30):
        try:
            r = requests.get(f"{DIRECT_BASE}/api/health", timeout=2)
            if r.status_code < 500:
                return
        except requests.exceptions.RequestException:
            pass
        time.sleep(1)


# ============================================================================
# WILDCARD MODE — allow_credentials MUST be off
# ============================================================================
class TestWildcardMode:
    """When ALLOWED_ORIGINS is unset or '*'."""

    @pytest.fixture(autouse=True)
    def _wildcard(self):
        _set_allowed_origins("*")

    def test_preflight_no_credentials(self):
        r = requests.options(
            f"{DIRECT_BASE}/api/journal/active",
            headers={
                "Origin": "https://asdelvolante.es",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
            timeout=10,
        )
        assert r.status_code in (200, 204), f"preflight failed: {r.status_code}"
        # Wildcard MUST be echoed
        assert r.headers.get("access-control-allow-origin") == "*", r.headers
        # Credentials MUST be omitted OR explicitly false
        creds = r.headers.get("access-control-allow-credentials", "").lower()
        assert creds in ("", "false"), (
            f"allow_credentials must be off when using wildcard. Got: {creds!r}"
        )

    def test_simple_get_no_credentials(self):
        r = requests.get(
            f"{DIRECT_BASE}/api/health",
            headers={"Origin": "https://asdelvolante.es"},
            timeout=10,
        )
        assert r.headers.get("access-control-allow-origin") == "*"
        creds = r.headers.get("access-control-allow-credentials", "").lower()
        assert creds in ("", "false")

    def test_retry_after_in_expose_headers(self):
        r = requests.get(
            f"{DIRECT_BASE}/api/health",
            headers={"Origin": "https://asdelvolante.es"},
            timeout=10,
        )
        expose = r.headers.get("access-control-expose-headers", "")
        assert "Retry-After" in expose, (
            f"'Retry-After' missing from expose-headers: {expose!r}"
        )

    def test_startup_warning_emitted(self):
        """Look for the warning line in the supervisor err log."""
        log = Path("/var/log/supervisor/backend.err.log").read_text(errors="ignore")
        # Only inspect the most recent 400 lines (roughly last restart)
        tail = "\n".join(log.splitlines()[-400:])
        assert "ALLOWED_ORIGINS" in tail and "wildcard" in tail.lower(), (
            f"Startup warning about wildcard not found in log tail:\n{tail[-2000:]}"
        )


# ============================================================================
# SPECIFIC-ORIGIN MODE — credentials on, origin echoed
# ============================================================================
class TestSpecificOriginMode:
    """When ALLOWED_ORIGINS is a comma-separated list of real origins."""

    @pytest.fixture(autouse=True)
    def _specific(self):
        _set_allowed_origins("https://asdelvolante.es,https://www.asdelvolante.es")

    def test_preflight_echoes_origin_with_credentials(self):
        r = requests.options(
            f"{DIRECT_BASE}/api/journal/active",
            headers={
                "Origin": "https://asdelvolante.es",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
            timeout=10,
        )
        assert r.status_code in (200, 204), f"preflight failed: {r.status_code}"
        assert r.headers.get("access-control-allow-origin") == "https://asdelvolante.es"
        assert r.headers.get("access-control-allow-credentials", "").lower() == "true"

    def test_second_allowed_origin_also_works(self):
        r = requests.options(
            f"{DIRECT_BASE}/api/journal/active",
            headers={
                "Origin": "https://www.asdelvolante.es",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
            timeout=10,
        )
        assert r.headers.get("access-control-allow-origin") == "https://www.asdelvolante.es"
        assert r.headers.get("access-control-allow-credentials", "").lower() == "true"

    def test_disallowed_origin_no_acao_header(self):
        r = requests.get(
            f"{DIRECT_BASE}/api/health",
            headers={"Origin": "https://evil.example.com"},
            timeout=10,
        )
        # CORSMiddleware must NOT echo a disallowed origin
        assert r.headers.get("access-control-allow-origin") in (None, "")

    def test_retry_after_in_expose_headers(self):
        r = requests.get(
            f"{DIRECT_BASE}/api/health",
            headers={"Origin": "https://asdelvolante.es"},
            timeout=10,
        )
        expose = r.headers.get("access-control-expose-headers", "")
        assert "Retry-After" in expose

    def test_journal_start_upload_with_origin(self):
        """
        Confirm authenticated multipart upload with a real Origin header
        does NOT get blocked by CORS in specific-origin mode.
        """
        # Login
        login = requests.post(
            f"{DIRECT_BASE}/api/auth/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
            headers={"Origin": "https://asdelvolante.es"},
            timeout=15,
        )
        assert login.status_code == 200, login.text[:300]
        # Login response must carry a valid CORS ACAO for the origin
        assert login.headers.get("access-control-allow-origin") == "https://asdelvolante.es"
        token = login.json()["access_token"]

        # Cleanup any leftover open journal
        active = requests.get(
            f"{DIRECT_BASE}/api/journal/active",
            headers={"Authorization": f"Bearer {token}",
                     "Origin": "https://asdelvolante.es"},
            timeout=15,
        )
        if active.status_code == 200 and isinstance(active.json(), dict) and active.json().get("id"):
            requests.delete(
                f"{DIRECT_BASE}/api/journal/{active.json()['id']}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )

        # POST tiny JPEG
        buf = io.BytesIO()
        Image.new("RGB", (200, 200), "white").save(buf, format="JPEG", quality=70)
        files = {"photo": ("start.jpg", buf.getvalue(), "image/jpeg")}
        r = requests.post(
            f"{DIRECT_BASE}/api/journal/start",
            files=files,
            headers={"Authorization": f"Bearer {token}",
                     "Origin": "https://asdelvolante.es"},
            timeout=120,
        )
        # Accept 200 (Gemini happy) or 5xx (Gemini quota) — the KEY assertion
        # is that we did NOT get 403 with "origin not allowed" or a network
        # rejection, AND that CORS ACAO is present on the response.
        assert r.status_code in (200, 400, 500, 502, 503), (
            f"unexpected status: {r.status_code} {r.text[:300]}"
        )
        assert r.headers.get("access-control-allow-origin") == "https://asdelvolante.es"
        # Sanity: no origin-block wording in the body
        assert "origin not allowed" not in r.text.lower()

        # Cleanup any newly-opened journal
        if r.status_code == 200:
            body = r.json()
            if isinstance(body, dict) and body.get("id"):
                requests.delete(
                    f"{DIRECT_BASE}/api/journal/{body['id']}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=15,
                )
