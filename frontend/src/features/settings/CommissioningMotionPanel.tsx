import { CircleAlert, MoveHorizontal, ShieldAlert, Square } from 'lucide-react';
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ButtonHTMLAttributes,
} from 'react';

import {
  armCommissioningJoint,
  acceptFieldJointMotion,
  completeFieldPreMotionChecks,
  getCommissioningMotionStatus,
  getFieldAcceptanceProgress,
  heartbeatCommissioningMotionTest,
  startCommissioningJointTest,
  startCommissioningMotionSession,
  stopCommissioningMotionTest,
} from '../../api/client';
import type {
  CommissioningMotionStatus,
  CommissioningTestEvidence,
  DeviceDiagnostics,
  FieldAcceptanceProgress,
  ProfileJointDefinition,
} from '../../api/types';
import { useRealSession } from '../../components/realSessionContext';
import { useRuntimeStatus } from '../../components/runtimeStatusContext';
import { KinematicsVerificationPanel } from './KinematicsVerificationPanel';

const HEARTBEAT_INTERVAL_MS = 150;
const STATUS_POLL_INTERVAL_MS = 1_000;
const PROGRESS_POLL_INTERVAL_MS = 2_000;

interface ActiveHold {
  epoch: number;
  jointId: string;
  direction: -1 | 1;
  heartbeatTimer: number | null;
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : 'Commissioning Motion Test request failed.';
}

function requestId(): string {
  return globalThis.crypto?.randomUUID?.() ??
    `commissioning-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function requestedValues(unit: 'mm' | 'deg') {
  return unit === 'mm'
    ? { delta: 0.5, speed: 0.5, acceleration: 1, hardDelta: 1, hardSpeed: 1 }
    : { delta: 1, speed: 1, acceleration: 2, hardDelta: 2, hardSpeed: 2 };
}

function directionResult(
  evidence: CommissioningTestEvidence[],
  direction: 'POSITIVE' | 'NEGATIVE',
): CommissioningTestEvidence | null {
  return [...evidence].reverse().find((item) => item.direction_expected === direction) ?? null;
}

export function CommissioningMotionPanel({
  diagnostics,
}: {
  diagnostics: DeviceDiagnostics | null;
}) {
  const runtime = useRuntimeStatus();
  const { summary, refresh: refreshSession } = useRealSession();
  const [status, setStatus] = useState<CommissioningMotionStatus | null>(null);
  const [progress, setProgress] = useState<FieldAcceptanceProgress | null>(null);
  const [evidenceByJoint, setEvidenceByJoint] = useState<
    Record<string, CommissioningTestEvidence[]>
  >({});
  const [hold, setHold] = useState<Pick<ActiveHold, 'jointId' | 'direction'> | null>(null);
  const [pending, setPending] = useState<
    'bind' | 'stop' | 'pre-motion' | 'accept-joints' | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  const epoch = useRef(0);
  const activeHold = useRef<ActiveHold | null>(null);
  const stopping = useRef(false);

  const sessionAuthorized = summary.session?.purpose === 'COMMISSIONING_MOTION_TEST' &&
    summary.capabilityDetails.commissioning_motion_test.ready &&
    summary.capabilityDetails.commissioning_motion_test.authorized;
  const readOnlyAuthorized = summary.session?.purpose === 'COMMISSIONING_READ_ONLY' &&
    summary.capabilityDetails.commissioning_read_only.ready &&
    summary.capabilityDetails.commissioning_read_only.authorized;
  const capability = summary.capabilityDetails.commissioning_motion_test;
  const diagnosticByJoint = useMemo(() => new Map(
    diagnostics?.records.map((record) => [record.joint_id, record]) ?? [],
  ), [diagnostics]);
  const joints = useMemo(() => {
    const profile = runtime.profile?.profile;
    if (!profile) return [];
    const definitions = new Map<string, ProfileJointDefinition>(
      profile.joint_definitions.map((definition) => [definition.joint_id, definition]),
    );
    return profile.enabled_joints.flatMap((jointId) => {
      const definition = definitions.get(jointId);
      return definition ? [{ jointId, unit: definition.domain_unit }] : [];
    });
  }, [runtime.profile]);
  const progressByJoint = useMemo(() => new Map(
    progress?.joints.map((joint) => [joint.joint_id, joint]) ?? [],
  ), [progress]);

  const refreshProgress = useCallback(async (signal?: AbortSignal) => {
    const next = await getFieldAcceptanceProgress(signal);
    if (!signal?.aborted && mounted.current) setProgress(next);
    return next;
  }, []);

  const clearHold = useCallback(() => {
    const active = activeHold.current;
    if (active?.heartbeatTimer !== null && active?.heartbeatTimer !== undefined) {
      window.clearInterval(active.heartbeatTimer);
    }
    activeHold.current = null;
    setHold(null);
  }, []);

  const requestStop = useCallback(async (reason: string) => {
    if (stopping.current) return;
    stopping.current = true;
    epoch.current += 1;
    clearHold();
    try {
      const next = await stopCommissioningMotionTest(reason);
      if (mounted.current) setStatus(next);
    } catch (caught) {
      if (mounted.current) setError(message(caught));
    } finally {
      stopping.current = false;
    }
  }, [clearHold]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (activeHold.current) void requestStop('ROUTE_CHANGE');
      clearHold();
    };
  }, [clearHold, requestStop]);

  useEffect(() => {
    if (runtime.backend !== 'connected' || runtime.controlMode !== 'REAL' || runtime.stale) {
      setProgress(null);
      return undefined;
    }
    const controller = new AbortController();
    let inFlight = false;
    const poll = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        await refreshProgress(controller.signal);
      } catch (caught) {
        if (!controller.signal.aborted && mounted.current) setError(message(caught));
      } finally {
        inFlight = false;
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), PROGRESS_POLL_INTERVAL_MS);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [refreshProgress, runtime.backend, runtime.controlMode, runtime.stale]);

  useEffect(() => {
    if (!sessionAuthorized) {
      if (activeHold.current) void requestStop('SESSION_UNAVAILABLE');
      setStatus(null);
      return undefined;
    }
    const controller = new AbortController();
    let inFlight = false;
    const refresh = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const next = await getCommissioningMotionStatus(controller.signal);
        if (!controller.signal.aborted && mounted.current) setStatus(next);
      } catch (caught) {
        if (!controller.signal.aborted && mounted.current) setError(message(caught));
      } finally {
        inFlight = false;
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), STATUS_POLL_INTERVAL_MS);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [requestStop, sessionAuthorized]);

  useEffect(() => {
    const stopFor = (reason: string) => {
      if (activeHold.current) void requestStop(reason);
    };
    const onBlur = () => stopFor('WINDOW_BLUR');
    const onOffline = () => stopFor('NETWORK_OFFLINE');
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') stopFor('DOCUMENT_HIDDEN');
    };
    window.addEventListener('blur', onBlur);
    window.addEventListener('offline', onOffline);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.removeEventListener('blur', onBlur);
      window.removeEventListener('offline', onOffline);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [requestStop]);

  const bindSession = async () => {
    setPending('bind');
    setError(null);
    try {
      setStatus(await startCommissioningMotionSession());
    } catch (caught) {
      setError(message(caught));
    } finally {
      setPending(null);
    }
  };

  const recordPreMotionChecks = async () => {
    if (!progress || !readOnlyAuthorized || !summary.readiness?.connected) return;
    setPending('pre-motion');
    setError(null);
    try {
      setProgress(await completeFieldPreMotionChecks(progress.checklist_version));
      await refreshSession();
    } catch (caught) {
      setError(message(caught));
    } finally {
      setPending(null);
    }
  };

  const acceptPersistedJointEvidence = async () => {
    if (!progress || !sessionAuthorized || !progress.ready_to_accept_joint_motion) return;
    setPending('accept-joints');
    setError(null);
    try {
      setProgress(await acceptFieldJointMotion(progress.checklist_version));
      await refreshSession();
    } catch (caught) {
      setError(message(caught));
    } finally {
      setPending(null);
    }
  };

  const beginHold = useCallback(async (
    jointId: string,
    unit: 'mm' | 'deg',
    direction: -1 | 1,
  ) => {
    if (activeHold.current || !sessionAuthorized || !progress?.pre_motion_checks_complete ||
      !status || !['AUTHORIZED', 'COMPLETED', 'FAILED'].includes(status.state)) {
      return;
    }
    const holdEpoch = ++epoch.current;
    const active: ActiveHold = { epoch: holdEpoch, jointId, direction, heartbeatTimer: null };
    activeHold.current = active;
    setHold({ jointId, direction });
    setError(null);
    try {
      const armed = await armCommissioningJoint(jointId);
      if (epoch.current !== holdEpoch || activeHold.current?.epoch !== holdEpoch) {
        await requestStop('RELEASED_BEFORE_ARM');
        return;
      }
      setStatus(armed);
      active.heartbeatTimer = window.setInterval(() => {
        void heartbeatCommissioningMotionTest().then((next) => {
          if (mounted.current && activeHold.current?.epoch === holdEpoch) setStatus(next);
        }).catch((caught) => {
          if (mounted.current) setError(`Deadman heartbeat failed: ${message(caught)}`);
          void requestStop('HEARTBEAT_FAILED');
        });
      }, HEARTBEAT_INTERVAL_MS);
      const requested = requestedValues(unit);
      const evidence = await startCommissioningJointTest(jointId, {
        signed_delta: direction * requested.delta,
        requested_speed: requested.speed,
        requested_acceleration: requested.acceleration,
        command_duration_s: 1,
        request_id: requestId(),
      });
      if (!mounted.current || epoch.current !== holdEpoch) return;
      setEvidenceByJoint((current) => ({
        ...current,
        [jointId]: [...(current[jointId] ?? []), evidence],
      }));
      await refreshProgress();
      setStatus(await getCommissioningMotionStatus());
    } catch (caught) {
      if (mounted.current && epoch.current === holdEpoch) {
        setError(message(caught));
        void requestStop('TEST_REQUEST_FAILED');
      }
    } finally {
      if (epoch.current === holdEpoch) clearHold();
    }
  }, [clearHold, progress?.pre_motion_checks_complete, refreshProgress, requestStop, sessionAuthorized, status]);

  const holdHandlers = (
    jointId: string,
    unit: 'mm' | 'deg',
    direction: -1 | 1,
  ): ButtonHTMLAttributes<HTMLButtonElement> => ({
    onPointerDown: (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      event.currentTarget.setPointerCapture?.(event.pointerId);
      void beginHold(jointId, unit, direction);
    },
    onPointerUp: () => void requestStop('POINTER_RELEASE'),
    onPointerCancel: () => void requestStop('POINTER_CANCEL'),
    onPointerLeave: () => void requestStop('POINTER_LEAVE'),
    onKeyDown: (event) => {
      if ((event.key === ' ' || event.key === 'Enter') && !event.repeat) {
        event.preventDefault();
        void beginHold(jointId, unit, direction);
      }
    },
    onKeyUp: (event) => {
      if (event.key === ' ' || event.key === 'Enter') void requestStop('KEY_RELEASE');
    },
  });

  const testReady = sessionAuthorized && progress?.pre_motion_checks_complete === true &&
    status !== null &&
    ['AUTHORIZED', 'COMPLETED', 'FAILED'].includes(status.state) && pending === null;
  const kinematicsReasons = summary.capabilityDetails.real_cartesian_motion;
  const kinematicsEvidenceRecorded = progress?.joint_motion_accepted === true &&
    progress.state !== 'KINEMATICS_VERIFICATION_PENDING';

  return (
    <section className="commissioning-motion" aria-labelledby="commissioning-motion-title">
      <div className="commissioning-motion__warning">
        <ShieldAlert aria-hidden="true" />
        <div>
          <p className="section-kicker">COMMISSIONING</p>
          <h3 id="commissioning-motion-title">COMMISSIONING MOTION TEST</h3>
          <strong>REAL HARDWARE · LOW-SPEED SINGLE-JOINT TEST ONLY</strong>
          <p>This is not normal robot operation. Physical E-stop must be ready.</p>
        </div>
      </div>

      <div className="commissioning-progress" aria-label="Commissioning progress">
        <h4>Commissioning progress</h4>
        <ol>
          <li><span>Device Identity</span><strong>{progress?.robot_unit_id ? '✓' : 'Pending'}</strong></li>
          <li><span>Read-only Diagnostics</span><strong>{summary.capabilityDetails.commissioning_read_only.ready ? '✓' : 'Pending'}</strong></li>
          <li><span>Calibration</span><strong>{summary.readiness?.calibration_configured ? '✓' : 'Pending'}</strong></li>
          <li><span>Pre-motion Checks</span><strong>{progress?.pre_motion_checks_complete ? '✓' : 'Pending'}</strong></li>
          <li>
            <span>Joint Motion Tests</span>
            <strong>{progress ? `${progress.completed_joint_directions} / ${progress.required_joint_directions}` : '—'}</strong>
          </li>
          <li><span>Joint Motion Acceptance</span><strong>{progress?.joint_motion_accepted ? '✓' : 'Pending'}</strong></li>
          <li><span>Kinematics Verification</span><strong>{kinematicsEvidenceRecorded ? 'Evidence recorded' : 'Pending'}</strong></li>
          <li><span>Cartesian Acceptance</span><strong>{progress?.valid_capabilities.includes('CARTESIAN') ? '✓' : 'Pending'}</strong></li>
          <li><span>Playback Acceptance</span><strong>{progress?.valid_capabilities.includes('PLAYBACK') ? '✓' : 'Pending'}</strong></li>
          <li><span>Vision Follow Acceptance</span><strong>{progress?.valid_capabilities.includes('VISION_FOLLOW') ? '✓' : 'Pending'}</strong></li>
        </ol>
      </div>

      <dl className="commissioning-motion__facts">
        <div><dt>Robot unit ID</dt><dd><code>{progress?.robot_unit_id ?? summary.readiness?.confirmation.robot_unit_id ?? 'Required'}</code></dd></div>
        <div><dt>Acceptance state</dt><dd>{progress?.state ?? 'Loading'}</dd></div>
        <div><dt>Checklist</dt><dd>{progress?.checklist_version ?? '—'}</dd></div>
        <div><dt>Session state</dt><dd>{status?.state ?? (sessionAuthorized ? 'Not bound' : 'Not authorized')}</dd></div>
        <div><dt>Commands</dt><dd>{status?.command_count ?? 0}</dd></div>
        <div><dt>Physical stop verification</dt><dd>{progress?.physical_stop_verification ?? status?.physical_stop_verification ?? 'PENDING'}</dd></div>
      </dl>

      <div className="commissioning-acceptance-actions" aria-label="Persisted acceptance actions">
        <div>
          <strong>Pre-motion checklist</strong>
          <p>Records a fresh backend diagnostics snapshot. A connected read-only commissioning session is required.</p>
          <button
            className="command-button"
            disabled={
              pending !== null || !progress || progress.pre_motion_checks_complete ||
              !readOnlyAuthorized || !summary.readiness?.connected
            }
            onClick={() => void recordPreMotionChecks()}
            type="button"
          >
            {pending === 'pre-motion' ? 'Recording pre-motion checks…' : 'Record pre-motion checks'}
          </button>
        </div>
        <div>
          <strong>Persisted joint evidence</strong>
          <p>Accepts only the backend-selected positive and negative evidence for every enabled joint.</p>
          <button
            className="command-button"
            disabled={
              pending !== null || !progress?.ready_to_accept_joint_motion ||
              !sessionAuthorized
            }
            onClick={() => void acceptPersistedJointEvidence()}
            type="button"
          >
            {pending === 'accept-joints' ? 'Accepting joint evidence…' : 'Accept persisted joint evidence'}
          </button>
        </div>
      </div>

      {!sessionAuthorized && (
        <div className="commissioning-motion__blocked" role="status">
          <CircleAlert aria-hidden="true" />
          <div>
            <strong>Commissioning Motion Test is blocked</strong>
            <ul>
              {capability.blocked_reasons.map((reason) => <li key={reason}>{reason}</li>)}
              {capability.required_evidence.map((item) => (
                <li key={item}>Required evidence: {item}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {sessionAuthorized && !status?.session_id && (
        <button
          className="command-button command-button--danger-solid"
          disabled={pending !== null}
          onClick={() => void bindSession()}
          type="button"
        >
          {pending === 'bind' ? 'Binding watchdog…' : 'Bind authorized test session'}
        </button>
      )}

      <div className="commissioning-joints">
        {joints.map(({ jointId, unit }) => {
          const record = diagnosticByJoint.get(jointId);
          const requested = requestedValues(unit);
          const records = evidenceByJoint[jointId] ?? [];
          const latestNegative = directionResult(records, 'NEGATIVE');
          const latestPositive = directionResult(records, 'POSITIVE');
          const persisted = progressByJoint.get(jointId);
          return (
            <article className="commissioning-joint" key={jointId}>
              <header>
                <div><strong>{jointId.toUpperCase()}</strong><span>{unit}</span></div>
                <dl>
                  <div><dt>Current</dt><dd>{record?.logical_value ?? '—'} {unit}</dd></div>
                  <div><dt>Raw</dt><dd>{record?.present_raw ?? '—'}</dd></div>
                </dl>
              </header>
              <p>
                Delta request {requested.delta} {unit} · hard cap ≤ {requested.hardDelta} {unit}
                <br />Speed request {requested.speed} {unit}/s · hard cap ≤ {requested.hardSpeed} {unit}/s
              </p>
              <div className="commissioning-joint__holds">
                {([-1, 1] as const).map((direction) => {
                  const active = hold?.jointId === jointId && hold.direction === direction;
                  return (
                    <button
                      {...holdHandlers(jointId, unit, direction)}
                      aria-label={`Hold ${jointId.toUpperCase()} ${direction < 0 ? 'negative' : 'positive'} commissioning test`}
                      aria-pressed={active}
                      className={`command-button commissioning-hold${active ? ' commissioning-hold--active' : ''}`}
                      disabled={!testReady && !active}
                      key={direction}
                      type="button"
                    >
                      <MoveHorizontal aria-hidden="true" /> Hold {direction < 0 ? '−' : '+'}
                    </button>
                  );
                })}
              </div>
              <dl className="commissioning-joint__results">
                <div>
                  <dt>Negative direction</dt>
                  <dd>{persisted?.negative_evidence_id ? 'Recorded' : 'Pending'}</dd>
                </div>
                <div>
                  <dt>Positive direction</dt>
                  <dd>{persisted?.positive_evidence_id ? 'Recorded' : 'Pending'}</dd>
                </div>
                <div><dt>Backend pair</dt><dd>{persisted?.complete ? 'Complete' : 'Incomplete'}</dd></div>
                <div><dt>Latest readback</dt><dd>{[latestNegative, latestPositive].filter(Boolean).at(-1)?.measured_or_observed_result ?? 'See persisted evidence'}</dd></div>
                <div><dt>Latest divergence</dt><dd>{[latestNegative, latestPositive].filter(Boolean).at(-1)?.divergence ?? '—'}</dd></div>
              </dl>
            </article>
          );
        })}
      </div>

      <div className="commissioning-stop">
        <button
          className="command-button command-button--danger-solid"
          disabled={!sessionAuthorized || pending === 'stop'}
          onClick={() => {
            setPending('stop');
            void requestStop('OPERATOR_STOP_TEST').finally(() => setPending(null));
          }}
          type="button"
        >
          <Square aria-hidden="true" /> STOP TEST
        </button>
        <div>
          <strong>Physical E-stop must remain reachable.</strong>
          <span>Software Stop physical behavior: NOT YET FIELD VERIFIED</span>
          <span>Fake-bus software paths never prove physical stopping behavior.</span>
        </div>
      </div>

      <div className="commissioning-kinematics">
        <strong>Kinematics Verification requires measured TCP evidence</strong>
        <p>Tracked model labels cannot verify Kinematics. Only measured field points committed by the backend count.</p>
        <ul>
          {kinematicsReasons.blocked_reasons.map((reason) => <li key={reason}>{reason}</li>)}
          {kinematicsReasons.required_evidence.map((item) => <li key={item}>Required evidence: {item}</li>)}
        </ul>
      </div>

      <KinematicsVerificationPanel
        fieldProgress={progress}
        onEvidenceChanged={refreshProgress}
      />

      {error && <p className="real-inline-error" role="alert">{error}</p>}
      {status?.failure_reason && <p className="real-inline-error">{status.failure_reason}</p>}
    </section>
  );
}
