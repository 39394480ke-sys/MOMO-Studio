import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AppContent } from './App';

const healthyResponse = {
  status: 'ok',
  product: 'MOMO Studio',
  version: '0.1.0',
  control_mode: 'DRY_RUN',
  real_motion_enabled: false,
};

const metaResponse = {
  product: 'MOMO Studio',
  version: '0.1.0',
  api_version: 'v1',
  stage: 1,
  active_robot_variant: 'V2',
  supported_robot_variants: ['V1', 'V2'],
  supported_control_modes: ['DRY_RUN', 'REAL'],
  real_motion_enabled: false,
};

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

function mockBackendOnline() {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(jsonResponse(healthyResponse))
    .mockResolvedValueOnce(jsonResponse(metaResponse));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

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

describe('MOMO Studio app shell', () => {
  it('renders the app and redirects the default route to Control', async () => {
    mockBackendOnline();
    renderRoute('/');

    expect(await screen.findByRole('heading', { level: 1, name: 'Control' })).toBeVisible();
    expect(screen.getByLabelText('Primary navigation')).toBeVisible();
  });

  it.each([
    ['/control', 'Control'],
    ['/studio', 'Studio'],
    ['/library', 'Library'],
    ['/vision', 'Vision'],
    ['/settings', 'Settings'],
  ])('provides the %s route', async (path, heading) => {
    mockBackendOnline();
    renderRoute(path);

    expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeVisible();
  });

  it('shows the backend online state after both bootstrap requests succeed', async () => {
    const fetchMock = mockBackendOnline();
    renderRoute('/control');

    expect(await screen.findByText('Backend connected')).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/health', expect.any(Object));
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/meta', expect.any(Object));
  });

  it('shows Backend unavailable when bootstrap fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    renderRoute('/control');

    expect(await screen.findByText('Backend unavailable')).toBeVisible();
  });

  it('uses the safe Stage 1 status while the backend is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    renderRoute('/control');

    expect(screen.getByText('DRY RUN')).toBeVisible();
    expect(screen.getByText('Real motion disabled')).toBeVisible();
    await screen.findByText('Backend unavailable');
  });

  it('rejects an unsafe backend status and keeps the safe fallback visible', async () => {
    const unsafeHealth = {
      ...healthyResponse,
      control_mode: 'REAL',
      real_motion_enabled: true,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(unsafeHealth))
      .mockResolvedValueOnce(jsonResponse(metaResponse));
    vi.stubGlobal('fetch', fetchMock);
    renderRoute('/control');

    expect(await screen.findByText('Backend unavailable')).toBeVisible();
    expect(screen.getByText('DRY RUN')).toBeVisible();
    expect(screen.getByText('Real motion disabled')).toBeVisible();
  });

  it.each(['/control', '/studio', '/library', '/vision', '/settings'])(
    'contains no prohibited entries or real-motion enable operation on %s',
    async (path) => {
      mockBackendOnline();
      renderRoute(path);
      await screen.findByText('Backend connected');

      const visibleText = document.body.textContent ?? '';
      const prohibitedEntries = [
        /\bmulti-arm\b/i,
        /\bphoto\b/i,
        /\bvideo\b/i,
        /\bAI\b/,
        /\bvoice\b/i,
        /\bgesture\b/i,
        /\bgripper\b/i,
        /\bteach\b/i,
        /\bPyBullet\b/i,
      ];

      for (const entry of prohibitedEntries) {
        expect(visibleText).not.toMatch(entry);
      }
      expect(screen.queryByRole('button', { name: /real motion/i })).not.toBeInTheDocument();
      expect(screen.queryByRole('link', { name: /real motion/i })).not.toBeInTheDocument();
      await waitFor(() => expect(screen.getByText('Real motion disabled')).toBeVisible());
    },
  );
});
