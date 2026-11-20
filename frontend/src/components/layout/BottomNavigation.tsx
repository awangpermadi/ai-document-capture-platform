import { History, Home, ScanLine } from 'lucide-react'
import { NavLink } from 'react-router-dom'

const navigation = [
  { label: 'Home', to: '/', icon: Home, end: true },
  { label: 'Scan', to: '/scan', icon: ScanLine, end: true },
  { label: 'History', to: '/documents', icon: History, end: false },
]

export function BottomNavigation() {
  return (
    <nav aria-label="Primary navigation" className="bottom-navigation">
      {navigation.map(({ label, to, icon: Icon, end }) => (
        <NavLink
          aria-label={label}
          className={({ isActive }) =>
            `bottom-navigation__item${isActive ? ' bottom-navigation__item--active' : ''}${label === 'Scan' ? ' bottom-navigation__item--scan' : ''}`
          }
          end={end}
          key={to}
          to={to}
        >
          <span className="bottom-navigation__icon">
            <Icon aria-hidden="true" size={label === 'Scan' ? 23 : 21} />
          </span>
          <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  )
}
