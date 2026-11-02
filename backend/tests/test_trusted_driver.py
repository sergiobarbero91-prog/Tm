from datetime import datetime, timedelta, timezone
import os
import sys

import requests
from pymongo import MongoClient
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_rides import API, _client_login, _driver_login  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _ask(ct, prefer=True):
    return requests.post(f"{API}/rides/rides", json={"origin": "Atocha", "destination": "Sol", "ride_type": "asap",
                                                      "prefer_my_driver": prefer}, headers={"Authorization": f"Bearer {ct}"}, timeout=10)


def test_trusted_request_is_exclusive_for_30_min_then_goes_to_pool():
    dt = _driver_login()
    ct = _client_login("+34600999301", "Confianza", "Uno", driver_token=dt)
    r = _ask(ct)
    assert r.status_code == 200, r.text
    ride = r.json()
    assert ride["dispatch_scope"] == "assigned" and ride["preferred"]
    until = datetime.fromisoformat(ride["exclusive_until"].replace("Z", "+00:00"))
    assert 29 <= (until - datetime.now(timezone.utc)).total_seconds() / 60 <= 30.1
    H = {"Authorization": f"Bearer {dt}"}
    assert any(x["id"] == ride["id"] for x in requests.get(f"{API}/rides/driver/assigned", headers=H).json())
    assert not any(x["id"] == ride["id"] for x in requests.get(f"{API}/rides/driver/offers", headers=H).json())
    # simulate the 30 minutes passing
    db.rides.update_one({"id": ride["id"]}, {"$set": {"exclusive_until": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    assert any(x["id"] == ride["id"] for x in requests.get(f"{API}/rides/driver/offers", headers=H).json())
    mine = next(x for x in requests.get(f"{API}/rides/rides/mine", headers={"Authorization": f"Bearer {ct}"}).json() if x["id"] == ride["id"])
    assert mine["dispatch_scope"] == "open" and mine["preferred_released"]


def test_trusted_driver_accepts_within_window():
    dt = _driver_login()
    ct = _client_login("+34600999302", "Confianza", "Dos", driver_token=dt)
    ride = _ask(ct).json()
    a = requests.post(f"{API}/rides/rides/{ride['id']}/accept", headers={"Authorization": f"Bearer {dt}"}, timeout=10)
    assert a.status_code == 200 and a.json()["status"] == "accepted"


def test_driver_can_release_trusted_request_to_pool():
    dt = _driver_login()
    ct = _client_login("+34600999303", "Confianza", "Tres", driver_token=dt)
    ride = _ask(ct).json()
    r = requests.post(f"{API}/rides/rides/{ride['id']}/reject", headers={"Authorization": f"Bearer {dt}"}, timeout=10)
    assert r.status_code == 200 and r.json()["dispatch_scope"] == "open" and r.json()["preferred_released"]


def test_normal_asap_request_stays_open():
    dt = _driver_login()
    ct = _client_login("+34600999304", "Normal", "Cuatro", driver_token=dt)
    ride = _ask(ct, prefer=False).json()
    assert ride["dispatch_scope"] == "open" and not ride["preferred"]
