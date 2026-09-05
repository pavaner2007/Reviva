// components/StatusBadge.jsx — Reusable colored badge for guardrail and outcome statuses

const STYLES = {
  // Guardrail
  cleared:       'bg-green-100 text-green-800 border border-green-200',
  blocked:       'bg-red-100 text-red-800 border border-red-200',
  // Outcome
  recovered:     'bg-green-100 text-green-800 border border-green-200',
  pending:       'bg-amber-100 text-amber-800 border border-amber-200',
  not_recovered: 'bg-gray-100 text-gray-600 border border-gray-200',
  // Neutral
  neutral:       'bg-gray-100 text-gray-500 border border-gray-200',
  blue:          'bg-blue-100 text-blue-800 border border-blue-200',
};

export default function StatusBadge({ variant = 'neutral', label }) {
  const cls = STYLES[variant] ?? STYLES.neutral;
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium whitespace-nowrap ${cls}`}
    >
      {label}
    </span>
  );
}
