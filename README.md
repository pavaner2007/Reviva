# Reviva — Autonomous Failed Payment Recovery Agent

> **Razorpay Buildathon · Track 03 — AI Revenue Recovery**

Reviva is an intelligent, explainable payment recovery system designed to combat transaction loss without blindly retrying failed charges. Built on a six-stage autonomous pipeline, Reviva evaluates failed payment events, identifies root causes using rule engines and LLM fallbacks, enforces strict multi-layered safety guardrails, generates dynamic Razorpay test-mode Payment Links, and measures recovery outcomes against live payment confirmation.

```
Detect ──▶ Analyze (Root Cause) ──▶ Decide (Strategy) ──▶ Guardrail ──▶ Execute (Razorpay) ──▶ Measure (Outcomes)
```

---

## Key Highlights

- **Intelligent Root Cause Analysis**: Classifies failures deterministically or falls back to Groq LLM (`qwen/qwen3.8-27b`) for unmapped gateway codes.
- **Strict Multi-Layer Safety Guardrails**: Evaluates customer attempt limits, quiet periods, escalation safety, and amount ceilings without short-circuiting.
- **Autonomous Razorpay Execution**: Generates real Razorpay test-mode Payment Links with AI-crafted contextual messages tailored to the specific failure.
- **Closed-Loop Outcome Measurement**: Live polling against Razorpay APIs tracks transitions (`paid` → **recovered**, `created` → **pending**, `expired`/`cancelled` → **not_recovered**).
- **Full-Featured React Dashboard**: Real-time Recovery Queue, Interactive Case Detail view with timeline and manual triggers, and Live KPI Analytics.
- **Complete Audit Trail**: Every decision, guardrail check, LLM output, and API call is immutably recorded with timestamps.

---

## System Architecture

```
                       ┌─────────────────────────────────────────┐
                       │  Failed Payment Events (SQLite DB)      │
                       └────────────────────┬────────────────────┘
                                            │
                                            ▼
                       ┌─────────────────────────────────────────┐
                       │  Stage 1 & 2: Detection & Root Cause    │
                       │  • detect_loss() checks status="failed" │
                       │  • Rule-based + Groq LLM fallback       │
                       └────────────────────┬────────────────────┘
                                            │
                                            ▼
                       ┌─────────────────────────────────────────┐
                       │  Stage 3: Strategy & Safety Guardrails  │
                       │  • Root cause ➔ Strategy mapping        │
                       │  • 4 Guardrail rules evaluated          │
                       └──────────────┬───────────────────┬──────┘
                                      │                   │
                            [Passed Guardrails]    [Blocked by Policy]
                                      │                   │
                                      ▼                   ▼
                       ┌──────────────────────┐    ┌─────────────────────┐
                       │  Stage 4: Execution  │    │  Marked 'Blocked'   │
                       │  • Razorpay API Link │    │  Logged to AuditLog │
                       │  • Dynamic AI desc   │    └─────────────────────┘
                       └──────────────┬───────┘
                                      │
                                      ▼
                       ┌─────────────────────────────────────────┐
                       │  Stage 5: Live Outcome Measurement      │
                       │  • Polls Razorpay Payment Link status   │
                       │  • Updates status to Recovered / Pending│
                       └────────────────────┬────────────────────┘
                                            │
                                            ▼
                       ┌─────────────────────────────────────────┐
                       │  Stage 6: React Dashboard & Audit Trail │
                       │  • Recovery Queue • Case Detail • Stats │
                       │  • Immutable AuditLog for every event   │
                       └─────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Backend Framework** | Python 3.11+, FastAPI, Uvicorn | High-performance RESTful API endpoints |
| **Database & ORM** | SQLAlchemy 2.0, SQLite | Type-safe ORM models & local persistence |
| **AI / LLM** | Groq API (`qwen/qwen3.8-27b`) | Fallback classification & contextual link descriptions |
| **Payment Gateway** | Razorpay Python SDK | Test-mode Payment Link creation and status polling |
| **Frontend UI** | React 18, Vite, Tailwind CSS v3 | Modern, responsive operator dashboard |
| **Icons & Routing** | Lucide React, React Router v6 | Rich iconography & single-page client routing |

---

## Safety Guardrails

Every candidate transaction must pass four safety guardrails before automated execution. **No short-circuiting** is performed — all failing reasons are aggregated to provide complete explainability.

| Guardrail Rule | Fail Reason Code | Threshold / Logic | Purpose |
|---|---|---|---|
| **Maximum Attempts** | `max_attempts_exceeded` | Customer has ≥ 3 prior cleared recovery runs | Prevents customer fatigue and spamming |
| **Cooldown Window** | `cooldown_active` | Prior cleared attempt within `GUARDRAIL_COOLDOWN_HOURS` (12h) | Enforces mandatory quiet period between contacts |
| **Human Escalation** | `escalated_not_auto_actionable` | Strategy is `escalate_to_human_review` | Flags issuer declines and fraud concerns for human review |
| **Amount Ceiling** | `amount_exceeds_auto_recovery_ceiling` | Transaction amount > ₹4,500 (450,000 paise) | Enforces manual authorization for high-value transactions |

---

## Root Cause & Recovery Strategy Matrix

| Failure Code | Root Cause Category | Recovery Strategy | Automated Action |
|---|---|---|---|
| `card_expired` | Card Expired | `send_update_payment_method_link` | Issues Payment Link with card update instructions |
| `insufficient_funds` | Insufficient Funds | `retry_in_48_hours` | Issues Payment Link timed for expected top-up window |
| `bank_timeout` | Bank/Network Timeout | `retry_immediately` | Issues immediate retry Payment Link for transient errors |
| `otp_failed` | OTP Verification Failed | `resend_checkout_link_now` | Re-issues fresh checkout link with new auth window |
| `issuer_declined` | Issuer Declined Transaction | `escalate_to_human_review` | **Blocked by Guardrail** — routed to human ops |
| Unrecognized Code | Unclassified — Needs Review | `escalate_to_human_review` | **Blocked by Guardrail** — routed to human ops |

---

## API Reference

### Health & Gateway
- `GET /health` — API server liveness check.
- `GET /health/razorpay` — Validates Razorpay API credentials and test connectivity.

### Events & Pipeline
- `GET /events` — Lists all seeded and detected `LossEvent` records.
- `GET /events/summary` — Returns live breakdown of events by failure code and subscription type.
- `POST /pipeline/run-phase2` — Executes detection and root-cause analysis (Rule engine + Groq LLM).
- `GET /pipeline/results` — Lists all pipeline runs joined with failure analysis.
- `POST /pipeline/run-phase3` — Determines recovery strategies and evaluates the 4 safety guardrails.
- `GET /pipeline/cleared` — Returns all events cleared for execution.
- `GET /pipeline/blocked` — Returns all events blocked with their failure reasons.
- `POST /seed/guardrail-test-cases` — Additive test case generator for guardrail boundary validation.

### Execution & Measurement
- `POST /pipeline/run-phase4` — Executes batch recovery via Razorpay Payment Links for cleared events.
- `POST /pipeline/execute-one/{event_id}` — Creates a Razorpay Payment Link for a single event in real time.
- `GET /pipeline/executed` — Lists all runs with active Razorpay Payment Links.
- `POST /pipeline/run-phase5` — Polls Razorpay API for live payment status across all active links.
- `POST /pipeline/measure-one/{event_id}` — Polls Razorpay API and updates outcome for a single event.
- `GET /pipeline/outcomes` — Lists all finalized outcomes (`recovered`, `pending`, `not_recovered`).
- `GET /pipeline/summary` — Returns real-time financial metrics (at-risk, recovered, recovery rate %, blocked value).
- `GET /audit-log/{event_id}` — Returns the complete, timestamped audit trail for a specific event.

---

## Local Setup & Quickstart

### Prerequisites
- **Python**: 3.11 or higher
- **Node.js**: 18 or higher (with npm)
- **Razorpay Account**: Key ID & Secret (Test Mode)
- **Groq API Key**: (Optional for LLM fallback & dynamic copy)

### 1. Backend Setup

```bash
cd recovery-agent/backend

# Create and activate virtual environment
python -m venv .venv

# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
# source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create environment configuration
copy .env.example .env     # Windows
# cp .env.example .env     # macOS/Linux
```

Configure your `.env` file:

```env
RAZORPAY_KEY_ID=rzp_test_your_key_id
RAZORPAY_KEY_SECRET=your_razorpay_secret
GROQ_API_KEY=gsk_your_groq_api_key
GROQ_MODEL=qwen/qwen3.8-27b
GUARDRAIL_COOLDOWN_HOURS=12
```

Initialize the database and run verification:

```bash
# Option A: Full automated database reset & pipeline execution
python -m app.reset_and_verify --yes

# Option B: Seed synthetic events only
python -m app.seed_data
```

Start the FastAPI backend server:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

- API Base URL: `http://localhost:8000`
- Interactive OpenAPI Docs: `http://localhost:8000/docs`

---

### 2. Frontend Setup

In a separate terminal window:

```bash
cd recovery-agent/frontend

# Install dependencies
npm install

# Start Vite dev server
npm run dev
```

Open your browser at: **`http://localhost:5173`**

---

## Frontend Walkthrough

1. **Recovery Queue (`/`)**:
   - Filter events by status tabs: **All**, **Actionable (Cleared)**, **Blocked (Guardrails)**, **In Recovery**, **Recovered**.
   - View customer name, amount in INR, failure reason, root cause, and guardrail decision badges.
   - Click any case to view its detailed timeline.

2. **Case Detail (`/case/:eventId`)**:
   - Step-by-step visual pipeline journey covering Detection, Analysis, Strategy, Guardrails, Execution, and Outcome.
   - Interactive action panel:
     - **Execute Recovery**: Creates a live Razorpay test Payment Link on demand.
     - **Check Payment Status**: Polls Razorpay for payment confirmation in real time.
   - Comprehensive audit log showing every system interaction and timestamp.

3. **Analytics Dashboard (`/dashboard`)**:
   - Financial KPI cards: Total At Risk, Eligible for Recovery, Total Recovered, Live Recovery Rate %, Guardrail Protected Value.
   - Breakdown of recovery rates grouped by payment failure root cause.

---

## Project Structure

```
Reviva/
├── recovery-agent/
│   ├── backend/
│   │   ├── app/
│   │   │   ├── main.py                     # FastAPI application & route controllers
│   │   │   ├── database.py                 # SQLAlchemy engine & session management
│   │   │   ├── models.py                   # LossEvent, PipelineRun, AuditLog ORM models
│   │   │   ├── seed_data.py                # Synthetic failed payment dataset generator
│   │   │   ├── reset_and_verify.py         # End-to-end pipeline verification runner
│   │   │   └── pipeline/
│   │   │       ├── detect.py               # Phase 1: Loss detection logic
│   │   │       ├── root_cause.py           # Phase 2: Rule + Groq LLM classification
│   │   │       ├── strategy.py             # Phase 3: Recovery strategy selection
│   │   │       ├── guardrails.py           # Phase 3: 4 deterministic safety guardrails
│   │   │       ├── execute.py              # Phase 4: Razorpay Payment Link execution
│   │   │       ├── measure.py              # Phase 5: Live payment outcome measurement
│   │   │       ├── runner.py               # Pipeline orchestrator
│   │   │       └── seed_guardrail_test_cases.py  # Guardrail boundary test seeder
│   │   ├── .env.example                    # Environment variable template
│   │   └── requirements.txt                # Python backend dependencies
│   │
│   └── frontend/
│       ├── src/
│       │   ├── App.jsx                     # Router & layout entry point
│       │   ├── main.jsx                    # React root mount
│       │   ├── index.css                   # Tailwind styles and theme tokens
│       │   ├── services/
│       │   │   └── api.js                  # Centralized backend API client
│       │   ├── components/
│       │   │   ├── Navigation.jsx          # Top navigation bar
│       │   │   └── Badge.jsx               # Status & outcome badge indicators
│       │   └── pages/
│       │       ├── RecoveryQueue.jsx       # Event management & filtering
│       │       ├── CaseDetail.jsx          # Detailed pipeline timeline & actions
│       │       └── Dashboard.jsx           # Real-time recovery analytics
│       ├── package.json                    # Node dependencies & scripts
│       ├── vite.config.js                  # Vite configuration
│       └── tailwind.config.js              # Tailwind CSS configuration
│
├── LICENSE                                 # MIT License
└── README.md                               # Project documentation
```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
