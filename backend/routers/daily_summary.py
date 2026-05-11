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

# Gemini model that supports Google Search grounding
GEMINI_MODEL = "gemini-2.5-flash"


def _build_prompt(today_human: str, today_iso: str, weekday_es: str) -> str:
    """Build the system + user prompt that forces real web search."""
    return f"""Eres un asistente que prepara un resumen diario de eventos en Madrid para taxistas profesionales.

OBJETIVO: Identificar los EVENTOS MÁS IMPORTANTES de HOY ({weekday_es}, {today_human}) en Madrid que generen demanda de taxi, para que el conductor sepa dónde habrá clientes.

REGLAS DE BÚSQUEDA (OBLIGATORIO):
1. Usa la herramienta Google Search MÚLTIPLES VECES antes de responder. No respondas de memoria.
2. Realiza al menos UNA búsqueda específica POR CADA fuente:
   - "WiZink Center conciertos {today_human}"
   - "Movistar Arena Madrid eventos {today_human}"
   - "IFEMA Madrid ferias {today_human}"
   - "Madrid eventos hoy {today_human}" (agenda municipal esmadrid.com)
   - "Madrid cortes tráfico hoy {today_iso}"
   - "partido Real Madrid Atlético Madrid {today_iso}"
3. Filtra estrictamente por fecha: solo eventos con fecha HOY ({today_iso}).

QUÉ INCLUIR EN EL RESUMEN (PRIORIDAD ESTRICTA — máximo 6 eventos en total):
1. Conciertos en WiZink Center o Movistar Arena (siempre incluir si los hay, con HORA exacta y artista).
2. Partidos en el Bernabéu o Metropolitano (con HORA).
3. Ferias grandes en IFEMA con nombre del evento (1 línea agrupada, NO listar pabellones).
4. Festivales masivos del Ayuntamiento agrupados en UNA línea (ej: "San Isidro: actuaciones todo el día en Pradera de San Isidro"). NO listes cada actuación individualmente.
5. Otros eventos masivos puntuales que afecten zonas concretas.

FORMATO DE SALIDA (texto plano, sin markdown, MÁXIMO 1200 CARACTERES, OBLIGATORIO terminar el mensaje correctamente):

Línea 1 (saludo): "Buenos días, compañero. Esto es lo que te espera hoy en Madrid:"
Línea en blanco.
Bloque de eventos (máximo 6 líneas):
- [HORA] · [EVENTO] en [LUGAR]. [Por qué te importa: zona caliente para recogidas tras evento, etc.]
Línea en blanco.
Bloque de avisos de tráfico (máximo 3 líneas, solo los más importantes):
⚠ Atención: [calle/zona] — [motivo breve].
Línea en blanco.
Cierre obligatorio: "¡Buena jornada y buen turno!"

REGLA CRÍTICA: el mensaje debe estar COMPLETO y terminar con la frase de cierre. Si no caben todos los eventos, prioriza WiZink/Movistar Arena/IFEMA/partidos sobre actuaciones de barrio. Si hay un festival con muchas actuaciones (como San Isidro), agrúpalas en UNA SOLA línea genérica, NO listes cada una.

NO INCLUYAS:
- Listados largos de actuaciones de un mismo festival (agrúpalas).
- Eventos de otros días.
- Disclaimers sobre IA.
- URLs en el cuerpo del texto.
- Markdown (* _ # etc.).

TONO: Profesional pero cercano. Tutea al taxista. Directo y práctico.
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
            temperature=0.6,
            max_output_tokens=8192,
        )

        # google-genai is sync; wrap in thread to avoid blocking event loop
        import asyncio
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=GEMINI_MODEL,
            contents=prompt,
            config=config,
        )

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
