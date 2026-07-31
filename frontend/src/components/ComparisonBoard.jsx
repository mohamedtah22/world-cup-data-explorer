import { hasValue } from "../utils/format";

function compareValues(left, right, direction) {
  if (!direction) return { left: false, right: false };
  const leftNumber = Number(left);
  const rightNumber = Number(right);
  if (!Number.isFinite(leftNumber) || !Number.isFinite(rightNumber) || leftNumber === rightNumber) {
    return { left: false, right: false };
  }
  const leftWins = direction === "lower" ? leftNumber < rightNumber : leftNumber > rightNumber;
  return { left: leftWins, right: !leftWins };
}

function defaultFormat(value) {
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}

export default function ComparisonBoard({ left, right, leftName, rightName, metrics, type = "team" }) {
  const visibleMetrics = metrics.filter((metric) => {
    const leftValue = metric.value(left);
    const rightValue = metric.value(right);
    return hasValue(leftValue) && hasValue(rightValue);
  });

  return (
    <section className={`comparison-board comparison-board-${type}`}>
      <div className="comparison-head">
        <Competitor name={leftName} side="left" />
        <div className="comparison-versus"><span>VS</span></div>
        <Competitor name={rightName} side="right" />
      </div>

      <div className="comparison-metrics" role="table" aria-label={`${leftName} compared with ${rightName}`}>
        {visibleMetrics.map((metric) => {
          const leftValue = metric.value(left);
          const rightValue = metric.value(right);
          const formattedLeft = metric.format ? metric.format(leftValue, left) : defaultFormat(leftValue);
          const formattedRight = metric.format ? metric.format(rightValue, right) : defaultFormat(rightValue);
          const winners = compareValues(leftValue, rightValue, metric.direction);
          return (
            <div className="comparison-row" role="row" key={metric.key}>
              <div className={`comparison-value comparison-value-left ${winners.left ? "comparison-winner" : ""}`} role="cell">
                {formattedLeft}
              </div>
              <div className="comparison-label" role="rowheader">
                <span>{metric.label}</span>
                {metric.note && <small>{metric.note}</small>}
              </div>
              <div className={`comparison-value comparison-value-right ${winners.right ? "comparison-winner" : ""}`} role="cell">
                {formattedRight}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function Competitor({ name, side }) {
  const initials = String(name || "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();

  return (
    <article className={`comparison-competitor comparison-competitor-${side}`}>
      <div className="comparison-avatar">{initials}</div>
      <div>
        <span>{side === "left" ? "Competitor one" : "Competitor two"}</span>
        <h2>{name}</h2>
      </div>
    </article>
  );
}
