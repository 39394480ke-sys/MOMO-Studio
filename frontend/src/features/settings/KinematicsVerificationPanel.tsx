import { CircleAlert, Crosshair, Ruler } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';

import {
  addKinematicsVerificationMeasurement,
  commitKinematicsVerificationDraft,
  getKinematicsVerificationStatus,
  startKinematicsVerificationDraft,
} from '../../api/client';
import type {
  FieldAcceptanceProgress,
  KinematicsVerificationDraft,
  KinematicsVerificationStatus,
  TcpPose,
} from '../../api/types';
import { useRealSession } from '../../components/realSessionContext';
import { useRuntimeStatus } from '../../components/runtimeStatusContext';

interface MeasurementFields {
  label: string;
  frame: string;
  x: string;
  y: string;
  z: string;
  qx: string;
  qy: string;
  qz: string;
  qw: string;
}

const EMPTY_MEASUREMENT: MeasurementFields = {
  label: '',
  frame: 'base',
  x: '',
  y: '',
  z: '',
  qx: '0',
  qy: '0',
  qz: '0',
  qw: '1',
};

function message(error: unknown): string {
  return error instanceof Error ? error.message : 'Kinematics verification request failed.';
}

function numeric(value: string, label: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new TypeError(`${label} must be a finite number.`);
  return parsed;
}

function thresholds(position: string, orientation: string) {
  const maxPosition = numeric(position, 'Maximum position error');
  const maxOrientation = numeric(orientation, 'Maximum orientation error');
  if (maxPosition <= 0 || maxPosition > 25) {
    throw new RangeError('Maximum position error must be greater than 0 and at most 25 mm.');
  }
  if (maxOrientation <= 0 || maxOrientation > 15) {
    throw new RangeError('Maximum orientation error must be greater than 0 and at most 15°');
  }
  return {
    max_position_error_mm: maxPosition,
    max_orientation_error_deg: maxOrientation,
  };
}

function measuredTcp(fields: MeasurementFields): TcpPose {
  const frame = fields.frame.trim();
  if (!frame || frame.length > 128) {
    throw new TypeError('Measured TCP frame must contain 1–128 characters.');
  }
  const orientation = {
    x: numeric(fields.qx, 'Quaternion X'),
    y: numeric(fields.qy, 'Quaternion Y'),
    z: numeric(fields.qz, 'Quaternion Z'),
    w: numeric(fields.qw, 'Quaternion W'),
  };
  if (
    orientation.x ** 2 + orientation.y ** 2 + orientation.z ** 2 + orientation.w ** 2 <
    1e-24
  ) {
    throw new TypeError('Measured TCP quaternion must be non-zero.');
  }
  return {
    frame,
    position_mm: {
      x: numeric(fields.x, 'Measured TCP X'),
      y: numeric(fields.y, 'Measured TCP Y'),
      z: numeric(fields.z, 'Measured TCP Z'),
    },
    orientation_quaternion_xyzw: orientation,
  };
}

function tcpSummary(pose: TcpPose): string {
  const { x, y, z } = pose.position_mm;
  return `${pose.frame}: ${x.toFixed(2)}, ${y.toFixed(2)}, ${z.toFixed(2)} mm`;
}

function jointStateSummary(
  point: KinematicsVerificationDraft['points'][number],
): string {
  const positions = Object.entries(point.joint_state.positions).map(([jointId, value]) => {
    const unit = point.joint_state.units?.[jointId] ?? '';
    return `${jointId}: ${value} ${unit}`.trim();
  }).join(' · ');
  return `Sequence ${point.joint_state_sequence} · captured ${point.joint_state_captured_at} · ${positions}`;
}

export function KinematicsVerificationPanel({
  fieldProgress,
  onEvidenceChanged,
}: {
  fieldProgress: FieldAcceptanceProgress | null;
  onEvidenceChanged: () => Promise<unknown>;
}) {
  const runtime = useRuntimeStatus();
  const { summary, refresh: refreshSession } = useRealSession();
  const [status, setStatus] = useState<KinematicsVerificationStatus | null>(null);
  const [draft, setDraft] = useState<KinematicsVerificationDraft | null>(null);
  const [positionThreshold, setPositionThreshold] = useState('5');
  const [orientationThreshold, setOrientationThreshold] = useState('5');
  const [measurement, setMeasurement] = useState<MeasurementFields>(EMPTY_MEASUREMENT);
  const [pending, setPending] = useState<'draft' | 'measurement' | 'commit' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const sessionAuthorized = summary.session?.purpose === 'REAL_MOTION' &&
    summary.session.scopes.includes('REAL_JOINT_MOTION') &&
    summary.capabilityDetails.real_joint_motion.ready &&
    summary.capabilityDetails.real_joint_motion.authorized &&
    !summary.stale;
  const jointAcceptanceComplete = fieldProgress?.joint_motion_accepted === true;

  useEffect(() => {
    if (runtime.backend !== 'connected' || runtime.controlMode !== 'REAL' || runtime.stale) {
      setStatus(null);
      return undefined;
    }
    const controller = new AbortController();
    void getKinematicsVerificationStatus(controller.signal)
      .then((next) => {
        if (!controller.signal.aborted) setStatus(next);
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(message(caught));
      });
    return () => controller.abort();
  }, [runtime.backend, runtime.controlMode, runtime.stale]);

  useEffect(() => {
    if (draft && draft.operator_session_id !== summary.session?.session_id) {
      setDraft(null);
      setError('The Operator Session changed. Start a new measured-TCP draft.');
    }
  }, [draft, summary.session?.session_id]);

  const startDraft = async () => {
    if (!sessionAuthorized || !jointAcceptanceComplete) return;
    setPending('draft');
    setError(null);
    try {
      const next = await startKinematicsVerificationDraft(
        thresholds(positionThreshold, orientationThreshold),
      );
      if (next.operator_session_id !== summary.session?.session_id) {
        throw new Error('Backend returned a Kinematics draft for another Operator Session.');
      }
      setDraft(next);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setPending(null);
    }
  };

  const addMeasurement = async (event: FormEvent) => {
    event.preventDefault();
    if (!draft || !sessionAuthorized) return;
    const label = measurement.label.trim();
    if (!label || label.length > 128) {
      setError('Measurement label must contain 1–128 characters.');
      return;
    }
    setPending('measurement');
    setError(null);
    try {
      const next = await addKinematicsVerificationMeasurement(draft.draft_id, {
        label,
        measured_tcp: measuredTcp(measurement),
      });
      if (next.operator_session_id !== summary.session?.session_id) {
        throw new Error('Backend returned a measurement for another Operator Session.');
      }
      setDraft(next);
      setMeasurement(EMPTY_MEASUREMENT);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setPending(null);
    }
  };

  const commitDraft = async () => {
    if (!draft || draft.points.length < 3 || !sessionAuthorized) return;
    setPending('commit');
    setError(null);
    try {
      const evidence = await commitKinematicsVerificationDraft(draft.draft_id);
      setStatus({
        state: 'VALID',
        stale_fields: [],
        evidence_id: evidence.id,
        point_count: evidence.test_points.length,
      });
      setDraft(null);
      await Promise.all([onEvidenceChanged(), refreshSession()]);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setPending(null);
    }
  };

  const startAllowed = sessionAuthorized && jointAcceptanceComplete &&
    status !== null && status.state !== 'VALID';

  return (
    <section className="kinematics-verification" aria-labelledby="kinematics-verification-title">
      <header>
        <Crosshair aria-hidden="true" />
        <div>
          <p className="section-kicker">MEASURED FIELD EVIDENCE</p>
          <h4 id="kinematics-verification-title">Kinematics Verification</h4>
          <p>Compare backend-predicted TCP poses with independently measured TCP poses at three or more distinct joint states.</p>
        </div>
      </header>

      <dl className="kinematics-verification__status">
        <div><dt>Persisted evidence</dt><dd>{status?.state ?? 'Loading'}</dd></div>
        <div><dt>Persisted points</dt><dd>{status?.point_count ?? '—'}</dd></div>
        <div><dt>Draft points</dt><dd>{draft?.points.length ?? 0}</dd></div>
        <div><dt>Robot unit</dt><dd><code>{draft?.robot_unit_id ?? fieldProgress?.robot_unit_id ?? 'Required'}</code></dd></div>
      </dl>

      {status?.stale_fields.length ? (
        <div className="commissioning-motion__blocked" role="status">
          <CircleAlert aria-hidden="true" />
          <div>
            <strong>Existing Kinematics evidence is stale</strong>
            <ul>{status.stale_fields.map((field) => <li key={field}>{field}</li>)}</ul>
          </div>
        </div>
      ) : null}

      {!jointAcceptanceComplete && (
        <p className="real-inline-note">Accept persisted single-joint motion evidence before starting measured-TCP verification.</p>
      )}
      {!sessionAuthorized && (
        <div className="commissioning-motion__blocked" role="status">
          <CircleAlert aria-hidden="true" />
          <div>
            <strong>Measured-TCP writes require an active REAL_MOTION session with REAL_JOINT_MOTION authorization.</strong>
            <ul>
              {summary.capabilityDetails.real_joint_motion.blocked_reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
              {summary.capabilityDetails.real_joint_motion.required_evidence.map((item) => (
                <li key={item}>Required evidence: {item}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {!draft && (
        <div className="kinematics-verification__start">
          <label>
            Max position error (mm)
            <input
              max="25"
              min="0.001"
              onChange={(event) => setPositionThreshold(event.target.value)}
              step="0.1"
              type="number"
              value={positionThreshold}
            />
          </label>
          <label>
            Max orientation error (deg)
            <input
              max="15"
              min="0.001"
              onChange={(event) => setOrientationThreshold(event.target.value)}
              step="0.1"
              type="number"
              value={orientationThreshold}
            />
          </label>
          <button
            className="command-button"
            disabled={!startAllowed || pending !== null}
            onClick={() => void startDraft()}
            type="button"
          >
            <Ruler aria-hidden="true" /> {pending === 'draft' ? 'Starting draft…' : 'Start measured-TCP draft'}
          </button>
        </div>
      )}

      {draft && (
        <>
          <div className="kinematics-verification__draft-facts">
            <strong>Draft bound to current Operator Session</strong>
            <span>Checklist: {draft.verification_checklist_version}</span>
            <span>Software: <code>{draft.software_commit}</code></span>
            <span>Device: <code>{draft.device_fingerprint}</code></span>
            <span>Position threshold ≤ {draft.thresholds.max_position_error_mm} mm</span>
            <span>Orientation threshold ≤ {draft.thresholds.max_orientation_error_deg}°</span>
          </div>

          <form className="kinematics-measurement" onSubmit={(event) => void addMeasurement(event)}>
            <div className="kinematics-measurement__snapshot">
              <strong>Server-owned joint snapshot</strong>
              <p>The backend captures and validates a fresh hardware readback when this measurement is submitted. Browser state is never accepted as joint evidence.</p>
            </div>
            <label className="kinematics-measurement__wide">
              Measurement label
              <input
                maxLength={128}
                onChange={(event) => setMeasurement((current) => ({ ...current, label: event.target.value }))}
                placeholder="e.g. front-low gauge point"
                required
                value={measurement.label}
              />
            </label>
            <label>
              Frame
              <input
                maxLength={128}
                onChange={(event) => setMeasurement((current) => ({ ...current, frame: event.target.value }))}
                required
                value={measurement.frame}
              />
            </label>
            {(['x', 'y', 'z'] as const).map((axis) => (
              <label key={axis}>
                Measured {axis.toUpperCase()} (mm)
                <input
                  onChange={(event) => setMeasurement((current) => ({ ...current, [axis]: event.target.value }))}
                  required
                  step="any"
                  type="number"
                  value={measurement[axis]}
                />
              </label>
            ))}
            {(['qx', 'qy', 'qz', 'qw'] as const).map((axis) => (
              <label key={axis}>
                {axis.toUpperCase()}
                <input
                  onChange={(event) => setMeasurement((current) => ({ ...current, [axis]: event.target.value }))}
                  required
                  step="any"
                  type="number"
                  value={measurement[axis]}
                />
              </label>
            ))}
            <p className="kinematics-measurement__note">
              Enter independent physical measurements. The backend binds its own fresh joint snapshot; MOMO Studio does not use a model label as evidence.
            </p>
            <button
              className="command-button"
              disabled={!sessionAuthorized || pending !== null}
              type="submit"
            >
              {pending === 'measurement' ? 'Computing backend residuals…' : 'Add measured point'}
            </button>
          </form>

          {draft.points.length > 0 && (
            <div className="table-scroll">
              <table className="diagnostics-table">
                <thead>
                  <tr>
                    <th>Label</th>
                    <th>Backend joint snapshot</th>
                    <th>Predicted TCP</th>
                    <th>Measured TCP</th>
                    <th>Position error</th>
                    <th>Orientation error</th>
                  </tr>
                </thead>
                <tbody>
                  {draft.points.map((point) => (
                    <tr key={point.point_id}>
                      <td>{point.label}</td>
                      <td title={`Operator Session ${point.snapshot_session_id}`}>
                        {jointStateSummary(point)}
                      </td>
                      <td>{tcpSummary(point.predicted_tcp)}</td>
                      <td>{tcpSummary(point.measured_tcp)}</td>
                      <td>{point.position_error_mm.toFixed(3)} mm</td>
                      <td>{point.orientation_error_deg.toFixed(3)}°</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <button
            className="command-button command-button--danger-solid"
            disabled={draft.points.length < 3 || !sessionAuthorized || pending !== null}
            onClick={() => void commitDraft()}
            type="button"
          >
            {pending === 'commit' ? 'Committing measured evidence…' : 'Commit measured Kinematics evidence'}
          </button>
          {draft.points.length < 3 && (
            <p className="real-inline-note">At least three backend-evaluated points are required. The backend also requires distinct joint states and passing residuals.</p>
          )}
        </>
      )}

      {error && <p className="real-inline-error" role="alert">{error}</p>}
    </section>
  );
}
