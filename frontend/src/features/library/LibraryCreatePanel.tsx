import { useMemo, useState, type FormEvent } from 'react';
import { Camera, Plus } from 'lucide-react';

import type {
  CapturePoseRequest,
  MotionMode,
  PoseSummary,
} from '../../api/types';
import { parseTags, validateEntityTags } from './libraryFormat';

export interface MotionCreationDraft {
  name: string;
  description: string;
  tags: string[];
  start_pose_id: string;
  start_pose_revision: number;
  end_pose_id: string;
  end_pose_revision: number;
  duration_s: number;
  motion_mode: MotionMode;
}

interface PoseCaptureFormProps {
  busy: boolean;
  disabled: boolean;
  robotLabel: string;
  onCapture: (request: CapturePoseRequest) => Promise<boolean>;
}

export function PoseCaptureForm({
  busy,
  disabled,
  robotLabel,
  onCapture,
}: PoseCaptureFormProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [tags, setTags] = useState('');
  const [validation, setValidation] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = name.trim();
    if (!normalizedName) {
      setValidation('Name is required before capturing a Pose.');
      return;
    }
    const normalizedTags = parseTags(tags);
    const tagError = validateEntityTags(normalizedTags);
    if (tagError) {
      setValidation(tagError);
      return;
    }
    setValidation(null);
    const created = await onCapture({
      name: normalizedName,
      description: description.trim(),
      tags: normalizedTags,
    });
    if (created) {
      setName('');
      setDescription('');
      setTags('');
    }
  }

  return (
    <section className="library-create-panel" aria-labelledby="capture-pose-heading">
      <header>
        <div>
          <p className="section-kicker">Current state</p>
          <h2 id="capture-pose-heading">Capture Pose</h2>
        </div>
        <span>{robotLabel}</span>
      </header>
      <p>
        Capture one coherent backend-owned joint/TCP snapshot from the active robot. Capture does not command motion.
      </p>
      <form className="entity-form" onSubmit={submit}>
        <label>
          <span>Name</span>
          <input
            disabled={disabled || busy}
            maxLength={200}
            onChange={(event) => setName(event.target.value)}
            placeholder="Inspection pose"
            value={name}
          />
        </label>
        <label>
          <span>Description</span>
          <textarea
            disabled={disabled || busy}
            maxLength={5000}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="What this snapshot is for"
            rows={2}
            value={description}
          />
        </label>
        <label>
          <span>Tags · comma separated</span>
          <input
            disabled={disabled || busy}
            maxLength={2079}
            onChange={(event) => setTags(event.target.value)}
            placeholder="demo, reach"
            value={tags}
          />
        </label>
        {validation ? <p className="form-validation" role="alert">{validation}</p> : null}
        <button
          className="command-button command-button--primary"
          disabled={disabled || busy}
          type="submit"
        >
          <Camera aria-hidden="true" />
          {busy ? 'Capturing…' : 'Capture current pose'}
        </button>
      </form>
    </section>
  );
}

interface MotionCreateFormProps {
  busy: boolean;
  disabled: boolean;
  poses: PoseSummary[];
  poseTotal: number;
  onCreate: (request: MotionCreationDraft) => Promise<boolean>;
}

export function MotionCreateForm({
  busy,
  disabled,
  poses,
  poseTotal,
  onCreate,
}: MotionCreateFormProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [tags, setTags] = useState('');
  const [startId, setStartId] = useState('');
  const [endId, setEndId] = useState('');
  const [duration, setDuration] = useState('2');
  const [motionMode, setMotionMode] = useState<MotionMode>('JOINT');
  const [validation, setValidation] = useState<string | null>(null);
  const poseById = useMemo(() => new Map(poses.map((pose) => [pose.id, pose])), [poses]);
  const startPose = poseById.get(startId);
  const endOptions = startPose
    ? poses.filter((pose) => pose.robot_variant === startPose.robot_variant)
    : poses;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = name.trim();
    const start = poseById.get(startId);
    const end = poseById.get(endId);
    const durationS = Number(duration);
    if (!normalizedName) {
      setValidation('Name is required before creating a Motion.');
      return;
    }
    if (!start || !end) {
      setValidation('Choose a start Pose and an end Pose.');
      return;
    }
    if (start.id === end.id) {
      setValidation('Start and end must use distinct Pose identities.');
      return;
    }
    if (start.robot_variant !== end.robot_variant) {
      setValidation('Both snapshots must use the same robot variant.');
      return;
    }
    if (!Number.isFinite(durationS) || durationS < 0.1 || durationS > 60) {
      setValidation('Transition duration must be between 0.1 and 60 seconds.');
      return;
    }

    const normalizedTags = parseTags(tags);
    const tagError = validateEntityTags(normalizedTags);
    if (tagError) {
      setValidation(tagError);
      return;
    }
    setValidation(null);
    const created = await onCreate({
      name: normalizedName,
      description: description.trim(),
      tags: normalizedTags,
      start_pose_id: start.id,
      start_pose_revision: start.revision,
      end_pose_id: end.id,
      end_pose_revision: end.revision,
      duration_s: durationS,
      motion_mode: motionMode,
    });
    if (created) {
      setName('');
      setDescription('');
      setTags('');
      setStartId('');
      setEndId('');
      setDuration('2');
      setMotionMode('JOINT');
    }
  }

  const unavailable = poses.length < 2;

  return (
    <section className="library-create-panel" aria-labelledby="create-motion-heading">
      <header>
        <div>
          <p className="section-kicker">Embedded snapshots</p>
          <h2 id="create-motion-heading">Create Motion</h2>
        </div>
        <span>{poseTotal} Pose{poseTotal === 1 ? '' : 's'} available</span>
      </header>
      <p>
        Build a valid two-keyframe Motion. Each selected snapshot is embedded; its source ID is provenance only.
      </p>
      {poseTotal > poses.length ? (
        <p className="library-form-note">Showing the first {poses.length} Pose records from the bounded source list.</p>
      ) : null}
      <form className="entity-form entity-form--motion" onSubmit={submit}>
        <label>
          <span>Name</span>
          <input
            disabled={disabled || busy || unavailable}
            maxLength={200}
            onChange={(event) => setName(event.target.value)}
            placeholder="Pick and place"
            value={name}
          />
        </label>
        <label>
          <span>Description</span>
          <textarea
            disabled={disabled || busy || unavailable}
            maxLength={5000}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Describe the stored sequence"
            rows={2}
            value={description}
          />
        </label>
        <label>
          <span>Start Pose</span>
          <select
            disabled={disabled || busy || unavailable}
            onChange={(event) => {
              const nextStart = event.target.value;
              setStartId(nextStart);
              const selected = poseById.get(nextStart);
              const currentEnd = poseById.get(endId);
              if (selected && currentEnd?.robot_variant !== selected.robot_variant) {
                setEndId('');
              }
            }}
            value={startId}
          >
            <option value="">Choose a Pose</option>
            {poses.map((pose) => (
              <option key={pose.id} value={pose.id}>
                {pose.name} · {pose.robot_variant} · {pose.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>End Pose</span>
          <select
            disabled={disabled || busy || unavailable || !startPose}
            onChange={(event) => setEndId(event.target.value)}
            value={endId}
          >
            <option value="">Choose a compatible Pose</option>
            {endOptions.map((pose) => (
              <option key={pose.id} value={pose.id}>
                {pose.name} · {pose.robot_variant} · {pose.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Transition type</span>
          <select
            disabled={disabled || busy || unavailable}
            onChange={(event) => setMotionMode(event.target.value as MotionMode)}
            value={motionMode}
          >
            <option value="JOINT">Joint</option>
            <option value="CARTESIAN_LINEAR">Cartesian linear</option>
          </select>
        </label>
        <label>
          <span>Duration · seconds</span>
          <input
            disabled={disabled || busy || unavailable}
            inputMode="decimal"
            max="60"
            min="0.1"
            onChange={(event) => setDuration(event.target.value)}
            step="0.1"
            type="number"
            value={duration}
          />
        </label>
        <label>
          <span>Tags · comma separated</span>
          <input
            disabled={disabled || busy || unavailable}
            maxLength={2079}
            onChange={(event) => setTags(event.target.value)}
            placeholder="demo, sequence"
            value={tags}
          />
        </label>
        {unavailable ? (
          <p className="form-validation" role="status">Capture at least two Poses to create a Motion.</p>
        ) : null}
        {validation ? <p className="form-validation" role="alert">{validation}</p> : null}
        <button
          className="command-button command-button--primary"
          disabled={disabled || busy || unavailable}
          type="submit"
        >
          <Plus aria-hidden="true" />
          {busy ? 'Creating…' : 'Create motion'}
        </button>
      </form>
    </section>
  );
}
