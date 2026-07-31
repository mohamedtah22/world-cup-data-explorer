import { hasValue } from "../utils/format";

export default function StatGrid({ items, className = "" }) {
  const visibleItems = items.filter((item) => !item.hidden && hasValue(item.value));

  if (!visibleItems.length) return null;

  return (
    <div className={`stat-grid ${className}`.trim()}>
      {visibleItems.map((item) => (
        <div className="stat-tile" key={item.label}>
          <span>{item.label}</span>
          <strong>{item.format ? item.format(item.value) : item.value}</strong>
          {item.note && <small>{item.note}</small>}
        </div>
      ))}
    </div>
  );
}
