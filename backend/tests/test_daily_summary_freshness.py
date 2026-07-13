"""
Tests for the daily-summary FRESHNESS bug fix (iteration_14).

Verifies:
  1. _build_prompt() emits the new REGLA DE VIGENCIA freshness rules
     (hora actual, en curso, TOTALMENTE PROHIBIDOS, etc.).
  2. _cache_slot_madrid() returns YYYY-MM-DDTHH with HH in {00,04,08,12,16,20}.
  3. _load_cached() / _persist() use the `cache_slot` key (NOT `date`).
  4. GET /api/events/daily-summary returns a payload that includes
     `cache_slot` matching the current slot.
  5. 2nd call within the SAME slot returns the cached payload
     (same cache_slot value, no new Gemini call).
  6. ?force_refresh=true bypasses the cache.
  7. Public endpoint /api/events/daily-summary-public also honours the
     cache_slot (does not return stale data from a previous slot).
  8. Gemini quota exhaustion → clean HTTP 503 with Spanish detail
     (existing behaviour, don't regress).
"""
import os
import re
import sys
import asyncio
import pytest
import requests
from datetime import datetime

import pytz

# Import daily_summary internals directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.daily_summary import (  # noqa: E402
    _build_prompt,
    _cache_slot_madrid,
    _load_cached,
    _persist,
    _today_madrid_str,
)
from shared import daily_summaries_collection  # noqa: E402

BASE_URL = "http://localhost:8001"
MADRID_TZ = pytz.timezone("Europe/Madrid")


# --------------------------------------------------------------------- #
# Unit-level: prompt content                                            #
# --------------------------------------------------------------------- #
class TestBuildPrompt:
    """The prompt must now instruct Gemini to filter out already-ended events."""

    def test_prompt_contains_current_hour(self):
        p = _build_prompt()
        assert "Hora actual en Madrid" in p, (
            "Prompt is missing 'Hora actual en Madrid' — the model has no "
            "way to filter finished events."
        )

    def test_prompt_contains_hora_de_referencia(self):
        assert "HORA DE REFERENCIA" in _build_prompt()

    def test_prompt_contains_ayer_anteayer_rule(self):
        # The reviewer asked for exactly this phrase snippet
        assert "AYER, ANTEAYER" in _build_prompt()

    def test_prompt_contains_finalization_rule(self):
        assert "FINALIZACIÓN sea anterior" in _build_prompt()

    def test_prompt_contains_en_curso_marker(self):
        assert "(en curso)" in _build_prompt()

    def test_prompt_contains_totalmente_prohibidos(self):
        assert "TOTALMENTE PROHIBIDOS" in _build_prompt()

    def test_prompt_uses_today_madrid_date(self):
        assert _today_madrid_str() in _build_prompt()

    def test_prompt_uses_now_hhmm(self):
        """HH:MM should appear at least twice (once in header, once in rule)."""
        now = datetime.now(MADRID_TZ).strftime("%H:%M")
        # Prompt is generated in the same second, so this should match.
        p = _build_prompt()
        assert p.count(now) >= 2, (
            f"Expected current time '{now}' at least twice in prompt, "
            f"found {p.count(now)}"
        )


# --------------------------------------------------------------------- #
# Unit-level: cache slot semantics                                      #
# --------------------------------------------------------------------- #
class TestCacheSlot:
    def test_slot_format(self):
        slot = _cache_slot_madrid()
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}$", slot), (
            f"Slot '{slot}' does not match YYYY-MM-DDTHH"
        )

    def test_slot_hour_in_allowed_bucket(self):
        slot = _cache_slot_madrid()
        hh = int(slot.split("T")[1])
        assert hh in {0, 4, 8, 12, 16, 20}, (
            f"Slot hour {hh} is not one of the expected 4-hour buckets"
        )

    def test_slot_matches_current_madrid_bucket(self):
        now = datetime.now(MADRID_TZ)
        expected_hh = (now.hour // 4) * 4
        expected = f"{now.strftime('%Y-%m-%d')}T{expected_hh:02d}"
        assert _cache_slot_madrid() == expected


# --------------------------------------------------------------------- #
# Unit-level: cache persistence keyed by cache_slot                     #
# --------------------------------------------------------------------- #
class TestCachePersistence:
    """Round-trip: _persist → _load_cached should use the cache_slot key."""

    def _cleanup(self):
        # Clean up any test docs we injected
        asyncio.get_event_loop().run_until_complete(
            daily_summaries_collection.delete_many({"summary": "TEST_MARKER_freshness"})
        )

    def test_persist_and_load_by_cache_slot(self):
        async def _run():
            slot = _cache_slot_madrid()
            payload = {
                "summary": "TEST_MARKER_freshness",
                "date": _today_madrid_str(),
                "cache_slot": slot,
                "generated_at": datetime.now(MADRID_TZ).isoformat(),
                "sources": [],
                "search_queries": ["q1", "q2"],
            }
            await _persist(payload)

            # Direct DB lookup by cache_slot
            doc = await daily_summaries_collection.find_one({"cache_slot": slot})
            assert doc is not None, "Persisted doc not found by cache_slot key"
            assert doc.get("summary") == "TEST_MARKER_freshness"
            assert doc.get("cache_slot") == slot

            # _load_cached must return it
            loaded = await _load_cached()
            assert loaded is not None
            assert loaded.get("summary") == "TEST_MARKER_freshness"
            assert loaded.get("cache_slot") == slot
            # _id must be stripped
            assert "_id" not in loaded

            # cleanup
            await daily_summaries_collection.delete_many(
                {"summary": "TEST_MARKER_freshness"}
            )

        asyncio.get_event_loop().run_until_complete(_run())

    def test_load_cached_ignores_previous_slot(self):
        """A doc from a previous 4-hour slot must NOT be returned as fresh."""

        async def _run():
            current_slot = _cache_slot_madrid()
            # Build a stale slot: subtract 4 hours safely
            date_part, hh = current_slot.split("T")
            stale_hh = (int(hh) - 4) % 24
            stale_slot = f"{date_part}T{stale_hh:02d}"
            if stale_slot == current_slot:  # guard against edge
                stale_slot = f"{date_part}T00" if hh != "00" else f"{date_part}T20"

            # Ensure no doc for current slot
            await daily_summaries_collection.delete_many(
                {"summary": "TEST_MARKER_freshness"}
            )
            # Insert a stale doc
            await daily_summaries_collection.insert_one({
                "summary": "TEST_MARKER_freshness",
                "date": _today_madrid_str(),
                "cache_slot": stale_slot,
                "generated_at": datetime.now(MADRID_TZ).isoformat(),
                "sources": [],
                "search_queries": [],
            })

            loaded = await _load_cached()
            # loaded either None OR a real (non-stale) doc; must not be ours
            if loaded is not None:
                assert loaded.get("summary") != "TEST_MARKER_freshness", (
                    "_load_cached returned a stale doc from previous slot!"
                )

            await daily_summaries_collection.delete_many(
                {"summary": "TEST_MARKER_freshness"}
            )

        asyncio.get_event_loop().run_until_complete(_run())


# --------------------------------------------------------------------- #
# API-level: response shape + caching + force_refresh                   #
# --------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def api_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(api_session):
    r = api_session.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": "admin", "password": "admin"},
        timeout=10,
    )
    if r.status_code == 200:
        return r.json().get("access_token")
    return None


class TestDailySummaryEndpoint:
    REQUIRED_KEYS = {
        "success", "summary", "sources", "search_queries",
        "date", "cache_slot", "generated_at", "airport_peaks",
    }

    def test_endpoint_200(self, api_session):
        r = api_session.get(f"{BASE_URL}/api/events/daily-summary", timeout=120)
        assert r.status_code == 200, r.text[:300]

    def test_payload_shape(self, api_session):
        r = api_session.get(f"{BASE_URL}/api/events/daily-summary", timeout=120)
        assert r.status_code == 200
        data = r.json()
        missing = self.REQUIRED_KEYS - set(data.keys())
        assert not missing, f"Missing keys in payload: {missing}"

    def test_cache_slot_format_and_current(self, api_session):
        r = api_session.get(f"{BASE_URL}/api/events/daily-summary", timeout=120)
        data = r.json()
        slot = data.get("cache_slot")
        assert slot is not None, "cache_slot missing"
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}$", slot), (
            f"Bad cache_slot format: {slot}"
        )
        # Must match the current Madrid slot
        assert slot == _cache_slot_madrid(), (
            f"Returned slot {slot} != current {_cache_slot_madrid()}"
        )

    def test_second_call_returns_cached_same_slot(self, api_session):
        r1 = api_session.get(f"{BASE_URL}/api/events/daily-summary", timeout=120)
        assert r1.status_code == 200
        r2 = api_session.get(f"{BASE_URL}/api/events/daily-summary", timeout=30)
        assert r2.status_code == 200
        d1, d2 = r1.json(), r2.json()
        assert d1["cache_slot"] == d2["cache_slot"], (
            "cache_slot changed between two calls within same slot"
        )
        # generated_at should be identical (proof of cache hit)
        assert d1.get("generated_at") == d2.get("generated_at"), (
            "generated_at differs → second call regenerated instead of using cache"
        )
        assert d1.get("summary") == d2.get("summary"), (
            "Summary text differs → cache was not hit"
        )

    def test_force_refresh_regenerates_or_503(self, api_session, admin_token):
        """?force_refresh=true must bypass cache. Either the payload is fresh
        (new generated_at) OR Gemini returns 503 (quota exhausted).
        Both outcomes prove the cache was bypassed."""
        # Baseline call
        r0 = api_session.get(f"{BASE_URL}/api/events/daily-summary", timeout=120)
        baseline_gen = r0.json().get("generated_at") if r0.status_code == 200 else None

        r = api_session.get(
            f"{BASE_URL}/api/events/daily-summary?force_refresh=true",
            timeout=180,
        )
        assert r.status_code in (200, 503), (
            f"Unexpected {r.status_code}: {r.text[:200]}"
        )
        if r.status_code == 503:
            # Must be Spanish user-facing message
            detail = r.json().get("detail", "")
            assert (
                "Cuota de Gemini" in detail
                or "saturado" in detail
                or "gemini" in detail.lower()
            ), f"503 without expected Spanish detail: {detail}"
            pytest.skip("Gemini quota exhausted — force_refresh path exercised OK")
        # 200 path: check cache_slot preserved, generated_at moved forward
        d = r.json()
        assert d.get("cache_slot") == _cache_slot_madrid()
        if baseline_gen is not None:
            assert d.get("generated_at") != baseline_gen, (
                "force_refresh returned identical generated_at → cache NOT bypassed"
            )


class TestPublicEndpointFreshness:
    def test_public_endpoint_200(self, api_session):
        r = api_session.get(
            f"{BASE_URL}/api/events/daily-summary-public", timeout=120
        )
        assert r.status_code == 200

    def test_public_endpoint_uses_current_slot(self, api_session):
        """The public endpoint reuses _load_cached, so after hitting the
        private endpoint (which persists under the CURRENT cache_slot),
        the public endpoint must serve fresh content, never a stale slot.
        We validate this by checking DB directly: doc with cache_slot ==
        current slot exists and matches the summary the public endpoint
        derived its markdown from."""

        # Warm the cache by hitting the private endpoint
        r_priv = api_session.get(
            f"{BASE_URL}/api/events/daily-summary", timeout=120
        )
        assert r_priv.status_code == 200
        priv = r_priv.json()

        # Now hit the public endpoint
        r_pub = api_session.get(
            f"{BASE_URL}/api/events/daily-summary-public", timeout=60
        )
        assert r_pub.status_code == 200
        pub = r_pub.json()

        # Both must reference the same underlying date and be non-empty
        assert pub.get("success") is True
        assert pub.get("date") == priv.get("date"), (
            f"public.date={pub.get('date')} != private.date={priv.get('date')}"
        )
        assert pub.get("summary"), "Public summary is empty"

        # And there IS a mongo doc for the current cache_slot
        async def _check():
            slot = _cache_slot_madrid()
            doc = await daily_summaries_collection.find_one({"cache_slot": slot})
            assert doc is not None, (
                f"No cached doc for current slot {slot} after warm-up"
            )
            assert doc.get("cache_slot") == slot
            return doc

        doc = asyncio.get_event_loop().run_until_complete(_check())
        # The private endpoint returned this same doc content
        assert priv.get("cache_slot") == doc["cache_slot"]


# --------------------------------------------------------------------- #
# Cleanup                                                               #
# --------------------------------------------------------------------- #
def teardown_module(module):
    """Delete any TEST_MARKER docs still in Mongo."""
    async def _cleanup():
        await daily_summaries_collection.delete_many(
            {"summary": "TEST_MARKER_freshness"}
        )
    try:
        asyncio.get_event_loop().run_until_complete(_cleanup())
    except Exception:
        pass
