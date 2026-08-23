import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  ApiError,
  deleteMotion,
  deletePose,
  duplicatePose,
  getBootstrapData,
  getPoses,
  normalizeCommandStatus,
  requestJson,
} from './client';

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

  it('resolves successful 204 deletes without trying to parse an empty body', async () => {
    const json = vi.fn();
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204, json });
    vi.stubGlobal('fetch', fetchMock);

    await expect(deletePose('11111111-1111-4111-8111-111111111111', 7)).resolves.toBeUndefined();
    await expect(deleteMotion('22222222-2222-4222-8222-222222222222', 3)).resolves.toBeUndefined();

    expect(json).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/v1/poses/11111111-1111-4111-8111-111111111111?expected_revision=7',
      expect.objectContaining({ method: 'DELETE' }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/motions/22222222-2222-4222-8222-222222222222?expected_revision=3',
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('bounds list pages and sends stable repeated tag filters', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ items: [], page: 1, page_size: 50, total: 0 }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await getPoses({
      page: -4,
      page_size: 500,
      search: '  inspection  ',
      tags: [' demo ', 'demo', 'arm'],
      sort: 'name',
      order: 'asc',
    });

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/poses?page=1&page_size=50&sort=name&order=asc&search=inspection&tag=demo&tag=arm',
      expect.objectContaining({ signal: undefined }),
    );
  });

  it('posts expected_revision when duplicating a UUID-addressed Pose', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: vi.fn().mockResolvedValue({}),
    });
    vi.stubGlobal('fetch', fetchMock);

    await duplicatePose('33333333-3333-4333-8333-333333333333', {
      expected_revision: 9,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/poses/33333333-3333-4333-8333-333333333333/duplicate',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ expected_revision: 9 }),
      }),
    );
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
