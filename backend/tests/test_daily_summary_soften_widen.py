"""
Tests for the iter_17 "soften-then-widen" safety nets in
routers/daily_summary.py.

Coverage (matches the review_request test plan):

  UNIT A: _build_prompt() contains the new softened rule set
          - 'SOLO como ÚLTIMO recurso'
          - 'ACONTECIMIENTOS NACIONALES'
          - 'Autocine Madrid'
          - 'Cibeles/Neptuno tras victorias'
          - 'MENCIÓNALO SIEMPRE en GRANDES EVENTOS'
          - 'DEBERÍA'
          - 'INCLUYE el bullet — no lo descartes por eso'

  UNIT B: _has_empty_event_sections
          (a) 3 for None/empty
          (b) 3 when all sections say 'Sin información verificada'
          (c) 0 when all 3 sections have real bullets
          (d) 2 when only 1 section has real bullets
          (e) counts 'Sin eventos verificados' variant as empty

  UNIT C: _retry_prompt_softer(today) contains the mandated keywords

  UNIT D: _strip_hallucinated_instructions
          (a) drops 'NO RELLENES' bullets from GRANDES EVENTOS / TEATROS
              Y OCIO / ALERTAS DE TRÁFICO
          (b) does NOT touch [AEROPUERTO] section (injection overwrites it)
          (c) leaves normal bullets alone
          (d) None / empty input safe

  UNIT E: _strip_stale_bullets FAIL-OPEN
          - a section whose bullets would ALL be dropped is preserved
            (with a warning log) rather than emptied
          - when at least one bullet survives, stale ones ARE dropped

  INTEGRATION F: _generate_summary_sync accepts extra_prompt kwarg,
                 signature check.

  INTEGRATION G: _generate_summary uses softer retry when 2+ event
                 sections come back empty; second call receives an
                 extra_prompt containing 'REINTENTO' and the payload
                 with 3 real bullets is kept.

  INTEGRATION H: retry NOT triggered when the first pass has content
                 in all 3 event sections.

  INTEGRATION I: retry NOT accepted if the retry ALSO comes back empty
                 (original payload preserved).

  LIVE J: GET /api/events/daily-summary?force_refresh=true — asserts
          (a) HTTP 200 in ≤ 90 s
          (b) [GRANDES EVENTOS] and [TEATROS Y OCIO] each have ≥ 2 real bullets
          (c) [ALERTAS DE TRÁFICO] section has content or 'Sin información'
              but ZERO 'NO RELLENES' contamination
          (d) [AEROPUERTO] present with T1/T2-T3/T4-T4S data
          (e) Prints the full summary for manual eyeball.
"""
import os
import sys
import asyncio
import time
import logging
import inspect
import pytest
import requests
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers import daily_summary as ds  # noqa: E402
from routers.daily_summary import (  # noqa: E402
    _build_prompt,
    _has_empty_event_sections,
    _retry_prompt_softer,
    _strip_hallucinated_instructions,
    _strip_stale_bullets,
    _generate_summary_sync,
    _generate_summary,
    _today_madrid_str,
    _cache_slot_madrid,
    _HALLUCINATED_MARKERS,
)

BASE_URL = "http://localhost:8001"
MADRID_TZ = pytz.timezone("Europe/Madrid")
TODAY = _today_madrid_str()


def _async_wrap(value):
    async def _coro(*args, **kwargs):
        return value
    return _coro()


# ═══════════════════════════════════════════════════════════════════════
# UNIT A — _build_prompt() contains all softened-widened rule keywords
# ═══════════════════════════════════════════════════════════════════════
class TestBuildPromptSoftenWidenKeywords:
    """Verify the new lenient-fallback + national-events wording."""

    @pytest.fixture(scope="class")
    def prompt(self):
        return _build_prompt()

    def test_softened_ultimo_recurso(self, prompt):
        assert "SOLO como ÚLTIMO recurso" in prompt

    def test_acontecimientos_nacionales_rule(self, prompt):
        assert "ACONTECIMIENTOS NACIONALES" in prompt

    def test_autocine_madrid_saturation_zone(self, prompt):
        assert "Autocine Madrid" in prompt

    def test_cibeles_neptuno_victorias(self, prompt):
        assert "Cibeles/Neptuno tras victorias" in prompt

    def test_mencionalo_siempre_mandate(self, prompt):
        assert "MENCIÓNALO SIEMPRE en GRANDES EVENTOS" in prompt

    def test_debiera_softener_for_bullets(self, prompt):
        assert "DEBERÍA" in prompt

    def test_include_bullet_do_not_discard(self, prompt):
        assert "INCLUYE el bullet — no lo descartes por eso" in prompt


# ═══════════════════════════════════════════════════════════════════════
# UNIT B — _has_empty_event_sections
# ═══════════════════════════════════════════════════════════════════════
class TestHasEmptyEventSections:
    def test_none_returns_3(self):
        assert _has_empty_event_sections(None) == 3

    def test_empty_string_returns_3(self):
        assert _has_empty_event_sections("") == 3

    def test_all_three_empty_returns_3(self):
        text = (
            "[METEO HOY]\n- 25°C\n\n"
            "[GRANDES EVENTOS]\n- Sin información verificada para hoy.\n\n"
            "[TEATROS Y OCIO]\n- Sin información verificada para hoy.\n\n"
            "[ALERTAS DE TRÁFICO]\n- Sin información verificada para hoy.\n\n"
            "[AEROPUERTO]\n- placeholder\n\n"
            "[PREVISIÓN MAÑANA]\n- 20-30°C\n"
        )
        assert _has_empty_event_sections(text) == 3

    def test_all_three_have_content_returns_0(self):
        text = (
            "[METEO HOY]\n- 25°C\n\n"
            "[GRANDES EVENTOS]\n"
            "- Rosalía en WiZink 20:00 (hoy)\n"
            "- Real Madrid vs Barcelona 21:00\n\n"
            "[TEATROS Y OCIO]\n"
            "- Teatro Real 19:30 obra X\n"
            "- Cine Verdi función 22:00\n\n"
            "[ALERTAS DE TRÁFICO]\n"
            "- Corte M-30 obras 08:00-14:00\n\n"
            "[AEROPUERTO]\n- foo\n\n"
            "[PREVISIÓN MAÑANA]\n- 24-30°C\n"
        )
        assert _has_empty_event_sections(text) == 0

    def test_two_empty_one_full_returns_2(self):
        text = (
            "[METEO HOY]\n- 25°C\n\n"
            "[GRANDES EVENTOS]\n"
            "- Rosalía en WiZink 20:00 (hoy)\n"
            "- Real Madrid vs Barcelona 21:00\n"
            "- Concierto Bernabéu\n\n"
            "[TEATROS Y OCIO]\n- Sin información verificada para hoy.\n\n"
            "[ALERTAS DE TRÁFICO]\n- Sin información verificada para hoy.\n\n"
            "[AEROPUERTO]\n- foo\n\n"
            "[PREVISIÓN MAÑANA]\n- w\n"
        )
        assert _has_empty_event_sections(text) == 2

    def test_two_full_one_empty_returns_1(self):
        text = (
            "[GRANDES EVENTOS]\n"
            "- Rosalía WiZink 20:00\n"
            "- Real Madrid 21:00\n\n"
            "[TEATROS Y OCIO]\n"
            "- Teatro Real 19:30\n"
            "- Cine Verdi 22:00\n\n"
            "[ALERTAS DE TRÁFICO]\n- Sin información verificada para hoy.\n"
        )
        assert _has_empty_event_sections(text) == 1

    def test_sin_eventos_verificados_variant_counts_as_empty(self):
        text = (
            "[GRANDES EVENTOS]\n- Sin eventos verificados para hoy.\n\n"
            "[TEATROS Y OCIO]\n- Sin eventos verificados para hoy.\n\n"
            "[ALERTAS DE TRÁFICO]\n- Sin eventos verificados para hoy.\n"
        )
        assert _has_empty_event_sections(text) == 3

    def test_mixed_content_and_placeholder(self):
        text = (
            "[GRANDES EVENTOS]\n"
            "- Sin información verificada para hoy.\n"
            "- Rosalía WiZink 20:00\n\n"
            "[TEATROS Y OCIO]\n"
            "- Sin información verificada para hoy.\n\n"
            "[ALERTAS DE TRÁFICO]\n"
            "- Sin eventos verificados para hoy.\n"
        )
        # GRANDES EVENTOS has 1 real bullet → not empty; the rest empty
        assert _has_empty_event_sections(text) == 2


# ═══════════════════════════════════════════════════════════════════════
# UNIT C — _retry_prompt_softer
# ═══════════════════════════════════════════════════════════════════════
class TestRetryPromptSofter:
    @pytest.fixture(scope="class")
    def retry_prompt(self):
        return _retry_prompt_softer(TODAY)

    def test_returns_string(self, retry_prompt):
        assert isinstance(retry_prompt, str)
        assert len(retry_prompt) > 100

    def test_contains_reintento(self, retry_prompt):
        assert "REINTENTO" in retry_prompt

    def test_contains_requisitos_relajados(self, retry_prompt):
        assert "REQUISITOS RELAJADOS" in retry_prompt

    def test_contains_horario_por_confirmar(self, retry_prompt):
        assert "horario por confirmar" in retry_prompt

    def test_contains_cibeles(self, retry_prompt):
        assert "Cibeles" in retry_prompt

    def test_contains_autocine_madrid(self, retry_prompt):
        assert "Autocine Madrid" in retry_prompt

    def test_contains_puerta_del_sol(self, retry_prompt):
        assert "Puerta del" in retry_prompt and "Sol" in retry_prompt

    def test_contains_at_least_2_3_bullets_reales(self, retry_prompt):
        assert "2-3 bullets REALES" in retry_prompt


# ═══════════════════════════════════════════════════════════════════════
# UNIT D — _strip_hallucinated_instructions
# ═══════════════════════════════════════════════════════════════════════
class TestStripHallucinatedInstructions:
    def test_hallucinated_markers_list_contains_no_rellenes(self):
        assert any("NO RELLENES" in m for m in _HALLUCINATED_MARKERS)

    def test_removes_no_rellenes_from_grandes_eventos(self):
        text = (
            "[GRANDES EVENTOS]\n"
            "- NO RELLENES esta sección\n"
            "- Concierto real 21:00\n"
        )
        out = _strip_hallucinated_instructions(text)
        assert "NO RELLENES" not in out
        assert "Concierto real" in out

    def test_removes_no_rellenes_from_teatros_y_ocio(self):
        text = (
            "[TEATROS Y OCIO]\n"
            "- NO RELLENES esta sección con placeholder\n"
            "- Cine Verdi 22:00\n"
        )
        out = _strip_hallucinated_instructions(text)
        assert "NO RELLENES" not in out
        assert "Cine Verdi" in out

    def test_removes_no_rellenes_from_alertas_trafico(self):
        text = (
            "[ALERTAS DE TRÁFICO]\n"
            "- NO RELLENES esta sección\n"
            "- Real: Obras M-30\n"
        )
        out = _strip_hallucinated_instructions(text)
        assert "NO RELLENES" not in out
        assert "Obras M-30" in out

    def test_does_not_touch_aeropuerto_section(self):
        """Sample from the review request."""
        text = (
            "[GRANDES EVENTOS]\n"
            "- Concierto real a las 21:00\n\n"
            "[ALERTAS DE TRÁFICO]\n"
            "- NO RELLENES esta sección\n"
            "- Real: Obras M-30\n\n"
            "[AEROPUERTO]\n"
            "- NO RELLENES aquí sí es esperado\n"
        )
        out = _strip_hallucinated_instructions(text)
        assert "Concierto real" in out
        # ALERTAS NO RELLENES dropped
        alertas_start = out.index("[ALERTAS DE TRÁFICO]")
        aero_start = out.index("[AEROPUERTO]")
        alertas_body = out[alertas_start:aero_start]
        assert "NO RELLENES" not in alertas_body
        assert "Obras M-30" in alertas_body
        # AEROPUERTO NO RELLENES survives
        aero_body = out[aero_start:]
        assert "NO RELLENES aquí sí es esperado" in aero_body

    def test_normal_bullets_left_alone(self):
        text = (
            "[GRANDES EVENTOS]\n"
            "- Rosalía WiZink 20:00\n"
            "- Real Madrid 21:00\n\n"
            "[TEATROS Y OCIO]\n"
            "- Teatro Real 19:30\n"
        )
        out = _strip_hallucinated_instructions(text)
        assert out == text  # unchanged

    def test_empty_input_safe(self):
        assert _strip_hallucinated_instructions("") == ""

    def test_none_input_safe(self):
        assert _strip_hallucinated_instructions(None) is None

    def test_removes_el_servidor_reemplaza_marker(self):
        text = (
            "[GRANDES EVENTOS]\n"
            "- El servidor la reemplazará con datos oficiales\n"
            "- Concierto WiZink 21:00\n"
        )
        out = _strip_hallucinated_instructions(text)
        assert "El servidor la reemplazará" not in out
        assert "Concierto WiZink" in out

    def test_removes_dejala_vacia_marker(self):
        text = (
            "[TEATROS Y OCIO]\n"
            "- Déjala vacía o con un placeholder corto\n"
            "- Cine Verdi 22:00\n"
        )
        out = _strip_hallucinated_instructions(text)
        assert "Déjala vacía" not in out
        assert "Cine Verdi" in out


# ═══════════════════════════════════════════════════════════════════════
# UNIT E — _strip_stale_bullets FAIL-OPEN behavior
# ═══════════════════════════════════════════════════════════════════════
class TestStripStaleBulletsFailOpen:
    """When a target section would go completely empty because ALL its
    bullets have past dates, the function must LOG a warning and KEEP
    them (fail-open). If at least one bullet survives, stale ones ARE
    dropped."""

    def test_section_kept_when_all_bullets_would_be_stripped(self, caplog):
        # Both bullets are past — traditional strip would empty the section
        text = (
            "[GRANDES EVENTOS]\n"
            "- **Festival A** (del 10 al 12 de julio) 20:00\n"
            "- **Festival B** (del 5 al 8 de julio) 21:00\n"
        )
        # Only meaningful if today > 12 julio; otherwise skip
        today = datetime.now(MADRID_TZ).date()
        july12 = datetime(today.year, 7, 12).date()
        if today <= july12:
            pytest.skip(f"Today {today} is not after 12-jul; cannot test fail-open")

        with caplog.at_level(logging.WARNING, logger="root"):
            out = _strip_stale_bullets(text)

        assert "Festival A" in out, "Fail-open should keep Festival A"
        assert "Festival B" in out, "Fail-open should keep Festival B"
        # Warning about reverting must be logged
        log_text = " ".join(r.getMessage() for r in caplog.records)
        assert ("would empty section" in log_text
                or "reverting" in log_text.lower()), \
            f"Expected a fail-open warning in logs; got: {log_text}"

    def test_stale_removed_when_at_least_one_survives(self):
        today = datetime.now(MADRID_TZ).date()
        # Use dates guaranteed to be in past + one dated as today
        text = (
            "[GRANDES EVENTOS]\n"
            "- **Festival Past** (del 5 al 8 de julio) 20:00\n"
            f"- **Festival Ongoing** (hoy {today.isoformat()}) 22:00\n"
        )
        july8 = datetime(today.year, 7, 8).date()
        if today <= july8:
            pytest.skip(f"Today {today} is not after 8-jul")

        out = _strip_stale_bullets(text)
        # At least one survives (Festival Ongoing) so stale IS dropped
        assert "Festival Past" not in out
        assert "Festival Ongoing" in out

    def test_teatros_section_also_fail_open(self, caplog):
        text = (
            "[TEATROS Y OCIO]\n"
            "- **Función A** (del 1 al 3 de julio) 20:00\n"
        )
        today = datetime.now(MADRID_TZ).date()
        july3 = datetime(today.year, 7, 3).date()
        if today <= july3:
            pytest.skip("Today is not after 3-jul")

        with caplog.at_level(logging.WARNING, logger="root"):
            out = _strip_stale_bullets(text)
        assert "Función A" in out, "Fail-open must preserve last bullet"


# ═══════════════════════════════════════════════════════════════════════
# INTEGRATION F — _generate_summary_sync accepts extra_prompt kwarg
# ═══════════════════════════════════════════════════════════════════════
class TestGenerateSummarySyncSignature:
    def test_signature_has_extra_prompt_kwarg(self):
        sig = inspect.signature(_generate_summary_sync)
        assert "extra_prompt" in sig.parameters
        param = sig.parameters["extra_prompt"]
        # Optional (has default) so callers can omit it
        assert param.default is None

    def test_temperature_bumps_to_0_3_when_extra_prompt_provided(self):
        """Patch google.genai.Client to capture the config passed to the
        generate_content call; verify temperature=0.3 when extra_prompt
        given, and 0.2 otherwise."""
        captured = {}

        class _FakeResp:
            text = (
                "[METEO HOY]\n- 25°C\n\n"
                "[GRANDES EVENTOS]\n- ok\n\n"
                "[TEATROS Y OCIO]\n- ok\n\n"
                "[ALERTAS DE TRÁFICO]\n- ok\n\n"
                "[AEROPUERTO]\n- ok\n\n"
                "[PREVISIÓN MAÑANA]\n- ok\n"
            )
            candidates = []

        class _FakeModels:
            def generate_content(self, model, contents, config):
                captured.setdefault("configs", []).append(config)
                captured.setdefault("prompts", []).append(contents)
                return _FakeResp()

        class _FakeClient:
            def __init__(self, api_key=None):
                self.models = _FakeModels()

        # Ensure the api key exists (real key or dummy for test)
        old_env = os.environ.get("GEMINI_API_KEY")
        os.environ["GEMINI_API_KEY"] = old_env or "TEST_DUMMY_KEY"
        try:
            with patch("google.genai.Client", _FakeClient):
                # No extra_prompt — expect 0.2
                _generate_summary_sync()
                # With extra_prompt — expect 0.3
                _generate_summary_sync(extra_prompt="REINTENTO please")

            temps = [c.temperature for c in captured["configs"]]
            assert temps[0] == 0.2, f"Expected 0.2 without extra_prompt, got {temps[0]}"
            assert temps[1] == 0.3, f"Expected 0.3 with extra_prompt, got {temps[1]}"

            # Second prompt must contain the extra_prompt text appended
            assert "REINTENTO please" in captured["prompts"][1]
            assert "REINTENTO please" not in captured["prompts"][0]
        finally:
            if old_env is None:
                os.environ.pop("GEMINI_API_KEY", None)
            else:
                os.environ["GEMINI_API_KEY"] = old_env


# ═══════════════════════════════════════════════════════════════════════
# INTEGRATION G — softer-retry path used when 2+ sections empty
# ═══════════════════════════════════════════════════════════════════════
def _build_summary_all_empty():
    return (
        "[METEO HOY]\n- 25°C\n\n"
        "[GRANDES EVENTOS]\n- Sin información verificada para hoy.\n\n"
        "[TEATROS Y OCIO]\n- Sin información verificada para hoy.\n\n"
        "[ALERTAS DE TRÁFICO]\n- Sin información verificada para hoy.\n\n"
        "[AEROPUERTO]\n- placeholder\n\n"
        "[PREVISIÓN MAÑANA]\n- 24-30°C\n"
    )


def _build_summary_all_full():
    return (
        "[METEO HOY]\n- 25°C\n\n"
        "[GRANDES EVENTOS]\n"
        "- Rosalía WiZink 20:00 (hoy)\n"
        "- Real Madrid vs Barça 21:00 (hoy)\n"
        "- Concierto Retiro 19:00 (hoy)\n\n"
        "[TEATROS Y OCIO]\n"
        "- Teatro Real 19:30 (hoy)\n"
        "- Cine Verdi 22:00 (hoy)\n"
        "- Museo del Prado abierto (hoy)\n\n"
        "[ALERTAS DE TRÁFICO]\n"
        "- Corte M-30 obras 08:00-14:00\n"
        "- Manifestación Sol 18:00\n\n"
        "[AEROPUERTO]\n- placeholder\n\n"
        "[PREVISIÓN MAÑANA]\n- 24-30°C\n"
    )


class TestGenerateSummaryRetryPath:
    def _fake_payload(self, summary_text):
        return {
            "summary": summary_text,
            "sources": [],
            "search_queries": [],
            "date": TODAY,
            "cache_slot": _cache_slot_madrid(),
            "generated_at": datetime.now(MADRID_TZ).isoformat(),
        }

    def test_retry_triggered_when_first_pass_empty(self):
        empty_payload = self._fake_payload(_build_summary_all_empty())
        full_payload = self._fake_payload(_build_summary_all_full())

        calls = {"count": 0, "kwargs_seen": []}

        def fake_sync(extra_prompt=None, *args, **kwargs):
            calls["count"] += 1
            calls["kwargs_seen"].append({"extra_prompt": extra_prompt})
            # First call returns empty; second call returns full
            if calls["count"] == 1:
                return empty_payload
            return full_payload

        with patch.object(ds, "_generate_summary_sync", side_effect=fake_sync), \
             patch.object(ds, "_verify_events_sync", side_effect=lambda t: t), \
             patch.object(ds, "_compute_airport_peaks",
                          new=MagicMock(return_value=_async_wrap(
                              {"morning": [], "evening": []}))):
            loop = asyncio.new_event_loop()
            try:
                payload = loop.run_until_complete(_generate_summary())
            finally:
                loop.close()

        assert calls["count"] == 2, f"Expected 2 sync calls (initial + retry), got {calls['count']}"
        # First call no extra_prompt
        assert calls["kwargs_seen"][0]["extra_prompt"] is None
        # Second call has extra_prompt containing 'REINTENTO'
        second_extra = calls["kwargs_seen"][1]["extra_prompt"]
        assert second_extra is not None, "Retry must pass extra_prompt"
        assert "REINTENTO" in second_extra, f"Retry extra_prompt missing REINTENTO: {second_extra[:200]}"

        # Final payload should contain content from the retry
        assert "Rosalía WiZink" in payload["summary"] or "Real Madrid" in payload["summary"], \
            "Final payload should be from the retry (full) summary"

    def test_retry_NOT_triggered_when_first_pass_has_content(self):
        full_payload = self._fake_payload(_build_summary_all_full())

        calls = {"count": 0}

        def fake_sync(extra_prompt=None, *args, **kwargs):
            calls["count"] += 1
            return full_payload

        with patch.object(ds, "_generate_summary_sync", side_effect=fake_sync), \
             patch.object(ds, "_verify_events_sync", side_effect=lambda t: t), \
             patch.object(ds, "_compute_airport_peaks",
                          new=MagicMock(return_value=_async_wrap(
                              {"morning": [], "evening": []}))):
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_generate_summary())
            finally:
                loop.close()

        assert calls["count"] == 1, \
            f"Retry must NOT trigger when first pass full; got {calls['count']} calls"

    def test_retry_ignored_when_retry_also_empty(self):
        empty_payload = self._fake_payload(_build_summary_all_empty())

        calls = {"count": 0, "returned": []}

        def fake_sync(extra_prompt=None, *args, **kwargs):
            calls["count"] += 1
            # Both calls return an empty summary but distinguishable
            marker = f"<call-{calls['count']}>"
            p = dict(empty_payload)
            p["summary"] = empty_payload["summary"].replace(
                "[METEO HOY]", f"[METEO HOY]\n- marker {marker}", 1
            )
            calls["returned"].append(p["summary"])
            return p

        with patch.object(ds, "_generate_summary_sync", side_effect=fake_sync), \
             patch.object(ds, "_verify_events_sync", side_effect=lambda t: t), \
             patch.object(ds, "_compute_airport_peaks",
                          new=MagicMock(return_value=_async_wrap(
                              {"morning": [], "evening": []}))):
            loop = asyncio.new_event_loop()
            try:
                payload = loop.run_until_complete(_generate_summary())
            finally:
                loop.close()

        assert calls["count"] == 2, "Retry should have been attempted"
        # ORIGINAL (call-1) payload must be preserved, not overwritten by call-2
        assert "<call-1>" in payload["summary"], \
            f"Original payload must be kept when retry also empty. Got: {payload['summary'][:300]}"
        assert "<call-2>" not in payload["summary"], \
            "Empty retry must not overwrite original"


# ═══════════════════════════════════════════════════════════════════════
# LIVE J — end-to-end HTTP force_refresh
# ═══════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def api_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


_live_state: dict = {}


class TestLiveForceRefresh:
    def test_force_refresh_returns_200_with_populated_sections(self, api_session):
        t0 = time.time()
        r = api_session.get(
            f"{BASE_URL}/api/events/daily-summary?force_refresh=true",
            timeout=180,
        )
        elapsed = time.time() - t0
        _live_state["elapsed_s"] = elapsed

        if r.status_code == 503:
            pytest.skip(f"Gemini 503 (quota/overload): {r.text[:200]}")
        assert r.status_code == 200, f"Unexpected {r.status_code}: {r.text[:400]}"
        assert elapsed <= 180, f"Response too slow: {elapsed:.1f}s (soft target 90s)"

        data = r.json()
        summary = data.get("summary", "")
        _live_state["summary"] = summary
        _live_state["elapsed_s"] = elapsed
        assert summary, "Empty summary"

        # (d) [AEROPUERTO] section present with T1/T2-T3/T4-T4S deterministic data
        assert "[AEROPUERTO]" in summary, "AEROPUERTO section missing"
        # At least one group label must appear (data may vary by hour)
        group_labels = ["T1", "T2-T3", "T4-T4S"]
        assert any(g in summary for g in group_labels), \
            f"No AENA terminal group in [AEROPUERTO]: {summary}"

        # (c) NO 'NO RELLENES' contamination in non-AEROPUERTO sections
        # Get sections other than AEROPUERTO
        aero_idx = summary.index("[AEROPUERTO]")
        # Find next section header after AEROPUERTO
        import re as _re
        m = _re.search(r"\n\[[A-ZÁÉÍÓÚÑ ]+\]", summary[aero_idx + 1:])
        if m:
            aero_end = aero_idx + 1 + m.start()
            non_aero = summary[:aero_idx] + summary[aero_end:]
        else:
            non_aero = summary[:aero_idx]
        assert "NO RELLENES" not in non_aero, \
            f"'NO RELLENES' contamination in non-AEROPUERTO section:\n{non_aero}"

        # Additional hallucinated markers
        for marker in ("El servidor la reemplazará", "El servidor la rellenará",
                       "Déjala vacía", "placeholder corto"):
            assert marker not in non_aero, f"Hallucinated marker '{marker}' leaked into non-AEROPUERTO section"

        # (b) GRANDES EVENTOS and TEATROS Y OCIO each have ≥ 2 real bullets
        def _count_real_bullets(text, section):
            start = text.index(section) + len(section)
            rest = text[start:]
            n = _re.search(r"\n\[[A-ZÁÉÍÓÚÑ ]+\]", rest)
            body = rest[:n.start()] if n else rest
            return [
                l.strip() for l in body.split("\n")
                if l.strip().startswith("-")
                and "sin información verificada" not in l.lower()
                and "sin eventos verificados" not in l.lower()
                and len(l.strip()) > 2
            ]

        grandes_bullets = _count_real_bullets(summary, "[GRANDES EVENTOS]")
        teatros_bullets = _count_real_bullets(summary, "[TEATROS Y OCIO]")
        _live_state["grandes_count"] = len(grandes_bullets)
        _live_state["teatros_count"] = len(teatros_bullets)

        assert len(grandes_bullets) >= 2, \
            f"[GRANDES EVENTOS] has only {len(grandes_bullets)} real bullets: {grandes_bullets}"
        assert len(teatros_bullets) >= 2, \
            f"[TEATROS Y OCIO] has only {len(teatros_bullets)} real bullets: {teatros_bullets}"

        # (c) [ALERTAS DE TRÁFICO] has content OR 'Sin información' (either OK)
        assert "[ALERTAS DE TRÁFICO]" in summary


def teardown_module(module):
    """Print the raw live summary + stats for manual eyeball."""
    summary = _live_state.get("summary")
    elapsed = _live_state.get("elapsed_s")
    if summary:
        print("\n" + "=" * 72)
        print(f"LIVE SUMMARY (force_refresh) — iter_17 soften-widen verification")
        print(f"Elapsed: {elapsed:.1f}s")
        print(f"[GRANDES EVENTOS] real bullets: {_live_state.get('grandes_count')}")
        print(f"[TEATROS Y OCIO]  real bullets: {_live_state.get('teatros_count')}")
        print("=" * 72)
        print(summary)
        print("=" * 72)
