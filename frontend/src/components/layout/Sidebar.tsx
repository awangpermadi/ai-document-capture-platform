import {
  FileStack,
  LayoutDashboard,
  ScanLine,
} from 'lucide-react'
import { NavLink, Link } from 'react-router-dom'

const navigation = [
  { label: 'Dashboard', to: '/', icon: LayoutDashboard, end: true },
  { label: 'Documents', to: '/documents', icon: FileStack, end: false },
  { label: 'Upload Document', to: '/upload', icon: ScanLine, end: true },
]

export function Sidebar() {
  return (
    <aside className="app-sidebar">
      <Link aria-label="AI Document Capture dashboard" className="app-brand" to="/">
        <span className="app-brand__mark">
          <ScanLine aria-hidden="true" size={21} />
        </span>
        <span className="app-brand__text">
          <strong>AI Document Capture</strong>
          <small>Document workspace</small>
        </span>
      </Link>

      <nav aria-label="Primary navigation" className="app-sidebar__navigation">
        <span className="app-sidebar__label">WORKSPACE</span>
        {navigation.map(({ label, to, icon: Icon, end }) => (
          <NavLink
            className={({ isActive }) =>
              `app-sidebar__link${isActive ? ' app-sidebar__link--active' : ''}`
            }
            end={end}
            key={to}
            to={to}
          >
            <Icon aria-hidden="true" size={18} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="app-sidebar__footer">
        Receipt capture and review
      </div>
    </aside>
  )
}
