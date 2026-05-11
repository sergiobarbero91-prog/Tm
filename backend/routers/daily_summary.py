"""
AI-powered daily event summary for Madrid taxi drivers.

Uses Google Gemini with Google Search grounding (real-time web search)
to find verified events at IFEMA, WiZink Center, Movistar Arena and
the official Madrid city events agenda. Designed to eliminate
hallucinations: if no real data is found, returns an explicit error
rather than inventing an empty day.

Endpoints:
    GET  /api/events/daily-summary
        Public. Returns today's cached summary. If missing/stale, generates
        on-demand. If generation fails, returns last successful summary
        with an error flag.

    POST /api/events/daily-summary/regenerate
        Admin only. Forces immediate regeneration (bypasses cache).

Background scheduler in server.py triggers regeneration every day at
05:00 Madrid time, with hourly retries until success.
"""
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
import os
import pytz
import logging

from google import genai
from google.genai import types

from shared import (
    daily_summaries_collection,
    get_admin_user,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["DailySummary"])

MADRID_TZ = pytz.timezone('Europe/Madrid')

# Venues / sources we MUST ground against
GROUNDING_SOURCES = [
    "ifema.es",
    "wizinkcenter.es",
    "movistararena.es",
    "esmadrid.com",
    "madrid.es",
]

# Gemini model that supports Google Search grounding (flash-lite has 500 RPD free vs 20 for flash)
GEMINI_MODEL = "gemini-2.5-flash-lite"


def _build_prompt(today_human: str, today_iso: str, weekday_es: str) -> str:
    """Build the system + user prompt that forces real web search."""
    return f"""Eres un asistente que prepara un briefing zonal diario para taxistas de Madrid.

FECHA OBJETIVO: HOY → {weekday_es}, {today_human} ({today_iso})

PASO 1 — BÚSQUEDAS OBLIGATORIAS (haz TODAS estas búsquedas con Google Search ANTES de redactar):
1. "WiZink Center agenda eventos {today_human}"
2. "Movistar Arena Madrid programación {today_human}"
3. "IFEMA Madrid ferias hoy {today_human}"
4. "Real Madrid Atlético Madrid partido hoy {today_iso}"
5. "musicales Gran Vía Madrid funciones {today_human}"
6. "cortes de tráfico hoy en Madrid {today_iso}"
7. "manifestaciones Madrid hoy {today_iso}"
8. "agenda esmadrid.com {today_human}"
9. "San Isidro Madrid programa {today_human}"
10. "festivales barrios Madrid hoy {weekday_es}"

PASO 2 — REDACTAR USANDO ESTA PLANTILLA EXACTA (rellena cada sección con datos REALES de las búsquedas; no inventes; si una sección no tiene resultados, usa el texto de "vacío" que indico):

Buenos días, compañero. Briefing de hoy en Madrid:

🏟 GRANDES RECINTOS (IFEMA · WIZINK · MOVISTAR ARENA)
[Aquí 2-5 líneas. Cada línea con formato: - HH:MMh · NOMBRE_EVENTO en LUGAR]
[Si no encuentras nada: - Sin eventos masivos confirmados hoy.]

⚽ ESTADIOS (BERNABÉU · METROPOLITANO)
[Aquí 1-3 líneas con partidos o eventos. Formato: - HH:MMh · COMPETICIÓN: EQUIPO vs EQUIPO en LUGAR]
[Si no hay partidos: - Sin partidos ni eventos hoy en los estadios.]

🎭 EJE GRAN VÍA · MUSICALES Y TEATROS
[Aquí 2-4 líneas. Formato: - HH:MMh · OBRA en TEATRO]
[Si es lunes y muchos teatros descansan: - La mayoría de teatros descansan los lunes. Funciones confirmadas hoy: ... (listar las que sí tengan)]
[Si no hay nada: - Sin funciones confirmadas hoy en Gran Vía.]

🚧 CORTES DE TRÁFICO Y MANIFESTACIONES
[Aquí 2-5 líneas. Formato: - HH:MM-HH:MMh · CALLE/ZONA — MOTIVO]
[Si no hay nada: - Sin cortes importantes reportados hoy.]

🎉 EVENTOS DE DISTRITO Y FESTIVALES DE BARRIO
[Aquí 2-5 líneas. Formato: - HH:MMh · EVENTO en BARRIO/ZONA]
[Para San Isidro u otros festivales grandes con muchas actuaciones, agrupa: - Todo el día · Fiestas de San Isidro: actuaciones, conciertos y verbenas en Pradera de San Isidro y entorno.]
[Si no hay nada: - Sin eventos de distrito relevantes hoy.]

¡Buena jornada y buen turno!

REGLAS:
- LAS 5 SECCIONES (🏟, ⚽, 🎭, 🚧, 🎉) DEBEN APARECER SIEMPRE EN ESE ORDEN, aunque alguna esté vacía con su texto correspondiente.
- Cada evento debe provenir de resultados REALES de tus búsquedas. No inventes. No uses datos de memoria.
- Filtra estrictamente por fecha HOY ({today_iso}). Descarta eventos de otros días.
- NO incluyas markdown (*, _, #, **).
- NO incluyas URLs en el cuerpo.
- NO incluyas disclaimers sobre IA.
- TONO profesional, tutea al taxista, frases breves y útiles.
- El mensaje DEBE terminar con "¡Buena jornada y buen turno!" (no te quedes a mitad).
- Sustituye los textos entre [corchetes] por contenido real. NO dejes los corchetes en la respuesta final.
"""


async def generate_daily_summary() -> dict:
    """
    Generate today's event summary using Gemini with Google Search grounding.

    Returns dict with keys:
        success: bool
        summary: str (the user-facing text)
        sources: list[dict] (citations from grounding)
        search_queries: list[str]
        generated_at: ISO datetime
        date: ISO date (YYYY-MM-DD)
        error: str | None
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {
            "success": False,
            "error": "GEMINI_API_KEY no configurada",
            "summary": None,
        }

    now = datetime.now(MADRID_TZ)
    today_iso = now.strftime("%Y-%m-%d")
    weekday_es = now.strftime("%A").capitalize()
    # Spanish weekday/month
    weekdays_es = {
        "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
        "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado",
        "Sunday": "Domingo",
    }
    months_es = {
        1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
        7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre",
        11: "noviembre", 12: "diciembre",
    }
    weekday_es = weekdays_es.get(now.strftime("%A"), weekday_es)
    today_human = f"{now.day} de {months_es[now.month]} de {now.year}"

    prompt = _build_prompt(today_human, today_iso, weekday_es)

    try:
        client = genai.Client(api_key=api_key)
        grounding_tool = types.Tool(google_search=types.GoogleSearch())
        config = types.GenerateContentConfig(
            tools=[grounding_tool],
            temperature=0.5,
            max_output_tokens=12288,
        )

        # google-genai is sync; wrap in thread to avoid blocking event loop.
        # Retry on transient 503 (overloaded) / 429 (rate limit) with backoff.
        import asyncio
        last_error = None
        response = None
        for attempt in range(4):  # 4 attempts max
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=config,
                )
                break  # success
            except Exception as exc:
                err_str = str(exc)
                last_error = exc
                err_upper = err_str.upper()
                if "503" in err_str or "UNAVAILABLE" in err_upper or "overloaded" in err_str.lower():
                    wait_s = [5, 15, 30][min(attempt, 2)]
                    logger.warning(f"[DailySummary] Gemini 503 overloaded (attempt {attempt+1}/4). Waiting {wait_s}s...")
                    if attempt < 3:
                        await asyncio.sleep(wait_s)
                        continue
                elif "429" in err_str or "RESOURCE_EXHAUSTED" in err_upper or "quota" in err_str.lower():
                    # Per-minute rate limit: longer wait. Per-day quota: don't retry now, scheduler will retry in 1h.
                    wait_s = [30, 60][min(attempt, 1)]
                    logger.warning(f"[DailySummary] Gemini 429 quota/rate-limit (attempt {attempt+1}/4). Waiting {wait_s}s...")
                    if attempt < 2:
                        await asyncio.sleep(wait_s)
                        continue
                    # After 2 retries on 429, give up — likely daily quota exhausted.
                    logger.error("[DailySummary] Daily quota likely exhausted. Hourly scheduler will retry.")
                    raise
                # Non-retryable error
                raise
        if response is None:
            raise last_error or RuntimeError("Generation failed after retries")

        summary_text = (response.text or "").strip()
        if not summary_text:
            return {
                "success": False,
                "error": "Respuesta vacía de Gemini",
                "summary": None,
            }

        # Extract grounding metadata for transparency
        sources = []
        search_queries = []
        try:
            candidate = response.candidates[0] if response.candidates else None
            gmeta = getattr(candidate, "grounding_metadata", None) if candidate else None
            if gmeta:
                if getattr(gmeta, "web_search_queries", None):
                    search_queries = list(gmeta.web_search_queries)
                if getattr(gmeta, "grounding_chunks", None):
                    for chunk in gmeta.grounding_chunks:
                        web = getattr(chunk, "web", None)
                        if web and getattr(web, "uri", None):
                            sources.append({
                                "uri": web.uri,
                                "title": getattr(web, "title", "") or "",
                            })
        except Exception as e:
            logger.debug(f"[DailySummary] Could not extract grounding metadata: {e}")

        # Validate that grounding actually happened (anti-hallucination)
        if not search_queries and not sources:
            logger.warning("[DailySummary] No grounding metadata returned - possible hallucination")
            return {
                "success": False,
                "error": "Gemini no realizó búsquedas web (sin grounding). Reintentar.",
                "summary": None,
                "raw_response": summary_text,
            }

        # Validate the response is not truncated (must end with punctuation/closing)
        last_chars = summary_text.rstrip()[-3:]
        if not any(c in last_chars for c in ['.', '!', '?', '"', ')']):
            logger.warning(f"[DailySummary] Response appears truncated. Last chars: {last_chars!r}")
            return {
                "success": False,
                "error": "Respuesta truncada por el modelo. Reintentar.",
                "summary": None,
                "raw_response": summary_text,
            }

        return {
            "success": True,
            "summary": summary_text,
            "sources": sources,
            "search_queries": search_queries,
            "generated_at": now.isoformat(),
            "date": today_iso,
            "error": None,
        }
    except Exception as e:
        logger.error(f"[DailySummary] Generation error: {e}")
        return {
            "success": False,
            "error": f"Error generando resumen: {type(e).__name__}: {str(e)[:200]}",
            "summary": None,
        }


async def save_summary(result: dict) -> None:
    """Persist a successful summary to MongoDB (upsert by date)."""
    if not result.get("success"):
        return
    await daily_summaries_collection.update_one(
        {"date": result["date"]},
        {"$set": {
            "date": result["date"],
            "summary": result["summary"],
            "sources": result.get("sources", []),
            "search_queries": result.get("search_queries", []),
            "generated_at": result["generated_at"],
        }},
        upsert=True,
    )
    logger.info(f"[DailySummary] Saved summary for {result['date']}")


async def get_cached_summary(date_iso: str) -> dict | None:
    """Return cached summary for given date, or None."""
    doc = await daily_summaries_collection.find_one(
        {"date": date_iso},
        {"_id": 0},
    )
    return doc


async def ensure_today_summary() -> dict:
    """
    Get today's summary. If missing, generate now.
    Used by the GET endpoint and the scheduler.
    """
    now = datetime.now(MADRID_TZ)
    today_iso = now.strftime("%Y-%m-%d")

    cached = await get_cached_summary(today_iso)
    if cached:
        return {
            "success": True,
            "cached": True,
            **cached,
        }

    # Not cached → generate
    logger.info(f"[DailySummary] No cache for {today_iso}, generating fresh...")
    result = await generate_daily_summary()
    if result.get("success"):
        await save_summary(result)
        return {"cached": False, **result}

    # Generation failed → try fallback to most recent successful summary
    fallback = await daily_summaries_collection.find_one(
        {},
        {"_id": 0},
        sort=[("date", -1)],
    )
    return {
        "success": False,
        "cached": False,
        "error": result.get("error", "No se pudo generar el resumen"),
        "summary": fallback.get("summary") if fallback else None,
        "fallback_date": fallback.get("date") if fallback else None,
        "date": today_iso,
    }


# ============== ENDPOINTS ==============

@router.get("/daily-summary")
async def get_daily_summary():
    """
    Public endpoint. Returns today's AI summary.
    Generates on-demand if cache is empty. If generation fails,
    returns the most recent successful summary with an error flag.
    """
    return await ensure_today_summary()


@router.post("/daily-summary/regenerate")
async def regenerate_daily_summary(
    _admin: dict = Depends(get_admin_user),
):
    """Admin-only: force regeneration of today's summary (bypasses cache)."""
    result = await generate_daily_summary()
    if result.get("success"):
        await save_summary(result)
        return {"cached": False, **result}
    raise HTTPException(
        status_code=502,
        detail=result.get("error", "Error generando resumen"),
    )
