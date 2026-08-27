import { AlertCircle, CheckCircle2, LoaderCircle, X } from 'lucide-react';
import { useEffect, useState } from 'react';
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
import { StudioInspector } from '../features/studio/StudioInspector';
import { StudioTimeline } from '../features/studio/StudioTimeline';
import { StudioToolbar } from '../features/studio/StudioToolbar';
import { StudioViewer } from '../features/studio/StudioViewer';
import { useStudioWorkspace } from '../features/studio/useStudioWorkspace';
import { useForwardKinematics } from '../features/control/useForwardKinematics';

type Confirmation =
  | { type: 'new' }
  | { type: 'goto'; frameId: string }
  | null;

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
  const [confirmation, setConfirmation] = useState<Confirmation>(null);
  const [mobileInspectorOpen, setMobileInspectorOpen] = useState(false);
  const kinematics = useForwardKinematics({
    enabled: runtime.backend === 'connected' && runtime.robot?.connected === true,
    stateSequence: runtime.robot?.state_sequence ?? null,
    socketTcpPose: null,
    socketStateSequence: null,
  });
  const frameLimitReached = workspace.keyframes.length >= 1000;

  useEffect(() => {
    if (
      workspace.initializing ||
      !workspace.draft ||
      workspace.loadedEntryKey !== entryKey ||
      searchParams.get('draft') === workspace.draft.id
    ) return;
    setSearchParams({ draft: workspace.draft.id }, { replace: true });
  }, [entryKey, searchParams, setSearchParams, workspace.draft, workspace.initializing, workspace.loadedEntryKey]);

  const openSaveAs = () => {
    setSaveAsName(`${workspace.editor.document.name || '未命名运动'} 副本`);
    setSaveAsOpen(true);
  };

  const requestNew = () => {
    if (workspace.formalDirty) setConfirmation({ type: 'new' });
    else void workspace.createBlankDraft();
  };

  const confirmAction = () => {
    if (confirmation?.type === 'new') void workspace.createBlankDraft();
    if (confirmation?.type === 'goto') void workspace.gotoFrame(confirmation.frameId);
    setConfirmation(null);
  };

  if (workspace.initializing) {
    return (
      <div className="page studio-page">
        <PageIntro
          title="编排"
          description="正在加载自动保存的时间轴工作区。"
          detail="草稿恢复只处理当前草稿，不会覆盖已正式保存的运动。"
        />
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
        <PageIntro
          title="编排"
          description="编辑器打开前检测到一次未完成的正式保存。"
          detail="MOMO Studio 不会擅自推断、重试或覆盖这次中断的保存。"
        />
        <div className="studio-notice studio-notice--conflict" role="alert">
          <AlertCircle aria-hidden="true" />
          <span>需要先明确解除正式保存的恢复标记，才能继续编辑此草稿。</span>
        </div>
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

  return (
    <div className="page studio-page">
      <PageIntro
        title="编排"
        description="使用关键帧和帧间过渡来编排摄影机械臂运动。"
        detail={`草稿会独立自动保存；只有通过校验和轨迹编译的正式运动，才能进入${runtime.controlMode === 'REAL' ? '后端授权的真机' : '仿真'}播放。`}
      />

      <StudioToolbar
        autosaveLabel={workspace.autosaveLabel}
        busy={workspace.action !== null}
        canRedo={workspace.editor.redoStack.length > 0}
        canSaveMotion={workspace.saveDisabledReason === null}
        canUndo={workspace.editor.undoStack.length > 0}
        dirty={workspace.formalDirty}
        draftName={workspace.editor.document.name}
        draftRevision={workspace.draft?.revision ?? null}
        onNameChange={(name) => workspace.edit({ type: 'document/set-name', name })}
        onNew={requestNew}
        onRedo={() => workspace.edit({ type: 'history/redo' })}
        onSave={() => void workspace.save()}
        onSaveAs={openSaveAs}
        onUndo={() => workspace.edit({ type: 'history/undo' })}
        robotVariant={workspace.editor.document.robotVariant}
        saveDisabledReason={workspace.saveDisabledReason}
      />

      {workspace.recoveryMessage ? (
        <div className="studio-notice studio-notice--success" role="status">
          <CheckCircle2 aria-hidden="true" />
          <span>{workspace.recoveryMessage}</span>
          <button aria-label="关闭编排提示" className="mini-command" onClick={workspace.clearRecoveryMessage} type="button">
            <X aria-hidden="true" />
          </button>
        </div>
      ) : null}
      {workspace.error ? (
        <div className="studio-notice studio-notice--error" role="alert">
          <AlertCircle aria-hidden="true" />
          <span>{workspace.error}</span>
          <button aria-label="关闭编排错误" className="mini-command" onClick={workspace.clearError} type="button">
            <X aria-hidden="true" />
          </button>
        </div>
      ) : null}
      {workspace.conflict && workspace.conflictAcknowledged ? (
        <div className="studio-notice studio-notice--conflict" role="status">
          <AlertCircle aria-hidden="true" />
          <span>草稿自动保存因版本冲突暂停。你可以继续本地编辑，然后选择“重新加载”或“另存为”。</span>
          <div className="studio-notice__actions">
            <button className="command-button" disabled={workspace.action !== null} onClick={() => void workspace.reloadConflict()} type="button">重新加载</button>
            <button className="command-button command-button--primary" disabled={workspace.action !== null || workspace.saveDisabledReason !== null} onClick={openSaveAs} type="button">另存为</button>
          </div>
        </div>
      ) : null}

      <StudioViewer
        action={workspace.action}
        compileDisabledReason={workspace.compileDisabledReason}
        compileError={null}
        currentTcp={kinematics.fk?.tcp_pose ?? null}
        currentTcpError={kinematics.error}
        draftPreflight={workspace.draftPreflight}
        draftValidation={workspace.draftValidation}
        frameLimitReached={frameLimitReached}
        motionDisabledReason={workspace.motionDisabledReason}
        playbackDisabledReason={workspace.playbackDisabledReason}
        onAddPose={() => workspace.startPoseInsertion('after', workspace.editor.selectedFrameId)}
        onCapture={() => void workspace.capture()}
        onCompile={() => void workspace.compile()}
        onOpenInspector={() => setMobileInspectorOpen(true)}
        onPause={() => void workspace.pause()}
        onPlay={() => void workspace.play()}
        onPreparePlayback={() => void workspace.preparePlayback()}
        onResume={() => void workspace.resume()}
        onStop={() => void workspace.stop()}
        onValidate={() => void workspace.validate()}
        playback={workspace.playback}
        playbackPreflight={workspace.playbackPreflight}
        preview={workspace.preview}
        robot={runtime.robot}
        runtimeMode={runtime.controlMode}
        savedMotion={workspace.savedMotion}
        savedMotionCurrent={!workspace.formalDirty}
        selectedFrame={workspace.selectedFrame}
        studioCommand={workspace.studioCommand}
        validateDisabledReason={workspace.validateDisabledReason}
      />

      <div className="studio-editor-grid">
        <StudioTimeline
          disabled={workspace.action !== null}
          defaultEdgeIds={workspace.defaultEdgeIds}
          frameLimitReached={frameLimitReached}
          frames={workspace.keyframes}
          initialScrollS={workspace.timelineScrollS}
          runtimeMode={runtime.controlMode}
          onAddAfter={(frameId) => workspace.startPoseInsertion('after', frameId)}
          onAddBefore={(frameId) => workspace.startPoseInsertion('before', frameId)}
          onDelete={(frameId) => workspace.edit({ type: 'frame/delete', frameId })}
          onDuplicate={(frameId) => workspace.edit({ type: 'frame/duplicate', frameId, duplicateFrameId: crypto.randomUUID() })}
          onMove={(frameId, direction) => workspace.edit({
            type: 'frame/move',
            frameId,
            direction: direction < 0 ? 'backward' : 'forward',
          })}
          onPlayheadChange={workspace.setPlayheadS}
          onReorder={(frameId, toIndex) => workspace.edit({ type: 'frame/reorder', frameId, toIndex })}
          onScrollChange={workspace.setTimelineScrollS}
          onSelect={(frameId) => workspace.edit({ type: 'selection/set', frameId })}
          onZoomChange={workspace.setTimelineZoom}
          playheadS={workspace.playheadS}
          selectedFrameId={workspace.editor.selectedFrameId}
          zoom={workspace.timelineZoom}
        />

        <StudioInspector
          busy={workspace.action !== null}
          frame={workspace.selectedFrame}
          frameIndex={workspace.selectedFrameIndex}
          frameLimitReached={frameLimitReached}
          mobileOpen={mobileInspectorOpen}
          motionDisabledReason={workspace.motionDisabledReason}
          runtimeMode={runtime.controlMode}
          onAddAfter={(frameId) => workspace.startPoseInsertion('after', frameId)}
          onAddBefore={(frameId) => workspace.startPoseInsertion('before', frameId)}
          onCaptureAfter={(frameId) => void workspace.capture('after', frameId)}
          onCaptureBefore={(frameId) => void workspace.capture('before', frameId)}
          onCloseMobile={() => setMobileInspectorOpen(false)}
          onDelete={(frameId) => workspace.edit({ type: 'frame/delete', frameId })}
          onDuplicate={(frameId) => workspace.edit({ type: 'frame/duplicate', frameId, duplicateFrameId: crypto.randomUUID() })}
          onEasingChange={(frameId, easing) => workspace.edit({ type: 'edge/set-easing', toFrameId: frameId, easing })}
          onGoto={(frameId) => setConfirmation({ type: 'goto', frameId })}
          onHoldChange={(frameId, holdS) => workspace.edit({ type: 'frame/set-hold', frameId, holdS })}
          onLabelChange={(frameId, label) => workspace.edit({ type: 'frame/set-label', frameId, label })}
          onModeChange={(frameId, motionMode) => workspace.edit({ type: 'edge/set-mode', toFrameId: frameId, motionMode })}
          onReplace={(frameId) => void workspace.replaceSnapshot(frameId)}
          onTransitionDurationChange={(frameId, durationS) => workspace.edit({ type: 'edge/set-duration', toFrameId: frameId, durationS })}
        />
      </div>

      {workspace.poseInsertion ? (
        <StudioPosePicker
          busy={workspace.posesBusy}
          error={workspace.poseError}
          onChoose={(pose) => void workspace.addPose(pose)}
          onClose={workspace.closePoseInsertion}
          onSearchChange={workspace.setPoseSearch}
          placement={workspace.poseInsertion.position}
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
          onSaveAs={() => {
            openSaveAs();
          }}
        />
      ) : null}

      {confirmation ? (
        <StudioConfirmDialog
          busy={workspace.action !== null}
          confirmLabel={confirmation.type === 'new'
            ? '新建草稿'
            : `确认${runtime.controlMode === 'REAL' ? '真机' : '仿真'}前往`}
          danger={confirmation.type === 'new'}
          description={confirmation.type === 'new'
            ? '当前工作草稿已经自动保存，但尚未保存为正式运动。新建空白草稿不会删除它。'
            : runtime.controlMode === 'REAL'
              ? '通过后端授权的真机关节运动入口提交内嵌关键帧快照。'
              : '通过唯一经过审核的仿真安全入口提交内嵌关键帧快照；不会启用实体硬件。'}
          onCancel={() => setConfirmation(null)}
          onConfirm={confirmAction}
          title={confirmation.type === 'new' ? '新建空白草稿？' : '前往所选关键帧？'}
        />
      ) : null}
    </div>
  );
}
