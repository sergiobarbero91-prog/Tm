# Emisora: fixed driver QR/code + printable business card
import io
import os
import time
import uuid

import pytest
import requests
from PIL import Image

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL")
if not BASE:
    for line in open("/app/frontend/.env"):
        if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
            BASE = line.split("=", 1)[1].strip().strip('"')
API = BASE.rstrip("/") + "/api"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{API}/auth/login", json={"username": "admin", "password": "admin"}, timeout=15)
    assert r.status_code == 200
    return r.json()["access_token"]


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def test_qr_fixed_across_many_calls(token):
    qs = [requests.post(f"{API}/rides/driver/qr", headers=_h(token), timeout=10).json() for _ in range(3)]
    assert len({q["token"] for q in qs}) == 1
    assert len({q["verification_code"] for q in qs}) == 1
    code = qs[0]["verification_code"]
    assert code.isdigit() and len(code) == 6
    assert qs[0]["url"] == f"https://www.asdelvolante.es/?cliente_qr={qs[0]['token']}"


def test_rotate_removed(token):
    r = requests.post(f"{API}/rides/driver/qr/rotate", headers=_h(token), timeout=10)
    assert r.status_code in (404, 405)


def test_card_png(token):
    r = requests.get(f"{API}/rides/driver/qr/card.png", headers=_h(token), timeout=20)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert "tarjeta-taxi.png" in r.headers.get("content-disposition", "")
    img = Image.open(io.BytesIO(r.content))
    assert img.size == (1004, 650)
    # Decode QR if pyzbar/opencv available
    try:
        import cv2
        import numpy as np
        arr = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
        data, _, _ = cv2.QRCodeDetector().detectAndDecode(arr)
        q = requests.post(f"{API}/rides/driver/qr", headers=_h(token), timeout=10).json()
        if data:
            assert data == q["url"]
            print("QR decoded:", data)
    except ImportError:
        pass


def test_card_requires_auth():
    assert requests.get(f"{API}/rides/driver/qr/card.png", timeout=10).status_code in (401, 403)


def test_client_auth_with_fixed_code(token):
    q = requests.post(f"{API}/rides/driver/qr", headers=_h(token), timeout=10).json()
    phone = f"+3469{int(time.time()) % 10000000:07d}"
    body = {"phone": phone, "first_name": "TEST_Card", "last_name": "Client",
            "qr_token": q["token"], "verification_code": q["verification_code"]}
    r = requests.post(f"{API}/rides/client/authenticate", json=body, timeout=10)
    assert r.status_code == 200, r.text
    assert r.json()["client"]["associated_driver_id"] == q["driver_id"]
    wrong = str((int(q["verification_code"]) + 1) % 1_000_000).zfill(6)
    r2 = requests.post(f"{API}/rides/client/authenticate", json={**body, "verification_code": wrong}, timeout=10)
    assert r2.status_code == 400
    # code still fixed after client usage
    q2 = requests.post(f"{API}/rides/driver/qr", headers=_h(token), timeout=10).json()
    assert q2["verification_code"] == q["verification_code"]
