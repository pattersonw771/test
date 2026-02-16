# EquiLens

EquiLens is a FastAPI web app that analyzes political framing from public URLs.

## Features

- URL analysis for:
  - web news articles
  - YouTube video links (metadata + available transcript/description)
  - X/Twitter post links
- Bias scoring (`Left`, `Center`, `Right`)
- Lead summary + rationale + global perspective section
- Source/extraction transparency metadata
- Persistent history, feedback, events, and jobs in database
- Account system: signup/login/logout with server-side sessions
- Async job API (`/api/jobs`) for non-blocking workflows
- Theme switcher with persistent preference
- About / Privacy / Terms pages

## Run locally

```powershell
cd c:\Users\patterson\political-bias-detector
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open: `http://127.0.0.1:8000`

## Core endpoints

- `GET /` - web app
- `GET /signup`, `POST /signup`
- `GET /login`, `POST /login`
- `POST /logout`
- `POST /analyze` - form-based analysis
- `POST /feedback` - save user feedback
- `GET /health` - health probe
- `POST /api/analyze` - synchronous JSON analysis
- `POST /api/jobs` - create async analysis job
- `GET /api/jobs/{job_id}` - poll job status
- `GET /api/history` - user/session history
- `GET /api/metrics` - basic product metrics
- `GET /about` / `GET /privacy` / `GET /terms`

## Storage

Storage backend is selected by `DATABASE_URL`:

- If `DATABASE_URL` is set: uses Postgres (recommended for deployment)
- Otherwise: falls back to local SQLite at `data/app.db`

## Free deployment ($0 start)

See `DEPLOY_FREE.md` for exact steps.

## Notes

- Model output is AI-generated and can be wrong.
- Global perspective is synthesized interpretation, not direct polling.
