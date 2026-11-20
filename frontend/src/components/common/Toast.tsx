import { Check, TriangleAlert, X } from 'lucide-react'
import { useEffect } from 'react'

interface ToastProps {
  message: string
  variant?: 'success' | 'warning'
  onDismiss: () => void
}

export function Toast({
  message,
  variant = 'success',
  onDismiss,
}: ToastProps) {
  useEffect(() => {
    const timer = window.setTimeout(onDismiss, 4500)
    return () => window.clearTimeout(timer)
  }, [message, onDismiss])

  const Icon = variant === 'success' ? Check : TriangleAlert

  return (
    <div
      className={`mobile-toast mobile-toast--${variant}`}
      role="status"
      aria-live="polite"
    >
      <Icon aria-hidden="true" size={18} />
      <span>{message}</span>
      <button
        aria-label="Dismiss notification"
        className="mobile-toast__dismiss"
        onClick={onDismiss}
        type="button"
      >
        <X aria-hidden="true" size={16} />
      </button>
    </div>
  )
}
