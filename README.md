# Lyftr Chatbot – LLM Chatbot with Key Failover and Response Caching

A production-ready LLM chatbot with intelligent key-pool failover, built-in response caching via LiteLLM, and persistent SQLite session storage. Built with React, FastAPI, and Docker.

---

## Live URLs

| Service  | URL                                      |
|----------|------------------------------------------|
| Frontend | https://frontend-sigma-eight-vg3egywebw.vercel.app |
| Backend  | https://chatbot-api-kr09.onrender.com              |

---

## Run Locally

### With Docker (recommended)

```bash
# 1. Clone the repo
git clone <repo-url> && cd lyftr-chatbot

# 2. Create .env from example
cp .env.example .env
# Edit .env and add your real API keys to LLM_API_KEYS

# 3. Start everything
make up

# Frontend: http://localhost:3000
# Backend:  http://localhost:8000
```

### Without Docker

**Backend:**
```bash
cd backend
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Set env vars
export LLM_API_KEYS="key1,key2"
export DATABASE_URL="sqlite:///app.db"
export ALLOWED_ORIGINS="http://localhost:3000"
export ENABLE_FAILURE_SIMULATION="true"

uvicorn app.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
VITE_API_BASE_URL=http://localhost:8000 npm run dev
```

**Run tests:**
```bash
cd backend
pip install -r requirements.txt
python -m pytest tests/ -v
```

---

## Design Decisions

### Key Fallback
- Keys are stored in an ordered pool (`key_1`, `key_2`, ...) loaded from the `LLM_API_KEYS` env var.
- On each chat request, the system tries keys in order. If a key returns 429 (rate limit), 401/403 (auth error), 5xx, timeout, or connection error, it fails over to the next key.
- `fallback_attempts` tracks how many keys failed before success. If all keys fail → 503.
- The `X-Simulate-Failure` header (when `ENABLE_FAILURE_SIMULATION=true`) lets you test failover without real key failures, by injecting simulated errors per-key.

### Caching
- LiteLLM's built-in in-memory cache is enabled with `temperature=0` for deterministic outputs.
- Cache key = model + full message list (system prompt + history + new message). The `api_key` is NOT part of the cache key.
- Same first message in a NEW session → cache hit (`LLM_CACHE`), identical reply, with `key_id=null`.
- Different messages are never served from cache.
- When simulating failures, cache is bypassed so failover is always demonstrable.

### SQLite Session Storage
- WAL mode for concurrent reads, parameterized queries only.
- Each session's messages are stored with metadata (resolution_source, tokens, etc.).
- DB file lives on a Docker named volume at `/data` → survives container restarts.
- Thread-safe via `aiosqlite` (one connection per request).
- Per-session system prompt override persisted in a `sessions` table.

---

## Verification

### Health check
```bash
curl http://localhost:8000/health
# → {"status":"ok","keys_configured":2,"cache_enabled":true}
```

### Basic chat
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"s-test1","message":"What is 2+2?"}'
# → 200 with reply, metadata.resolution_source="LIVE_INFERENCE"
```

### Cache hit (same message, new session)
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"s-test2","message":"What is 2+2?"}'
# → 200 with metadata.resolution_source="LLM_CACHE", identical reply, key_id=null
```

### Failover: key_1 rate limited
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: key_1=429" \
  -d '{"session_id":"s-fail1","message":"Hello failover"}'
# → 200, metadata.key_id="key_2", fallback_attempts=1
```

### Failover: key_1=429, key_2=500
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: key_1=429,key_2=500" \
  -d '{"session_id":"s-fail2","message":"Both fail"}'
# → 503 {"detail":"all providers unavailable"}
```

### All keys fail
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: *=429" \
  -d '{"session_id":"s-fail3","message":"Star fail"}'
# → 503 {"detail":"all providers unavailable"}
```

### Validation errors (422)
```bash
# Empty message
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"s-v","message":""}'
# → 422

# Missing session_id
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"hi"}'
# → 422

# Message too long
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"s-v\",\"message\":\"$(python3 -c 'print("a"*4001)')\"}"
# → 422
```

### History endpoint
```bash
curl http://localhost:8000/sessions/s-test1/messages
# → 200 with messages array (oldest first), assistant has metadata

curl http://localhost:8000/sessions/nonexistent/messages
# → 404 {"detail":"session not found"}
```

---

## Setup Used

- **Editor**: Google Antigravity
- **AI Tools**: Claude (AI-assisted development via Antigravity)
- **Stack**: React 18 + Vite (frontend), Python 3.11 + FastAPI + LiteLLM + aiosqlite (backend), Docker + docker-compose

---

## Bonus Features

- **Dark theme UI** with smooth animations and typing indicator
- **Color-coded badges** for LIVE_INFERENCE (blue) vs LLM_CACHE (green)
- **Key ID and fallback count badges** shown on each message
- **Per-session system prompt** persisted across turns
- **React Error Boundary** for graceful crash recovery
- **Responsive design** works on mobile and desktop
- **Multi-stage Docker builds** for minimal image size
- **WAL mode SQLite** for concurrent performance

---

## Deployment Guide

### Backend (Render / Railway / Fly.io / Hugging Face Spaces)

1. **Choose a Docker-based deployment** platform (e.g., Render Web Service).
2. Set the **root directory** to `backend/` or use the provided Dockerfile.
3. Add a **persistent volume/disk** mounted at `/data` (required for SQLite persistence).
4. Set environment variables:
   ```
   LLM_API_KEYS=your-key-1,your-key-2
   LLM_MODEL=gemini/gemini-3.5-flash
   DATABASE_URL=sqlite:////data/app.db
   ALLOWED_ORIGINS=https://your-frontend.vercel.app
   ENABLE_FAILURE_SIMULATION=true
   PORT=8000
   ```
5. Deploy. The health check endpoint is `GET /health`.

### Frontend (Vercel / Netlify)

1. Set the **root directory** to `frontend/`.
2. **Build command**: `npm run build`
3. **Output directory**: `dist`
4. Set the build environment variable:
   ```
   VITE_API_BASE_URL=https://your-backend.onrender.com
   ```
5. Deploy. The SPA fallback is handled by the hosting platform.
