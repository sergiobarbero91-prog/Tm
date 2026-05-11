"""Regression + new feature tests for:
- /api/flights: instant_demand_pct/level/trend per terminal (TASK 1)
- /api/events/daily-summary: 4 telegram sections + sources + queries (TASK 2)
- /api/events/daily-summary/regenerate: auth-gated (TASK 2)
- /api/trains regression
"""
import os
import re
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://tariff-tool.preview.emergentagent.com").rstrip("/")
TIMEOUT = 60
LONG_TIMEOUT = 180


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"username": "admin", "password": "admin"}, timeout=30)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("access_token")
    assert tok and len(tok) > 20
    return tok


# ---------- TASK 1: Instant Demand per terminal ----------
class TestInstantDemand:
    @pytest.fixture(scope="class")
    def flights(self):
        r = requests.get(f"{BASE_URL}/api/flights", timeout=TIMEOUT)
        assert r.status_code == 200, f"/api/flights failed: {r.status_code}"
        return r.json()

    def test_terminals_present(self, flights):
        terms = flights.get("terminals", {})
        for t in ["T1", "T2", "T3", "T4", "T4S"]:
            assert t in terms, f"Missing terminal {t}"

    def test_instant_demand_fields_present(self, flights):
        for tname, tdata in flights["terminals"].items():
            assert "instant_demand_pct" in tdata, f"{tname} missing instant_demand_pct"
            assert "instant_demand_level" in tdata, f"{tname} missing instant_demand_level"
            assert "instant_demand_trend" in tdata, f"{tname} missing instant_demand_trend"

    def test_instant_demand_value_types_and_ranges(self, flights):
        valid_levels = {"green", "yellow", "red", "critical"}
        valid_trends = {"up", "down", "flat"}
        for tname, tdata in flights["terminals"].items():
            pct = tdata["instant_demand_pct"]
            assert isinstance(pct, (int, float)), f"{tname} pct not numeric: {pct!r}"
            assert 0 <= pct <= 500, f"{tname} pct out of expected range: {pct}"
            assert tdata["instant_demand_level"] in valid_levels, \
                f"{tname} bad level: {tdata['instant_demand_level']}"
            assert tdata["instant_demand_trend"] in valid_trends, \
                f"{tname} bad trend: {tdata['instant_demand_trend']}"

    def test_original_score_fields_preserved(self, flights):
        # CRITICAL: original Score / XA-YP backend fields must still be there
        for tname, tdata in flights["terminals"].items():
            for f in ("score_30min", "score_60min", "total_next_30min",
                      "total_next_60min", "past_30min", "past_60min"):
                assert f in tdata, f"{tname} regression: missing {f}"


# ---------- TASK 2: AI daily summary ----------
class TestDailySummary:
    @pytest.fixture(scope="class")
    def summary(self):
        r = requests.get(f"{BASE_URL}/api/events/daily-summary", timeout=LONG_TIMEOUT)
        assert r.status_code == 200, f"daily-summary failed: {r.status_code} {r.text[:200]}"
        return r.json()

    def test_basic_fields(self, summary):
        for f in ("summary", "sources", "search_queries", "date", "generated_at"):
            assert f in summary, f"missing field {f}"
        assert isinstance(summary["summary"], str) and len(summary["summary"]) > 100
        assert isinstance(summary["sources"], list)
        assert isinstance(summary["search_queries"], list)

    def test_four_sections_present(self, summary):
        text = summary["summary"]
        for header in ("[GRANDES EVENTOS]", "[TEATROS Y OCIO]",
                       "[ALERTAS DE TRÁFICO]", "[PREVISIÓN MAÑANA]"):
            assert header in text, f"Missing section header: {header}"

    def test_bold_markers_present(self, summary):
        # Telegram-style **bold** must exist for places/hours
        assert re.search(r"\*\*[^*]+\*\*", summary["summary"]), "No **bold** segments found"

    def test_has_sources_and_queries(self, summary):
        assert len(summary["search_queries"]) >= 5, \
            f"too few queries: {len(summary['search_queries'])}"
        assert len(summary["sources"]) >= 1


class TestRegenerateAuth:
    def test_no_auth_unauthorized(self):
        r = requests.post(f"{BASE_URL}/api/events/daily-summary/regenerate", timeout=30)
        assert r.status_code in (401, 403), f"Expected 401/403, got {r.status_code}"

    def test_with_admin_token_ok(self, admin_token):
        r = requests.post(f"{BASE_URL}/api/events/daily-summary/regenerate",
                          headers={"Authorization": f"Bearer {admin_token}"},
                          timeout=LONG_TIMEOUT)
        assert r.status_code == 200, f"regen failed: {r.status_code} {r.text[:200]}"
        data = r.json()
        assert data.get("success") is True
        assert "summary" in data and len(data["summary"]) > 50


# ---------- Regression: trains ----------
class TestTrainsRegression:
    def test_trains_endpoint(self):
        r = requests.get(f"{BASE_URL}/api/trains", timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert "atocha" in data
        assert "arrivals" in data["atocha"]
        assert isinstance(data["atocha"]["arrivals"], list)
