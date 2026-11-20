interface StatusBadgeProps {
  status: string
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const normalizedStatus = status.toLowerCase()
  const label = normalizedStatus.toUpperCase()

  return (
    <span
      className={`status-badge status-badge--${normalizedStatus}`}
      aria-label={`Status: ${label}`}
    >
      <span aria-hidden="true" className="status-badge__dot" />
      <span>{label}</span>
    </span>
  )
}
