import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  getMotionCommand,
  getPlayback,
  gotoMotionDraftKeyframe,
  pausePlayback,
  playMotion,
  preflightMotion,
  resumePlayback,
  stopMotion,
  stopPlayback,
} from '../../api/client';
import type {
  MotionDraft,
  MotionEntity,
  PlaybackStatus,
  PoseSnapshot,
  RobotProfile,
  TrajectoryPreflightReport,
} from '../../api/types';
import {
  SAFE_RUNTIME_STATUS,
  type RuntimeStatus,
} from '../../components/runtimeStatusContext';
import { robotFor, stage3Ids, v2Profile } from '../../test/stage3Fixtures';
import { motionKeyframesToStudioDocument } from './studioEditorState';
import { useStudioMotionSession } from './useStudioMotionSession';

vi.mock('../../api/client', () => ({
  getMotionCommand: vi.fn(),
  getPlayback: vi.fn(),
  gotoMotionDraftKeyframe: vi.fn(),
  pausePlayback: vi.fn(),
  playMotion: vi.fn(),
  preflightMotion: vi.fn(),
  resumePlayback: vi.fn(),
  stopMotion: vi.fn(),
  stopPlayback: vi.fn(),
}));

const DRAFT_ID = '11111111-1111-4111-8111-111111111111';
const MOTION_ID = '22222222-2222-4222-8222-222222222222';
const FRAME_A = '33333333-3333-4333-8333-333333333333';
const FRAME_B = '44444444-4444-4444-8444-444444444444';

function snapshot(x: number): PoseSnapshot {
  return {
    robot_variant: 'V2',
    joint_state: {
      positions: Object.fromEntries(v2Profile.enabled_joints.map((jointId, index) => [jointId, x + index])),
      units: Object.fromEntries(
        v2Profile.enabled_joints.map((jointId) => [jointId, jointId === 'j10' ? 'mm' : 'deg']),
      ),
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

function draft(): MotionDraft {
  return {
    schema_version: '1.0.0',
    id: DRAFT_ID,
    source_motion_id: MOTION_ID,
    source_motion_revision: 1,
    name: 'Motion session test',
    description: '',
    robot_variant: 'V2',
    keyframes: [{
      id: FRAME_A,
      label: 'Frame A',
      pose_snapshot: snapshot(100),
      source_pose_id: null,
      hold_s: 0,
      incoming_transition: null,
    }, {
      id: FRAME_B,
      label: 'Frame B',
      pose_snapshot: snapshot(150),
      source_pose_id: null,
      hold_s: 0,
      incoming_transition: {
        duration_s: 1,
        motion_mode: 'JOINT',
        easing: 'SMOOTHSTEP',
      },
    }],
    playback_defaults: { loop: false, speed_multiplier: 1 },
    tags: [],
    source_metadata: null,
    trusted_legacy_snapshot_sha256: [],
    editor_metadata: {
      selected_keyframe_id: FRAME_A,
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

function motion(source: MotionDraft): MotionEntity {
  return {
    schema_version: '2.0.0',
    id: MOTION_ID,
    name: source.name,
    description: source.description,
    robot_variant: source.robot_variant,
    keyframes: source.keyframes,
    playback_defaults: source.playback_defaults,
    tags: source.tags,
    source_metadata: null,
    created_at: source.created_at,
    updated_at: source.updated_at,
    revision: 1,
  };
}

function playback(state: PlaybackStatus['state']): PlaybackStatus {
  return {
    session_id: state === 'IDLE' ? null : 'session-1',
    state,
    motion_id: state === 'IDLE' ? null : MOTION_ID,
    trajectory_digest: state === 'IDLE' ? null : 'sha256:prepared',
    progress: 0,
    elapsed_s: 0,
    duration_s: state === 'IDLE' ? 0 : 1,
    current_keyframe_id: state === 'IDLE' ? null : FRAME_A,
    current_segment_index: state === 'IDLE' ? null : 0,
    current_sample_index: state === 'IDLE' ? null : 0,
    loop: false,
    rate: 1,
    error: null,
    updated_at: '2026-08-24T02:00:00Z',
    hardware_accessed: false,
  };
}

const preflight: TrajectoryPreflightReport = {
  passed: true,
  digest: 'sha256:prepared',
  motion_id: MOTION_ID,
  motion_revision: 1,
  duration_s: 1,
  sample_count: 21,
  segment_count: 1,
  sample_rate_hz: 20,
  violations: [],
  checks: [{ name: 'limits', passed: true, detail: 'All samples are within limits' }],
  prepared_at: '2026-08-24T02:00:00Z',
};

function runtime(): RuntimeStatus {
  return {
    ...SAFE_RUNTIME_STATUS,
    backend: 'connected',
    stale: false,
    robot: robotFor('V2', true) as RuntimeStatus['robot'],
    profile: {
      profile: v2Profile as RobotProfile,
      fingerprint: stage3Ids.profileFingerprint,
      kinematics_fingerprint: stage3Ids.kinematicsFingerprint,
      real_eligible: false,
    },
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe('useStudioMotionSession', () => {
  it('lets priority Stop invalidate an in-flight preflight result', async () => {
    vi.useFakeTimers();
    const sourceDraft = draft();
    const pendingPreflight = deferred<TrajectoryPreflightReport>();
    vi.mocked(getPlayback).mockReturnValue(new Promise<PlaybackStatus>(() => undefined));
    vi.mocked(preflightMotion).mockReturnValue(pendingPreflight.promise);
    vi.mocked(stopPlayback).mockResolvedValue(playback('STOPPED'));

    const onError = vi.fn();
    const { result } = renderHook(() => useStudioMotionSession({
      document: motionKeyframesToStudioDocument(sourceDraft.keyframes, {
        name: sourceDraft.name,
        robotVariant: sourceDraft.robot_variant,
      }),
      onDraftConflict: vi.fn(() => false),
      onError,
      onMessage: vi.fn(),
      persistWorkspace: vi.fn().mockResolvedValue(sourceDraft),
      runtime: runtime(),
      savedMotion: motion(sourceDraft),
    }));
    await act(async () => Promise.resolve());

    let prepare!: Promise<void>;
    act(() => {
      prepare = result.current.preparePlayback();
    });
    expect(result.current.action).toBe('prepare-playback');

    await act(async () => {
      await result.current.stop();
    });
    expect(stopPlayback).toHaveBeenCalledTimes(1);
    expect(result.current.playback?.state).toBe('STOPPED');

    await act(async () => {
      pendingPreflight.resolve(preflight);
      await prepare;
    });
    expect(result.current.playbackPreflight).toBeNull();
    expect(result.current.playback?.state).toBe('STOPPED');
    expect(onError).not.toHaveBeenCalledWith(expect.stringMatching(/failed/i));
  });

  it('issues a compensating Stop after an in-flight Goto settles and ignores its stale command', async () => {
    vi.useFakeTimers();
    const sourceDraft = draft();
    const pendingGoto = deferred<Awaited<ReturnType<typeof gotoMotionDraftKeyframe>>>();
    const order: string[] = [];
    vi.mocked(getPlayback).mockResolvedValue(playback('IDLE'));
    vi.mocked(gotoMotionDraftKeyframe).mockImplementation(async () => {
      order.push('goto');
      return pendingGoto.promise;
    });
    vi.mocked(stopMotion).mockImplementation(async () => {
      order.push(`stop-${vi.mocked(stopMotion).mock.calls.length}`);
      return {
        result: 'STOPPED',
        status: robotFor('V2', true) as NonNullable<RuntimeStatus['robot']>,
        hardware_accessed: false,
      };
    });
    const persistWorkspace = vi.fn(async () => {
      order.push('persist');
      return sourceDraft;
    });
    const onMessage = vi.fn();
    const { result } = renderHook(() => useStudioMotionSession({
      document: motionKeyframesToStudioDocument(sourceDraft.keyframes, {
        name: sourceDraft.name,
        robotVariant: sourceDraft.robot_variant,
      }),
      onDraftConflict: vi.fn(() => false),
      onError: vi.fn(),
      onMessage,
      persistWorkspace,
      runtime: runtime(),
      savedMotion: motion(sourceDraft),
    }));
    await act(async () => Promise.resolve());

    let goto!: Promise<void>;
    act(() => {
      goto = result.current.gotoFrame(FRAME_A);
    });
    await act(async () => Promise.resolve());
    expect(order).toEqual(['persist', 'goto']);

    let stop!: Promise<void>;
    act(() => {
      stop = result.current.stop();
    });
    await act(async () => Promise.resolve());
    expect(order).toEqual(['persist', 'goto', 'stop-1']);

    await act(async () => {
      order.push('goto-response');
      pendingGoto.resolve({
        command_id: 'goto-command',
        command: { command_id: 'goto-command', state: 'RUNNING' },
        preflight: null,
        hardware_accessed: false,
      });
      await goto;
      await stop;
    });

    expect(order).toEqual(['persist', 'goto', 'stop-1', 'goto-response', 'stop-2']);
    expect(stopMotion).toHaveBeenCalledTimes(2);
    expect(getMotionCommand).not.toHaveBeenCalled();
    expect(result.current.studioCommand).toBeNull();
    expect(result.current.action).toBeNull();
    expect(onMessage).toHaveBeenCalledWith(
      '当前仿真运动链路已接受优先停止请求。',
    );
    expect(playMotion).not.toHaveBeenCalled();
    expect(pausePlayback).not.toHaveBeenCalled();
    expect(resumePlayback).not.toHaveBeenCalled();
  });
});
