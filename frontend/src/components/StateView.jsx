export function LoadingState({ label = "Loading data" }) {
  return <div className="state">{label}...</div>;
}

export function ErrorState({ message, onRetry }) {
  return (
    <div className="state state-error">
      <strong>Could not load data.</strong>
      <span>{message}</span>
      {onRetry && <button onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function EmptyState({ label = "No records found" }) {
  return <div className="state">{label}</div>;
}
