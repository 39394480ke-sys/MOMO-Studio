import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { mockStage3Backend } from '../test/stage3Fixtures';
import { AppContent } from './App';

function renderRoute(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppContent />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('MOMO Studio product shell', () => {
  it.each([
    ['/control', '机器人控制', '机器人工作区'],
    ['/studio', '编辑', '运动工作区'],
    ['/library', '资源库', '位姿与运动'],
    ['/vision', '视觉监控', '监看与跟随'],
    ['/settings', '设置', '系统与安全'],
  ])('provides the %s route', async (path, heading, workspace) => {
    mockStage3Backend();
    renderRoute(path);
    expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeVisible();
    const header = screen.getByLabelText('系统状态');
    expect(within(header).getByText(workspace)).toBeVisible();
    expect(within(header).getByText('V2')).toBeVisible();
    expect(within(header).getByText('Connected')).toBeVisible();
    expect(screen.getByText('Robot: V2')).toBeVisible();
    expect(screen.getByText('J10 0.0 mm')).toBeVisible();
    expect(screen.getByText('J11 0.0°')).toBeVisible();
    expect(screen.getByText('Backend Online · DRY RUN')).toBeVisible();
  });

  it('opens the active Studio timeline authoring workspace', async () => {
    mockStage3Backend();
    const view = renderRoute('/library');
    expect(await screen.findByText(/Stage 5 · 已编译的仿真播放/)).toBeVisible();
    view.unmount();
    renderRoute('/studio');
    expect(await screen.findByText('空白运动草稿')).toBeVisible();
    expect(screen.queryByRole('button', { name: /捕获当前姿态/ })).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: '添加关键帧' }));
    expect(await screen.findByRole('button', { name: /捕获当前姿态/ })).toBeVisible();
  });

  it('switches to V1 in Settings and exposes exactly the enabled joint set', async () => {
    const user = userEvent.setup();
    mockStage3Backend({ connected: false });
    renderRoute('/settings');
    expect(await screen.findByText('一条直线导轨 + 五个旋转关节')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'V1' }));
    expect(await screen.findByText('五个旋转关节 · 无直线导轨')).toBeVisible();
    const enabledJoints = screen.getByLabelText('启用关节与运动范围');
    for (const jointId of ['J11', 'J12', 'J13', 'J14', 'J15']) {
      expect(within(enabledJoints).getByText(jointId)).toBeVisible();
    }
    expect(within(enabledJoints).queryByText('J10')).not.toBeInTheDocument();
    expect(screen.getByText('Robot: V1')).toBeVisible();
  });

  it('renders V1 Control as five keyed joint cards without J10', async () => {
    mockStage3Backend({ variant: 'V1' });
    renderRoute('/control');
    expect(await screen.findByLabelText('J11 target (deg)')).toBeVisible();
    expect(screen.getAllByRole('slider')).toHaveLength(5);
    expect(screen.queryByLabelText(/J10 target/)).not.toBeInTheDocument();
  });

  it('connects, performs a global motion stop, and disconnects the Dry Run robot', async () => {
    const user = userEvent.setup();
    const backend = mockStage3Backend({ connected: false });
    renderRoute('/control');
    expect(await screen.findByText('Disconnected')).toBeVisible();

    await user.click(screen.getByRole('button', { name: '连接' }));
    expect(await screen.findByText('Connected')).toBeVisible();
    await user.click(screen.getByRole('button', { name: '停止运动' }));
    await user.click(screen.getByRole('button', { name: '断开连接' }));
    expect(await screen.findByText('Disconnected')).toBeVisible();

    expect(backend.requestsFor('/robot/connect')).toHaveLength(1);
    expect(backend.requestsFor('/motion/stop')).toHaveLength(1);
    expect(backend.requestsFor('/robot/disconnect')).toHaveLength(1);
  });

  it('renders the backend structured error message for a failed lifecycle action', async () => {
    const user = userEvent.setup();
    mockStage3Backend({ connected: false, connectError: true });
    renderRoute('/control');
    await screen.findByText('Disconnected');
    await user.click(screen.getByRole('button', { name: '连接' }));
    expect(await screen.findByText(/The active Dry Run robot is already connected/)).toBeVisible();
  });

  it('preserves telemetry but disables motion when a later refresh becomes stale', async () => {
    const backend = mockStage3Backend();
    renderRoute('/control');
    await waitFor(() => expect(screen.getByLabelText('J10 target (mm)')).toBeEnabled());
    backend.goOffline();
    await waitFor(
      () => expect(screen.getByText('后端不可用 · 正在显示过期状态')).toBeVisible(),
      { timeout: 1800 },
    );
    expect(screen.getByLabelText('J10 target (mm)')).toBeVisible();
    expect(screen.getByRole('button', { name: '移动全部关节' })).toBeDisabled();
  });

  it('uses a truthful safe fallback and disables all motion when initially offline', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    vi.stubGlobal('WebSocket', undefined);
    renderRoute('/control');
    expect((await screen.findAllByText('后端不可用')).length).toBeGreaterThan(0);
    expect(screen.getByText('Offline')).toBeVisible();
    expect(screen.getAllByText('DRY RUN').length).toBeGreaterThan(0);
    expect(screen.getByLabelText('DRY RUN 仿真模式，真实运动已禁用')).toBeVisible();
    expect(screen.getByRole('button', { name: '停止运动' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: '移动到位姿' })).not.toBeInTheDocument();
  });
});
