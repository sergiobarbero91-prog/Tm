"""
Tests for the DATE-verification bug fix (iteration_15).

The previous iter_14 fix improved HOUR-based staleness filtering but MISSED
DATE-based staleness of multi-day events (e.g. Mad Cool Festival which ended
before yesterday still appearing in the summary).

Verifies:
  1. _build_prompt() now emits the REGLA #0 block with 4-step FECHA_INICIO/
     FECHA_FIN verification checklist and explicit anti-examples for
     Mad Cool + Auditorio Miguel Ríos de Rivas.
  2. _verify_events_sync exists, is callable, and returns a non-empty string
     (doesn't crash even if Gemini is unavailable — safety path preserves
     original text).
  3. _generate_summary awaits _verify_events_sync exactly once with the
     initial summary text (mocked via unittest.mock).
  4. temperature was lowered to 0.2 (main gen) and 0.1 (verify pass).
  5. Cache slot behaviour: stale slot doc is NOT returned by _load_cached.
  6. LIVE: /api/events/daily-summary?force_refresh=true returns a summary
     with all mandatory sections and (best-effort) does NOT mention
     Mad Cool if today > 2026-07-12.
  7. LIVE: 2nd call (no force_refresh) returns the cached slot version
     (same generated_at).
  8. LIVE: /api/events/daily-summary-public returns 200 with matching data.
"""
import os
import re
import sys
import asyncio
import pytest
import requests
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers import daily_summary as ds  # noqa: E402
from routers.daily_summary import (  # noqa: E402
    _build_prompt,
    _cache_slot_madrid,
    _load_cached,
    _today_madrid_str,
    _verify_events_sync,
    _generate_summary,
)
from shared import daily_summaries_collection  # noqa: E402

BASE_URL = "http://localhost:8001"
MADRID_TZ = pytz.timezone("Europe/Madrid")


# --------------------------------------------------------------------- #
# 1. Prompt now includes REGLA #0 with date-verification keywords       #
# --------------------------------------------------------------------- #
class TestBuildPromptDateVerification:
    REQUIRED_KEYWORDS = [
        "REGLA #0",
        "VERIFICACIÓN DE FECHA",
        "Paso 1",
        "Paso 2",
        "Paso 3",
        "Paso 4",
        "FECHA INICIO",
        "FECHA FIN",
        "Mad Cool",
        "Auditorio",
        "DESCARTA",
        "PROHIBIDO",
        "AYER",
        "MAÑANA",
    ]

    def test_all_required_keywords_present(self):
        p = _build_prompt()
        missing = [kw for kw in self.REQUIRED_KEYWORDS if kw not in p]
        assert not missing, f"Prompt is missing required keywords: {missing}"

    def test_today_iso_date_appears_at_least_twice(self):
        today = _today_madrid_str()
        p = _build_prompt()
        count = p.count(today)
        assert count >= 2, (
            f"Today's ISO date '{today}' must appear >=2 times in prompt "
            f"(found {count})"
        )


# --------------------------------------------------------------------- #
# 2. _verify_events_sync exists, is callable, safe                      #
# --------------------------------------------------------------------- #
class TestVerifyEventsSyncExists:
    def test_is_callable(self):
        assert callable(_verify_events_sync)

    def test_returns_string_and_doesnt_crash_on_mad_cool_bullet(self):
        """Called with a summary mentioning Mad Cool. If Gemini quota is
        exhausted the function must return the original text unchanged
        (safety) — never crash, never return empty."""
        today = _today_madrid_str()
        sample = (
            "[METEO HOY]\n- Temperatura 25°C\n\n"
            "[GRANDES EVENTOS]\n- Mad Cool Festival en IFEMA\n\n"
            "[TEATROS Y OCIO]\n- Sin información\n\n"
            "[ALERTAS DE TRÁFICO]\n- Sin información\n\n"
            "[AEROPUERTO]\n- Sin información\n\n"
            f"[PREVISIÓN MAÑANA]\n- {today}\n"
        )
        out = _verify_events_sync(sample)
        assert isinstance(out, str), "Must return a string"
        assert len(out) > 0, "Must return non-empty string"


# --------------------------------------------------------------------- #
# 3. _generate_summary calls verify pass exactly once with the initial  #
#    summary and uses the returned text                                 #
# --------------------------------------------------------------------- #
class TestGenerateSummaryCallsVerify:
    def test_verify_called_once_with_initial_summary(self):
        today = _today_madrid_str()
        slot = _cache_slot_madrid()
        iso = datetime.now(MADRID_TZ).isoformat()

        initial_summary = (
            "[GRANDES EVENTOS]\n- Mad Cool test\n\n"
            "[METEO HOY]\n- 25°C\n\n"
            "[TEATROS Y OCIO]\n-\n\n"
            "[ALERTAS DE TRÁFICO]\n-\n\n"
            "[AEROPUERTO]\n-\n\n"
            "[PREVISIÓN MAÑANA]\n-"
        )
        modified_summary = (
            "[GRANDES EVENTOS]\n- Sin eventos verificados para hoy.\n\n"
            "[METEO HOY]\n- 25°C\n\n"
            "[TEATROS Y OCIO]\n-\n\n"
            "[ALERTAS DE TRÁFICO]\n-\n\n"
            "[AEROPUERTO]\n-\n\n"
            "[PREVISIÓN MAÑANA]\n-"
        )

        fake_gen_payload = {
            "summary": initial_summary,
            "sources": [],
            "search_queries": [],
            "date": today,
            "cache_slot": slot,
            "generated_at": iso,
        }

        with patch.object(ds, "_generate_summary_sync",
                          return_value=fake_gen_payload) as mock_gen, \
             patch.object(ds, "_verify_events_sync",
                          return_value=modified_summary) as mock_verify, \
             patch.object(ds, "_compute_airport_peaks",
                          new=MagicMock(return_value=_async_wrap({"morning": [], "evening": []}))):
            payload = asyncio.get_event_loop().run_until_complete(
                _generate_summary()
            )

        assert mock_gen.call_count == 1
        assert mock_verify.call_count == 1, (
            f"_verify_events_sync must be called exactly once, "
            f"was called {mock_verify.call_count}"
        )
        # It must have been called with the INITIAL summary text
        called_arg = mock_verify.call_args[0][0]
        assert called_arg == initial_summary, (
            "_verify_events_sync was not called with the initial summary text"
        )
        # And the returned payload must reflect the modified summary
        # (airport section is injected afterwards, but the [GRANDES EVENTOS]
        #  line must come from the verified/modified text).
        assert "Sin eventos verificados para hoy." in payload["summary"], (
            "_generate_summary did not use the verified/modified summary"
        )
        assert "Mad Cool test" not in payload["summary"], (
            "_generate_summary kept the pre-verify Mad Cool bullet"
        )


def _async_wrap(value):
    """Helper: wrap a value in an awaitable coroutine for patching async funcs."""
    async def _coro(*args, **kwargs):
        return value
    return _coro()


# --------------------------------------------------------------------- #
# 4. Temperature was lowered                                            #
# --------------------------------------------------------------------- #
class TestTemperatureLowered:
    def test_main_generation_temperature_is_0_2(self):
        path = os.path.join(os.path.dirname(ds.__file__), "daily_summary.py")
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        # Find _generate_summary_sync block
        gen_start = src.index("def _generate_summary_sync")
        gen_end = src.index("def _verify_events_sync")
        gen_block = src[gen_start:gen_end]
        assert "temperature=0.2" in gen_block, (
            "Main generation temperature is not 0.2"
        )

    def test_verify_pass_temperature_is_0_1(self):
        path = os.path.join(os.path.dirname(ds.__file__), "daily_summary.py")
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        v_start = src.index("def _verify_events_sync")
        # Search until the next top-level def
        rest = src[v_start:]
        # slice up to next "\nasync def " or "\ndef "
        next_def = min(
            (rest.find("\nasync def ", 1) if rest.find("\nasync def ", 1) != -1 else len(rest)),
            (rest.find("\ndef ", 1) if rest.find("\ndef ", 1) != -1 else len(rest)),
        )
        v_block = rest[:next_def]
        assert "temperature=0.1" in v_block, (
            "Verify pass temperature is not 0.1"
        )


# --------------------------------------------------------------------- #
# 5. Cache slot: stale doc must NOT be returned                         #
# --------------------------------------------------------------------- #
class TestCacheStaleSlotIgnored:
    def test_stale_slot_returns_none_or_non_stale(self):
        async def _run():
            # Clean any existing STALE marker
            await daily_summaries_collection.delete_many(
                {"summary": "TEST_MARKER_iter15_stale"}
            )
            await daily_summaries_collection.insert_one({
                "summary": "TEST_MARKER_iter15_stale",
                "cache_slot": "STALE-SLOT",
                "date": _today_madrid_str(),
                "generated_at": datetime.now(MADRID_TZ).isoformat(),
                "sources": [],
                "search_queries": [],
            })
            loaded = await _load_cached()
            if loaded is not None:
                assert loaded.get("summary") != "TEST_MARKER_iter15_stale", (
                    "_load_cached returned a doc with cache_slot='STALE-SLOT'"
                )
            await daily_summaries_collection.delete_many(
                {"summary": "TEST_MARKER_iter15_stale"}
            )
        asyncio.get_event_loop().run_until_complete(_run())


# --------------------------------------------------------------------- #
# LIVE ENDPOINT TESTS                                                   #
# --------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def api_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_headers(api_session):
    r = api_session.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": "admin", "password": "admin"},
        timeout=15,
    )
    if r.status_code != 200:
        return {}
    tok = r.json().get("access_token")
    return {"Authorization": f"Bearer {tok}"} if tok else {}


# Shared holder so the raw summary flows across tests for reporting
_raw_state: dict = {}


class TestLiveForceRefresh:
    REQUIRED_SECTIONS = [
        "[METEO HOY]",
        "[GRANDES EVENTOS]",
        "[TEATROS Y OCIO]",
        "[ALERTAS DE TRÁFICO]",
        "[AEROPUERTO]",
        "[PREVISIÓN MAÑANA]",
    ]

    def test_force_refresh_returns_200_and_all_sections(self, api_session, admin_headers):
        r = api_session.get(
            f"{BASE_URL}/api/events/daily-summary?force_refresh=true",
            headers=admin_headers,
            timeout=180,
        )
        if r.status_code == 503:
            pytest.skip(
                f"Gemini 503 (quota or overload): {r.text[:200]} — "
                "code-path still exercised."
            )
        assert r.status_code == 200, f"Unexpected {r.status_code}: {r.text[:300]}"
        data = r.json()
        _raw_state["force_refresh_json"] = data
        _raw_state["force_refresh_summary"] = data.get("summary", "")
        missing = [s for s in self.REQUIRED_SECTIONS if s not in data.get("summary", "")]
        assert not missing, f"Missing sections in summary: {missing}"

    def test_no_known_past_events_in_result(self, api_session, admin_headers):
        """Common-sense date verification: Mad Cool 2026 was 10-12 Jul 2026.
        If today > 2026-07-12, Mad Cool must NOT appear in the summary."""
        summary = _raw_state.get("force_refresh_summary")
        if not summary:
            pytest.skip("no summary available (previous test skipped)")

        today = _today_madrid_str()
        # Extract [GRANDES EVENTOS] + [TEATROS Y OCIO] blocks
        interesting = ""
        for section in ("[GRANDES EVENTOS]", "[TEATROS Y OCIO]"):
            if section in summary:
                start = summary.index(section)
                # find next [SECTION] or end
                rest = summary[start:]
                idxs = [rest.find(f"\n[{s}", 1) for s in
                        ["METEO", "GRANDES", "TEATROS", "ALERTAS",
                         "AEROPUERTO", "PREVISIÓN"]
                        if rest.find(f"\n[{s}", 1) != -1]
                end = min(idxs) if idxs else len(rest)
                interesting += rest[:end].lower() + "\n"

        # Mad Cool 2026 ended 2026-07-12
        if today > "2026-07-12":
            assert "mad cool" not in interesting, (
                f"Mad Cool must NOT appear on {today} — but found it in "
                f"summary. Full summary:\n{summary}"
            )

        # Auditorio Miguel Ríos de Rivas — typically weekend programming.
        # Only flag if today is Mon/Tue/Wed/Thu (weekday 0..3)
        weekday = datetime.now(MADRID_TZ).weekday()
        if weekday <= 3 and "auditorio miguel ríos" in interesting:
            pytest.fail(
                f"Auditorio Miguel Ríos de Rivas found on weekday {weekday} "
                f"(Mon=0) — past-weekend event still present. Summary:\n{summary}"
            )

        # Common heuristics for stale-date wording
        stale_phrases = [
            "del fin de semana pasado",
            "terminó el domingo",
            "terminó ayer",
        ]
        found_stale = [ph for ph in stale_phrases if ph in interesting]
        assert not found_stale, (
            f"Summary references past events explicitly: {found_stale}\n"
            f"Full summary:\n{summary}"
        )


class TestLiveCacheReturnsSameGeneratedAt:
    def test_second_call_returns_cached(self, api_session):
        r1 = api_session.get(f"{BASE_URL}/api/events/daily-summary", timeout=120)
        if r1.status_code == 503:
            pytest.skip("Gemini 503 (quota)")
        assert r1.status_code == 200
        r2 = api_session.get(f"{BASE_URL}/api/events/daily-summary", timeout=30)
        assert r2.status_code == 200
        d1, d2 = r1.json(), r2.json()
        assert d1.get("generated_at") == d2.get("generated_at"), (
            "generated_at changed on 2nd non-force call → cache miss"
        )
        assert d1.get("cache_slot") == d2.get("cache_slot")
        slot = d1.get("cache_slot")
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}$", slot)
        hh = int(slot.split("T")[1])
        assert hh in {0, 4, 8, 12, 16, 20}


class TestLivePublicEndpoint:
    def test_public_endpoint_200(self, api_session):
        r = api_session.get(
            f"{BASE_URL}/api/events/daily-summary-public", timeout=60
        )
        assert r.status_code == 200
        d = r.json()
        assert d.get("success") is True
        assert d.get("summary"), "public summary empty"
        assert d.get("day_name") in {
            "lunes", "martes", "miércoles", "jueves",
            "viernes", "sábado", "domingo",
        }


# --------------------------------------------------------------------- #
# Report the raw summary to stdout for manual eyeball                   #
# --------------------------------------------------------------------- #
def teardown_module(module):
    """Print the raw summary for manual inspection + cleanup."""
    summary = _raw_state.get("force_refresh_summary")
    if summary:
        print("\n" + "=" * 70)
        print("RAW SUMMARY (force_refresh) — for manual date-verification:")
        print("=" * 70)
        print(summary)
        print("=" * 70)

    async def _cleanup():
        await daily_summaries_collection.delete_many(
            {"summary": {"$regex": "^TEST_MARKER_iter15"}}
        )
    try:
        asyncio.get_event_loop().run_until_complete(_cleanup())
    except Exception:
        pass
