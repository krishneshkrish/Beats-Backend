# Beats Backend 🎵

FastAPI backend for the Beats Premium AI Music PWA.

## Stack
- **FastAPI** — async API framework
- **SQLAlchemy (async) + aiosqlite** — SQLite ORM
- **scikit-learn** — ML recommendation model
- **Pydantic v2** — request/response validation (mirrors `index.ts` types exactly)

---

## Quick Start (Fedora 42)

```bash
cd beats-backend
bash run.sh
```

That's it. The script creates a venv, installs deps, seeds the DB, and starts the server.

API docs: http://localhost:8000/docs

---

## Connect to Next.js Frontend

In your Beats Next.js project, create/edit `.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

That's all — `src/lib/api.ts` already reads this variable.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/greeting` | Time-aware dynamic greeting |
| GET | `/api/recommendations?mood=Chill&limit=10` | Mood-filtered songs |
| GET | `/api/recommendations/ai?context=discover` | AI editorial picks |
| POST | `/api/log/play` | Log a play event (ML training data) |
| POST | `/api/mood/set` | Log mood change |
| GET | `/api/analytics/summary` | Music DNA dashboard data |
| GET | `/api/journey/timeline` | Storytelling timeline |
| GET | `/api/search?q=neon&type=songs` | Full-text search |
| POST | `/api/ml/train` | Trigger ML model training |
| GET | `/api/ml/status` | Check recommender mode + event count |
| GET | `/api/ml/events` | View recent play events (debug) |
| GET | `/health` | Health check |
| GET | `/docs` | Swagger UI |

---

## ML Progression

The recommender auto-switches between two modes:

### Phase 1 — Rule-Based (active immediately)
No training needed. Uses mood tag + time-of-day logic.

```
Workout → s3, s7, s5
Night   → s2, s6, s9
Focus   → s4, s8, s9
```

### Phase 2 — ML Model (kicks in after 50 play events)
Random Forest trained on your real listening data.

Features:
- `hour_of_day` — when you listen
- `day_of_week` — weekday vs weekend patterns
- `mood_encoded` — your mood at play time
- `was_skipped` — negative signal
- `was_replayed` — strong positive signal

To trigger training manually:
```bash
curl -X POST http://localhost:8000/api/ml/train
```

Check status:
```bash
curl http://localhost:8000/api/ml/status
```

### Phase 3 — Librosa Audio Features (future)
Once you add local audio files, run `scripts/extract_features.py` to enrich
the song catalog with BPM, energy, valence, danceability. These become
additional ML features for richer recommendations.

---

## Project Structure

```
beats-backend/
├── app/
│   ├── main.py              # FastAPI app, CORS, lifespan
│   ├── core/
│   │   └── config.py        # Settings (env vars)
│   ├── db/
│   │   ├── database.py      # SQLAlchemy tables + engine
│   │   ├── mock_data.py     # Mirrors frontend mockData.ts
│   │   └── seeder.py        # Seeds song catalog on startup
│   ├── models/
│   │   └── schemas.py       # Pydantic models (mirrors index.ts)
│   ├── ml/
│   │   └── recommender.py   # Rule-based + RF ML engine
│   └── routers/
│       ├── greeting.py
│       ├── recommendations.py
│       ├── log.py           # Play event logger
│       ├── mood.py
│       ├── analytics.py     # Music DNA
│       ├── journey.py       # Timeline storytelling
│       ├── search.py
│       └── ml.py            # Training trigger + status
├── data/
│   ├── beats.db             # SQLite (auto-created)
│   └── models/              # Trained .pkl files
├── .env.example
├── requirements.txt
└── run.sh
```

---

## Database Tables

| Table | Purpose |
|-------|---------|
| `play_events` | Every song play — core ML training data |
| `mood_logs` | Mood change history — time-of-day correlation |
| `song_catalog` | Song metadata + Librosa audio features |
| `user_sessions` | Session-level context for sequence modeling |

---

## Environment Variables

```env
APP_ENV=development
APP_PORT=8000
DATABASE_URL=sqlite+aiosqlite:///./data/beats.db
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:3001
MODEL_PATH=./data/models/recommender.pkl
SEED_MOCK_DATA=1
```
