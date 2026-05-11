"""
AI-powered daily event summary for Madrid taxi drivers.

Uses Google Gemini (flash-lite) with Google Search grounding (real-time web search)
to find verified events at IFEMA, WiZink Center, Movistar Arena, theatres, traffic,
and other movility-affecting items. Designed to eliminate hallucinations.

Endpoints:
    GET  /api/events/daily-summary
        Public. Returns today's cached summary. If missing, generates on demand.
    POST /api/events/daily-summary/regenerate
        Admin only. Forces immediate regeneration (bypasses cache).
"""
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
import os
import asyncio
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

# Gemini model that supports Google Search grounding.
# Note: gemini-1.5-flash-lite was sunset; the current equivalent flash-lite tier
# with grounding is gemini-2.5-flash-lite (500 RPD free, fast, accurate citations).
GEMINI_MODEL = "gemini-2.5-flash-lite"

# Generation config requested by user
MAX_OUTPUT_TOKENS = 1500
TEMPERATURE = 0.1


def _build_prompt(today_human: str, today_iso: str, weekday_es: str,
                  tomorrow_human: str) -> str:
    """Build the prompt that forces real web search + telegram-style report."""
    return f"""Eres un asistente que prepara un INFORME DE MOVILIDAD para taxistas profesionales de Madrid.

FECHA OBJETIVO: HOY → {weekday_es}, {today_human} ({today_iso})
MAÑANA → {tomorrow_human}

PASO 1 — BÚSQUEDAS OBLIGATORIAS (usa Google Search múltiples veces ANTES de redactar):
- "WiZink Center agenda {today_human}"
- "Movistar Arena Madrid {today_human}"
- "IFEMA Madrid ferias hoy {today_human}"
- "Real Madrid partido Bernabéu {today_iso}"
- "Atlético de Madrid Metropolitano {today_iso}"
- "Rayo Vallecano partido Vallecas {today_iso}"
- "Getafe CF Coliseum {today_iso}"
- "conciertos Madrid hoy {today_human}"
- "musicales Gran Vía Madrid {today_human}"
- "teatros Madrid {weekday_es}"
- "fiestas San Isidro Madrid {today_human}"
- "fiestas barrios Madrid hoy {weekday_es}"
- "fiestas patronales municipios Madrid {today_human}" (Rivas, Alcorcón, Móstoles, Leganés, Getafe, Pozuelo, etc.)
- "cortes de tráfico hoy Madrid {today_iso}"
- "manifestaciones Madrid hoy {today_iso}"
- "obras EMT Madrid {today_human}"
- "eventos Madrid mañana {tomorrow_human}"

PASO 2 — REDACTA EL INFORME usando esta plantilla EXACTA. Estilo telegrama: directo, profesional, frases cortas. Usa **negritas** para lugares y horas:

Briefing de movilidad Madrid · {today_human}

[GRANDES EVENTOS]
- **HH:MMh** · NOMBRE en **LUGAR**. (1 línea por evento; incluye IFEMA, WiZink, Movistar Arena, Bernabéu, Metropolitano, Vallecas, Coliseum Getafe y conciertos destacados).
- Si no hay nada: "Sin eventos masivos hoy."

[TEATROS Y OCIO]
- **HH:MMh** · OBRA en **TEATRO**. (Musicales de Gran Vía; eventos de barrio como San Isidro, fiestas patronales en municipios).
- Si lunes y los teatros descansan: "Mayoría de teatros cerrados (descanso lunes). Funciones confirmadas: ..."
- Si no hay nada: "Sin teatros ni eventos de ocio hoy."

[ALERTAS DE TRÁFICO]
- **HH:MM-HH:MMh** · CALLE/ZONA — MOTIVO (cortes, obras EMT, manifestaciones).
- Si no hay nada: "Sin cortes ni manifestaciones programadas."

[PREVISIÓN MAÑANA]
- **HH:MMh** · EVENTO que afecte al turno de madrugada/mañana (vuelos especiales, espectáculos que terminan tarde, eventos de primera hora del día siguiente).
- Si no hay nada relevante: "Mañana sin eventos destacados conocidos."

REGLAS:
- LAS 4 SECCIONES SIEMPRE DEBEN APARECER EN ESE ORDEN, aunque alguna esté vacía con su frase correspondiente.
- Cada dato debe provenir de resultados reales de búsqueda. No inventes. No respondas de memoria.
- Filtra estrictamente por fecha HOY ({today_iso}) excepto en [PREVISIÓN MAÑANA].
- Para festivales con muchas actuaciones (San Isidro, etc.), agrúpalas en 1 línea: "Todo el día · **Fiestas de San Isidro** en Pradera de San Isidro".
- NO incluyas URLs ni disclaimers sobre IA.
- TONO: profesional, directo, tutea al taxista. Sin coloquialismos. Frases breves.
"""


async def generate_daily_summary() -> dict:
    """Generate today's event summary using Gemini with Google Search grounding."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"success": False, "error": "GEMINI_API_KEY no configurada", "summary": None}

    now = datetime.now(MADRID_TZ)
    today_iso = now.strftime("%Y-%m-%d")
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
    weekday_es = weekdays_es.get(now.strftime("%A"), "")
    today_human = f"{now.day} de {months_es[now.month]} de {now.year}"

    from datetime import timedelta
    tomorrow = now + timedelta(days=1)
    tomorrow_human = f"{tomorrow.day} de {months_es[tomorrow.month]} de {tomorrow.year}"

    prompt = _build_prompt(today_human, today_iso, weekday_es, tomorrow_human)

    try:
        client = genai.Client(api_key=api_key)
        grounding_tool = types.Tool(google_search=types.GoogleSearch())
        config = types.GenerateContentConfig(
            tools=[grounding_tool],
            temperature=TEMPERATURE,
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )

        # Retry on transient 503 (overloaded) / 429 (rate limit) with backoff.
        last_error = None
        response = None
        for attempt in range(4):
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=config,
                )
                break
            except Exception as exc:
                err_str = str(exc)
                last_error = exc
                err_upper = err_str.upper()
                if "503" in err_str or "UNAVAILABLE" in err_upper or "overloaded" in err_str.lower():
                    wait_s = [5, 15, 30][min(attempt, 2)]
                    logger.warning(f"[DailySummary] 503 (attempt {attempt+1}/4). Wait {wait_s}s")
                    if attempt < 3:
                        await asyncio.sleep(wait_s)
                        continue
                elif "429" in err_str or "RESOURCE_EXHAUSTED" in err_upper:
                    wait_s = [30, 60][min(attempt, 1)]
                    logger.warning(f"[DailySummary] 429 (attempt {attempt+1}/4). Wait {wait_s}s")
                    if attempt < 2:
                        await asyncio.sleep(wait_s)
                        continue
                    raise
                raise
        if response is None:
            raise last_error or RuntimeError("Generation failed after retries")

        summary_text = (response.text or "").strip()
        if not summary_text:
            return {"success": False, "error": "Respuesta vacía", "summary": None}

        # Deduplicate consecutive identical lines (Gemini sometimes loops)
        deduped_lines = []
        prev_line = None
        repeat_count = 0
        for line in summary_text.split("\n"):
            stripped = line.strip()
            if stripped == prev_line and stripped:
                repeat_count += 1
                if repeat_count >= 1:
                    continue
            else:
                repeat_count = 0
            deduped_lines.append(line)
            if stripped:
                prev_line = stripped
        summary_text = "\n".join(deduped_lines).strip()

        # Extract grounding metadata (anti-hallucination check)
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
            logger.debug(f"[DailySummary] grounding meta extract: {e}")

        if not search_queries and not sources:
            logger.warning("[DailySummary] No grounding metadata - possible hallucination")
            return {
                "success": False,
                "error": "Gemini no realizó búsquedas web. Reintentar.",
                "summary": None,
            }

        # Truncation guard
        last_chars = summary_text.rstrip()[-3:]
        if not any(c in last_chars for c in ['.', '!', '?', '"', ')', ']']):
            logger.warning(f"[DailySummary] Possibly truncated. Tail: {last_chars!r}")

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
            "error": f"{type(e).__name__}: {str(e)[:200]}",
            "summary": None,
        }


async def save_summary(result: dict) -> None:
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


async def get_cached_summary(date_iso: str):
    return await daily_summaries_collection.find_one({"date": date_iso}, {"_id": 0})


async def ensure_today_summary() -> dict:
    """Get today's summary. If missing, generate now. On failure, fall back."""
    now = datetime.now(MADRID_TZ)
    today_iso = now.strftime("%Y-%m-%d")

    cached = await get_cached_summary(today_iso)
    if cached:
        return {"success": True, "cached": True, **cached}

    logger.info(f"[DailySummary] No cache for {today_iso}, generating fresh...")
    result = await generate_daily_summary()
    if result.get("success"):
        await save_summary(result)
        return {"cached": False, **result}

    fallback = await daily_summaries_collection.find_one({}, {"_id": 0}, sort=[("date", -1)])
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
    """Public. Returns today's AI summary (cached or fresh)."""
    return await ensure_today_summary()


@router.post("/daily-summary/regenerate")
async def regenerate_daily_summary(_admin: dict = Depends(get_admin_user)):
    """Admin-only: force regeneration."""
    result = await generate_daily_summary()
    if result.get("success"):
        await save_summary(result)
        return {"cached": False, **result}
    raise HTTPException(status_code=502, detail=result.get("error", "Error generando resumen"))
