# Live API regression for GET /api/buses (Avanza live Estación Sur + Alsa GTFS Av. América)
import os
from datetime import datetime, timedelta

import pytest
import pytz
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
if not BASE_URL:
    for line in open("/app/frontend/.env"):
        if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
MADRID = pytz.timezone("Europe/Madrid")
SHORT = {"Alcala De Henares", "Alcalá De Henares", "Guadalajara", "Torrejon De Ardoz", "Torrejón De Ardoz"}


@pytest.fixture(scope="module")
def data():
    r = requests.get(f"{BASE_URL}/api/buses", timeout=60)
    assert r.status_code == 200
    return r.json()


def test_avenida_america_gtfs(data):
    aa = data["avenida_america"]
    if aa["source"] != "alsa_gtfs":
        pytest.skip(f"no GTFS arrivals in window, source={aa['source']}")
    assert aa["source_label"] == "Horarios programados de Alsa (sin retrasos)"
    for a in aa["arrivals"]:
        assert a["status"] == "Programado" and a["bus_company"] == "ALSA"
        assert a["origin"] not in SHORT


def test_estacion_sur_live(data):
    es = data["estacion_sur"]
    assert es["source"] == "avanza_live", es["source"]
    assert es["source_label"] == "En directo · panel de Estación Sur (Avanza)"
    assert es["arrivals"]
    assert {a["status"] for a in es["arrivals"]} <= {"En dársena", "Retrasado", "Programado"}
    for a in es["arrivals"]:
        if a["status"] == "En dársena":
            assert a["platform"]


def test_counts_and_winners(data):
    for w in ("30min", "60min"):
        flags = [data[k][f"is_winner_{w}"] for k in ("avenida_america", "estacion_sur")]
        assert sum(flags) == 1
        win = data[f"winner_{w}"]
        assert data[win][f"is_winner_{w}"]
    for k in ("avenida_america", "estacion_sur"):
        s = data[k]
        assert s["total_next_30min"] <= s["total_next_60min"]
        assert s["past_30min"] <= s["past_60min"]
        assert s["score_30min"] == round(s["total_next_30min"] * 0.7 + s["past_30min"] * 0.3, 2)
        assert s["score_60min"] == round(s["total_next_60min"] * 0.7 + s["past_60min"] * 0.3, 2)
    aa, es = data["avenida_america"], data["estacion_sur"]
    for w in ("30min", "60min"):
        exp = "avenida_america" if aa[f"score_{w}"] >= es[f"score_{w}"] else "estacion_sur"
        assert data[f"winner_{w}"] == exp
