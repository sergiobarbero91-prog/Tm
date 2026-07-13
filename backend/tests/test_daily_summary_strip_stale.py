"""
Tests for the iter_16 defensive filter `_strip_stale_bullets` inside
routers/daily_summary.py.

Third defensive layer added on top of iter_14 (hour-based) and iter_15
(date-verification + verify pass). This is a deterministic regex-based
post-generation filter that scans each bullet inside [GRANDES EVENTOS]
and [TEATROS Y OCIO] for date patterns and drops bullets whose parsed
end date is strictly earlier than today (Madrid).

Coverage:
  UNIT 1: dropping and keeping bullets by date pattern
  UNIT 2: non-event sections (METEO, ALERTAS, AEROPUERTO, PREVISIÓN) untouched
  UNIT 3: section header tracker edge cases (blank lines, bracketed text
          inside a bullet, headers of unknown sections)
  UNIT 4: bullets whose parsed end date == today are KEPT
  UNIT 5: malformed input safety (empty, single-line, only-headers, only-bullets)
  INTEGRATION 1: full _generate_summary pipeline strips Mad Cool + Iberdrola
                 even when _verify_events_sync is an IDENTITY
  INTEGRATION 2: _strip_stale_bullets still runs even if _verify_events_sync
                 raises an exception
  LIVE: force_refresh has zero mad cool / iberdrola music / auditorio bullets
"""
import os
import sys
import asyncio
import pytest
import requests
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers import daily_summary as ds  # noqa: E402
from routers.daily_summary import (  # noqa: E402
    _strip_stale_bullets,
    _today_madrid_str,
    _generate_summary,
    _cache_slot_madrid,
)

BASE_URL = "http://localhost:8001"
MADRID_TZ = pytz.timezone("Europe/Madrid")

TODAY = _today_madrid_str()  # e.g. '2026-07-13'


def _async_wrap(value):
    """Helper: wrap `value` in an awaitable coroutine for async patching."""
    async def _coro(*args, **kwargs):
        return value
    return _coro()


# ═══════════════════════════════════════════════════════════════════════
# UNIT 1 — dropping vs keeping bullets by date pattern
# ═══════════════════════════════════════════════════════════════════════
class TestStripStaleBulletsDropVsKeep:
    """Feed a sample summary containing a mix of past, ongoing, future,
    and non-dated bullets. Assert the correct ones are dropped and kept."""

    def _sample(self):
        # Use dynamic today reference; Mad Cool 10-12 jul is past for 07-13
        return (
            "[METEO HOY]\n"
            "- **Temperatura**: 22-32°C\n\n"
            "[GRANDES EVENTOS]\n"
            "- **Mad Cool 2026** en IFEMA (del 10 al 12 de julio) 20:00\n"
            "- **Iberdrola Music** en Caja Mágica (hasta el 5 de julio) 21:30\n"
            "- **Auditorio Rivas** concierto (del 11 al 12 de julio) 22:00\n"
            "- **Veranos de la Villa** (del 7 de julio al 29 de agosto) horarios variados\n"
            "- **Chulíssima** en Espacio Gran Vía (del 6 al 20 de julio) 21:00\n"
            f"- **Rosalía WiZink** (hoy {TODAY}, 22:00)\n"
            "- **Concierto Bernabéu** sin fecha explícita 20:00\n\n"
            "[TEATROS Y OCIO]\n"
            "- **Sin fecha** función de flamenco 20:30\n\n"
            "[ALERTAS DE TRÁFICO]\n"
            "- Corte M-30\n\n"
            "[AEROPUERTO]\n"
            "- Info\n\n"
            "[PREVISIÓN MAÑANA]\n"
            "- 24-34°C\n"
        )

    def test_mad_cool_dropped(self):
        out = _strip_stale_bullets(self._sample())
        assert "Mad Cool 2026" not in out, \
            f"Mad Cool bullet should be dropped (ended 12 jul, today {TODAY})"

    def test_iberdrola_music_dropped(self):
        out = _strip_stale_bullets(self._sample())
        assert "Iberdrola Music" not in out, \
            "Iberdrola Music bullet ('hasta el 5 de julio') should be dropped"

    def test_auditorio_rivas_dropped(self):
        out = _strip_stale_bullets(self._sample())
        assert "Auditorio Rivas" not in out, \
            "Auditorio Rivas (11-12 julio) should be dropped"

    def test_veranos_villa_kept(self):
        out = _strip_stale_bullets(self._sample())
        assert "Veranos de la Villa" in out, \
            "Veranos de la Villa (ends 29 ago) must be kept"

    def test_chulissima_kept(self):
        out = _strip_stale_bullets(self._sample())
        assert "Chulíssima" in out, \
            "Chulíssima (6-20 julio) must be kept (ends 20 > today 13)"

    def test_rosalia_today_iso_kept(self):
        out = _strip_stale_bullets(self._sample())
        assert "Rosalía WiZink" in out, \
            f"Rosalía bullet with ISO {TODAY} must be kept"

    def test_no_date_bullet_kept_by_default(self):
        out = _strip_stale_bullets(self._sample())
        assert "Concierto Bernabéu" in out, \
            "Bullet with no parseable date should be kept by default"
        assert "Sin fecha" in out, \
            "Teatros bullet with no parseable date must be kept"


# ═══════════════════════════════════════════════════════════════════════
# UNIT 2 — non-event sections must be preserved verbatim
# ═══════════════════════════════════════════════════════════════════════
class TestStripStaleBulletsNonEventSectionsUntouched:
    def test_meteo_past_dated_bullet_preserved(self):
        sample = (
            "[METEO HOY]\n"
            "- **Ola de calor** (hasta el 5 julio) aviso amarillo\n"
            "- Temperatura: 30°C\n\n"
            "[GRANDES EVENTOS]\n"
            "- Nothing\n"
        )
        out = _strip_stale_bullets(sample)
        assert "Ola de calor" in out
        assert "hasta el 5 julio" in out

    def test_alertas_past_dated_bullet_preserved(self):
        sample = (
            "[ALERTAS DE TRÁFICO]\n"
            "- **Obras M-30** hasta el 1 de julio (corte parcial)\n\n"
            "[GRANDES EVENTOS]\n"
            "- x\n"
        )
        out = _strip_stale_bullets(sample)
        assert "Obras M-30" in out

    def test_aeropuerto_past_bullet_preserved(self):
        sample = (
            "[AEROPUERTO]\n"
            "- **T4 · 10:00-11:00** del 1 al 2 de julio (5 vuelos)\n\n"
            "[GRANDES EVENTOS]\n"
            "- x\n"
        )
        out = _strip_stale_bullets(sample)
        assert "T4 · 10:00-11:00" in out

    def test_prevision_manana_past_bullet_preserved(self):
        sample = (
            "[PREVISIÓN MAÑANA]\n"
            "- Recap de eventos (del 1 al 5 de julio) para taxistas\n"
        )
        out = _strip_stale_bullets(sample)
        assert "Recap de eventos" in out


# ═══════════════════════════════════════════════════════════════════════
# UNIT 3 — section header tracker edge cases
# ═══════════════════════════════════════════════════════════════════════
class TestStripStaleBulletsSectionTracker:
    def test_bracketed_text_inside_bullet_does_not_switch_section(self):
        """A bullet like '- [nota] evento (del 1 al 2 de julio)' inside
        [METEO HOY] must NOT flip the tracker to a target section — the
        bullet stays preserved."""
        sample = (
            "[METEO HOY]\n"
            "- [Nota AEMET] alerta terminada (del 1 al 2 de julio)\n"
            "- Temperatura 25°C\n"
        )
        out = _strip_stale_bullets(sample)
        assert "[Nota AEMET]" in out
        assert "del 1 al 2 de julio" in out

    def test_blank_line_between_sections_does_not_break_parsing(self):
        sample = (
            "[METEO HOY]\n"
            "- 25°C\n"
            "\n"
            "\n"
            "[GRANDES EVENTOS]\n"
            "- Mad Cool (del 10 al 12 de julio) 20:00\n"
        )
        out = _strip_stale_bullets(sample)
        assert "Mad Cool" not in out, \
            "Blank lines must not break tracker; Mad Cool should be dropped"
        assert "[GRANDES EVENTOS]" in out
        assert "[METEO HOY]" in out

    def test_unknown_section_header_does_not_crash(self):
        sample = (
            "[NUEVA SECCIÓN INVENTADA]\n"
            "- foo (del 1 al 2 de julio)\n\n"
            "[GRANDES EVENTOS]\n"
            "- bar (del 1 al 2 de julio)\n"
        )
        out = _strip_stale_bullets(sample)
        # Unknown section bullets stay untouched
        assert "foo" in out
        # Real target section bullet still gets dropped
        assert "bar" not in out


# ═══════════════════════════════════════════════════════════════════════
# UNIT 4 — end_date == today is KEPT (only strictly-before is dropped)
# ═══════════════════════════════════════════════════════════════════════
class TestStripStaleBulletsEndDateEqualsToday:
    def test_bullet_ending_today_iso_is_kept(self):
        sample = (
            "[GRANDES EVENTOS]\n"
            f"- **Fescinal último día** (hoy {TODAY}, hasta 01:00)\n"
        )
        out = _strip_stale_bullets(sample)
        assert "Fescinal último día" in out, \
            f"Bullet with today's ISO {TODAY} must be kept"

    def test_bullet_ending_today_written_as_day_month_is_kept(self):
        # Build "D de mes" from today
        today_date = datetime.now(MADRID_TZ).date()
        months_es = [
            "enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
        ]
        month_es = months_es[today_date.month - 1]
        sample = (
            "[GRANDES EVENTOS]\n"
            f"- **Fiesta local** hasta el {today_date.day} de {month_es} 22:00\n"
        )
        out = _strip_stale_bullets(sample)
        assert "Fiesta local" in out, \
            f"Bullet ending today ({today_date.day} de {month_es}) must be kept"

    def test_bullet_ending_yesterday_is_dropped(self):
        yesterday = datetime.now(MADRID_TZ).date() - timedelta(days=1)
        months_es = [
            "enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
        ]
        month_es = months_es[yesterday.month - 1]
        sample = (
            "[GRANDES EVENTOS]\n"
            f"- **Evento pasado** hasta el {yesterday.day} de {month_es} 22:00\n"
        )
        out = _strip_stale_bullets(sample)
        assert "Evento pasado" not in out, \
            "Bullet whose end date is yesterday must be dropped"


# ═══════════════════════════════════════════════════════════════════════
# UNIT 5 — malformed input safety
# ═══════════════════════════════════════════════════════════════════════
class TestStripStaleBulletsMalformedInput:
    def test_empty_string(self):
        assert _strip_stale_bullets("") == ""

    def test_none_returns_none_gracefully(self):
        # Function returns text unchanged if falsy; must not raise
        assert _strip_stale_bullets(None) is None

    def test_single_line(self):
        assert _strip_stale_bullets("just one line") == "just one line"

    def test_only_headers_no_bullets(self):
        sample = "[GRANDES EVENTOS]\n[TEATROS Y OCIO]\n[ALERTAS DE TRÁFICO]"
        out = _strip_stale_bullets(sample)
        assert out == sample

    def test_only_bullets_no_headers(self):
        # No section header ever → inside_target stays False → nothing dropped
        sample = (
            "- Mad Cool (del 10 al 12 de julio)\n"
            "- Iberdrola (hasta el 5 de julio)\n"
        )
        out = _strip_stale_bullets(sample)
        assert "Mad Cool" in out
        assert "Iberdrola" in out


# ═══════════════════════════════════════════════════════════════════════
# INTEGRATION 1 — end-to-end _generate_summary applies the strip filter
# even when the verify pass is an IDENTITY (does not remove past events)
# ═══════════════════════════════════════════════════════════════════════
class TestGenerateSummaryAppliesStripFilter:
    def test_strip_filter_removes_mad_cool_and_iberdrola_when_verify_is_identity(self):
        slot = _cache_slot_madrid()
        iso = datetime.now(MADRID_TZ).isoformat()
        summary_with_stale = (
            "[METEO HOY]\n"
            "- 25°C\n\n"
            "[GRANDES EVENTOS]\n"
            "- **Mad Cool 2026** en IFEMA (del 10 al 12 de julio) 20:00\n"
            "- **Iberdrola Music** en Caja Mágica (hasta el 5 de julio) 21:30\n"
            "- **Veranos de la Villa** (del 7 de julio al 29 de agosto) 22:00\n\n"
            "[TEATROS Y OCIO]\n"
            "- Función flamenco 20:30\n\n"
            "[ALERTAS DE TRÁFICO]\n"
            "- Corte M-30\n\n"
            "[AEROPUERTO]\n"
            "- placeholder\n\n"
            "[PREVISIÓN MAÑANA]\n"
            "- 24-34°C\n"
        )
        fake_payload = {
            "summary": summary_with_stale,
            "sources": [],
            "search_queries": [],
            "date": TODAY,
            "cache_slot": slot,
            "generated_at": iso,
        }

        # Patch: primary gen returns the stale summary. Verify pass is IDENTITY
        # (mimics production behavior where verify pass leaks Mad Cool through).
        # _compute_airport_peaks is patched to be a no-op async returning empty.
        with patch.object(ds, "_generate_summary_sync",
                          return_value=fake_payload), \
             patch.object(ds, "_verify_events_sync",
                          side_effect=lambda text: text), \
             patch.object(ds, "_compute_airport_peaks",
                          new=MagicMock(return_value=_async_wrap(
                              {"morning": [], "evening": []}))):
            loop = asyncio.new_event_loop()
            try:
                payload = loop.run_until_complete(_generate_summary())
            finally:
                loop.close()

        final = payload["summary"]
        assert "Mad Cool" not in final, \
            "Mad Cool bullet must be stripped by _strip_stale_bullets"
        assert "Iberdrola Music" not in final, \
            "Iberdrola Music bullet must be stripped by _strip_stale_bullets"
        assert "Veranos de la Villa" in final, \
            "Ongoing event Veranos de la Villa must survive"


# ═══════════════════════════════════════════════════════════════════════
# INTEGRATION 2 — strip filter runs even when verify pass raises
# ═══════════════════════════════════════════════════════════════════════
class TestStripFilterRunsAfterVerifyRaises:
    def test_verify_pass_raises_but_strip_still_applied(self):
        slot = _cache_slot_madrid()
        iso = datetime.now(MADRID_TZ).isoformat()
        summary_with_stale = (
            "[METEO HOY]\n- 25°C\n\n"
            "[GRANDES EVENTOS]\n"
            "- **Mad Cool 2026** (del 10 al 12 de julio) 20:00\n"
            "- **Iberdrola Music** (hasta el 5 de julio) 21:30\n\n"
            "[TEATROS Y OCIO]\n- x\n\n"
            "[ALERTAS DE TRÁFICO]\n- y\n\n"
            "[AEROPUERTO]\n- z\n\n"
            "[PREVISIÓN MAÑANA]\n- w\n"
        )
        fake_payload = {
            "summary": summary_with_stale,
            "sources": [],
            "search_queries": [],
            "date": TODAY,
            "cache_slot": slot,
            "generated_at": iso,
        }

        with patch.object(ds, "_generate_summary_sync",
                          return_value=fake_payload), \
             patch.object(ds, "_verify_events_sync",
                          side_effect=Exception("boom")), \
             patch.object(ds, "_compute_airport_peaks",
                          new=MagicMock(return_value=_async_wrap(
                              {"morning": [], "evening": []}))):
            loop = asyncio.new_event_loop()
            try:
                payload = loop.run_until_complete(_generate_summary())
            finally:
                loop.close()

        final = payload["summary"]
        assert "Mad Cool" not in final, \
            "Strip filter should have stripped Mad Cool even though verify raised"
        assert "Iberdrola Music" not in final


# ═══════════════════════════════════════════════════════════════════════
# LIVE — force_refresh on the real endpoint
# ═══════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def api_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


_live_state: dict = {}


class TestLiveNoStaleBullets:
    def test_force_refresh_has_no_mad_cool_or_iberdrola_music(self, api_session):
        r = api_session.get(
            f"{BASE_URL}/api/events/daily-summary?force_refresh=true",
            timeout=180,
        )
        if r.status_code == 503:
            pytest.skip(f"Gemini 503 (quota/overload): {r.text[:200]}")
        assert r.status_code == 200, f"Unexpected {r.status_code}: {r.text[:400]}"
        data = r.json()
        summary = data.get("summary", "")
        _live_state["summary"] = summary
        low = summary.lower()

        # Zero "mad cool"
        assert "mad cool" not in low, \
            f"Mad Cool still present in live summary:\n{summary}"

        # Zero "iberdrola music" or "festival iberdrola" (sponsor names allowed
        # elsewhere, but the FESTIVAL must be gone)
        assert "iberdrola music" not in low, \
            f"'iberdrola music' still present in live summary:\n{summary}"
        assert "festival iberdrola" not in low, \
            f"'festival iberdrola' still present in live summary:\n{summary}"

        # Auditorio Miguel Ríos de Rivas — past-weekend event on a Monday
        assert "auditorio miguel ríos" not in low, \
            f"'auditorio miguel ríos' still present in live summary:\n{summary}"


def teardown_module(module):
    """Print the raw live summary for manual eyeball."""
    summary = _live_state.get("summary")
    if summary:
        print("\n" + "=" * 72)
        print("LIVE SUMMARY (force_refresh) — iter_16 strip-stale verification:")
        print("=" * 72)
        print(summary)
        print("=" * 72)
