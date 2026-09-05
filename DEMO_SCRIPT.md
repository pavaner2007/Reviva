# Reviva — Demo Script (3 Minutes)

> **Hackathon: Razorpay Buildathon · Track 03 — AI Revenue Recovery**
> 
> Run this script exactly as written. Practice it twice before presenting.

---

## Pre-Demo Checklist

- [ ] Backend running: `uvicorn app.main:app --host 127.0.0.1 --port 8000`
- [ ] Frontend running: `npm run dev` (in `recovery-agent/frontend/`)
- [ ] Browser open at: **http://localhost:5173**
- [ ] Browser zoom: 100% (or 90% for smaller screens)
- [ ] No unrelated tabs open on the same browser window

---

## Current Demo Events (from live data)

> **These IDs are correct for the CURRENT database state.**
> After running `reset_and_verify.py`, new Payment Links are created.
> You MUST manually complete a test payment and update the "Recovered Event" below.

### ✅ Best Blocked Event (ready now)

| Field | Value |
|---|---|
| **Event ID** | **4** |
| **Customer** | Ananya Iyer |
| **Amount** | ₹4,999 |
| **Root Cause** | Insufficient Funds |
| **Strategy** | retry_in_48_hours |
| **Guardrail Reason** | `amount_exceeds_auto_recovery_ceiling` |
| **URL** | http://localhost:5173/case/4 |

### ✅ Best Executed Event (pending — complete a test payment to make it recovered)

| Field | Value |
|---|---|
| **Event ID** | **34** |
| **Customer** | Ramesh Naidu |
| **Amount** | ₹4,499 |
| **Root Cause** | OTP Verification Failed |
| **Strategy** | resend_checkout_link_now |
| **Razorpay Link** | https://rzp.io/rzp/S15G3jA |
| **URL** | http://localhost:5173/case/34 |

> **To create a recovered event for demo:**
> 1. Open https://rzp.io/rzp/S15G3jA in a browser tab
> 2. Pay with test card: `4111 1111 1111 1111`, any future expiry, CVV `123`
> 3. Or UPI: `success@razorpay`
> 4. Then call: `POST http://localhost:8000/pipeline/measure-one/34`
> 5. Verify `outcome=recovered` in the response
> 6. Reload http://localhost:5173/case/34

---

## Demo Timeline

### [0:00 – 0:20] The Problem

> *"Failed payments are silent revenue leaks. When a payment fails, merchants typically do nothing automated or send generic retry emails. Reviva changes this."*

> *"Reviva detects every failed payment, diagnoses why it failed, selects a targeted recovery strategy, runs it through 4 safety guardrails, executes a real Razorpay Payment Link, and then measures whether revenue was actually recovered — all automatically, all auditable."*

> *"The goal is not blind retries. The goal is safe, explainable, measurable recovery."*

---

### [0:20 – 0:50] Recovery Queue

**Action:** Open http://localhost:5173 (should already be open)

> *"This is the Recovery Queue. Every failed payment event is here — 58 total."*

> *"Each row shows the AI-classified root cause, the selected recovery strategy, the guardrail verdict, and the current outcome."*

**Action:** Click the **Blocked** filter tab.

> *"10 events are intentionally blocked. The system did not blindly execute on all of them."*

---

### [0:50 – 1:35] Blocked Case Detail (Event #4)

**Action:** Click on **Ananya Iyer** (₹4,999) — or navigate to http://localhost:5173/case/4

> *"Let me walk through the AI decision for this event."*

Point to the red RECOVERY BLOCKED banner:

> *"Failure: insufficient_funds. The AI classified this as Insufficient Funds. Strategy selected: retry in 48 hours — correct timing after a salary credit window."*

> *"But the system never executed it. Why? Look at the guardrail reason: `amount exceeds auto recovery ceiling`. ₹4,999 is above the ₹4,500 automatic execution limit. This transaction requires human authorization."*

> *"Scroll to the pipeline timeline."*

**Action:** Scroll to the timeline section.

> *"Detect, Root Cause, Strategy, Guardrail — all ran. Execute and Measure? Not reached. The system documented exactly why it stopped. This is explainability built into the pipeline."*

> *"Reviva doesn't just act on money. It knows when NOT to act."*

---

### [1:35 – 2:20] Recovered Case Detail

**Action:** Navigate to http://localhost:5173/case/34

> *"Now a successful recovery. Ramesh Naidu's OTP failed during checkout. The AI classified it as OTP Verification Failed."*

> *"Strategy: resend checkout link now — the fastest path to re-engage the customer."*

> *"Guardrail verdict: cleared. Amount is within limits, no cooldown, not escalated."*

**Action:** Point to the Razorpay Payment Link card.

> *"Phase 4 created a real Razorpay test-mode Payment Link. The customer receives this — they click, they pay."*

> *"Phase 5 then polls Razorpay's API to confirm the actual payment. Only when Razorpay confirms `status=paid` does the system mark this as recovered."*

**Action:** Point to outcome badge and recovered amount.

> *"Outcome: Recovered. ₹4,499 recovered. This came from Razorpay's API — not a hardcoded value."*

**Action:** Click **Refresh Status** to show the live measurement call.

> *"I can trigger a live status check right now. This calls the backend, which calls Razorpay, and updates the record in real time."*

---

### [2:20 – 2:50] Dashboard

**Action:** Click **Dashboard** in the top navigation.

> *"The dashboard shows the business impact — all from the real backend."*

Point to the hero metric:

> *"Total revenue recovered. Recovery rate. This updates every 10 seconds automatically."*

Scroll down to the root cause table:

> *"Every rupee recovered is tied to a specific root cause. We know not just how much we recovered — but why each failure happened and which strategy worked."*

---

### [2:50 – 3:00] Closing

> *"Every recovery decision in Reviva is bounded by guardrails, executed via a real Razorpay API, confirmed by live payment status, and fully auditable with timestamps. Nothing here acts on money without a logged and explainable reason."*

> *"Reviva: safe, measurable, explainable revenue recovery."*

---

## Backup: If Recovered Event Is Not Available

If the recovered event was reset or is still pending:

1. Use **Event #1** (Aarav Sharma) — has a full pipeline timeline through execute+measure
2. Show the Razorpay Payment Link and the pending status
3. Explain: *"This link is live in Razorpay test mode. A customer clicks it, pays, and Phase 5 automatically detects the recovery."*
4. Optionally complete a live test payment during the demo

---

## Screenshot Checklist

Before the hackathon, take these screenshots and save to `demo_assets/screenshots/`:

- [ ] `01_recovery_queue_all.png` — Recovery Queue, All filter, all events visible
- [ ] `02_recovery_queue_blocked.png` — Recovery Queue, Blocked filter
- [ ] `03_case_4_blocked.png` — Case Detail for Event #4 (RECOVERY BLOCKED banner)
- [ ] `04_case_4_timeline.png` — Case Detail Event #4, pipeline timeline scrolled down
- [ ] `05_case_34_recovered.png` — Case Detail for Event #34, recovered outcome + amount
- [ ] `06_case_34_timeline.png` — Case Detail Event #34, full timeline
- [ ] `07_dashboard_top.png` — Dashboard hero metrics
- [ ] `08_dashboard_root_cause.png` — Dashboard root cause breakdown table

---

## After Running `reset_and_verify.py`

After a clean reset, update this file with new event IDs:

1. Run `python -m app.reset_and_verify --yes`
2. Run `GET http://localhost:8000/pipeline/blocked` → pick the best blocked event (highest amount, clearest reason)
3. Open 3–4 Razorpay Payment Links from `GET http://localhost:8000/pipeline/executed`
4. Complete test payments (card `4111 1111 1111 1111` or UPI `success@razorpay`)
5. Run `POST http://localhost:8000/pipeline/run-phase5`
6. Run `GET http://localhost:8000/pipeline/outcomes` → pick best recovered event
7. Update the **Current Demo Events** section above with new IDs
