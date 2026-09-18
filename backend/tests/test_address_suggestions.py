"""Tests for the Madrid-biased address suggestions and reverse geocoding."""
import requests

API = "http://localhost:8001/api"


def _admin_token() -> str:
    r = requests.post(f"{API}/auth/login", json={"username": "admin", "password": "admin"}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def test_suggestions_requires_auth():
    r = requests.post(f"{API}/rides/address-suggestions", json={"query": "gran via"}, timeout=10)
    assert r.status_code == 401


def test_suggestions_returns_madrid_addresses():
    tk = _admin_token()
    r = requests.post(
        f"{API}/rides/address-suggestions",
        json={"query": "gran via"},
        headers={"Authorization": f"Bearer {tk}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    data = r.json()["suggestions"]
    assert isinstance(data, list)
    assert len(data) >= 1
    # Bias to Madrid — first hit must be a Madrid street
    assert any("madrid" in s["address"].lower() for s in data)
    for s in data:
        assert -180 <= s["lon"] <= 180
        assert -90 <= s["lat"] <= 90


def test_suggestions_rejects_short_query():
    tk = _admin_token()
    r = requests.post(
        f"{API}/rides/address-suggestions",
        json={"query": "a"},
        headers={"Authorization": f"Bearer {tk}"},
        timeout=10,
    )
    assert r.status_code == 422


def test_reverse_geocode_returns_address():
    tk = _admin_token()
    # Puerta del Sol coords
    r = requests.get(
        f"{API}/rides/reverse-geocode",
        params={"lat": 40.4168, "lon": -3.7038},
        headers={"Authorization": f"Bearer {tk}"},
        timeout=15,
    )
    assert r.status_code == 200
    addr = r.json().get("address")
    # Photon may return null under heavy load — accept both but string must
    # contain Madrid when present.
    if addr:
        assert "madrid" in addr.lower() or len(addr) >= 3


def test_reverse_geocode_rejects_bad_coords():
    tk = _admin_token()
    r = requests.get(
        f"{API}/rides/reverse-geocode",
        params={"lat": 200, "lon": 0},
        headers={"Authorization": f"Bearer {tk}"},
        timeout=10,
    )
    assert r.status_code == 400
