"""Comprehensive backend tests – LiteLLM mocked, all spec scenarios covered."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

# Reload config with test env
import importlib
import app.config
importlib.reload(app.config)
from app.config import settings as _settings
_settings.__init__()

# Now import the app
from app.main import app
from app.db import init_db


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_response(text="Hello!", prompt_tokens=10, completion_tokens=5, cache_hit=False):
    """Create a mock LiteLLM response."""
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens

    choice = MagicMock()
    choice.message.content = text

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    resp._hidden_params = {"cache_hit": cache_hit}
    return resp


@pytest.fixture(autouse=True)
async def setup_db():
    """Ensure DB tables exist for each test."""
    await init_db()
    yield


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ── Health ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["keys_configured"] == 2
    assert data["cache_enabled"] is True


# ── Validation 422 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_422_empty_message(client):
    resp = await client.post("/chat", json={"session_id": "s-1", "message": ""})
    assert resp.status_code == 422
    assert "detail" in resp.json()


@pytest.mark.asyncio
async def test_422_whitespace_only(client):
    resp = await client.post("/chat", json={"session_id": "s-1", "message": "   \n\t  "})
    assert resp.status_code == 422
    assert "detail" in resp.json()


@pytest.mark.asyncio
async def test_422_message_too_long(client):
    resp = await client.post("/chat", json={"session_id": "s-1", "message": "a" * 4001})
    assert resp.status_code == 422
    assert "detail" in resp.json()


@pytest.mark.asyncio
async def test_422_missing_session_id(client):
    resp = await client.post("/chat", json={"message": "hi"})
    assert resp.status_code == 422
    assert "detail" in resp.json()


@pytest.mark.asyncio
async def test_422_malformed_json(client):
    resp = await client.post("/chat", content=b"not json", headers={"Content-Type": "application/json"})
    assert resp.status_code == 422
    assert "detail" in resp.json()


# ── Chat basic ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_basic(client):
    mock_resp = _mock_response("I'm helpful!", 15, 7)
    with patch("app.llm.litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp):
        resp = await client.post("/chat", json={"session_id": "s-basic", "message": "Hello"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "s-basic"
    assert data["reply"] == "I'm helpful!"
    meta = data["metadata"]
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert meta["model"] == "gemini/gemini-3.5-flash"
    assert isinstance(meta["latency_ms"], int)
    assert meta["input_tokens"] == 15
    assert meta["output_tokens"] == 7
    assert meta["key_id"] == "key_1"
    assert meta["fallback_attempts"] == 0


# ── Multi-turn memory ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_multi_turn_memory(client):
    """History sent to LLM must include prior turns."""
    mock_resp1 = _mock_response("Answer 1", 10, 5)
    mock_resp2 = _mock_response("Answer 2", 20, 8)
    captured_calls = []

    async def capture_completion(**kwargs):
        captured_calls.append(kwargs["messages"])
        return mock_resp1 if len(captured_calls) == 1 else mock_resp2

    with patch("app.llm.litellm.acompletion", side_effect=capture_completion):
        await client.post("/chat", json={"session_id": "s-multi", "message": "Turn 1"})
        await client.post("/chat", json={"session_id": "s-multi", "message": "Turn 2"})

    # Second call should include system + turn1 user + turn1 assistant + turn2 user
    msgs = captured_calls[1]
    assert msgs[0]["role"] == "system"
    assert msgs[1] == {"role": "user", "content": "Turn 1"}
    assert msgs[2] == {"role": "assistant", "content": "Answer 1"}
    assert msgs[3] == {"role": "user", "content": "Turn 2"}


# ── Session isolation ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_session_isolation(client):
    """Different sessions don't share history."""
    captured_calls = []
    mock_resp = _mock_response("Reply", 10, 5)

    async def capture_completion(**kwargs):
        captured_calls.append(kwargs["messages"])
        return mock_resp

    with patch("app.llm.litellm.acompletion", side_effect=capture_completion):
        await client.post("/chat", json={"session_id": "s-iso-1", "message": "In session 1"})
        await client.post("/chat", json={"session_id": "s-iso-2", "message": "In session 2"})

    # Session 2's call should only have system + its own message
    msgs = captured_calls[1]
    assert len(msgs) == 2  # system + user
    assert msgs[1]["content"] == "In session 2"


# ── History endpoint ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_history_endpoint(client):
    mock_resp = _mock_response("Answer", 10, 5)
    with patch("app.llm.litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp):
        await client.post("/chat", json={"session_id": "s-hist", "message": "Question"})

    resp = await client.get("/sessions/s-hist/messages")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "s-hist"
    msgs = data["messages"]
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "Question"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"] == "Answer"
    # Assistant message must have metadata
    assert "metadata" in msgs[1]
    assert "resolution_source" in msgs[1]["metadata"]
    assert "input_tokens" in msgs[1]["metadata"]
    assert "output_tokens" in msgs[1]["metadata"]


@pytest.mark.asyncio
async def test_history_404(client):
    resp = await client.get("/sessions/nonexistent/messages")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "session not found"


@pytest.mark.asyncio
async def test_history_oldest_first(client):
    """Messages are returned oldest first."""
    mock_resp1 = _mock_response("A1", 10, 5)
    mock_resp2 = _mock_response("A2", 20, 8)
    call_count = [0]

    async def ordered_resp(**kwargs):
        call_count[0] += 1
        return mock_resp1 if call_count[0] == 1 else mock_resp2

    with patch("app.llm.litellm.acompletion", side_effect=ordered_resp):
        await client.post("/chat", json={"session_id": "s-order", "message": "Q1"})
        await client.post("/chat", json={"session_id": "s-order", "message": "Q2"})

    resp = await client.get("/sessions/s-order/messages")
    msgs = resp.json()["messages"]
    assert len(msgs) == 4
    assert msgs[0]["content"] == "Q1"
    assert msgs[1]["content"] == "A1"
    assert msgs[2]["content"] == "Q2"
    assert msgs[3]["content"] == "A2"


# ── Cache hit labeling ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cache_hit_labeling(client):
    """Same message in a new session -> LLM_CACHE with identical reply, key_id null."""
    mock_live = _mock_response("Cached answer", 10, 5, cache_hit=False)
    mock_cached = _mock_response("Cached answer", 10, 5, cache_hit=True)
    call_count = [0]

    async def mock_completion(**kwargs):
        call_count[0] += 1
        return mock_live if call_count[0] == 1 else mock_cached

    with patch("app.llm.litellm.acompletion", side_effect=mock_completion):
        r1 = await client.post("/chat", json={"session_id": "s-cache-1", "message": "Hello cache"})
        r2 = await client.post("/chat", json={"session_id": "s-cache-2", "message": "Hello cache"})

    d1 = r1.json()
    d2 = r2.json()
    assert d1["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert d2["metadata"]["resolution_source"] == "LLM_CACHE"
    assert d2["reply"] == d1["reply"]  # identical reply
    assert d2["metadata"]["key_id"] is None
    assert d2["metadata"]["fallback_attempts"] == 0


@pytest.mark.asyncio
async def test_different_message_not_cached(client):
    mock_resp = _mock_response("Different", 10, 5, cache_hit=False)
    with patch("app.llm.litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp):
        r = await client.post("/chat", json={"session_id": "s-diff", "message": "Unique message"})
    assert r.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"


# ── Per-request tokens not cumulative ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_tokens_per_request(client):
    mock1 = _mock_response("R1", 10, 5)
    mock2 = _mock_response("R2", 15, 8)
    call_count = [0]

    async def mock_comp(**kwargs):
        call_count[0] += 1
        return mock1 if call_count[0] == 1 else mock2

    with patch("app.llm.litellm.acompletion", side_effect=mock_comp):
        r1 = await client.post("/chat", json={"session_id": "s-tok", "message": "M1"})
        r2 = await client.post("/chat", json={"session_id": "s-tok", "message": "M2"})

    # Second request must NOT be cumulative
    assert r2.json()["metadata"]["input_tokens"] == 15
    assert r2.json()["metadata"]["output_tokens"] == 8


# ── Failover via X-Simulate-Failure ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_failover_key1_429(client):
    """key_1=429 -> key_2 answers."""
    mock_resp = _mock_response("From key 2", 10, 5)
    with patch("app.llm.litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp):
        resp = await client.post(
            "/chat",
            json={"session_id": "s-fo1", "message": "Test failover"},
            headers={"X-Simulate-Failure": "key_1=429"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["metadata"]["key_id"] == "key_2"
    assert data["metadata"]["fallback_attempts"] == 1


@pytest.mark.asyncio
async def test_failover_key1_500(client):
    """key_1=500 -> key_2 answers."""
    mock_resp = _mock_response("From key 2", 10, 5)
    with patch("app.llm.litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp):
        resp = await client.post(
            "/chat",
            json={"session_id": "s-fo2", "message": "Test 500"},
            headers={"X-Simulate-Failure": "key_1=500"},
        )
    assert resp.status_code == 200
    assert resp.json()["metadata"]["key_id"] == "key_2"


@pytest.mark.asyncio
async def test_failover_both_keys_fail(client):
    """key_1=429,key_2=500 -> 503."""
    mock_resp = _mock_response("Never reached", 10, 5)
    with patch("app.llm.litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp):
        resp = await client.post(
            "/chat",
            json={"session_id": "s-fo3", "message": "Both fail"},
            headers={"X-Simulate-Failure": "key_1=429,key_2=500"},
        )
    assert resp.status_code == 503
    assert resp.json()["detail"] == "all providers unavailable"


@pytest.mark.asyncio
async def test_failover_star_429(client):
    """*=429 -> 503 and no history added."""
    with patch("app.llm.litellm.acompletion", new_callable=AsyncMock):
        resp = await client.post(
            "/chat",
            json={"session_id": "s-star", "message": "Star fail"},
            headers={"X-Simulate-Failure": "*=429"},
        )
    assert resp.status_code == 503
    assert resp.json()["detail"] == "all providers unavailable"

    # Verify nothing was added to history
    hist = await client.get("/sessions/s-star/messages")
    # Session might not exist (404) or be empty
    if hist.status_code == 200:
        assert len(hist.json()["messages"]) == 0
    else:
        assert hist.status_code == 404


@pytest.mark.asyncio
async def test_sim_header_ignored_when_disabled(client):
    """X-Simulate-Failure header ignored when ENABLE_FAILURE_SIMULATION=false."""
    from app.config import settings as s
    original = s.ENABLE_FAILURE_SIMULATION
    s.ENABLE_FAILURE_SIMULATION = False
    try:
        mock_resp = _mock_response("Normal response", 10, 5)
        with patch("app.llm.litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp):
            resp = await client.post(
                "/chat",
                json={"session_id": "s-nodis", "message": "Should not fail"},
                headers={"X-Simulate-Failure": "*=429"},
            )
        assert resp.status_code == 200
        assert resp.json()["metadata"]["key_id"] == "key_1"
    finally:
        s.ENABLE_FAILURE_SIMULATION = original


# ── 503 leaves history unchanged ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_503_no_history(client):
    """Failed requests (503) must not add to history."""
    # First, add a successful message
    mock_resp = _mock_response("Success", 10, 5)
    with patch("app.llm.litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp):
        await client.post("/chat", json={"session_id": "s-503h", "message": "Good"})

    # Now fail
    with patch("app.llm.litellm.acompletion", new_callable=AsyncMock):
        resp = await client.post(
            "/chat",
            json={"session_id": "s-503h", "message": "Bad"},
            headers={"X-Simulate-Failure": "*=429"},
        )
    assert resp.status_code == 503

    # History should only have the first turn
    hist = await client.get("/sessions/s-503h/messages")
    assert len(hist.json()["messages"]) == 2  # user + assistant from first turn only


# ── Persistence across restart ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_persistence(client):
    """Data survives re-init (simulated restart)."""
    mock_resp = _mock_response("Persisted", 10, 5)
    with patch("app.llm.litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp):
        await client.post("/chat", json={"session_id": "s-persist", "message": "Save me"})

    # Re-init DB (simulates restart)
    await init_db()

    hist = await client.get("/sessions/s-persist/messages")
    assert hist.status_code == 200
    assert len(hist.json()["messages"]) == 2
    assert hist.json()["messages"][1]["content"] == "Persisted"
