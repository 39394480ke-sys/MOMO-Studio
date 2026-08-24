import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  clearVisionTarget,
  detectVisionTarget,
  getVisionCapabilities,
  getVisionStatus,
  heartbeatVisionFollow,
  selectVisionTarget,
  startVisionFollow,
  stopVisionFollow,
} from './client';

const FRAME_ID = '11111111-1111-4111-8111-111111111111';
const LEASE_ID = '22222222-2222-4222-8222-222222222222';

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

function capability(providerId: string, kind: string) {
  return {
    provider_id: providerId,
    kind,
    available: true,
    active: true,
    model_source: 'Built in',
    notice: 'No network download.',
    reason: null,
  };
}

function status() {
  return {
    camera_access_policy: 'SYNTHETIC_ONLY',
    source_state: 'STREAMING',
    latest_frame: {
      frame_id: FRAME_ID,
      width_px: 640,
      height_px: 360,
      captured_at: '2026-08-24T00:00:00Z',
      source_id: 'synthetic',
      age_ms: 25,
    },
    selection: null,
    tracking: null,
    follow: {
      active: false,
      lease_id: null,
      expires_at: null,
      stop_reason: null,
      error_x: null,
      error_y: null,
      ema_error_x: null,
      ema_error_y: null,
      last_command_id: null,
    },
    robot_state: 'CONNECTED',
    dry_run: true,
    real_follow_blocked_reason: 'Field acceptance required.',
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('Stage 7 Vision API client', () => {
  it('normalizes honest capabilities and bounded status metadata', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({
        camera_access_policy: 'SYNTHETIC_ONLY',
        source: capability('synthetic', 'frame-source'),
        trackers: [capability('tracker', 'tracker')],
        detectors: [capability('person', 'person-detector')],
        stream: capability('stream', 'stream'),
        real_follow_allowed: false,
        real_follow_blocked_reason: 'Field acceptance required.',
      }))
      .mockResolvedValueOnce(response(status()));
    vi.stubGlobal('fetch', fetchMock);

    const capabilities = await getVisionCapabilities();
    const current = await getVisionStatus();
    expect(capabilities.real_follow_allowed).toBe(false);
    expect(capabilities.source.provider_id).toBe('synthetic');
    expect(current.latest_frame).toEqual(expect.objectContaining({
      frame_id: FRAME_ID,
      width_px: 640,
      height_px: 360,
      age_ms: 25,
    }));
  });

  it('uses exact frame-bound ROI, detector, lease heartbeat, and Stop routes', async () => {
    const requests: Array<{ path: string; method: string; body: unknown }> = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).replace('/api/v1', '');
      const method = init?.method ?? 'GET';
      const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined;
      requests.push({ path, method, body });
      if (path === '/vision/detect/person') {
        return response({ capability: capability('person', 'person-detector'), detections: [] });
      }
      if (path === '/vision/follow/start' || path.endsWith('/heartbeat')) {
        return response({ lease_id: LEASE_ID, expires_at: '2026-08-24T00:00:02Z', status: status() });
      }
      return response(status());
    }));

    const box = { x: 0.1, y: 0.2, width: 0.3, height: 0.4 };
    await selectVisionTarget(FRAME_ID, box);
    await clearVisionTarget();
    await detectVisionTarget('person', FRAME_ID);
    await startVisionFollow({
      configuration: {
        dead_zone_x: 0.08, dead_zone_y: 0.08, ema_alpha: 0.35, gain: 0.5,
        max_step: 2, max_rate: 4, confidence_threshold: 0.55,
        frame_freshness_limit_s: 0.75, target_lost_limit_s: 0.5, lease_ttl_s: 2,
      },
      mapping: {
        pan_joint: 'pan', tilt_joint: 'tilt', pan_sign: 1, tilt_sign: -1,
        verification_status: 'VERIFIED_FOR_DRY_RUN',
      },
    });
    await heartbeatVisionFollow(LEASE_ID);
    await stopVisionFollow(LEASE_ID);

    expect(requests[0]).toEqual({
      path: '/vision/selection', method: 'POST', body: { frame_id: FRAME_ID, bounding_box: box },
    });
    expect(requests[1]).toEqual({ path: '/vision/selection', method: 'DELETE', body: undefined });
    expect(requests[2]).toEqual({
      path: '/vision/detect/person', method: 'POST', body: { frame_id: FRAME_ID },
    });
    expect(requests[4]).toEqual({
      path: `/vision/follow/${LEASE_ID}/heartbeat`, method: 'POST', body: {},
    });
    expect(requests[5]).toEqual({
      path: `/vision/follow/${LEASE_ID}/stop`, method: 'POST', body: {},
    });
  });

  it('rejects unsafe capability claims and malformed normalized boxes', async () => {
    const unsafeCapabilities = {
      camera_access_policy: 'SYNTHETIC_ONLY',
      source: capability('synthetic', 'frame-source'),
      trackers: [], detectors: [], stream: capability('stream', 'stream'),
      real_follow_allowed: true,
      real_follow_blocked_reason: 'none',
    };
    const malformedStatus = {
      ...status(),
      selection: { frame_id: FRAME_ID, bounding_box: { x: 0.9, y: 0, width: 0.2, height: 0.5 } },
    };
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(response(unsafeCapabilities))
      .mockResolvedValueOnce(response(malformedStatus)));

    await expect(getVisionCapabilities()).rejects.toThrow(/invalid Vision capabilities/);
    await expect(getVisionStatus()).rejects.toThrow(/out-of-range Vision selection box/);
  });

  it('rejects out-of-range confidence and an active Follow without a stoppable lease', async () => {
    const invalidConfidence = {
      ...status(),
      tracking: {
        frame_id: FRAME_ID,
        source_id: 'synthetic',
        captured_at: '2026-08-24T00:00:00Z',
        bounding_box: { x: 0.1, y: 0.1, width: 0.2, height: 0.2 },
        confidence: 1.1,
        status: 'LOCKED',
        error: null,
      },
    };
    const missingLease = {
      ...status(),
      follow: { ...status().follow, active: true },
    };
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(response(invalidConfidence))
      .mockResolvedValueOnce(response(missingLease)));

    await expect(getVisionStatus()).rejects.toThrow(/tracking confidence/);
    await expect(getVisionStatus()).rejects.toThrow(/active Follow without a lease/);
  });
});
