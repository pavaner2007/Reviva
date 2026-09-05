# Reviva

An AI-powered failed payment recovery agent that detects payment failures, analyzes root causes with hybrid rule/LLM classification, determines targeted recovery strategies, enforces safety guardrails, and autonomously executes recovery actions via the Razorpay API.

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
| **Razorpay Health Check** | Direct test-mode connectivity and credential verification |

---

## Project Structure

```
recovery-agent/
│
├── backend/
│   ├── app/
│   │   ├── __init__.py                  # Package marker
│   │   ├── main.py                      # FastAPI app & REST endpoints
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
│   │       ├── runner.py                # Pipeline orchestrator & CLI runner
│   │       └── seed_guardrail_test_cases.py # Boundary test case seeder
│   │
│   ├── .env.example                     # Environment variable template
│   ├── .gitignore
│   └── requirements.txt
│
└── README.md
```

---

## Setup Instructions

### 1. Navigate to the backend directory

```bash
cd recovery-agent/backend
```

### 2. Create and activate a Python virtual environment

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

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

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

> **Note:** The server starts normally even without third-party API keys. Unconfigured services report `not_configured` or fallback gracefully to offline handling.

### 5. Seed the database

Populate the database with initial failed payment loss events:

```bash
python -m app.seed_data
```

Optionally seed dedicated guardrail boundary test cases:

```bash
python -m app.pipeline.seed_guardrail_test_cases
```

### 6. Run the Pipeline via CLI

You can run the pipeline directly from the command line:

```bash
# Process unanalyzed loss events (detection + root-cause classification)
python -m app.pipeline.runner

# Reprocess all events (force update)
python -m app.pipeline.runner --force
```

### 7. Start the FastAPI Server

```bash
uvicorn app.main:app --reload
```

The server starts at: **http://127.0.0.1:8000**

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
| `POST` | `/pipeline/run-phase4` | Execute automated recovery actions for all cleared pipeline runs (`?force=true` optional) |
| `GET` | `/pipeline/executed` | List all pipeline runs with generated Razorpay Payment Links and execution details |
| `POST` | `/pipeline/execute-one/{event_id}` | Demo endpoint to execute recovery for a single event with strict safety validation |

Interactive API documentation:
- **Swagger UI:** http://127.0.0.1:8000/docs
- **ReDoc:** http://127.0.0.1:8000/redoc

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

1. **Maximum Attempts Exceeded (`max_attempts_exceeded`)**:
   Prevents spamming customers. Blocks recovery if prior failed recovery attempts exceed threshold.
2. **Cooldown Period Active (`cooldown_active`)**:
   Enforces a mandatory quiet period (configurable via `GUARDRAIL_COOLDOWN_HOURS`, default 12h) since the last contact attempt.
3. **Amount Ceiling Exceeded (`amount_exceeds_auto_recovery_ceiling`)**:
   Transactions exceeding the safety threshold (₹4,500 / 450,000 paise) are blocked from automated execution to prevent unintended high-value transfers.
4. **Escalation Review Required (`escalated_not_auto_actionable`)**:
   Events marked for human review (`escalate_to_human_review`) are blocked from automated execution to prevent unauthorized customer outreach.

---

## Automated Recovery Execution & Razorpay Integration

When an event passes all safety guardrails, the recovery engine autonomously initiates recovery:

### 4-Layer Safety Gates
1. **Guardrail Gate**: Ensures `guardrail_passed is True`. Blocked events are strictly rejected.
2. **Strategy Gate**: Blocks human-escalated events (`escalate_to_human_review`).
3. **Whitelist Gate**: Confirms the strategy is in the executable recovery whitelist.
4. **Idempotency Gate**: Re-execution is safely skipped if a valid `razorpay_link_id` already exists.

### Recovery Execution Flow
- **Razorpay Payment Link Creation**: Calls `razorpay_client.payment_link.create()` with customer details, order reference, currency, amount, and automatic SMS/email notification flags.
- **Dynamic Descriptions**: Uses Groq LLM to generate empathetic, customer-friendly payment notes tailored to the root cause (with robust deterministic fallbacks).
- **Intelligent Scheduling**: Strategies like `retry_in_48_hours` automatically compute and record `scheduled_for` timestamps.
- **Audit Logging**: Every execution attempt, whether successful, skipped, or failed, records a permanent audit log entry.
