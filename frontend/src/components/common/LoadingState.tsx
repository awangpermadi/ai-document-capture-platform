import { LoaderCircle } from 'lucide-react'

interface LoadingStateProps {
  label?: string
}

export function LoadingState({
  label = 'Loading data…',
}: LoadingStateProps) {
  return (
    <div className="state-card" role="status" aria-live="polite">
      <LoaderCircle aria-hidden="true" className="loading-icon" size={24} />
      <span>{label}</span>
    </div>
  )
}
