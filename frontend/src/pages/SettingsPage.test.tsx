import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AppContent } from '../app/App';
import { mockStage7Backend } from '../test/stage7Fixtures';

function renderSettings() {
  return render(
    <MemoryRouter initialEntries={['/settings']}>
      <AppContent />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('Settings product center', () => {
  it('renders every product section from real runtime fields without inventing unavailable device data', async () => {
    const backend = mockStage7Backend();
    renderSettings();

    for (const heading of ['设备', '关节与运动', '标定', '相机', '网络与服务', '安全', '高级']) {
      expect(await screen.findByRole('heading', { name: heading })).toBeVisible();
    }

    const device = screen.getByRole('heading', { name: '设备' }).closest('section');
    expect(device).not.toBeNull();
    expect(within(device as HTMLElement).getAllByText('未配置').length).toBeGreaterThanOrEqual(2);
    expect(within(device as HTMLElement).getByText('当前版本暂不支持')).toBeVisible();

    expect(await screen.findByText('synthetic-frame-source')).toBeVisible();
    expect(screen.getByText('当前会话仅使用内存合成画面；不会枚举、打开或录制本机摄像头。')).toBeVisible();
    expect(screen.queryByText(/USB Camera|Built-in Camera/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '零点快速标定' })).toBeDisabled();
    expect(screen.getByRole('button', { name: /打开关节设置/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: '重启服务' })).toBeDisabled();

    expect(backend.requestsFor('/vision/camera/open')).toHaveLength(0);
    expect(backend.requestsFor('/vision/camera/close')).toHaveLength(0);
    expect(backend.requestsFor('/vision/follow/start')).toHaveLength(0);
  });

  it('keeps compatibility facts but removes the second hardware-control surface', async () => {
    const user = userEvent.setup();
    mockStage7Backend();
    renderSettings();
    await screen.findByRole('heading', { name: '设备' });

    const advanced = screen.getByText('高级 · 配置与标定兼容性').closest('details');
    expect(advanced).not.toHaveAttribute('open');

    await user.click(screen.getByRole('button', { name: '完整标定' }));
    await waitFor(() => expect(advanced).toHaveAttribute('open'));
    expect(screen.getByText(/不提供第二套设备连接或运动入口/)).toBeVisible();
    expect(screen.queryByRole('button', { name: '只读连接' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'V2 连接与方向验收' })).not.toBeInTheDocument();
  });

  it('switches to the configured REAL workspace only after explicit safety confirmation', async () => {
    const user = userEvent.setup();
    const backend = mockStage7Backend({ connected: false });
    renderSettings();

    const real = await screen.findByRole('button', { name: 'REAL' });
    expect(real).toBeEnabled();
    await user.click(real);

    const dialog = screen.getByRole('dialog', { name: '切换到 REAL' });
    const submit = within(dialog).getByRole('button', { name: '切换并重启' });
    expect(submit).toBeDisabled();
    await user.click(within(dialog).getByRole('checkbox', { name: '物理急停已就绪' }));
    await user.click(within(dialog).getByRole('checkbox', { name: '机械臂工作区已清空' }));
    expect(submit).toBeEnabled();
    await user.click(submit);

    await waitFor(() => expect(backend.requestsFor('/runtime/mode')).toHaveLength(3));
    const modeRequest = backend.requestsFor('/runtime/mode').find(
      (request) => 'init' in request && request.init?.method === 'POST',
    );
    expect(modeRequest?.body).toEqual({
      target_mode: 'REAL',
      confirm_robot_disconnected: true,
      confirm_physical_estop_ready: true,
      confirm_workspace_clear: true,
    });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByText('真机生产控制')).toBeVisible();
  });
});
