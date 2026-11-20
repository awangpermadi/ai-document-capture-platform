import { Outlet } from 'react-router-dom'
import { BottomNavigation } from './BottomNavigation'
import { MobileHeader } from './MobileHeader'

export function MobileLayout() {
  return (
    <div className="mobile-app">
      <MobileHeader />
      <main className="mobile-content" id="main-content">
        <Outlet />
      </main>
      <BottomNavigation />
    </div>
  )
}
