# Tests for the new P/E/F/S + GRANDE + Demanda fields on /api/flights
# Verifies per-terminal counters, demand_pct/demand_level, status_tag enrichment
# and backward compatibility of old fields.

import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or os.environ.get(
    "REACT_APP_BACKEND_URL", ""
).rstrip("/")

VALID_LEVELS = {"baja", "media", "alta", "critica"}
VALID_TAGS = {"proximo", "siguiente", "equipaje", "finalizado", None}
TERMINALS = ["T1", "T2", "T4"]  # backend groups: T1, T2-T3, T4-T4S


@pytest.fixture(scope="module")
def flights_payload():
    assert BASE_URL, "Backend URL env var must be set"
    r = requests.get(f"{BASE_URL}/api/flights", timeout=60)
    assert r.status_code == 200, f"flights endpoint failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    # Backend wraps terminals under "terminals" key
    return body.get("terminals", body)


class TestTerminalDemandBuckets:
    """Per-terminal P/E/F/S/GRANDE + demand fields."""

    def test_endpoint_ok(self, flights_payload):
        assert isinstance(flights_payload, dict)
        for t in TERMINALS:
            assert t in flights_payload, f"Missing terminal block {t}"

    def test_buckets_present_and_int(self, flights_payload):
        for t in TERMINALS:
            term = flights_payload[t]
            for field in ("proximos", "equipaje", "finalizado", "siguientes", "grande"):
                assert field in term, f"{t} missing field {field}"
                assert isinstance(term[field], int), f"{t}.{field} not int: {term[field]}"
                assert term[field] >= 0, f"{t}.{field} negative"

    def test_demand_pct_and_level(self, flights_payload):
        for t in TERMINALS:
            term = flights_payload[t]
            assert "demand_pct" in term
            assert isinstance(term["demand_pct"], int)
            assert 0 <= term["demand_pct"] <= 500
            assert "demand_level" in term
            assert term["demand_level"] in VALID_LEVELS

    def test_demand_level_matches_pct(self, flights_payload):
        for t in TERMINALS:
            term = flights_payload[t]
            pct = term["demand_pct"]
            lvl = term["demand_level"]
            if pct > 100:
                expected = "critica"
            elif pct >= 70:
                expected = "alta"
            elif pct >= 40:
                expected = "media"
            else:
                expected = "baja"
            assert lvl == expected, f"{t}: pct={pct} → expected {expected}, got {lvl}"

    def test_grande_le_total_tagged(self, flights_payload):
        """grande counts long-haul flights that are also inside a P/E/F/S bucket."""
        for t in TERMINALS:
            term = flights_payload[t]
            total_tagged = term["proximos"] + term["equipaje"] + term["finalizado"] + term["siguientes"]
            assert term["grande"] <= total_tagged, (
                f"{t}: grande={term['grande']} exceeds total tagged={total_tagged}"
            )


class TestArrivalStatusTag:
    """status_tag and is_large fields on arrival objects."""

    def test_arrivals_have_optional_status_tag(self, flights_payload):
        for t in TERMINALS:
            arrivals = flights_payload[t].get("arrivals", [])
            assert isinstance(arrivals, list)
            for a in arrivals:
                tag = a.get("status_tag")
                assert tag in VALID_TAGS, f"{t} flight {a.get('flight_number')} bad tag: {tag}"

    def test_arrivals_have_optional_is_large(self, flights_payload):
        for t in TERMINALS:
            for a in flights_payload[t].get("arrivals", []):
                il = a.get("is_large")
                assert il is None or isinstance(il, bool), (
                    f"{t} flight {a.get('flight_number')}: is_large={il} ({type(il).__name__})"
                )

    def test_status_tag_counts_consistent(self, flights_payload):
        """Counts of tagged arrivals (in returned subset) should be ≤ aggregate buckets.
        Aggregates are computed over the FULL raw_arrivals list while terminal.arrivals
        is the trimmed display list, so the trimmed list cannot exceed the aggregates."""
        for t in TERMINALS:
            term = flights_payload[t]
            arrivals = term.get("arrivals", [])
            counts = {"proximo": 0, "siguiente": 0, "equipaje": 0, "finalizado": 0}
            for a in arrivals:
                tag = a.get("status_tag")
                if tag in counts:
                    counts[tag] += 1
            assert counts["proximo"] <= term["proximos"], f"{t}: arrivals proximo={counts['proximo']} > agg {term['proximos']}"
            assert counts["siguiente"] <= term["siguientes"], f"{t}: arrivals siguiente={counts['siguiente']} > agg {term['siguientes']}"
            assert counts["equipaje"] <= term["equipaje"], f"{t}: arrivals equipaje={counts['equipaje']} > agg {term['equipaje']}"
            assert counts["finalizado"] <= term["finalizado"], f"{t}: arrivals finalizado={counts['finalizado']} > agg {term['finalizado']}"


class TestBackwardCompatibility:
    """Old fields used by legacy UI still present."""

    def test_old_fields_present(self, flights_payload):
        for t in TERMINALS:
            term = flights_payload[t]
            assert "total_next_30min" in term
            assert isinstance(term["total_next_30min"], int)
            assert "total_next_60min" in term
            assert "score_30min" in term  # may be None or float
            assert "past_30min" in term

    def test_instant_pressure_still_returned(self, flights_payload):
        """The pre-existing instant pressure feature must remain intact."""
        for t in TERMINALS:
            term = flights_payload[t]
            assert "instant_pressure_pct" in term
            assert "instant_pressure_level" in term
            assert "instant_pressure_trend" in term

    def test_demand_pct_equals_instant_pressure_pct(self, flights_payload):
        """Per server.py:2144, demand_pct mirrors instant_pressure_pct."""
        for t in TERMINALS:
            term = flights_payload[t]
            if term["instant_pressure_pct"] is not None:
                assert term["demand_pct"] == term["instant_pressure_pct"]
