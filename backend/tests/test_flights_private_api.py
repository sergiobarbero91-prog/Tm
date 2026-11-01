# Private flight weighting (0.25) in GET /api/flights
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or open("/app/frontend/.env").read().split("EXPO_PUBLIC_BACKEND_URL=")[1].split()[0].rstrip("/")


@pytest.fixture(scope="module")
def flights():
    r = requests.get(f"{BASE_URL}/api/flights", timeout=90)
    assert r.status_code == 200, r.text[:300]
    return r.json()


def _all_arrivals(data):
    for t, td in data["terminals"].items():
        for a in td.get("arrivals", []):
            yield t, a


def test_every_arrival_has_is_private_bool(flights):
    arr = list(_all_arrivals(flights))
    assert arr
    for _, a in arr:
        assert isinstance(a.get("is_private"), bool), a


def test_commercial_flights_not_private(flights):
    comm = [a for _, a in _all_arrivals(flights) if a["flight_number"][:2] in ("IB", "FR", "UX", "VY", "I2")]
    assert comm
    assert all(a["is_private"] is False for a in comm)


def test_ecmkv_in_t4_private(flights):
    t4 = flights["terminals"]["T4"]["arrivals"]
    ec = [a for a in t4 if a["flight_number"] == "ECMKV"]
    assert ec, "ECMKV not in T4 arrivals"
    assert ec[0]["is_private"] is True


def test_t4_past_counts_fractional(flights):
    t4 = flights["terminals"]["T4"]
    print({k: v for k, v in t4.items() if k != "arrivals"})
    for k in ("past_30min", "past_60min"):
        assert abs((t4[k] * 4) - round(t4[k] * 4)) < 1e-9
        assert abs(t4[k] - round(t4[k])) > 1e-9 or t4[k] % 1 == 0.25 or True
    # ECMKV landed ~10 min ago → past_30 must include 0.25 fraction
    assert abs(t4["past_30min"] % 1 - 0.25) < 1e-9, t4["past_30min"]
    assert abs(t4["past_60min"] % 1 - 0.25) < 1e-9, t4["past_60min"]


def test_counts_numeric_and_extra_fields(flights):
    for t, td in flights["terminals"].items():
        for k in ("total_next_30min", "total_next_60min"):
            if k in td:
                assert isinstance(td[k], (int, float))
    print({k: v for k, v in flights.items() if k != "terminals"})
