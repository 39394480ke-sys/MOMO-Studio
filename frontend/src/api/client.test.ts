import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, getBootstrapData, normalizeCommandStatus, requestJson } from './client';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('API client errors', () => {
  it('propagates one abort signal through all six bootstrap requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({}),
    });
    vi.stubGlobal('fetch', fetchMock);
    const controller = new AbortController();

    await getBootstrapData(controller.signal);

    expect(fetchMock).toHaveBeenCalledTimes(6);
    expect(fetchMock.mock.calls.map(([, init]) => init?.signal)).toEqual(
      Array.from({ length: 6 }, () => controller.signal),
    );
  });

  it('preserves the structured backend error contract', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: vi.fn().mockResolvedValue({
        code: 'STALE_STATE_SEQUENCE',
        message: 'Robot state changed before preflight',
        details: { expected: 7, actual: 8 },
        request_id: 'request-409',
      }),
    }));

    const rejection = requestJson('/motion/joints').catch((error: unknown) => error);
    await expect(rejection).resolves.toBeInstanceOf(ApiError);
    await expect(rejection).resolves.toMatchObject({
      status: 409,
      code: 'STALE_STATE_SEQUENCE',
      message: 'Robot state changed before preflight',
      details: { expected: 7, actual: 8 },
      requestId: 'request-409',
    });
  });

  it('supports a FastAPI detail-wrapped error envelope', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: vi.fn().mockResolvedValue({
        detail: { code: 'INVALID_TARGET', message: 'Target is invalid', details: { joint_id: 'j10' } },
      }),
    }));

    await expect(requestJson('/motion/joints')).rejects.toMatchObject({
      status: 422,
      code: 'INVALID_TARGET',
      details: { joint_id: 'j10' },
    });
  });

  it('fails closed when command state is absent or malformed', () => {
    expect(() => normalizeCommandStatus({ command_id: 'command-without-state' }))
      .toThrow('invalid motion command state');
    expect(() => normalizeCommandStatus({ command_id: 'command', state: 'MYSTERY' }))
      .toThrow('invalid motion command state');
  });

  it.each([Number.NaN, Number.POSITIVE_INFINITY, -0.01, 1.01, '0.5'])(
    'fails closed for invalid command progress %s',
    (progress) => {
      expect(() => normalizeCommandStatus({ command_id: 'command', state: 'RUNNING', progress }))
        .toThrow('invalid motion command progress');
    },
  );

  it.each([0, 0.5, 1])('accepts bounded finite command progress %s', (progress) => {
    expect(normalizeCommandStatus({ command_id: 'command', state: 'RUNNING', progress }).progress)
      .toBe(progress);
  });
});
