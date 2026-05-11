# SOP Troubleshooting Chatbot

A production-ready customer-facing troubleshooting chatbot that executes structured SOP (Standard Operating Procedure) flows — not free-form RAG responses.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  Customer Browser                                        │
│  React Chat UI  ←→  React Admin UI                      │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP / REST
┌────────────────────▼────────────────────────────────────┐
│  FastAPI Backend                                         │
│                                                          │
│  /chat/message  →  ConversationService (state machine)   │
│                     ↓                                    │
│              FlowEngine (SOP step runner)                │
│                     ↓                                    │
│          LLM Service (classify / interpret only)         │
│                                                          │
│  /sops/upload  →  Ingestion Pipeline                     │
│                   PDF/DOCX → LLM Parser → SOP JSON       │
│                                                          │
│  /sops/search  →  HybridSearch (keyword + pgvector)      │
└────────────────────┬────────────────────────────────────┘
                     │ SQLAlchemy
┌────────────────────▼────────────────────────────────────┐
│  Supabase / PostgreSQL + pgvector                        │
│                                                          │
│  products  issues  sop_flows  sop_chunks (embeddings)   │
│  conversations  conversation_events                      │
│  escalations  analytics_events                          │
└─────────────────────────────────────────────────────────┘
```

### Key Architectural Principle

The LLM is used for:
- Parsing raw SOP documents into structured JSON (ingestion time, not runtime)
- Classifying customer messages to identify product/issue
- Interpreting customer step replies (maps to controlled labels only)
- Generating escalation summaries

The LLM is **not** used for:
- Generating troubleshooting steps (these come only from approved SOP JSON)
- Answering questions from raw PDFs at runtime
- Inventing or skipping steps

---

## Directory Structure

```
/backend          FastAPI application
  /app
    /api          REST endpoints (chat, sops, escalations, analytics, admin)
    /ingestion    PDF/DOCX extraction + LLM SOP parser
    /models       SQLAlchemy ORM models + Pydantic schemas
    /services     LLM, embeddings, search, conversation, flow engine, analytics
    /prompts      (unused — prompts are in /prompts at root)
  requirements.txt
  Dockerfile
  .env.example

/frontend         React web app (Vite)
  /src
    /components   ChatBubble, QuickReplies, DebugPanel
    /pages        ChatPage, AdminPage
    /services     api.js

/prompts          LLM prompt templates (sop_parser, classifier, step_interpreter, etc.)
/data
  /sops           Drop PDF/DOCX files here for ingestion
  /parsed_sops    Auto-generated structured SOP JSON files
  /seeds          Pre-built sample SOP JSON files (Wi-Fi Router, Smart TV, AC)
/migrations       SQL migration files
/scripts          run_migrations.py, seed_data.py, run_ingestion.py
/tests            pytest test suite
docker-compose.yml
```

---

## Setup Instructions

### Prerequisites

- Python 3.11+
- Node.js 20+
- PostgreSQL 15+ with pgvector extension OR Supabase account
- OpenAI API key (or compatible provider)

---

### 1. Supabase Setup (Recommended for Production)

1. Create a project at [supabase.com](https://supabase.com)
2. In the SQL Editor, enable pgvector:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
3. Copy your **Project URL**, **Service Role Key**, and **Anon Key** from Settings → API

---

### 2. Environment Variables

```bash
cd backend
cp .env.example .env
```

Edit `backend/.env`:

```env
SUPABASE_URL=https://your-ref.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_ANON_KEY=your-anon-key

# OR for local Postgres (override Supabase)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/chatbot

# LLM
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-small

ENVIRONMENT=development
```

---

### 3. Run Database Migrations

```bash
cd backend
pip install -r requirements.txt

# Option A: using the script
python ../scripts/run_migrations.py

# Option B: paste migration files into Supabase SQL Editor
# migrations/001_pgvector.sql
# migrations/002_initial_schema.sql
```

---

### 4. Load Seed Data (Sample SOPs)

This loads 3 pre-built SOPs (Wi-Fi Router, Smart TV, Air Conditioner) directly into the database without needing LLM or real PDF files:

```bash
python ../scripts/seed_data.py
```

---

### 5. Start Backend

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

API docs available at: [http://localhost:8000/docs](http://localhost:8000/docs)

---

### 6. Start Frontend

```bash
cd frontend
npm install
npm run dev
```

Chat UI: [http://localhost:3000](http://localhost:3000)
Admin UI: [http://localhost:3000/admin](http://localhost:3000/admin)

---

### 7. Docker Compose (All-in-one)

```bash
# Copy and fill in the .env
cp backend/.env.example backend/.env
# Edit backend/.env with your keys

docker-compose up --build
```

- Chat UI: http://localhost:3000
- Backend API: http://localhost:8000
- Postgres: localhost:5432

---

## How to Ingest SOPs

### Option A — Upload via Admin UI

1. Go to `http://localhost:3000/admin`
2. Click **SOPs** tab
3. Click **Upload & Parse**
4. Select a PDF, DOCX, or DOC file
5. The system extracts text, sends it to the LLM for parsing, validates the output, and saves parsed JSON
6. Review the generated JSON in the **View JSON** button
7. When satisfied, click **Publish**

### Option B — Batch ingest from folder

1. Drop PDF/DOCX/DOC files into `data/sops/`
2. Run:
   ```bash
   python scripts/run_ingestion.py
   ```
3. Parsed JSON files appear in `data/parsed_sops/`
4. Publish via admin UI or API:
   ```bash
   curl -X POST http://localhost:8000/sops/<sop_id>/publish
   ```

### Option C — Seed pre-built JSON

```bash
python scripts/seed_data.py
```

---

## How to Test the Chatbot

1. Open `http://localhost:3000`
2. Type your issue or click a product button
3. Follow the bot's step-by-step instructions
4. Reply with the quick-reply buttons or type freely
5. Test keywords: "Done", "Not sure", "It failed", "I want to talk to a human"

**Dev mode debug panel** appears in the bottom-right corner showing current state, step, product, and SOP.

---

## How to Publish SOPs

Via admin UI:
- Admin → SOPs → click **Publish** on a draft SOP

Via API:
```bash
curl -X POST http://localhost:8000/sops/{sop_id_or_slug}/publish
```

Via API (unpublish):
```bash
curl -X POST http://localhost:8000/sops/{sop_id_or_slug}/unpublish
```

Only `published` SOPs are returned by search and used in conversations.

---

## How to View Conversations and Escalations

**Admin UI:**
- Admin → Conversations: lists all conversations with status and current step
- Admin → Escalations: lists all escalations with summaries and recommended actions
- Admin → Analytics: shows resolution rates, top products, top issues

**API:**
```bash
# Conversations
GET /admin/conversations
GET /admin/conversations/{id}/events
GET /chat/conversation/{id}

# Escalations
GET /escalations/
GET /escalations/{id}
PATCH /escalations/{id}/status?status=assigned

# Analytics
GET /analytics/summary
```

---

## How to Test Search

1. Admin UI → **Search Test** tab
2. Enter product text, issue text, and a customer message
3. View candidate SOPs with scores and match reasons

Or via API:
```bash
curl -X POST http://localhost:8000/sops/search \
  -H "Content-Type: application/json" \
  -d '{"product_text":"router","issue_text":"no internet","customer_message":"wifi stopped working"}'
```

---

## Running Tests

```bash
cd backend
pip install -r requirements.txt
pytest ../tests/ -v
```

Tests use SQLite (no Postgres needed) and mock all LLM/embedding calls.

---

## API Reference (Key Endpoints)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/chat/message` | Main chat endpoint |
| GET | `/chat/conversation/{id}` | Get conversation + events |
| GET | `/sops/` | List SOPs |
| GET | `/sops/{id}` | Get SOP details |
| POST | `/sops/upload` | Upload PDF/DOCX file |
| POST | `/sops/{id}/publish` | Publish SOP |
| POST | `/sops/search` | Test hybrid search |
| GET | `/escalations/` | List escalations |
| PATCH | `/escalations/{id}/status` | Update escalation status |
| GET | `/analytics/summary` | Analytics summary |
| GET | `/admin/conversations` | List conversations |
| GET | `/admin/products` | List products |
| POST | `/admin/products` | Create product |

Full interactive docs: `http://localhost:8000/docs`

---

## Conversation State Machine

```
NEW
 ↓
AWAITING_PRODUCT  ← asks "Which product?"
 ↓
AWAITING_ISSUE    ← asks "What's the issue?"
 ↓
CLARIFYING        ← asks one clarifying question
 ↓
SOP_SELECTED      ← confirms "I'll help with X for Y"
 ↓
RUNNING_STEP      ← sends step to customer
 ↓
WAITING_STEP_RESPONSE ← waits for customer reply
 ↓
RESOLVED          ← all steps completed
ESCALATED         ← failed, stuck, or customer asked for human
ABANDONED         ← timed out (future)
```

---

## SOP JSON Format

Each SOP is stored as structured JSON. Example step:

```json
{
  "id": "step_1",
  "type": "instruction",
  "customer_message": "Please restart your router by unplugging it for 30 seconds.",
  "agent_notes": "Power cycle resolves most connectivity issues.",
  "expected_responses": ["done", "yes", "not_sure", "failed"],
  "response_buttons": ["Done", "Not sure", "It failed"],
  "on_done": "step_2",
  "on_not_sure": "step_1_help",
  "on_failed": "escalate_1",
  "retry_limit": 1,
  "safety_note": ""
}
```

Step types: `instruction`, `question`, `check`, `decision`, `terminal`, `escalation`

Response labels (controlled): `yes`, `no`, `done`, `not_sure`, `failed`, `help_needed`, `wants_human`, `unrelated`, `other`

---

## Security Notes

- API keys are in `.env` only — never committed
- `.env.example` has no real values
- Input validated with Pydantic
- SOP JSON schema validated before storage
- LLM outputs are parsed as strict JSON; free-form text never reaches customers
- Debug panel only visible in `ENVIRONMENT=development`
- Rate limiting: placeholder ready — add slowapi or nginx rate limiting before production

---

## Known Limitations

1. **Embeddings on seed data**: Seed JSON SOPs loaded via `seed_data.py` do not have vector embeddings. Keyword search still works. Run ingestion pipeline for full embedding support.
2. **`.doc` files**: Require LibreOffice installed on the server. DOCX and PDF work natively.
3. **No auth**: Admin UI has no authentication. Add JWT or basic auth before exposing to internet.
4. **Single-tenant**: One Postgres DB. Multi-tenant isolation is a future improvement.
5. **LLM SOP parser accuracy**: Complex SOPs with nested tables or non-standard formatting may need manual review. Always review parsed JSON before publishing.
6. **Rate limiting**: Placeholder only — not enforced.

---

## Future Improvements

- [ ] Zoho Desk / Zendesk escalation integration
- [ ] WhatsApp / SMS channel via Twilio
- [ ] Auth for admin UI (JWT / SSO)
- [ ] SOP diff viewer (version comparison)
- [ ] A/B test different SOP flows
- [ ] Scheduled SOP review reminders
- [ ] Multi-language support (Hindi, Tamil, etc.)
- [ ] Confidence threshold tuning per product
- [ ] Customer satisfaction survey after resolution
- [ ] Agent takeover UI (live agent joins conversation)
- [ ] Webhook notifications on escalation
- [ ] SOP import from Google Docs / Confluence

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.11, FastAPI |
| ORM | SQLAlchemy 2.0 |
| Database | PostgreSQL 16 + pgvector |
| Embeddings | OpenAI text-embedding-3-small |
| LLM | OpenAI gpt-4o-mini (configurable) |
| PDF parsing | PyMuPDF / pdfplumber |
| DOCX parsing | python-docx |
| Frontend | React 18 + Vite |
| Containerisation | Docker Compose |
| Tests | pytest + SQLite |
