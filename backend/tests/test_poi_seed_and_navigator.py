"""Tests for POI seed density expansion and preferred_navigator profile field.

Runs against the external preview URL to mimic real client requests.
"""
import os
import uuid
import pytest
import requests

BASE = "https://tariff-tool.preview.emergentagent.com/api"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE}/auth/login",
                      json={"username": "admin", "password": "admin"}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ---------- Seed density ----------

def test_pharmacy_24_has_at_least_15(auth_headers):
    r = requests.get(f"{BASE}/pois", params={"type_key": "pharmacy_24"},
                     headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 15, f"Expected >=15 pharmacy_24, got {len(data)}"


def test_tobacco_24_has_at_least_8(auth_headers):
    r = requests.get(f"{BASE}/pois", params={"type_key": "tobacco_24"},
                     headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 8, f"Expected >=8 tobacco_24, got {len(data)}"


# ---------- Nearby ----------

def test_nearby_sol_has_close_pharmacy_and_tobacco(auth_headers):
    r = requests.get(f"{BASE}/pois/nearby",
                     params={"lat": 40.4168, "lon": -3.7038},
                     headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text
    entries = r.json()
    assert isinstance(entries, list) and len(entries) > 0

    # All builtin non-manual types must have closest
    for e in entries:
        t = e["type"]
        if t.get("builtin") and not t.get("manual_only"):
            assert e["closest"] is not None, f"{t['key']} sin closest"
            assert "distance_km" in e["closest"]

    pharm = next((e for e in entries if e["type"]["key"] == "pharmacy_24"), None)
    tob = next((e for e in entries if e["type"]["key"] == "tobacco_24"), None)
    assert pharm and pharm["closest"], "pharmacy_24 sin closest"
    assert tob and tob["closest"], "tobacco_24 sin closest"
    assert pharm["closest"]["distance_km"] < 1.0, \
        f"pharmacy too far: {pharm['closest']['distance_km']}"
    assert tob["closest"]["distance_km"] < 1.0, \
        f"tobacco too far: {tob['closest']['distance_km']}"


# ---------- preferred_navigator profile ----------

def test_profile_update_preferred_navigator_waze(auth_headers):
    r = requests.put(f"{BASE}/auth/profile",
                     json={"preferred_navigator": "waze"},
                     headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("preferred_navigator") == "waze", body

    me = requests.get(f"{BASE}/auth/me", headers=auth_headers, timeout=15)
    assert me.status_code == 200
    assert me.json().get("preferred_navigator") == "waze"


def test_profile_update_preferred_navigator_google_maps(auth_headers):
    r = requests.put(f"{BASE}/auth/profile",
                     json={"preferred_navigator": "google_maps"},
                     headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json().get("preferred_navigator") == "google_maps"

    me = requests.get(f"{BASE}/auth/me", headers=auth_headers, timeout=15)
    assert me.json().get("preferred_navigator") == "google_maps"


def test_profile_update_preferred_navigator_invalid_returns_400(auth_headers):
    r = requests.put(f"{BASE}/auth/profile",
                     json={"preferred_navigator": "apple_maps"},
                     headers=auth_headers, timeout=15)
    assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"


# ---------- POI CRUD still works ----------

def test_poi_create_update_flow(auth_headers):
    payload = {
        "type_key": "pharmacy_24",
        "name": f"TEST_Farmacia_{uuid.uuid4().hex[:6]}",
        "address": "Calle Test 1",
        "lat": 40.4170,
        "lon": -3.7040,
    }
    c = requests.post(f"{BASE}/pois", json=payload, headers=auth_headers, timeout=15)
    assert c.status_code == 200, c.text
    poi_id = c.json()["id"]

    u = requests.put(f"{BASE}/pois/{poi_id}",
                     json={"name": payload["name"] + "_upd"},
                     headers=auth_headers, timeout=15)
    assert u.status_code == 200, u.text
    assert u.json()["name"].endswith("_upd")

    # cleanup
    requests.delete(f"{BASE}/pois/{poi_id}", headers=auth_headers, timeout=15)


# ---------- Delete builtin type forbidden ----------

def test_delete_builtin_type_forbidden(auth_headers):
    types = requests.get(f"{BASE}/pois/types", headers=auth_headers, timeout=15).json()
    builtin = next(t for t in types if t.get("builtin"))
    r = requests.delete(f"{BASE}/pois/types/{builtin['id']}",
                        headers=auth_headers, timeout=15)
    assert r.status_code == 400, f"Expected 400, got {r.status_code}"


# ---------- Regression: driver offers ordered by distance ----------

def test_driver_offers_ordered_by_distance(auth_headers):
    r = requests.get(f"{BASE}/rides/driver/offers",
                     params={"lat": 40.4168, "lon": -3.7038},
                     headers=auth_headers, timeout=15)
    # accept 200 or 403 (if admin isn't a driver). Only assert ordering if 200.
    assert r.status_code in (200, 403), r.text
    if r.status_code == 200:
        offers = r.json()
        distances = [o.get("distance_km") for o in offers if o.get("distance_km") is not None]
        assert distances == sorted(distances), f"Not sorted: {distances}"
