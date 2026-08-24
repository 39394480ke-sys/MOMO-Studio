import { NavLink, Outlet } from 'react-router-dom';

import { NavIcon } from '../components/NavIcon';
import { StatusHeader } from '../components/StatusHeader';

const navigation = [
  { label: '控制', to: '/control', icon: 'control' },
  { label: '编排', to: '/studio', icon: 'studio' },
  { label: '资源库', to: '/library', icon: 'library' },
  { label: '视觉', to: '/vision', icon: 'vision' },
  { label: '设置', to: '/settings', icon: 'settings' },
] as const;

export function AppShell() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand" aria-label="MOMO Studio">
          <strong>MOMO</strong> <span>Studio</span>
        </div>
        <nav className="main-nav" aria-label="主导航">
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
      <footer className="stage-footer" aria-label="发布状态">
        <strong>MOMO Studio 0.1.0-rc1</strong>
        <span>仿真运行已验证</span>
        <span>真实硬件现场验收待完成</span>
      </footer>
    </div>
  );
}
