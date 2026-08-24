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

describe('MOMO Studio Stage 7 shell', () => {
  it.each([
    ['/control', 'Control'],
    ['/studio', 'Studio'],
    ['/library', 'Library'],
    ['/vision', 'Vision'],
    ['/settings', 'Settings'],
  ])('provides the %s route', async (path, heading) => {
    mockStage3Backend();
    renderRoute(path);
    expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeVisible();
    expect(screen.getByText(/Stage 7\s*·\s*Safe Vision Following/)).toBeVisible();
  });

  it('opens the active Studio timeline authoring workspace', async () => {
    mockStage3Backend();
    const view = renderRoute('/library');
    expect(await screen.findByText(/Stage 5 · Compiled Dry Run playback/)).toBeVisible();
    view.unmount();
    renderRoute('/studio');
    expect(await screen.findByText('Blank Motion draft')).toBeVisible();
    expect(screen.getByRole('button', { name: /Capture current/ })).toBeVisible();
  });

  it('switches to V1 in Settings and exposes exactly the enabled joint set', async () => {
    const user = userEvent.setup();
    mockStage3Backend({ connected: false });
    renderRoute('/settings');
    expect(await screen.findByText('V2 · Linear rail plus five revolute joints')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'V1' }));
    expect(await screen.findByText('V1 · Five revolute joints · No linear rail')).toBeVisible();
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

    await user.click(screen.getByRole('button', { name: 'Connect' }));
    expect(await screen.findByText('CONNECTED')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'STOP MOTION' }));
    await user.click(screen.getByRole('button', { name: 'Disconnect' }));
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
    await user.click(screen.getByRole('button', { name: 'Connect' }));
    expect(await screen.findByText(/The active Dry Run robot is already connected/)).toBeVisible();
  });

  it('preserves telemetry but disables motion when a later refresh becomes stale', async () => {
    const backend = mockStage3Backend();
    renderRoute('/control');
    expect(await screen.findByLabelText('J10 target (mm)')).toBeEnabled();
    backend.goOffline();
    await waitFor(
      () => expect(screen.getByText('Backend unavailable · showing stale state')).toBeVisible(),
      { timeout: 1800 },
    );
    expect(screen.getByLabelText('J10 target (mm)')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Move all joints' })).toBeDisabled();
  });

  it('uses a truthful safe fallback and disables all motion when initially offline', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    vi.stubGlobal('WebSocket', undefined);
    renderRoute('/control');
    expect((await screen.findAllByText('Backend unavailable')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('DRY RUN').length).toBeGreaterThan(0);
    expect(screen.getByText('Real motion disabled')).toBeVisible();
    expect(screen.getByRole('button', { name: 'STOP MOTION' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Move Pose' })).toBeDisabled();
  });
});
