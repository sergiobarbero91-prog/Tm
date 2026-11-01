import io
import os
import sys
import zipfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bus_sources import AV_AMERICA_STOP, MADRID_TZ, avamerica_arrivals, build_schedule, parse_avanza  # noqa: E402

NOW = MADRID_TZ.localize(datetime(2026, 11, 1, 22, 0))


def test_parse_avanza_statuses_and_window():
    data = {"status": "ok", "data": [
        {"fx": "01/11/26", "hora": "22:15", "empresa": "ALSA", "parada": "BENIDORM", "cc": "SITUADO", "darsena": "40"},
        {"fx": "01/11/26", "hora": "22:30", "empresa": "FLIXBUS", "parada": "LISBOA", "cc": "RETRASADO", "darsena": None, "darsenaprevista": "12"},
        {"fx": "01/11/26", "hora": "23:00", "empresa": "AISA", "parada": "-", "cc": "-"},
        {"fx": "01/11/26", "hora": "19:00", "empresa": "ALSA", "parada": "TOLEDO", "cc": "-"},
    ]}
    res = parse_avanza(data, NOW)
    assert [a["status"] for a in res] == ["En dársena", "Retrasado", "Programado"]
    assert res[0]["origin"] == "Benidorm" and res[0]["platform"] == "40"
    assert res[1]["platform"] == "12"
    assert res[2]["origin"] == "Origen sin indicar"


def _gtfs_zip():
    files = {
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\n"
                     f"{AV_AMERICA_STOP},Madrid (Intercam Av.America),40.43846909,-3.67594080\n"
                     "BIL,Bilbao,43.2630,-2.9350\nALC,Alcala De Henares,40.4818,-3.3643\nNER,Nerja,36.7570,-3.8740\n",
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence,drop_off_type\n"
                          "t1,18:00:00,18:00:00,BIL,1,1\nt1,22:45:00,22:45:00," + AV_AMERICA_STOP + ",2,0\n"
                          "t2,21:00:00,21:00:00,ALC,1,1\nt2,22:10:00,22:10:00," + AV_AMERICA_STOP + ",2,0\n"
                          "t3,16:00:00,16:00:00,NER,1,1\nt3,24:10:00,24:10:00," + AV_AMERICA_STOP + ",2,0\n",
        "trips.txt": "route_id,service_id,trip_id\nr,daily,t1\nr,daily,t2\nr,daily,t3\n",
        "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                        "daily,1,1,1,1,1,1,1,20260101,20271231\n",
        "calendar_dates.txt": "service_id,date,exception_type\n",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


def test_alsa_schedule_long_distance_and_after_midnight():
    sched = build_schedule(_gtfs_zip())
    origins = {t[3] for t in sched["trips"]}
    assert origins == {"Bilbao", "Nerja"}  # Alcalá (<70 km) excluded
    res = avamerica_arrivals(sched, NOW)
    assert [(a["time"], a["origin"]) for a in res] == [("22:45", "Bilbao"), ("00:10", "Nerja")]
    assert all(a["status"] == "Programado" and a["source"] == "alsa_gtfs" for a in res)



def test_avanza_origin_article_and_delayed_bus_stays_upcoming():
    from datetime import timedelta
    from routers.buses import filter_and_count_arrivals, filter_upcoming
    data = {"status": "ok", "data": [{"fx": "01/11/26", "hora": "21:40", "empresa": "ALSA", "parada": "MANGA, LA", "cc": "RETRASADO"}]}
    bus = parse_avanza(data, NOW)[0]
    assert bus["origin"] == "La Manga"
    late = [{**bus, "at": (datetime.now(MADRID_TZ) - timedelta(minutes=20)).isoformat()}]
    assert filter_upcoming(late)
    assert filter_and_count_arrivals(late, 30)[0] == 1
