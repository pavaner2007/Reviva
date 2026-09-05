# Reviva — Failed Payment Recovery Agent

> **Razorpay Buildathon · Track 03 — AI Revenue Recovery**

Reviva automatically processes failed payment events through a fully explainable recovery loop. It does not blindly retry payments. Every recovery decision is bounded by configurable safety guardrails, executed via Razorpay test-mode Payment Links, and measured against real payment confirmation — producing auditable, measurable revenue recovery.

```
Detect → Analyze → Decide → Guardrail → Execute → Measure → Audit
```

---

## Architecture

```
Failed Payment Events (SQLite · LossEvent)
              ↓
    ┌─────────────────────┐
    │  Phase 2: Detection  │  detect_loss() validates status="failed"
    │  + Root Cause        │  rule-based classifier + Groq LLM fallback
    └─────────────────────┘
              ↓
    ┌─────────────────────┐
    │  Phase 3: Strategy   │  Deterministic root-cause → strategy map
    │  + Guardrails        │  4 safety rules evaluated before any action
    └─────────────────────┘
         ↓           ↓
    [Cleared]     [Blocked]  ← stored in PipelineRun.guardrail_passed
         ↓
    ┌─────────────────────┐
    │  Phase 4: Execute    │  Razorpay Payment Link creation (test-mode)
    │  (Razorpay API)      │  Dynamic descriptions via Groq LLM
    └─────────────────────┘
              ↓
    ┌─────────────────────┐
    │  Phase 5: Measure    │  Live Razorpay status polling
    │                      │  paid → recovered · created → pending
    └─────────────────────┘
              ↓
    ┌─────────────────────┐
    │  React Dashboard     │  Recovery Queue · Case Detail · Analytics
    └─────────────────────┘
              ↓
    AuditLog (every decision, every stage, timestamped)
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.11+, FastAPI, Uvicorn |
| **ORM & Database** | SQLAlchemy, SQLite |
| **AI / LLM** | Groq API (qwen-3.8-27b fallback classifier + payment description generator) |
| **Payments** | Razorpay Python SDK, Razorpay Test Mode |
| **Frontend** | React 18, Vite, Tailwind CSS v3, React Router v6 |
| **Environment** | python-dotenv |

---

## Local Setup

### Prerequisites
- Python 3.11+
- Node.js 18+
- Razorpay test-mode API keys
- Groq API key (optional — rules-only fallback works without it)

### 1. Backend

```bash
cd recovery-agent/backend

# Create virtual environment
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Activate (macOS/Linux)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

Create `.env` from the template:

```bash
copy .env.example .env     # Windows
cp .env.example .env       # macOS/Linux
```

Edit `.env`:

```env
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxx
RAZORPAY_KEY_SECRET=your_secret_here
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxx
GROQ_MODEL=qwen/qwen3.8-27b
GUARDRAIL_COOLDOWN_HOURS=12
```

Seed and run the full pipeline:

```bash
# Option A: automated reset + full pipeline verification
python -m app.reset_and_verify

# Option B: manual step-by-step
python -m app.seed_data
python -m app.pipeline.seed_guardrail_test_cases
```

Start the backend:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

API docs: http://localhost:8000/docs

### 2. Frontend

```bash
cd recovery-agent/frontend
npm install
npm run dev
```

Open: **http://localhost:5173**

---

## Safety Guardrails

All four rules are evaluated for every candidate event before any automated action is taken. No short-circuiting — all failing reasons are collected together.

| Rule | Reason Code | Why |
|---|---|---|
| **Maximum Attempts** | `max_attempts_exceeded` | Prevents repeated automated contact with the same customer |
| **Cooldown Window** | `cooldown_active` | Enforces a mandatory quiet period (default: 12 hours) between recovery attempts |
| **Human Escalation** | `escalated_not_auto_actionable` | Some failure types require human review and must never be auto-executed |
| **Amount Ceiling** | `amount_exceeds_auto_recovery_ceiling` | High-value transactions (> ₹4,500) require manual authorization before automated recovery |

Guardrail decisions are written to `PipelineRun.guardrail_passed` and `PipelineRun.guardrail_reason`, and audited in `AuditLog`.

---

## Recovery Strategies

| Root Cause | Strategy | Action |
|---|---|---|
| Card Expired | `send_update_payment_method_link` | Request customer to update card |
| Insufficient Funds | `retry_in_48_hours` | Retry after expected salary/top-up window |
| Bank/Network Timeout | `retry_immediately` | Immediate retry for transient failures |
| OTP Verification Failed | `resend_checkout_link_now` | Re-issue checkout link with fresh authentication |
| Issuer Declined | `escalate_to_human_review` | Escalate — never auto-execute |
| Unclassified | `escalate_to_human_review` | Escalate — requires manual investigation |

---

## Pipeline Verification

Run the full end-to-end verification from a clean state:

```bash
# Interactive (confirms before clearing DB)
python -m app.reset_and_verify

# Non-interactive (CI / demo prep)
python -m app.reset_and_verify --yes
```

The script:
1. Clears local DB (LossEvent, PipelineRun, AuditLog)
2. Seeds 50 synthetic failed payment records
3. Seeds guardrail boundary test cases
4. Runs Phase 2 (detection + root cause)
5. Runs Phase 3 (strategy + guardrails)
6. Runs Phase 4 (Razorpay payment link creation)
7. Runs Phase 5 (outcome measurement)
8. Prints a final analytics report

> **Note:** Razorpay Payment Links created in the Razorpay test dashboard are **not** deleted when the local DB is reset. They are external resources.

---

## Known Limitations

- **Notification delivery is simulated.** Recovery actions create Razorpay Payment Links and log audit records. Actual email or SMS delivery to customers is not implemented; this is a prototype.
- **Razorpay test-mode only.** All payment link creation and status checking uses Razorpay's test environment. No real money is moved.
- **Single-tenant prototype.** The system is designed for a single merchant. Multi-tenant isolation and authentication are not implemented.
- **Guardrail rules are simplified.** The four guardrail rules use deterministic thresholds suitable for a hackathon prototype. Production systems would require per-merchant configuration and ML-driven thresholds.
- **LLM fallback is best-effort.** When the Groq API is unavailable, ambiguous failure codes are classified as `Unclassified — Needs Review`. The pipeline does not crash.

---

## Project Structure

```
recovery-agent/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app + CORS + all endpoints
│   │   ├── database.py              # Engine, session, auto-migration
│   │   ├── models.py                # LossEvent, PipelineRun, AuditLog
│   │   ├── seed_data.py             # 50 synthetic events
│   │   ├── reset_and_verify.py      # Full pipeline verification script
│   │   └── pipeline/
│   │       ├── detect.py            # Phase 2: Loss detection
│   │       ├── root_cause.py        # Phase 2: Rule + LLM classifier
│   │       ├── strategy.py          # Phase 3: Strategy selection
│   │       ├── guardrails.py        # Phase 3: Safety guardrail rules
│   │       ├── execute.py           # Phase 4: Razorpay link creation
│   │       ├── measure.py           # Phase 5: Outcome measurement
│   │       ├── runner.py            # Pipeline orchestrator (all phases)
│   │       └── seed_guardrail_test_cases.py
│   ├── .env.example
│   └── requirements.txt
│
└── frontend/
    ├── src/
    │   ├── services/api.js          # Centralized API + data merge
    │   ├── components/              # Navigation, Badge, Loading, Error
    │   └── pages/
    │       ├── RecoveryQueue.jsx    # All events + filter tabs
    │       ├── CaseDetail.jsx       # Pipeline timeline + refresh
    │       └── Dashboard.jsx        # Live analytics + auto-refresh
    ├── package.json
    └── vite.config.js
```
