# Reviva

An AI-powered failed payment recovery agent that detects payment failures, analyzes root causes with hybrid rule/LLM classification, determines targeted recovery strategies, enforces safety guardrails, autonomously executes recovery actions via the Razorpay API, measures real payment outcomes in real time, and presents everything in a premium React dashboard.

---

## Features & Components

| Component | Description |
|---|---|
| **FastAPI Backend** | Modular REST API service under `backend/app/` with automatic database migration |
| **SQLite Database** | Auto-migrated schema with `LossEvent`, `PipelineRun`, and `AuditLog` ORM models |
| **Synthetic Data Engine** | Realistic failed-payment records spanning common and ambiguous failure codes |
| **Detection Engine** | Detects loss events, validates payload integrity, and logs audit events |
| **Root Cause Analysis** | Hybrid analyzer combining deterministic rule matching with Groq LLM fallback for edge cases |
| **Strategy Selection** | Deterministic recovery strategy selection mapped directly to classified root causes |
| **Guardrails Engine** | Multi-rule safety evaluation preventing over-contacting, enforcing cooldowns, and bounding recovery amounts |
| **Guardrail Boundary Tests** | Dedicated test-case seeder covering all guardrail safety rules |
| **Automated Recovery Execution** | Real-time creation of Razorpay Payment Links with customer notification preferences |
| **Dynamic Payment Descriptions** | Context-aware payment link descriptions generated via Groq LLM with deterministic fallbacks |
| **Execution Safety Gates** | 4-layer validation preventing un-cleared, duplicate, or human-escalated link creation |
| **Payment Outcome Measurement** | Live Razorpay status polling that maps payment link status to `recovered`, `pending`, or `not_recovered` |
| **Recovery Analytics Summary** | Live computation of 8 financial metrics including recovery rate, at-risk amounts, and per-root-cause breakdowns |
| **React Frontend Dashboard** | Premium fintech-style UI with Recovery Queue, Case Detail pipeline timeline, and live analytics dashboard |
| **Razorpay Health Check** | Direct test-mode connectivity and credential verification |

---

## Project Structure

```
recovery-agent/
│
├── backend/
│   ├── app/
│   │   ├── __init__.py                  # Package marker
│   │   ├── main.py                      # FastAPI app, REST endpoints & CORS middleware
│   │   ├── database.py                  # Database engine, session, and auto-migration
│   │   ├── models.py                    # LossEvent, PipelineRun, AuditLog ORM models
│   │   ├── seed_data.py                 # Synthetic data generator
│   │   └── pipeline/
│   │       ├── __init__.py              # Pipeline package marker
│   │       ├── detect.py                # Loss event validation & detection
│   │       ├── root_cause.py            # Rule-based & Groq LLM root-cause analyzer
│   │       ├── strategy.py              # Root cause to recovery strategy mapping
│   │       ├── guardrails.py            # Safety guardrail rules & policy checks
│   │       ├── execute.py               # Automated action execution & Razorpay link creation
│   │       ├── measure.py               # Payment outcome measurement & recovery analytics
│   │       ├── runner.py                # Pipeline orchestrator & CLI runner
│   │       └── seed_guardrail_test_cases.py # Boundary test case seeder
│   │
│   ├── .env.example                     # Environment variable template
│   ├── .gitignore
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── App.jsx                      # Root app with BrowserRouter & routes
│   │   ├── main.jsx                     # React entry point
│   │   ├── index.css                    # Tailwind CSS + Inter font + global utilities
│   │   ├── services/
│   │   │   └── api.js                   # Centralized API service & fetchMergedQueue()
│   │   ├── components/
│   │   │   ├── Navigation.jsx           # Top navigation bar
│   │   │   ├── StatusBadge.jsx          # Colored status badge (Cleared/Blocked/Recovered/Pending)
│   │   │   ├── Loading.jsx              # Loading spinner
│   │   │   └── ErrorMessage.jsx         # Error display card
│   │   └── pages/
│   │       ├── RecoveryQueue.jsx        # Page 1: All events with filter tabs
│   │       ├── CaseDetail.jsx           # Page 2: Pipeline journey & case inspection
│   │       └── Dashboard.jsx            # Page 3: Live recovery analytics
│   │
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   └── postcss.config.js
│
└── README.md
```

---

## Setup Instructions

### Backend

#### 1. Navigate to the backend directory

```bash
cd recovery-agent/backend
```

#### 2. Create and activate a Python virtual environment

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

#### 3. Install dependencies

```bash
pip install -r requirements.txt
```

#### 4. Configure Environment Variables

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

Edit `.env` with your API credentials:

```env
# Razorpay Test Credentials
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxxxxxx
RAZORPAY_KEY_SECRET=your_razorpay_secret_here

# Groq LLM Configuration (Root Cause Analysis & Dynamic Messaging)
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GROQ_MODEL=qwen/qwen3.8-27b

# Recovery Guardrails Configuration
GUARDRAIL_COOLDOWN_HOURS=12
```

> **Note:** The server starts normally even without third-party API keys. Unconfigured services report `not_configured` or fallback gracefully.

#### 5. Seed the database

```bash
python -m app.seed_data
python -m app.pipeline.seed_guardrail_test_cases   # optional guardrail test cases
```

#### 6. Start the FastAPI server

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Backend runs at: **http://localhost:8000**

---

### Frontend

#### 1. Navigate to the frontend directory

```bash
cd recovery-agent/frontend
```

#### 2. Install dependencies

```bash
npm install
```

#### 3. Start the development server

```bash
npm run dev
```

Frontend runs at: **http://localhost:5173**

> **Note:** Both the backend and frontend must be running simultaneously for the UI to work.

---

## API Reference

### Health & Event Data

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Server liveness check |
| `GET` | `/health/razorpay` | Razorpay credential & test connection verification |
| `GET` | `/events` | List all recorded loss events |
| `GET` | `/events/summary` | Aggregate statistics by failure code and payment type |

### Detection & Root Cause Analysis

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/pipeline/run-phase2` | Execute detection and root-cause classification (`?force=true` optional) |
| `GET` | `/pipeline/results` | List pipeline runs with root-cause classifications joined with loss events |
| `GET` | `/audit-log/{event_id}` | Chronological audit trail for a specific event |

### Strategy Selection & Safety Guardrails

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/pipeline/run-phase3` | Execute strategy selection and guardrail evaluation (`?force=true` optional) |
| `GET` | `/pipeline/cleared` | List all pipeline runs that passed all guardrails (eligible for recovery) |
| `GET` | `/pipeline/blocked` | List all pipeline runs blocked by guardrails with reason details |
| `POST` | `/seed/guardrail-test-cases` | Seed idempotent test cases covering all guardrail boundary scenarios |

### Automated Recovery Execution

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/pipeline/run-phase4` | Execute automated recovery actions for all cleared pipeline runs |
| `GET` | `/pipeline/executed` | List all pipeline runs with generated Razorpay Payment Links |
| `POST` | `/pipeline/execute-one/{event_id}` | Demo endpoint to execute recovery for a single event |

### Payment Outcome Measurement & Analytics

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/pipeline/run-phase5` | Fetch live Razorpay status for all executed payment links and update outcomes |
| `GET` | `/pipeline/summary` | Live recovery analytics summary (8 financial metrics) |
| `GET` | `/pipeline/outcomes` | All pipeline runs with a non-null outcome, sorted by `updated_at DESC` |
| `POST` | `/pipeline/measure-one/{event_id}` | Demo endpoint to measure a single event's payment outcome in real time |

Interactive API documentation:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

---

## Frontend Pages

### Recovery Queue (`/`)
The default landing page. Displays all failed payment events in a professional fintech-style table.

- **All events** — merged from 5 backend endpoints into one unified view
- **Filter tabs** — All / Blocked / Cleared / Recovered / Pending (client-side, instant)
- **Status badges** — color-coded guardrail and outcome indicators
- **Row click** — navigates to Case Detail for that event

### Case Detail (`/case/:eventId`)
The most important page for the demo — shows the complete AI recovery pipeline journey for a single event.

- **Header** — Order ID, customer name, amount, current outcome
- **Info cards** — Failure Code, Root Cause, Strategy
- **Guardrail block warning** — prominent red panel when guardrail prevented execution
- **Razorpay Payment Link** — clickable link opening in a new tab
- **Refresh Status** — calls `POST /pipeline/measure-one/{id}` live to detect real payments
- **Pipeline Timeline** — vertical journey: Detect → Root Cause → Strategy → Guardrail → Execute → Measure

### Dashboard (`/dashboard`)
Live recovery analytics powered entirely by `GET /pipeline/summary`.

- **Hero metric** — Total Revenue Recovered (most prominent)
- **Recovery Rate** — percentage of at-risk revenue recovered
- **Secondary cards** — eligible at-risk, guardrail-blocked value, total executed, pending count
- **Outcome breakdown** — Recovered / Pending / Not Recovered counts
- **Root cause table** — all 6 categories with attempted count, recovered count, recovered amount, and progress bar
- **Auto-refresh** — every 10 seconds with live timestamp indicator

---

## Root Cause Analysis

The root cause analyzer categorizes failed payment events into standard categories:

1. **Card Expired**: Card validity expired.
2. **Insufficient Funds**: Customer account balance insufficient.
3. **Bank/Network Timeout**: Issuer bank or payment gateway network timeout.
4. **OTP Verification Failed**: 3DS / OTP authentication failed or expired.
5. **Issuer Declined Transaction**: Explicit decline from the customer's bank.
6. **Unclassified — Needs Review**: Ambiguous failure needing manual investigation.

When encountering unmapped or free-text errors (e.g. `3DS_AUTH_TIMEOUT`, `auth_error_unmapped`), the system calls the Groq LLM with a strict JSON classification prompt to resolve the underlying root cause with confidence scoring and reasoning.

---

## Recovery Strategy Selection

Each classified root cause is mapped to a tailored recovery strategy:

| Classified Root Cause | Selected Recovery Strategy | Action |
|---|---|---|
| **Card Expired** | `send_update_payment_method_link` | Prompt customer to update expired card details |
| **Insufficient Funds** | `retry_in_48_hours` | Schedule intelligent retry after salary/balance window |
| **Bank/Network Timeout** | `retry_immediately` | Immediate retry to capture transient network recovery |
| **OTP Verification Failed** | `resend_checkout_link_now` | Re-issue checkout/payment link with fresh authentication |
| **Issuer Declined Transaction** | `escalate_to_human_review` | Flag for account manager or support intervention |
| **Unclassified — Needs Review** | `escalate_to_human_review` | Require manual review before taking action |

---

## Safety Guardrails

Before any automated recovery action can be executed, every candidate transaction must pass four strict guardrail checks (evaluated without short-circuiting):

1. **Maximum Attempts Exceeded (`max_attempts_exceeded`)**: Prevents spamming customers.
2. **Cooldown Period Active (`cooldown_active`)**: Enforces a mandatory quiet period (configurable via `GUARDRAIL_COOLDOWN_HOURS`, default 12h).
3. **Amount Ceiling Exceeded (`amount_exceeds_auto_recovery_ceiling`)**: Transactions above ₹4,500 (450,000 paise) are blocked.
4. **Escalation Review Required (`escalated_not_auto_actionable`)**: Human-escalated events are never auto-executed.

---

## Automated Recovery Execution & Razorpay Integration

### 4-Layer Safety Gates
1. **Guardrail Gate**: Ensures `guardrail_passed is True`.
2. **Strategy Gate**: Blocks human-escalated events.
3. **Whitelist Gate**: Confirms the strategy is in the executable recovery whitelist.
4. **Idempotency Gate**: Skips if `razorpay_link_id` already exists.

### Recovery Execution Flow
- **Razorpay Payment Link Creation** via `razorpay_client.payment_link.create()`
- **Dynamic Descriptions** via Groq LLM (with deterministic fallback)
- **Intelligent Scheduling** for `retry_in_48_hours` strategies
- **Audit Logging** for every execution attempt

---

## Payment Outcome Measurement

### Status Mapping

| Razorpay Status | Outcome |
|---|---|
| `paid` | `recovered` |
| `cancelled` | `not_recovered` |
| `expired` | `not_recovered` |
| `created` | `pending` |
| unknown | `pending` (with audit log warning) |

### Key Guarantees

- **No fake recoveries**: Outcome is only set to `recovered` when Razorpay confirms payment.
- **No double-counting**: `total_recovered_amount` is always `SUM(recovered_amount WHERE outcome="recovered")` from live DB state.
- **API failure safety**: Previously confirmed `recovered` outcomes are never overwritten on API failure.
- **Always fresh**: Phase 5 always re-fetches Razorpay — never skips based on existing outcome.

### Recovery Analytics (`GET /pipeline/summary`)

| Metric | Description |
|---|---|
| `total_executed_events` | Runs with a valid Razorpay Payment Link |
| `total_at_risk_amount` | Sum of `event.amount` for executed runs (paise) |
| `eligible_at_risk_amount` | Sum of `event.amount` for guardrail-cleared runs (paise) |
| `total_recovered_amount` | Sum of `recovered_amount` where `outcome="recovered"` (paise) |
| `recovery_rate` | `(total_recovered / total_at_risk) × 100` (%) |
| `recovered_count` | Number of confirmed recovered events |
| `pending_count` | Number of pending (unpaid) events |
| `not_recovered_count` | Number of cancelled or expired links |
| `guardrail_blocked_value` | Sum of `event.amount` blocked by guardrails (paise) |
| `by_root_cause` | Per-root-cause breakdown: `attempted_count`, `recovered_count`, `recovered_amount` |
