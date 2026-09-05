// pages/CaseDetail.jsx — Page 2: Full pipeline journey for one event
import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  fetchMergedQueue,
  getAuditLog,
  measureOne,
  formatMoney,
  formatStrategy,
  formatDate,
} from '../services/api';
import StatusBadge from '../components/StatusBadge';
import Loading from '../components/Loading';
import ErrorMessage from '../components/ErrorMessage';

// Pipeline stages in display order
const STAGES = [
  { key: 'detect',     label: 'Detect',     icon: '🔍' },
  { key: 'root_cause', label: 'Root Cause',  icon: '🧠' },
  { key: 'strategy',   label: 'Strategy',    icon: '🎯' },
  { key: 'guardrail',  label: 'Guardrail',   icon: '🛡️' },
  { key: 'execute',    label: 'Execute',     icon: '⚡' },
  { key: 'measure',    label: 'Measure',     icon: '📊' },
];

function InfoCard({ label, value, mono = false }) {
  return (
    <div className="card p-4">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">{label}</p>
      <p className={`text-sm font-medium text-gray-900 ${mono ? 'font-mono' : ''}`}>
        {value ?? <span className="text-gray-400 italic">—</span>}
      </p>
    </div>
  );
}

function OutcomeBadge({ outcome }) {
  if (!outcome) return <StatusBadge variant="neutral" label="Not executed" />;
  if (outcome === 'recovered') return <StatusBadge variant="recovered" label="Recovered" />;
  if (outcome === 'pending') return <StatusBadge variant="pending" label="Pending" />;
  if (outcome === 'not_recovered') return <StatusBadge variant="not_recovered" label="Not Recovered" />;
  return <StatusBadge variant="neutral" label={outcome} />;
}

export default function CaseDetail() {
  const { eventId } = useParams();
  const navigate = useNavigate();
  const id = parseInt(eventId, 10);

  const [row, setRow] = useState(null);
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState(null);

  const loadData = useCallback(async () => {
    try {
      const [allRows, auditLogs] = await Promise.all([
        fetchMergedQueue(),
        getAuditLog(id),
      ]);
      const found = allRows.find((r) => r.event_id === id);
      if (!found) throw new Error(`Event ID ${id} not found.`);
      setRow(found);
      setLogs(auditLogs);
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, [id]);

  useEffect(() => {
    setLoading(true);
    loadData().finally(() => setLoading(false));
  }, [loadData]);

  const handleRefresh = async () => {
    setRefreshing(true);
    setRefreshMsg('Refreshing payment status…');
    try {
      await measureOne(id);
      await loadData();
      setRefreshMsg('Status refreshed successfully.');
    } catch (e) {
      setRefreshMsg(`Refresh failed: ${e.message}`);
    } finally {
      setRefreshing(false);
      setTimeout(() => setRefreshMsg(null), 4000);
    }
  };

  // Build stage map from audit logs (latest entry per stage key)
  const stageMap = {};
  for (const log of logs) {
    stageMap[log.stage] = log; // later entries overwrite earlier — we want latest
  }

  if (loading) return <Loading message="Loading case details…" />;
  if (error) return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      <button onClick={() => navigate('/')} className="btn-secondary mb-4">← Back to Queue</button>
      <ErrorMessage message={error} />
    </div>
  );

  const isBlocked = row.guardrail_passed === false;
  const isExecuted = Boolean(row.razorpay_link_id);
  const isRecovered = row.outcome === 'recovered';

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      {/* Back button */}
      <button onClick={() => navigate('/')} className="btn-secondary mb-6">
        ← Back to Queue
      </button>

      {/* ── HEADER CARD ─────────────────────────────────────────────────── */}
      <div className="card p-6 mb-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <span className="font-mono text-sm bg-gray-100 text-gray-600 px-3 py-1 rounded-lg">
                {row.order_id}
              </span>
              <OutcomeBadge outcome={row.outcome} />
            </div>
            <h1 className="text-2xl font-bold text-gray-900">{row.customer_name}</h1>
            <p className="text-gray-500 text-sm mt-1">{row.customer_id}</p>
          </div>
          <div className="text-right">
            <p className="text-xs text-gray-400 font-medium uppercase tracking-wide">Amount</p>
            <p className="text-3xl font-extrabold text-gray-900">{formatMoney(row.amount)}</p>
            {isRecovered && (
              <p className="text-sm text-green-600 font-semibold mt-1">
                ✓ {formatMoney(row.recovered_amount)} recovered
              </p>
            )}
          </div>
        </div>
      </div>

      {/* ── INFO GRID ───────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-6">
        <InfoCard label="Failure Code" value={row.failure_code} mono />
        <InfoCard label="Root Cause" value={row.root_cause ?? 'Not processed yet'} />
        <InfoCard label="Strategy" value={formatStrategy(row.strategy)} />
      </div>

      {/* ── GUARDRAIL BLOCK WARNING ──────────────────────────────────────── */}
      {isBlocked && (
        <div className="mb-6 rounded-xl border border-red-200 bg-red-50 p-5">
          <div className="flex items-start gap-3">
            <div className="flex-shrink-0 w-9 h-9 bg-red-100 rounded-full flex items-center justify-center text-lg">
              🛡️
            </div>
            <div>
              <p className="font-bold text-red-900 text-base">RECOVERY BLOCKED</p>
              <p className="text-red-700 text-sm mt-1">
                The safety guardrail intentionally prevented automatic recovery execution.
              </p>
              <div className="mt-3 inline-flex items-center gap-2 bg-red-100 rounded-lg px-3 py-1.5">
                <span className="text-xs text-red-500 font-medium uppercase tracking-wide">Reason</span>
                <span className="font-mono text-sm font-semibold text-red-800">
                  {row.guardrail_reason?.replace(/_/g, ' ') ?? 'blocked'}
                </span>
              </div>
              <p className="text-red-500 text-xs mt-2">
                This event requires manual review and cannot be auto-recovered.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* ── PAYMENT LINK CARD ───────────────────────────────────────────── */}
      {isExecuted && (
        <div className="card p-5 mb-6 border-blue-100 bg-blue-50/30">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div>
              <p className="text-xs font-semibold text-blue-400 uppercase tracking-wide mb-1">Razorpay Payment Link</p>
              <p className="font-mono text-sm text-gray-700">{row.razorpay_link_id}</p>
            </div>
            <a
              href={row.razorpay_short_url}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-primary"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
              </svg>
              Open Payment Link
            </a>
          </div>
          {row.razorpay_short_url && (
            <p className="text-xs text-blue-500 mt-2 font-mono">{row.razorpay_short_url}</p>
          )}
        </div>
      )}

      {/* ── REFRESH STATUS BUTTON ────────────────────────────────────────── */}
      {isExecuted && (
        <div className="mb-6 flex items-center gap-4">
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="btn-primary"
          >
            {refreshing ? (
              <>
                <div className="w-3 h-3 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                Refreshing…
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99" />
                </svg>
                Refresh Status
              </>
            )}
          </button>
          {refreshMsg && (
            <span className={`text-sm font-medium ${refreshMsg.startsWith('Refresh failed') ? 'text-red-600' : 'text-green-600'}`}>
              {refreshMsg}
            </span>
          )}
        </div>
      )}

      {/* ── PIPELINE TIMELINE ────────────────────────────────────────────── */}
      <div className="card p-6">
        <h2 className="text-base font-bold text-gray-900 mb-6">Pipeline Journey</h2>
        <div className="relative">
          {/* Vertical connector line */}
          <div className="absolute left-[19px] top-0 bottom-0 w-0.5 bg-gray-100" />

          <div className="space-y-0">
            {STAGES.map((stage, idx) => {
              const log = stageMap[stage.key];
              const reached = Boolean(log);
              const isLast = idx === STAGES.length - 1;

              return (
                <div key={stage.key} className={`relative flex gap-4 ${!isLast ? 'pb-6' : ''}`}>
                  {/* Icon circle */}
                  <div
                    className={`flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center text-base z-10 border-2 transition-colors ${
                      reached
                        ? 'bg-white border-blue-200 shadow-sm'
                        : 'bg-gray-50 border-gray-100'
                    }`}
                  >
                    {stage.icon}
                  </div>

                  {/* Content */}
                  <div className="flex-1 min-w-0 pt-1.5">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-sm font-semibold ${reached ? 'text-gray-900' : 'text-gray-400'}`}>
                        {stage.label}
                      </span>
                      {reached && (
                        <span className="w-1.5 h-1.5 rounded-full bg-blue-400 flex-shrink-0" />
                      )}
                    </div>

                    {reached ? (
                      <>
                        <p className="text-sm text-gray-600 leading-relaxed">{log.detail}</p>
                        <p className="text-xs text-gray-400 mt-1">{formatDate(log.timestamp)}</p>
                      </>
                    ) : (
                      <p className="text-sm text-gray-400 italic">
                        {stage.key === 'execute' && isBlocked
                          ? 'Not reached — recovery blocked by guardrail.'
                          : stage.key === 'measure' && isBlocked
                          ? 'Not reached — execution did not occur.'
                          : 'Not reached yet.'}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
