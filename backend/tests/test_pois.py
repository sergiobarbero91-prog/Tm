"""POI catalogue: types + sites + nearest lookup."""
import requests

API = "http://localhost:8001/api"


def _admin_token() -> str:
    r = requests.post(f"{API}/auth/login", json={"username": "admin", "password": "admin"}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def test_types_seeded_and_listable():
    tk = _admin_token()
    r = requests.get(f"{API}/pois/types", headers={"Authorization": f"Bearer {tk}"}, timeout=10)
    assert r.status_code == 200
    keys = {t["key"] for t in r.json()}
    for expected in {"hospital_er", "pharmacy_24", "fuel_24", "nightlife", "tobacco_24", "nightclub"}:
        assert expected in keys, f"Falta el tipo {expected}"


def test_nearby_returns_closest_per_type():
    tk = _admin_token()
    # Puerta del Sol
    r = requests.get(
        f"{API}/pois/nearby",
        params={"lat": 40.4168, "lon": -3.7038},
        headers={"Authorization": f"Bearer {tk}"},
        timeout=10,
    )
    assert r.status_code == 200
    entries = r.json()
    assert isinstance(entries, list) and len(entries) >= 6
    for e in entries:
        assert "type" in e and "closest" in e
        if e["type"]["key"] == "nightlife":
            # Manual-only category — closest may be None.
            continue
        # Rest should have at least one seed.
        assert e["closest"] is not None
        assert 0 <= e["closest"]["distance_km"] < 500


def test_admin_can_create_type_and_site_prevails_over_seed():
    tk = _admin_token()
    # Add a bogus custom type
    r = requests.post(
        f"{API}/pois/types",
        json={"key": "test_custom", "label": "Test Custom", "icon": "flag", "manual_only": False},
        headers={"Authorization": f"Bearer {tk}"},
        timeout=10,
    )
    # 200 first time, 409 on rerun — both OK
    assert r.status_code in (200, 409)

    # Add a site near Sol under 'pharmacy_24' — should beat the seed
    site = requests.post(
        f"{API}/pois",
        json={
            "type_key": "pharmacy_24",
            "name": "Farmacia Test Sol",
            "address": "Sol 1",
            "lat": 40.4169, "lon": -3.7037,
        },
        headers={"Authorization": f"Bearer {tk}"},
        timeout=10,
    )
    assert site.status_code == 200, site.text
    site_id = site.json()["id"]

    r = requests.get(
        f"{API}/pois/nearby",
        params={"lat": 40.4168, "lon": -3.7038},
        headers={"Authorization": f"Bearer {tk}"},
        timeout=10,
    )
    entries = r.json()
    pharm = next(e for e in entries if e["type"]["key"] == "pharmacy_24")
    assert pharm["closest"]["name"] == "Farmacia Test Sol"

    # Cleanup
    requests.delete(f"{API}/pois/{site_id}", headers={"Authorization": f"Bearer {tk}"}, timeout=10)


def test_delete_builtin_type_forbidden():
    tk = _admin_token()
    # Fetch builtin type id
    types = requests.get(f"{API}/pois/types", headers={"Authorization": f"Bearer {tk}"}, timeout=10).json()
    builtin = next(t for t in types if t["key"] == "hospital_er")
    r = requests.delete(
        f"{API}/pois/types/{builtin['id']}",
        headers={"Authorization": f"Bearer {tk}"},
        timeout=10,
    )
    assert r.status_code == 400


def test_nearby_requires_auth():
    r = requests.get(f"{API}/pois/nearby", params={"lat": 40.4, "lon": -3.7}, timeout=10)
    assert r.status_code == 401
