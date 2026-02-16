# Free Deployment Guide (Render + Free Postgres)

This guide gets EquiLens online first, then enables durable auth/history with a free Postgres database.

## 1) Push repository to GitHub

Render deploys directly from your repo.

## 2) Create free Postgres (Supabase or Neon)

- Create a free project.
- Copy the `DATABASE_URL` connection string.

## 3) Deploy to Render (free)

1. Sign in to Render.
2. New -> Blueprint.
3. Select this repo.
4. Render reads `render.yaml`.
5. Set env vars:
   - `GROQ_API_KEY` (required)
   - `DATABASE_URL` (required for durable auth/history)
   - `GROQ_MODEL` (optional)
6. Deploy.

## 4) Verify

- `GET /health` returns `{ "status": "ok" }`
- Open home page, create account, log in, run analysis.
- Confirm history persists after redeploy/restart.

## 5) Auth routes

- `GET /signup`
- `POST /signup`
- `GET /login`
- `POST /login`
- `POST /logout`

## 6) API routes

- `POST /api/analyze`
- `POST /api/jobs`
- `GET /api/jobs/{job_id}`
- `GET /api/history`
- `GET /api/metrics`

## 7) Free-tier caveats

- Cold starts and resource limits still apply.
- Use database pooling options from provider defaults if needed.
