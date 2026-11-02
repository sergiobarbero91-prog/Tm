# Helper (not a test): creates linked + unlinked client sessions for UI testing, prints JSON
import json, os, sys, requests
from dotenv import load_dotenv
from pymongo import MongoClient
load_dotenv("/app/frontend/.env"); load_dotenv("/app/backend/.env")
API = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") + "/api"
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
dt = requests.post(f"{API}/auth/login", json={"username": "admin", "password": "admin"}).json()["access_token"]


def client(phone, fn, ln):
    qr = requests.post(f"{API}/rides/driver/qr", headers={"Authorization": f"Bearer {dt}"}).json()
    r = requests.post(f"{API}/rides/client/authenticate", json={"phone": phone, "first_name": fn, "last_name": ln,
                      "qr_token": qr["token"], "verification_code": qr["verification_code"]}).json()
    return r


mode = sys.argv[1] if len(sys.argv) > 1 else "sessions"
if mode == "sessions":
    linked = client("+34600999501", "TEST_UI", "Linked")
    unlinked = client("+34600999502", "TEST_UI", "Unlinked")
    for c in db.list_collection_names():
        db[c].update_many({"phone": "+34600999502", "associated_driver_id": {"$exists": True}}, {"$set": {"associated_driver_id": None}})
    unlinked["client"]["associated_driver_id"] = None
    print(json.dumps({"linked": linked, "unlinked": unlinked, "driver_token": dt}))
elif mode == "ride":
    ct = client("+34600999503", "TEST_Cliente", sys.argv[2] if len(sys.argv) > 2 else "Modal")["access_token"]
    r = requests.post(f"{API}/rides/rides", json={"origin": "TEST Calle Mayor 1", "destination": "TEST Aeropuerto T4",
                      "ride_type": "asap", "prefer_my_driver": True}, headers={"Authorization": f"Bearer {ct}"}).json()
    print(json.dumps({"id": r["id"], "ct": ct}))
elif mode == "cleanup":
    n = db.rides.update_many({"status": {"$in": ["pending", "accepted"]}, "$or": [{"origin": {"$regex": "^TEST"}}, {"client_name": {"$regex": "^(TEST_|Confianza|Normal)"}}]},
                             {"$set": {"status": "cancelled"}})
    print("cancelled", n.modified_count)
