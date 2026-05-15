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

# Cache freshness: a stored summary is considered current if it was generated
# today (Madrid date). Otherwise we regenerate on the first GET of the day.
SECTIONS = [
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
# 15-35 min after touchdown. We score 30-min windows weighting wide-body
# aircraft 3x normal flights.
PEAK_BIN_MINUTES = 30
DAY_BREAK_HOUR = 5  # 05:00 splits the operational day in Madrid
EVENING_BREAK_HOUR = 17  # 17:00 splits morning vs evening shift
LARGE_FLIGHT_WEIGHT = 3.0
NORMAL_FLIGHT_WEIGHT = 1.0
MIN_PEAK_SEPARATION_MINUTES = 120  # Force the 2 peaks per shift to be at least 2h apart
TERMINALS_FOR_PEAKS = ["T1", "T2", "T3", "T4", "T4S"]


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


async def _compute_airport_peaks() -> Dict[str, List[Dict[str, Any]]]:
    """Return the 2 best terminal-entry times for each shift.

    Output:
      {
        "morning": [ {time, terminal, flights, large, score}, ... ],
        "evening": [...]
      }

    Operates on the AENA cached arrivals for *today*. If AENA is unreachable
    we return empty lists (callers must handle gracefully).
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

    # bucket: (terminal, bin_start_minutes) -> {flights, large, score}
    buckets: Dict[tuple, Dict[str, Any]] = {}
    for terminal in TERMINALS_FOR_PEAKS:
        for arr in all_arrivals.get(terminal, []):
            mins = _time_str_to_minutes(arr.get("time", ""))
            if mins is None:
                continue
            bin_start = (mins // PEAK_BIN_MINUTES) * PEAK_BIN_MINUTES
            key = (terminal, bin_start)
            entry = buckets.setdefault(
                key, {"flights": 0, "large": 0, "score": 0.0}
            )
            entry["flights"] += 1
            if arr.get("is_large"):
                entry["large"] += 1
                entry["score"] += LARGE_FLIGHT_WEIGHT
            else:
                entry["score"] += NORMAL_FLIGHT_WEIGHT

    def _shift_filter(bin_minutes: int, shift: str) -> bool:
        """True if a bin start time belongs to the given shift."""
        h = (bin_minutes // 60) % 24
        if shift == "morning":  # 05:00 - 16:59
            return DAY_BREAK_HOUR <= h < EVENING_BREAK_HOUR
        # evening: 17:00 - 04:59 next day
        return h >= EVENING_BREAK_HOUR or h < DAY_BREAK_HOUR

    def _top_2_for_shift(shift: str) -> List[Dict[str, Any]]:
        candidates = [
            {
                "time": _bin_label(bin_start),
                "minutes": bin_start,
                "terminal": term,
                "flights": data["flights"],
                "large": data["large"],
                "score": round(data["score"], 1),
            }
            for (term, bin_start), data in buckets.items()
            if _shift_filter(bin_start, shift) and data["score"] > 0
        ]
        candidates.sort(key=lambda c: c["score"], reverse=True)

        picked: List[Dict[str, Any]] = []
        for cand in candidates:
            if not picked:
                picked.append(cand)
                continue
            # Enforce >=2h separation in time-of-day terms
            too_close = any(
                abs(((cand["minutes"] - p["minutes"]) + 1440) % 1440)
                < MIN_PEAK_SEPARATION_MINUTES
                or abs(((p["minutes"] - cand["minutes"]) + 1440) % 1440)
                < MIN_PEAK_SEPARATION_MINUTES
                for p in picked
            )
            if too_close:
                continue
            picked.append(cand)
            if len(picked) == 2:
                break

        # Sort by time ascending for readable output
        picked.sort(key=lambda c: c["minutes"])
        # Drop the helper "minutes" field
        for p in picked:
            p.pop("minutes", None)
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
        # Suggest leaving ~30 min before the peak so the taxi is at the
        # terminal exit just as the bulk of passengers start coming out.
        peak_mins = _time_str_to_minutes(p["time"]) or 0
        leave_mins = (peak_mins - 30 + 1440) % 1440
        leave = _bin_label(leave_mins)
        large_tag = f", {p['large']} grandes" if p["large"] else ""
        return (
            f"- **{p['terminal']} a las {p['time']}h** "
            f"({p['flights']} vuelos{large_tag}) — sal hacia el aeropuerto "
            f"sobre las **{leave}h**."
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


def _tomorrow_madrid_str() -> str:
    now = datetime.now(MADRID_TZ)
    return (now.replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(days=1)).strftime("%Y-%m-%d")


def _build_prompt() -> str:
    today = _today_madrid_str()
    return (
        "Eres un asistente para TAXISTAS de Madrid con conocimiento profundo del "
        f"calendario de eventos y vida cultural de la ciudad. Genera un briefing "
        f"TELEGRAM con la información REAL del día {today} (zona horaria Europe/Madrid).\n\n"
        "REGLAS DE BÚSQUEDA (CRÍTICO):\n"
        "1. Usa Google Search EXHAUSTIVAMENTE para verificar TODO. NO inventes nada.\n"
        "2. Madrid SIEMPRE tiene actividad. Si tu primera búsqueda no encuentra "
        "nada, AMPLÍA la búsqueda con consultas alternativas (mínimo 8 queries "
        "diferentes por sección) antes de rendirte:\n"
        "   - Para GRANDES EVENTOS: busca también 'Madrid hoy fiestas patronales', "
        "'San Isidro 2026 programa', 'Las Ventas corrida hoy', 'IFEMA feria mayo', "
        "'Plaza Mayor concierto hoy', 'Pradera San Isidro programación', "
        "'Veranos Villa Madrid', 'eventos al aire libre Madrid hoy', y "
        "calendarios oficiales del Ayuntamiento de Madrid.\n"
        "   - Para TEATROS Y OCIO: busca cartelera teatros centro, Cines Verdi, "
        "Cineteca, exposiciones Reina Sofía/Prado/Thyssen abiertas hoy.\n"
        "   - Para ALERTAS DE TRÁFICO: busca DGT Madrid hoy, manifestaciones, "
        "obras M-30/M-40, cortes esmadrid.es.\n"
        "3. SOLO escribe 'Sin información verificada para hoy.' si después de "
        "TRES rondas de búsqueda con distintas palabras clave SIGUES sin "
        "encontrar absolutamente nada. Es muy raro en Madrid.\n"
        "4. Considera GRANDES EVENTOS (no solo deportivos):\n"
        "   - Partidos Real Madrid / Atlético / Rayo (Bernabéu, Metropolitano, Vallecas)\n"
        "   - Conciertos grandes (WiZink, Palacio de Vistalegre, Movistar Arena)\n"
        "   - Fiestas patronales y festejos del Ayuntamiento (San Isidro, "
        "Dos de Mayo, Veranos de la Villa, Navidad, Carnaval)\n"
        "   - Conciertos al aire libre (Plaza Mayor, Pradera de San Isidro, "
        "Madrid Río, Templo de Debod)\n"
        "   - Festejos taurinos en Las Ventas\n"
        "   - Ferias activas en IFEMA / Casa de Campo\n"
        "   - Eventos cívicos masivos (Día del Orgullo, San Silvestre, etc.)\n"
        "5. Usa **negrita** (estilo Telegram, con dobles asteriscos) para lugares "
        "clave, horas y nombres propios.\n"
        "6. Sé conciso: 4-7 bullets por sección, frases cortas.\n"
        "7. Prioriza puntos calientes para taxis: estadios, grandes teatros del "
        "centro, Atocha/Chamartín, T1/T2/T3/T4/T4S de Barajas, IFEMA, "
        "Pradera San Isidro, Plaza Mayor.\n"
        "8. No repitas el mismo evento en dos secciones distintas.\n\n"
        "FORMATO OBLIGATORIO (respeta los corchetes y orden):\n"
        "[GRANDES EVENTOS]\n"
        "- bullet con **lugar**, **hora** y motivo\n\n"
        "[TEATROS Y OCIO]\n"
        "- bullet con **teatro/sala**, **hora función** y obra\n\n"
        "[ALERTAS DE TRÁFICO]\n"
        "- bullet con **calle/zona**, motivo y franja horaria\n\n"
        "[AEROPUERTO]\n"
        "- NO RELLENES esta sección. El servidor la reemplazará por datos\n"
        "  precomputados de AENA. Déjala vacía o con un placeholder corto.\n\n"
        "[PREVISIÓN MAÑANA]\n"
        "- bullet con tiempo, temperatura y eventos relevantes para mañana ("
        f"{_tomorrow_madrid_str()})\n"
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


def _generate_summary_sync() -> Dict[str, Any]:
    """Call Gemini synchronously (intended to run inside a thread)."""
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
        temperature=0.4,
    )

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=_build_prompt(),
            config=config,
        )
    except Exception as e:
        # Translate provider quota errors (429 RESOURCE_EXHAUSTED) into a clean
        # 503 so the frontend can show a friendlier "intentar más tarde" message.
        msg = str(e)
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
            logger.warning(f"[daily-summary] Gemini quota exhausted: {msg[:200]}")
            raise HTTPException(
                status_code=503,
                detail="Cuota de Gemini agotada. Vuelve a intentarlo más tarde o renueva el GEMINI_API_KEY.",
                headers={"Retry-After": "3600"},
            )
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
        "generated_at": now.isoformat(),
    }


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

    # Overwrite whatever Gemini wrote for [AEROPUERTO] with our real data.
    airport_section_text = _format_airport_section(airport_peaks)
    payload["summary"] = _inject_airport_section(
        payload["summary"], airport_section_text
    )
    payload["airport_peaks"] = airport_peaks
    return payload


async def _load_cached() -> Optional[Dict[str, Any]]:
    today = _today_madrid_str()
    doc = await daily_summaries_collection.find_one(
        {"date": today}, {"_id": 0}
    )
    return doc


async def _persist(summary: Dict[str, Any]) -> None:
    await daily_summaries_collection.update_one(
        {"date": summary["date"]},
        {"$set": summary},
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
