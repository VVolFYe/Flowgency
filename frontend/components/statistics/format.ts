/** Formatting helpers. null is unknown and is never shown as 0. */

export const UNKNOWN = "—";

const formatters = new Map<number, Intl.NumberFormat>();

export function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return UNKNOWN;
  let formatter = formatters.get(digits);
  if (!formatter) {
    formatter = new Intl.NumberFormat("en-GB", { maximumFractionDigits: digits });
    formatters.set(digits, formatter);
  }
  return formatter.format(value);
}

export function formatWithUnit(value: number | null | undefined, unit: string, digits = 1): string {
  const text = formatNumber(value, digits);
  return text === UNKNOWN ? text : `${text} ${unit}`;
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return UNKNOWN;
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function formatSignedNumber(value: number | null | undefined, digits = 1): string {
  const text = formatNumber(value, digits);
  return text !== UNKNOWN && value !== null && value !== undefined && value > 0 ? `+${text}` : text;
}

export function formatClock(seconds: number): string {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
