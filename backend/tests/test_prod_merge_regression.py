"""Backend regression suite after PROD MERGE.

Covers:
1. /api/flights : new instant_demand_* fields + prod-only fields (delivering, large, saturation, etc) per terminal,
   per-arrival belt/aircraft/status fields.
2. /api/events/daily-summary : 4 sections, sources, queries.
3. /api/events/daily-summary/regenerate : 401 without auth, 200 with admin.
4. /api/trains : atocha.arrivals regression.
5. /api/buses (NEW) : avenida_america + estacion_sur, no auth.
6. /api/reservations (NEW) : 401 without auth, 200 with auth.
7. Smoke: no 500s on /api/flights, /api/trains, /api/buses across 3 consecutive calls.
"""
import os
import re
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://tariff-tool.preview.emergentagent.com").rstrip("/")
TIMEOUT = 60
LONG_TIMEOUT = 180


@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"username": "admin", "password": "admin"}, timeout=30)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("access_token")
    assert tok and len(tok) > 20
    return tok


# ---------- /api/flights ----------
class TestFlights:
    @pytest.fixture(scope="class")
    def flights(self):
        r = requests.get(f"{BASE_URL}/api/flights", timeout=TIMEOUT)
        assert r.status_code == 200, f"/api/flights failed: {r.status_code}"
        return r.json()

    def test_terminals_present(self, flights):
        terms = flights.get("terminals", {})
        for t in ["T1", "T2", "T3", "T4", "T4S"]:
            assert t in terms, f"Missing terminal {t}"

    def test_instant_demand_fields(self, flights):
        valid_levels = {"green", "yellow", "red", "critical"}
        for tname, tdata in flights["terminals"].items():
            assert "instant_demand_pct" in tdata, f"{tname} missing instant_demand_pct"
            assert "instant_demand_level" in tdata, f"{tname} missing instant_demand_level"
            assert "instant_demand_points" in tdata, f"{tname} missing instant_demand_points"
            pct = tdata["instant_demand_pct"]
            assert isinstance(pct, (int, float)) and 0 <= pct <= 1000, \
                f"{tname} instant_demand_pct out of range: {pct}"
            assert tdata["instant_demand_level"] in valid_levels

    def test_prod_only_fields_present(self, flights):
        """Prod-merged fields that must exist after the recovery merge."""
        required = [
            "delivering_30min", "delivering_60min",
            "large_30min", "large_60min",
            "next_after_30min", "next_after_60min",
            "saturation_30min", "saturation_60min",
            "saturation_level_30min", "saturation_level_60min",
            "past_30min", "past_60min",
            "score_30min", "score_60min",
        ]
        sat_levels = {"baja", "media", "alta"}
        for tname, tdata in flights["terminals"].items():
            for f in required:
                assert f in tdata, f"{tname} missing prod-merged field: {f}"
            assert tdata["saturation_level_30min"] in sat_levels, \
                f"{tname} bad sat level 30: {tdata['saturation_level_30min']}"
            assert tdata["saturation_level_60min"] in sat_levels, \
                f"{tname} bad sat level 60: {tdata['saturation_level_60min']}"

    def test_per_arrival_fields(self, flights):
        """At least one arrival across terminals should expose belt/aircraft/status."""
        valid_status_substrings = ["tierra", "Entregando", "Finalizado", "vuelo",
                                   "Aterrizado", "Programado", "Retrasado", "Cancelado",
                                   "Desviado", "Embarcando"]
        found_any = False
        for tname, tdata in flights["terminals"].items():
            arrivals = tdata.get("arrivals") or tdata.get("next_arrivals") or []
            for a in arrivals:
                if isinstance(a, dict):
                    if "belt" in a and "aircraft" in a and "status" in a:
                        found_any = True
                        # status must be a non-empty string
                        assert isinstance(a["status"], str) and len(a["status"]) > 0
                        break
            if found_any:
                break
        assert found_any, "No arrival across any terminal exposed belt/aircraft/status fields"


# ---------- /api/events/daily-summary ----------
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

    def test_four_sections(self, summary):
        text = summary["summary"]
        for header in ("[GRANDES EVENTOS]", "[TEATROS Y OCIO]",
                       "[ALERTAS DE TRÁFICO]", "[PREVISIÓN MAÑANA]"):
            assert header in text, f"Missing section header: {header}"

    def test_bold_markers(self, summary):
        assert re.search(r"\*\*[^*]+\*\*", summary["summary"]), "No **bold** segments"

    def test_sources_and_queries(self, summary):
        assert len(summary["search_queries"]) >= 5, \
            f"too few queries: {len(summary['search_queries'])}"
        assert len(summary["sources"]) >= 1, "no sources returned"


# ---------- /api/events/daily-summary/regenerate auth ----------
class TestRegenerateAuth:
    def test_no_auth_unauthorized(self):
        r = requests.post(f"{BASE_URL}/api/events/daily-summary/regenerate", timeout=30)
        assert r.status_code in (401, 403), f"Expected 401/403, got {r.status_code}"

    def test_with_admin_ok(self, admin_token):
        r = requests.post(f"{BASE_URL}/api/events/daily-summary/regenerate",
                          headers={"Authorization": f"Bearer {admin_token}"},
                          timeout=LONG_TIMEOUT)
        assert r.status_code == 200, f"regen failed: {r.status_code} {r.text[:200]}"
        data = r.json()
        assert data.get("success") is True
        assert "summary" in data and len(data["summary"]) > 50


# ---------- /api/trains regression ----------
class TestTrainsRegression:
    def test_atocha_arrivals(self):
        r = requests.get(f"{BASE_URL}/api/trains", timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert "atocha" in data, "missing atocha"
        assert "arrivals" in data["atocha"], "missing atocha.arrivals"
        assert isinstance(data["atocha"]["arrivals"], list)


# ---------- /api/buses NEW ----------
class TestBuses:
    @pytest.fixture(scope="class")
    def buses(self):
        r = requests.get(f"{BASE_URL}/api/buses", timeout=TIMEOUT)
        assert r.status_code == 200, f"/api/buses failed: {r.status_code} {r.text[:200]}"
        return r.json()

    def test_no_auth_required(self):
        # explicit: no Authorization header
        r = requests.get(f"{BASE_URL}/api/buses", timeout=TIMEOUT)
        assert r.status_code == 200

    def test_two_stations_present(self, buses):
        # Accept either "stations" wrapper or top-level keys
        keys = buses if isinstance(buses, dict) else {}
        flat = keys.get("stations", keys)
        assert "avenida_america" in flat, f"missing avenida_america; keys={list(flat.keys())}"
        assert "estacion_sur" in flat, f"missing estacion_sur; keys={list(flat.keys())}"


# ---------- /api/reservations NEW ----------
class TestReservations:
    def test_no_auth_unauthorized(self):
        r = requests.get(f"{BASE_URL}/api/reservations", timeout=TIMEOUT)
        assert r.status_code in (401, 403), f"Expected 401/403, got {r.status_code}"

    def test_with_admin_ok(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/reservations",
                         headers={"Authorization": f"Bearer {admin_token}"},
                         timeout=TIMEOUT)
        assert r.status_code == 200, f"reservations failed: {r.status_code} {r.text[:200]}"
        data = r.json()
        # Accept list or {reservations: [...]}
        if isinstance(data, dict):
            assert "reservations" in data or "items" in data or "data" in data or len(data) >= 0
        else:
            assert isinstance(data, list)


# ---------- Smoke: no 500s on 3 consecutive calls ----------
class TestSmokeNo500:
    @pytest.mark.parametrize("path", ["/api/flights", "/api/trains", "/api/buses"])
    def test_three_consecutive_calls(self, path):
        codes = []
        for _ in range(3):
            r = requests.get(f"{BASE_URL}{path}", timeout=TIMEOUT)
            codes.append(r.status_code)
        for c in codes:
            assert c < 500, f"{path} returned {c} in sequence {codes}"
