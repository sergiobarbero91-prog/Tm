--- a/backend/server.py
+++ b/backend/server.py
@@ -1,3 +1,4 @@
+# === ADD AT THE TOP OF FILE (with the other imports if needed) ===
+# Ya tienes: from datetime import datetime, timedelta
+# Ya tienes: from typing import List, Dict, Optional
+# No hace falta importar nada más para esta funcionalidad.

# ============================================================
# AÑADE ESTAS FUNCIONES en /app/backend/server.py
# Pégalas justo DESPUÉS de la función `filter_future_flights` (alrededor de la línea 1390)
# ============================================================

# Long-haul / wide-body keywords (transatlantic/transpacific/intercontinental)
_LONG_HAUL_KEYWORDS = [
    "new york", "nueva york", "newark", "jfk", "miami", "boston", "washington",
    "chicago", "los angeles", "los ángeles", "dallas", "houston", "atlanta",
    "san francisco", "philadelphia", "toronto", "montreal", "vancouver",
    "buenos aires", "santiago de chile", "santiago chile", "lima", "bogota", "bogotá",
    "caracas", "panama", "panamá", "quito", "guayaquil", "la habana", "habana",
    "mexico", "méxico", "cancun", "cancún", "guadalajara", "monterrey",
    "sao paulo", "são paulo", "rio de janeiro", "brasilia", "asunción", "asuncion",
    "montevideo", "san salvador", "guatemala", "managua", "tegucigalpa",
    "san juan", "punta cana", "santo domingo",
    "dubai", "dubái", "doha", "abu dhabi", "tel aviv", "estambul", "istanbul",
    "tokio", "tokyo", "pekin", "pekín", "beijing", "shanghai", "shanghái",
    "hong kong", "seul", "seúl", "bangkok", "singapur", "singapore", "delhi",
    "johannesburgo", "johannesburg", "cairo", "el cairo", "casablanca",
    "addis abeba", "addis ababa", "nairobi", "lagos", "argel",
]


def _is_long_haul_flight(flight: Dict) -> bool:
    """Heuristica para detectar vuelos long-haul / avion grande por nombre de origen."""
    origin = (flight.get("origin") or "").lower()
    return any(kw in origin for kw in _LONG_HAUL_KEYWORDS)


def _parse_flight_hhmm_to_dt(time_str: str, now: datetime) -> Optional[datetime]:
    """Parsea 'HH:MM' a datetime con TZ, manejando cambio de día."""
    try:
        if not time_str or ":" not in time_str:
            return None
        h, m = time_str.split(":")
        h, m = int(h), int(m)
        dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if (dt - now).total_seconds() > 12 * 3600:
            dt -= timedelta(days=1)
        elif (now - dt).total_seconds() > 20 * 3600:
            dt += timedelta(days=1)
        return dt
    except (ValueError, AttributeError):
        return None


def calculate_instant_demand(arrivals: List[Dict], now: datetime) -> int:
    """Calcula el % de saturacion de Demanda en este Momento.

    Puntos por vuelo segun minutos desde aterrizaje:
      - EN TIERRA (<5min):             +0.2
      - ENTREGANDO EQUIPO <15min:      +0.4
      - ENTREGANDO EQUIPO >15min:      +0.8
      - FINALIZADO 0-15min:            +1.0
      - FINALIZADO 16-30min:           +0.3
    x1.5 si es vuelo long-haul / avion grande.
    Total x10 = % saturacion. Puede superar 100%.
    """
    total_score = 0.0
    for flight in arrivals:
        dt = _parse_flight_hhmm_to_dt(flight.get("time", ""), now)
        if dt is None:
            continue
        mins_since = (now - dt).total_seconds() / 60.0
        if mins_since < 0 or mins_since > 60:
            continue
        if mins_since < 5:
            pts = 0.2
        elif mins_since < 15:
            pts = 0.4
        elif mins_since < 30:
            pts = 0.8
        elif mins_since < 45:
            pts = 1.0
        else:
            pts = 0.3
        if _is_long_haul_flight(flight):
            pts *= 1.5
        total_score += pts
    return int(round(total_score * 10))


def instant_demand_level(pct: int) -> str:
    """Mapea % de saturacion a un nivel de color."""
    if pct > 100:
        return "critical"
    if pct >= 70:
        return "red"
    if pct >= 40:
        return "yellow"
    return "green"


# Cache en memoria del valor anterior por terminal para calcular la tendencia
_prev_instant_demand: Dict[str, int] = {}


def instant_demand_trend(terminal: str, current_pct: int) -> str:
    """Compara con el valor anterior cacheado para devolver up/down/flat."""
    prev = _prev_instant_demand.get(terminal)
    _prev_instant_demand[terminal] = current_pct
    if prev is None:
        return "flat"
    diff = current_pct - prev
    if diff >= 5:
        return "up"
    if diff <= -5:
        return "down"
    return "flat"


# ============================================================
# AÑADE ESTOS CAMPOS al modelo TerminalData (busca "class TerminalData" en tu server.py)
# ============================================================
# Dentro de la clase TerminalData(BaseModel), añade al final estas 3 líneas:
#
#     instant_demand_pct: Optional[int] = None
#     instant_demand_level: Optional[str] = None   # 'green' | 'yellow' | 'red' | 'critical'
#     instant_demand_trend: Optional[str] = None   # 'up' | 'down' | 'flat'


# ============================================================
# DENTRO del endpoint @api_router.get("/flights")
# Busca donde rellenas `terminal_data[terminal] = TerminalData(...)` y JUSTO DESPUES
# añade este bloque (sustituye `raw_arrivals` por la variable que tengas con todos
# los vuelos sin filtrar, y `now` por tu variable de "ahora" con tz Madrid):
# ============================================================
#
#     # ===== Demanda en este Momento =====
#     if not custom_time_window:  # solo en modo tiempo-real
#         try:
#             instant_pct = calculate_instant_demand(raw_arrivals, now)
#             terminal_data[terminal].instant_demand_pct = instant_pct
#             terminal_data[terminal].instant_demand_level = instant_demand_level(instant_pct)
#             terminal_data[terminal].instant_demand_trend = instant_demand_trend(terminal, instant_pct)
#         except Exception as e:
#             logger.warning(f"[Flights] Instant demand calc failed for {terminal}: {e}")
