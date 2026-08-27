import {
  CirclePause,
  CirclePlay,
  Eye,
  FolderPlus,
  PanelRightOpen,
  Radio,
  RotateCcw,
  ShieldCheck,
  Square,
} from 'lucide-react';

import type {
  MotionEntity,
  MotionDraftValidation,
  MotionKeyframe,
  MotionCommandStatus,
  PlaybackStatus,
  RobotStatus,
  TcpPose,
  TrajectoryPreflightReport,
  TrajectoryPreview as TrajectoryPreviewData,
} from '../../api/types';
import { TrajectoryPreview } from '../library/TrajectoryPreview';
import { zhStatus } from '../../i18n/zh';

interface StudioViewerProps {
  action: string | null;
  compileDisabledReason: string | null;
  compileError: string | null;
  currentTcp: TcpPose | null;
  currentTcpError: string | null;
  draftPreflight: TrajectoryPreflightReport | null;
  draftValidation: MotionDraftValidation | null;
  frameLimitReached: boolean;
  motionDisabledReason: string | null;
  playbackDisabledReason: string | null;
  playback: PlaybackStatus | null;
  playbackPreflight: TrajectoryPreflightReport | null;
  preview: TrajectoryPreviewData | null;
  robot: RobotStatus | null;
  runtimeMode: 'DRY RUN' | 'REAL';
  savedMotion: MotionEntity | null;
  savedMotionCurrent: boolean;
  selectedFrame: MotionKeyframe | null;
  studioCommand: MotionCommandStatus | null;
  validateDisabledReason: string | null;
  onAddPose: () => void;
  onCapture: () => void;
  onCompile: () => void;
  onOpenInspector: () => void;
  onPause: () => void;
  onPlay: () => void;
  onPreparePlayback: () => void;
  onResume: () => void;
  onStop: () => void;
  onValidate: () => void;
}

function fixed(value: number | undefined, digits = 1): string {
  return value === undefined || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

export function StudioViewer({
  action,
  compileDisabledReason,
  compileError,
  currentTcp,
  currentTcpError,
  draftPreflight,
  draftValidation,
  frameLimitReached,
  motionDisabledReason,
  playbackDisabledReason,
  playback,
  playbackPreflight,
  preview,
  robot,
  runtimeMode,
  savedMotion,
  savedMotionCurrent,
  selectedFrame,
  studioCommand,
  validateDisabledReason,
  onAddPose,
  onCapture,
  onCompile,
  onOpenInspector,
  onPause,
  onPlay,
  onPreparePlayback,
  onResume,
  onStop,
  onValidate,
}: StudioViewerProps) {
  const selectedTcp = selectedFrame?.pose_snapshot.tcp_pose;
  const state = playback?.state ?? 'IDLE';
  const playbackBelongsHere = Boolean(
    savedMotion && (!playback?.motion_id || playback.motion_id === savedMotion.id),
  );
  const playbackPrepared = Boolean(
    savedMotion &&
    playbackPreflight?.passed &&
    savedMotionCurrent &&
    playbackPreflight.digest &&
    playbackPreflight.motion_id === savedMotion.id &&
    playbackPreflight.motion_revision === savedMotion.revision &&
    playback?.state === 'READY' &&
    playback.trajectory_digest === playbackPreflight.digest,
  );
  const playbackActive =
    state === 'PREFLIGHTING' || state === 'READY' || state === 'PLAYING' || state === 'PAUSED';
  const stopAvailable =
    action === 'prepare-playback' ||
    playbackActive;
  const foreignPlaybackActive = playbackActive && !playbackBelongsHere;
  const studioCommandActive = Boolean(
    studioCommand &&
    ['ACCEPTED', 'PREFLIGHTING', 'READY', 'RUNNING', 'PLAYING', 'PAUSED', 'STOPPING'].includes(studioCommand.state),
  );
  const priorityStopAvailable = stopAvailable || action === 'goto' || studioCommandActive;
  const busy = action !== null;

  return (
    <section aria-labelledby="studio-viewer-heading" className="studio-viewer">
      <header className="studio-panel-heading">
        <div>
          <p className="section-kicker">{runtimeMode === 'REAL' ? '真机能力' : '仿真'}查看器</p>
          <h2 id="studio-viewer-heading">机械臂状态与轨迹</h2>
        </div>
        <div className="studio-viewer__badges">
          <span className="dry-run-badge">{runtimeMode}</span>
          <span className={`playback-state playback-state--${state.toLowerCase()}`}>{zhStatus(state)}</span>
          <button
            aria-label="打开关键帧检查器"
            className="mini-command studio-viewer__inspector-button"
            disabled={!selectedFrame}
            onClick={onOpenInspector}
            type="button"
          >
            <PanelRightOpen aria-hidden="true" />
          </button>
        </div>
      </header>

      <div className="studio-viewer__overview">
        <section aria-label={`当前${runtimeMode === 'REAL' ? '真机' : '仿真'}机械臂`} className="studio-viewer-card">
          <span>当前机械臂</span>
          <strong>{robot ? `${robot.variant} · ${zhStatus(robot.connection_state)}` : '不可用'}</strong>
          <small>
            {robot ? `${Object.keys(robot.positions).length} 个启用关节 · 状态序号 ${robot.state_sequence}` : '需要后端状态'}
          </small>
          <div className="studio-viewer-card__actions">
            <button
              className="command-button command-button--primary"
              disabled={busy || motionDisabledReason !== null || frameLimitReached}
              onClick={onCapture}
              title={frameLimitReached
                ? '草稿已达到 1000 个关键帧上限'
                : motionDisabledReason ?? '捕获一份由后端统一读取的状态快照'}
              type="button"
            >
              <Radio aria-hidden="true" /> {action === 'capture' ? '正在捕获…' : '捕获当前状态'}
            </button>
            <button className="command-button" disabled={busy || frameLimitReached} onClick={onAddPose} type="button">
              <FolderPlus aria-hidden="true" /> 添加机位
            </button>
          </div>
          {motionDisabledReason ? <small>暂时无法捕获 · {motionDisabledReason}</small> : null}
          {frameLimitReached ? <small>暂时无法捕获或插入 · 已达到 1000 个关键帧上限</small> : null}
          {currentTcp ? (
            <dl className="studio-viewer-tcp" aria-label="当前机械臂 TCP">
              <div><dt>X</dt><dd>{fixed(currentTcp.position_mm.x)} mm</dd></div>
              <div><dt>Y</dt><dd>{fixed(currentTcp.position_mm.y)} mm</dd></div>
              <div><dt>Z</dt><dd>{fixed(currentTcp.position_mm.z)} mm</dd></div>
            </dl>
          ) : <small>{currentTcpError ?? '正在等待后端返回当前正向运动学（FK）结果。'}</small>}
        </section>

        <section aria-label="所选关键帧 TCP" className="studio-viewer-card">
          <span>所选关键帧</span>
          <strong>{selectedFrame?.label ?? '尚未选择'}</strong>
          {selectedTcp ? (
            <dl className="studio-viewer-tcp">
              <div><dt>X</dt><dd>{fixed(selectedTcp.position_mm.x)} mm</dd></div>
              <div><dt>Y</dt><dd>{fixed(selectedTcp.position_mm.y)} mm</dd></div>
              <div><dt>Z</dt><dd>{fixed(selectedTcp.position_mm.z)} mm</dd></div>
            </dl>
          ) : (
            <small>请在时间轴上选择一个关键帧。</small>
          )}
        </section>

        <section aria-label="轨迹编译摘要" className="studio-viewer-card">
          <span>草稿编译</span>
          <strong>
            {draftPreflight
              ? draftPreflight.passed
                ? '预检通过'
                : '预检未通过'
              : '尚未编译'}
          </strong>
          <small>
            {draftPreflight
              ? `${draftPreflight.segment_count} 段 · ${draftPreflight.sample_count} 个采样点 · ${fixed(draftPreflight.duration_s, 2)} 秒`
              : '轨迹插值只由后端编译器生成。'}
          </small>
          <div className="studio-viewer-card__actions">
            <button
              className="command-button"
              disabled={busy || validateDisabledReason !== null}
              onClick={onValidate}
              title={validateDisabledReason ?? '校验已持久化的草稿边界'}
              type="button"
            >
              <ShieldCheck aria-hidden="true" /> {action === 'validate' ? '正在校验…' : '校验草稿'}
            </button>
            <button
              className="command-button"
              disabled={busy || compileDisabledReason !== null}
              onClick={onCompile}
              title={compileDisabledReason ?? '校验并编译一份有边界、不可直接执行的草稿预览'}
              type="button"
            >
              <Eye aria-hidden="true" /> {action === 'compile' ? '正在编译…' : '编译预览'}
            </button>
          </div>
          {validateDisabledReason ? <small>暂时无法校验 · {validateDisabledReason}</small> : null}
          {compileDisabledReason ? <small>暂时无法编译 · {compileDisabledReason}</small> : null}
        </section>
      </div>

      {compileError ? <p className="playback-error" role="alert">{compileError}</p> : null}

      {draftValidation ? (
        <section
          aria-label="编排草稿校验结果"
          className={draftValidation.valid ? 'preflight-report preflight-report--passed' : 'preflight-report'}
        >
          <header>
            <strong>{draftValidation.valid ? '草稿结构有效' : '草稿结构需要处理'}</strong>
            <code>草稿版本 {draftValidation.draft_revision}</code>
          </header>
          {draftValidation.issues.length > 0 ? (
            <ul className="studio-compile-issues">
              {draftValidation.issues.map((issue, index) => (
                <li key={`${issue.code}-${index}`}><code>{issue.code}</code> {issue.message}</li>
              ))}
            </ul>
          ) : <small className="studio-non-executable-note">通过结构校验并不代表草稿可以直接执行。</small>}
        </section>
      ) : null}

      {draftPreflight ? (
        <section
          aria-label="编排草稿预检结果"
          className={draftPreflight.passed ? 'preflight-report preflight-report--passed' : 'preflight-report'}
        >
          <header>
            <strong>{draftPreflight.passed ? '草稿轨迹已接受' : '草稿轨迹已拒绝'}</strong>
            <code>{draftPreflight.digest ?? '无摘要'}</code>
          </header>
          <dl className="preflight-metrics">
            <div><dt>时长</dt><dd>{fixed(draftPreflight.duration_s, 2)} 秒</dd></div>
            <div><dt>轨迹段</dt><dd>{draftPreflight.segment_count}</dd></div>
            <div><dt>采样点</dt><dd>{draftPreflight.sample_count}</dd></div>
            <div><dt>采样率</dt><dd>{draftPreflight.sample_rate_hz} Hz</dd></div>
          </dl>
          {draftPreflight.violations.length > 0 ? (
            <ul className="studio-compile-issues">
              {draftPreflight.violations.map((violation, index) => (
                <li key={`${violation.code}-${index}`}>
                  <code>{violation.code}</code> {violation.message}
                </li>
              ))}
            </ul>
          ) : null}
          {draftPreflight.checks.length > 0 ? (
            <details className="preflight-checks">
              <summary>编译器检查（{draftPreflight.checks.length}）</summary>
              <ul>
                {draftPreflight.checks.map((check, index) => (
                  <li key={`${check.name}-${index}`}>
                    <strong>{check.passed ? '通过' : '失败'} · {check.name}</strong>
                    <span>{check.detail}</span>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
          <small className="studio-non-executable-note">
            草稿预览不可直接执行。请先保存为正式运动，再运行正常的摘要绑定播放预检。
          </small>
        </section>
      ) : null}

      {preview ? <TrajectoryPreview preview={preview} /> : null}

      <section aria-labelledby="studio-playback-heading" className="studio-playback">
        <header>
          <div>
            <p className="section-kicker">仅限已保存的正式运动</p>
            <h3 id="studio-playback-heading">{runtimeMode === 'REAL' ? '已授权真机' : '仿真'}播放</h3>
          </div>
          <span>{savedMotion ? `${savedMotion.name} · 版本 ${savedMotion.revision}` : '需要先保存'}</span>
        </header>
        <div className="studio-playback__buttons">
          <button
            className="command-button"
            disabled={busy || !savedMotion || !savedMotionCurrent || playbackDisabledReason !== null || stopAvailable || studioCommandActive}
            onClick={onPreparePlayback}
            title={!savedMotion
              ? '请先将此草稿保存为正式运动'
              : !savedMotionCurrent
                ? '请先保存当前修改，再准备播放'
                : '运行不可变运动的播放预检'}
            type="button"
          >
            <ShieldCheck aria-hidden="true" /> {action === 'prepare-playback' ? '正在准备…' : '准备播放'}
          </button>
          <button
            className="command-button command-button--primary"
            disabled={busy || !playbackPrepared || playbackDisabledReason !== null}
            onClick={onPlay}
            title={playbackPrepared
              ? `通过${runtimeMode === 'REAL' ? '真机能力' : '仿真'}安全入口播放已准备轨迹`
              : '请先准备播放'}
            type="button"
          >
            <CirclePlay aria-hidden="true" /> 播放
          </button>
          <button className="command-button" disabled={busy || !playbackBelongsHere || state !== 'PLAYING'} onClick={onPause} type="button">
            <CirclePause aria-hidden="true" /> 暂停
          </button>
          <button className="command-button" disabled={busy || !playbackBelongsHere || state !== 'PAUSED'} onClick={onResume} type="button">
            <RotateCcw aria-hidden="true" /> 继续
          </button>
          <button className="command-button command-button--danger" disabled={action === 'stop' || !priorityStopAvailable} onClick={onStop} type="button">
            <Square aria-hidden="true" /> 停止
          </button>
        </div>
        {savedMotion && !savedMotionCurrent ? (
          <p className="studio-field-note">保存当前修改前不能准备新的播放；已经运行的不可变轨迹仍可随时停止。</p>
        ) : null}
        {foreignPlaybackActive ? (
          <p className="studio-field-note">另一个正式运动正在占用播放会话。编辑操作保持隔离，但优先停止仍然可用。</p>
        ) : null}
        {studioCommand ? (
          <p className="studio-field-note">前往编排关键帧 · {zhStatus(studioCommand.state)} · 命令 {studioCommand.command_id}</p>
        ) : null}
        {playbackDisabledReason ? (
          <p className="studio-field-note">暂时不能执行新的播放操作 · {playbackDisabledReason}</p>
        ) : null}
        <div className="studio-playback-progress" aria-live="polite">
          <progress aria-label="编排播放进度" max="1" value={playbackBelongsHere ? playback?.progress ?? 0 : 0} />
          <span>{Math.round((playbackBelongsHere ? playback?.progress ?? 0 : 0) * 100)}%</span>
          <small>{runtimeMode === 'REAL'
            ? '需要后端 REAL_PLAYBACK 真机播放能力'
            : '未访问实体硬件 · 真机预览已拒绝'}</small>
        </div>
      </section>
    </section>
  );
}
