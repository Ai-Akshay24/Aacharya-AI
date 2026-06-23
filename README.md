# Aacharya AI — Rural Public Health Platform

**Aacharya AI** is a multilingual, offline-first public health chatbot built for rural and semi-urban communities in India. It provides deterministic, pre-vetted health guidance in English, Hindi, and Kannada, and includes a B2B portal for ASHA (Accredited Social Health Activist) workers to manage local medicine inventories and broadcast location-tagged health alerts across a decentralized hub-and-spoke supply network.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Knowledge Base](#knowledge-base)
- [ASHA Supply Network](#asha-supply-network)
- [Getting Started](#getting-started)
- [Backend API Reference](#backend-api-reference)
- [Frontend Routes](#frontend-routes)
- [Configuration & Environment](#configuration--environment)
- [Expanding the Knowledge Base](#expanding-the-knowledge-base)
- [Security Notes](#security-notes)
- [Reference Material](#reference-material)

---

## Overview

### The Problem

Rural healthcare access in India faces three compounding challenges:

- Unreliable internet connectivity makes cloud-dependent AI services unusable in the field.
- Generative LLMs produce inconsistent, disclaimer-heavy responses that are unsuitable for safety-critical health guidance in local languages.
- Medicine availability is poorly tracked — a patient at one village sub-centre has no way of knowing whether a medicine they need is stocked at a nearby centre.

### What Aacharya AI Does

- Resolves free-text health queries in **English, Hindi, and Kannada** (including Roman-script transliterations like "bukhar", "sir dard", "hotte novu") through a fully local, deterministic matching pipeline — **zero external API calls** on the chat path.
- Detects **critical emergencies** (snake bites, chest pain) via a hardcoded veto layer that bypasses all fuzzy logic and surfaces the 108 emergency number immediately.
- When a user requests a medicine, presents a **live stock availability check** across a 5-node regional cluster with automatic proximity-based fallback routing.
- Lets **ASHA workers** log in, update their centre's medicine inventory, and broadcast location-prefixed health alerts to the entire cluster.

---

## Architecture

### Local Deterministic Matching Pipeline (Backend)

The chat resolution pipeline has four sequential stages, all running in-process with no network dependency:

```
User Input (any script / language)
         │
         ▼
┌─────────────────────────────┐
│ Stage 0 — Normalizer        │  Unicode NFC, lowercase, punctuation
│                             │  strip, Roman spelling fixups
│                             │  (e.g. "dardh" → "dard")
└────────────┬────────────────┘
             ▼
┌─────────────────────────────┐
│ Stage 1 — Emergency Veto    │  Exact substring scan against
│ (runs first, always wins)   │  hardcoded critical tokens only.
│                             │  If matched → bypass all further
│                             │  stages, return 108 alert.
└────────────┬────────────────┘
             ▼ (no critical hit)
┌─────────────────────────────┐
│ Stage 2 — Exact Concept     │  Longest-token-first substring
│ Resolution                  │  lookup in the canonical_tokens
│                             │  index (all 3 languages).
└────────────┬────────────────┘
             ▼ (no exact hit)
┌─────────────────────────────┐
│ Stage 3 — Fuzzy Fallback    │  RapidFuzz token_sort_ratio
│ (non-critical only)         │  against canonical token pool.
│                             │  Language-specific thresholds:
│                             │  EN ≥88, HI ≥82, KN ≥78.
└────────────┬────────────────┘
             ▼
┌─────────────────────────────┐
│ Stage 4 — Intent Resolver   │  concept_id → structured
│                             │  MatchResult consumed by auth.py
└─────────────────────────────┘
```

**Critical design rule:** Stage 1 emergency tokens are excluded from the fuzzy pool entirely. A typo can never soften an emergency match.

### Hub-and-Spoke Supply Network

A static 5×5 distance matrix (hand-authored road distances, not straight-line) covers the Chikkaballapur regional cluster. When a requested centre has zero stock, the routing engine walks proximity-sorted neighbours and returns the nearest stocked alternative. Stock reservation uses a **single conditional `UPDATE WHERE quantity >= amount`** — there is no read-then-write gap for concurrent requests to double-book.

---

## Project Structure

```
Aacharya AI/
├── backend/
│   ├── auth.py                 # FastAPI server — all endpoints
│   ├── matcher.py              # Stage 0–4 local NLP pipeline
│   ├── models.py               # SQLModel schema (multi-center)
│   ├── inventory_routing.py    # 5×5 distance matrix + fallback routing
│   ├── knowledge_base.json     # Multilingual concept dictionary (v2.0)
│   ├── seed_db.py              # Database seeder (5 centers × 8 medicines)
│   └── requirements.txt        # Pruned dependencies (no ML stack)
│
├── frontend/
│   ├── src/
│   │   ├── App.js              # Route definitions + PWA service worker
│   │   ├── components/
│   │   │   ├── LanguageSelector.js   # Entry screen (EN / HI / KN)
│   │   │   ├── Chat.js               # Main chat interface
│   │   │   ├── Login.js              # ASHA worker login
│   │   │   ├── Dashboard.js          # Worker inventory + alert portal
│   │   │   ├── ProtectedRoute.js     # JWT-gated route wrapper
│   │   │   └── ui/                   # shadcn/ui component library
│   │   ├── hooks/use-toast.js
│   │   └── lib/utils.js
│   ├── craco.config.js         # Webpack alias: @/ → src/
│   ├── jsconfig.json           # Editor path alias (no baseUrl)
│   ├── tailwind.config.js
│   └── package.json            # Proxy: http://127.0.0.1:8000
│
└── docs/
    └── reference-material/
        └── knowledge_base/     # WHO-sourced prose docs (not runtime)
```

---

## Knowledge Base

`backend/knowledge_base.json` is the single source of truth for all chatbot responses. It is read once at server startup and never modified at runtime.

**Current coverage (v2.0.0 — 19 concepts):**

| Category | Concepts |
|---|---|
| Emergency (critical veto) | Snake Bite, Chest Pain |
| Symptoms | Fever, Headache, Stomach Pain, Diarrhea, Allergy, Acidity, Weakness |
| Diseases | Dengue, Malaria |
| Vaccines | BCG |
| Medicines | Paracetamol 500mg, Dicyclomine 10mg, ORS Packet, Amoxicillin 250mg, Iron & Folic Acid, Cetirizine 10mg, Antacid |

Each concept contains:

```json
{
  "concept_id": "MED_ORS_001",
  "type": "medicine",
  "severity_tier": "standard",
  "bypass_fuzzy_matching": false,
  "canonical_tokens": {
    "en": ["ors", "oral rehydration", "electral", "..."],
    "hi": ["ors", "ओआरएस", "electral", "jeevan jal", "..."],
    "kn": ["ors", "ಓಆರ್‌ಎಸ್", "electral", "jeevan jala", "..."]
  },
  "response": {
    "en": { "text": "...", "audio_file": "audio/en/med_ors_001.mp3" },
    "hi": { "text": "...", "audio_file": "audio/hi/med_ors_001.mp3" },
    "kn": { "text": "...", "audio_file": "audio/kn/med_ors_001.mp3" }
  },
  "requires_location": true,
  "linked_concepts": ["SYM_DIARRHEA_001"],
  "suggested_medicines": [],
  "escalation_flag": false
}
```

**`requires_location: true`** signals the frontend to render the ASHA centre dropdown for a live stock check instead of returning a plain text response.

---

## ASHA Supply Network

### Regional Cluster — Chikkaballapur District, Karnataka

| Node ID | Name | Type |
|---|---|---|
| `PHC_CKB_HUB` | Chikkaballapur District PHC | District Hub |
| `SC_CKB_MANCHE` | Manchenahalli Sub-Centre | Village Sub-Centre |
| `SC_CKB_NAGA` | Nagamangala Sub-Centre | Village Sub-Centre |
| `SC_CKB_DIBBUR` | Dibburahalli Sub-Centre | Village Sub-Centre |
| `SC_CKB_MELUR` | Melur Sub-Centre | Village Sub-Centre |

### 5×5 Distance Matrix (road distances in km)

| | HUB | MANCHE | NAGA | DIBBUR | MELUR |
|---|---|---|---|---|---|
| **HUB** | — | 6.2 | 8.9 | 11.4 | 7.8 |
| **MANCHE** | 6.2 | — | 9.5 | 14.0 | 5.3 |
| **NAGA** | 8.9 | 9.5 | — | 6.7 | 10.1 |
| **DIBBUR** | 11.4 | 14.0 | 6.7 | — | 9.0 |
| **MELUR** | 7.8 | 5.3 | 10.1 | 9.0 | — |

Routing is relative to **any** node — if a user selects Manchenahalli, the fallback order is Melur (5.3 km) → Hub (6.2 km) → Nagamangala (9.5 km) → Dibburahalli (14.0 km).

### Seeded Stock Baseline

| Item | HUB | MANCHE | NAGA | DIBBUR | MELUR |
|---|---|---|---|---|---|
| Paracetamol 500mg | 240 | **0** | random | random | **1** |
| BCG Vaccine | 50 | random | **0** | **0** | random |
| All other items | random | random | random | random | random |

Manchenahalli Paracetamol = 0 and Melur = 1 are deliberate — they exercise the fallback routing path and the atomic concurrency edge case respectively.

---

## Getting Started

### Prerequisites

- Python 3.10+
- Node.js 18+ and Yarn
- No external API keys required for core chat functionality

### 1. Backend Setup

```bash
cd backend

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # macOS / Linux
venv\Scripts\activate           # Windows

# Install dependencies (no ML stack — fast install)
pip install -r requirements.txt

# Create and configure your environment file
cp .env.example .env
# Edit .env and set a strong SECRET_KEY

# Seed the database
python seed_db.py

# Start the FastAPI server
uvicorn auth:app --reload --host 127.0.0.1 --port 8000
```

The backend starts at `http://127.0.0.1:8000`. Interactive API docs are available at `http://127.0.0.1:8000/docs`.

### 2. Frontend Setup

```bash
cd frontend

# Install dependencies
yarn install

# Start the development server
yarn start
```

The frontend starts at `http://localhost:3000`. All `/api/*` requests are proxied to `http://127.0.0.1:8000` automatically via the `proxy` field in `package.json` — no CORS configuration needed during development.

### 3. First Run Checklist

- [ ] Backend server running on port 8000
- [ ] `seed_db.py` has been run (creates `health_chatbot.db` with 5 centres, 5 workers, 40 inventory rows)
- [ ] Frontend dev server running on port 3000
- [ ] Open `http://localhost:3000`, select a language, and send a test query

### Default Seed Credentials

All five seeded ASHA worker accounts share the same password for local development. **Change these before any deployment.**

| Username | Centre | Password |
|---|---|---|
| `hubworker` | Chikkaballapur District PHC | `securepass` |
| `mancheworker` | Manchenahalli Sub-Centre | `securepass` |
| `nagaworker` | Nagamangala Sub-Centre | `securepass` |
| `dibburworker` | Dibburahalli Sub-Centre | `securepass` |
| `melurworker` | Melur Sub-Centre | `securepass` |

---

## Backend API Reference

### Public Endpoints

**`POST /api/chat`**

Resolves a health query through the local 4-stage pipeline.

Request:
```json
{ "query": "mujhe bukhar hai", "language": "hi" }
```

Response (standard):
```json
{
  "response": "हल्के बुखार में आराम करें...",
  "intent": "symptom",
  "requires_location": false,
  "escalation_flag": false,
  "escalation_action": null
}
```

Response (medicine — triggers frontend dropdown):
```json
{
  "response": "पैरासिटामोल 500mg बुखार और हल्के दर्द में मदद करती है...",
  "intent": "medicine",
  "requires_location": true,
  "item_id": "MED_PARA_500",
  "escalation_flag": false
}
```

Response (emergency — always returned immediately):
```json
{
  "response": "This is a medical emergency. Call 108 immediately...",
  "intent": "emergency",
  "requires_location": false,
  "escalation_flag": true,
  "escalation_action": "DISPLAY_EMERGENCY_NUMBER_108"
}
```

**`GET /api/get-alerts`**

Returns all broadcast alerts, newest first. Alerts are append-only.

**`GET /api/inventory/nearest-stock?center_id=SC_CKB_MANCHE&item_id=MED_PARA_500`**

Read-only proximity stock check. Returns the nearest centre with available stock relative to the requested centre.

```json
{
  "found": true,
  "center_id": "SC_CKB_MELUR",
  "center_name": "Melur Sub-Centre",
  "distance_km": 5.3,
  "quantity_available": 1,
  "is_fallback": true,
  "global_out_of_stock": false
}
```

### Protected Worker Endpoints (Bearer Token Required)

**`POST /api/worker/login`**

```json
{ "username": "nagaworker", "password": "securepass" }
```
Returns `{ "access_token": "...", "token_type": "bearer" }`.

**`GET /api/worker/get-inventory`**

Returns inventory rows scoped to the authenticated worker's assigned centre only.

**`POST /api/worker/update-inventory`**

```json
{ "item_id": "MED_ORS_001", "item_name": "ORS Packet", "quantity": 45 }
```

No `center_id` in the request — the backend derives it from the JWT. Creates the row if it doesn't exist; updates quantity if it does. A worker cannot write to another centre's inventory.

**`POST /api/worker/broadcast-alert`**

```json
{ "message": "Dengue cases rising in the area" }
```

The backend prepends the worker's centre name automatically before saving: `"Nagamangala Sub-Centre: Dengue cases rising in the area"`.

---

## Frontend Routes

| Path | Component | Access |
|---|---|---|
| `/` | `LanguageSelector` | Public |
| `/chat` | `Chat` | Public |
| `/login` | `Login` | Public |
| `/dashboard` | `Dashboard` | Protected (JWT) |

The selected language (`en` / `hi` / `kn`) is stored in `localStorage` at `selected_language` and read by `Chat.js` on mount.

---

## Configuration & Environment

Create `backend/.env` with the following keys:

```env
# Required — generate a strong random string for production
SECRET_KEY="your-strong-secret-key-here"

# Optional — defaults shown
# ACCESS_TOKEN_EXPIRE_MINUTES=60
```

**Do not commit `.env` to version control.** It is covered by `.gitignore`.

### Frontend Environment

`frontend/.env` can override the API proxy for staging or production builds:

```env
REACT_APP_API_URL=https://your-production-api.example.com
```

---

## Expanding the Knowledge Base

To add a new concept, append a new object to the `concepts` array in `backend/knowledge_base.json`. No code changes are required — `matcher.py` rebuilds its index at startup.

Minimum required fields:

```json
{
  "concept_id": "SYM_COUGH_001",
  "type": "symptom",
  "severity_tier": "standard",
  "bypass_fuzzy_matching": false,
  "canonical_tokens": {
    "en": ["cough", "dry cough", "wet cough"],
    "hi": ["khansi", "खांसी", "sukhi khansi"],
    "kn": ["kembilu", "ಕೆಮ್ಮು", "oola kembilu"]
  },
  "response": {
    "en": { "text": "...", "audio_file": "audio/en/sym_cough_001.mp3" },
    "hi": { "text": "...", "audio_file": "audio/hi/sym_cough_001.mp3" },
    "kn": { "text": "...", "audio_file": "audio/kn/sym_cough_001.mp3" }
  },
  "suggested_medicines": [],
  "escalation_flag": false
}
```

To add a new medicine to the seeder, add an entry to the `MEDICINES` list in `seed_db.py` and re-run it against a fresh database.

**Token authoring rules:**

- Include the generic name, common brand names, and colloquial terms per language.
- For critical/emergency entries, set `"bypass_fuzzy_matching": true` — these will only ever match exactly, never approximately.
- Run `python matcher.py` after any KB edit to verify the self-test suite still resolves correctly.
- Watch for token collisions — if two concepts share an identical normalised token in the same language, the second one silently wins. The collision check in `matcher.py`'s `KnowledgeBase.__init__` will log a warning.

---

## Security Notes

- **Rotate credentials before deployment.** The seed script sets all worker passwords to `securepass` and prints a warning at runtime. Change these and generate a strong `SECRET_KEY` before any non-local use.
- **`backend/.env` is git-ignored.** Confirm it never appears in your repository history.
- **`bcrypt==4.0.1` is pinned** in `requirements.txt`. Newer bcrypt versions break passlib's version introspection — do not bump this without re-testing password hashing end-to-end.
- **SQLite is appropriate for this cluster size** (5 nodes, low concurrent write volume). SQLite's write serialisation is sufficient for the atomic `UPDATE WHERE quantity >= amount` pattern used in `inventory_routing.py`. If the cluster grows significantly, migrating to PostgreSQL would unlock true row-level locking.
- **CORS is open (`allow_origins=["*"]`)** for development. Tighten this to your specific frontend origin before production deployment.

---

## Reference Material

`docs/reference-material/knowledge_base/` contains WHO-sourced prose documents covering a broader range of conditions (Dengue, Malaria, Tuberculosis, Typhoid, Snake bite, Vaccination schedules, and others). These files are **not read at runtime** — they are a content reference for authors expanding `knowledge_base.json` with new colloquial multilingual entries.
