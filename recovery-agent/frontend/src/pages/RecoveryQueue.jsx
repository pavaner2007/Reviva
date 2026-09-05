// pages/RecoveryQueue.jsx — Page 1: All failed payment events with filter tabs
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchMergedQueue, formatMoney, formatStrategy } from '../services/api';
import StatusBadge from '../components/StatusBadge';
import Loading from '../components/Loading';
import ErrorMessage from '../components/ErrorMessage';

const FILTERS = ['All', 'Blocked', 'Cleared', 'Recovered', 'Pending'];

function guardrailBadge(row) {
  if (row.guardrail_passed === true)
    return <StatusBadge variant="cleared" label="Cleared" />;
  if (row.guardrail_passed === false) {
    const reason = row.guardrail_reason
      ? row.guardrail_reason.replace(/_/g, ' ')
      : 'blocked';
    return <StatusBadge variant="blocked" label={`Blocked — ${reason}`} />;
  }
  return <StatusBadge variant="neutral" label="Not evaluated" />;
}

function outcomeBadge(row) {
  if (!row.outcome) return <StatusBadge variant="neutral" label="Not executed" />;
  if (row.outcome === 'recovered')
    return <StatusBadge variant="recovered" label="Recovered" />;
  if (row.outcome === 'pending')
    return <StatusBadge variant="pending" label="Pending" />;
  if (row.outcome === 'not_recovered')
    return <StatusBadge variant="not_recovered" label="Not Recovered" />;
  return <StatusBadge variant="neutral" label={row.outcome} />;
}

function matchesFilter(row, filter) {
  if (filter === 'All') return true;
  if (filter === 'Blocked') return row.guardrail_passed === false;
  if (filter === 'Cleared') return row.guardrail_passed === true;
  if (filter === 'Recovered') return row.outcome === 'recovered';
  if (filter === 'Pending') return row.outcome === 'pending';
  return true;
}

export default function RecoveryQueue() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('All');
  const navigate = useNavigate();

  useEffect(() => {
    fetchMergedQueue()
      .then(setRows)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const filtered = rows.filter((r) => matchesFilter(r, filter));

  const filterCount = (f) => {
    if (f === 'All') return rows.length;
    return rows.filter((r) => matchesFilter(r, f)).length;
  };

  return (
    <div className="max-w-7xl mx-auto px-6 py-8">
      {/* Page header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Recovery Queue</h1>
        <p className="text-sm text-gray-500 mt-1">
          All failed payment events — AI-classified, guardrail-evaluated, and recovery-tracked.
        </p>
      </div>

      {/* Filter tabs */}
      <div className="flex items-center gap-1 mb-5 bg-gray-100 p-1 rounded-xl w-fit">
        {FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-4 py-1.5 text-sm font-medium rounded-lg transition-colors duration-150 ${
              filter === f
                ? 'bg-white text-blue-600 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {f}
            <span
              className={`ml-2 text-xs px-1.5 py-0.5 rounded-full ${
                filter === f ? 'bg-blue-100 text-blue-600' : 'bg-gray-200 text-gray-500'
              }`}
            >
              {filterCount(f)}
            </span>
          </button>
        ))}
      </div>

      {loading && <Loading message="Loading recovery events…" />}
      {error && <ErrorMessage message={error} />}

      {!loading && !error && rows.length === 0 && (
        <div className="card p-12 text-center">
          <p className="text-gray-400 text-lg mb-2">📭 No data yet</p>
          <p className="text-gray-500 text-sm">Run the seed and pipeline to populate events.</p>
          <code className="mt-3 block text-xs text-gray-400">python -m app.seed_data &amp;&amp; python -m app.reset_and_verify</code>
        </div>
      )}

      {!loading && !error && rows.length > 0 && (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100">
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Order ID</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Customer</th>
                  <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Amount</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Root Cause</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Strategy</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Guardrail</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Outcome</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filtered.map((row) => (
                  <tr
                    key={row.event_id}
                    className="table-row-hover"
                    onClick={() => navigate(`/case/${row.event_id}`)}
                  >
                    <td className="px-4 py-3">
                      <span className="font-mono text-xs text-gray-600 bg-gray-100 px-2 py-0.5 rounded">
                        {row.order_id}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="font-medium text-gray-900">{row.customer_name}</div>
                      <div className="text-xs text-gray-400">{row.customer_id}</div>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className="font-semibold text-gray-900">{formatMoney(row.amount)}</span>
                    </td>
                    <td className="px-4 py-3 text-gray-700">
                      {row.root_cause ?? (
                        <span className="text-gray-400 italic">Not processed yet</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-600 max-w-[180px]">
                      <span className="truncate block">{formatStrategy(row.strategy)}</span>
                    </td>
                    <td className="px-4 py-3">{guardrailBadge(row)}</td>
                    <td className="px-4 py-3">{outcomeBadge(row)}</td>
                  </tr>
                ))}
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-12 text-center text-gray-400 text-sm">
                      No events match this filter.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Footer count */}
          <div className="px-4 py-3 bg-gray-50 border-t border-gray-100 text-xs text-gray-400">
            Showing {filtered.length} of {rows.length} events
          </div>
        </div>
      )}
    </div>
  );
}
