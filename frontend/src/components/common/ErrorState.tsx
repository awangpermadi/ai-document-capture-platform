import { CircleAlert } from 'lucide-react'

interface ErrorStateProps {
  title?: string
  message: string
  onRetry?: () => void
  retryLabel?: string
}

export function ErrorState({
  title = 'We couldn’t load this information',
  message,
  onRetry,
  retryLabel = 'Try again',
}: ErrorStateProps) {
  return (
    <div className="state-card state-card--error" role="alert">
      <CircleAlert aria-hidden="true" size={24} />
      <div>
        <h2>{title}</h2>
        <p>{message}</p>
        {onRetry ? (
          <button className="button button--secondary" onClick={onRetry} type="button">
            {retryLabel}
          </button>
        ) : null}
      </div>
    </div>
  )
}
