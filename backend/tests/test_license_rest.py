from datetime import date, datetime

from license_rest import MADRID, in_shift, license_status

HOL = {date(2026, 11, 9), date(2026, 5, 15)}


def at(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=MADRID)


def test_weekday_rest_06_to_06():
    # 2026-06-04 is Thursday → licences ending in 3/4 rest
    assert license_status("1234", at(2026, 6, 4, 5, 59), HOL)["can_work"] is True
    s = license_status("1234", at(2026, 6, 4, 10), HOL)
    assert s["can_work"] is False and s["until"] == at(2026, 6, 5, 6)
    assert license_status("1234", at(2026, 6, 5, 5, 30), HOL)["can_work"] is False
    assert license_status("1234", at(2026, 6, 5, 6, 0), HOL)["can_work"] is True
    assert license_status("1235", at(2026, 6, 4, 10), HOL)["can_work"] is True


def test_weekend_parity_07_to_20():
    # Sat 13 (odd) → even licence rests; Sat 6 (even) → odd licence rests
    assert license_status("4", at(2026, 6, 13, 10), HOL)["can_work"] is False
    assert license_status("4", at(2026, 6, 13, 20, 0), HOL)["can_work"] is True
    assert license_status("4", at(2026, 6, 13, 6, 59), HOL)["can_work"] is True
    assert license_status("4", at(2026, 6, 6, 10), HOL)["can_work"] is True
    assert license_status("7", at(2026, 6, 6, 8), HOL)["can_work"] is False
    assert license_status("7", at(2026, 6, 14, 12), HOL)["can_work"] is False  # Sunday 14 even


def test_friday_rest_runs_into_saturday_morning():
    # Fri 2026-06-05: 5/6 rest until Sat 06:00; Sat 6 even → odd 5 rests again 07–20
    s = license_status("5", at(2026, 6, 5, 23), HOL)
    assert s["can_work"] is False and s["until"] == at(2026, 6, 6, 6)
    assert license_status("5", at(2026, 6, 6, 6, 30), HOL)["can_work"] is True
    assert license_status("5", at(2026, 6, 6, 7, 30), HOL)["can_work"] is False


def test_holiday_parity_and_weekly_rest_kept():
    # Mon 9 Nov 2026 (odd, holiday): even licences rest 07–20; 7/8 also weekly rest
    assert license_status("4", at(2026, 11, 9, 12), HOL)["can_work"] is False
    assert license_status("4", at(2026, 11, 9, 21), HOL)["can_work"] is True
    assert license_status("3", at(2026, 11, 9, 12), HOL)["can_work"] is True
    s = license_status("8", at(2026, 11, 9, 12), HOL)
    assert s["can_work"] is False and s["until"] == at(2026, 11, 10, 6)
    assert license_status("4", at(2026, 11, 9, 12), set())["can_work"] is True


def test_next_rest_and_unknown():
    s = license_status("1234", at(2026, 6, 1, 10), HOL)
    assert s["can_work"] is True and s["next_rest_start"] == at(2026, 6, 4, 6)
    assert license_status("", at(2026, 6, 1, 10), HOL)["known"] is False


def test_shift():
    assert in_shift("day", at(2026, 6, 1, 5)) and not in_shift("day", at(2026, 6, 1, 17))
    assert in_shift("night", at(2026, 6, 1, 23)) and in_shift("night", at(2026, 6, 1, 4))
    assert not in_shift("night", at(2026, 6, 1, 12)) and in_shift("all", at(2026, 6, 1, 12))
