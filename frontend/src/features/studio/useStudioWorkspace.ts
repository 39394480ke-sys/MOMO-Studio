import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';

import { captureStudioSnapshot } from '../../api/client';
import type {
  MotionEasing,
  MotionKeyframe,
  MotionMode,
} from '../../api/types';
import type { RuntimeStatus } from '../../components/runtimeStatusContext';
import {
  createEmptyStudioDocument,
  createStudioEditorState,
  studioDocumentToDraftKeyframes,
  studioEditorReducer,
  validatePlayableStudioDocument,
  type StudioInsertPosition,
} from './studioEditorState';
import { useStudioDirtyNavigationGuard } from './useStudioDirtyNavigationGuard';
import {
  useStudioDraftSession,
  type StudioEntry,
} from './useStudioDraftSession';
import { useStudioMotionSession } from './useStudioMotionSession';
import {
  snapshotCompatibilityReason,
  useStudioPoseInsertion,
} from './useStudioPoseInsertion';

export type {
  StudioConflict,
  StudioFormalSaveRecovery,
} from './useStudioDraftSession';

const MAX_STUDIO_FRAMES = 1000;

function id(): string {
  return globalThis.crypto.randomUUID();
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : '编排操作失败。';
}

export function useStudioWorkspace(entry: StudioEntry, runtime: RuntimeStatus) {
  const [editor, dispatch] = useReducer(
    studioEditorReducer,
    createStudioEditorState(createEmptyStudioDocument({ robotVariant: 'V2', name: '未命名运动' })),
  );
  const [playheadS, setPlayheadS] = useState(0);
  const [timelineZoom, setTimelineZoom] = useState(1);
  const [timelineScrollS, setTimelineScrollS] = useState(0);
  const editorRef = useRef(editor);
  editorRef.current = editor;

  const draftSession = useStudioDraftSession({
    dispatch,
    editor,
    entry,
    playheadS,
    runtime,
    setPlayheadS,
    setTimelineScrollS,
    setTimelineZoom,
    timelineScrollS,
    timelineZoom,
  });
  const { clearCompiledState, setAction, setError } = draftSession;

  const edit = useCallback((actionToDispatch: Parameters<typeof dispatch>[0]) => {
    const current = editorRef.current;
    const next = studioEditorReducer(current, actionToDispatch);
    if (next.document !== current.document) clearCompiledState();
    dispatch(actionToDispatch);
  }, [clearCompiledState]);

  const poseInsertionSession = useStudioPoseInsertion({
    document: editor.document,
    edit,
    getWorkspaceGeneration: draftSession.getWorkspaceGeneration,
    workspaceGeneration: draftSession.workspaceGeneration,
  });

  const motionSession = useStudioMotionSession({
    document: editor.document,
    onDraftConflict: draftSession.recordDraftConflict,
    onError: draftSession.setError,
    onMessage: draftSession.setRecoveryMessage,
    persistWorkspace: draftSession.persistWorkspace,
    runtime,
    savedMotion: draftSession.savedMotion,
  });
  const action = draftSession.action ?? poseInsertionSession.action ?? motionSession.action;
  const actionRef = useRef(action);
  actionRef.current = action;

  const capture = useCallback(async (
    position: StudioInsertPosition = 'after',
    anchorFrameId: string | null = editorRef.current.selectedFrameId,
  ) => {
    if (editorRef.current.document.frames.length >= MAX_STUDIO_FRAMES) {
      setError(`编排草稿最多支持 ${MAX_STUDIO_FRAMES} 个关键帧。`);
      return;
    }
    setAction('capture');
    setError(null);
    try {
      const snapshot = await captureStudioSnapshot();
      const incompatibility = snapshotCompatibilityReason(snapshot, editorRef.current.document);
      if (incompatibility) throw new Error(incompatibility);
      edit({
        type: 'frame/capture',
        position,
        anchorFrameId,
        frameId: id(),
        label: `Capture ${editorRef.current.document.frames.length + 1}`,
        snapshot,
      });
    } catch (caught) {
      setError(message(caught));
    } finally {
      setAction((currentAction) => currentAction === 'capture' ? null : currentAction);
    }
  }, [edit, setAction, setError]);

  const replaceSnapshot = useCallback(async (frameId: string) => {
    setAction('replace');
    setError(null);
    try {
      const snapshot = await captureStudioSnapshot();
      const incompatibility = snapshotCompatibilityReason(
        snapshot,
        editorRef.current.document,
        frameId,
      );
      if (incompatibility) throw new Error(incompatibility);
      edit({ type: 'frame/replace-snapshot', frameId, snapshot, sourcePoseId: null });
    } catch (caught) {
      setError(message(caught));
    } finally {
      setAction((currentAction) => currentAction === 'replace' ? null : currentAction);
    }
  }, [edit, setAction, setError]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return;
      if (actionRef.current !== null) return;
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'z') return;
      event.preventDefault();
      edit({ type: event.shiftKey ? 'history/redo' : 'history/undo' });
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [edit]);

  useStudioDirtyNavigationGuard({
    formalDirty: draftSession.formalDirty,
    persistWorkspace: draftSession.persistWorkspace,
  });

  const keyframes = useMemo(
    () => studioDocumentToDraftKeyframes(editor.document),
    [editor.document],
  );
  const selectedFrame = keyframes.find((frame) => frame.id === editor.selectedFrameId) ?? null;
  const selectedFrameIndex = selectedFrame
    ? keyframes.findIndex((frame) => frame.id === selectedFrame.id)
    : -1;
  const defaultEdgeIds = useMemo(
    () => new Set(
      editor.document.edges
        .filter((edge) => edge.isDefault)
        .map((edge) => `${edge.fromFrameId}->${edge.toFrameId}`),
    ),
    [editor.document.edges],
  );
  const validation = validatePlayableStudioDocument(editor.document);
  const saveDisabledReason = validation.valid ? null : validation.errors[0] ?? '草稿无效。';
  const validateDisabledReason = runtime.backend !== 'connected'
    ? '后端不可用'
    : draftSession.draft === null ? '草稿尚未就绪' : null;
  const compileDisabledReason = runtime.backend !== 'connected'
    ? '后端不可用'
    : saveDisabledReason;

  return {
    action,
    addPose: poseInsertionSession.addPose,
    autosaveLabel: draftSession.autosaveLabel,
    capture,
    clearConflict: draftSession.clearConflict,
    closePoseInsertion: poseInsertionSession.closePoseInsertion,
    clearError: draftSession.clearError,
    clearRecoveryMessage: draftSession.clearRecoveryMessage,
    compile: draftSession.compile,
    compileDisabledReason,
    conflict: draftSession.conflict,
    conflictAcknowledged: draftSession.conflictAcknowledged,
    createBlankDraft: draftSession.createBlankDraft,
    defaultEdgeIds,
    draft: draftSession.draft,
    draftPreflight: draftSession.draftPreflight,
    draftValidation: draftSession.draftValidation,
    edit,
    editor,
    error: draftSession.error,
    formalDirty: draftSession.formalDirty,
    formalSaveRecovery: draftSession.formalSaveRecovery,
    gotoFrame: motionSession.gotoFrame,
    initializing: draftSession.initializing,
    keyframes,
    loadedEntryKey: draftSession.loadedEntryKey,
    motionDisabledReason: motionSession.disabledReason,
    pause: motionSession.pause,
    play: motionSession.play,
    playback: motionSession.playback,
    playbackDisabledReason: motionSession.playbackDisabledReason,
    playbackPreflight: motionSession.playbackPreflight,
    playheadS,
    poseError: poseInsertionSession.poseError,
    poseInsertion: poseInsertionSession.poseInsertion,
    poseSearch: poseInsertionSession.poseSearch,
    poses: poseInsertionSession.poses,
    posesBusy: poseInsertionSession.posesBusy,
    preparePlayback: motionSession.preparePlayback,
    preview: draftSession.preview,
    recoveryMessage: draftSession.recoveryMessage,
    releaseFormalSaveRecovery: draftSession.releaseFormalSaveRecovery,
    reloadConflict: draftSession.reloadConflict,
    replaceSnapshot,
    resume: motionSession.resume,
    save: draftSession.save,
    saveAs: draftSession.saveAs,
    saveDisabledReason,
    savedMotion: draftSession.savedMotion,
    selectedFrame,
    selectedFrameIndex,
    setPlayheadS: (value: number) => setPlayheadS((current) =>
      Number.isFinite(value) ? Math.min(600, Math.max(0, value)) : current
    ),
    setPoseSearch: poseInsertionSession.setPoseSearch,
    setTimelineScrollS: (value: number) => setTimelineScrollS((current) =>
      Number.isFinite(value) ? Math.min(600, Math.max(0, value)) : current
    ),
    setTimelineZoom: (value: number) => setTimelineZoom((current) =>
      Number.isFinite(value) ? Math.min(8, Math.max(0.25, value)) : current
    ),
    startPoseInsertion: poseInsertionSession.startPoseInsertion,
    stop: motionSession.stop,
    studioCommand: motionSession.studioCommand,
    timelineScrollS,
    timelineZoom,
    validate: draftSession.validate,
    validateDisabledReason,
  };
}

export type StudioWorkspace = ReturnType<typeof useStudioWorkspace>;

export function motionKeyframeForInspector(frame: MotionKeyframe | null): MotionKeyframe | null {
  return frame;
}

export type StudioModeUpdate = (frameId: string, mode: MotionMode) => void;
export type StudioEasingUpdate = (frameId: string, easing: MotionEasing) => void;
