import { AlertCircle, CheckCircle2, LoaderCircle, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { PageIntro } from '../components/PageIntro';
import { useRuntimeStatus } from '../components/runtimeStatusContext';
import {
  StudioConflictDialog,
  StudioConfirmDialog,
  StudioFormalSaveRecoveryDialog,
  StudioPosePicker,
  StudioSaveAsDialog,
} from '../features/studio/StudioDialogs';
import { StudioCompatibilityNotice } from '../features/studio/StudioCompatibilityNotice';
import { StudioInspector } from '../features/studio/StudioInspector';
import { StudioTimeline } from '../features/studio/StudioTimeline';
import { StudioToolbar } from '../features/studio/StudioToolbar';
import { StudioViewer } from '../features/studio/StudioViewer';
import { timelineData } from '../features/studio/studioTimelineMath';
import {
  sampleDraftJointState,
  sampleTrajectoryJointState,
} from '../features/studio/studioViewerState';
import { useStudioWorkspace } from '../features/studio/useStudioWorkspace';

const EMPTY_JOINT_IDS: readonly string[] = [];
const EMPTY_JOINT_DEFINITIONS: readonly never[] = [];

export function StudioPage() {
  const runtime = useRuntimeStatus();
  const [searchParams, setSearchParams] = useSearchParams();
  const entryKey = `${searchParams.get('draft') ?? ''}|${searchParams.get('motion') ?? ''}|${searchParams.get('pose') ?? ''}`;
  const workspace = useStudioWorkspace({
    draftId: searchParams.get('draft'),
    motionId: searchParams.get('motion'),
    poseId: searchParams.get('pose'),
  }, runtime);
  const [saveAsOpen, setSaveAsOpen] = useState(false);
  const [saveAsName, setSaveAsName] = useState('');
  const [confirmNewOpen, setConfirmNewOpen] = useState(false);
  const [mobileInspectorOpen, setMobileInspectorOpen] = useState(false);
  const [simulationPlaying, setSimulationPlaying] = useState(false);
  const compilePreview = workspace.compile;
  const setWorkspacePlayheadS = workspace.setPlayheadS;
  const playheadRef = useRef(workspace.playheadS);
  playheadRef.current = workspace.playheadS;

  const frameLimitReached = workspace.keyframes.length >= 1000;
  const frameIds = useMemo(
    () => new Set(workspace.keyframes.map((frame) => frame.id)),
    [workspace.keyframes],
  );
  const timeline = useMemo(() => timelineData(workspace.keyframes), [workspace.keyframes]);
  const simulationDuration = workspace.preview?.duration_s ?? timeline.duration;
  const viewerProfile = useMemo(() => {
    const profile = runtime.profile?.profile ?? null;
    return profile?.variant === workspace.editor.document.robotVariant ? profile : null;
  }, [runtime.profile, workspace.editor.document.robotVariant]);
  const viewerEnabledJointIds = viewerProfile?.enabled_joints ?? EMPTY_JOINT_IDS;
  const viewerJointDefinitions = viewerProfile?.joint_definitions ?? EMPTY_JOINT_DEFINITIONS;
  const sampledViewerState = useMemo(
    () => sampleTrajectoryJointState(workspace.preview, workspace.playheadS, viewerEnabledJointIds)
      ?? sampleDraftJointState(workspace.keyframes, workspace.playheadS, viewerEnabledJointIds),
    [viewerEnabledJointIds, workspace.keyframes, workspace.playheadS, workspace.preview],
  );
  const selectedSnapshot = workspace.selectedFrame?.pose_snapshot.joint_state ?? null;
  const viewerJointPositions = sampledViewerState?.positions
    ?? selectedSnapshot?.positions
    ?? runtime.robot?.positions
    ?? {};
  const viewerJointUnits = sampledViewerState?.units
    ?? selectedSnapshot?.units
    ?? runtime.robot?.units
    ?? {};

  useEffect(() => {
    if (
      workspace.initializing
      || !workspace.draft
      || workspace.loadedEntryKey !== entryKey
      || searchParams.get('draft') === workspace.draft.id
    ) return;
    setSearchParams({ draft: workspace.draft.id }, { replace: true });
  }, [entryKey, searchParams, setSearchParams, workspace.draft, workspace.initializing, workspace.loadedEntryKey]);

  useEffect(() => {
    if (!workspace.preview) setSimulationPlaying(false);
  }, [workspace.preview]);

  useEffect(() => {
    if (!simulationPlaying) return;
    let animationFrame = 0;
    let previous = performance.now();
    const tick = (now: number) => {
      const elapsed = Math.max(0, (now - previous) / 1000);
      previous = now;
      const next = Math.min(simulationDuration, playheadRef.current + elapsed);
      setWorkspacePlayheadS(next);
      if (next >= simulationDuration) {
        setSimulationPlaying(false);
        return;
      }
      animationFrame = window.requestAnimationFrame(tick);
    };
    animationFrame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(animationFrame);
  }, [setWorkspacePlayheadS, simulationDuration, simulationPlaying]);

  const openSaveAs = () => {
    setSaveAsName(`${workspace.editor.document.name || '未命名运动'} 副本`);
    setSaveAsOpen(true);
  };

  const requestNew = () => {
    if (workspace.formalDirty) setConfirmNewOpen(true);
    else void workspace.createBlankDraft();
  };
  const canSwitchCompatibilityVariant = Boolean(
    workspace.compatibilityIssue
    && runtime.backend === 'connected'
    && runtime.controlMode === 'DRY RUN'
    && runtime.hardwareAccessPolicy === 'DISABLED'
    && runtime.realMotionEnabled === false
    && runtime.robot?.connected === false
    && runtime.pendingAction === null,
  );

  const playSimulation = useCallback(async () => {
    let preview = workspace.preview;
    if (!preview) preview = await compilePreview();
    if (!preview) return;
    if (playheadRef.current >= preview.duration_s) setWorkspacePlayheadS(0);
    setSimulationPlaying(true);
  }, [compilePreview, setWorkspacePlayheadS, workspace.preview]);

  const pauseSimulation = useCallback(() => setSimulationPlaying(false), []);
  const scrubSimulation = useCallback((timeS: number) => {
    setWorkspacePlayheadS(timeS);
  }, [setWorkspacePlayheadS]);

  if (workspace.initializing) {
    return (
      <div className="page studio-page">
        <PageIntro title="编辑" description="正在加载 Motion Workspace。" detail="草稿恢复不会覆盖已正式保存的运动。" />
        <div className="studio-initializing" role="status">
          <LoaderCircle aria-hidden="true" />
          <strong>正在打开编排草稿…</strong>
        </div>
      </div>
    );
  }

  if (workspace.formalSaveRecovery) {
    const recovery = workspace.formalSaveRecovery;
    return (
      <div className="page studio-page">
        <PageIntro title="编辑" description="检测到一次未完成的正式保存。" detail="MOMO Studio 不会擅自覆盖运动资源。" />
        <StudioFormalSaveRecoveryDialog
          actualTargetRevision={recovery.actualTargetRevision}
          busy={workspace.action === 'abandon-save-intent'}
          draftId={recovery.draftId}
          draftRevision={recovery.draftRevision}
          error={workspace.error}
          kind={recovery.kind}
          onRelease={() => void workspace.releaseFormalSaveRecovery()}
          reason={recovery.reason}
          targetMotionId={recovery.targetMotionId}
          targetMotionRevision={recovery.targetMotionRevision}
        />
      </div>
    );
  }

  const lastFrameId = workspace.keyframes.at(-1)?.id ?? null;
  const insertionAnchorId = workspace.editor.selectedFrameId ?? lastFrameId;

  return (
    <div className="page studio-page">
      <PageIntro
        title="编辑"
        description="Motion Workspace · 编辑关键帧、节奏与摄影机械臂轨迹。"
        detail="时间轴播放和拖动只驱动仿真预览，不会向实体机械臂发送命令。"
      />

      <StudioToolbar
        autosaveLabel={workspace.autosaveLabel}
        busy={workspace.action !== null}
        canRedo={workspace.editor.redoStack.length > 0}
        canSaveMotion={workspace.saveDisabledReason === null}
        canUndo={workspace.editor.undoStack.length > 0}
        dirty={workspace.formalDirty}
        draftName={workspace.editor.document.name}
        onNameChange={(name) => workspace.edit({ type: 'document/set-name', name })}
        onNew={requestNew}
        onRedo={() => workspace.edit({ type: 'history/redo' })}
        onSave={() => void workspace.save()}
        onSaveAs={openSaveAs}
        onUndo={() => workspace.edit({ type: 'history/undo' })}
        saveDisabledReason={workspace.saveDisabledReason}
      />

      {workspace.recoveryMessage ? (
        <div className="studio-notice studio-notice--success" role="status">
          <CheckCircle2 aria-hidden="true" />
          <span>{workspace.recoveryMessage}</span>
          <button aria-label="关闭编排提示" className="mini-command" onClick={workspace.clearRecoveryMessage} type="button"><X aria-hidden="true" /></button>
        </div>
      ) : null}
      {workspace.error ? (
        <div className="studio-notice studio-notice--error" role="alert">
          <AlertCircle aria-hidden="true" />
          <span><strong>无法预览</strong></span>
          <span>{workspace.error}</span>
          <button aria-label="关闭编排错误" className="mini-command" onClick={workspace.clearError} type="button"><X aria-hidden="true" /></button>
        </div>
      ) : null}
      {workspace.compatibilityIssue ? (
        <StudioCompatibilityNotice
          busy={workspace.action !== null}
          canSwitchVariant={canSwitchCompatibilityVariant}
          frameCount={workspace.keyframes.length}
          frameIds={frameIds}
          issue={workspace.compatibilityIssue}
          onCaptureReplace={(frameId) => void workspace.replaceSnapshot(frameId)}
          onDelete={(frameId) => workspace.edit({ type: 'frame/delete', frameId })}
          onDiscardDraft={requestNew}
          onDismiss={workspace.clearError}
          onReplaceFromLibrary={workspace.startPoseReplacement}
          onSelect={(frameId) => workspace.edit({ type: 'selection/set', frameId })}
          onSwitchVariant={() => void runtime.switchVariant(workspace.compatibilityIssue?.draftVariant ?? 'V2')}
        />
      ) : null}
      {workspace.conflict && workspace.conflictAcknowledged ? (
        <div className="studio-notice studio-notice--conflict" role="status">
          <AlertCircle aria-hidden="true" />
          <span>草稿自动保存因版本冲突暂停。请选择重新加载或另存为。</span>
          <div className="studio-notice__actions">
            <button className="command-button" disabled={workspace.action !== null} onClick={() => void workspace.reloadConflict()} type="button">重新加载</button>
            <button className="command-button command-button--primary" disabled={workspace.action !== null || workspace.saveDisabledReason !== null} onClick={openSaveAs} type="button">另存为</button>
          </div>
        </div>
      ) : null}

      <main className="studio-workspace" aria-label="Motion 编辑工作区">
        <div className="studio-primary-grid">
          <StudioViewer
            onOpenInspector={() => setMobileInspectorOpen(true)}
            playbackActive={simulationPlaying}
            runtimeMode={runtime.controlMode}
            selectedFrame={workspace.selectedFrame}
            viewerEnabledJointIds={viewerEnabledJointIds}
            viewerJointDefinitions={viewerJointDefinitions}
            viewerJointPositions={viewerJointPositions}
            viewerJointUnits={viewerJointUnits}
            viewerVariant={workspace.editor.document.robotVariant}
          />

          <StudioInspector
            busy={workspace.action !== null}
            frame={workspace.selectedFrame}
            frameCount={workspace.keyframes.length}
            frameIndex={workspace.selectedFrameIndex}
            frameLimitReached={frameLimitReached}
            mobileOpen={mobileInspectorOpen}
            onCloseMobile={() => setMobileInspectorOpen(false)}
            onDelete={(frameId) => workspace.edit({ type: 'frame/delete', frameId })}
            onDuplicate={(frameId) => workspace.edit({ type: 'frame/duplicate', frameId, duplicateFrameId: crypto.randomUUID() })}
            onLabelChange={(frameId, label) => workspace.edit({ type: 'frame/set-label', frameId, label })}
            onModeChange={(frameId, motionMode) => workspace.edit({ type: 'edge/set-mode', toFrameId: frameId, motionMode })}
            onTransitionDurationChange={(frameId, durationS) => workspace.edit({ type: 'edge/set-duration', toFrameId: frameId, durationS })}
          />
        </div>

        <StudioTimeline
          disabled={workspace.action !== null}
          frameLimitReached={frameLimitReached}
          frames={workspace.keyframes}
          initialScrollS={workspace.timelineScrollS}
          isPlaying={simulationPlaying}
          motionName={workspace.editor.document.name}
          onAdd={() => workspace.startPoseInsertion('after', insertionAnchorId)}
          onMoveFrameTime={workspace.moveFrameTime}
          onPause={pauseSimulation}
          onPlay={() => void playSimulation()}
          onPlayheadChange={scrubSimulation}
          onScrollChange={workspace.setTimelineScrollS}
          onSelect={(frameId) => workspace.edit({ type: 'selection/set', frameId })}
          playheadS={workspace.playheadS}
          selectedFrameId={workspace.editor.selectedFrameId}
        />
      </main>

      {workspace.poseInsertion ? (
        <StudioPosePicker
          busy={workspace.posesBusy || workspace.action === 'capture'}
          error={workspace.poseError}
          onChoose={(pose) => {
            void workspace.addPose(pose).then((added) => {
              if (added) workspace.clearError();
            });
          }}
          onClose={workspace.closePoseInsertion}
          onCapture={() => {
            const insertion = workspace.poseInsertion;
            if (!insertion) return;
            if (insertion.kind === 'replace') {
              void workspace.replaceSnapshot(insertion.frameId).then((replaced) => {
                if (replaced) workspace.closePoseInsertion();
              });
            } else {
              void workspace.capture(insertion.position, insertion.anchorFrameId).then((captured) => {
                if (captured) workspace.closePoseInsertion();
              });
            }
          }}
          onSearchChange={workspace.setPoseSearch}
          placement="after"
          mode={workspace.poseInsertion.kind}
          poses={workspace.poses}
          search={workspace.poseSearch}
        />
      ) : null}

      {saveAsOpen ? (
        <StudioSaveAsDialog
          busy={workspace.action === 'save-as'}
          name={saveAsName}
          onClose={() => setSaveAsOpen(false)}
          onNameChange={setSaveAsName}
          onSave={() => {
            void workspace.saveAs(saveAsName).then((saved) => {
              if (saved) setSaveAsOpen(false);
            });
          }}
        />
      ) : null}

      {workspace.conflict && !workspace.conflictAcknowledged && !saveAsOpen ? (
        <StudioConflictDialog
          actualRevision={workspace.conflict.actualRevision}
          busy={workspace.action !== null}
          expectedRevision={workspace.conflict.expectedRevision}
          onCancel={workspace.clearConflict}
          onReload={() => void workspace.reloadConflict()}
          onSaveAs={openSaveAs}
        />
      ) : null}

      {confirmNewOpen ? (
        <StudioConfirmDialog
          busy={workspace.action !== null}
          confirmLabel="新建草稿"
          danger
          description="当前工作草稿已经自动保存，但尚未保存为正式运动。新建不会删除它。"
          onCancel={() => setConfirmNewOpen(false)}
          onConfirm={() => {
            setConfirmNewOpen(false);
            void workspace.createBlankDraft();
          }}
          title="新建空白草稿？"
        />
      ) : null}
    </div>
  );
}
