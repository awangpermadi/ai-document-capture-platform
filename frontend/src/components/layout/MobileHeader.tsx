import { ArrowLeft, ScanLine } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'

function getPageTitle(pathname: string): string {
  if (pathname === '/scan') return 'Scan Receipt'
  if (pathname === '/documents') return 'Document History'
  if (pathname.startsWith('/documents/')) return 'Receipt Review'
  return 'Page Not Found'
}

export function MobileHeader() {
  const { pathname } = useLocation()
  const navigate = useNavigate()

  if (pathname === '/') {
    return (
      <header className="mobile-header mobile-header--home">
        <span className="mobile-header__mark">
          <ScanLine aria-hidden="true" size={20} />
        </span>
        <span className="mobile-header__brand">
          <h1>AI Document Capture</h1>
          <small>Smart receipt processing</small>
        </span>
      </header>
    )
  }

  const backPath = pathname.startsWith('/documents/') ? '/documents' : '/'

  return (
    <header className="mobile-header">
      <button
        aria-label="Back"
        className="mobile-header__back"
        onClick={() => navigate(backPath)}
        type="button"
      >
        <ArrowLeft aria-hidden="true" size={21} />
      </button>
      <h1>{getPageTitle(pathname)}</h1>
    </header>
  )
}
