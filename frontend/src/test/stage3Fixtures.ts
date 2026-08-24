import { vi } from 'vitest';

import type { MotionCommandState, MotionStopResponse, RobotVariant } from '../api/types';

const PROFILE_FINGERPRINT = 'a'.repeat(64);
const KINEMATICS_FINGERPRINT = 'b'.repeat(64);
const COMMAND_ID = '11111111-1111-4111-8111-111111111111';
const JOG_SESSION_ID = '22222222-2222-4222-8222-222222222222';

function definition(jointId: string, unit: 'mm' | 'deg') {
  return {
    joint_id: jointId,
    joint_type: unit === 'mm' ? 'PRISMATIC' : 'REVOLUTE',
    domain_unit: unit,
    minimum: unit === 'mm' ? 0 : -180,
    maximum: unit === 'mm' ? 500 : 180,
    home: 0,
    servo_id: null,
    motor_degrees_per_domain_unit: null,
    raw_counts_per_motor_revolution: 4096,
    direction: 1,
    operating_mode: 'MULTI_TURN',
    home_present_raw: null,
    raw_bounds: null,
    raw_reachable: false,
  };
}

export const v2Profile = {
  schema_version: '1.0.0',
  variant: 'V2',
  display_name: 'MOMO V2 Example',
  has_linear_rail: true,
  enabled_joints: ['j10', 'j11', 'j12', 'j13', 'j14', 'j15'],
  joint_definitions: [
    definition('j10', 'mm'),
    ...['j11', 'j12', 'j13', 'j14', 'j15'].map((jointId) => definition(jointId, 'deg')),
  ],
  urdf_reference: null,
  tcp_link: 'tool0',
  template: true,
  verification_status: 'VERIFIED_FOR_DRY_RUN',
  source: 'example',
  source_revision: 'stage-3',
  description: 'example',
};

export const v1Profile = {
  ...v2Profile,
  variant: 'V1',
  display_name: 'MOMO V1 Example',
  has_linear_rail: false,
  enabled_joints: ['j11', 'j12', 'j13', 'j14', 'j15'],
  joint_definitions: v2Profile.joint_definitions.slice(1),
};

export function robotFor(variant: RobotVariant, connected: boolean) {
  const jointIds = variant === 'V2' ? v2Profile.enabled_joints : v1Profile.enabled_joints;
  return {
    robot_id: 'primary',
    variant,
    control_mode: 'DRY_RUN',
    hardware_access_policy: 'DISABLED',
    connection_state: connected ? 'CONNECTED' : 'DISCONNECTED',
    connected,
    profile_fingerprint: PROFILE_FINGERPRINT,
    profile_verification_status: 'VERIFIED_FOR_DRY_RUN',
    calibration_status: 'TEMPLATE_ONLY',
    positions: Object.fromEntries(jointIds.map((jointId) => [jointId, 0])),
    units: Object.fromEntries(jointIds.map((jointId) => [jointId, jointId === 'j10' ? 'mm' : 'deg'])),
    raw_positions: null,
    last_error: null,
    updated_at: '2026-08-24T00:00:00Z',
    state_sequence: connected ? 7 : 0,
    hardware_accessed: false,
    stale: false,
  };
}

export const preflight = {
  accepted: true,
  command_id: COMMAND_ID,
  checks: [
    { name: 'operator_intent', passed: true, detail: 'Explicit Control command' },
    { name: 'limits', passed: true, detail: 'Target is within the active profile' },
  ],
  warnings: ['Dry Run only'],
  profile_fingerprint: PROFILE_FINGERPRINT,
  kinematics_fingerprint: KINEMATICS_FINGERPRINT,
};

function jsonResponse(body: unknown, ok = true, status = ok ? 200 : 500): Response {
  return {
    ok,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

interface MockBackendOptions {
  variant?: RobotVariant;
  connected?: boolean;
  motionState?: MotionCommandState;
  polledCommandStates?: MotionCommandState[];
  connectError?: boolean;
  disconnectGate?: Promise<void>;
  heartbeatError?: boolean;
  ikError?: boolean;
  ikSuccess?: boolean;
  preflightReject?: boolean;
  robotStale?: boolean;
  stopResult?: MotionStopResponse['result'];
}

interface RecordedRequest {
  path: string;
  init: RequestInit | undefined;
  body: unknown;
}

export function mockStage3Backend(options: MockBackendOptions = {}) {
  let variant = options.variant ?? 'V2';
  let currentRobot = robotFor(variant, options.connected ?? true);
  if (options.robotStale !== undefined) {
    currentRobot = { ...currentRobot, stale: options.robotStale };
  }
  let offline = false;
  let pollIndex = 0;
  let motionStopped = false;
  let draftRevision = 1;
  const draftId = '66666666-6666-4666-8666-666666666666';
  const requests: RecordedRequest[] = [];

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const fullPath = String(input);
    const path = fullPath.replace(/^https?:\/\/[^/]+/, '').replace(/^\/api\/v1/, '');
    let body: unknown = undefined;
    if (typeof init?.body === 'string') body = JSON.parse(init.body);
    requests.push({ path, init, body });
    if (offline) throw new Error('offline');

    if (path === '/health') {
      return jsonResponse({
        status: 'ok', product: 'MOMO Studio', version: '0.1.0-rc1', stage: 8,
        control_mode: 'DRY_RUN', hardware_access_policy: 'DISABLED', real_motion_enabled: false,
      });
    }
    if (path === '/meta') {
      return jsonResponse({
        product: 'MOMO Studio', version: '0.1.0-rc1', api_version: 'v1', stage: 8,
        release_status: 'FIELD_ACCEPTANCE_REQUIRED', dry_run_validated: true,
        real_hardware_field_acceptance: 'PENDING',
        active_robot_variant: variant, supported_robot_variants: ['V1', 'V2'],
        supported_control_modes: ['DRY_RUN', 'REAL'], active_control_mode: 'DRY_RUN',
        hardware_access_policy: 'DISABLED', real_motion_enabled: false,
      });
    }
    if (path === '/robot/profile') {
      return jsonResponse({
        profile: variant === 'V2' ? v2Profile : v1Profile,
        fingerprint: PROFILE_FINGERPRINT,
        kinematics_fingerprint: KINEMATICS_FINGERPRINT,
        real_eligible: false,
      });
    }
    if (path === '/calibration/status') {
      return jsonResponse({
        status: 'TEMPLATE_ONLY', configured: true, template: true, variant_match: true,
        profile_match: true, joint_set_match: true, mapping_match: true, complete: true,
        calibration_valid: true, real_readiness: 'BLOCKED_BY_STAGE_POLICY',
        blocking_reasons: ['Stage 4 remains Dry Run only'],
      });
    }
    if (path === '/robot/diagnostics') {
      return jsonResponse({
        hardware_access_policy: 'DISABLED', runtime_state_path: 'data/runtime/robots/primary.json',
        runtime_state_valid: true, runtime_state_diagnostic: 'No saved runtime state',
        quarantined_runtime_file: null, backend_version: '0.1.0',
        legacy_source_commit: 'ff8bbda0c2222cb57951c7913f7f12f5777b98fa',
        stage_policy: 'STAGE_4_DRY_RUN_ONLY', active_profile_fingerprint: PROFILE_FINGERPRINT,
        active_kinematics_fingerprint: KINEMATICS_FINGERPRINT, hardware_accessed: false,
      });
    }
    if (path === '/robot/fk') {
      return jsonResponse({
        robot_id: 'primary', variant, state_sequence: currentRobot.state_sequence,
        profile_fingerprint: PROFILE_FINGERPRINT,
        kinematics_fingerprint: KINEMATICS_FINGERPRINT,
        tcp_pose: {
          frame: 'base', position_mm: { x: 101, y: 202, z: 303 },
          orientation_quaternion_xyzw: { x: 0, y: 0, z: 0, w: 1 },
        },
        hardware_accessed: false,
      });
    }
    if (path === '/robot/connect') {
      if (options.connectError) {
        return jsonResponse({
          code: 'ALREADY_CONNECTED',
          message: 'The active Dry Run robot is already connected',
          details: { robot_id: 'primary' },
          request_id: 'request-123',
        }, false, 409);
      }
      currentRobot = { ...currentRobot, connected: true, connection_state: 'CONNECTED', state_sequence: 7 };
      return jsonResponse({ status: currentRobot, hardware_accessed: false });
    }
    if (path === '/robot/disconnect') {
      await options.disconnectGate;
      currentRobot = { ...currentRobot, connected: false, connection_state: 'DISCONNECTED', state_sequence: 9 };
      return jsonResponse({ status: currentRobot, hardware_accessed: false });
    }
    if (path === '/robot/stop') {
      return jsonResponse({ result: 'STOPPED', status: currentRobot, hardware_accessed: false });
    }
    if (path === '/robot/variant') {
      const next = body as { variant: RobotVariant };
      variant = next.variant;
      currentRobot = robotFor(variant, false);
      return jsonResponse({ status: currentRobot, hardware_accessed: false });
    }
    if (path === '/robot') return jsonResponse(currentRobot);

    if (path.startsWith('/poses?')) {
      return jsonResponse({ items: [], page: 1, page_size: 24, total: 0 });
    }
    if (path.startsWith('/motions?')) {
      return jsonResponse({ items: [], page: 1, page_size: 24, total: 0 });
    }
    if (path.startsWith('/studio/drafts?')) {
      return jsonResponse({ items: [], page: 1, page_size: 20, total: 0 });
    }
    if (path === '/studio/drafts' && (init?.method ?? 'GET') === 'POST') {
      const request = body as Record<string, unknown>;
      return jsonResponse({
        schema_version: '1.0.0',
        id: draftId,
        source_motion_id: null,
        source_motion_revision: null,
        name: request.name ?? 'Untitled Motion',
        description: request.description ?? '',
        robot_variant: request.robot_variant ?? variant,
        keyframes: request.keyframes ?? [],
        playback_defaults: request.playback_defaults ?? { loop: false, speed_multiplier: 1 },
        tags: request.tags ?? [],
        editor_metadata: request.editor_metadata ?? {
          selected_keyframe_id: null,
          playhead_s: 0,
          timeline_zoom: 1,
          timeline_scroll_s: 0,
          default_edges: [],
        },
        revision: draftRevision,
        created_at: '2026-08-24T00:00:00Z',
        updated_at: '2026-08-24T00:00:00Z',
      }, true, 201);
    }
    if (path === `/studio/drafts/${draftId}` && init?.method === 'PUT') {
      const request = body as Record<string, unknown>;
      draftRevision += 1;
      return jsonResponse({
        schema_version: '1.0.0', id: draftId,
        source_motion_id: null, source_motion_revision: null,
        name: request.name, description: request.description, robot_variant: request.robot_variant,
        keyframes: request.keyframes, playback_defaults: request.playback_defaults,
        tags: request.tags, editor_metadata: request.editor_metadata,
        revision: draftRevision, created_at: '2026-08-24T00:00:00Z',
        updated_at: '2026-08-24T00:00:01Z',
      });
    }

    if (path === '/kinematics/ik') {
      if (options.ikError) {
        return jsonResponse({
          code: 'IK_INVALID_TARGET', message: 'IK target is outside the provisional workspace',
          details: { axis: 'z' }, request_id: 'ik-request',
        }, false, 422);
      }
      const success = options.ikSuccess ?? true;
      return jsonResponse({
        success,
        joint_state_optional: success
          ? { positions: currentRobot.positions, units: currentRobot.units }
          : null,
        best_joint_state: { positions: currentRobot.positions, units: currentRobot.units },
        iterations: 4,
        position_error_mm: success ? 0.02 : 42,
        orientation_error_deg: success ? 0.01 : 18,
        termination_reason: success ? 'CONVERGED' : 'UNREACHABLE',
        warnings: success ? [] : ['No solution within limits'],
        kinematics_fingerprint: KINEMATICS_FINGERPRINT,
      });
    }
    if (path === '/motion/jog/start') {
      return jsonResponse({
        jog_session_id: JOG_SESSION_ID,
        command_id: COMMAND_ID,
        lease_expires_in_ms: 500,
        status: 'RUNNING',
      }, true, 202);
    }
    if (path === `/motion/jog/${JOG_SESSION_ID}/heartbeat`) {
      if (options.heartbeatError) {
        return jsonResponse({ code: 'JOG_LEASE_EXPIRED', message: 'Jog lease expired', details: {} }, false, 409);
      }
      return jsonResponse({
        jog_session_id: JOG_SESSION_ID,
        command_id: COMMAND_ID,
        lease_expires_in_ms: 500,
        status: 'RUNNING',
      });
    }
    if (path === `/motion/jog/${JOG_SESSION_ID}/stop`) {
      return jsonResponse({ jog_session_id: JOG_SESSION_ID, stopped: true, status: 'CANCELLED' });
    }
    if (path.startsWith('/motion/commands/')) {
      const states = options.polledCommandStates ?? ['COMPLETED'];
      const state = motionStopped ? 'CANCELLED' : states[Math.min(pollIndex, states.length - 1)];
      pollIndex += 1;
      return jsonResponse({
        command_id: COMMAND_ID,
        state,
        progress: state === 'COMPLETED' ? 1 : 0.35,
        preflight,
        error: null,
        started_at: '2026-08-24T00:00:00Z',
        updated_at: '2026-08-24T00:00:01Z',
        finished_at: state === 'COMPLETED' ? '2026-08-24T00:00:02Z' : null,
        hardware_accessed: false,
      });
    }
    if (path === '/motion/stop') {
      motionStopped = true;
      return jsonResponse({
        result: options.stopResult ?? 'STOPPED',
        status: currentRobot,
        hardware_accessed: false,
      });
    }
    if (
      path === '/motion/joints' || path === '/motion/jog-step' ||
      path === '/motion/cartesian-jog' || path === '/motion/pose' || path === '/motion/home'
    ) {
      if (options.preflightReject) {
        return jsonResponse({
          code: 'MOTION_PREFLIGHT_REJECTED',
          message: 'Motion preflight rejected the target',
          details: {
            preflight: {
              ...preflight,
              accepted: false,
              checks: [
                { name: 'workspace_bounds', passed: false, detail: 'Target Z exceeds provisional bounds' },
              ],
              warnings: [],
            },
          },
          request_id: 'preflight-request',
        }, false, 422);
      }
      return jsonResponse({
        command_id: COMMAND_ID,
        status: options.motionState ?? 'COMPLETED',
        preflight,
      }, true, 202);
    }
    throw new Error(`Unhandled request: ${path}`);
  });

  vi.stubGlobal('fetch', fetchMock);
  vi.stubGlobal('WebSocket', undefined);

  return {
    fetchMock,
    requests,
    goOffline: () => { offline = true; },
    requestsFor: (path: string) => requests.filter((request) => request.path === path),
    lastBody: (path: string) => requests.filter((request) => request.path === path).at(-1)?.body,
  };
}

export const stage3Ids = {
  profileFingerprint: PROFILE_FINGERPRINT,
  kinematicsFingerprint: KINEMATICS_FINGERPRINT,
  commandId: COMMAND_ID,
  jogSessionId: JOG_SESSION_ID,
};
