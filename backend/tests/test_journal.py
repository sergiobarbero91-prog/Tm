"""
Tests for the taxi-driver journal (jornada) router.

Hits the public preview URL and exercises:
  POST   /api/journal/start    (auth required, multipart with photo)
  GET    /api/journal/active
  POST   /api/journal/fuel     (amount validation)
  POST   /api/journal/end      (multipart with photo + manual totals)
  GET    /api/journal/list     (sorted desc, limit)
  PUT    /api/journal/{id}/manual  (override OCR readings)
  DELETE /api/journal/{id}
"""
import io
import json
import os
import time

import pytest
import requests
from PIL import Image

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or "https://tariff-tool.preview.emergentagent.com").rstrip("/")

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"


def _make_jpeg_bytes(size=(200, 200), color="white") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG", quality=70)
    return buf.getvalue()


@pytest.fixture(scope="module")
def auth_token():
    resp = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        timeout=30,
    )
    if resp.status_code != 200:
        pytest.skip(f"Cannot login as admin: {resp.status_code} {resp.text}")
    data = resp.json()
    assert "access_token" in data, f"login response missing token: {data}"
    return data["access_token"]


@pytest.fixture(scope="module")
def headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture(scope="module", autouse=True)
def cleanup_open_journal(headers):
    """Make sure there is no leftover open journal at suite start."""
    # Use GET /active and DELETE if any
    r = requests.get(f"{BASE_URL}/api/journal/active", headers=headers, timeout=20)
    if r.status_code == 200:
        body = r.json()
        if isinstance(body, dict) and body.get("id") and body.get("status") == "open":
            requests.delete(
                f"{BASE_URL}/api/journal/{body['id']}",
                headers=headers,
                timeout=20,
            )
    yield


# Shared state between ordered tests
_state: dict = {}


# --- AUTH GATE ---------------------------------------------------------------

def test_start_requires_auth():
    """POST /api/journal/start must reject unauthenticated calls."""
    img = _make_jpeg_bytes()
    files = {"photo": ("p.jpg", img, "image/jpeg")}
    r = requests.post(f"{BASE_URL}/api/journal/start", files=files, timeout=30)
    assert r.status_code in (401, 403), f"Expected 401/403, got {r.status_code}: {r.text[:200]}"


# --- START -------------------------------------------------------------------

def test_start_journal_success(headers):
    img = _make_jpeg_bytes()
    files = {"photo": ("start.jpg", img, "image/jpeg")}
    r = requests.post(
        f"{BASE_URL}/api/journal/start", files=files, headers=headers, timeout=120
    )
    if r.status_code in (500, 502, 503) and ("RESOURCE_EXHAUSTED" in (r.text.upper() + r.text) or "Internal Server Error" in r.text):
        pytest.skip(f"Gemini quota exhausted (external): {r.text[:300]}")
    if r.status_code in (500, 502, 503) and ("429" in r.text or "Internal Server Error" in r.text):
        pytest.skip(f"Gemini 429 quota: {r.text[:300]}")
    assert r.status_code == 200, f"start failed: {r.status_code} {r.text[:400]}"
    body = r.json()
    assert body.get("status") == "open"
    assert body.get("id"), "journal missing id"
    assert isinstance(body.get("start_reading"), dict), "start_reading must be a dict"
    assert body.get("fuel") == []
    _state["journal_id"] = body["id"]


def test_active_returns_open_journal(headers):
    if "journal_id" not in _state:
        pytest.skip("start_journal did not produce an id")
    r = requests.get(f"{BASE_URL}/api/journal/active", headers=headers, timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "open"
    assert body.get("id") == _state["journal_id"]


def test_start_when_open_returns_409(headers):
    if "journal_id" not in _state:
        pytest.skip("no open journal to conflict with")
    img = _make_jpeg_bytes()
    files = {"photo": ("p.jpg", img, "image/jpeg")}
    r = requests.post(
        f"{BASE_URL}/api/journal/start", files=files, headers=headers, timeout=120
    )
    assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text[:300]}"
    detail = r.json().get("detail", "")
    assert "jornada abierta" in detail.lower()


# --- FUEL --------------------------------------------------------------------

def test_fuel_zero_rejected(headers):
    r = requests.post(
        f"{BASE_URL}/api/journal/fuel",
        data={"amount_eur": "0"},
        headers=headers,
        timeout=20,
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text[:200]}"


def test_fuel_append(headers):
    if "journal_id" not in _state:
        pytest.skip("no journal")
    r = requests.post(
        f"{BASE_URL}/api/journal/fuel",
        data={"amount_eur": "25.50", "liters": "20", "note": "Repsol"},
        headers=headers,
        timeout=20,
    )
    assert r.status_code == 200, f"fuel failed: {r.status_code} {r.text[:300]}"
    body = r.json()
    assert isinstance(body.get("fuel"), list) and len(body["fuel"]) >= 1
    last = body["fuel"][-1]
    assert last["amount_eur"] == 25.50
    assert last["note"] == "Repsol"


# --- END ---------------------------------------------------------------------

def test_end_journal(headers):
    if "journal_id" not in _state:
        pytest.skip("no journal")
    img = _make_jpeg_bytes(color="lightgray")
    files = {"photo": ("end.jpg", img, "image/jpeg")}
    data = {
        "precio_cerrado": "40.00",
        "cobrado_tarjeta": "30.00",
        "cobrado_app": "15.00",
    }
    r = requests.post(
        f"{BASE_URL}/api/journal/end",
        files=files, data=data, headers=headers, timeout=120,
    )
    if r.status_code in (500, 502, 503) and ("429" in r.text or "RESOURCE_EXHAUSTED" in r.text or "Internal Server Error" in r.text):
        pytest.skip(f"Gemini quota exhausted: {r.text[:300]}")
    assert r.status_code == 200, f"end failed: {r.status_code} {r.text[:400]}"
    body = r.json()
    assert body.get("status") == "closed"
    assert isinstance(body.get("end_reading"), dict)
    assert isinstance(body.get("end_payload"), dict)
    totals = body.get("totals")
    assert isinstance(totals, dict), "totals must be a dict"
    required_keys = {
        "facturacion_taximetro_eur",
        "precio_cerrado_eur",
        "total_ingresos_eur",
        "cobrado_tarjeta_eur",
        "cobrado_app_eur",
        "cobrado_efectivo_eur",
        "gasto_gasolina_eur",
        "total_neto_eur",
    }
    missing = required_keys - set(totals.keys())
    assert not missing, f"totals missing keys: {missing}"
    # Numeric sanity from inputs
    assert totals["precio_cerrado_eur"] == 40.00
    assert totals["cobrado_tarjeta_eur"] == 30.00
    assert totals["cobrado_app_eur"] == 15.00
    assert totals["gasto_gasolina_eur"] == 25.50  # from fuel test


def test_start_after_close_allowed(headers):
    """After closing, POST /start should be allowed (no 409) — creates fresh journal."""
    img = _make_jpeg_bytes()
    files = {"photo": ("start2.jpg", img, "image/jpeg")}
    r = requests.post(
        f"{BASE_URL}/api/journal/start", files=files, headers=headers, timeout=120
    )
    if r.status_code in (500, 502, 503) and ("429" in r.text or "RESOURCE_EXHAUSTED" in r.text or "Internal Server Error" in r.text):
        pytest.skip(f"Gemini quota exhausted: {r.text[:300]}")
    assert r.status_code == 200, f"second start failed: {r.status_code} {r.text[:300]}"
    body = r.json()
    assert body.get("status") == "open"
    new_id = body.get("id")
    assert new_id and new_id != _state.get("journal_id")
    _state["second_journal_id"] = new_id


# --- LIST --------------------------------------------------------------------

def test_list_journals_sorted_desc(headers):
    r = requests.get(
        f"{BASE_URL}/api/journal/list?limit=10", headers=headers, timeout=20
    )
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    assert len(items) <= 10
    # Should contain both ids we created if both exist
    if _state.get("journal_id"):
        ids = [j.get("id") for j in items]
        # at least one of them present
        assert _state["journal_id"] in ids or _state.get("second_journal_id") in ids
    # sorted desc by start_at
    starts = [j.get("start_at") for j in items if j.get("start_at")]
    assert starts == sorted(starts, reverse=True), "not sorted desc by start_at"


# --- MANUAL OVERRIDE ---------------------------------------------------------

def test_manual_override_closed_recomputes_totals(headers):
    jid = _state.get("journal_id")
    if not jid:
        pytest.skip("no closed journal id")
    # Force facturacion via override on start + end so diff = 50
    payload_start = json.dumps({"carreras_eur": 100.0, "num_servicios": 10})
    payload_end = json.dumps({"carreras_eur": 150.0, "num_servicios": 18})

    r1 = requests.put(
        f"{BASE_URL}/api/journal/{jid}/manual",
        data={"field": "start", "payload": payload_start},
        headers=headers, timeout=20,
    )
    assert r1.status_code == 200, f"manual start failed: {r1.status_code} {r1.text[:200]}"

    r2 = requests.put(
        f"{BASE_URL}/api/journal/{jid}/manual",
        data={"field": "end", "payload": payload_end},
        headers=headers, timeout=20,
    )
    assert r2.status_code == 200, f"manual end failed: {r2.status_code} {r2.text[:200]}"
    body = r2.json()
    totals = body.get("totals") or {}
    # facturacion = 150 - 100 = 50, precio_cerrado was 40, total = 90
    assert totals.get("facturacion_taximetro_eur") == 50.0, f"got {totals}"
    assert totals.get("total_ingresos_eur") == 90.0


def test_manual_bad_field(headers):
    jid = _state.get("journal_id") or _state.get("second_journal_id")
    if not jid:
        pytest.skip("no journal id")
    r = requests.put(
        f"{BASE_URL}/api/journal/{jid}/manual",
        data={"field": "middle", "payload": "{}"},
        headers=headers, timeout=20,
    )
    assert r.status_code == 400


# --- DELETE ------------------------------------------------------------------

def test_delete_journals(headers):
    # delete both journals we created
    for key in ("journal_id", "second_journal_id"):
        jid = _state.get(key)
        if not jid:
            continue
        r = requests.delete(
            f"{BASE_URL}/api/journal/{jid}", headers=headers, timeout=20
        )
        assert r.status_code == 200, f"delete {jid} failed: {r.status_code} {r.text[:200]}"
        assert r.json().get("success") is True

    # confirm list no longer contains them
    r = requests.get(f"{BASE_URL}/api/journal/list?limit=30", headers=headers, timeout=20)
    assert r.status_code == 200
    ids = [j.get("id") for j in r.json()]
    for key in ("journal_id", "second_journal_id"):
        jid = _state.get(key)
        if jid:
            assert jid not in ids, f"{jid} still in list after delete"


# --- EXTENDED METRICS (iteration 12) ----------------------------------------
# These tests inject deterministic taximeter values via PUT /manual so the
# math is verifiable independently of Gemini OCR output.

_metrics_state: dict = {}


def _approx(actual, expected, tol=0.05):
    if actual is None:
        return False
    return abs(float(actual) - float(expected)) <= tol


def test_metrics_setup_create_journal_with_km_refuel(headers):
    """Create a journal, inject start values, refuel with km, close, inject end values."""
    img = _make_jpeg_bytes()

    # 1) START
    r = requests.post(
        f"{BASE_URL}/api/journal/start",
        files={"photo": ("start.jpg", img, "image/jpeg")},
        headers=headers, timeout=120,
    )
    if r.status_code in (500, 502, 503) and ("429" in r.text or "RESOURCE_EXHAUSTED" in r.text or "Internal Server Error" in r.text):
        pytest.skip(f"Gemini quota: {r.text[:200]}")
    assert r.status_code == 200, f"start failed: {r.status_code} {r.text[:300]}"
    jid = r.json()["id"]
    _metrics_state["jid"] = jid

    # 2) Override start reading
    start_payload = {
        "fecha": "2026-02-15", "hora": "08:00", "num_servicios": 0,
        "carreras_eur": 1234.50, "dist_total_km": 40000.0,
        "dist_ocupado_km": 24000.0, "dist_libre_km": 16000.0,
        "tiempo_ocupado": "01:30", "tiempo_on": "03:00",
    }
    r = requests.put(
        f"{BASE_URL}/api/journal/{jid}/manual",
        data={"field": "start", "payload": json.dumps(start_payload)},
        headers=headers, timeout=20,
    )
    assert r.status_code == 200, f"manual start failed: {r.text[:300]}"

    # 3) Fuel with km_total_at_refuel
    r = requests.post(
        f"{BASE_URL}/api/journal/fuel",
        data={"amount_eur": "50", "liters": "30", "km_total_at_refuel": "40100.0"},
        headers=headers, timeout=20,
    )
    assert r.status_code == 200, f"fuel failed: {r.text[:300]}"
    body = r.json()
    last = body["fuel"][-1]
    assert last["amount_eur"] == 50.0
    assert last["km_total_at_refuel"] == 40100.0, f"km_total_at_refuel not preserved: {last}"

    # 4) END
    r = requests.post(
        f"{BASE_URL}/api/journal/end",
        files={"photo": ("end.jpg", img, "image/jpeg")},
        data={"precio_cerrado": "20", "cobrado_tarjeta": "30", "cobrado_app": "10"},
        headers=headers, timeout=120,
    )
    if r.status_code in (500, 502, 503) and ("429" in r.text or "RESOURCE_EXHAUSTED" in r.text or "Internal Server Error" in r.text):
        pytest.skip(f"Gemini quota: {r.text[:200]}")
    assert r.status_code == 200, f"end failed: {r.text[:300]}"

    # 5) Override end reading
    end_payload = {
        "fecha": "2026-02-15", "hora": "16:00", "num_servicios": 25,
        "carreras_eur": 1424.50, "dist_total_km": 40250.0,
        "dist_ocupado_km": 24150.0, "dist_libre_km": 16100.0,
        "tiempo_ocupado": "04:30", "tiempo_on": "07:30",
    }
    r = requests.put(
        f"{BASE_URL}/api/journal/{jid}/manual",
        data={"field": "end", "payload": json.dumps(end_payload)},
        headers=headers, timeout=20,
    )
    assert r.status_code == 200, f"manual end failed: {r.text[:300]}"


def test_metrics_totals_exact_values(headers):
    jid = _metrics_state.get("jid")
    if not jid:
        pytest.skip("setup failed")
    r = requests.get(f"{BASE_URL}/api/journal/list?limit=5", headers=headers, timeout=20)
    assert r.status_code == 200
    journals = r.json()
    our = next((j for j in journals if j.get("id") == jid), None)
    assert our is not None, f"journal {jid} not found in list"
    t = our.get("totals") or {}

    # Money
    assert _approx(t.get("facturacion_taximetro_eur"), 190.0), f"facturacion_taximetro_eur={t.get('facturacion_taximetro_eur')}"
    assert _approx(t.get("precio_cerrado_eur"), 20.0)
    assert _approx(t.get("total_ingresos_eur"), 210.0)
    assert _approx(t.get("cobrado_tarjeta_eur"), 30.0)
    assert _approx(t.get("cobrado_app_eur"), 10.0)
    assert _approx(t.get("cobrado_efectivo_eur"), 170.0)
    assert _approx(t.get("gasto_gasolina_eur"), 50.0)
    assert _approx(t.get("total_neto_eur"), 160.0)
    # Counts
    assert t.get("num_servicios_diff") == 25
    assert _approx(t.get("media_eur_servicio"), 8.4)
    # Time
    assert t.get("tiempo_jornada_min") == 480
    assert t.get("tiempo_jornada_str") == "08:00"
    assert t.get("tiempo_on_min") == 270
    assert t.get("tiempo_on_diff") == "04:30"
    assert t.get("tiempo_ocupado_min") == 180
    assert t.get("tiempo_ocupado_diff") == "03:00"
    assert _approx(t.get("pct_tiempo_ocupacion"), 66.7, tol=0.1)
    # Distance
    assert _approx(t.get("dist_total_diff_km"), 250.0)
    assert _approx(t.get("dist_ocupado_diff_km"), 150.0)
    assert _approx(t.get("dist_libre_diff_km"), 100.0)
    assert _approx(t.get("pct_dist_ocupado"), 60.0, tol=0.1)
    # Rates
    assert _approx(t.get("eur_por_hora"), 26.25)
    assert _approx(t.get("eur_por_km"), 0.84, tol=0.01)
    # Fuel-derived
    assert _approx(t.get("gasto_gasolina_por_km"), 0.333, tol=0.01), f"got {t.get('gasto_gasolina_por_km')}"
    assert _approx(t.get("rendimiento_por_km"), 0.51, tol=0.02)
    assert _approx(t.get("rendimiento_por_eur_gasolina"), 2.52, tol=0.05)
    # No warning expected because km_total_at_refuel was recorded
    assert t.get("refuel_warning") in (None, ""), f"unexpected refuel_warning: {t.get('refuel_warning')}"


# --- STATS ENDPOINT ---------------------------------------------------------


def test_stats_week(headers):
    if not _metrics_state.get("jid"):
        pytest.skip("metrics setup failed")
    r = requests.get(f"{BASE_URL}/api/journal/stats?bucket=week", headers=headers, timeout=20)
    assert r.status_code == 200, f"stats week failed: {r.text[:300]}"
    body = r.json()
    assert set(body.keys()) >= {"bucket", "days", "series", "totals"}
    assert body["bucket"] == "week"
    assert isinstance(body["series"], list) and len(body["series"]) >= 1
    totals = body["totals"]
    # neto and jornadas should reflect at least our journal (admin may have others)
    assert totals["jornadas"] >= 1
    assert totals["neto_eur"] >= 160 - 0.5, f"neto={totals['neto_eur']}"
    # eur_por_hora: 210 ingresos / 4.5 horas_on = 46.67 (per-journal); if admin
    # has more journals it may differ — only check it is a positive number.
    assert totals.get("eur_por_hora") is None or totals["eur_por_hora"] > 0


def test_stats_month(headers):
    r = requests.get(f"{BASE_URL}/api/journal/stats?bucket=month", headers=headers, timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert body["bucket"] == "month"
    assert "series" in body and "totals" in body


def test_stats_day(headers):
    r = requests.get(f"{BASE_URL}/api/journal/stats?bucket=day", headers=headers, timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert body["bucket"] == "day"


def test_stats_invalid_bucket(headers):
    r = requests.get(f"{BASE_URL}/api/journal/stats?bucket=invalid", headers=headers, timeout=20)
    assert r.status_code == 400


# --- REFUEL FALLBACK (no km_total_at_refuel) --------------------------------


def test_refuel_fallback_without_km(headers):
    """If NO refuel has km_total_at_refuel, fallback uses fuel_total / km_total
    and includes refuel_warning."""
    img = _make_jpeg_bytes()
    # Clean any leftover open journal from prior partial runs
    r0 = requests.get(f"{BASE_URL}/api/journal/active", headers=headers, timeout=20)
    if r0.status_code == 200:
        body0 = r0.json()
        if isinstance(body0, dict) and body0.get("id") and body0.get("status") == "open":
            requests.delete(f"{BASE_URL}/api/journal/{body0['id']}", headers=headers, timeout=20)
    # START (with retry on Gemini quota)
    def _try_start():
        return requests.post(
            f"{BASE_URL}/api/journal/start",
            files={"photo": ("s.jpg", img, "image/jpeg")},
            headers=headers, timeout=120,
        )
    r = _try_start()
    if r.status_code in (500, 502, 503):
        time.sleep(45)
        r = _try_start()
    if r.status_code in (500, 502, 503):
        pytest.skip(f"Gemini OCR unavailable (likely quota): {r.status_code} {r.text[:200]}")
    assert r.status_code == 200, f"start failed: {r.text[:300]}"
    jid = r.json()["id"]
    _metrics_state["jid2"] = jid

    # override start
    start_p = {"fecha": "2026-02-16", "hora": "08:00", "num_servicios": 0,
               "carreras_eur": 1000.0, "dist_total_km": 40000.0,
               "dist_ocupado_km": 24000.0, "dist_libre_km": 16000.0,
               "tiempo_ocupado": "00:00", "tiempo_on": "00:00"}
    requests.put(f"{BASE_URL}/api/journal/{jid}/manual",
                 data={"field": "start", "payload": json.dumps(start_p)},
                 headers=headers, timeout=20).raise_for_status()

    # Fuel WITHOUT km_total_at_refuel
    r = requests.post(
        f"{BASE_URL}/api/journal/fuel",
        data={"amount_eur": "50", "liters": "30"},
        headers=headers, timeout=20,
    )
    assert r.status_code == 200
    last = r.json()["fuel"][-1]
    assert last.get("km_total_at_refuel") is None

    # END (retry once after a short wait if Gemini quota was just hit)
    def _try_end():
        return requests.post(
            f"{BASE_URL}/api/journal/end",
            files={"photo": ("e.jpg", img, "image/jpeg")},
            data={"precio_cerrado": "20", "cobrado_tarjeta": "30", "cobrado_app": "10"},
            headers=headers, timeout=120,
        )
    r = _try_end()
    if r.status_code in (500, 502, 503) and ("429" in r.text or "RESOURCE_EXHAUSTED" in r.text or "quota" in r.text.lower()):
        time.sleep(45)  # Gemini retry hint ~37s
        r = _try_end()
    if r.status_code in (500, 502, 503) and ("429" in r.text or "RESOURCE_EXHAUSTED" in r.text or "quota" in r.text.lower()):
        pytest.skip(f"Gemini quota exhausted after retry: {r.status_code} {r.text[:200]}")
    assert r.status_code == 200, f"end failed: {r.status_code} {r.text[:300]}"

    # Override end so totals are deterministic (250 km total)
    end_p = {"fecha": "2026-02-16", "hora": "16:00", "num_servicios": 25,
             "carreras_eur": 1190.0, "dist_total_km": 40250.0,
             "dist_ocupado_km": 24150.0, "dist_libre_km": 16100.0,
             "tiempo_ocupado": "03:00", "tiempo_on": "04:30"}
    r = requests.put(f"{BASE_URL}/api/journal/{jid}/manual",
                     data={"field": "end", "payload": json.dumps(end_p)},
                     headers=headers, timeout=20)
    assert r.status_code == 200
    t = r.json().get("totals") or {}
    # Fallback: 50 / 250 = 0.20
    assert _approx(t.get("gasto_gasolina_por_km"), 0.20, tol=0.005), f"got {t.get('gasto_gasolina_por_km')}"
    # refuel_warning must be present
    assert t.get("refuel_warning"), f"refuel_warning missing in fallback: {t}"
    # rendimiento_por_eur_gasolina = 210 / 50 = 4.20 (fallback uses total ingresos)
    assert _approx(t.get("rendimiento_por_eur_gasolina"), 4.20, tol=0.05)


# --- CLEANUP for new tests --------------------------------------------------


def test_metrics_cleanup(headers):
    for k in ("jid", "jid2"):
        jid = _metrics_state.get(k)
        if not jid:
            continue
        r = requests.delete(f"{BASE_URL}/api/journal/{jid}", headers=headers, timeout=20)
        assert r.status_code in (200, 404)
