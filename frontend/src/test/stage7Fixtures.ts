import { vi } from 'vitest';

import type {
  ControlMode,
  HardwareAccessPolicy,
  NormalizedBoundingBox,
  OperatorSessionScope,
  VisionStatus,
  VisionTrackingState,
} from '../api/types';
import { mockStage3Backend } from './stage3Fixtures';

const FRAME_ID = '77777777-7777-4777-8777-777777777777';
const LEASE_ID = '88888888-8888-4888-8888-888888888888';
const DETECTION_ID = '99999999-9999-4999-8999-999999999999';

function jsonResponse(body: unknown, ok = true, status = ok ? 200 : 500): Response {
  return {
    ok,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

interface Stage7Options {
  connected?: boolean;
  faceAvailable?: boolean;
  frameHeightPx?: number;
  frameWidthPx?: number;
  pollStatusGate?: Promise<void>;
  startGate?: Promise<void>;
  controlMode?: ControlMode;
  hardwareAccessPolicy?: HardwareAccessPolicy;
  realMotionEnabled?: boolean;
  realSessionScopes?: OperatorSessionScope[];
}

export function mockStage7Backend(options: Stage7Options = {}) {
  const base = mockStage3Backend({
    connected: options.connected ?? true,
    controlMode: options.controlMode,
    hardwareAccessPolicy: options.hardwareAccessPolicy,
    realMotionEnabled: options.realMotionEnabled,
    realSessionScopes: options.realSessionScopes,
  });
  let selection: { frame_id: string; bounding_box: NormalizedBoundingBox } | null = null;
  let trackingState: VisionTrackingState | null = null;
  let followActive = false;
  let followStopReason: string | null = null;
  let frameId = FRAME_ID;
  let sourceState = 'STREAMING';
  let visionStatusCalls = 0;
  let visionStatusAvailable = true;
  const requests: Array<{ path: string; method: string; body: unknown }> = [];
  const defaultBox = { x: 0.2, y: 0.25, width: 0.25, height: 0.35 };

  const status = (): VisionStatus => ({
    camera_access_policy: 'SYNTHETIC_ONLY',
    source_state: sourceState,
    latest_frame: {
      frame_id: frameId,
      width_px: options.frameWidthPx ?? 640,
      height_px: options.frameHeightPx ?? 360,
      captured_at: '2026-08-24T00:00:00Z',
      source_id: 'synthetic-primary',
      age_ms: 18,
    },
    selection,
    tracking: selection && trackingState ? {
      frame_id: frameId,
      source_id: 'synthetic-primary',
      captured_at: '2026-08-24T00:00:00Z',
      bounding_box: trackingState === 'LOCKED' ? selection.bounding_box : null,
      confidence: trackingState === 'LOCKED' ? 0.93 : 0,
      status: trackingState,
      error: trackingState === 'LOCKED' ? null : `Target ${trackingState.toLowerCase()}`,
    } : null,
    follow: {
      active: followActive,
      lease_id: followActive ? LEASE_ID : null,
      expires_at: followActive ? '2026-08-24T00:00:02Z' : null,
      stop_reason: followStopReason,
      error_x: followActive ? 0.16 : null,
      error_y: followActive ? -0.08 : null,
      ema_error_x: followActive ? 0.1 : null,
      ema_error_y: followActive ? -0.05 : null,
      last_command_id: followActive ? 'vision-command-1' : null,
    },
    robot_state: options.connected === false ? 'DISCONNECTED' : 'CONNECTED',
    dry_run: true,
    real_follow_blocked_reason: 'Real Follow requires Stage 8 field acceptance.',
  });

  const capability = (
    providerId: string,
    kind: string,
    available = true,
    active = available,
  ) => ({
    provider_id: providerId,
    kind,
    available,
    active,
    model_source: providerId.includes('synthetic') ? 'Built-in deterministic generator' : 'OpenCV built-in data',
    notice: 'Local provider; no network download.',
    reason: available ? null : 'Optional OpenCV provider is not installed.',
  });

  const capabilities = {
    camera_access_policy: 'SYNTHETIC_ONLY',
    source: capability('synthetic-frame-source', 'frame-source'),
    trackers: [capability('synthetic-tracker', 'tracker')],
    detectors: [
      capability('synthetic-person-detector', 'person-detector'),
      capability('opencv-haar-face', 'face-detector', options.faceAvailable ?? false, false),
    ],
    stream: capability('bounded-local-stream', 'stream'),
    real_follow_allowed: false,
    real_follow_blocked_reason: 'Real Follow requires Stage 8 field acceptance.',
  };

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const fullPath = String(input);
    const path = fullPath.replace(/^https?:\/\/[^/]+/, '').replace(/^\/api\/v1/, '');
    const method = init?.method ?? 'GET';
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined;
    if (!path.startsWith('/vision/')) return base.fetchMock(input, init);
    requests.push({ path, method, body });

    if (path === '/vision/capabilities') return jsonResponse(capabilities);
    if (path === '/vision/status') {
      visionStatusCalls += 1;
      if (visionStatusCalls > 1) await options.pollStatusGate;
      if (!visionStatusAvailable) {
        return jsonResponse({ code: 'VISION_STATUS_UNAVAILABLE', message: 'Vision status unavailable' }, false, 503);
      }
      return jsonResponse(status());
    }
    if (path === '/vision/selection' && method === 'POST') {
      const request = body as { frame_id: string; bounding_box: NormalizedBoundingBox };
      selection = { frame_id: request.frame_id, bounding_box: request.bounding_box };
      trackingState = 'LOCKED';
      followStopReason = null;
      return jsonResponse(status());
    }
    if (path === '/vision/selection' && method === 'DELETE') {
      selection = null;
      trackingState = null;
      followActive = false;
      followStopReason = 'TARGET_CLEARED';
      return jsonResponse(status());
    }
    if (path === '/vision/tracking/reset') {
      trackingState = selection ? 'LOCKED' : null;
      return jsonResponse(status());
    }
    if (path === '/vision/detect/person' || path === '/vision/detect/face') {
      const isFace = path.endsWith('/face');
      const provider = isFace ? capabilities.detectors[1] : capabilities.detectors[0];
      return jsonResponse({
        capability: provider,
        detections: provider.available ? [{
          detection_id: DETECTION_ID,
          frame_id: FRAME_ID,
          source_id: 'synthetic-primary',
          captured_at: '2026-08-24T00:00:00Z',
          bounding_box: defaultBox,
          confidence: 0.89,
          label: isFace ? 'face' : 'person',
        }] : [],
      });
    }
    if (path === '/vision/follow/start') {
      await options.startGate;
      followActive = true;
      followStopReason = null;
      return jsonResponse({ lease_id: LEASE_ID, expires_at: '2026-08-24T00:00:02Z', status: status() });
    }
    if (path === `/vision/follow/${LEASE_ID}/heartbeat`) {
      return jsonResponse({ lease_id: LEASE_ID, expires_at: '2026-08-24T00:00:02Z', status: status() });
    }
    if (path === `/vision/follow/${LEASE_ID}/stop`) {
      followActive = false;
      followStopReason = 'OPERATOR_STOP';
      return jsonResponse(status());
    }
    throw new Error(`Unhandled Vision request: ${method} ${path}`);
  });

  vi.stubGlobal('fetch', fetchMock);

  return {
    fetchMock,
    requests,
    status,
    selectDefaultTarget: () => {
      selection = { frame_id: FRAME_ID, bounding_box: defaultBox };
      trackingState = 'LOCKED';
    },
    setFrameId: (nextFrameId: string) => {
      frameId = nextFrameId;
    },
    setSourceState: (nextSourceState: string) => {
      sourceState = nextSourceState;
    },
    setVisionStatusAvailable: (available: boolean) => {
      visionStatusAvailable = available;
    },
    setTrackingState: (state: VisionTrackingState) => {
      if (!selection) selection = { frame_id: FRAME_ID, bounding_box: defaultBox };
      trackingState = state;
      if (state !== 'LOCKED') {
        followActive = false;
        followStopReason = `TARGET_${state}`;
      }
    },
    requestsFor: (path: string) => requests.filter((request) => request.path === path),
    lastBody: (path: string) => requests.filter((request) => request.path === path).at(-1)?.body,
    goOffline: base.goOffline,
  };
}

export const stage7Ids = { frameId: FRAME_ID, leaseId: LEASE_ID, detectionId: DETECTION_ID };
