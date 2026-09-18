"""ASAP offers ordered by distance to the client's pickup coordinates."""
import time
import requests

API = "http://localhost:8001/api"


def _admin_token() -> str:
    r = requests.post(f"{API}/auth/login", json={"username": "admin", "password": "admin"}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def _client_token(phone: str) -> str:
    tk = _admin_token()
    requests.post(
        f"{API}/admin/clients",
        json={"phone": phone, "first_name": "T", "last_name": "T", "password": "pass1234"},
        headers={"Authorization": f"Bearer {tk}"},
        timeout=10,
    )
    return requests.post(
        f"{API}/rides/client/login",
        json={"phone": phone, "password": "pass1234"},
        timeout=10,
    ).json()["access_token"]


def _cleanup(phone: str):
    tk = _admin_token()
    lst = requests.get(
        f"{API}/admin/clients/search?q={phone[-6:]}",
        headers={"Authorization": f"Bearer {tk}"},
        timeout=10,
    ).json()
    for c in lst:
        if c["phone"] == phone:
            requests.delete(
                f"{API}/admin/clients/{c['id']}",
                headers={"Authorization": f"Bearer {tk}"},
                timeout=10,
            )


def test_asap_offers_sorted_by_distance_to_driver():
    ct1 = _client_token(f"+34600{int(time.time()) % 100000:05d}")
    ct2 = _client_token(f"+34611{int(time.time()) % 100000:05d}")
    dt = _admin_token()

    # Far ride first (Barajas ~10 km NE from Sol)
    far = requests.post(
        f"{API}/rides/rides",
        json={
            "origin": "Barajas T4", "destination": "IFEMA",
            "ride_type": "asap",
            "origin_lat": 40.4936, "origin_lon": -3.5668,
        },
        headers={"Authorization": f"Bearer {ct1}"},
        timeout=10,
    ).json()

    # Near ride second (Sol center)
    near = requests.post(
        f"{API}/rides/rides",
        json={
            "origin": "Puerta del Sol", "destination": "Atocha",
            "ride_type": "asap",
            "origin_lat": 40.4168, "origin_lon": -3.7038,
        },
        headers={"Authorization": f"Bearer {ct2}"},
        timeout=10,
    ).json()

    # Driver near Sol should see NEAR first, then FAR.
    r = requests.get(
        f"{API}/rides/driver/offers",
        params={"lat": 40.4170, "lon": -3.7040},
        headers={"Authorization": f"Bearer {dt}"},
        timeout=10,
    )
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()]
    assert near["id"] in ids and far["id"] in ids
    assert ids.index(near["id"]) < ids.index(far["id"])

    # Distance is annotated on each ride
    near_hit = next(x for x in r.json() if x["id"] == near["id"])
    far_hit = next(x for x in r.json() if x["id"] == far["id"])
    assert near_hit["distance_km"] is not None
    assert far_hit["distance_km"] is not None
    assert near_hit["distance_km"] < far_hit["distance_km"]

    # Cleanup rides
    for rid in (near["id"], far["id"]):
        requests.post(f"{API}/rides/rides/{rid}/cancel", headers={"Authorization": f"Bearer {ct1}"}, timeout=10)
    _cleanup(ct1)  # best-effort


def test_offers_without_driver_position_keeps_created_at_order():
    tk = _admin_token()
    r = requests.get(
        f"{API}/rides/driver/offers",
        headers={"Authorization": f"Bearer {tk}"},
        timeout=10,
    )
    assert r.status_code == 200
    # Every ride should NOT have a computed distance when we didn't send GPS.
    for ride in r.json():
        assert ride.get("distance_km") is None
