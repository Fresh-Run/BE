# Running Route AI 🏃‍♂️🇰🇷

A FastAPI backend that generates running routes in South Korea using OpenAI
Function Calling, enriched with real pedestrian routing and place data from
Kakao / Naver Map APIs, and persisted via Supabase.

## Features

- **AI route generation** — OpenAI Function Calling returns a structured,
  schema-validated route (distance, duration, ordered waypoints).
- **Pitstop resolution** — snap an AI-suggested pitstop (e.g. `편의점`,
  convenience store) to a real nearby place via the Map API.
- **Pedestrian routing** — fetch real walking path geometry between waypoints.
- **Supabase** — client wired up for persistence/auth.

## Project structure

```
app/
├── main.py                  # FastAPI entry point
├── api/
│   └── routes.py            # HTTP route handlers
├── services/
│   ├── openai_service.py    # OpenAI Function Calling → structured route
│   ├── map_service.py       # Kakao/Naver place search + pedestrian routing
│   └── route_service.py     # Orchestration glue
├── models/
│   └── schemas.py           # Pydantic schemas
└── core/
    ├── config.py            # Settings (pydantic-settings)
    └── supabase_client.py   # Supabase client setup
```

## Setup

### 1. Install dependencies

With **Poetry**:

```bash
poetry install
```

Or with **pip**:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# then fill in OPENAI_API_KEY, SUPABASE_*, and KAKAO_REST_API_KEY / NAVER_* keys
```

### 3. Run

```bash
uvicorn app.main:app --reload
```

Open the interactive docs at http://localhost:8000/docs

## Example request

```bash
curl -X POST http://localhost:8000/api/routes/generate \
  -H "Content-Type: application/json" \
  -d '{
    "start": {"lat": 37.5283, "lng": 126.9326},
    "target_distance_km": 5,
    "pitstop_keyword": "편의점"
  }'
```

## Notes on Korean Map APIs

- **Coordinate order**: Kakao expects `x=longitude, y=latitude`.
- Kakao Mobility & Naver Directions are primarily *driving* APIs. For
  sidewalk-accurate **pedestrian** routing — the right choice for runners —
  use the [T-map Pedestrian API](https://tmapapi.sktelecom.com), scaffolded as
  `_tmap_pedestrian_route` in `app/services/map_service.py`.
- Switch providers with `MAP_PROVIDER=kakao|naver|tmap` in `.env`. Set
  `TMAP_APP_KEY` when using `tmap`.
