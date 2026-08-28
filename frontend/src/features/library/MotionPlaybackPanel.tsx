import { CirclePause, CirclePlay, RotateCcw, ShieldCheck, Square } from 'lucide-react';

import type {
  MotionEntity,
  PlaybackStatus,
  TrajectoryPreflightReport,
  TrajectoryPreview as TrajectoryPreviewData,
} from '../../api/types';
import { playbackLocksLibrary } from './playbackState';
import { TrajectoryPreview } from './TrajectoryPreview';
import { zhStatus } from '../../i18n/zh';

const RATE_OPTIONS = [0.25, 0.5, 1, 1.5, 2] as const;

interface MotionPlaybackPanelProps {
  actionKey: string | null;
  disabledReason: string | null;
  error: string | null;
  loop: boolean;
  motion: MotionEntity;
  onLoopChange: (loop: boolean) => void;
  onDismissError: () => void;
  onPause: () => void;
  onPlay: () => void;
  onPreflight: () => void;
  onRateChange: (rate: number) => void;
  onResume: () => void;
  onStop: () => void;
  playback: PlaybackStatus | null;
  preflight: TrajectoryPreflightReport | null;
  preview: TrajectoryPreviewData | null;
  previewLoading: boolean;
  rate: number;
  runtimeMode: 'DRY RUN' | 'REAL';
  stopDisabled: boolean;
}

function seconds(value: number): string {
  return `${value.toFixed(2)} 秒`;
}

export function MotionPlaybackPanel({
  actionKey,
  disabledReason,
  error,
  loop,
  motion,
  onLoopChange,
  onDismissError,
  onPause,
  onPlay,
  onPreflight,
  onRateChange,
  onResume,
  onStop,
  playback,
  preflight,
  preview,
  previewLoading,
  rate,
  runtimeMode,
  stopDisabled,
}: MotionPlaybackPanelProps) {
  const actionBusy = actionKey !== null;
  const playbackBelongsHere = !playback?.motion_id || playback.motion_id === motion.id;
  const relevantPlayback = playbackBelongsHere ? playback : null;
  const foreignPlaybackActive = !playbackBelongsHere && playbackLocksLibrary(playback);
  const state = relevantPlayback?.state ?? 'IDLE';
  const sessionActive = playbackLocksLibrary(relevantPlayback);
  const hasPreparedTrajectory = Boolean(
    preflight?.passed &&
    preflight.digest &&
    preflight.motion_id === motion.id &&
    preflight.motion_revision === motion.revision,
  );
  const keyframeLabel = motion.keyframes.find(
    (keyframe) => keyframe.id === relevantPlayback?.current_keyframe_id,
  )?.label;
  const progress = relevantPlayback?.progress ?? 0;
  const displayedDuration = relevantPlayback?.motion_id === motion.id
    ? relevantPlayback.duration_s
    : preflight?.duration_s ?? 0;
  const preflightDisabled = actionBusy || disabledReason !== null || sessionActive || foreignPlaybackActive;
  const orchestrationReady = Boolean(
    state === 'READY' &&
    relevantPlayback?.session_id == null &&
    relevantPlayback?.motion_id === motion.id &&
    relevantPlayback?.trajectory_digest === preflight?.digest,
  );
  const playDisabled =
    actionBusy ||
    disabledReason !== null ||
    !hasPreparedTrajectory ||
    !orchestrationReady ||
    foreignPlaybackActive;
  const stopInFlight = actionKey === `stop-motion-${motion.id}`;
  const stopAvailable =
    state === 'PREFLIGHTING' ||
    state === 'READY' ||
    state === 'PLAYING' ||
    state === 'PAUSED';
  const optionsAvailable =
    state === 'IDLE' ||
    state === 'READY' ||
    state === 'PLAYING' ||
    state === 'PAUSED';
  const shownError = error ?? relevantPlayback?.error;

  return (
    <section aria-labelledby="motion-playback-heading" className="motion-playback-panel">
      <header>
        <div>
          <p className="section-kicker">Stage 5 安全流程</p>
          <h4 id="motion-playback-heading">预检与播放</h4>
        </div>
        <span className={`playback-state playback-state--${state.toLowerCase()}`}>{zhStatus(state)}</span>
      </header>

      <p className="motion-playback-panel__intro">
        {runtimeMode === 'REAL'
          ? '请先编译并验证不可变运动。真机播放始终通过后端授权的能力入口。'
          : '请先编译并验证不可变运动。播放始终通过已审核的仿真入口，不会访问实体硬件。'}
      </p>

      {disabledReason ? (
        <p className="playback-blocker" role="status">暂时无法播放 · {disabledReason}</p>
      ) : null}
      {foreignPlaybackActive ? (
        <p className="playback-blocker" role="status">
          另一个运动（{playback?.motion_id}）正在占用播放会话。请先停止它，再准备当前运动。
        </p>
      ) : null}
      {shownError ? (
        <div className="playback-error" role="alert">
          <span>{shownError}</span>
          {error ? (
            <button
              aria-label="关闭播放错误"
              className="command-button"
              onClick={onDismissError}
              type="button"
            >
              关闭
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="preflight-actions">
        <button
          className="command-button command-button--primary"
          disabled={preflightDisabled}
          onClick={onPreflight}
          type="button"
        >
          <ShieldCheck aria-hidden="true" />
          {actionKey === `preflight-motion-${motion.id}` ? '正在预检…' : '运行预检'}
        </button>
        <span>版本 {motion.revision} · 有边界的编译器采样</span>
      </div>

      {preflight ? (
        <section
          aria-label="预检结果"
          className={preflight.passed ? 'preflight-report preflight-report--passed' : 'preflight-report preflight-report--failed'}
        >
          <header>
            <strong>{preflight.passed ? '预检通过' : '预检未通过'}</strong>
            <code title={preflight.digest ?? '无轨迹摘要'}>{preflight.digest ?? '无摘要'}</code>
          </header>
          <dl className="preflight-metrics">
            <div><dt>时长</dt><dd>{seconds(preflight.duration_s)}</dd></div>
            <div><dt>轨迹段</dt><dd>{preflight.segment_count}</dd></div>
            <div><dt>采样点</dt><dd>{preflight.sample_count}</dd></div>
            <div><dt>采样率</dt><dd>{preflight.sample_rate_hz} Hz</dd></div>
          </dl>
          {preflight.violations.length > 0 ? (
            <div className="preflight-violations">
              <strong>违规项</strong>
              <ul>
                {preflight.violations.map((violation, index) => (
                  <li key={`${violation.code}-${violation.segment_index ?? 'motion'}-${index}`}>
                    <code>{violation.code}</code>
                    <span>{violation.message}</span>
                    {violation.segment_index !== null && violation.segment_index !== undefined
                      ? <small>轨迹段 {violation.segment_index + 1}</small>
                      : null}
                    {violation.keyframe_id ? <small>关键帧 {violation.keyframe_id}</small> : null}
                    {violation.check ? <small>检查项 {violation.check}</small> : null}
                    {violation.sample_index !== null && violation.sample_index !== undefined
                      ? <small>采样点 {violation.sample_index}</small>
                      : null}
                    {violation.joint_id ? (
                      <small>
                        关节 {violation.joint_id}
                        {violation.actual !== null && violation.actual !== undefined
                          ? ` · 实际 ${violation.actual}${violation.unit ? ` ${violation.unit}` : ''}`
                          : ''}
                        {violation.limit !== null && violation.limit !== undefined
                          ? ` · 限制 ${violation.limit}${violation.unit ? ` ${violation.unit}` : ''}`
                          : ''}
                      </small>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {preflight.checks.length > 0 ? (
            <details className="preflight-checks">
              <summary>安全检查 · {preflight.checks.filter((check) => check.passed).length}/{preflight.checks.length} 通过</summary>
              <ul>
                {preflight.checks.map((check, index) => (
                  <li key={`${check.name}-${index}`}>
                    <strong>{check.passed ? '通过' : '失败'} · {check.name}</strong>
                    <span>{check.detail}</span>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </section>
      ) : null}

      {previewLoading ? <p className="trajectory-loading" role="status">正在加载有边界的轨迹预览…</p> : null}
      {preview ? <TrajectoryPreview preview={preview} /> : null}

      <section aria-labelledby="playback-controls-heading" className="playback-controls">
        <header>
          <h5 id="playback-controls-heading">播放控制</h5>
          <span>{hasPreparedTrajectory ? '已验证准备好的轨迹摘要' : '需要先运行预检'}</span>
        </header>
        <div className="playback-controls__buttons">
          <button className="command-button command-button--primary" disabled={playDisabled} onClick={onPlay} type="button">
            <CirclePlay aria-hidden="true" /> 播放
          </button>
          <button className="command-button" disabled={actionBusy || state !== 'PLAYING' || disabledReason !== null} onClick={onPause} type="button">
            <CirclePause aria-hidden="true" /> 暂停
          </button>
          <button className="command-button" disabled={actionBusy || state !== 'PAUSED' || disabledReason !== null} onClick={onResume} type="button">
            <RotateCcw aria-hidden="true" /> 继续
          </button>
          <button
            className="command-button command-button--danger"
            disabled={stopDisabled || stopInFlight || !stopAvailable}
            onClick={onStop}
            type="button"
          >
            <Square aria-hidden="true" /> 停止
          </button>
        </div>
        <div className="playback-options">
          <label>
            <span>速度倍率</span>
            <select
              aria-label="播放速度倍率"
              disabled={actionBusy || disabledReason !== null || foreignPlaybackActive || !optionsAvailable}
              onChange={(event) => onRateChange(Number(event.target.value))}
              value={rate}
            >
              {RATE_OPTIONS.map((option) => <option key={option} value={option}>{option}×</option>)}
            </select>
          </label>
          <label className="playback-loop-toggle">
            <input
              checked={loop}
              disabled={actionBusy || disabledReason !== null || foreignPlaybackActive || !optionsAvailable}
              onChange={(event) => onLoopChange(event.target.checked)}
              type="checkbox"
            />
            <span>循环播放</span>
          </label>
        </div>

        <div aria-live="polite" className="playback-progress">
          <div>
            <strong>{zhStatus(state)}</strong>
            <span>{Math.round(progress * 100)}%</span>
          </div>
          <progress aria-label="播放进度" max={1} value={progress} />
          <dl>
            <div><dt>已用时</dt><dd>{seconds(relevantPlayback?.elapsed_s ?? 0)} / {seconds(displayedDuration)}</dd></div>
            <div><dt>关键帧</dt><dd title={keyframeLabel ?? relevantPlayback?.current_keyframe_id ?? undefined}>{keyframeLabel ?? relevantPlayback?.current_keyframe_id ?? '—'}</dd></div>
            <div><dt>轨迹段</dt><dd>{relevantPlayback?.current_segment_index === null || relevantPlayback?.current_segment_index === undefined ? '—' : relevantPlayback.current_segment_index + 1}</dd></div>
            <div><dt>采样点</dt><dd>{relevantPlayback?.current_sample_index ?? '—'}</dd></div>
          </dl>
          <small>速度 {rate}× · {loop ? '循环开启' : '循环关闭'} · 未访问实体硬件</small>
        </div>
      </section>
    </section>
  );
}
