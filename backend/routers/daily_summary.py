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
MODEL_NAME = "gemini-2.5-flash-lite"

# Cache freshness: a stored summary is considered current if it was generated
# today (Madrid date). Otherwise we regenerate on the first GET of the day.
SECTIONS = [
    "[GRANDES EVENTOS]",
    "[TEATROS Y OCIO]",
    "[ALERTAS DE TRÁFICO]",
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


def _today_madrid_str() -> str:
    return datetime.now(MADRID_TZ).strftime("%Y-%m-%d")


def _tomorrow_madrid_str() -> str:
    now = datetime.now(MADRID_TZ)
    return (now.replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(days=1)).strftime("%Y-%m-%d")


def _build_prompt() -> str:
    today = _today_madrid_str()
    return (
        "Eres un asistente para TAXISTAS de Madrid. Genera un briefing TELEGRAM "
        f"con la información REAL del día {today} (zona horaria Europe/Madrid).\n\n"
        "REGLAS ESTRICTAS:\n"
        "1. Usa Google Search para verificar TODO. NO inventes nada.\n"
        "2. Si no encuentras información fiable para una sección, escribe "
        "exactamente 'Sin información verificada para hoy.' en esa sección.\n"
        "3. Usa **negrita** (estilo Telegram, con dobles asteriscos) para "
        "lugares clave, horas y nombres propios.\n"
        "4. Sé conciso: máximo 4-6 bullets por sección, frases cortas.\n"
        "5. Prioriza puntos calientes para taxis: estadios (Bernabéu, Metropolitano, "
        "WiZink Center), grandes teatros del centro, Atocha/Chamartín, T1/T2/T3/T4/T4S "
        "de Barajas, IFEMA.\n"
        "6. No repitas el mismo evento en dos secciones distintas.\n\n"
        "FORMATO OBLIGATORIO (respeta los corchetes y orden):\n"
        "[GRANDES EVENTOS]\n"
        "- bullet con **lugar**, **hora** y motivo\n\n"
        "[TEATROS Y OCIO]\n"
        "- bullet con **teatro/sala**, **hora función** y obra\n\n"
        "[ALERTAS DE TRÁFICO]\n"
        "- bullet con **calle/zona**, motivo y franja horaria\n\n"
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
    return await asyncio.to_thread(_generate_summary_sync)


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
            out.append(f"{i}. **{tip}**")

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
