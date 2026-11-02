import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agenda_sources import (  # noqa: E402
    MADRID_TZ, parse_ayuntamiento, parse_espn, parse_jsonld_events, parse_movistar_arena, parse_vistalegre,
)

NOW = MADRID_TZ.localize(datetime(2026, 11, 2, 12, 0))


def test_espn_keeps_only_upcoming_home_matches_in_madrid():
    def ev(i, date, venue, state="pre", home="Real Madrid", away="Celta Vigo"):
        return {"id": i, "date": date, "league": {"name": "Spanish LALIGA"}, "competitions": [{
            "venue": {"fullName": venue}, "status": {"type": {"state": state}},
            "competitors": [{"homeAway": "home", "team": {"displayName": home}}, {"homeAway": "away", "team": {"displayName": away}}]}]}
    data = {"events": [ev(1, "2026-11-21T20:00Z", "Santiago Bernabéu"), ev(2, "2026-11-07T20:00Z", "Mestalla Stadium"),
                       ev(3, "2026-10-01T20:00Z", "Santiago Bernabéu", state="post")]}
    res = parse_espn(data, NOW)
    assert len(res) == 1
    assert res[0]["name"] == "Real Madrid – Celta Vigo · LaLiga" and res[0]["start"] == "21:00" and res[0]["hot"]


def test_movistar_arena_links():
    page = ('<a href="/programacion/evento/duran-duran/6-11-2026/21:00" data-x="1" data-event-detail="Duran Duran - Tour">'
            '<a href="/programacion/evento/duran-duran/6-11-2026/21:00" data-event-detail="Duran Duran - Tour">')
    res = parse_movistar_arena(page, NOW)
    assert len(res) == 1 and res[0]["date"] == "2026-11-06" and res[0]["place"] == "Movistar Arena"


def test_vistalegre_and_jsonld():
    v = parse_vistalegre({"events": [{"id": 5, "title": "Joe &#8211; Tour", "start_date": "2026-11-08 20:00:00"}]}, NOW)
    assert v[0]["name"] == "Joe – Tour" and v[0]["start"] == "20:00"
    page = '<script type="application/ld+json">{"@type":"Event","name":"Alex Ubago","startDate":"2026-11-04T21:00:00+01:00"}</script>'
    r = parse_jsonld_events(page, "Sala La Riviera", "riviera", "concierto", False, NOW)
    assert r[0]["date"] == "2026-11-04" and r[0]["start"] == "21:00"
    fair = '<script type="application/ld+json">[{"@type":"Event","name":"Privel","startDate":"2026-11-04","endDate":"2026-11-05"},' \
           '{"@type":"Event","name":"WAH","startDate":"2026-09-17","endDate":"2027-01-10"}]</script>'
    f = parse_jsonld_events(fair, "IFEMA", "ifema", "feria", False, NOW, (10, 19))
    assert [(x["name"], x["date"]) for x in f] == [("Privel", "2026-11-04"), ("Privel", "2026-11-05")]


def test_ayuntamiento_filters_and_recurrence():
    base = "https://datos.madrid.es/egob/kos/actividades/"
    data = {"@graph": [
        {"@type": base + "TeatroPerformance", "id": "1", "title": "Moscú no existe", "event-location": "Fernán Gómez Centro Cultural de la Villa",
         "dtstart": "2026-11-03 00:00:00.0", "dtend": "2026-11-05 23:59:00.0", "time": "19:30",
         "recurrence": {"days": "TU,TH"}, "excluded-days": ""},
        {"@type": base + "CursosTalleres", "id": "2", "title": "Taller", "event-location": "Matadero Madrid",
         "dtstart": "2026-11-03 17:00:00.0", "dtend": "2026-11-03 19:00:00.0", "time": "17:00"},
        {"@type": base + "Musica", "id": "3", "title": "Concierto barrio", "event-location": "Centro Cultural X",
         "dtstart": "2026-11-03 19:00:00.0", "dtend": "2026-11-03 21:00:00.0", "time": "19:00"},
        {"@type": base + "ProgramacionDestacadaAgendaCultura", "id": "4", "title": "Curso Junior de Ficción", "event-location": "Matadero Madrid",
         "dtstart": "2026-11-03 17:00:00.0", "dtend": "2026-11-03 19:00:00.0", "time": "17:00"},
    ]}
    res = parse_ayuntamiento(data, NOW)
    assert [(e["name"], e["date"], e["start"]) for e in res] == [("Moscú no existe", "2026-11-03", "19:30"), ("Moscú no existe", "2026-11-05", "19:30")]


def test_kapital_nights_from_opening_hours():
    from agenda_sources import parse_kapital
    page = "Miércoles: 23:00h – 5:30h Jueves: 23:00h – 5:30h Viernes: 23:00h – 06:00h Sábado: 23:00h – 06:00h Domingo: 23:00h – 5:30h"
    res = parse_kapital(page, NOW)  # NOW = Monday 2 Nov 2026
    first = res[0]
    assert first["date"] == "2026-11-04" and first["start"] == "23:00" and first["end"] == "05:30" and not first["hot"]
    fri = next(e for e in res if e["date"] == "2026-11-06")
    assert fri["hot"] and fri["end"] == "06:00" and fri["category"] == "noche"
    assert not any(e["date"] in ("2026-11-02", "2026-11-03") for e in res)  # closed Mon/Tue
    assert parse_kapital("", NOW)  # falls back to known hours
