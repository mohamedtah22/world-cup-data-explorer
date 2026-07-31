import { useEffect, useState } from "react";
import Icon from "./Icon";

export function LoadingState({ label = "Loading data" }) {
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setSlow(true), 4500);
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <div className="state loading-state" role="status">
      <div className="loader" aria-hidden="true" />
      <div>
        <strong>{label}</strong>
        <span>{slow ? "The free Render server may need up to 40 seconds to wake up." : "Fetching the latest database results…"}</span>
      </div>
    </div>
  );
}

export function ErrorState({ message, onRetry }) {
  return (
    <div className="state state-error" role="alert">
      <div className="state-icon"><Icon name="info" size={22} /></div>
      <div>
        <strong>Could not load this section</strong>
        <span>{message}</span>
        {onRetry && <button onClick={onRetry}>Try again</button>}
      </div>
    </div>
  );
}

export function EmptyState({ label = "No records match these filters" }) {
  return (
    <div className="state empty-state">
      <div className="state-icon"><Icon name="search" size={22} /></div>
      <div>
        <strong>No results</strong>
        <span>{label}</span>
      </div>
    </div>
  );
}
