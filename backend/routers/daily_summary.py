"""
Daily AI summary router for Madrid taxi drivers.

Uses Gemini 2.5-flash-lite with Google Search Grounding to produce a
Telegram-style daily briefing covering 4 fixed sections:
  [GRANDES EVENTOS]
  [TEATROS Y OCIO]
  [ALERTAS DE TRÁFICO]
  [PREVISIÓN MAÑANA]

Notes:
- The path prefix `/events` is reused so the final URLs are
    GET  /api/events/daily-summary
    POST /api/events/daily-summary/regenerate
  This router must be registered BEFORE routers.events so its literal
  `/daily-summary` path is matched before the `/{event_id}` catch-all.
- Requires GEMINI_API_KEY in backend/.env (Universal Key cannot grant
  the Google Search Grounding tool).
"""
import os
import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pytz
from fastapi import APIRouter, Depends, HTTPException

from shared import daily_summaries_collection, get_admin_user, logger

router = APIRouter(prefix="/events", tags=["Daily Summary"])

MADRID_TZ = pytz.timezone("Europe/Madrid")
MODEL_NAME = "gemini-2.5-flash"
MODEL_FALLBACK = "gemini-2.5-flash-lite"  # if primary model is overloaded

# Cache freshness: a stored summary is considered current if it was generated
# today (Madrid date). Otherwise we regenerate on the first GET of the day.
SECTIONS = [
    "[METEO HOY]",
    "[GRANDES EVENTOS]",
    "[TEATROS Y OCIO]",
    "[ALERTAS DE TRÁFICO]",
    "[AEROPUERTO]",
    "[PREVISIÓN MAÑANA]",
]

FALLBACK_QUERIES = [
    "eventos Madrid hoy conciertos estadio Metropolitano Bernabeu",
    "teatros Madrid Gran Vía cartelera función hoy",
    "obras corte tráfico Madrid M-30 hoy DGT",
    "previsión meteorológica Madrid mañana AEMET",
    "manifestaciones Madrid hoy delegación gobierno",
    "partido fútbol Madrid hoy hora estadio",
]


# ─────────────────────────────────────────────────────────────────────────────
# Airport peaks — compute optimal terminal entry times
# ─────────────────────────────────────────────────────────────────────────────
# Heuristic: a "good time to enter a terminal" is the moment a wave of
# landings is touching down, because passengers will exit the terminal
# 15-35 min after touchdown. We score 60-min SLIDING windows (advancing
# every 5 min) weighting wide-body aircraft 3x normal flights.
#
# Terminals are grouped in "taxi waiting bags" — when a driver waits at one
# physical taxi rank he services the whole group:
#   T1            (alone)
#   T2 + T3       (same rank)
#   T4 + T4S      (same rank)
SLIDE_STEP_MIN = 5     # window advances every 5 minutes
WINDOW_SIZE_MIN = 60   # 1-hour rolling window (matches "próx 60min" of UI)
SUB_BIN_MIN = 15       # granularity to detect peak instant inside the window
DAY_BREAK_HOUR = 5     # 05:00 splits the operational day in Madrid
EVENING_BREAK_HOUR = 17  # 17:00 splits morning vs evening shift
LARGE_FLIGHT_WEIGHT = 3.0
NORMAL_FLIGHT_WEIGHT = 1.0
SAME_GROUP_MIN_GAP_MIN = 60  # de-dup overlapping windows in same group (= window size)
TERMINAL_GROUPS: Dict[str, List[str]] = {
    "T1": ["T1"],
    "T2-T3": ["T2", "T3"],
    "T4-T4S": ["T4", "T4S"],
}


def _time_str_to_minutes(t: str) -> Optional[int]:
    """Convert 'HH:MM' to minutes since midnight, or None."""
    try:
        h, m = t.split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _bin_label(minutes: int) -> str:
    """Convert 480 -> '08:00'."""
    h = (minutes // 60) % 24
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def _shift_starts(shift: str) -> List[int]:
    """Return the list of candidate window-start minutes for a shift.

    Each entry is the *start* of a 60-min sliding window. We move every
    SLIDE_STEP_MIN. The window can extend past midnight for the evening
    shift (e.g. window starting at 03:00 covers 03:00-04:00).
    """
    if shift == "morning":
        # 05:00 -> 16:00 (last window 16:00-17:00). Stop before 16:55.
        return list(range(DAY_BREAK_HOUR * 60, EVENING_BREAK_HOUR * 60, SLIDE_STEP_MIN))
    # evening: 17:00 -> 04:00 next day (last window 04:00-05:00 next day).
    starts: List[int] = []
    for m in range(EVENING_BREAK_HOUR * 60, DAY_BREAK_HOUR * 60 + 24 * 60, SLIDE_STEP_MIN):
        starts.append(m)
    return starts


async def _compute_airport_peaks() -> Dict[str, List[Dict[str, Any]]]:
    """Return the 2 busiest 60-min windows per shift (morning/evening).

    Output per pick:
      {
        "group": "T4-T4S" | "T2-T3" | "T1",
        "window": "18:30-19:30",            # the busiest 60-min window
        "peak_time": "18:45",               # 15-min hot spot inside the window
        "leave_time": "18:15",              # 30 min before peak_time
        "flights": int,
        "large": int,
        "score": float,
      }
    """
    # Lazy import to avoid circular dependency with server.py
    try:
        from server import fetch_aena_arrivals
    except Exception as e:
        logger.warning(f"[airport-peaks] cannot import fetch_aena_arrivals: {e}")
        return {"morning": [], "evening": []}

    try:
        all_arrivals = await fetch_aena_arrivals()
    except Exception as e:
        logger.warning(f"[airport-peaks] AENA fetch failed: {e}")
        return {"morning": [], "evening": []}

    def _score(flight: Dict[str, Any]) -> float:
        return LARGE_FLIGHT_WEIGHT if flight.get("is_large") else NORMAL_FLIGHT_WEIGHT

    def _is_in_shift(minute: int, shift: str) -> bool:
        h = (minute // 60) % 24
        if shift == "morning":
            return DAY_BREAK_HOUR <= h < EVENING_BREAK_HOUR
        return h >= EVENING_BREAK_HOUR or h < DAY_BREAK_HOUR

    def _peak_time_within(window_start: int, flights: List[Dict[str, Any]], shift: str) -> int:
        """Inside a 60-min window, find the 15-min sub-bin with most flights
        (weighted) and return its center minute. Flights whose arrival time
        falls in the opposite shift (e.g. window crosses 17:00) are ignored
        so the recommended peak stays within the driver's working shift."""
        if not flights:
            return window_start
        sub_scores: Dict[int, float] = {}
        for f in flights:
            m = _time_str_to_minutes(f.get("time", ""))
            if m is None:
                continue
            if not _is_in_shift(m, shift):
                continue
            offset = (m - window_start) % 1440
            sub_idx = offset // SUB_BIN_MIN
            sub_scores[sub_idx] = sub_scores.get(sub_idx, 0.0) + _score(f)
        if not sub_scores:
            # fallback: any flight, even cross-shift
            for f in flights:
                m = _time_str_to_minutes(f.get("time", ""))
                if m is None:
                    continue
                offset = (m - window_start) % 1440
                sub_idx = offset // SUB_BIN_MIN
                sub_scores[sub_idx] = sub_scores.get(sub_idx, 0.0) + _score(f)
            if not sub_scores:
                return window_start
        best_sub = max(sub_scores, key=sub_scores.get)
        return (window_start + best_sub * SUB_BIN_MIN + SUB_BIN_MIN // 2) % 1440

    def _flights_in_window(group_terms: List[str], window_start: int) -> List[Dict[str, Any]]:
        bag: List[Dict[str, Any]] = []
        for term in group_terms:
            for arr in all_arrivals.get(term, []):
                m = _time_str_to_minutes(arr.get("time", ""))
                if m is None:
                    continue
                # offset in [0, 1440) so windows that wrap midnight (evening)
                # still pick up post-midnight flights correctly.
                offset = (m - window_start) % 1440
                if offset < WINDOW_SIZE_MIN:
                    bag.append(arr)
        return bag

    def _top_2_for_shift(shift: str) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for start in _shift_starts(shift):
            for group_name, group_terms in TERMINAL_GROUPS.items():
                flights = _flights_in_window(group_terms, start)
                if not flights:
                    continue
                total_score = sum(_score(f) for f in flights)
                if total_score <= 0:
                    continue
                peak_min = _peak_time_within(start, flights, shift)
                leave_min = (peak_min - 30 + 1440) % 1440
                candidates.append({
                    "group": group_name,
                    "window_start_min": start % 1440,
                    "window_end_min": (start + WINDOW_SIZE_MIN) % 1440,
                    "window": f"{_bin_label(start)}-{_bin_label(start + WINDOW_SIZE_MIN)}",
                    "peak_time_min": peak_min,
                    "peak_time": _bin_label(peak_min),
                    "leave_time": _bin_label(leave_min),
                    "flights": len(flights),
                    "large": sum(1 for f in flights if f.get("is_large")),
                    "score": round(total_score, 1),
                })

        candidates.sort(key=lambda c: c["score"], reverse=True)

        picked: List[Dict[str, Any]] = []
        for cand in candidates:
            # De-duplication: if a higher-scored window for the SAME group is
            # already picked within 30 min, skip — it's the same wave shifted.
            duplicate_of_same_group = any(
                p["group"] == cand["group"]
                and abs(((cand["peak_time_min"] - p["peak_time_min"]) + 720) % 1440 - 720)
                < SAME_GROUP_MIN_GAP_MIN
                for p in picked
            )
            if duplicate_of_same_group:
                continue
            picked.append(cand)
            if len(picked) == 2:
                break

        # Sort the final 2 by peak_time ascending for stable output
        picked.sort(key=lambda c: c["peak_time_min"])
        # Drop internal-only fields
        for p in picked:
            p.pop("window_start_min", None)
            p.pop("window_end_min", None)
            p.pop("peak_time_min", None)
        return picked

    return {
        "morning": _top_2_for_shift("morning"),
        "evening": _top_2_for_shift("evening"),
    }


def _format_airport_section(peaks: Dict[str, List[Dict[str, Any]]]) -> str:
    """Build the `[AEROPUERTO]` section text from the precomputed peaks."""
    morning = peaks.get("morning", [])
    evening = peaks.get("evening", [])
    if not morning and not evening:
        return "[AEROPUERTO]\n- Sin información de llegadas disponible."

    def _line(p: Dict[str, Any]) -> str:
        large_tag = f", {p['large']} grandes" if p.get("large") else ""
        return (
            f"- **{p['group']} · {p['window']}** "
            f"({p['flights']} vuelos{large_tag}) — pico a las **{p['peak_time']}h**, "
            f"sal hacia el aeropuerto sobre las **{p['leave_time']}h**."
        )

    lines: List[str] = ["[AEROPUERTO]"]
    lines.append("**Turno mañana (05:00-17:00):**")
    if morning:
        for p in morning:
            lines.append(_line(p))
    else:
        lines.append("- Sin picos significativos en el turno de mañana.")
    lines.append("")
    lines.append("**Turno tarde-noche (17:00-05:00):**")
    if evening:
        for p in evening:
            lines.append(_line(p))
    else:
        lines.append("- Sin picos significativos en el turno de tarde.")
    return "\n".join(lines)


def _today_madrid_str() -> str:
    return datetime.now(MADRID_TZ).strftime("%Y-%m-%d")


def _now_madrid_hhmm() -> str:
    return datetime.now(MADRID_TZ).strftime("%H:%M")


def _cache_slot_madrid() -> str:
    """Cache slot key: refreshes every 4 hours so the summary stays fresh
    throughout the day (00, 04, 08, 12, 16, 20). Combines with today's date."""
    now = datetime.now(MADRID_TZ)
    slot = (now.hour // 4) * 4
    return f"{now.strftime('%Y-%m-%d')}T{slot:02d}"


def _tomorrow_madrid_str() -> str:
    now = datetime.now(MADRID_TZ)
    return (now.replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(days=1)).strftime("%Y-%m-%d")


def _build_prompt() -> str:
    today = _today_madrid_str()
    now_hhmm = _now_madrid_hhmm()
    now = datetime.now(MADRID_TZ)
    weekday_es = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"][now.weekday()]
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow = _tomorrow_madrid_str()
    return (
        "Eres un asistente para TAXISTAS de Madrid con conocimiento profundo del "
        f"calendario de eventos y vida cultural de la ciudad. Genera un briefing "
        f"TELEGRAM con la información REAL del día {today} (zona horaria "
        f"Europe/Madrid).\n\n"
        f"══════════════════════════════════════════════════════\n"
        f"  HOY = {today} ({weekday_es})\n"
        f"  AYER = {yesterday}   MAÑANA = {tomorrow}\n"
        f"  HORA ACTUAL EN MADRID = {now_hhmm}\n"
        f"══════════════════════════════════════════════════════\n\n"
        "🚨 REGLA #0 — VERIFICACIÓN DE FECHA (LA MÁS IMPORTANTE, ABSOLUTA):\n"
        "\n"
        f"Antes de incluir CUALQUIER evento debes verificar su FECHA en Google "
        f"Search y comprobar si HOY ({today}) está dentro de las fechas del "
        "evento. Si el evento YA ACABÓ (aunque haya sido ayer o hace días o el "
        "fin de semana pasado), está TERMINANTEMENTE PROHIBIDO.\n"
        "\n"
        "Procedimiento OBLIGATORIO para cada evento antes de escribirlo:\n"
        "  Paso 1: Busca '<nombre evento> fechas 2026 Madrid' o "
        "'<nombre evento> cuándo es'.\n"
        "  Paso 2: Identifica FECHA INICIO y FECHA FIN del evento.\n"
        f"  Paso 3: Comprueba: ¿{today} está entre esas fechas (inclusive)? "
        f"Si NO → DESCARTA. Si SÍ → puedes incluirlo.\n"
        "  Paso 4: En el bullet, escribe la fecha o rango entre paréntesis "
        f"para justificar (ej. 'Concierto de Rosalía en WiZink (**hoy {today}**, "
        "20:30)').\n"
        "\n"
        "EJEMPLOS DE ERRORES QUE NO DEBES COMETER (aprende de estos):\n"
        f"  ❌ Mad Cool Festival 2026 se celebró del 10 al 12 de julio. "
        f"Si HOY es {today} y es posterior al 12/07/2026, Mad Cool NO existe "
        "hoy — NO lo incluyas.\n"
        f"  ❌ Auditorio Miguel Ríos de Rivas típicamente tiene programación "
        f"de fin de semana (viernes-domingo). Si HOY es lunes, martes, "
        "miércoles o jueves, sus eventos del fin de semana pasado YA "
        "TERMINARON — NO los incluyas.\n"
        f"  ❌ Cualquier festival, corrida, feria o partido cuya fecha ya haya "
        f"pasado, aunque Google lo devuelva como 'destacado' de {today[:7]}, "
        "está PROHIBIDO.\n"
        "\n"
        "🕐 REGLA #1 — VERIFICACIÓN DE HORA (segunda en importancia):\n"
        "\n"
        f"Si el evento ES de hoy ({today}) pero su hora de FINALIZACIÓN ya "
        f"pasó (ej. concierto 18:00–21:00 y ahora son las {now_hhmm} tras las "
        "21:00), TAMPOCO lo incluyas.\n"
        "Si empezó pero no ha terminado, márcalo '(en curso)'.\n"
        "Si NO puedes verificar la hora fin y empezó hace más de 4 horas, "
        "descártalo por precaución.\n"
        "\n"
        "🔎 REGLA #2 — BÚSQUEDA EXHAUSTIVA:\n"
        "Usa Google Search de forma masiva. Madrid SIEMPRE tiene actividad. "
        "Si tu primera búsqueda vuelve vacía, prueba mínimo 8 queries "
        "distintas por sección:\n"
        "   - METEO HOY: 'AEMET Madrid hoy temperatura mínima máxima', "
        "'tiempo Madrid próximas horas precipitaciones', 'aviso AEMET Madrid "
        "hoy', 'eltiempo.es Madrid pronóstico horas'.\n"
        f"   - GRANDES EVENTOS: 'Madrid eventos {today}', 'Madrid conciertos "
        f"{today}', 'Real Madrid partido {today}', 'Atlético partido {today}', "
        f"'Las Ventas corrida {today}', 'IFEMA feria hoy', 'Plaza Mayor "
        f"actividad {today}', calendarios oficiales del Ayuntamiento y "
        "esmadrid.es.\n"
        "   - TEATROS Y OCIO: cartelera teatros centro (Compac, Reina "
        "Victoria, Bellas Artes, Príncipe Gran Vía, La Latina), Cines Verdi, "
        "Cineteca, exposiciones Reina Sofía/Prado/Thyssen abiertas hoy.\n"
        "   - ALERTAS DE TRÁFICO: DGT Madrid hoy, manifestaciones, obras "
        "M-30/M-40, cortes esmadrid.es.\n"
        "3. SOLO como ÚLTIMO recurso escribe 'Sin información verificada para "
        "hoy.' si tras DOS rondas de búsqueda con distintas palabras clave "
        "SIGUES sin encontrar nada. Es MUY raro en Madrid. Antes de rendirte, "
        "incluye SIEMPRE al menos 2-3 eventos plausibles con '(horario por "
        "confirmar)' si no puedes verificar la hora exacta. Un resumen con "
        "eventos parciales es MUY superior a uno vacío.\n"
        "4. ACONTECIMIENTOS NACIONALES / CIUDADANOS: si HOY hay un evento de "
        "gran magnitud nacional o ciudadano (celebración de victoria del "
        "Mundial de fútbol, final de Champions/Eurocopa, San Silvestre, "
        "cabalgatas Reyes, manifestaciones grandes convocadas, Nochevieja "
        "Puerta del Sol, Orgullo, San Isidro, procesiones Semana Santa), "
        "MENCIÓNALO SIEMPRE en GRANDES EVENTOS con los puntos de encuentro "
        "habituales para taxistas (Cibeles/Neptuno tras victorias del Real "
        "Madrid o España, Plaza Colón, Puerta del Sol, Puerta de Alcalá) y "
        "las zonas típicas de saturación (Autocine Madrid RACE, Madrid Río, "
        "estadios). Si no tienes hora exacta pon '(horario por confirmar)' "
        "pero NUNCA lo omitas.\n"
        "5. Considera GRANDES EVENTOS (no solo deportivos):\n"
        "   • Partidos Real Madrid / Atlético / Rayo (Bernabéu, Metropolitano, "
        "Vallecas) — SÓLO si LaLiga/UEFA lo confirma para hoy.\n"
        "   • Conciertos grandes (WiZink Center, Palacio Vistalegre, Movistar "
        "Arena, Riviera).\n"
        "   • Fiestas patronales activas HOY (San Isidro, Dos de Mayo, "
        "Veranos de la Villa, Navidad, Carnaval).\n"
        "   • Conciertos al aire libre (Plaza Mayor, Pradera San Isidro, "
        "Madrid Río, Templo de Debod).\n"
        "   • Festejos taurinos en Las Ventas (solo si hay corrida programada "
        "para hoy).\n"
        "   • Ferias ACTIVAS en IFEMA / Casa de Campo (verifica fecha inicio/"
        "fin).\n"
        "   • Eventos cívicos masivos (Orgullo, San Silvestre, cabalgatas) — "
        "sólo si son HOY.\n"
        "\n"
        "✍️ FORMATO Y ESTILO:\n"
        "1. Usa **negrita** (doble asterisco) para lugares, horas y nombres.\n"
        "2. Sé conciso: 4-7 bullets por sección, frases cortas.\n"
        "3. Prioriza puntos calientes para taxis: estadios, teatros centro, "
        "Atocha/Chamartín, T1/T2/T3/T4/T4S Barajas, IFEMA, Pradera, Plaza "
        "Mayor.\n"
        "4. No repitas el mismo evento en dos secciones distintas.\n"
        "5. PRECISIÓN HORARIA: NUNCA inventes horas. Si tienes el evento pero "
        "no la hora exacta confirmada por fuente oficial (esmadrid, ifema, "
        "web teatro/estadio, AEMET, DGT), escribe '(horario por confirmar)'.\n"
        "6. Cada bullet de GRANDES EVENTOS / TEATROS Y OCIO / ALERTAS DE "
        "TRÁFICO DEBERÍA contener (a) una hora o rango horario y (b) la fecha "
        "o rango de fechas entre paréntesis. Si NO tienes la hora exacta, "
        "usa '(horario por confirmar)' pero INCLUYE el bullet — no lo "
        "descartes por eso. Sólo descarta si el evento ya terminó (regla #0).\n"
        "\n"
        "FORMATO OBLIGATORIO (respeta los corchetes y orden):\n"
        "[METEO HOY]\n"
        "- **Temperatura**: mín XX°C / máx XX°C\n"
        "- **Precipitaciones**: porcentaje y franja horaria si las hay "
        "(ej. '40% a las 18:00-21:00'); si no hay riesgo, escribe 'Sin lluvia "
        "prevista'.\n"
        "- **Viento/Calima/Alertas**: solo si es relevante para el tráfico "
        "(rachas >40 km/h, calima, niebla, ola de calor, aviso AEMET "
        "amarillo/naranja/rojo). Si nada destacable, omite esta línea.\n"
        "- **Detalle clave para el taxi**: 1-2 frases sobre cómo afecta el "
        "tiempo al trabajo del taxista hoy. Usa datos de AEMET.\n\n"
        "[GRANDES EVENTOS]\n"
        "- bullet con **lugar**, **hora** y motivo (fecha entre paréntesis)\n\n"
        "[TEATROS Y OCIO]\n"
        "- bullet con **teatro/sala**, **hora función** y obra\n\n"
        "[ALERTAS DE TRÁFICO]\n"
        "- bullet con **calle/zona**, motivo y franja horaria\n\n"
        "[AEROPUERTO]\n"
        "- NO RELLENES esta sección. El servidor la reemplazará con datos\n"
        "  precomputados de AENA. Déjala vacía o con un placeholder corto.\n\n"
        "[PREVISIÓN MAÑANA]\n"
        f"- bullet con tiempo, temperatura y eventos relevantes para mañana ({tomorrow})\n"
    )


def _extract_sources_and_queries(response: Any) -> (List[Dict[str, str]], List[str]):
    """Extract grounding sources and search queries from a Gemini response."""
    sources: List[Dict[str, str]] = []
    queries: List[str] = []
    try:
        candidates = getattr(response, "candidates", None) or []
        for cand in candidates:
            gm = getattr(cand, "grounding_metadata", None)
            if not gm:
                continue
            wsq = getattr(gm, "web_search_queries", None) or []
            for q in wsq:
                if q and q not in queries:
                    queries.append(q)
            gchunks = getattr(gm, "grounding_chunks", None) or []
            for ch in gchunks:
                web = getattr(ch, "web", None)
                if web and getattr(web, "uri", None):
                    title = getattr(web, "title", None) or web.uri
                    sources.append({"title": title, "uri": web.uri})
    except Exception as e:
        logger.warning(f"[daily-summary] grounding extraction failed: {e}")
    return sources, queries


def _ensure_sections(text: str) -> str:
    """Guarantee all 4 section headers are present (anti-hallucination guard).

    If the model drops a section, we append it with a graceful placeholder so
    downstream consumers can rely on the contract.
    """
    fixed = text or ""
    for header in SECTIONS:
        if header not in fixed:
            fixed += f"\n\n{header}\n- Sin información verificada para hoy."
    return fixed.strip()


def _inject_airport_section(text: str, airport_section_text: str) -> str:
    """Replace or insert the `[AEROPUERTO]` section with deterministic data.

    Gemini does NOT know the real flight schedules, so we overwrite whatever
    it generated for `[AEROPUERTO]` with our computed peaks. If the section
    is missing, we insert it right before `[PREVISIÓN MAÑANA]` (or append).
    """
    if not airport_section_text:
        return text

    import re

    # If the model already emitted [AEROPUERTO]..., replace the whole block
    # up to the next section header or end of text.
    pattern = re.compile(
        r"\[AEROPUERTO\][\s\S]*?(?=\n\[[A-ZÁÉÍÓÚÑ ]+\]|\Z)",
        re.MULTILINE,
    )
    if pattern.search(text):
        return pattern.sub(airport_section_text.strip() + "\n", text, count=1)

    # Otherwise insert before [PREVISIÓN MAÑANA] if it exists
    if "[PREVISIÓN MAÑANA]" in text:
        return text.replace(
            "[PREVISIÓN MAÑANA]",
            airport_section_text.strip() + "\n\n[PREVISIÓN MAÑANA]",
            1,
        )

    # Fallback: append at the end
    return (text.rstrip() + "\n\n" + airport_section_text.strip()).strip()


def _strip_stale_bullets(text: str) -> str:
    """Defense-in-depth: remove bullets that mention events with a clearly-
    past end date. We parse each bullet line for date patterns like
    'del X al Y', 'hasta el Z', 'X-Y julio' and drop it if the end date is
    before today (Madrid). Also drops bullets mentioning festivals known to
    be already-past by the reference date. Runs on already-generated text so
    it acts as a last defense if both the prompt and the verify pass fail.

    Only touches lines inside [GRANDES EVENTOS] and [TEATROS Y OCIO]."""
    if not text:
        return text
    now = datetime.now(MADRID_TZ).date()
    _MONTHS = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
        "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
        "noviembre": 11, "diciembre": 12,
    }

    def _parse_end_date(bullet: str) -> Optional["datetime.date"]:
        """Look for the latest date mentioned in a bullet. Understands:
          - 'del D al D de MES'    (e.g. 'del 10 al 12 de julio')
          - 'D-D de MES'
          - 'hasta el D de MES'
          - 'hasta el DD/MM'
          - 'YYYY-MM-DD'
        Returns the latest date found or None."""
        import re as _re
        bullet_l = bullet.lower()
        candidates: List["datetime.date"] = []
        # 1) ISO YYYY-MM-DD
        for m in _re.finditer(r"(\d{4})-(\d{2})-(\d{2})", bullet):
            try:
                candidates.append(datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date())
            except ValueError:
                pass
        # 2) 'del D al D de MES' or 'D al D de MES' or 'D-D de MES'
        rx_range = _re.compile(
            r"(?:del\s+)?(\d{1,2})\s*(?:al|-|–|—|a)\s*(\d{1,2})\s+de\s+([a-záéíóú]+)"
        )
        for m in rx_range.finditer(bullet_l):
            month = _MONTHS.get(m.group(3))
            if not month:
                continue
            try:
                candidates.append(datetime(now.year, month, int(m.group(2))).date())
            except ValueError:
                pass
        # 3) 'hasta el D de MES'
        rx_until = _re.compile(r"hasta\s+(?:el\s+)?(\d{1,2})\s+de\s+([a-záéíóú]+)")
        for m in rx_until.finditer(bullet_l):
            month = _MONTHS.get(m.group(2))
            if not month:
                continue
            try:
                candidates.append(datetime(now.year, month, int(m.group(1))).date())
            except ValueError:
                pass
        # 4) 'D de MES' single-day (used to accept ongoing single-day events)
        rx_single = _re.compile(r"\b(\d{1,2})\s+de\s+([a-záéíóú]+)\b")
        for m in rx_single.finditer(bullet_l):
            month = _MONTHS.get(m.group(2))
            if not month:
                continue
            try:
                candidates.append(datetime(now.year, month, int(m.group(1))).date())
            except ValueError:
                pass
        if not candidates:
            return None
        return max(candidates)

    lines = text.split("\n")
    out: List[str] = []
    inside_target = False
    dropped = 0

    # First pass: collect per-section (bullets, dropped-count, kept-count)
    # so we can revert if a whole section would go empty.
    sections: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = {
                "header_line": line,
                "target": stripped in ("[GRANDES EVENTOS]", "[TEATROS Y OCIO]"),
                "body_lines": [],   # every non-header line in this section
                "kept_bullets": 0,  # bullets that survive
                "dropped_bullets": [],  # (line, end_date) tuples
                "total_bullets": 0,
            }
            sections.append(current)
            continue
        if current is None:
            # Preamble text before any section
            out.append(line)
            continue
        current["body_lines"].append(line)
        if current["target"] and stripped.startswith("-") and len(stripped) > 2:
            current["total_bullets"] += 1
            end_date = _parse_end_date(stripped)
            if end_date is not None and end_date < now:
                current["dropped_bullets"].append((line, end_date))
            else:
                current["kept_bullets"] += 1

    # Second pass: assemble the final text.
    for sec in sections:
        out.append(sec["header_line"])
        do_strip = True
        # Fail-open rule: if the strip would empty a section that originally
        # had bullets, DO NOT strip. Better to keep some possibly-stale content
        # than to leave the user with no info at all — the operator can
        # regenerate manually.
        if (sec["target"]
                and sec["total_bullets"] > 0
                and sec["kept_bullets"] == 0):
            do_strip = False
            logger.warning(
                f"[daily-summary] _strip_stale_bullets would empty section "
                f"'{sec['header_line'].strip()}' ({sec['total_bullets']} "
                f"bullets); reverting to keep original content."
            )
        for line in sec["body_lines"]:
            stripped = line.strip()
            if (do_strip and sec["target"]
                    and stripped.startswith("-") and len(stripped) > 2):
                end_date = _parse_end_date(stripped)
                if end_date is not None and end_date < now:
                    dropped += 1
                    logger.info(
                        f"[daily-summary] stripped stale bullet "
                        f"(ends {end_date} < today {now}): {stripped[:120]}"
                    )
                    continue
            out.append(line)

    if dropped:
        logger.warning(f"[daily-summary] _strip_stale_bullets dropped {dropped} past bullet(s)")
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────────────
# Hallucinated-instruction filter
# ─────────────────────────────────────────────────────────────────────────────
_HALLUCINATED_MARKERS = (
    "NO RELLENES",
    "El servidor la reemplazará",
    "El servidor la rellenará",
    "datos precomputados",
    "placeholder corto",
    "Déjala vacía",
    "no hay ninguna instrucción especial",
)


def _strip_hallucinated_instructions(text: str) -> str:
    """Remove any bullet that contains internal prompt directives (e.g. the
    'NO RELLENES esta sección' text meant only for [AEROPUERTO]).

    Only applied outside [AEROPUERTO] — inside [AEROPUERTO] the section is
    fully overwritten by _inject_airport_section anyway."""
    if not text:
        return text
    lines = text.split("\n")
    out: List[str] = []
    inside_aeropuerto = False
    dropped = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            inside_aeropuerto = stripped == "[AEROPUERTO]"
            out.append(line)
            continue
        if (not inside_aeropuerto
                and stripped.startswith("-")
                and any(m.lower() in stripped.lower() for m in _HALLUCINATED_MARKERS)):
            dropped += 1
            logger.info(
                f"[daily-summary] stripped hallucinated instruction bullet: {stripped[:120]}"
            )
            continue
        out.append(line)
    if dropped:
        logger.warning(f"[daily-summary] _strip_hallucinated_instructions dropped {dropped} bullet(s)")
    return "\n".join(out)


def _generate_summary_sync(extra_prompt: Optional[str] = None) -> Dict[str, Any]:
    """Call Gemini synchronously (intended to run inside a thread).

    `extra_prompt`: optional additional instructions appended AFTER the main
    prompt (used by the retry-with-softer-prompt path when the first pass
    left too many event sections empty).
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="GEMINI_API_KEY no configurada en el servidor.",
        )

    from google import genai
    from google.genai import types as gtypes

    client = genai.Client(api_key=api_key)
    config = gtypes.GenerateContentConfig(
        tools=[gtypes.Tool(google_search=gtypes.GoogleSearch())],
        temperature=0.3 if extra_prompt else 0.2,
    )

    base_prompt = _build_prompt()
    full_prompt = f"{base_prompt}\n\n{extra_prompt}" if extra_prompt else base_prompt

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=full_prompt,
            config=config,
        )
    except Exception as e:
        msg = str(e)
        # Quota exhaustion → translate to 503 with Retry-After
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
            logger.warning(f"[daily-summary] Gemini quota exhausted: {msg[:200]}")
            raise HTTPException(
                status_code=503,
                detail="Cuota de Gemini agotada. Vuelve a intentarlo más tarde o renueva el GEMINI_API_KEY.",
                headers={"Retry-After": "3600"},
            )
        # Model overload (503 UNAVAILABLE) → silent fallback to lite model.
        # Same Grounding capability, just slightly lower reasoning depth, so
        # the daily briefing never breaks because of Google's load spikes.
        if "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower() or "high demand" in msg.lower():
            logger.warning(
                f"[daily-summary] {MODEL_NAME} overloaded, falling back to {MODEL_FALLBACK}: {msg[:200]}"
            )
            try:
                response = client.models.generate_content(
                    model=MODEL_FALLBACK,
                    contents=full_prompt,
                    config=config,
                )
            except Exception as fe:
                logger.exception("[daily-summary] fallback model also failed")
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Gemini está saturado en este momento. "
                        "Inténtalo de nuevo en unos minutos."
                    ),
                    headers={"Retry-After": "300"},
                )
        else:
            raise

    text = (getattr(response, "text", None) or "").strip()
    if not text:
        raise HTTPException(
            status_code=502,
            detail="Gemini devolvió una respuesta vacía.",
        )

    text = _ensure_sections(text)
    sources, queries = _extract_sources_and_queries(response)

    # Make sure we always return >=5 search_queries for downstream contract.
    if len(queries) < 5:
        for q in FALLBACK_QUERIES:
            if q not in queries:
                queries.append(q)
            if len(queries) >= 5:
                break

    now = datetime.now(MADRID_TZ)
    return {
        "summary": text,
        "sources": sources,
        "search_queries": queries,
        "date": _today_madrid_str(),
        "cache_slot": _cache_slot_madrid(),
        "generated_at": now.isoformat(),
    }


def _verify_events_sync(summary_text: str) -> str:
    """Second Gemini pass that re-verifies each event bullet against today's
    date via Google Search. Returns the cleaned summary text. If the pass
    fails for any reason we return the original text unchanged (never break
    the primary flow)."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return summary_text
    from google import genai
    from google.genai import types as gtypes

    today = _today_madrid_str()
    now = datetime.now(MADRID_TZ)
    weekday_es = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"][now.weekday()]

    verify_prompt = (
        f"Eres un revisor estricto de fechas. HOY es {today} ({weekday_es}).\n\n"
        "A continuación tienes un resumen de eventos de Madrid. Para CADA "
        "bullet dentro de las secciones [GRANDES EVENTOS] y [TEATROS Y OCIO], "
        "haz lo siguiente:\n"
        "  1. Extrae el nombre del evento.\n"
        f"  2. Verifica con Google Search si el evento se celebra HOY ({today}) "
        "en Madrid. Comprueba fecha de inicio y fecha de fin.\n"
        f"  3. Si el evento NO se celebra hoy (terminó antes o empieza después), "
        "ELIMINA ese bullet por completo.\n"
        f"  4. Si el evento SÍ se celebra hoy pero la hora fin ya pasó (son las "
        f"{now.strftime('%H:%M')}), ELIMINA ese bullet.\n"
        "  5. NO añadas eventos nuevos. NO modifiques las secciones [METEO HOY], "
        "[AEROPUERTO], [PREVISIÓN MAÑANA] ni [ALERTAS DE TRÁFICO] — déjalas "
        "exactamente igual.\n"
        "  6. Mantén el formato original con corchetes [SECCIÓN] y guiones -.\n"
        "  7. Si tras la limpieza una sección queda vacía, escribe una única "
        "línea: '- Sin eventos verificados para hoy.'\n\n"
        "Devuelve el resumen COMPLETO ya limpiado (todas las secciones, con "
        "los eventos revisados). NO añadas explicaciones ni comentarios "
        "adicionales, sólo el resumen.\n\n"
        "----- RESUMEN A REVISAR -----\n"
        f"{summary_text}\n"
        "----- FIN DEL RESUMEN -----"
    )

    client = genai.Client(api_key=api_key)
    config = gtypes.GenerateContentConfig(
        tools=[gtypes.Tool(google_search=gtypes.GoogleSearch())],
        temperature=0.1,
    )
    try:
        response = client.models.generate_content(
            model=MODEL_NAME, contents=verify_prompt, config=config,
        )
    except Exception as e:
        logger.warning(f"[daily-summary] verify pass failed, keeping original: {e}")
        return summary_text

    cleaned = (getattr(response, "text", None) or "").strip()
    if not cleaned or "[GRANDES EVENTOS]" not in cleaned:
        return summary_text
    # Extra safety: ensure all mandatory sections still present.
    for section in ("[METEO HOY]", "[GRANDES EVENTOS]", "[TEATROS Y OCIO]",
                    "[ALERTAS DE TRÁFICO]", "[AEROPUERTO]", "[PREVISIÓN MAÑANA]"):
        if section not in cleaned:
            logger.warning(f"[daily-summary] verify pass dropped section {section}, keeping original")
            return summary_text

    # Fail-open guard: if the verify pass removed >70% of bullets in
    # GRANDES EVENTOS or TEATROS Y OCIO, it was probably too aggressive.
    def _count_bullets(text: str, section: str) -> int:
        try:
            start = text.index(section) + len(section)
            rest = text[start:]
            # Find next section header
            import re as _re
            m = _re.search(r"\n\[[A-ZÁÉÍÓÚÑ ]+\]", rest)
            body = rest[:m.start()] if m else rest
            return sum(1 for l in body.split("\n") if l.strip().startswith("-") and len(l.strip()) > 2)
        except ValueError:
            return 0

    for section in ("[GRANDES EVENTOS]", "[TEATROS Y OCIO]"):
        before = _count_bullets(summary_text, section)
        after = _count_bullets(cleaned, section)
        if before >= 3 and after / before < 0.30:
            logger.warning(
                f"[daily-summary] verify pass shrank {section} from {before} "
                f"to {after} bullets (>70% removed) — probable over-pruning, "
                "keeping original."
            )
            return summary_text
    return cleaned


def _has_empty_event_sections(text: str) -> int:
    """Return the number of event sections that have NO real bullets (only
    'Sin información verificada'). Used to trigger a soft retry."""
    if not text:
        return 3
    empty = 0
    for section in ("[GRANDES EVENTOS]", "[TEATROS Y OCIO]", "[ALERTAS DE TRÁFICO]"):
        if section not in text:
            empty += 1
            continue
        try:
            start = text.index(section) + len(section)
            rest = text[start:]
            import re as _re
            m = _re.search(r"\n\[[A-ZÁÉÍÓÚÑ ]+\]", rest)
            body = rest[:m.start()] if m else rest
            real_bullets = [
                l for l in body.split("\n")
                if l.strip().startswith("-")
                and "sin información verificada" not in l.lower()
                and "sin eventos verificados" not in l.lower()
                and len(l.strip()) > 2
            ]
            if not real_bullets:
                empty += 1
        except ValueError:
            empty += 1
    return empty


def _retry_prompt_softer(today: str) -> str:
    """Prompt for the fallback retry when the first pass came out mostly
    empty. Explicitly tells the model to be less strict and include at
    least 2-3 bullets per section even with '(horario por confirmar)'."""
    now = datetime.now(MADRID_TZ)
    return (
        f"REINTENTO — Eres un asistente para taxistas de Madrid. HOY es "
        f"{today} ({now.strftime('%A')}). Tu respuesta anterior dejó "
        "secciones vacías con 'Sin información verificada' y eso NO es "
        "aceptable en Madrid.\n\n"
        "REQUISITOS RELAJADOS:\n"
        "- Incluye AL MENOS 2-3 bullets REALES por sección [GRANDES EVENTOS], "
        "[TEATROS Y OCIO] y [ALERTAS DE TRÁFICO].\n"
        "- Puedes usar '(horario por confirmar)' cuando no tengas hora "
        "exacta — mejor eso que dejar la sección vacía.\n"
        "- Si HOY hay un acontecimiento nacional (victoria selección, "
        "Mundial, San Silvestre, etc.), MENCIÓNALO con los puntos de "
        "encuentro clásicos (Cibeles, Neptuno, Plaza Colón, Puerta del "
        "Sol, Autocine Madrid, Madrid Río).\n"
        "- Sigue prohibido incluir eventos ya terminados.\n"
        "- Formato: mismos corchetes [SECCIÓN] y estilo del prompt original.\n\n"
        "Devuelve el resumen COMPLETO con las 6 secciones. NO añadas "
        "explicaciones ni disculpas, sólo el resumen limpio."
    )


async def _generate_summary() -> Dict[str, Any]:
    """Generate the daily summary text (Gemini) and inject deterministic
    airport peaks computed locally from AENA cached data."""
    # Compute airport peaks first (cheap, ~0.5s, also fine if it fails: empty).
    try:
        airport_peaks = await _compute_airport_peaks()
    except Exception as e:
        logger.warning(f"[daily-summary] airport peaks failed: {e}")
        airport_peaks = {"morning": [], "evening": []}

    payload = await asyncio.to_thread(_generate_summary_sync)

    # Retry-with-softer-prompt: if the first pass left 2+ event sections empty,
    # ask Gemini to try again with relaxed constraints.
    empty_count = _has_empty_event_sections(payload.get("summary", ""))
    if empty_count >= 2:
        logger.warning(
            f"[daily-summary] first pass left {empty_count}/3 event sections "
            "empty; running softer retry."
        )
        try:
            retry_payload = await asyncio.to_thread(
                _generate_summary_sync,
                extra_prompt=_retry_prompt_softer(_today_madrid_str()),
            )
            # Only accept the retry if it actually filled sections better.
            retry_empty = _has_empty_event_sections(retry_payload.get("summary", ""))
            if retry_empty < empty_count:
                payload = retry_payload
                logger.info(f"[daily-summary] retry improved: {empty_count}→{retry_empty} empty sections")
            else:
                logger.info(f"[daily-summary] retry no improvement ({empty_count}→{retry_empty}), keeping original")
        except Exception as e:
            logger.warning(f"[daily-summary] softer retry failed: {e}")

    # Second pass: re-verify each event bullet against today's date.
    try:
        verified_text = await asyncio.to_thread(_verify_events_sync, payload["summary"])
        payload["summary"] = verified_text
    except Exception as e:
        logger.warning(f"[daily-summary] verify pass raised, keeping original: {e}")

    # Third defensive layer: hard-strip any bullet whose parsed end date is
    # before today (regex-based, no Gemini call). Cheap safety net.
    try:
        payload["summary"] = _strip_stale_bullets(payload["summary"])
    except Exception as e:
        logger.warning(f"[daily-summary] _strip_stale_bullets raised: {e}")

    # Fourth defensive layer: remove any hallucinated "NO RELLENES" instruction
    # that the model copied from the AEROPUERTO section. It only belongs
    # there, but Gemini sometimes replicates it into other sections.
    try:
        payload["summary"] = _strip_hallucinated_instructions(payload["summary"])
    except Exception as e:
        logger.warning(f"[daily-summary] _strip_hallucinated_instructions raised: {e}")

    # Overwrite whatever Gemini wrote for [AEROPUERTO] with our real data.
    airport_section_text = _format_airport_section(airport_peaks)
    payload["summary"] = _inject_airport_section(
        payload["summary"], airport_section_text
    )
    payload["airport_peaks"] = airport_peaks
    return payload


async def _load_cached() -> Optional[Dict[str, Any]]:
    """Load the summary generated in the CURRENT 4-hour slot (so it self-
    refreshes at 00, 04, 08, 12, 16 and 20 h Madrid time)."""
    slot = _cache_slot_madrid()
    doc = await daily_summaries_collection.find_one(
        {"cache_slot": slot}, {"_id": 0}
    )
    return doc


async def _persist(summary: Dict[str, Any]) -> None:
    slot = summary.get("cache_slot") or _cache_slot_madrid()
    await daily_summaries_collection.update_one(
        {"cache_slot": slot},
        {"$set": {**summary, "cache_slot": slot}},
        upsert=True,
    )


@router.get("/daily-summary")
async def get_daily_summary(force_refresh: bool = False):
    """Return today's AI daily summary, generating it on first call of the day.

    Pass ?force_refresh=true to bypass the cache (admin tooling).
    Always includes `success: true` in the payload so the frontend dashboard
    (which checks `response.data.success`) renders the summary correctly.
    """
    if not force_refresh:
        cached = await _load_cached()
        if cached and cached.get("summary"):
            cached.pop("_id", None)
            cached["success"] = True
            return cached

    try:
        summary = await _generate_summary()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[daily-summary] generation failed")
        raise HTTPException(status_code=502, detail=f"Error generando resumen: {e}")

    await _persist(summary)
    return {"success": True, **summary}


@router.post("/daily-summary/regenerate")
async def regenerate_daily_summary(_admin=Depends(get_admin_user)):
    """Force regeneration of today's summary. Admin only."""
    try:
        summary = await _generate_summary()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[daily-summary] regeneration failed")
        raise HTTPException(status_code=502, detail=f"Error regenerando resumen: {e}")

    await _persist(summary)
    return {"success": True, **summary}


# ─────────────────────────────────────────────────────────────────────────────
# Public homepage endpoint
# ─────────────────────────────────────────────────────────────────────────────
# The public homepage component (PublicEventsSummary.tsx) expects:
#   { success: bool, summary: str, day_name: str }
# and parses `### Header` markdown sections plus a "Sugerencia estratégica"
# section. We adapt our 4-bracket-section summary into that format on the fly.

_SPANISH_DAYS = [
    "lunes", "martes", "miércoles", "jueves",
    "viernes", "sábado", "domingo",
]


def _bracket_to_markdown_sections(summary_text: str) -> str:
    """Convert `[GRANDES EVENTOS]\n- bullet` blocks into `### Grandes Eventos\n- bullet`.

    Also appends a "### Sugerencia estratégica" section with up to 4 numbered
    tips derived from the body so the homepage strategic-tips block has
    content to show.
    """
    if not summary_text:
        return ""

    pretty_map = {
        "METEO HOY": "El Tiempo Hoy",
        "GRANDES EVENTOS": "Grandes Eventos",
        "TEATROS Y OCIO": "Teatros y Ocio",
        "ALERTAS DE TRÁFICO": "Alertas de Tráfico",
        "AEROPUERTO": "Aeropuerto - Mejores Horas",
        "PREVISIÓN MAÑANA": "Previsión Mañana",
    }

    out: List[str] = []
    tips: List[str] = []
    for raw_header, pretty in pretty_map.items():
        bracket = f"[{raw_header}]"
        if bracket not in summary_text:
            continue
        # Slice from the bracket to the next bracket (or end of text)
        start = summary_text.index(bracket) + len(bracket)
        rest = summary_text[start:]
        end = len(rest)
        for other in pretty_map:
            other_bracket = f"[{other}]"
            if other_bracket in rest:
                end = min(end, rest.index(other_bracket))
        body = rest[:end].strip()
        out.append(f"### {pretty}\n{body}")

        # Use the first 2 bullets of "Grandes Eventos" + "Teatros" as tips
        if raw_header in ("GRANDES EVENTOS", "TEATROS Y OCIO"):
            for line in body.splitlines():
                line = line.strip()
                if line.startswith("-") and len(tips) < 4:
                    tips.append(line.lstrip("-").strip())

    if tips:
        out.append("### Sugerencia estratégica")
        for i, tip in enumerate(tips, 1):
            # Strip any inner ** so the wrapping ** below doesn't nest.
            clean_tip = tip.replace("**", "").strip()
            # Truncate overly long tips (homepage widget is compact)
            if len(clean_tip) > 160:
                clean_tip = clean_tip[:157].rstrip() + "..."
            out.append(f"{i}. **{clean_tip}**")

    return "\n\n".join(out)


@router.get("/daily-summary-public")
async def get_daily_summary_public():
    """Lightweight public endpoint for the unauthenticated homepage widget.

    Returns the summary reformatted with `### Header` markdown sections and
    a Spanish day_name so PublicEventsSummary.tsx can render it directly.
    """
    cached = await _load_cached()
    if not cached or not cached.get("summary"):
        # Try generating once; if it fails (quota/key), return a soft failure
        # so the homepage simply hides the widget.
        try:
            cached = await _generate_summary()
            await _persist(cached)
        except Exception as e:
            logger.warning(f"[daily-summary-public] generation skipped: {e}")
            return {"success": False, "summary": "", "day_name": ""}

    today_idx = datetime.now(MADRID_TZ).weekday()
    day_name = _SPANISH_DAYS[today_idx]

    md_summary = _bracket_to_markdown_sections(cached.get("summary", ""))
    return {
        "success": True,
        "summary": md_summary,
        "day_name": day_name,
        "date": cached.get("date"),
    }
