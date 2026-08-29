import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StrictMode, type ReactNode } from 'react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type {
  MotionDraft,
  MotionEntity,
  PlaybackStatus,
  PoseEntity,
  PoseSnapshot,
  PoseSummary,
  RobotProfile,
  TrajectoryPreflightReport,
  TrajectoryPreview,
} from '../api/types';
import {
  RealSessionContext,
  type RealSessionContextValue,
} from '../components/realSessionContext';
import {
  RuntimeStatusContext,
  SAFE_RUNTIME_STATUS,
  type RuntimeStatus,
} from '../components/runtimeStatusContext';
import { realSessionFixture } from '../test/realSessionFixtures';
import { robotFor, stage3Ids, v2Profile } from '../test/stage3Fixtures';
import { StudioPage } from './StudioPage';

const DRAFT_ID = '11111111-1111-4111-8111-111111111111';
const FRESH_DRAFT_ID = '22222222-2222-4222-8222-222222222222';
const POSE_ID = '33333333-3333-4333-8333-333333333333';
const MOTION_ID = '44444444-4444-4444-8444-444444444444';
const FRAME_A = '55555555-5555-4555-8555-555555555555';
const FRAME_B = '66666666-6666-4666-8666-666666666666';

function snapshot(x: number): PoseSnapshot {
  const joints = v2Profile.enabled_joints;
  return {
    robot_variant: 'V2',
    joint_state: {
      positions: Object.fromEntries(joints.map((jointId, index) => [jointId, x + index])),
      units: Object.fromEntries(joints.map((jointId) => [jointId, jointId === 'j10' ? 'mm' : 'deg'])),
    } as PoseSnapshot['joint_state'],
    tcp_pose: {
      frame: 'base',
      position_mm: { x, y: 200 + x, z: 300 + x },
      orientation_quaternion_xyzw: { x: 0, y: 0, z: 0, w: 1 },
    },
    profile_fingerprint: stage3Ids.profileFingerprint,
    kinematics_fingerprint: stage3Ids.kinematicsFingerprint,
    state_sequence: 7,
    hardware_snapshot: null,
    calibration_fingerprint: null,
    captured_at: '2026-08-24T01:00:00Z',
  };
}

const pose: PoseEntity = {
  schema_version: '2.0.0',
  id: POSE_ID,
  name: 'Saved Pose',
  description: 'Library source',
  tags: ['studio'],
  snapshot: snapshot(150),
  created_at: '2026-08-24T01:00:00Z',
  updated_at: '2026-08-24T01:00:00Z',
  revision: 2,
};

const poseSummary: PoseSummary = {
  id: pose.id,
  name: pose.name,
  description: pose.description,
  tags: pose.tags,
  robot_variant: pose.snapshot.robot_variant,
  joint_state: pose.snapshot.joint_state,
  tcp_pose: pose.snapshot.tcp_pose,
  profile_fingerprint: pose.snapshot.profile_fingerprint,
  kinematics_fingerprint: pose.snapshot.kinematics_fingerprint,
  state_sequence: pose.snapshot.state_sequence,
  created_at: pose.created_at,
  updated_at: pose.updated_at,
  revision: pose.revision,
};

function draft(keyframeCount = 2, id = DRAFT_ID): MotionDraft {
  const frames = [
    {
      id: FRAME_A,
      label: 'Frame A',
      pose_snapshot: snapshot(100),
      source_pose_id: null,
      hold_s: 0.2,
      incoming_transition: null,
    },
    {
      id: FRAME_B,
      label: 'Frame B',
      pose_snapshot: snapshot(150),
      source_pose_id: POSE_ID,
      hold_s: 0,
      incoming_transition: {
        duration_s: 2,
        motion_mode: 'JOINT' as const,
        easing: 'SMOOTHSTEP' as const,
      },
    },
  ].slice(0, keyframeCount);
  return {
    schema_version: '1.0.0',
    id,
    source_motion_id: null,
    source_motion_revision: null,
    name: 'Studio Motion',
    description: '',
    robot_variant: 'V2',
    keyframes: frames,
    playback_defaults: { loop: false, speed_multiplier: 1 },
    tags: [],
    source_metadata: null,
    trusted_legacy_snapshot_sha256: [],
    editor_metadata: {
      selected_keyframe_id: frames[0]?.id ?? null,
      playhead_s: 0,
      timeline_zoom: 1,
      timeline_scroll_s: 0,
      default_edges: [],
    },
    save_intent: null,
    revision: 3,
    created_at: '2026-08-24T01:00:00Z',
    updated_at: '2026-08-24T01:00:00Z',
  };
}

function importedDraft(): MotionDraft {
  const imported = draft();
  return {
    ...imported,
    source_motion_id: MOTION_ID,
    source_motion_revision: 1,
    keyframes: imported.keyframes.map((keyframe) => ({
      ...keyframe,
      pose_snapshot: {
        ...keyframe.pose_snapshot,
        state_sequence: null,
      },
    })),
    source_metadata: {
      importer: 'momo.tools.import_legacy_actions',
      source_file_name: 'legacy-camera-action.json',
      source_sha256: 'e'.repeat(64),
      legacy_id: 'legacy-camera-action',
      legacy_source: 'web_record:arm_a',
      warnings: ['Legacy snapshots do not carry runtime state sequences.'],
    },
    trusted_legacy_snapshot_sha256: ['f'.repeat(64)],
  };
}

const motion: MotionEntity = {
  schema_version: '2.0.0',
  id: MOTION_ID,
  name: 'Studio Motion',
  description: '',
  robot_variant: 'V2',
  keyframes: draft().keyframes,
  playback_defaults: { loop: false, speed_multiplier: 1 },
  tags: [],
  source_metadata: null,
  created_at: '2026-08-24T01:00:00Z',
  updated_at: '2026-08-24T01:00:01Z',
  revision: 1,
};

const preflight: TrajectoryPreflightReport = {
  passed: true,
  digest: 'sha256:studio-prepared',
  motion_id: MOTION_ID,
  motion_revision: 1,
  duration_s: 2.2,
  sample_count: 45,
  segment_count: 2,
  sample_rate_hz: 20,
  violations: [],
  checks: [{ name: 'limits', passed: true, detail: 'All samples are within limits' }],
  prepared_at: '2026-08-24T02:00:00Z',
};

const preview: TrajectoryPreview = {
  digest: 'sha256:draft-preview',
  motion_id: DRAFT_ID,
  duration_s: 2.2,
  sample_rate_hz: 20,
  sample_count: 45,
  segments: [{
    segment_index: 0,
    motion_mode: 'JOINT',
    start_time_s: 0,
    end_time_s: 2,
    sample_count: 41,
    start_keyframe_id: FRAME_A,
    end_keyframe_id: FRAME_B,
  }],
  joint_series: {
    j10: [
      { time_s: 0, value: 100, unit: 'mm' },
      { time_s: 2.2, value: 150, unit: 'mm' },
    ],
  },
  tcp_path: [
    { time_s: 0, x_mm: 100, y_mm: 300, z_mm: 400 },
    { time_s: 2.2, x_mm: 150, y_mm: 350, z_mm: 450 },
  ],
  keyframe_markers: [
    { keyframe_id: FRAME_A, label: 'Frame A', time_s: 0, sample_index: 0 },
    { keyframe_id: FRAME_B, label: 'Frame B', time_s: 2, sample_index: 40 },
  ],
};

function playback(state: PlaybackStatus['state'], progress = 0): PlaybackStatus {
  return {
    session_id: state === 'PLAYING' || state === 'PAUSED' ? 'session-1' : null,
    state,
    motion_id: state === 'IDLE' ? null : MOTION_ID,
    trajectory_digest: state === 'IDLE' ? null : preflight.digest,
    progress,
    elapsed_s: progress * 2.2,
    duration_s: state === 'IDLE' ? 0 : 2.2,
    current_keyframe_id: state === 'IDLE' ? null : FRAME_A,
    current_segment_index: state === 'IDLE' ? null : 0,
    current_sample_index: state === 'IDLE' ? null : Math.round(progress * 44),
    loop: false,
    rate: 1,
    error: null,
    updated_at: '2026-08-24T02:00:00Z',
    hardware_accessed: false,
  };
}

interface RequestRecord {
  body: unknown;
  method: string;
  path: string;
}

interface BackendOptions {
  activeGoto?: boolean;
  activeSaveConflict?: 'missing' | 'recovery' | 'unknown';
  canonicalizeDraftName?: boolean;
  compileError?: boolean;
  conflictOnAutosave?: boolean;
  conflictOnFormalSave?: boolean;
  draftConflictOnCommand?: 'compile' | 'goto' | 'validate';
  draftConflictOnFormalSave?: boolean;
  draftConflictOnSaveAs?: boolean;
  deferPreflight?: boolean;
  deferGoto?: boolean;
  deferPose?: boolean;
  deferFirstAutosave?: boolean;
  draft?: MotionDraft;
  initialPlaybackState?: PlaybackStatus['state'];
  formalSaveRecovery?: 'draft' | 'list';
  rejectRecoveryRelease?: boolean;
  rejectFork?: boolean;
  recoverFromList?: boolean;
  saveAsNonDraftConflict?: 'missing' | 'motion' | 'unknown';
}

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

function mockStudioBackend(options: BackendOptions = {}) {
  const requests: RequestRecord[] = [];
  let currentDraft = structuredClone(options.draft ?? draft());
  let freshDraft: MotionDraft | null = null;
  let conflictPending = options.conflictOnAutosave ?? false;
  let formalSaveConflictPending = options.conflictOnFormalSave ?? false;
  let draftFormalSaveConflictPending = options.draftConflictOnFormalSave ?? false;
  let draftSaveAsConflictPending = options.draftConflictOnSaveAs ?? false;
  let commandConflictPending = options.draftConflictOnCommand;
  let activeSaveConflictPending = options.activeSaveConflict;
  let saveAsNonDraftConflictPending = options.saveAsNonDraftConflict;
  let motionSaveRecoveryPending = false;
  let deferredResolve: ((value: Response) => void) | null = null;
  let deferredPreflightResolve: ((value: Response) => void) | null = null;
  let deferredGotoResolve: ((value: Response) => void) | null = null;
  let deferredPoseResolve: ((value: Response) => void) | null = null;
  let firstAutosavePending = options.deferFirstAutosave ?? false;
  let playbackStatus = playback(options.initialPlaybackState ?? 'IDLE');
  let studioCommandStopped = false;
  let formalSaveRecoveryPending = options.formalSaveRecovery !== undefined;
  const recoveryOperationId = '77777777-7777-4777-8777-777777777777';
  const recoveryConflict = () => response({
    code: 'REVISION_CONFLICT',
    message: 'Formal save recovery found different content at the target revision',
    details: {
      reason: 'FORMAL_SAVE_TARGET_CONTENT_MISMATCH',
      entity: 'Motion',
      draft_id: currentDraft.id,
      draft_revision: currentDraft.revision,
      operation_id: recoveryOperationId,
      kind: 'SAVE_AS',
      target_motion_id: MOTION_ID,
      target_motion_revision: 1,
      expected_motion_revision: null,
      actual_target_revision: 1,
      started_at: '2026-08-24T01:30:00Z',
    },
  }, 409);

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://momo.test');
    const path = url.pathname.replace(/^\/api\/v1/, '');
    const method = init?.method ?? 'GET';
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined;
    requests.push({ path: `${path}${url.search}`, method, body });

    if (path === `/studio/drafts/${DRAFT_ID}` && method === 'GET') {
      if (formalSaveRecoveryPending && options.formalSaveRecovery === 'draft') {
        return recoveryConflict();
      }
      if (motionSaveRecoveryPending) {
        motionSaveRecoveryPending = false;
        currentDraft = {
          ...currentDraft,
          save_intent: null,
          revision: currentDraft.revision + 1,
          updated_at: '2026-08-24T02:55:00Z',
        };
      }
      return response(currentDraft);
    }
    if (path === `/studio/drafts/${FRESH_DRAFT_ID}` && method === 'GET' && freshDraft) return response(freshDraft);
    if (path === `/studio/drafts/from-motion/${MOTION_ID}` && method === 'POST') {
      freshDraft = {
        ...draft(2, FRESH_DRAFT_ID),
        source_motion_id: motion.id,
        source_motion_revision: motion.revision,
        name: motion.name,
        description: motion.description,
        keyframes: structuredClone(motion.keyframes),
        playback_defaults: structuredClone(motion.playback_defaults),
        tags: [...motion.tags],
        revision: 1,
      };
      return response(freshDraft, 201);
    }
    if (path === '/studio/drafts' && method === 'GET') {
      if (formalSaveRecoveryPending && options.formalSaveRecovery === 'list') {
        return recoveryConflict();
      }
      return response({
        items: options.recoverFromList ? [{
          id: currentDraft.id,
          source_motion_id: currentDraft.source_motion_id,
          source_motion_revision: currentDraft.source_motion_revision,
          name: currentDraft.name,
          robot_variant: currentDraft.robot_variant,
          keyframe_count: currentDraft.keyframes.length,
          created_at: currentDraft.created_at,
          updated_at: currentDraft.updated_at,
          revision: currentDraft.revision,
        }] : [],
        page: 1,
        page_size: 20,
        total: options.recoverFromList ? 1 : 0,
      });
    }
    if (path === '/studio/drafts' && method === 'POST') {
      const request = body as Record<string, unknown>;
      freshDraft = {
        ...draft(0, FRESH_DRAFT_ID),
        name: String(request.name ?? 'Untitled Motion'),
        description: String(request.description ?? ''),
        robot_variant: (request.robot_variant ?? 'V2') as 'V2',
        keyframes: (request.keyframes ?? []) as MotionDraft['keyframes'],
        playback_defaults: (request.playback_defaults ?? { loop: false, speed_multiplier: 1 }) as MotionDraft['playback_defaults'],
        tags: (request.tags ?? []) as string[],
        editor_metadata: (request.editor_metadata ?? draft(0).editor_metadata) as MotionDraft['editor_metadata'],
        revision: 1,
      };
      return response(freshDraft, 201);
    }
    if (path === `/studio/drafts/${DRAFT_ID}/save-intent/abandon` && method === 'POST') {
      if (options.rejectRecoveryRelease) {
        return response({
          code: 'REVISION_CONFLICT',
          message: 'Formal save recovery operation changed',
          details: {
            reason: 'FORMAL_SAVE_OPERATION_MISMATCH',
            entity: 'MotionDraft',
            draft_id: currentDraft.id,
            draft_revision: currentDraft.revision,
          },
        }, 409);
      }
      formalSaveRecoveryPending = false;
      currentDraft = {
        ...currentDraft,
        save_intent: null,
        revision: currentDraft.revision + 1,
        updated_at: '2026-08-24T02:30:00Z',
      };
      return response(currentDraft);
    }
    if (path === `/studio/drafts/${DRAFT_ID}/fork` && method === 'POST') {
      const expectedRevision = Number((body as { expected_revision?: number }).expected_revision);
      if (options.rejectFork) {
        currentDraft = {
          ...currentDraft,
          revision: currentDraft.revision + 1,
          updated_at: '2026-08-24T02:45:00Z',
        };
        return response({
          code: 'REVISION_CONFLICT',
          message: 'Draft changed again before it could be forked',
          details: {
            entity: 'MotionDraft',
            expected_revision: expectedRevision,
            actual_revision: currentDraft.revision,
          },
        }, 409);
      }
      freshDraft = {
        ...structuredClone(currentDraft),
        id: FRESH_DRAFT_ID,
        revision: 1,
        save_intent: null,
        created_at: '2026-08-24T02:45:00Z',
        updated_at: '2026-08-24T02:45:00Z',
      };
      return response(freshDraft, 201);
    }
    if ((path === `/studio/drafts/${DRAFT_ID}` || path === `/studio/drafts/${FRESH_DRAFT_ID}`) && method === 'PUT') {
      const target = path.endsWith(FRESH_DRAFT_ID) ? freshDraft : currentDraft;
      if (!target) throw new Error('missing target draft');
      if (conflictPending && path.endsWith(DRAFT_ID)) {
        conflictPending = false;
        const expectedRevision = target.revision;
        currentDraft = {
          ...currentDraft,
          name: 'Concurrent server edit',
          revision: expectedRevision + 1,
          updated_at: '2026-08-24T02:40:00Z',
        };
        return response({
          code: 'REVISION_CONFLICT',
          message: 'Draft revision changed',
          details: {
            entity: 'MotionDraft',
            expected_revision: expectedRevision,
            actual_revision: currentDraft.revision,
          },
        }, 409);
      }
      const updated: MotionDraft = {
        ...target,
        ...(body as Pick<MotionDraft, 'name' | 'description' | 'robot_variant' | 'keyframes' | 'playback_defaults' | 'tags' | 'editor_metadata'>),
        name: options.canonicalizeDraftName
          ? String((body as { name?: string }).name ?? '').trim() || 'Untitled Motion'
          : String((body as { name?: string }).name ?? target.name),
        revision: target.revision + 1,
        updated_at: '2026-08-24T02:00:00Z',
      };
      if (path.endsWith(FRESH_DRAFT_ID)) freshDraft = updated;
      else currentDraft = updated;
      if (firstAutosavePending && path.endsWith(DRAFT_ID)) {
        firstAutosavePending = false;
        return await new Promise<Response>((resolve) => {
          deferredResolve = resolve;
        });
      }
      return response(updated);
    }
    if (path === '/studio/capture' && method === 'POST') return response(snapshot(125));
    if (path === '/robot/fk' && method === 'GET') {
      return response({
        robot_id: 'primary',
        variant: 'V2',
        state_sequence: 7,
        profile_fingerprint: stage3Ids.profileFingerprint,
        kinematics_fingerprint: stage3Ids.kinematicsFingerprint,
        tcp_pose: snapshot(125).tcp_pose,
        hardware_accessed: false,
      });
    }
    if (path === '/poses' && method === 'GET') {
      return response({ items: [poseSummary], page: 1, page_size: 24, total: 1 });
    }
    if (path === `/poses/${POSE_ID}` && method === 'GET') {
      if (options.deferPose) {
        return await new Promise<Response>((resolve) => {
          deferredPoseResolve = resolve;
        });
      }
      return response(pose);
    }
    if (path.endsWith('/validate') && method === 'POST') {
      if (commandConflictPending === 'validate') {
        commandConflictPending = undefined;
        const expectedRevision = Number((body as { expected_revision?: number }).expected_revision);
        currentDraft = {
          ...currentDraft,
          keyframes: currentDraft.keyframes.map((keyframe, index) =>
            index === 0 ? { ...keyframe, label: 'Concurrent server frame' } : keyframe
          ),
          revision: expectedRevision + 1,
        };
        return response({
          code: 'REVISION_CONFLICT',
          message: 'MotionDraft revision changed',
          details: { entity: 'MotionDraft', expected_revision: expectedRevision, actual_revision: currentDraft.revision },
        }, 409);
      }
      const target = path.includes(FRESH_DRAFT_ID) ? freshDraft : currentDraft;
      const valid = (target?.keyframes.length ?? 0) >= 2;
      return response({
        draft_id: target?.id ?? DRAFT_ID,
        draft_revision: target?.revision ?? 1,
        valid,
        issues: valid ? [] : [{
          code: 'DRAFT_REQUIRES_TWO_KEYFRAMES',
          message: 'A formal Motion requires at least two keyframes',
        }],
      });
    }
    if (path.endsWith('/compile') && method === 'POST') {
      if (commandConflictPending === 'compile') {
        commandConflictPending = undefined;
        const expectedRevision = Number((body as { expected_revision?: number }).expected_revision);
        currentDraft = {
          ...currentDraft,
          keyframes: currentDraft.keyframes.map((keyframe, index) =>
            index === 0 ? { ...keyframe, label: 'Concurrent server frame' } : keyframe
          ),
          revision: expectedRevision + 1,
        };
        return response({
          code: 'REVISION_CONFLICT',
          message: 'MotionDraft revision changed',
          details: { entity: 'MotionDraft', expected_revision: expectedRevision, actual_revision: currentDraft.revision },
        }, 409);
      }
      if (options.compileError) {
        return response({
          code: 'ENTITY_INVALID',
          message: '草稿转换失败',
          details: { issues: ['DRAFT_REQUIRES_TWO_KEYFRAMES'] },
        }, 422);
      }
      return response({
        draft_id: path.includes(FRESH_DRAFT_ID) ? FRESH_DRAFT_ID : DRAFT_ID,
        draft_revision: (path.includes(FRESH_DRAFT_ID) ? freshDraft : currentDraft)?.revision ?? 1,
        preflight: { ...preflight, motion_id: DRAFT_ID, digest: preview.digest },
        preview,
        executable: false,
      });
    }
    if (path.endsWith('/save') && method === 'POST') {
      if (draftFormalSaveConflictPending) {
        draftFormalSaveConflictPending = false;
        const expectedRevision = Number((body as { expected_revision?: number }).expected_revision);
        currentDraft = {
          ...currentDraft,
          keyframes: currentDraft.keyframes.map((keyframe, index) =>
            index === 0 ? { ...keyframe, label: 'Concurrent server frame' } : keyframe
          ),
          revision: expectedRevision + 1,
          updated_at: '2026-08-24T02:48:00Z',
        };
        return response({
          code: 'REVISION_CONFLICT',
          message: 'MotionDraft revision changed',
          details: { entity: 'MotionDraft', expected_revision: expectedRevision, actual_revision: currentDraft.revision },
        }, 409);
      }
      if (activeSaveConflictPending) {
        const kind = activeSaveConflictPending;
        activeSaveConflictPending = undefined;
        const details = kind === 'recovery'
          ? {
              entity: 'Motion',
              reason: 'FORMAL_SAVE_TARGET_CONTENT_MISMATCH',
              draft_id: currentDraft.id,
              draft_revision: currentDraft.revision,
              operation_id: '99999999-9999-4999-8999-999999999999',
              kind: 'SAVE',
              target_motion_id: MOTION_ID,
              target_motion_revision: 1,
              expected_motion_revision: 1,
              actual_target_revision: 1,
              started_at: '2026-08-24T02:49:00Z',
            }
          : {
              ...(kind === 'unknown' ? { entity: 'FreshMotion' } : {}),
              expected_revision: 1,
              actual_revision: 2,
            };
        return response({
          code: 'REVISION_CONFLICT',
          message: `Fail-closed ${kind} formal save conflict`,
          details,
        }, 409);
      }
      if (formalSaveConflictPending) {
        formalSaveConflictPending = false;
        motionSaveRecoveryPending = true;
        currentDraft = {
          ...currentDraft,
          save_intent: {
            operation_id: '88888888-8888-4888-8888-888888888888',
            kind: 'SAVE',
            target_motion_id: MOTION_ID,
            target_motion_revision: 2,
            expected_motion_revision: 1,
            target_name: currentDraft.name,
            target_motion_created_at: motion.created_at,
            started_at: '2026-08-24T02:50:00Z',
          },
          revision: currentDraft.revision + 1,
          updated_at: '2026-08-24T02:50:00Z',
        };
        return response({
          code: 'REVISION_CONFLICT',
          message: 'Source Motion revision changed',
          details: { entity: 'Motion', expected_revision: 1, actual_revision: 2 },
        }, 409);
      }
      currentDraft = { ...currentDraft, source_motion_id: MOTION_ID, source_motion_revision: 1 };
      return response({ draft: currentDraft, motion, preflight });
    }
    if (path.endsWith('/save-as') && method === 'POST') {
      if (draftSaveAsConflictPending && path.includes(DRAFT_ID)) {
        draftSaveAsConflictPending = false;
        const expectedRevision = Number((body as { expected_revision?: number }).expected_revision);
        currentDraft = {
          ...currentDraft,
          keyframes: currentDraft.keyframes.map((keyframe, index) =>
            index === 0 ? { ...keyframe, label: 'Concurrent server frame' } : keyframe
          ),
          revision: expectedRevision + 1,
          updated_at: '2026-08-24T02:52:00Z',
        };
        return response({
          code: 'REVISION_CONFLICT',
          message: 'MotionDraft revision changed before Save As',
          details: { entity: 'MotionDraft', expected_revision: expectedRevision, actual_revision: currentDraft.revision },
        }, 409);
      }
      if (saveAsNonDraftConflictPending) {
        const kind = saveAsNonDraftConflictPending;
        saveAsNonDraftConflictPending = undefined;
        return response({
          code: 'REVISION_CONFLICT',
          message: `Fail-closed ${kind} Save As conflict`,
          details: {
            ...(kind === 'motion' ? { entity: 'Motion' } : {}),
            ...(kind === 'unknown' ? { entity: 'FreshMotion' } : {}),
            expected_revision: 1,
            actual_revision: 2,
          },
        }, 409);
      }
      const source = path.includes(FRESH_DRAFT_ID) && freshDraft ? freshDraft : currentDraft;
      const savedName = String((body as { name?: string }).name ?? source.name);
      const savedMotion = {
        ...motion,
        name: savedName,
        keyframes: structuredClone(source.keyframes),
        source_metadata: source.source_metadata,
      };
      const savedDraft = {
        ...source,
        name: savedName,
        source_motion_id: MOTION_ID,
        source_motion_revision: 1,
      };
      if (path.includes(FRESH_DRAFT_ID)) freshDraft = savedDraft;
      else currentDraft = savedDraft;
      return response({ draft: savedDraft, motion: savedMotion, preflight });
    }
    if (path === `/motions/${MOTION_ID}` && method === 'GET') return response(motion);
    if (path === `/motions/${MOTION_ID}/preflight` && method === 'POST') {
      playbackStatus = playback('READY');
      if (options.deferPreflight) {
        playbackStatus = playback('PREFLIGHTING');
        return await new Promise<Response>((resolve) => {
          deferredPreflightResolve = resolve;
        });
      }
      return response(preflight);
    }
    if (path === `/motions/${MOTION_ID}/play` && method === 'POST') {
      playbackStatus = playback('PLAYING', 0.25);
      return response(playbackStatus);
    }
    if (path === '/playback' && method === 'GET') return response(playbackStatus);
    if (path === '/playback/pause' && method === 'POST') {
      playbackStatus = playback('PAUSED', 0.3);
      return response(playbackStatus);
    }
    if (path === '/playback/resume' && method === 'POST') {
      playbackStatus = playback('PLAYING', 0.35);
      return response(playbackStatus);
    }
    if (path === '/playback/stop' && method === 'POST') {
      playbackStatus = playback('STOPPED', 0.35);
      return response(playbackStatus);
    }
    if (path.includes('/keyframes/') && path.endsWith('/goto') && method === 'POST') {
      if (commandConflictPending === 'goto') {
        commandConflictPending = undefined;
        const expectedRevision = Number((body as { expected_revision?: number }).expected_revision);
        currentDraft = {
          ...currentDraft,
          keyframes: currentDraft.keyframes.map((keyframe, index) =>
            index === 0 ? { ...keyframe, label: 'Concurrent server frame' } : keyframe
          ),
          revision: expectedRevision + 1,
        };
        return response({
          code: 'REVISION_CONFLICT',
          message: 'MotionDraft revision changed',
          details: { entity: 'MotionDraft', expected_revision: expectedRevision, actual_revision: currentDraft.revision },
        }, 409);
      }
      if (options.deferGoto) {
        return await new Promise<Response>((resolve) => {
          deferredGotoResolve = resolve;
        });
      }
      return response({
        command_id: 'goto-command',
        status: options.activeGoto ? 'RUNNING' : 'COMPLETED',
        preflight: null,
      }, 202);
    }
    if (path === '/robot/stop' && method === 'POST') {
      studioCommandStopped = true;
      return response({ result: 'STOPPED', status: robotFor('V2', true), hardware_accessed: false });
    }
    if (path === '/motion/commands/goto-command' && method === 'GET') {
      return response({
        command_id: 'goto-command',
        state: studioCommandStopped ? 'STOPPED' : 'RUNNING',
        progress: studioCommandStopped ? 1 : 0.25,
      });
    }
    throw new Error(`Unhandled Studio test request: ${method} ${path}`);
  });

  vi.stubGlobal('fetch', fetchMock);
  return {
    requests,
    resolveDeferredAutosave: () => {
      if (!deferredResolve) throw new Error('No deferred autosave is pending');
      deferredResolve(response(currentDraft));
      deferredResolve = null;
    },
    rejectDeferredAutosave: () => {
      if (!deferredResolve) throw new Error('No deferred autosave is pending');
      deferredResolve(response({
        code: 'BACKEND_UNAVAILABLE',
        message: 'Old workspace write failed',
        details: {},
      }, 503));
      deferredResolve = null;
    },
    resolveDeferredPreflight: () => {
      if (!deferredPreflightResolve) throw new Error('No deferred preflight is pending');
      deferredPreflightResolve(response(preflight));
      deferredPreflightResolve = null;
    },
    resolveDeferredGoto: () => {
      if (!deferredGotoResolve) throw new Error('No deferred Goto is pending');
      deferredGotoResolve(response({ command_id: 'goto-command', status: 'RUNNING', preflight: null }, 202));
      deferredGotoResolve = null;
    },
    resolveDeferredPose: () => {
      if (!deferredPoseResolve) throw new Error('No deferred Pose is pending');
      deferredPoseResolve(response(pose));
      deferredPoseResolve = null;
    },
  };
}

function runtime(overrides: Partial<RuntimeStatus> = {}): RuntimeStatus {
  return {
    ...SAFE_RUNTIME_STATUS,
    backend: 'connected' as const,
    stale: false,
    robot: robotFor('V2', true) as RuntimeStatus['robot'],
    profile: {
      profile: v2Profile as RobotProfile,
      fingerprint: stage3Ids.profileFingerprint,
      kinematics_fingerprint: stage3Ids.kinematicsFingerprint,
      real_eligible: false as const,
    },
    ...overrides,
  };
}

function renderStudio(
  path = `/studio?draft=${DRAFT_ID}`,
  strict = false,
  status = runtime(),
  realSession: RealSessionContextValue = realSessionFixture(),
) {
  const content: ReactNode = (
    <MemoryRouter initialEntries={[path]}>
      <RuntimeStatusContext.Provider value={status}>
        <RealSessionContext.Provider value={realSession}>
          <StudioPage />
          <LocationProbe />
        </RealSessionContext.Provider>
      </RuntimeStatusContext.Provider>
    </MemoryRouter>
  );
  return render(
    strict ? <StrictMode>{content}</StrictMode> : content,
  );
}

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="studio-location" hidden>{location.search}</span>;
}

function StudioEntrySwitcher() {
  const navigate = useNavigate();
  return (
    <>
      <button onClick={() => navigate(`/studio?pose=${POSE_ID}`)} type="button">Open Pose entry</button>
      <StudioPage />
      <LocationProbe />
    </>
  );
}

function renderStudioWithEntrySwitcher() {
  return render(
    <MemoryRouter initialEntries={[`/studio?draft=${DRAFT_ID}`]}>
      <RuntimeStatusContext.Provider value={runtime()}>
        <StudioEntrySwitcher />
      </RuntimeStatusContext.Provider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('Stage 6 Studio workspace', () => {
  it('renders only the Viewer, Inspector, and Timeline as primary Studio regions', async () => {
    mockStudioBackend();
    renderStudio();

    expect(await screen.findByRole('heading', { name: '3D 仿真视图' })).toBeVisible();
    expect(screen.getByRole('heading', { name: '关键帧属性' })).toBeVisible();
    expect(screen.getByRole('region', { name: 'Studio Motion' })).toBeVisible();
    expect(screen.getAllByRole('button', { name: '添加关键帧' })).toHaveLength(1);
    expect(screen.queryByText('当前机械臂状态')).not.toBeInTheDocument();
    expect(screen.queryByText('环境编译')).not.toBeInTheDocument();
    expect(screen.queryByText('校准屏障')).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/停留/)).not.toBeInTheDocument();
  });

  it('disables the incoming motion mode for the first keyframe only', async () => {
    const user = userEvent.setup();
    mockStudioBackend();
    renderStudio();

    const first = await screen.findByRole('button', { name: /关键帧 1：Frame A/ });
    expect(first).toHaveClass('studio-keyframe-marker--selected');
    const mode = screen.getByLabelText('进入过渡的运动模式');
    expect(mode).toBeDisabled();
    expect(mode).toHaveValue('');
    expect(screen.getByText('起始关键帧（无进入运动）')).toBeVisible();

    await user.click(screen.getByRole('button', { name: /关键帧 2：Frame B/ }));
    expect(mode).toBeEnabled();
    expect(mode).toHaveValue('JOINT');
  });

  it('keeps the timeline simulation-only in Commissioning READ ONLY', async () => {
    const backend = mockStudioBackend();
    renderStudio(
      `/studio?draft=${DRAFT_ID}`,
      false,
      runtime({
        controlMode: 'REAL',
        hardwareAccessPolicy: 'READ_ONLY',
        realMotionEnabled: false,
      }),
      realSessionFixture({
        capabilities: {
          real_joint_motion: { blocked_reasons: ['unsafe runtime policy'] },
          real_playback: { blocked_reasons: ['unsafe runtime policy'] },
        },
      }),
    );

    await screen.findByLabelText('运动名称');
    expect(screen.queryByRole('button', { name: /前往/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '准备播放' })).not.toBeInTheDocument();
    expect(screen.getByText('SIMULATION')).toBeVisible();
    expect(screen.getByRole('button', { name: '播放仿真预览' })).toBeEnabled();
    expect(backend.requests.some((request) => request.path.includes('/goto'))).toBe(false);
    expect(backend.requests.some((request) =>
      request.path.endsWith('/play') && request.method === 'POST'
    )).toBe(false);
  });

  it('never exposes a physical Goto action even when Real Joint capability is authorized', async () => {
    const backend = mockStudioBackend();
    renderStudio(
      `/studio?draft=${DRAFT_ID}`,
      false,
      runtime({
        controlMode: 'REAL',
        hardwareAccessPolicy: 'FULL',
        realMotionEnabled: true,
      }),
      realSessionFixture({
        session: {
          active: true,
          session_id: '33333333-3333-4333-8333-333333333333',
          expires_at: '2099-08-25T00:00:00Z',
          purpose: 'REAL_MOTION',
          scopes: ['REAL_JOINT_MOTION'],
        },
        capabilities: {
          real_joint_motion: {
            ready: true,
            authorized: true,
            blocked_reasons: [],
          },
        },
      }),
    );

    await screen.findByLabelText('运动名称');
    expect(screen.queryByRole('button', { name: /真机前往/ })).not.toBeInTheDocument();
    expect(screen.getByText('SIMULATION')).toBeVisible();
    expect(backend.requests.some((request) => request.path.includes('/goto'))).toBe(false);
  });

  it('starts blank, captures current state, adds a Pose, and autosaves two playable frames', async () => {
    const user = userEvent.setup();
    const backend = mockStudioBackend({ draft: draft(0) });
    renderStudio();

    expect(await screen.findByText('空白运动草稿')).toBeVisible();
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: '添加关键帧' }));
    await user.click(await screen.findByRole('button', { name: /捕获当前姿态/ }));
    expect(await screen.findByRole('button', { name: /关键帧 1：Capture 1/ })).toBeVisible();
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled();

    await user.click(screen.getByRole('button', { name: '添加关键帧' }));
    await user.click(await screen.findByRole('button', { name: /Saved Pose/ }));
    expect(await screen.findByRole('button', { name: /关键帧 2：Saved Pose/ })).toBeVisible();
    expect(screen.getByRole('button', { name: '保存' })).toBeEnabled();

    await waitFor(
      () => expect(backend.requests.some((request) => {
        if (request.method !== 'PUT') return false;
        return (request.body as { keyframes?: MotionDraft['keyframes'] }).keyframes?.length === 2;
      })).toBe(true),
      { timeout: 1800 },
    );
    const autosave = backend.requests.filter((request) => {
      if (request.method !== 'PUT') return false;
      return (request.body as { keyframes?: MotionDraft['keyframes'] }).keyframes?.length === 2;
    }).at(-1);
    const body = autosave?.body as { keyframes: MotionDraft['keyframes'] };
    expect(body.keyframes).toHaveLength(2);
    expect(body.keyframes[0].incoming_transition).toBeNull();
    expect(body.keyframes[1].incoming_transition).toMatchObject({
      duration_s: 1,
      motion_mode: 'JOINT',
      easing: 'SMOOTHSTEP',
    });
    expect(body.keyframes.every((keyframe) => keyframe.hold_s === 0)).toBe(true);
  });

  it('duplicates after the selected keyframe with zero hold and disables delete at the minimum', async () => {
    const user = userEvent.setup();
    const backend = mockStudioBackend();
    renderStudio();

    await screen.findByRole('button', { name: /关键帧 1：Frame A/ });
    expect(screen.getByRole('button', { name: '删除关键帧' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: '复制关键帧' }));
    expect(await screen.findByRole('button', { name: /关键帧 2：Frame A 副本/ })).toBeVisible();
    expect(screen.getByRole('button', { name: '删除关键帧' })).toBeEnabled();
    await waitFor(() => expect(backend.requests.some((request) => {
      if (request.method !== 'PUT') return false;
      const keyframes = (request.body as { keyframes?: MotionDraft['keyframes'] }).keyframes;
      return keyframes?.[1]?.label === 'Frame A 副本' && keyframes[1].hold_s === 0;
    })).toBe(true), { timeout: 1900 });

    await user.click(screen.getByRole('button', { name: '删除关键帧' }));
    expect(screen.queryByRole('button', { name: /Frame A 副本/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '删除关键帧' })).toBeDisabled();
  });

  it('undoes, redoes, and formally saves a transition duration edit', async () => {
    const user = userEvent.setup();
    const backend = mockStudioBackend();
    renderStudio();

    await user.click(await screen.findByRole('button', { name: /关键帧 2：Frame B/ }));
    const duration = screen.getByLabelText('进入过渡时长（秒）');
    fireEvent.change(duration, { target: { value: '3' } });
    expect(duration).toHaveValue(3);
    await user.click(screen.getByRole('button', { name: '撤销上一次编排修改' }));
    expect(duration).toHaveValue(2);
    await user.click(screen.getByRole('button', { name: '重做上一次编排修改' }));
    expect(duration).toHaveValue(3);

    await user.click(screen.getByRole('button', { name: '保存' }));
    expect(await screen.findByText(/已将正式运动“Studio Motion”保存为版本 1/)).toBeVisible();
    const saveRequest = backend.requests.find((request) => request.path.endsWith('/save') && request.method === 'POST');
    expect(saveRequest).toBeDefined();
    expect(backend.requests.some((request) => {
      if (request.path !== `/studio/drafts/${DRAFT_ID}` || request.method !== 'PUT') return false;
      const keyframes = (request.body as { keyframes?: MotionDraft['keyframes'] }).keyframes;
      return keyframes?.[1]?.incoming_transition?.duration_s === 3;
    })).toBe(true);
  });

  it('traps focus in the add-keyframe drawer and restores its trigger after Escape', async () => {
    const user = userEvent.setup();
    mockStudioBackend({ draft: draft(0) });
    renderStudio();

    const trigger = await screen.findByRole('button', { name: '添加关键帧' });
    await user.click(trigger);
    const search = await screen.findByLabelText('搜索 Pose');
    const close = screen.getByRole('button', { name: '关闭机位选择器' });
    const last = screen.getByRole('button', { name: /Saved Pose/ });
    expect(search).toHaveFocus();

    last.focus();
    await user.tab();
    expect(close).toHaveFocus();
    await user.tab({ shift: true });
    expect(last).toHaveFocus();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: '添加关键帧' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('serializes Pose insertion so its dialog cannot switch workspaces mid-request', async () => {
    const user = userEvent.setup();
    const backend = mockStudioBackend({ deferPose: true });
    renderStudio();
    await screen.findByRole('button', { name: /关键帧 1/ });
    await user.click(screen.getByRole('button', { name: '添加关键帧' }));
    await user.click(await screen.findByRole('button', { name: /Saved Pose/ }));

    expect(screen.getByRole('button', { name: '关闭机位选择器' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '新建草稿' })).toBeDisabled();
    backend.resolveDeferredPose();
    expect(await screen.findByRole('button', { name: /关键帧 2：Saved Pose/ })).toBeVisible();
  });

  it('recovers the newest persisted draft when Studio opens without a handoff', async () => {
    mockStudioBackend({ recoverFromList: true });
    renderStudio('/studio');
    expect(await screen.findByText(/崩溃恢复已从草稿版本 3 恢复“Studio Motion”/)).toBeVisible();
    expect(screen.getByLabelText('运动名称')).toHaveValue('Studio Motion');
  });

  it.each([
    ['draft GET', 'draft' as const, `/studio?draft=${DRAFT_ID}`],
    ['draft list', 'list' as const, '/studio'],
  ])('fails closed on a formal-save recovery conflict from %s and explicitly releases the draft', async (_source, recoverySource, path) => {
    const user = userEvent.setup();
    const backend = mockStudioBackend({ formalSaveRecovery: recoverySource });
    renderStudio(path);

    const dialog = await screen.findByRole('dialog', { name: '需要处理未完成的正式保存' });
    expect(within(dialog).getByText(/目标运动不会被修改/i)).toBeVisible();
    expect(within(dialog).getByText(/不会重试、强制覆盖或删除/i)).toBeVisible();
    expect(screen.queryByLabelText('运动名称')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '保存' })).not.toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: '解除草稿锁定' }));

    expect(await screen.findByText(/已解除草稿恢复标记/)).toBeVisible();
    expect(screen.getByLabelText('运动名称')).toHaveValue('Studio Motion');
    const release = backend.requests.find((request) =>
      request.path === `/studio/drafts/${DRAFT_ID}/save-intent/abandon`
    );
    expect(release).toEqual({
      path: `/studio/drafts/${DRAFT_ID}/save-intent/abandon`,
      method: 'POST',
      body: {
        expected_revision: 3,
        operation_id: '77777777-7777-4777-8777-777777777777',
        confirm: 'ABANDON_FORMAL_SAVE',
      },
    });
    expect(backend.requests.filter((request) =>
      request.path === `/studio/drafts/${DRAFT_ID}` && request.method === 'GET'
    ).length).toBeGreaterThanOrEqual(1);
    await waitFor(() => expect(screen.getByTestId('studio-location')).toHaveTextContent(
      `?draft=${DRAFT_ID}`,
    ));
  });

  it('keeps the recovery gate locked when Release draft conflicts', async () => {
    const user = userEvent.setup();
    mockStudioBackend({ formalSaveRecovery: 'draft', rejectRecoveryRelease: true });
    renderStudio();
    const dialog = await screen.findByRole('dialog', { name: '需要处理未完成的正式保存' });

    await user.click(within(dialog).getByRole('button', { name: '解除草稿锁定' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Formal save recovery operation changed');
    expect(screen.queryByLabelText('运动名称')).not.toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: '解除草稿锁定' })).toBeEnabled();
  });

  it('compares a recovered source-linked draft with its formal Motion, not with itself', async () => {
    const locallyEdited = {
      ...draft(),
      source_motion_id: MOTION_ID,
      source_motion_revision: 1,
      name: 'Autosaved local edit',
    } satisfies MotionDraft;
    mockStudioBackend({ draft: locallyEdited });
    renderStudio();

    expect(await screen.findByText('运动有未保存修改')).toBeVisible();
    expect(screen.getByRole('button', { name: '播放仿真预览' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: '准备播放' })).not.toBeInTheDocument();
  });

  it('initializes exactly one workspace under React StrictMode', async () => {
    const backend = mockStudioBackend();
    renderStudio(`/studio?draft=${DRAFT_ID}`, true);

    expect(await screen.findByLabelText('运动名称')).toHaveValue('Studio Motion');
    expect(backend.requests.filter((request) =>
      request.path === `/studio/drafts/${DRAFT_ID}` && request.method === 'GET'
    )).toHaveLength(2);
    expect(backend.requests.filter((request) =>
      request.path === '/studio/drafts' && request.method === 'POST'
    )).toHaveLength(0);
  });

  it.each([
    ['Motion', `/studio?motion=${MOTION_ID}`, `/studio/drafts/from-motion/${MOTION_ID}`],
    ['Pose', `/studio?pose=${POSE_ID}`, `/poses/${POSE_ID}`],
  ])('rebinds an initial %s handoff URL to the created autosaved draft', async (_kind, path, handoffRequest) => {
    const backend = mockStudioBackend();
    renderStudio(path);

    await screen.findByLabelText('运动名称');
    await waitFor(() => expect(screen.getByTestId('studio-location')).toHaveTextContent(
      `?draft=${FRESH_DRAFT_ID}`,
    ));
    expect(backend.requests.some((request) => request.path === handoffRequest)).toBe(true);
  });

  it('loads a changed search-param entry on the same mounted Studio page, then rebinds it', async () => {
    const user = userEvent.setup();
    const backend = mockStudioBackend();
    renderStudioWithEntrySwitcher();
    expect(await screen.findByLabelText('运动名称')).toHaveValue('Studio Motion');

    await user.click(screen.getByRole('button', { name: 'Open Pose entry' }));

    expect(await screen.findByLabelText('运动名称')).toHaveValue('Saved Pose Motion');
    await waitFor(() => expect(screen.getByTestId('studio-location')).toHaveTextContent(
      `?draft=${FRESH_DRAFT_ID}`,
    ));
    expect(backend.requests.some((request) => request.path === `/poses/${POSE_ID}`)).toBe(true);
  });

  it('applies the canonical autosave document without fabricating an Undo entry', async () => {
    const user = userEvent.setup();
    mockStudioBackend({ canonicalizeDraftName: true });
    renderStudio();
    const name = await screen.findByLabelText('运动名称');
    fireEvent.change(name, { target: { value: '  Canonical name  ' } });

    await waitFor(() => expect(name).toHaveValue('Canonical name'), { timeout: 1900 });
    await user.click(screen.getByRole('button', { name: '撤销上一次编排修改' }));
    expect(name).toHaveValue('Studio Motion');
  });

  it('supports keyboard timing edits and exposes a mobile Inspector drawer without page-level timeline overflow', async () => {
    const user = userEvent.setup();
    mockStudioBackend();
    renderStudio();
    const second = await screen.findByRole('button', { name: /关键帧 2：Frame B/ });
    second.focus();
    await user.keyboard('{ArrowRight}');
    const movedSecond = await screen.findByRole('button', { name: /关键帧 2：Frame B，时间 2\.25 秒/ });
    expect(movedSecond).toBeVisible();
    expect(screen.getByTestId('studio-timeline-scroll')).toHaveClass('studio-timeline-scroll');

    await user.click(movedSecond);
    await user.click(screen.getByRole('button', { name: '打开关键帧属性' }));
    expect(screen.getByRole('dialog', { name: '关键帧属性' })).toHaveClass('studio-inspector--mobile-open');
    expect(screen.getByLabelText('进入过渡时长（秒）')).toHaveValue(2.05);
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: '关键帧属性' })).not.toBeInTheDocument();
  });

  it('persists and recovers an absolute keyframe time edit as adjacent transition timing', async () => {
    const user = userEvent.setup();
    const backend = mockStudioBackend();
    const firstView = renderStudio();
    const second = await screen.findByRole('button', { name: /关键帧 2：Frame B/ });
    second.focus();
    await user.keyboard('{ArrowRight}');
    await waitFor(
      () => expect(backend.requests.some((request) => {
        if (request.method !== 'PUT') return false;
        const keyframes = (request.body as { keyframes?: MotionDraft['keyframes'] }).keyframes;
        return keyframes?.[1]?.incoming_transition?.duration_s === 2.05;
      })).toBe(true),
      { timeout: 1900 },
    );

    firstView.unmount();
    renderStudio();
    expect(await screen.findByText('2.05 s')).toBeVisible();
  });

  it('uses backend compile preview for client-only timeline playback and keeps real motion routes untouched', async () => {
    const user = userEvent.setup();
    const backend = mockStudioBackend();
    renderStudio();
    await screen.findByRole('button', { name: /关键帧 1/ });

    await user.click(screen.getByRole('button', { name: '播放仿真预览' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '暂停仿真预览' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: '暂停仿真预览' }));
    expect(screen.getByRole('button', { name: '播放仿真预览' })).toBeEnabled();
    expect(backend.requests.some((request) => request.path.endsWith('/compile'))).toBe(true);
    expect(backend.requests.some((request) => /\/(playback|motion)\//.test(request.path))).toBe(false);
  });

  it('renders a backend compile failure without fabricating a preview', async () => {
    const user = userEvent.setup();
    mockStudioBackend({ compileError: true });
    renderStudio();
    await screen.findByRole('button', { name: /关键帧 1/ });
    await user.click(screen.getByRole('button', { name: '播放仿真预览' }));
    expect(await screen.findByText('草稿转换失败')).toBeVisible();
    expect(screen.getByRole('button', { name: '暂停仿真预览' })).toBeDisabled();
  });

  it('does not expose real playback preparation or priority Stop in the editor', async () => {
    const backend = mockStudioBackend({ deferPreflight: true });
    renderStudio();
    await screen.findByRole('button', { name: /关键帧 1/ });
    expect(screen.queryByRole('button', { name: '准备播放' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '停止' })).not.toBeInTheDocument();
    expect(backend.requests.some((request) => request.path.includes('/preflight'))).toBe(false);
  });

  it('isolates the editor from a foreign hardware playback session', async () => {
    const backend = mockStudioBackend({ initialPlaybackState: 'PLAYING' });
    renderStudio();
    await screen.findByRole('button', { name: /关键帧 1/ });

    expect(screen.queryByRole('button', { name: '停止' })).not.toBeInTheDocument();
    expect(screen.queryByText(/另一个正式运动正在占用播放会话/)).not.toBeInTheDocument();
    expect(backend.requests.some((request) => request.path === '/playback/stop')).toBe(false);
  });

  it('never exposes or submits keyframe Goto from the timeline editor', async () => {
    const backend = mockStudioBackend({ deferGoto: true });
    renderStudio();
    await screen.findByRole('button', { name: /关键帧 1/ });
    expect(screen.queryByRole('button', { name: '仿真前往' })).not.toBeInTheDocument();
    expect(backend.requests.some((request) =>
      request.path === `/studio/drafts/${DRAFT_ID}/keyframes/${FRAME_A}/goto`
    )).toBe(false);
  });

  it('autosaves editor changes without submitting Goto or Stop commands', async () => {
    const user = userEvent.setup();
    const backend = mockStudioBackend({ deferFirstAutosave: true });
    renderStudio();
    const name = await screen.findByLabelText('运动名称');
    await user.type(name, ' edited');
    await waitFor(() => expect(backend.requests.some((request) =>
      request.path === `/studio/drafts/${DRAFT_ID}` && request.method === 'PUT'
    )).toBe(true));
    backend.resolveDeferredAutosave();
    await waitFor(() => expect(screen.getByLabelText('运动名称')).toHaveValue('Studio Motion edited'));
    expect(backend.requests.some((request) => request.path.includes('/keyframes/'))).toBe(false);
    expect(backend.requests.some((request) => request.path === '/robot/stop')).toBe(false);
  });

  it('does not surface an active Goto command inside the editor workspace', async () => {
    const backend = mockStudioBackend({ activeGoto: true });
    renderStudio();
    await screen.findByRole('button', { name: /关键帧 1/ });
    expect(screen.queryByText(/前往编排关键帧/)).not.toBeInTheDocument();
    expect(backend.requests.some((request) => request.path === '/motion/commands/goto-command')).toBe(false);
  });

  it('forks the latest imported draft, applies local null-sequence content, rebinds, then saves as', async () => {
    const user = userEvent.setup();
    const backend = mockStudioBackend({ conflictOnAutosave: true, draft: importedDraft() });
    renderStudio();
    const name = await screen.findByLabelText('运动名称');
    fireEvent.change(name, { target: { value: 'Local conflict edits' } });
    fireEvent.change(screen.getByLabelText('关键帧名称'), {
      target: { value: 'Local Legacy frame' },
    });

    const conflictDialog = await screen.findByRole('dialog', { name: /已保存的数据发生变化/ }, { timeout: 1900 });
    await user.click(within(conflictDialog).getByRole('button', { name: '另存为' }));
    const saveDialog = await screen.findByRole('dialog', { name: '运动另存为' });
    const saveName = within(saveDialog).getByLabelText('新运动名称');
    await user.clear(saveName);
    await user.type(saveName, 'Conflict-safe copy');
    await user.click(within(saveDialog).getByRole('button', { name: '保存为新运动' }));

    expect(await screen.findByText(/已将新的正式运动“Conflict-safe copy”保存为新 UUID/)).toBeVisible();
    expect(screen.getByLabelText('关键帧名称')).toHaveValue('Local Legacy frame');
    expect(screen.getByRole('button', { name: /关键帧 1：Local Legacy frame/ })).toBeVisible();
    await waitFor(() => expect(screen.getByTestId('studio-location')).toHaveTextContent(
      `?draft=${FRESH_DRAFT_ID}`,
    ));

    const conflictPutIndex = backend.requests.findIndex((request) =>
      request.path === `/studio/drafts/${DRAFT_ID}` && request.method === 'PUT'
    );
    const latestGetIndex = backend.requests.findIndex((request, index) =>
      index > conflictPutIndex && request.path === `/studio/drafts/${DRAFT_ID}` && request.method === 'GET'
    );
    const forkIndex = backend.requests.findIndex((request) =>
      request.path === `/studio/drafts/${DRAFT_ID}/fork` && request.method === 'POST'
    );
    const forkPutIndex = backend.requests.findIndex((request) =>
      request.path === `/studio/drafts/${FRESH_DRAFT_ID}` && request.method === 'PUT'
    );
    const saveAsIndex = backend.requests.findIndex((request) =>
      request.path === `/studio/drafts/${FRESH_DRAFT_ID}/save-as` && request.method === 'POST'
    );
    expect([conflictPutIndex, latestGetIndex, forkIndex, forkPutIndex, saveAsIndex]).toEqual(
      [...[conflictPutIndex, latestGetIndex, forkIndex, forkPutIndex, saveAsIndex]].sort((left, right) => left - right),
    );
    expect(backend.requests[forkIndex]?.body).toEqual({ expected_revision: 4 });
    const forkUpdate = backend.requests[forkPutIndex]?.body as Record<string, unknown>;
    expect(forkUpdate).toMatchObject({
      expected_revision: 1,
      name: 'Local conflict edits',
    });
    expect((forkUpdate.keyframes as MotionDraft['keyframes'])[0].pose_snapshot.state_sequence).toBeNull();
    expect(forkUpdate).not.toHaveProperty('source_metadata');
    expect(forkUpdate).not.toHaveProperty('trusted_legacy_snapshot_sha256');
    expect(backend.requests.some((request) =>
      request.path === '/studio/drafts' && request.method === 'POST'
    )).toBe(false);
  });

  it('keeps local imported edits and the original URL when the exact-revision fork loses a race', async () => {
    const user = userEvent.setup();
    const backend = mockStudioBackend({
      conflictOnAutosave: true,
      draft: importedDraft(),
      rejectFork: true,
    });
    renderStudio();
    const name = await screen.findByLabelText('运动名称');
    fireEvent.change(name, { target: { value: 'Local race-safe edits' } });

    const conflictDialog = await screen.findByRole('dialog', { name: /已保存的数据发生变化/ }, { timeout: 1900 });
    await user.click(within(conflictDialog).getByRole('button', { name: '另存为' }));
    const saveDialog = await screen.findByRole('dialog', { name: '运动另存为' });
    await user.click(within(saveDialog).getByRole('button', { name: '保存为新运动' }));

    expect(await screen.findByText('Draft changed again before it could be forked')).toBeVisible();
    expect(screen.getByLabelText('运动名称')).toHaveValue('Local race-safe edits');
    expect(screen.getByTestId('studio-location')).toHaveTextContent(`?draft=${DRAFT_ID}`);
    expect(within(saveDialog).getByRole('button', { name: '保存为新运动' })).toBeEnabled();
    expect(backend.requests.find((request) =>
      request.path === `/studio/drafts/${DRAFT_ID}/fork`
    )?.body).toEqual({ expected_revision: 4 });
    expect(backend.requests.some((request) =>
      request.path === `/studio/drafts/${FRESH_DRAFT_ID}` && request.method === 'PUT'
    )).toBe(false);
    expect(backend.requests.some((request) => request.path.endsWith('/save-as'))).toBe(false);
  });

  it('recovers and forks a Motion conflict so post-conflict local edits survive Save As', async () => {
    const user = userEvent.setup();
    const sourceLinked = {
      ...draft(),
      source_motion_id: MOTION_ID,
      source_motion_revision: motion.revision,
      revision: 1,
    } satisfies MotionDraft;
    const backend = mockStudioBackend({ conflictOnFormalSave: true, draft: sourceLinked });
    renderStudio();
    await screen.findByLabelText('运动名称');
    await user.click(screen.getByRole('button', { name: '保存' }));

    const conflictDialog = await screen.findByRole('dialog', { name: /已保存的数据发生变化/ });
    await user.click(within(conflictDialog).getByRole('button', { name: '继续本地编辑' }));
    fireEvent.change(screen.getByLabelText('运动名称'), {
      target: { value: 'Post-conflict working name' },
    });
    fireEvent.change(screen.getByLabelText('关键帧名称'), {
      target: { value: 'Post-conflict local frame' },
    });
    await user.click(within(screen.getByLabelText('编排文档控制')).getByRole(
      'button',
      { name: '另存为' },
    ));
    const saveDialog = await screen.findByRole('dialog', { name: '运动另存为' });
    const saveName = within(saveDialog).getByLabelText('新运动名称');
    await user.clear(saveName);
    await user.type(saveName, 'Motion conflict copy');
    await user.click(within(saveDialog).getByRole('button', { name: '保存为新运动' }));

    expect(await screen.findByText(/已将新的正式运动“Motion conflict copy”保存为新 UUID/)).toBeVisible();
    expect(screen.getByLabelText('关键帧名称')).toHaveValue('Post-conflict local frame');
    expect(backend.requests.some((request) =>
      request.path === '/studio/drafts' && request.method === 'POST'
    )).toBe(false);
    expect(backend.requests.filter((request) =>
      request.path === `/studio/drafts/${DRAFT_ID}` && request.method === 'GET'
    )).toHaveLength(2);
    const saveIndex = backend.requests.findIndex((request) =>
      request.path === `/studio/drafts/${DRAFT_ID}/save`
    );
    const recoveryGetIndex = backend.requests.findIndex((request, index) =>
      index > saveIndex && request.path === `/studio/drafts/${DRAFT_ID}` && request.method === 'GET'
    );
    const forkIndex = backend.requests.findIndex((request) =>
      request.path === `/studio/drafts/${DRAFT_ID}/fork`
    );
    const forkPutIndex = backend.requests.findIndex((request) =>
      request.path === `/studio/drafts/${FRESH_DRAFT_ID}` && request.method === 'PUT'
    );
    const saveAsIndex = backend.requests.findIndex((request) =>
      request.path === `/studio/drafts/${FRESH_DRAFT_ID}/save-as`
    );
    expect(saveIndex).toBeLessThan(recoveryGetIndex);
    expect(recoveryGetIndex).toBeLessThan(forkIndex);
    expect(forkIndex).toBeLessThan(forkPutIndex);
    expect(forkPutIndex).toBeLessThan(saveAsIndex);
    expect(backend.requests[forkIndex]?.body).toEqual({ expected_revision: 3 });
    const forkUpdate = backend.requests[forkPutIndex]?.body as {
      expected_revision: number;
      keyframes: MotionDraft['keyframes'];
      name: string;
    };
    expect(forkUpdate).toMatchObject({
      expected_revision: 1,
      name: 'Post-conflict working name',
    });
    expect(forkUpdate.keyframes[0].label).toBe('Post-conflict local frame');
    expect(backend.requests[saveAsIndex]?.body).toEqual({
      expected_revision: 2,
      name: 'Motion conflict copy',
      sample_rate_hz: 25,
    });
    await waitFor(() => expect(screen.getByTestId('studio-location')).toHaveTextContent(
      `?draft=${FRESH_DRAFT_ID}`,
    ));
  });

  it('classifies a formal Save Draft race and forks the latest server draft without losing local content', async () => {
    const user = userEvent.setup();
    const backend = mockStudioBackend({ draftConflictOnFormalSave: true });
    renderStudio();
    await screen.findByLabelText('运动名称');
    fireEvent.change(screen.getByLabelText('关键帧名称'), {
      target: { value: 'Local formal-save frame' },
    });
    await waitFor(() => expect(backend.requests.some((request) =>
      request.path === `/studio/drafts/${DRAFT_ID}` && request.method === 'PUT'
    )).toBe(true), { timeout: 1900 });

    await user.click(screen.getByRole('button', { name: '保存' }));
    const conflictDialog = await screen.findByRole('dialog', { name: /已保存的数据发生变化/ });
    await user.click(within(conflictDialog).getByRole('button', { name: '另存为' }));
    const saveDialog = await screen.findByRole('dialog', { name: '运动另存为' });
    const saveName = within(saveDialog).getByLabelText('新运动名称');
    await user.clear(saveName);
    await user.type(saveName, 'Local formal-save copy');
    await user.click(within(saveDialog).getByRole('button', { name: '保存为新运动' }));

    expect(await screen.findByText(/已将新的正式运动“Local formal-save copy”保存为新 UUID/)).toBeVisible();
    expect(screen.getByLabelText('关键帧名称')).toHaveValue('Local formal-save frame');
    const saveIndex = backend.requests.findIndex((request) =>
      request.path === `/studio/drafts/${DRAFT_ID}/save`
    );
    const latestGetIndex = backend.requests.findIndex((request, index) =>
      index > saveIndex && request.path === `/studio/drafts/${DRAFT_ID}` && request.method === 'GET'
    );
    const forkIndex = backend.requests.findIndex((request) => request.path.endsWith('/fork'));
    const forkPutIndex = backend.requests.findIndex((request) =>
      request.path === `/studio/drafts/${FRESH_DRAFT_ID}` && request.method === 'PUT'
    );
    expect(saveIndex).toBeLessThan(latestGetIndex);
    expect(latestGetIndex).toBeLessThan(forkIndex);
    expect(forkIndex).toBeLessThan(forkPutIndex);
    expect(backend.requests[forkIndex]?.body).toEqual({ expected_revision: 5 });
    expect(((backend.requests[forkPutIndex]?.body as {
      keyframes: MotionDraft['keyframes'];
    }).keyframes)[0].label).toBe('Local formal-save frame');
  });

  it('turns a direct Save As Draft race into a retryable fork while retaining different local content', async () => {
    const user = userEvent.setup();
    const backend = mockStudioBackend({ draftConflictOnSaveAs: true });
    renderStudio();
    await screen.findByLabelText('运动名称');
    fireEvent.change(screen.getByLabelText('关键帧名称'), {
      target: { value: 'Local direct-save-as frame' },
    });
    await waitFor(() => expect(backend.requests.some((request) =>
      request.path === `/studio/drafts/${DRAFT_ID}` && request.method === 'PUT'
    )).toBe(true), { timeout: 1900 });

    await user.click(screen.getByRole('button', { name: '另存为' }));
    let saveDialog = await screen.findByRole('dialog', { name: '运动另存为' });
    const saveName = within(saveDialog).getByLabelText('新运动名称');
    await user.clear(saveName);
    await user.type(saveName, 'Direct race copy');
    await user.click(within(saveDialog).getByRole('button', { name: '保存为新运动' }));
    expect(await screen.findByText('MotionDraft revision changed before Save As')).toBeVisible();
    await user.click(within(saveDialog).getByRole('button', { name: '关闭另存为对话框' }));

    const conflictDialog = await screen.findByRole('dialog', { name: /已保存的数据发生变化/ });
    await user.click(within(conflictDialog).getByRole('button', { name: '另存为' }));
    saveDialog = await screen.findByRole('dialog', { name: '运动另存为' });
    const retryName = within(saveDialog).getByLabelText('新运动名称');
    await user.clear(retryName);
    await user.type(retryName, 'Direct race copy');
    await user.click(within(saveDialog).getByRole('button', { name: '保存为新运动' }));

    expect(await screen.findByText(/已将新的正式运动“Direct race copy”保存为新 UUID/)).toBeVisible();
    expect(screen.getByLabelText('关键帧名称')).toHaveValue('Local direct-save-as frame');
    expect(backend.requests.filter((request) => request.path.endsWith('/save-as'))).toHaveLength(2);
    const forkPut = backend.requests.find((request) =>
      request.path === `/studio/drafts/${FRESH_DRAFT_ID}` && request.method === 'PUT'
    );
    expect(((forkPut?.body as { keyframes: MotionDraft['keyframes'] }).keyframes)[0].label).toBe(
      'Local direct-save-as frame',
    );
    await waitFor(() => expect(screen.getByTestId('studio-location')).toHaveTextContent(
      `?draft=${FRESH_DRAFT_ID}`,
    ));
  });

  it.each(['compile'] as const)(
    'classifies a post-persist %s Draft race and keeps local editor content for Reload or Save As',
    async (operation) => {
      const user = userEvent.setup();
      const backend = mockStudioBackend({ draftConflictOnCommand: operation });
      renderStudio();
      await screen.findByLabelText('运动名称');
      fireEvent.change(screen.getByLabelText('关键帧名称'), {
        target: { value: `Local ${operation} frame` },
      });
      await waitFor(() => expect(backend.requests.some((request) =>
        request.path === `/studio/drafts/${DRAFT_ID}` && request.method === 'PUT'
      )).toBe(true), { timeout: 1900 });

      await user.click(screen.getByRole('button', { name: '播放仿真预览' }));

      const conflictDialog = await screen.findByRole('dialog', { name: /已保存的数据发生变化/ });
      expect(within(conflictDialog).getByRole('button', { name: '重新加载' })).toBeEnabled();
      expect(within(conflictDialog).getByRole('button', { name: '另存为' })).toBeEnabled();
      expect(screen.getByLabelText('关键帧名称')).toHaveValue(`Local ${operation} frame`);
      expect(backend.requests.some((request) => request.path.endsWith('/fork'))).toBe(false);
    },
  );

  it.each(['missing', 'recovery', 'unknown'] as const)(
    'keeps an active %s formal-save conflict generic and never exposes the initialization Release flow',
    async (kind) => {
      const user = userEvent.setup();
      mockStudioBackend({ activeSaveConflict: kind });
      renderStudio();
      await screen.findByLabelText('运动名称');
      await user.click(screen.getByRole('button', { name: '保存' }));

      expect(await screen.findByText(`Fail-closed ${kind} formal save conflict`)).toBeVisible();
      expect(screen.queryByRole('dialog', { name: /已保存的数据发生变化/ })).not.toBeInTheDocument();
      expect(screen.queryByRole('dialog', { name: '需要处理未完成的正式保存' })).not.toBeInTheDocument();
      expect(screen.getByLabelText('运动名称')).toBeVisible();
    },
  );

  it.each(['missing', 'motion', 'unknown'] as const)(
    'keeps a direct Save As %s conflict generic instead of guessing a Draft conflict',
    async (kind) => {
      const user = userEvent.setup();
      mockStudioBackend({ saveAsNonDraftConflict: kind });
      renderStudio();
      await screen.findByLabelText('运动名称');
      await user.click(screen.getByRole('button', { name: '另存为' }));
      const saveDialog = await screen.findByRole('dialog', { name: '运动另存为' });
      await user.click(within(saveDialog).getByRole('button', { name: '保存为新运动' }));

      expect(await screen.findByText(`Fail-closed ${kind} Save As conflict`)).toBeVisible();
      await user.click(within(saveDialog).getByRole('button', { name: '关闭另存为对话框' }));
      expect(screen.queryByRole('dialog', { name: /已保存的数据发生变化/ })).not.toBeInTheDocument();
      expect(screen.getByLabelText('运动名称')).toBeVisible();
    },
  );

  it('fences a delayed old autosave when New Draft switches workspace identity', async () => {
    const user = userEvent.setup();
    const backend = mockStudioBackend({ deferFirstAutosave: true });
    renderStudio();
    const name = await screen.findByLabelText('运动名称');
    await user.clear(name);
    await user.type(name, 'Old draft edit');
    await waitFor(
      () => expect(backend.requests.some((request) =>
        request.path === `/studio/drafts/${DRAFT_ID}` && request.method === 'PUT'
      )).toBe(true),
      { timeout: 1900 },
    );

    await user.click(screen.getByRole('button', { name: '新建草稿' }));
    await user.click(within(await screen.findByRole('dialog', { name: '新建空白草稿？' })).getByRole('button', { name: '新建草稿' }));
    expect(screen.queryByText(/已创建空白自动保存草稿/)).not.toBeInTheDocument();
    backend.resolveDeferredAutosave();
    expect(await screen.findByText(/已创建空白自动保存草稿/)).toBeVisible();
    await waitFor(() => expect(screen.getByTestId('studio-location')).toHaveTextContent(
      `?draft=${FRESH_DRAFT_ID}`,
    ));

    const newName = screen.getByLabelText('运动名称');
    await user.clear(newName);
    await user.type(newName, 'Fresh identity edit');
    await waitFor(
      () => expect(backend.requests.some((request) =>
        request.path === `/studio/drafts/${FRESH_DRAFT_ID}` && request.method === 'PUT'
      )).toBe(true),
      { timeout: 1900 },
    );
    expect((backend.requests.filter((request) => request.method === 'PUT').at(-1)?.body as { name: string }).name).toBe('Fresh identity edit');
  });

  it('keeps the current workspace when the required pre-New autosave rejects', async () => {
    const user = userEvent.setup();
    const backend = mockStudioBackend({ deferFirstAutosave: true });
    renderStudio();
    const name = await screen.findByLabelText('运动名称');
    await user.clear(name);
    await user.type(name, 'Old edit that will fail');
    await waitFor(
      () => expect(backend.requests.some((request) =>
        request.path === `/studio/drafts/${DRAFT_ID}` && request.method === 'PUT'
      )).toBe(true),
      { timeout: 1900 },
    );

    await user.click(screen.getByRole('button', { name: '新建草稿' }));
    await user.click(within(await screen.findByRole('dialog', { name: '新建空白草稿？' })).getByRole('button', { name: '新建草稿' }));
    backend.rejectDeferredAutosave();

    expect(await screen.findByText('Old workspace write failed')).toBeVisible();
    expect(screen.getByLabelText('运动名称')).toHaveValue('Old edit that will fail');
    expect(backend.requests.some((request) => request.path === '/studio/drafts' && request.method === 'POST')).toBe(false);
    expect(screen.getByTestId('studio-location')).toHaveTextContent(`?draft=${DRAFT_ID}`);
  });

  it('flushes an edit before New even when the autosave debounce has not fired', async () => {
    const user = userEvent.setup();
    const backend = mockStudioBackend();
    renderStudio();
    const name = await screen.findByLabelText('运动名称');
    fireEvent.change(name, { target: { value: 'Immediate edit' } });
    await user.click(screen.getByRole('button', { name: '新建草稿' }));
    await user.click(within(await screen.findByRole('dialog', { name: '新建空白草稿？' })).getByRole('button', { name: '新建草稿' }));

    expect(await screen.findByText(/已创建空白自动保存草稿/)).toBeVisible();
    const oldSaveIndex = backend.requests.findIndex((request) =>
      request.path === `/studio/drafts/${DRAFT_ID}` && request.method === 'PUT'
    );
    const createIndex = backend.requests.findIndex((request) =>
      request.path === '/studio/drafts' && request.method === 'POST'
    );
    expect(oldSaveIndex).toBeGreaterThan(-1);
    expect(createIndex).toBeGreaterThan(oldSaveIndex);
    expect((backend.requests[oldSaveIndex].body as { name: string }).name).toBe('Immediate edit');
  });

  it('keeps a formal-dirty guard after draft autosave for unload and internal navigation', async () => {
    const user = userEvent.setup();
    mockStudioBackend({ draft: draft(0) });
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderStudio();
    const name = await screen.findByLabelText('运动名称');
    await user.clear(name);
    await user.type(name, 'Unsaved formal name');
    expect(screen.getByText('运动有未保存修改')).toBeVisible();

    const unload = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(unload);
    expect(unload.defaultPrevented).toBe(true);
    const historyGo = vi.spyOn(window.history, 'go').mockImplementation(() => undefined);
    window.dispatchEvent(new PopStateEvent('popstate', { state: { idx: -1 } }));
    expect(historyGo).toHaveBeenCalledWith(1);
    window.dispatchEvent(new PopStateEvent('popstate', { state: { idx: 0 } }));
    window.dispatchEvent(new PopStateEvent('popstate', { state: { idx: 1 } }));
    expect(historyGo).toHaveBeenCalledWith(-1);
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('heading', { level: 1, name: '编辑' })).toBeVisible();
  });

  it('keeps invalid numeric input from poisoning the draft document', async () => {
    const user = userEvent.setup();
    const backend = mockStudioBackend();
    renderStudio();
    await user.click(await screen.findByRole('button', { name: /关键帧 2：Frame B/ }));
    const duration = screen.getByLabelText('进入过渡时长（秒）');
    fireEvent.change(duration, { target: { value: '-1' } });
    expect(duration).toHaveValue(2);
    await waitFor(
      () => expect(backend.requests.filter((request) => request.method === 'PUT').length).toBe(0),
      { timeout: 850 },
    );
  });
});
