import { NavLink, Outlet } from 'react-router-dom';

import { NavIcon } from '../components/NavIcon';
import { StatusHeader } from '../components/StatusHeader';

const navigation = [
  { label: 'Control', to: '/control', icon: 'control' },
  { label: 'Studio', to: '/studio', icon: 'studio' },
  { label: 'Library', to: '/library', icon: 'library' },
  { label: 'Vision', to: '/vision', icon: 'vision' },
  { label: 'Settings', to: '/settings', icon: 'settings' },
] as const;

export function AppShell() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand" aria-label="MOMO Studio">
          <strong>MOMO</strong> <span>Studio</span>
        </div>
        <nav className="main-nav" aria-label="Primary navigation">
          {navigation.map((item) => (
            <NavLink
              className={({ isActive }) =>
                `main-nav__link${isActive ? ' main-nav__link--active' : ''}`
              }
              key={item.to}
              to={item.to}
            >
              <NavIcon name={item.icon} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
      </aside>
      <StatusHeader />
      <main className="workspace">
        <div className="workspace__content">
          <Outlet />
        </div>
      </main>
      <footer className="stage-footer">Stage 2&nbsp; · &nbsp;Robot Core</footer>
    </div>
  );
}
