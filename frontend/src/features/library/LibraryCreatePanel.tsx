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
      setValidation('捕获机位前必须填写名称。');
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
    <section className="library-create-panel" aria-labelledby="capture-pose-heading" id="capture-pose-panel">
      <header>
        <div>
          <p className="section-kicker">当前状态</p>
          <h2 id="capture-pose-heading">捕获机位</h2>
        </div>
        <span>{robotLabel}</span>
      </header>
      <p>
        从当前机械臂捕获一份由后端统一读取的关节/TCP 快照；捕获操作不会发出运动命令。
      </p>
      <form className="entity-form" onSubmit={submit}>
        <label>
          <span>名称</span>
          <input
            disabled={disabled || busy}
            maxLength={200}
            onChange={(event) => setName(event.target.value)}
            placeholder="例如：产品正面"
            value={name}
          />
        </label>
        <label>
          <span>说明</span>
          <textarea
            disabled={disabled || busy}
            maxLength={5000}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="说明这个机位的用途"
            rows={2}
            value={description}
          />
        </label>
        <label>
          <span>标签 · 用逗号分隔</span>
          <input
            disabled={disabled || busy}
            maxLength={2079}
            onChange={(event) => setTags(event.target.value)}
            placeholder="产品, 正面"
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
          {busy ? '正在捕获…' : '捕获当前机位'}
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
      setValidation('创建运动前必须填写名称。');
      return;
    }
    if (!start || !end) {
      setValidation('请选择起始机位和结束机位。');
      return;
    }
    if (start.id === end.id) {
      setValidation('起始和结束必须使用两个不同的机位。');
      return;
    }
    if (start.robot_variant !== end.robot_variant) {
      setValidation('两个快照必须使用相同的机械臂型号。');
      return;
    }
    if (!Number.isFinite(durationS) || durationS < 0.1 || durationS > 60) {
      setValidation('过渡时长必须在 0.1 到 60 秒之间。');
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
    <section className="library-create-panel" aria-labelledby="create-motion-heading" id="create-motion-panel">
      <header>
        <div>
          <p className="section-kicker">内嵌快照</p>
          <h2 id="create-motion-heading">创建运动</h2>
        </div>
        <span>可用机位 {poseTotal} 个</span>
      </header>
      <p>
        创建一个包含两个关键帧的有效运动。所选快照会被内嵌，来源 ID 只用于追溯。
      </p>
      {poseTotal > poses.length ? (
        <p className="library-form-note">当前显示受限来源列表中的前 {poses.length} 个机位。</p>
      ) : null}
      <form className="entity-form entity-form--motion" onSubmit={submit}>
        <label>
          <span>名称</span>
          <input
            disabled={disabled || busy || unavailable}
            maxLength={200}
            onChange={(event) => setName(event.target.value)}
            placeholder="例如：正面推到侧面"
            value={name}
          />
        </label>
        <label>
          <span>说明</span>
          <textarea
            disabled={disabled || busy || unavailable}
            maxLength={5000}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="说明这段运动的用途"
            rows={2}
            value={description}
          />
        </label>
        <label>
          <span>起始机位</span>
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
            <option value="">选择一个机位</option>
            {poses.map((pose) => (
              <option key={pose.id} value={pose.id}>
                {pose.name} · {pose.robot_variant} · {pose.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>结束机位</span>
          <select
            disabled={disabled || busy || unavailable || !startPose}
            onChange={(event) => setEndId(event.target.value)}
            value={endId}
          >
            <option value="">选择兼容机位</option>
            {endOptions.map((pose) => (
              <option key={pose.id} value={pose.id}>
                {pose.name} · {pose.robot_variant} · {pose.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>过渡类型</span>
          <select
            disabled={disabled || busy || unavailable}
            onChange={(event) => setMotionMode(event.target.value as MotionMode)}
            value={motionMode}
          >
            <option value="JOINT">关节插值（JOINT）</option>
            <option value="CARTESIAN_LINEAR">笛卡尔直线（CARTESIAN LINEAR）</option>
          </select>
        </label>
        <label>
          <span>时长 · 秒</span>
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
          <span>标签 · 用逗号分隔</span>
          <input
            disabled={disabled || busy || unavailable}
            maxLength={2079}
            onChange={(event) => setTags(event.target.value)}
            placeholder="产品, 推镜头"
            value={tags}
          />
        </label>
        {unavailable ? (
          <p className="form-validation" role="status">至少捕获两个机位后才能创建运动。</p>
        ) : null}
        {validation ? <p className="form-validation" role="alert">{validation}</p> : null}
        <button
          className="command-button command-button--primary"
          disabled={disabled || busy || unavailable}
          type="submit"
        >
          <Plus aria-hidden="true" />
          {busy ? '正在创建…' : '创建运动'}
        </button>
      </form>
    </section>
  );
}
