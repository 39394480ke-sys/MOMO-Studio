import { useLocation } from 'react-router-dom';

import { StatusPill, type StatusPillTone } from './ui/StatusPill';
import { useRuntimeStatus } from './runtimeStatusContext';

const routeDetails: Record<string, { label: string; workspace: string }> = {
  '/control': { label: '控制', workspace: '机器人工作区' },
  '/studio': { label: '编排', workspace: '运动工作区' },
  '/library': { label: '资源库', workspace: '位姿与运动' },
  '/vision': { label: '视觉', workspace: '监看与跟随' },
  '/settings': { label: '设置', workspace: '系统与安全' },
};

interface ConnectionPresentation {
  label: string;
  ariaLabel: string;
  tone: StatusPillTone;
}

export function StatusHeader() {
  const { pathname } = useLocation();
  const {
    backend,
    controlMode,
    hardwareAccessPolicy,
    realMotionEnabled,
    robot,
    stale,
  } = useRuntimeStatus();
  const route = routeDetails[pathname] ?? routeDetails['/control'];
  const variant = robot?.variant ?? null;
  const variantLabel = variant ?? 'V–';
  const variantAriaLabel = variant ? `机器人型号 ${variant}` : '机器人型号未加载';
  const modeLabel = controlMode === 'DRY RUN'
    ? 'DRY RUN'
    : hardwareAccessPolicy === 'READ_ONLY'
      ? 'REAL · READ ONLY'
      : hardwareAccessPolicy === 'DISABLED'
        ? 'REAL · DISABLED'
        : 'REAL';
  const modeAriaLabel = controlMode === 'DRY RUN'
    ? 'DRY RUN 仿真模式，真实运动已禁用'
    : hardwareAccessPolicy === 'READ_ONLY'
      ? 'REAL 投产只读模式，禁止运动'
      : realMotionEnabled
        ? 'REAL 模式，真实运动仍需安全会话授权'
        : 'REAL 模式，真实运动未启用';

  let connection: ConnectionPresentation;
  if (backend === 'unavailable') {
    connection = { label: 'Offline', ariaLabel: '后端离线', tone: 'danger' };
  } else if (stale) {
    connection = { label: 'Stale', ariaLabel: '后端在线，但机器人状态已过期', tone: 'danger' };
  } else if (!robot) {
    connection = { label: 'No Robot', ariaLabel: '后端在线，机器人状态未加载', tone: 'neutral' };
  } else if (robot.connected && robot.connection_state === 'CONNECTED') {
    connection = { label: 'Connected', ariaLabel: '机器人已连接', tone: 'success' };
  } else if (robot.connection_state === 'CONNECTING') {
    connection = { label: 'Connecting', ariaLabel: '机器人正在连接', tone: 'accent' };
  } else if (robot.connection_state === 'DISCONNECTING') {
    connection = { label: 'Disconnecting', ariaLabel: '机器人正在断开连接', tone: 'neutral' };
  } else if (robot.connection_state === 'FAULTED') {
    connection = { label: 'Faulted', ariaLabel: '机器人连接故障', tone: 'danger' };
  } else {
    connection = { label: 'Disconnected', ariaLabel: '机器人未连接', tone: 'neutral' };
  }

  return (
    <header className="status-header" aria-label="系统状态">
      <span className="status-header__mobile-brand" aria-label="MOMO Studio">MOMO</span>
      <nav className="status-header__breadcrumb" aria-label="当前位置">
        <ol>
          <li>{route.label}</li>
          <li aria-current="page">{route.workspace}</li>
        </ol>
      </nav>
      <div className="status-header__runtime" aria-label="运行状态">
        <StatusPill label={variantLabel} ariaLabel={variantAriaLabel} />
        <StatusPill label={modeLabel} ariaLabel={modeAriaLabel} />
        <StatusPill
          label={connection.label}
          ariaLabel={connection.ariaLabel}
          tone={connection.tone}
          dot
        />
      </div>
    </header>
  );
}
