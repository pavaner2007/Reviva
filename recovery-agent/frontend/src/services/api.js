// services/api.js — Centralized API service for Reviva frontend
// All fetch calls go through this module. BASE_URL is the only place to change the host.

const BASE_URL = 'http://localhost:8000';

async function apiFetch(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`API error ${res.status} on ${path}: ${text}`);
  }
  return res.json();
}

export const getEvents = () => apiFetch('/events');
export const getPipelineResults = () => apiFetch('/pipeline/results');
export const getBlockedEvents = () => apiFetch('/pipeline/blocked');
export const getClearedEvents = () => apiFetch('/pipeline/cleared');
export const getOutcomes = () => apiFetch('/pipeline/outcomes');
export const getSummary = () => apiFetch('/pipeline/summary');
export const getAuditLog = (eventId) => apiFetch(`/audit-log/${eventId}`);
export const measureOne = (eventId) =>
  apiFetch(`/pipeline/measure-one/${eventId}`, { method: 'POST' });
export const executeOne = (eventId) =>
  apiFetch(`/pipeline/execute-one/${eventId}`, { method: 'POST' });

// ---------------------------------------------------------------------------
// Helper: merge all pipeline data keyed by event_id
// Returns a Map<eventId, mergedObject> built from all 5 sources
// ---------------------------------------------------------------------------
export async function fetchMergedQueue() {
  const [events, results, blocked, cleared, outcomes] = await Promise.all([
    getEvents(),
    getPipelineResults(),
    getBlockedEvents(),
    getClearedEvents(),
    getOutcomes(),
  ]);

  // Build base map from events (id is the primary key)
  const map = new Map();
  for (const e of events) {
    map.set(e.id, {
      event_id: e.id,
      order_id: e.order_id,
      customer_id: e.customer_id,
      customer_name: e.customer_name,
      amount: e.amount,
      failure_code: e.failure_code,
      status: e.status,
      created_at: e.created_at,
      subscription_id: e.subscription_id,
      // pipeline fields — filled below
      root_cause: null,
      root_cause_method: null,
      strategy: null,
      guardrail_passed: null,
      guardrail_reason: null,
      razorpay_link_id: null,
      razorpay_short_url: null,
      outcome: null,
      recovered_amount: null,
      updated_at: null,
    });
  }

  // Merge pipeline/results (root_cause, strategy from phase 2)
  for (const r of results) {
    const row = map.get(r.event_id);
    if (row) {
      row.root_cause = r.root_cause ?? row.root_cause;
      row.root_cause_method = r.root_cause_method ?? row.root_cause_method;
    }
  }

  // Merge blocked (guardrail_passed=false, guardrail_reason, strategy)
  for (const b of blocked) {
    const row = map.get(b.event_id);
    if (row) {
      row.guardrail_passed = false;
      row.guardrail_reason = b.guardrail_reason;
      row.strategy = b.strategy ?? row.strategy;
      row.root_cause = b.root_cause ?? row.root_cause;
    }
  }

  // Merge cleared (guardrail_passed=true, strategy)
  for (const c of cleared) {
    const row = map.get(c.event_id);
    if (row) {
      row.guardrail_passed = true;
      row.strategy = c.strategy ?? row.strategy;
      row.root_cause = c.root_cause ?? row.root_cause;
    }
  }

  // Merge outcomes (razorpay link, outcome, recovered_amount)
  for (const o of outcomes) {
    const row = map.get(o.event_id);
    if (row) {
      row.razorpay_link_id = o.razorpay_link_id;
      row.razorpay_short_url = o.razorpay_short_url;
      row.outcome = o.outcome;
      row.recovered_amount = o.recovered_amount;
      row.updated_at = o.updated_at;
      row.strategy = o.strategy ?? row.strategy;
      row.guardrail_passed = o.guardrail_passed ?? row.guardrail_passed;
      row.root_cause = o.root_cause ?? row.root_cause;
    }
  }

  return Array.from(map.values());
}

// ---------------------------------------------------------------------------
// Formatting helpers (shared across components)
// ---------------------------------------------------------------------------

/** Convert paise (integer) to ₹ display string. 169900 → "₹1,699" */
export function formatMoney(paise) {
  if (paise == null) return '—';
  const rupees = Math.floor(paise / 100);
  return '₹' + rupees.toLocaleString('en-IN');
}

/** Convert snake_case strategy to Title Case words */
export function formatStrategy(strategy) {
  if (!strategy) return '—';
  return strategy
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

/** Format ISO timestamp to readable date+time */
export function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}
