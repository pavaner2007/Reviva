# Reviva

An AI-powered failed payment recovery agent that detects payment failures, analyzes their root causes, and helps recover lost revenue intelligently.

---

## Features & Components

| Component | Description |
|---|---|
| **FastAPI Backend** | Clean modular architecture under `backend/app/` |
| **SQLite Database** | Auto-migrated schema with `LossEvent`, `PipelineRun`, and `AuditLog` models |
| **Synthetic Data Engine** | 50 realistic failed-payment records spanning common and ambiguous failure codes |
| **Detection Engine** | Detects loss events, validates fields, and logs audit events |
| **Root Cause Analysis** | Hybrid analyzer combining fast rule-based matching with Groq LLM fallback for edge cases |
| **Pipeline Runner & CLI** | Idempotent execution orchestrator with CLI and REST API interfaces |
| **Razorpay Health Check** | Direct test-mode connectivity and credential verification |

---

## Project Structure

```
recovery-agent/
│
├── backend/
│   ├── app/
│   │   ├── __init__.py          # Package marker
│   │   ├── main.py              # FastAPI app & REST endpoints
│   │   ├── database.py          # Database engine, session, and auto-migration
│   │   ├── models.py            # LossEvent, PipelineRun, AuditLog ORM models
│   │   ├── seed_data.py         # Synthetic data generator (50 records)
│   │   └── pipeline/
│   │       ├── __init__.py      # Pipeline package marker
│   │       ├── detect.py        # Loss event validation & detection
│   │       ├── root_cause.py    # Rule-based & Groq LLM root-cause analyzer
│   │       └── runner.py        # Pipeline orchestrator & CLI runner
│   │
│   ├── .env.example             # Environment variable template
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

# Groq LLM Configuration (Root Cause Analysis Fallback)
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GROQ_MODEL=qwen/qwen3.8-27b
```

> **Note:** The server starts normally even without API keys. Unconfigured services will report `not_configured` or fallback gracefully to offline handling.

### 5. Seed the database

Run from the `backend/` directory:

```bash
python -m app.seed_data
```

### 6. Run the Detection & Root Cause Analysis Pipeline

You can run the pipeline directly via CLI:

```bash
# Process all unanalyzed loss events
python -m app.pipeline.runner

# Reprocess all events (force update)
python -m app.pipeline.runner --force
```

### 7. Start the FastAPI server

```bash
uvicorn app.main:app --reload
```

The server starts at: **http://127.0.0.1:8000**

---

## API Reference

### Health & Events

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Server liveness check |
| `GET` | `/health/razorpay` | Razorpay credential verification |
| `GET` | `/events` | List all seeded loss events |
| `GET` | `/events/summary` | Aggregate statistics by failure code and payment type |

### Pipeline & Diagnostics

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/pipeline/run-phase2` | Trigger detection & root cause pipeline execution (`?force=true` optional) |
| `GET` | `/pipeline/results` | Retrieve all pipeline runs with root cause classifications |
| `GET` | `/audit-log/{event_id}` | Retrieve chronological audit trail for a specific event |

Interactive API documentation:
- **Swagger UI:** http://127.0.0.1:8000/docs
- **ReDoc:** http://127.0.0.1:8000/redoc

---

## Root Cause Analysis Classification

The hybrid analyzer categorizes failed payment events into standard failure categories:

- `insufficient_funds` &rarr; Customer account balance insufficient
- `card_expired` &rarr; Card validity expired
- `bank_timeout` &rarr; Issuer bank or network timed out
- `otp_failed` &rarr; 3DS / OTP authentication failed
- `issuer_declined` &rarr; Declined by issuing bank
- `fraud_risk` &rarr; Suspected fraud / high risk transaction

When encountering unmapped or free-text errors (e.g. `3DS_AUTH_TIMEOUT`, `auth_error_unmapped`), the system calls the Groq LLM with a strict JSON classification prompt to resolve the underlying root cause with confidence scoring and reasoning.
