import { useCallback, useEffect, useRef, useState } from 'react';

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
import { STUDIO_EXECUTION_HZ } from './studioExecution';
import type {
  MotionCommandStatus,
  MotionDraft,
  MotionEntity,
  PlaybackStatus,
  TrajectoryPreflightReport,
} from '../../api/types';
import {
  realCapabilityAvailability,
  useRealSession,
  type RealSessionSummary,
} from '../../components/realSessionContext';
import type { RuntimeStatus } from '../../components/runtimeStatusContext';
import type { StudioDraftDocument } from './studioEditorState';

const PLAYBACK_POLL_MS = 350;

const ACTIVE_STUDIO_COMMAND_STATES = new Set<MotionCommandStatus['state']>([
  'ACCEPTED',
  'PREFLIGHTING',
  'READY',
  'RUNNING',
  'PLAYING',
  'PAUSED',
  'STOPPING',
]);

interface UseStudioMotionSessionOptions {
  document: StudioDraftDocument;
  onDraftConflict: (error: unknown, expectedRevision: number | null) => boolean;
  onError: (error: string | null) => void;
  onMessage: (message: string) => void;
  persistWorkspace: () => Promise<MotionDraft>;
  runtime: RuntimeStatus;
  savedMotion: MotionEntity | null;
}

function id(): string {
  return globalThis.crypto.randomUUID();
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : '编排操作失败。';
}

function motionDisabledReason(
  runtime: RuntimeStatus,
  realSession: RealSessionSummary,
  capability: 'real_joint_motion' | 'real_playback',
): string | null {
  if (runtime.backend !== 'connected') return '后端不可用';
  if (!runtime.robot?.connected) {
    return runtime.controlMode === 'REAL'
      ? '后端显示真机尚未连接'
      : '请先连接仿真机械臂';
  }
  if (runtime.robot.stale || runtime.stale) return '机械臂状态已经过期';
  if (!runtime.profile) return '机械臂配置不可用';
  if (runtime.controlMode === 'REAL') {
    const availability = realCapabilityAvailability(realSession, capability);
    return availability.allowed ? null : availability.reason;
  }
  if (runtime.hardwareAccessPolicy !== 'DISABLED' || runtime.realMotionEnabled !== false) {
    return '仿真运行的硬件隔离不可用';
  }
  return null;
}

function draftMotionDisabledReason(
  runtime: RuntimeStatus,
  document: StudioDraftDocument,
  realSession: RealSessionSummary,
  capability: 'real_joint_motion' | 'real_playback',
): string | null {
  const runtimeReason = motionDisabledReason(runtime, realSession, capability);
  if (runtimeReason) return runtimeReason;
  if (runtime.robot?.variant !== document.robotVariant) {
    return `当前机械臂是 ${runtime.robot?.variant ?? '不可用'}，草稿型号是 ${document.robotVariant}`;
  }
  const reference = document.frames[0]?.poseSnapshot;
  if (!reference) return null;
  if (reference.robot_variant !== document.robotVariant) return '草稿快照中的机械臂型号不一致';
  if (reference.profile_fingerprint !== runtime.profile?.fingerprint) {
    return '当前配置与草稿快照不匹配';
  }
  if (reference.kinematics_fingerprint !== runtime.profile?.kinematics_fingerprint) {
    return '当前运动学模型与草稿快照不匹配';
  }
  const enabledJoints = runtime.profile?.profile.enabled_joints ?? [];
  const snapshotJoints = Object.keys(reference.joint_state.positions);
  if (
    enabledJoints.length !== snapshotJoints.length ||
    enabledJoints.some((jointId) => !Object.hasOwn(reference.joint_state.positions, jointId))
  ) {
    return '草稿快照的关节集合与当前配置不匹配';
  }
  const expectedUnits = new Map(
    runtime.profile?.profile.joint_definitions.map((joint) => [joint.joint_id, joint.domain_unit]),
  );
  if (enabledJoints.some((jointId) => reference.joint_state.units[jointId] !== expectedUnits.get(jointId))) {
    return '草稿快照的单位与当前配置不匹配';
  }
  return null;
}

export function useStudioMotionSession({
  document,
  onDraftConflict,
  onError,
  onMessage,
  persistWorkspace,
  runtime,
  savedMotion,
}: UseStudioMotionSessionOptions) {
  const { summary: realSession } = useRealSession();
  const [action, setAction] = useState<string | null>(null);
  const [playbackPreflight, setPlaybackPreflight] = useState<TrajectoryPreflightReport | null>(null);
  const [playback, setPlayback] = useState<PlaybackStatus | null>(null);
  const [studioCommand, setStudioCommand] = useState<MotionCommandStatus | null>(null);
  const [studioCommandPollGeneration, setStudioCommandPollGeneration] = useState(0);
  const documentRef = useRef(document);
  const playbackEpochRef = useRef(0);
  const playbackActionRef = useRef<string | null>(null);
  const actionRef = useRef(action);
  const studioCommandRef = useRef(studioCommand);
  const studioCommandEpochRef = useRef(0);
  const studioGotoRequestRef = useRef<Promise<void> | null>(null);

  documentRef.current = document;
  actionRef.current = action;
  studioCommandRef.current = studioCommand;

  useEffect(() => {
    setPlaybackPreflight(null);
  }, [document, savedMotion?.id, savedMotion?.revision]);

  const preparePlayback = useCallback(async () => {
    if (!savedMotion || draftMotionDisabledReason(
      runtime,
      documentRef.current,
      realSession,
      'real_playback',
    )) return;
    const actionName = 'prepare-playback';
    const epoch = playbackEpochRef.current + 1;
    playbackEpochRef.current = epoch;
    playbackActionRef.current = actionName;
    setAction(actionName);
    onError(null);
    try {
      const report = await preflightMotion(savedMotion.id, {
        expected_revision: savedMotion.revision,
        sample_rate_hz: STUDIO_EXECUTION_HZ,
      });
      if (playbackEpochRef.current !== epoch) return;
      const status = await getPlayback();
      if (playbackEpochRef.current !== epoch) return;
      playbackEpochRef.current += 1;
      setPlaybackPreflight(report);
      setPlayback(status);
    } catch (caught) {
      if (playbackEpochRef.current === epoch) {
        playbackEpochRef.current += 1;
        onError(message(caught));
      }
    } finally {
      if (playbackActionRef.current === actionName) {
        playbackActionRef.current = null;
        setAction((currentAction) => currentAction === actionName ? null : currentAction);
      }
    }
  }, [onError, realSession, runtime, savedMotion]);

  const play = useCallback(async () => {
    if (!savedMotion || !playbackPreflight?.passed || !playbackPreflight.digest ||
      draftMotionDisabledReason(
        runtime,
        documentRef.current,
        realSession,
        'real_playback',
      )) return;
    const actionName = 'play';
    const epoch = playbackEpochRef.current + 1;
    playbackEpochRef.current = epoch;
    playbackActionRef.current = actionName;
    setAction(actionName);
    onError(null);
    try {
      const status = await playMotion(savedMotion.id, {
        expected_revision: savedMotion.revision,
        trajectory_digest: playbackPreflight.digest,
        loop: savedMotion.playback_defaults.loop,
        rate: Math.min(2, savedMotion.playback_defaults.speed_multiplier),
      });
      if (playbackEpochRef.current !== epoch) return;
      playbackEpochRef.current += 1;
      setPlayback(status);
    } catch (caught) {
      if (playbackEpochRef.current === epoch) {
        playbackEpochRef.current += 1;
        onError(message(caught));
      }
    } finally {
      if (playbackActionRef.current === actionName) {
        playbackActionRef.current = null;
        setAction((currentAction) => currentAction === actionName ? null : currentAction);
      }
    }
  }, [onError, playbackPreflight, realSession, runtime, savedMotion]);

  const playbackAction = useCallback(async (
    actionName: string,
    operation: () => Promise<PlaybackStatus>,
  ) => {
    const epoch = playbackEpochRef.current + 1;
    playbackEpochRef.current = epoch;
    playbackActionRef.current = actionName;
    setAction(actionName);
    onError(null);
    try {
      const status = await operation();
      if (playbackEpochRef.current !== epoch) return;
      playbackEpochRef.current += 1;
      setPlayback(status);
    } catch (caught) {
      if (playbackEpochRef.current === epoch) {
        playbackEpochRef.current += 1;
        onError(message(caught));
      }
    } finally {
      if (playbackActionRef.current === actionName) {
        playbackActionRef.current = null;
        setAction((currentAction) => currentAction === actionName ? null : currentAction);
      }
    }
  }, [onError]);

  useEffect(() => {
    if (runtime.backend !== 'connected') return;
    let cancelled = false;
    let inFlight = false;
    const poll = () => {
      if (inFlight) return;
      inFlight = true;
      const epoch = playbackEpochRef.current;
      void getPlayback().then((status) => {
        if (
          !cancelled &&
          playbackActionRef.current === null &&
          playbackEpochRef.current === epoch
        ) {
          setPlayback(status);
        }
      }).catch(() => undefined).finally(() => {
        inFlight = false;
      });
    };
    poll();
    const timer = window.setInterval(poll, PLAYBACK_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [runtime.backend, savedMotion]);

  const gotoFrame = useCallback(async (frameId: string) => {
    const frame = documentRef.current.frames.find((candidate) => candidate.id === frameId);
    if (!frame || draftMotionDisabledReason(
      runtime,
      documentRef.current,
      realSession,
      'real_joint_motion',
    )) return;
    const epoch = studioCommandEpochRef.current + 1;
    studioCommandEpochRef.current = epoch;
    setAction('goto');
    onError(null);
    let expectedDraftRevision: number | null = null;
    const operation = (async () => {
      const persisted = await persistWorkspace();
      expectedDraftRevision = persisted.revision;
      if (studioCommandEpochRef.current !== epoch) return;
      const submission = await gotoMotionDraftKeyframe(persisted.id, frameId, {
        expected_revision: persisted.revision,
        speed_scale: 0.25,
        idempotency_key: id(),
        duration_s: 1,
      });
      if (studioCommandEpochRef.current !== epoch) return;
      setStudioCommand(submission.command);
      setStudioCommandPollGeneration(epoch);
      onMessage(`已通过审核后的运动入口提交“${frame.label}”。`);
    })();
    studioGotoRequestRef.current = operation;
    try {
      await operation;
    } catch (caught) {
      if (
        studioCommandEpochRef.current === epoch &&
        !onDraftConflict(caught, expectedDraftRevision)
      ) onError(message(caught));
    } finally {
      if (studioGotoRequestRef.current === operation) studioGotoRequestRef.current = null;
      setAction((currentAction) => currentAction === 'goto' ? null : currentAction);
    }
  }, [onDraftConflict, onError, onMessage, persistWorkspace, realSession, runtime]);

  const studioCommandId = studioCommand?.command_id ?? null;
  const studioCommandIsActive = Boolean(
    studioCommand && ACTIVE_STUDIO_COMMAND_STATES.has(studioCommand.state),
  );
  useEffect(() => {
    if (!studioCommandId || !studioCommandIsActive) return;
    const epoch = studioCommandEpochRef.current;
    let cancelled = false;
    let inFlight = false;
    const poll = () => {
      if (inFlight) return;
      inFlight = true;
      void getMotionCommand(studioCommandId).then((status) => {
        if (!cancelled && studioCommandEpochRef.current === epoch) setStudioCommand(status);
      }).catch(() => undefined).finally(() => {
        inFlight = false;
      });
    };
    poll();
    const timer = window.setInterval(poll, PLAYBACK_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [studioCommandId, studioCommandIsActive, studioCommandPollGeneration]);

  const stop = useCallback(async () => {
    const playbackState = playback?.state ?? 'IDLE';
    const stopPlaybackSession =
      actionRef.current === 'prepare-playback' ||
      playbackState === 'PREFLIGHTING' ||
      playbackState === 'READY' ||
      playbackState === 'PLAYING' ||
      playbackState === 'PAUSED';
    const stopStudioCommand =
      actionRef.current === 'goto' ||
      Boolean(studioCommandRef.current && ACTIVE_STUDIO_COMMAND_STATES.has(studioCommandRef.current.state));
    if (!stopPlaybackSession && !stopStudioCommand) return;

    const playbackEpoch = playbackEpochRef.current + 1;
    playbackEpochRef.current = playbackEpoch;
    const commandEpoch = studioCommandEpochRef.current + 1;
    studioCommandEpochRef.current = commandEpoch;
    setStudioCommandPollGeneration(commandEpoch);
    const pendingGoto = studioGotoRequestRef.current;
    playbackActionRef.current = 'stop';
    setAction('stop');
    onError(null);
    if (stopStudioCommand) {
      setStudioCommand((current) => current ? { ...current, state: 'STOPPING' } : current);
    }
    setPlaybackPreflight(null);
    let firstError: unknown = null;
    try {
      if (stopStudioCommand) {
        let commandStopError: unknown = null;
        try {
          await stopMotion();
        } catch (caught) {
          commandStopError = caught;
        }
        if (pendingGoto) {
          try {
            await pendingGoto;
          } catch {
            // A failed submission cannot start motion; retry Stop because a
            // transport failure does not prove the server rejected it.
          }
          try {
            await stopMotion();
            commandStopError = null;
          } catch (caught) {
            commandStopError = caught;
          }
        }
        firstError = commandStopError;
      }
      if (stopPlaybackSession) {
        try {
          const status = await stopPlayback();
          if (playbackEpochRef.current === playbackEpoch) setPlayback(status);
        } catch (caught) {
          firstError ??= caught;
        }
      }
      if (firstError) throw firstError;
      onMessage(runtime.controlMode === 'REAL'
        ? '当前真机运动链路已接受优先停止请求。'
        : '当前仿真运动链路已接受优先停止请求。');
    } catch (caught) {
      if (
        playbackEpochRef.current === playbackEpoch &&
        studioCommandEpochRef.current === commandEpoch
      ) onError(message(caught));
    } finally {
      if (playbackActionRef.current === 'stop') {
        playbackActionRef.current = null;
        setAction((currentAction) => currentAction === 'stop' ? null : currentAction);
      }
    }
  }, [onError, onMessage, playback?.state, runtime.controlMode]);

  return {
    action,
    disabledReason: draftMotionDisabledReason(
      runtime,
      document,
      realSession,
      'real_joint_motion',
    ),
    playbackDisabledReason: draftMotionDisabledReason(
      runtime,
      document,
      realSession,
      'real_playback',
    ),
    gotoFrame,
    pause: () => playbackAction('pause', pausePlayback),
    play,
    playback,
    playbackPreflight,
    preparePlayback,
    resume: () => playbackAction('resume', resumePlayback),
    stop,
    studioCommand,
  };
}

export type StudioMotionSession = ReturnType<typeof useStudioMotionSession>;
