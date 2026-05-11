"""Tests for the Instant Demand (Demanda en este Momento) feature on /api/flights."""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL")
if not BASE_URL:
    # Fallback to reading the frontend .env, must not be empty
    raise RuntimeError("Backend URL env var missing")
BASE_URL = BASE_URL.rstrip("/")

REQUIRED_TERMINALS = ["T1", "T2", "T3", "T4", "T4S"]
BREAKDOWN_KEYS = {
    "en_tierra",
    "entregando_equipo_lt15",
    "entregando_equipo_gt15",
    "finalizado_0_15",
    "finalizado_16_30",
    "long_haul_boost",
}
VALID_LEVELS = {"green", "yellow", "red", "critical"}
VALID_TRENDS = {"up", "down", "flat"}


def expected_level(pct: int) -> str:
    if pct > 100:
        return "critical"
    if pct >= 70:
        return "red"
    if pct >= 40:
        return "yellow"
    return "green"


@pytest.fixture(scope="module")
def flights_realtime():
    resp = requests.get(f"{BASE_URL}/api/flights", timeout=30)
    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text[:200]}"
    return resp.json()


@pytest.fixture(scope="module")
def flights_custom_window():
    # Pick an arbitrary one-hour window that is clearly outside "now"
    resp = requests.get(
        f"{BASE_URL}/api/flights",
        params={
            "start_time": "2026-01-15T10:00:00",
            "end_time": "2026-01-15T11:00:00",
        },
        timeout=30,
    )
    assert resp.status_code == 200
    return resp.json()


class TestInstantPressureSchema:
    """Verify the response schema for the new instant pressure fields."""

    def test_terminals_present(self, flights_realtime):
        for t in REQUIRED_TERMINALS:
            assert t in flights_realtime["terminals"], f"Terminal {t} missing"

    def test_pct_is_int(self, flights_realtime):
        for t, td in flights_realtime["terminals"].items():
            pct = td.get("instant_pressure_pct")
            assert pct is not None, f"{t} missing instant_pressure_pct"
            assert isinstance(pct, int), f"{t} pct must be int, got {type(pct)}"
            assert pct >= 0, f"{t} pct must be >=0"

    def test_level_valid(self, flights_realtime):
        for t, td in flights_realtime["terminals"].items():
            lvl = td.get("instant_pressure_level")
            assert lvl in VALID_LEVELS, f"{t} invalid level {lvl}"

    def test_trend_valid(self, flights_realtime):
        for t, td in flights_realtime["terminals"].items():
            tr = td.get("instant_pressure_trend")
            assert tr in VALID_TRENDS, f"{t} invalid trend {tr}"

    def test_breakdown_keys(self, flights_realtime):
        for t, td in flights_realtime["terminals"].items():
            bk = td.get("instant_pressure_breakdown")
            assert isinstance(bk, dict), f"{t} breakdown missing or not dict"
            assert set(bk.keys()) == BREAKDOWN_KEYS, (
                f"{t} breakdown keys mismatch. Got {set(bk.keys())}"
            )
            for k, v in bk.items():
                assert isinstance(v, int) and v >= 0, f"{t}.{k} bad value {v}"


class TestInstantPressureLevelMapping:
    """Level must match the pct thresholds."""

    def test_level_matches_pct(self, flights_realtime):
        for t, td in flights_realtime["terminals"].items():
            pct = td["instant_pressure_pct"]
            level = td["instant_pressure_level"]
            assert level == expected_level(pct), (
                f"{t}: pct={pct} should map to {expected_level(pct)} but got {level}"
            )


class TestInstantPressureCustomWindow:
    """Instant pressure must be omitted/null when a custom time window is used."""

    def test_custom_window_no_instant_pressure(self, flights_custom_window):
        for t, td in flights_custom_window["terminals"].items():
            assert td.get("instant_pressure_pct") is None, f"{t} pct should be null"
            assert td.get("instant_pressure_level") is None, f"{t} level should be null"
            assert td.get("instant_pressure_trend") is None, f"{t} trend should be null"
            assert td.get("instant_pressure_breakdown") is None, f"{t} breakdown should be null"


class TestPressureCalculationUnit:
    """Hit the function directly to verify the math from the spec."""

    def _call(self, arrivals):
        from datetime import datetime
        import pytz
        from backend.server import calculate_instant_pressure, pressure_level

        tz = pytz.timezone("Europe/Madrid")
        now = tz.localize(datetime(2026, 1, 15, 12, 0, 0))

        # Convert minutes-since-arrival to HH:MM string
        out = []
        for mins, origin in arrivals:
            t = now.replace(minute=0)
            from datetime import timedelta
            dt = now - timedelta(minutes=mins)
            out.append({"time": dt.strftime("%H:%M"), "origin": origin})
        return calculate_instant_pressure(out, now), pressure_level

    def test_sample_calculation(self):
        # 1 flight EN TIERRA (3min)=0.2, 1 entregando<15 (10min)=0.4,
        # 1 entregando>15 (20min)=0.8, 1 finalizado_0_15 (35min)=1.0,
        # 1 finalizado_16_30 (55min)=0.3, 1 long-haul entregando>15 (20min from JFK)=0.8*1.5=1.2
        # Total = 3.9, pct = 39 -> green
        arrivals = [
            (3, "Sevilla"),
            (10, "Paris"),
            (20, "Roma"),
            (35, "Lisboa"),
            (55, "Berlin"),
            (20, "New York JFK"),
        ]
        result, pressure_level = self._call(arrivals)
        assert result["breakdown"]["en_tierra"] == 1
        assert result["breakdown"]["entregando_equipo_lt15"] == 1
        assert result["breakdown"]["entregando_equipo_gt15"] == 2  # roma + JFK
        assert result["breakdown"]["finalizado_0_15"] == 1
        assert result["breakdown"]["finalizado_16_30"] == 1
        assert result["breakdown"]["long_haul_boost"] == 1
        # Score check: 0.2+0.4+0.8+1.0+0.3+0.8*1.5 = 3.9, pct=39, green
        assert result["pct"] == 39
        assert pressure_level(result["pct"]) == "green"

    def test_level_thresholds(self):
        from backend.server import pressure_level
        assert pressure_level(0) == "green"
        assert pressure_level(39) == "green"
        assert pressure_level(40) == "yellow"
        assert pressure_level(69) == "yellow"
        assert pressure_level(70) == "red"
        assert pressure_level(100) == "red"
        assert pressure_level(101) == "critical"
        assert pressure_level(150) == "critical"
