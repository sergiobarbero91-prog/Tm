"""Madrid taxi licence rest-day rules (libranzas) and preferred-shift checks."""
from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")

# Mon..Fri → last digits that rest that day (06:00 → 06:00 next day)
WEEKDAY_REST = {0: (7, 8), 1: (9, 0), 2: (1, 2), 3: (3, 4), 4: (5, 6)}
SHIFTS = {"day": (5, 17), "night": (17, 5)}
SHIFT_LABELS = {"day": "Día (05:00–17:00)", "night": "Noche (17:00–05:00)", "all": "Todo el día"}
REASONS = {"weekly": "libranza semanal", "weekend": "libranza de fin de semana", "holiday": "libranza de festivo"}
DAY_NAMES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

# Festivos Madrid capital 2026 (fallback if the open-data calendar is unreachable)
DEFAULT_HOLIDAYS_2026 = [
    ("2026-01-01", "Año Nuevo"), ("2026-01-06", "Epifanía del Señor (Reyes)"),
    ("2026-04-02", "Jueves Santo"), ("2026-04-03", "Viernes Santo"),
    ("2026-05-01", "Fiesta del Trabajo"), ("2026-05-15", "San Isidro Labrador"),
    ("2026-10-12", "Fiesta Nacional de España"), ("2026-11-02", "Traslado de Todos los Santos"),
    ("2026-11-09", "Nuestra Señora de la Almudena"), ("2026-12-07", "Traslado del Día de la Constitución"),
    ("2026-12-08", "Inmaculada Concepción"), ("2026-12-25", "Navidad"),
]


def last_digit(license_number: Optional[str]) -> Optional[int]:
    digits = [c for c in str(license_number or "") if c.isdigit()]
    return int(digits[-1]) if digits else None


def _day_windows(d: date, digit: int, holidays: set):
    out = []
    if d.weekday() < 5 and digit in WEEKDAY_REST[d.weekday()]:
        start = datetime.combine(d, time(6), MADRID)
        out.append((start, datetime.combine(d + timedelta(days=1), time(6), MADRID), "weekly"))
    is_weekend = d.weekday() >= 5
    if is_weekend or d in holidays:
        # even licence rests on odd dates, odd licence rests on even dates
        if (digit % 2 == 0) == (d.day % 2 == 1):
            kind = "holiday" if d in holidays and not is_weekend else "weekend"
            out.append((datetime.combine(d, time(7), MADRID), datetime.combine(d, time(20), MADRID), kind))
    return out


def _merged_windows(digit: int, around: date, holidays: set, days: int = 10):
    wins = []
    for i in range(-1, days):
        wins.extend(_day_windows(around + timedelta(days=i), digit, holidays))
    wins.sort(key=lambda w: w[0])
    merged = []
    for s, e, k in wins:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
            merged[-1][2].append(k)
        else:
            merged.append([s, e, [k]])
    return merged


def human_time(dt: datetime, now: datetime) -> str:
    dt, now = dt.astimezone(MADRID), now.astimezone(MADRID)
    hhmm = dt.strftime("%H:%M")
    delta = (dt.date() - now.date()).days
    if delta == 0:
        return f"hoy a las {hhmm}"
    if delta == 1:
        return f"mañana a las {hhmm}"
    return f"el {DAY_NAMES[dt.weekday()]} {dt.day} a las {hhmm}"


def _reason(kinds: list) -> str:
    return " y ".join(dict.fromkeys(REASONS[k] for k in kinds))


def license_status(license_number: Optional[str], at: datetime, holidays: Iterable[date]) -> dict:
    digit = last_digit(license_number)
    if digit is None:
        return {"known": False, "can_work": None}
    at = at.astimezone(MADRID)
    for s, e, kinds in _merged_windows(digit, at.date(), set(holidays)):
        if s <= at < e:
            return {"known": True, "can_work": False, "until": e, "reason": _reason(kinds),
                    "label": f"Libras hasta {human_time(e, at)}"}
        if s > at:
            return {"known": True, "can_work": True, "next_rest_start": s, "next_rest_end": e,
                    "next_reason": _reason(kinds),
                    "label": f"Próxima libranza: {human_time(s, at)} ({_reason(kinds)})"}
    return {"known": True, "can_work": True, "label": "Sin libranzas próximas"}


def in_shift(shift: Optional[str], at: datetime) -> bool:
    rng = SHIFTS.get(shift or "all")
    if not rng:
        return True
    h = at.astimezone(MADRID).hour
    start, end = rng
    return start <= h < end if start < end else (h >= start or h < end)


def month_calendar(license_number: Optional[str], year: int, month: int, holidays: Iterable[date]) -> list:
    """Rest windows starting on each day of the month."""
    digit = last_digit(license_number)
    if digit is None:
        return []
    hol = set(holidays)
    d, out = date(year, month, 1), []
    while d.month == month:
        for s, e, k in _day_windows(d, digit, hol):
            out.append({"date": d.isoformat(), "kind": k, "reason": REASONS[k],
                        "start": s.strftime("%H:%M"), "end": e.strftime("%H:%M"),
                        "ends_next_day": e.date() != d, "holiday": d in hol})
        d += timedelta(days=1)
    return out
