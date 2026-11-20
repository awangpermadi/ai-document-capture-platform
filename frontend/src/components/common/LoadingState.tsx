interface LoadingStateProps {
  label?: string
}

export function LoadingState({
  label = 'Loading data…',
}: LoadingStateProps) {
  return (
    <div className="loading-state" role="status" aria-live="polite">
      <span className="visually-hidden">{label}</span>
      <span aria-hidden="true" className="loading-skeleton" />
      <span aria-hidden="true" className="loading-skeleton" />
      <span aria-hidden="true" className="loading-skeleton loading-skeleton--short" />
    </div>
  )
}
