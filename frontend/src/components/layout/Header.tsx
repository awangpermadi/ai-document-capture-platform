import { useLocation } from 'react-router-dom'

function getPageTitle(pathname: string): string {
  if (pathname === '/') return 'Dashboard'
  if (pathname === '/documents') return 'Documents'
  if (pathname === '/upload') return 'Upload Document'
  if (pathname.startsWith('/documents/')) return 'Document Review'
  return 'Page Not Found'
}

export function Header() {
  const { pathname } = useLocation()

  return (
    <header className="app-header">
      <div>
        <p className="app-header__eyebrow">WORKSPACE</p>
        <h1>{getPageTitle(pathname)}</h1>
      </div>
    </header>
  )
}
