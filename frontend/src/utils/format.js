export function hasValue(value) {
  return value !== null && value !== undefined && value !== "" && !(typeof value === "number" && Number.isNaN(value));
}

export function formatNumber(value, options = {}) {
  if (!hasValue(value)) return "";
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return String(value);
  return numeric.toLocaleString(undefined, options);
}

export function formatDate(value) {
  if (!hasValue(value)) return "";
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("en", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

export function formatPercent(value, digits = 1) {
  if (!hasValue(value)) return "";
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return "";
  return `${numeric.toFixed(digits).replace(/\.0$/, "")}%`;
}

export function formatDecimal(value, digits = 3) {
  if (!hasValue(value)) return "";
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return "";
  return numeric.toFixed(digits).replace(/0+$/, "").replace(/\.$/, "");
}
