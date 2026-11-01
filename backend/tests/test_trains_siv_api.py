# API tests for /api/trains with Adif SIV primary source
import os
import re
from datetime import datetime, timedelta

import pytz
import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
MADRID = pytz.timezone("Europe/Madrid")
HHMM = re.compile(r"^\d{2}:\d{2}$")
STATUS = re.compile(r"^(En hora|Retraso \d+ min|Adelantado)$")


@pytest.fixture(scope="module")
def trains():
    r = requests.get(f"{BASE_URL}/api/trains", timeout=90)
    assert r.status_code == 200
    return r.json()


@pytest.mark.parametrize("st", ["atocha", "chamartin"])
def test_siv_fields(trains, st):
    s = trains[st]
    if s.get("source") != "siv":
        pytest.skip("SIV unreachable - legacy fallback")
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", s["data_time"])
    assert isinstance(s["cancelled_count"], int)
    assert isinstance(s["alerts"], list)
    for a in s["alerts"]:
        assert set(a) >= {"id", "level", "header", "text"}


@pytest.mark.parametrize("st", ["atocha", "chamartin"])
def test_arrival_shape(trains, st):
    for a in trains[st]["arrivals"]:
        assert a["train_type"] != "C"
        assert HHMM.match(a["time"]) and HHMM.match(a["scheduled_time"])
        assert a["origin"] and a["train_number"] and a["platform"]
        assert STATUS.match(a["status"]), a["status"]
        d = a["delay_minutes"]
        exp = (datetime.strptime(a["scheduled_time"], "%H:%M") + timedelta(minutes=d)).strftime("%H:%M")
        assert exp == a["time"]
        assert a["operator"] in ("Renfe", "Iryo", "Ouigo")


@pytest.mark.parametrize("st", ["atocha", "chamartin"])
def test_counts_coherent(trains, st):
    s = trains[st]
    now = datetime.now(MADRID)

    def mins(a):
        t = MADRID.localize(datetime.strptime(a["time"], "%H:%M").replace(year=now.year, month=now.month, day=now.day))
        if t < now - timedelta(hours=6):
            t += timedelta(days=1)
        return (t - now).total_seconds() / 60

    m = [mins(a) for a in s["arrivals"]]
    n30 = sum(1 for x in m if 0 <= x <= 30)
    n60 = sum(1 for x in m if 0 <= x <= 60)
    assert abs(s["total_next_30min"] - n30) <= 1
    assert abs(s["total_next_60min"] - n60) <= 1
    assert s["total_next_30min"] <= s["total_next_60min"]
    listed_past15 = sum(1 for x in m if -15 <= x < 0)
    assert s["past_30min"] >= listed_past15 - 1


def test_custom_past_window():
    now = datetime.now(MADRID)
    start = (now - timedelta(hours=3)).strftime("%H:%M")
    end = (now - timedelta(hours=2)).strftime("%H:%M")
    r = requests.get(f"{BASE_URL}/api/trains", params={"start_time": start, "end_time": end}, timeout=90)
    assert r.status_code == 200, r.text
    d = r.json()
    for st in ("atocha", "chamartin"):
        assert "arrivals" in d[st]
        assert d[st].get("source") in (None, "")
