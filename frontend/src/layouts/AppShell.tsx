import { NavLink, Outlet } from 'react-router-dom';

import { NavIcon } from '../components/NavIcon';
import { StatusHeader } from '../components/StatusHeader';
import { useRuntimeStatus } from '../components/runtimeStatusContext';

const navigation = [
  { label: '控制', englishLabel: 'Control', to: '/control', icon: 'control' },
  { label: '编排', englishLabel: 'Studio', to: '/studio', icon: 'studio' },
  { label: '资源库', englishLabel: 'Library', to: '/library', icon: 'library' },
  { label: '视觉', englishLabel: 'Vision', to: '/vision', icon: 'vision' },
  { label: '设置', englishLabel: 'Settings', to: '/settings', icon: 'settings' },
] as const;

function RuntimeStatusBar() {
  const runtime = useRuntimeStatus();
  const enabledJoints = runtime.profile?.profile.enabled_joints ?? [];
  const readings = enabledJoints.flatMap((jointId) => {
    const value = runtime.robot?.positions[jointId];
    const unit = runtime.robot?.units[jointId];
    if (typeof value !== 'number' || !Number.isFinite(value) || (unit !== 'mm' && unit !== 'deg')) {
      return [];
    }
    return [`${jointId.toUpperCase()} ${value.toFixed(1)}${unit === 'deg' ? '°' : ' mm'}`];
  }).slice(0, 2);
  const backendLabel = runtime.backend === 'unavailable'
    ? 'Backend Offline'
    : runtime.stale
      ? 'Backend Stale'
      : 'Backend Online';

  return (
    <footer className="status-bar" aria-label="实时状态">
      <div className="status-bar__telemetry">
        <strong>{runtime.robot ? `Robot: ${runtime.robot.variant}` : 'Robot: 未加载'}</strong>
        {readings.map((reading) => <span key={reading}>{reading}</span>)}
      </div>
      <div
        className={`status-bar__backend status-bar__backend--${runtime.backend}`}
        role="status"
      >
        <span className="status-bar__dot" aria-hidden="true" />
        <span>{backendLabel} · {runtime.controlMode}</span>
      </div>
    </footer>
  );
}

export function AppShell() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <NavLink className="brand" to="/control" aria-label="MOMO Studio 首页">
          <strong>MOMO</strong>
          <span>STUDIO</span>
        </NavLink>
        <nav className="main-nav" aria-label="主导航">
          {navigation.map((item) => (
            <NavLink
              className={({ isActive }) =>
                [
                  'main-nav__link',
                  item.to === '/settings' ? 'main-nav__link--settings' : '',
                  isActive ? 'main-nav__link--active' : '',
                ].filter(Boolean).join(' ')
              }
              key={item.to}
              to={item.to}
              aria-label={`${item.label} ${item.englishLabel}`}
            >
              <NavIcon name={item.icon} />
              <span className="main-nav__labels">
                <span className="main-nav__label">{item.label}</span>
                <span className="main-nav__english" aria-hidden="true">{item.englishLabel}</span>
              </span>
            </NavLink>
          ))}
        </nav>
      </aside>
      <StatusHeader />
      <main className="workspace" aria-label="工作区内容">
        <div className="workspace__content">
          <Outlet />
        </div>
      </main>
      <RuntimeStatusBar />
    </div>
  );
}
