import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  ApiError,
  createLanSecuritySession,
  deleteMotion,
  deletePose,
  duplicatePose,
  getBootstrapData,
  getPoses,
  normalizeCommandStatus,
  normalizePlaybackStatus,
  normalizeTrajectoryPreflight,
  normalizeTrajectoryPreview,
  pausePlayback,
  playMotion,
  requestJson,
  revokeLanSecuritySession,
  resumePlayback,
  setPlaybackLoop,
  setPlaybackRate,
  stopPlayback,
} from './client';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('API client errors', () => {
  it('always includes HttpOnly-cookie credentials and does not allow a caller override', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ ok: true }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await requestJson('/health', { credentials: 'omit' });

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/health',
      expect.objectContaining({ credentials: 'include' }),
    );
  });

  it('exchanges a bearer for non-secret cookie metadata and revokes via the cookie', async () => {
    const bearer = 'lan-session-exchange-token-material-0123456789';
    const json = vi.fn().mockResolvedValue({
      principal_id: 'operator',
      issued_at: '2026-08-24T01:00:00Z',
      expires_at: '2026-08-24T01:05:00Z',
      surfaces: ['REST', 'CONTROL', 'WEBSOCKET', 'VISION'],
      session_token: 'must-not-reach-javascript',
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json })
      .mockResolvedValueOnce({ ok: true, status: 204, json: vi.fn() });
    vi.stubGlobal('fetch', fetchMock);

    const session = await createLanSecuritySession(bearer);
    await revokeLanSecuritySession();

    expect(session).toEqual({
      principal_id: 'operator',
      issued_at: '2026-08-24T01:00:00Z',
      expires_at: '2026-08-24T01:05:00Z',
      surfaces: ['REST', 'CONTROL', 'WEBSOCKET', 'VISION'],
    });
    expect(session).not.toHaveProperty('session_token');
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/v1/security/session',
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        headers: expect.objectContaining({ Authorization: `Bearer ${bearer}` }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/security/session',
      expect.objectContaining({ method: 'DELETE', credentials: 'include' }),
    );
  });

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

  it('uses the exact playback control paths and bounded request bodies', async () => {
    const playbackResponse = {
      session_id: 'session-id',
      state: 'PLAYING',
      motion_id: 'motion-id',
      trajectory_digest: 'sha256:trajectory',
      progress: 0,
      elapsed_s: 0,
      duration_s: 2,
      current_keyframe_id: null,
      current_segment_index: 0,
      current_sample_index: 0,
      loop: false,
      rate: 1,
      error: null,
      updated_at: '2026-08-24T00:00:00Z',
      hardware_accessed: false,
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue(playbackResponse),
    });
    vi.stubGlobal('fetch', fetchMock);

    await playMotion('motion/id', {
      expected_revision: 7,
      trajectory_digest: 'sha256:digest/value',
      loop: true,
      rate: 1.5,
    });
    await pausePlayback();
    await resumePlayback();
    await stopPlayback();
    await setPlaybackRate(2);
    await setPlaybackLoop(false);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/v1/motions/motion%2Fid/play',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          expected_revision: 7,
          trajectory_digest: 'sha256:digest/value',
          loop: true,
          rate: 1.5,
        }),
      }),
    );
    expect(fetchMock.mock.calls.slice(1).map(([path, init]) => [path, init?.method, init?.body])).toEqual([
      ['/api/v1/playback/pause', 'POST', undefined],
      ['/api/v1/playback/resume', 'POST', undefined],
      ['/api/v1/playback/stop', 'POST', undefined],
      ['/api/v1/playback/rate', 'PUT', JSON.stringify({ rate: 2 })],
      ['/api/v1/playback/loop', 'PUT', JSON.stringify({ loop: false })],
    ]);
    expect(() => setPlaybackRate(0.24)).toThrow('between 0.25× and 2×');
    expect(() => setPlaybackRate(2.01)).toThrow('between 0.25× and 2×');
  });

  it('normalizes a digest-bound trajectory preflight and fails closed on inconsistent output', () => {
    const report = {
      passed: true,
      digest: 'sha256:trajectory',
      motion_id: 'motion-id',
      motion_revision: 4,
      duration_s: 2.5,
      sample_count: 51,
      segment_count: 2,
      sample_rate_hz: 20,
      violations: [],
      checks: [{ name: 'limits', passed: true, detail: 'All samples pass' }],
    };
    expect(normalizeTrajectoryPreflight(report)).toMatchObject(report);
    expect(() => normalizeTrajectoryPreflight({ ...report, digest: null })).toThrow(
      'missing its digest',
    );
    expect(() => normalizeTrajectoryPreflight({ ...report, passed: false })).toThrow(
      'must not include a digest',
    );
  });

  it('rejects malformed or hardware-touching playback status at the client boundary', () => {
    const status = {
      session_id: 'session-id',
      state: 'PLAYING',
      motion_id: 'motion-id',
      trajectory_digest: 'sha256:trajectory',
      progress: 0.42,
      elapsed_s: 1,
      duration_s: 2.5,
      current_keyframe_id: 'keyframe-id',
      current_segment_index: 0,
      current_sample_index: 20,
      loop: false,
      rate: 1.5,
      error: null,
      updated_at: '2026-08-24T00:00:00Z',
      hardware_accessed: false,
    };
    expect(normalizePlaybackStatus(status)).toMatchObject(status);
    expect(() => normalizePlaybackStatus({ ...status, state: 'UNKNOWN' })).toThrow(
      'invalid playback state',
    );
    expect(() => normalizePlaybackStatus({ ...status, progress: 1.01 })).toThrow(
      'invalid playback progress',
    );
    expect(normalizePlaybackStatus({ ...status, hardware_accessed: true })).toMatchObject({
      hardware_accessed: true,
    });
    expect(() => normalizePlaybackStatus({ ...status, hardware_accessed: 'yes' })).toThrow(
      'invalid playback status',
    );
  });

  it('normalizes signed joint/TCP preview samples and clean segment markers', () => {
    const preview = normalizeTrajectoryPreview({
      digest: 'sha256:trajectory',
      motion_id: 'motion-id',
      duration_s: 1,
      sample_rate_hz: 20,
      sample_count: 2,
      segments: [{
        segment_index: 0,
        motion_mode: 'CARTESIAN_LINEAR',
        start_time_s: 0,
        end_time_s: 1,
        sample_count: 2,
        start_keyframe_id: 'start',
        end_keyframe_id: 'end',
      }],
      joint_series: { j11: [{ time_s: 0, value: -42, unit: 'deg' }] },
      tcp_path: [{ time_s: 0, x_mm: -10, y_mm: 20, z_mm: -30 }],
      keyframe_markers: [{ keyframe_id: 'start', label: 'Start', time_s: 0, sample_index: 0 }],
    });
    expect(preview.joint_series.j11[0]?.value).toBe(-42);
    expect(preview.tcp_path[0]).toMatchObject({ x_mm: -10, y_mm: 20, z_mm: -30 });
    expect(preview.segments[0]?.motion_mode).toBe('CARTESIAN_LINEAR');
  });
});
