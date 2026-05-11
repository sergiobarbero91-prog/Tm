"""
Tests for AI Daily Event Summary feature.

Validates:
- GET /api/events/daily-summary (public, no auth)
- POST /api/events/daily-summary/regenerate (admin only)
- MongoDB persistence in daily_summaries collection
"""
import os
import pytest
import requests
from datetime import datetime
import pytz

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://tariff-tool.preview.emergentagent.com").rstrip("/")
MADRID_TZ = pytz.timezone("Europe/Madrid")


@pytest.fixture(scope="module")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(api_client):
    # Try common admin login endpoints
    endpoints = ["/api/auth/login", "/api/login", "/api/admin/login"]
    for ep in endpoints:
        try:
            r = api_client.post(
                f"{BASE_URL}{ep}",
                json={"username": "admin", "password": "admin"},
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                token = (
                    data.get("token")
                    or data.get("access_token")
                    or data.get("jwt")
                    or (data.get("data") or {}).get("token")
                )
                if token:
                    return token
        except Exception:
            continue
    return None


# ---------------- GET /api/events/daily-summary ----------------

class TestDailySummaryGet:
    def test_endpoint_returns_200(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/events/daily-summary", timeout=120)
        assert r.status_code == 200, f"Got {r.status_code}: {r.text[:300]}"

    def test_response_has_required_fields(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/events/daily-summary", timeout=120)
        data = r.json()
        # Required fields per spec
        for field in ("success", "summary", "date"):
            assert field in data, f"Missing field '{field}'. Got keys: {list(data.keys())}"
        assert isinstance(data["success"], bool)

    def test_summary_is_spanish_and_real_events(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/events/daily-summary", timeout=120)
        data = r.json()
        summary = data.get("summary") or ""
        assert summary, "Summary is empty"
        # Spanish opener
        assert "Buenos días, compañero" in summary, (
            f"Summary doesn't start with expected Spanish opener. First 200 chars: {summary[:200]}"
        )
        # Must NOT be the placeholder/empty fallback (anti-hallucination)
        # If summary explicitly says no events confirmed it's allowed only as last line,
        # but it must not be only that message. Length > 200 ensures real content.
        assert len(summary) > 200, f"Summary too short ({len(summary)} chars), likely hallucinated empty"
        # Should not contain the previous bad hallucination phrase
        assert "no hay eventos" not in summary.lower(), "Detected previous hallucination phrase"

    def test_date_format(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/events/daily-summary", timeout=120)
        data = r.json()
        date_str = data.get("date")
        assert date_str, "Missing date field"
        # YYYY-MM-DD
        datetime.strptime(date_str, "%Y-%m-%d")
        # Should be today's Madrid date (or yesterday boundary tolerance)
        today_madrid = datetime.now(MADRID_TZ).strftime("%Y-%m-%d")
        assert date_str == today_madrid, f"Date {date_str} != today {today_madrid}"

    def test_search_queries_not_empty(self, api_client):
        """Proves Google Search grounding was activated."""
        r = api_client.get(f"{BASE_URL}/api/events/daily-summary", timeout=120)
        data = r.json()
        sq = data.get("search_queries")
        assert sq is not None, "Missing search_queries field"
        assert isinstance(sq, list)
        assert len(sq) > 0, "search_queries is empty - grounding NOT activated!"

    def test_sources_not_empty(self, api_client):
        """Proves grounding chunks/citations were returned."""
        r = api_client.get(f"{BASE_URL}/api/events/daily-summary", timeout=120)
        data = r.json()
        sources = data.get("sources")
        assert sources is not None, "Missing sources field"
        assert isinstance(sources, list)
        assert len(sources) > 0, "sources is empty - no grounding citations!"
        # Validate source structure
        first = sources[0]
        assert "uri" in first, f"Source missing 'uri': {first}"

    def test_cached_flag_present(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/events/daily-summary", timeout=120)
        data = r.json()
        # cached field expected per spec
        assert "cached" in data, f"Missing 'cached' field. Got keys: {list(data.keys())}"
        assert isinstance(data["cached"], bool)


# ---------------- POST /api/events/daily-summary/regenerate ----------------

class TestDailySummaryRegenerate:
    def test_regenerate_without_auth_unauthorized(self, api_client):
        r = api_client.post(
            f"{BASE_URL}/api/events/daily-summary/regenerate",
            json={},
            timeout=30,
        )
        assert r.status_code in (401, 403), (
            f"Expected 401/403 without auth, got {r.status_code}: {r.text[:200]}"
        )

    def test_regenerate_with_admin_auth(self, api_client, admin_token):
        if not admin_token:
            pytest.skip("Could not obtain admin token - skipping authenticated regenerate test")
        headers = {"Authorization": f"Bearer {admin_token}"}
        r = api_client.post(
            f"{BASE_URL}/api/events/daily-summary/regenerate",
            json={},
            headers=headers,
            timeout=180,  # generation can be slow
        )
        # Either success or upstream 502
        assert r.status_code in (200, 502), (
            f"Unexpected status {r.status_code}: {r.text[:300]}"
        )
        if r.status_code == 200:
            data = r.json()
            assert data.get("success") is True
            assert data.get("summary")
            assert "Buenos días, compañero" in data.get("summary", "")


# ---------------- MongoDB persistence ----------------

class TestDailySummaryPersistence:
    def test_mongo_doc_exists_after_get(self, api_client):
        # Trigger GET first
        api_client.get(f"{BASE_URL}/api/events/daily-summary", timeout=120)

        from pymongo import MongoClient
        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "test_database")
        client = MongoClient(mongo_url)
        try:
            db = client[db_name]
            today = datetime.now(MADRID_TZ).strftime("%Y-%m-%d")
            doc = db.daily_summaries.find_one({"date": today})
            assert doc is not None, f"No daily_summaries doc for {today}"
            assert doc.get("summary"), "Doc has empty summary"
            assert "Buenos días, compañero" in doc.get("summary", "")
            # _id should not leak through API but is fine in DB
            assert doc.get("search_queries") is not None
            assert doc.get("sources") is not None
        finally:
            client.close()
