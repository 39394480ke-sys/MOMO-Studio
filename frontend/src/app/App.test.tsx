import { render, screen, waitFor } from '@testing-library/react';
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

describe('MOMO Studio Stage 8 release-candidate shell', () => {
  it.each([
    ['/control', '控制'],
    ['/studio', '编排'],
    ['/library', '资源库'],
    ['/vision', '视觉'],
    ['/settings', '设置'],
  ])('provides the %s route', async (path, heading) => {
    mockStage3Backend();
    renderRoute(path);
    expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeVisible();
    expect(screen.getByText('MOMO Studio 0.1.0-rc1')).toBeVisible();
    expect(screen.getByText('仿真运行已验证')).toBeVisible();
    expect(screen.getByText('真实硬件现场验收待完成')).toBeVisible();
  });

  it('opens the active Studio timeline authoring workspace', async () => {
    mockStage3Backend();
    const view = renderRoute('/library');
    expect(await screen.findByText(/Stage 5 · 已编译的仿真播放/)).toBeVisible();
    view.unmount();
    renderRoute('/studio');
    expect(await screen.findByText('空白运动草稿')).toBeVisible();
    expect(screen.getByRole('button', { name: /捕获当前状态/ })).toBeVisible();
  });

  it('switches to V1 in Settings and exposes exactly the enabled joint set', async () => {
    const user = userEvent.setup();
    mockStage3Backend({ connected: false });
    renderRoute('/settings');
    expect(await screen.findByText('V2 · 一条直线导轨 + 五个旋转关节')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'V1' }));
    expect(await screen.findByText('V1 · 五个旋转关节 · 无直线导轨')).toBeVisible();
    expect(await screen.findByText('J11, J12, J13, J14, J15')).toBeVisible();
    expect(screen.queryByText('J10')).not.toBeInTheDocument();
  });

  it('renders V1 Control as five keyed joint cards without J10', async () => {
    mockStage3Backend({ variant: 'V1' });
    renderRoute('/control');
    expect(await screen.findByLabelText('J11 target (deg)')).toBeVisible();
    expect(screen.getAllByRole('article')).toHaveLength(5);
    expect(screen.queryByLabelText(/J10 target/)).not.toBeInTheDocument();
  });

  it('connects, performs a global motion stop, and disconnects the Dry Run robot', async () => {
    const user = userEvent.setup();
    const backend = mockStage3Backend({ connected: false });
    renderRoute('/control');
    expect(await screen.findByText('DISCONNECTED')).toBeVisible();

    await user.click(screen.getByRole('button', { name: '连接' }));
    expect(await screen.findByText('CONNECTED')).toBeVisible();
    await user.click(screen.getByRole('button', { name: '停止运动' }));
    await user.click(screen.getByRole('button', { name: '断开连接' }));
    expect(await screen.findByText('DISCONNECTED')).toBeVisible();

    expect(backend.requestsFor('/robot/connect')).toHaveLength(1);
    expect(backend.requestsFor('/motion/stop')).toHaveLength(1);
    expect(backend.requestsFor('/robot/disconnect')).toHaveLength(1);
  });

  it('renders the backend structured error message for a failed lifecycle action', async () => {
    const user = userEvent.setup();
    mockStage3Backend({ connected: false, connectError: true });
    renderRoute('/control');
    await screen.findByText('DISCONNECTED');
    await user.click(screen.getByRole('button', { name: '连接' }));
    expect(await screen.findByText(/The active Dry Run robot is already connected/)).toBeVisible();
  });

  it('preserves telemetry but disables motion when a later refresh becomes stale', async () => {
    const backend = mockStage3Backend();
    renderRoute('/control');
    expect(await screen.findByLabelText('J10 target (mm)')).toBeEnabled();
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
    expect(screen.getAllByText('DRY RUN').length).toBeGreaterThan(0);
    expect(screen.getByText('真实运动已禁用')).toBeVisible();
    expect(screen.getByRole('button', { name: '停止运动' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '移动到位姿' })).toBeDisabled();
  });
});
