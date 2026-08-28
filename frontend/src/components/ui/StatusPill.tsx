export type StatusPillTone = 'neutral' | 'accent' | 'success' | 'danger';

interface StatusPillProps {
  label: string;
  ariaLabel?: string;
  tone?: StatusPillTone;
  dot?: boolean;
}

export function StatusPill({
  label,
  ariaLabel,
  tone = 'neutral',
  dot = false,
}: StatusPillProps) {
  return (
    <span className={`status-pill status-pill--${tone}`} aria-label={ariaLabel}>
      {dot ? <span className="status-pill__dot" aria-hidden="true" /> : null}
      <span>{label}</span>
    </span>
  );
}
