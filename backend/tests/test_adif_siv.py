import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adif_siv import MADRID_TZ, parse_siv_payload  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "siv", "atocha_60000.json")
NOW = MADRID_TZ.localize(datetime(2026, 11, 1, 22, 5))


def _train(number, arrival, delay=0, status="running", traffic="L", class_stop="destination", also=None, product="AVE"):
    return {
        "commercial_id": [{"numbers": [number] + (also or []), "product": product}],
        "company": "Renfe", "traffic_type": traffic, "class_stop": class_stop, "status": status,
        "arrival_time": arrival, "delay_in": delay, "platform_in": "5", "origins": [{"code": "71801"}],
    }


def _payload(trains, alerts=None):
    return {"station_settings": {"code": "60000"}, "trains": trains,
            "stations": {"71801": {"name": ["Barcelona Sants"]}}, "station_alerts": alerts or []}


def test_real_snapshot_parses_long_distance_only():
    with open(FIXTURE) as f:
        data = json.load(f)
    res = parse_siv_payload(data, now=NOW)
    assert res["arrivals"], "expected arrivals from real Atocha snapshot"
    for a in res["arrivals"]:
        assert a["train_type"] != "C"
        assert len(a["time"]) == 5 and a["origin"]
    assert {a["operator"] for a in res["arrivals"]} & {"Renfe", "Iryo"}
    assert any("huelga" in al["header"].lower() for al in res["alerts"])


def test_delay_cancel_coupled_and_cercanias():
    trains = [
        _train("03192", "2026-11-01T22:17:00+01:00", delay=6),
        _train("08213", "2026-11-01T22:15:00+01:00", delay=-7, product="AVANT"),
        _train("06190", "2026-11-01T22:30:00+01:00", status="cancelled", product="IRYO"),
        _train("05000", "2026-11-01T22:40:00+01:00", also=["05001"]),
        _train("05001", "2026-11-01T22:40:00+01:00"),
        _train("99999", "2026-11-01T22:20:00+01:00", traffic="C"),
        _train("11111", "2026-11-01T22:20:00+01:00", class_stop="origin"),
    ]
    res = parse_siv_payload(_payload(trains), now=NOW)
    by_num = {a["train_number"]: a for a in res["arrivals"]}
    assert set(by_num) == {"03192", "08213", "05000"}
    assert by_num["03192"]["time"] == "22:23" and by_num["03192"]["status"] == "Retraso 6 min"
    assert by_num["08213"]["time"] == "22:08" and by_num["08213"]["status"] == "Adelantado"
    assert res["cancelled"] == 1


def test_arrived_trains_are_carried_as_llegado():
    first = parse_siv_payload(_payload([_train("03192", "2026-11-01T21:50:00+01:00")]), now=NOW)
    assert first["arrivals"][0]["status"] == "En hora"
    second = parse_siv_payload(_payload([]), prev_arrivals=first["arrivals"], now=NOW)
    assert [a["status"] for a in second["arrivals"]] == ["Llegado"]


def test_alerts_filtered_to_long_distance():
    alerts = [
        {"id": "a", "level": "info", "message": {"ESP": {"header": "Huelga", "description": "x"}}, "filter": {"traffic_types": ["L"]}},
        {"id": "b", "level": "info", "message": {"ESP": {"header": "Cercanías", "description": "y"}}, "filter": {"traffic_types": ["C"]}},
    ]
    res = parse_siv_payload(_payload([], alerts), now=NOW)
    assert [a["id"] for a in res["alerts"]] == ["a"]


def test_relayed_payload_rejects_future_and_stale_timestamps():
    from datetime import timedelta
    import pytz
    from adif_siv import ingest_relayed_payload
    def snap(dt):
        return {**_payload([]), "station_settings": {"code": "60000", "data_time": dt.isoformat()}}
    now = datetime.now(pytz.utc)
    assert ingest_relayed_payload("60000", snap(now + timedelta(hours=3))) is None
    assert ingest_relayed_payload("60000", snap(now - timedelta(minutes=10))) is None
    assert ingest_relayed_payload("60000", snap(now - timedelta(seconds=5))) is not None
