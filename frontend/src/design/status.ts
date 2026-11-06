export type StatusTone = 'neutral' | 'good' | 'bad' | 'danger';
// Exact codes: availability is not validity, profitability or observed effect.
export function statusTone(code: string): StatusTone {
  if (['FAILED', 'BLOCKED', 'DENIED', 'STOP'].includes(code)) return 'danger';
  if (['PARTIAL', 'STALE', 'EXPIRED', 'UNAVAILABLE', 'INCOMPATIBLE', 'UNKNOWN', 'NOT_STARTED', 'DRAIN', 'REQUESTED', 'CLAIMED'].includes(code)) return 'bad';
  if (['MATCHED', 'OBSERVED'].includes(code)) return 'good';
  return 'neutral';
}
