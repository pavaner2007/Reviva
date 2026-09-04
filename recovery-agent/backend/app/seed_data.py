"""
seed_data.py — Generates exactly 50 synthetic LossEvent records for Phase 1.

Usage (run from the backend/ directory):
    python -m app.seed_data
  or:
    python app/seed_data.py

Distribution:
    15 × insufficient_funds   (30 %)
    12 × card_expired         (24 %)
    10 × bank_timeout         (20 %)
     8 × otp_failed           (16 %)
     5 × unusual/ambiguous    (10 %)
   ────────────────────────────────
    50 total

Subscription split:
    30 records have a subscription_id
    20 records have subscription_id = NULL

Idempotency:
    Running this script more than once clears the existing LossEvent rows
    first, then inserts a fresh batch of 50.
"""
from __future__ import annotations

import os
import random
import string
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Make sure imports work whether the script is run as a module or directly
# ---------------------------------------------------------------------------
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Load .env before any app imports that might read env vars
from dotenv import load_dotenv  # noqa: E402

load_dotenv(dotenv_path=_BACKEND_DIR / ".env", override=False)

from app.database import create_session, init_db  # noqa: E402
from app.models import LossEvent  # noqa: E402

# ---------------------------------------------------------------------------
# Seed parameters
# ---------------------------------------------------------------------------
TOTAL_RECORDS = 50
SUBSCRIPTION_COUNT = 30  # exactly 30 with a subscription_id
ONE_OFF_COUNT = 20        # exactly 20 with NULL subscription_id

RANDOM_SEED = 42  # deterministic RNG for reproducibility

# ---------------------------------------------------------------------------
# Realistic Indian customer names
# ---------------------------------------------------------------------------
CUSTOMER_NAMES: list[str] = [
    "Aarav Sharma",
    "Priya Reddy",
    "Rahul Verma",
    "Ananya Iyer",
    "Vikram Patel",
    "Sneha Gupta",
    "Arjun Nair",
    "Divya Menon",
    "Rohit Joshi",
    "Kavya Pillai",
    "Karthik Rao",
    "Meera Bhat",
    "Siddharth Singh",
    "Pooja Agarwal",
    "Nikhil Desai",
    "Ishaan Malhotra",
    "Riya Krishnan",
    "Aditya Chaudhary",
    "Shreya Bose",
    "Manish Kumar",
    "Tanvi Shah",
    "Suresh Nair",
    "Deepa Sharma",
    "Abhishek Tiwari",
    "Lakshmi Subramanian",
    "Vishal Mehta",
    "Sunita Pandey",
    "Gaurav Saxena",
    "Neha Kapoor",
    "Rajesh Bhatt",
    "Anjali Srivastava",
    "Harish Gowda",
    "Preeti Mishra",
    "Ramesh Naidu",
    "Swati Kulkarni",
    "Varun Khanna",
    "Geeta Chakraborty",
    "Sanjay Yadav",
    "Pallavi Deshpande",
    "Manoj Tripathi",
    "Ritika Jain",
    "Dinesh Rajan",
    "Nandini Banerjee",
    "Ajay Hegde",
    "Shweta Choudhury",
    "Tarun Mathur",
    "Poornima Venkatesh",
    "Ravi Shankar",
    "Chitra Raghavan",
    "Bhavesh Solanki",
]

# Exactly 50 names, one per customer slot
assert len(CUSTOMER_NAMES) == TOTAL_RECORDS, "CUSTOMER_NAMES list must have exactly 50 entries"

# ---------------------------------------------------------------------------
# Failure-code distribution — deterministic order, not random.choice
# ---------------------------------------------------------------------------
FAILURE_CODES_ORDERED: list[str] = (
    ["insufficient_funds"] * 15
    + ["card_expired"] * 12
    + ["bank_timeout"] * 10
    + ["otp_failed"] * 8
    + [
        "3DS_AUTH_TIMEOUT",
        "unknown_gateway_error",
        "issuer_response_unclassified",
        "payment_processing_interrupted",
        "auth_error_unmapped",
    ]
)

assert len(FAILURE_CODES_ORDERED) == TOTAL_RECORDS

# ---------------------------------------------------------------------------
# Subscription-id presence — first 30 get a sub, last 20 get NULL
# ---------------------------------------------------------------------------
SUBSCRIPTION_PRESENT_FLAGS: list[bool] = (
    [True] * SUBSCRIPTION_COUNT + [False] * ONE_OFF_COUNT
)

assert len(SUBSCRIPTION_PRESENT_FLAGS) == TOTAL_RECORDS


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _random_alphanumeric(length: int, rng: random.Random) -> str:
    """Generate a random alphanumeric string of `length` characters."""
    chars = string.ascii_letters + string.digits
    return "".join(rng.choices(chars, k=length))


def _generate_order_id(rng: random.Random, existing: set[str]) -> str:
    """Generate a unique order_id in the format 'order_<alphanumeric>'."""
    while True:
        candidate = "order_" + _random_alphanumeric(10, rng)
        if candidate not in existing:
            existing.add(candidate)
            return candidate


def _generate_subscription_id(rng: random.Random) -> str:
    """Generate a realistic Razorpay-style subscription ID."""
    return "sub_" + _random_alphanumeric(14, rng)


def _generate_amount_paise(rng: random.Random) -> int:
    """
    Generate a realistic transaction amount in paise.

    Valid range: ₹99–₹4999 → 9900–499900 paise.
    Uses a weighted set of realistic price points to mimic SaaS/e-commerce
    pricing (₹99, ₹199, ₹299, ₹499, ₹999, ₹1499, ₹1999, ₹2499, ₹4999, etc.)
    """
    rupee_amounts: list[int] = [
        99, 149, 199, 249, 299, 349, 399, 449, 499,
        599, 699, 799, 899, 999,
        1199, 1299, 1499, 1699, 1999,
        2199, 2499, 2999,
        3499, 3999, 4499, 4999,
    ]
    rupees = rng.choice(rupee_amounts)
    paise = rupees * 100

    # Validate before returning — never float, always in range
    if not isinstance(paise, int):
        raise ValueError(f"Amount must be int, got {type(paise).__name__}: {paise}")
    if not (9900 <= paise <= 499900):
        raise ValueError(
            f"Amount {paise} paise is out of valid range [9900, 499900]"
        )
    return paise


def _random_created_at(rng: random.Random) -> datetime:
    """
    Return a UTC datetime in the past 7 days.
    Never returns a future timestamp.
    """
    now = datetime.now(timezone.utc)
    offset_seconds = rng.randint(0, 7 * 24 * 3600 - 1)
    return now - timedelta(seconds=offset_seconds)


# ---------------------------------------------------------------------------
# Core seeding logic
# ---------------------------------------------------------------------------

def seed(clear_existing: bool = True) -> None:
    """
    Seed exactly 50 LossEvent records into the database.

    If `clear_existing` is True (default) and records already exist,
    they are deleted before the new batch is inserted.
    """
    # Ensure tables exist
    init_db()

    db = create_session()
    try:
        # ── Idempotency guard ────────────────────────────────────────────
        existing_count: int = db.query(LossEvent).count()
        if existing_count > 0:
            print(
                "\n[WARNING] Existing LossEvent records found. "
                "Clearing existing synthetic data before reseeding."
            )
            db.query(LossEvent).delete()
            db.commit()
            print(f"   Deleted {existing_count} existing record(s).\n")

        # ── Data generation ──────────────────────────────────────────────
        rng = random.Random(RANDOM_SEED)

        # Shuffle the ordered lists so the distribution is preserved but
        # records are not in a predictable pattern (e.g. all insufficient_funds first)
        failure_codes = FAILURE_CODES_ORDERED.copy()
        sub_flags = SUBSCRIPTION_PRESENT_FLAGS.copy()
        rng.shuffle(failure_codes)
        rng.shuffle(sub_flags)

        existing_order_ids: set[str] = set()
        records: list[LossEvent] = []

        for i in range(TOTAL_RECORDS):
            order_id = _generate_order_id(rng, existing_order_ids)
            customer_id = f"CUST_{i + 1:04d}"
            customer_name = CUSTOMER_NAMES[i]
            amount = _generate_amount_paise(rng)
            failure_code = failure_codes[i]
            has_subscription = sub_flags[i]
            subscription_id = _generate_subscription_id(rng) if has_subscription else None
            created_at = _random_created_at(rng)

            event = LossEvent(
                order_id=order_id,
                subscription_id=subscription_id,
                customer_id=customer_id,
                customer_name=customer_name,
                amount=amount,
                failure_code=failure_code,
                status="failed",
                created_at=created_at,
            )
            records.append(event)

        db.add_all(records)
        db.commit()

        # ── Post-insert verification ─────────────────────────────────────
        _print_summary(db)

    finally:
        db.close()


def _print_summary(db) -> None:
    """Query the live database and print a seeding summary."""
    from collections import Counter

    events: list[LossEvent] = db.query(LossEvent).all()
    total = len(events)

    failure_counts: Counter = Counter(e.failure_code for e in events)
    subscription_count = sum(1 for e in events if e.subscription_id is not None)
    one_off_count = sum(1 for e in events if e.subscription_id is None)

    db_path = _BACKEND_DIR / "recovery_agent.db"

    print("=" * 40)
    print("SEEDING COMPLETE")
    print("=" * 40)
    print(f"\nTotal LossEvent records: {total}")
    print("\nFailure Code Breakdown:")
    for code, count in sorted(failure_counts.items(), key=lambda x: -x[1]):
        print(f"  {code}: {count}")
    print("\nPayment Type Breakdown:")
    print(f"  subscription: {subscription_count}")
    print(f"  one_off: {one_off_count}")
    print(f"\nDatabase: {db_path}")
    print("=" * 40)


# ---------------------------------------------------------------------------
# Script entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    seed()
