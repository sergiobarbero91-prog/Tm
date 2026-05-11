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

OBJETIVO: Identificar eventos REALES y VERIFICADOS que se celebran HOY ({weekday_es}, {today_human}) en Madrid, para que el taxista sepa dónde habrá demanda y dónde hay obras o cortes.

REGLAS DE BÚSQUEDA (OBLIGATORIO):
1. Usa la herramienta Google Search MÚLTIPLES VECES antes de responder. No respondas de memoria.
2. Realiza al menos UNA búsqueda específica POR CADA fuente de esta lista:
   - Búsqueda 1: "WiZink Center conciertos {today_human}" o "WiZink Center hoy"
   - Búsqueda 2: "Movistar Arena Madrid eventos {today_human}" o "Movistar Arena hoy"
   - Búsqueda 3: "IFEMA Madrid ferias {today_human}" o "IFEMA hoy programa"
   - Búsqueda 4: "esmadrid.com agenda {today_human}" o "Madrid eventos hoy {weekday_es}"
   - Búsqueda 5: "Madrid cortes tráfico hoy {today_iso}" o "Madrid obras tráfico {today_human}"
3. Si una primera búsqueda no da resultados claros, REFORMULA y vuelve a buscar con sinónimos (ej. "conciertos en Madrid esta noche", "qué hacer en Madrid hoy").
4. Cada evento que menciones DEBE provenir de resultados reales de búsqueda con fecha verificada.
5. Filtra estrictamente: solo eventos con fecha HOY ({today_iso}). Descarta cualquier evento de otro día.
6. Si tras buscar no encuentras eventos en una fuente concreta, indícalo así: "(Sin eventos confirmados hoy en [fuente])".

QUÉ BUSCAR (en orden de prioridad para el taxista):
- Conciertos y espectáculos en WiZink Center y Movistar Arena (con hora exacta y nombre del artista).
- Ferias, congresos y exposiciones grandes en IFEMA (con horario y pabellón si lo encuentras).
- Eventos masivos del Ayuntamiento (esmadrid.com / madrid.es): cabalgatas, manifestaciones convocadas, San Isidro, maratones, festivales, etc.
- Obras importantes o cortes de tráfico en calles principales (Gran Vía, Castellana, Alcalá, M-30) si aparecen en madrid.es.
- Partidos del Real Madrid en el Bernabéu o Atlético en el Metropolitano si se juegan hoy.

FORMATO DE SALIDA (texto plano, sin markdown ni asteriscos):
- Empieza con: "Buenos días, compañero. Esto es lo que te espera hoy en Madrid:"
- Lista los eventos como bullets con guión:
    - [HORA] · [EVENTO] en [LUGAR]. [Por qué te importa: zona caliente para recogidas tras el evento, etc.]
- Si hay obra o corte importante: línea al final con "⚠ Atención: [calle/zona] — [motivo]."
- Si tras buscar no hay nada confirmado en ninguna fuente, di literalmente:
    "He revisado WiZink Center, Movistar Arena, IFEMA y la agenda municipal y hoy no aparecen eventos masivos confirmados. Día tranquilo de jornada habitual."
- Termina con una línea motivadora corta y profesional (ej: "¡Buena jornada y buen turno!").
- Máximo 1500 caracteres en total. Sé conciso pero útil.

NO INCLUYAS:
- Eventos de otros días (ni mañana ni ayer).
- Eventos genéricos sin nombre concreto ni hora.
- Disclaimers largos sobre IA.
- URLs en el cuerpo del texto.
- Listas vacías repetidas de "no he podido confirmar"; agrupa las fuentes sin resultados en una sola línea.

TONO: Profesional pero cercano. Tutea al taxista. Lenguaje directo y práctico, sin coloquialismos excesivos.
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
            temperature=0.7,
            max_output_tokens=4096,
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
