// pages/Dashboard.jsx — Page 3: Live recovery analytics
import { useState, useEffect } from 'react';
import { getSummary, formatMoney } from '../services/api';
import Loading from '../components/Loading';
import ErrorMessage from '../components/ErrorMessage';

const ROOT_CAUSES = [
  'Card Expired',
  'Insufficient Funds',
  'Bank/Network Timeout',
  'OTP Verification Failed',
  'Issuer Declined Transaction',
  'Unclassified \u2014 Needs Review',
];

function MetricCard({ label, value, sub, accent = false, large = false }) {
  return (
    <div className={`card p-6 ${accent ? 'border-blue-100 bg-gradient-to-br from-blue-600 to-blue-700 text-white' : ''}`}>
      <p className={`text-xs font-semibold uppercase tracking-wide mb-1 ${accent ? 'text-blue-200' : 'text-gray-400'}`}>
        {label}
      </p>
      <p className={`font-extrabold leading-none ${large ? 'text-4xl' : 'text-2xl'} ${accent ? 'text-white' : 'text-gray-900'}`}>
        {value}
      </p>
      {sub && (
        <p className={`text-sm mt-1.5 ${accent ? 'text-blue-200' : 'text-gray-500'}`}>{sub}</p>
      )}
    </div>
  );
}

function OutcomeCard({ label, count, color }) {
  const colors = {
    green: 'bg-green-50 border-green-100',
    amber: 'bg-amber-50 border-amber-100',
    gray: 'bg-gray-50 border-gray-100',
  };
  const textColors = {
    green: 'text-green-700',
    amber: 'text-amber-700',
    gray: 'text-gray-600',
  };
  return (
    <div className={`card p-5 ${colors[color]}`}>
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">{label}</p>
      <p className={`text-3xl font-extrabold ${textColors[color]}`}>{count}</p>
    </div>
  );
}

export default function Dashboard() {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  const load = () => {
    getSummary()
      .then((data) => {
        setSummary(data);
        setLastUpdated(new Date());
        setError(null);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, []);

  if (loading) return <Loading message="Loading recovery analytics…" />;
  if (error) return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      <ErrorMessage message={error} />
    </div>
  );

  const byRootCause = summary.by_root_cause ?? {};

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      {/* Page header */}
      <div className="flex items-start justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Recovery Dashboard</h1>
          <p className="text-sm text-gray-500 mt-1">Live revenue recovery metrics · auto-refreshes every 10s</p>
        </div>
        {lastUpdated && (
          <span className="text-xs text-gray-400 mt-1 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
            Updated {lastUpdated.toLocaleTimeString('en-IN')}
          </span>
        )}
      </div>

      {/* ── PRIMARY HERO METRIC ─────────────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
        <div className="sm:col-span-2">
          <MetricCard
            label="Total Revenue Recovered"
            value={formatMoney(summary.total_recovered_amount)}
            sub={`out of ${formatMoney(summary.total_at_risk_amount)} at risk`}
            accent
            large
          />
        </div>
        <MetricCard
          label="Recovery Rate"
          value={`${summary.recovery_rate?.toFixed(1) ?? '0.0'}%`}
          sub={`${summary.recovered_count} payment${summary.recovered_count !== 1 ? 's' : ''} recovered`}
          large
        />
      </div>

      {/* ── SECONDARY METRICS ───────────────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
        <MetricCard
          label="Eligible At Risk"
          value={formatMoney(summary.eligible_at_risk_amount)}
          sub="Guardrail-cleared"
        />
        <MetricCard
          label="Guardrail Blocked"
          value={formatMoney(summary.guardrail_blocked_value)}
          sub="Intentionally protected"
        />
        <MetricCard
          label="Total Executed"
          value={summary.total_executed_events ?? 0}
          sub="Payment links created"
        />
        <MetricCard
          label="Pending Recovery"
          value={summary.pending_count ?? 0}
          sub="Awaiting payment"
        />
      </div>

      {/* ── OUTCOME BREAKDOWN ───────────────────────────────────────────── */}
      <div className="mb-8">
        <h2 className="text-base font-bold text-gray-900 mb-4">Outcome Breakdown</h2>
        <div className="grid grid-cols-3 gap-4">
          <OutcomeCard label="Recovered" count={summary.recovered_count ?? 0} color="green" />
          <OutcomeCard label="Pending" count={summary.pending_count ?? 0} color="amber" />
          <OutcomeCard label="Not Recovered" count={summary.not_recovered_count ?? 0} color="gray" />
        </div>
      </div>

      {/* ── ROOT CAUSE BREAKDOWN ─────────────────────────────────────────── */}
      <div className="card overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-100">
          <h2 className="text-base font-bold text-gray-900">Root Cause Breakdown</h2>
          <p className="text-xs text-gray-400 mt-0.5">Recovery performance by classified root cause</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-100">
                <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Root Cause</th>
                <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Attempted</th>
                <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Recovered</th>
                <th className="text-right px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Recovered Amount</th>
                <th className="px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Recovery %</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {ROOT_CAUSES.map((rc) => {
                const d = byRootCause[rc] ?? { attempted_count: 0, recovered_count: 0, recovered_amount: 0 };
                const rate = d.attempted_count > 0
                  ? Math.round((d.recovered_count / d.attempted_count) * 100)
                  : 0;
                return (
                  <tr key={rc} className="hover:bg-gray-50/60 transition-colors">
                    <td className="px-6 py-3 font-medium text-gray-800">{rc}</td>
                    <td className="px-4 py-3 text-right text-gray-600">{d.attempted_count}</td>
                    <td className="px-4 py-3 text-right font-semibold text-green-700">{d.recovered_count}</td>
                    <td className="px-6 py-3 text-right font-semibold text-gray-900">{formatMoney(d.recovered_amount)}</td>
                    <td className="px-6 py-3">
                      <div className="flex items-center gap-2">
                        <div className="flex-1 bg-gray-100 rounded-full h-1.5 max-w-[80px]">
                          <div
                            className="bg-blue-500 h-1.5 rounded-full transition-all duration-300"
                            style={{ width: `${rate}%` }}
                          />
                        </div>
                        <span className="text-xs text-gray-500 w-8 text-right">{rate}%</span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
