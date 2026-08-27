import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from 'react';

import {
  abandonMotionDraftSaveIntent,
  ApiError,
  compileMotionDraft,
  createMotionDraft,
  createMotionDraftFromMotion,
  forkMotionDraft,
  getMotion,
  getMotionDraft,
  getMotionDrafts,
  getPose,
  saveMotionDraft,
  saveMotionDraftAs,
  updateMotionDraft,
  validateMotionDraft,
} from '../../api/client';
import type {
  MotionDraft,
  MotionDraftEditorMetadata,
  MotionDraftValidation,
  MotionEntity,
  RobotVariant,
  TrajectoryPreflightReport,
  TrajectoryPreview,
} from '../../api/types';
import type { RuntimeStatus } from '../../components/runtimeStatusContext';
import {
  createEmptyStudioDocument,
  motionKeyframesToStudioDocument,
  motionToStudioDocument,
  studioDocumentToDraftKeyframes,
  type StudioDraftDocument,
  type StudioEditorAction,
  type StudioEditorState,
} from './studioEditorState';

const AUTOSAVE_DELAY_MS = 650;

export interface StudioEntry {
  draftId: string | null;
  motionId: string | null;
  poseId: string | null;
}

export interface StudioConflict {
  actualRevision: number | null;
  expectedRevision: number | null;
  scope: 'draft' | 'motion';
}

const FORMAL_SAVE_RECOVERY_REASONS = new Set([
  'FORMAL_SAVE_TARGET_IDENTITY_MISMATCH',
  'FORMAL_SAVE_TARGET_CONTENT_MISMATCH',
  'FORMAL_SAVE_TARGET_REVISION_ADVANCED',
] as const);

export interface StudioFormalSaveRecovery {
  reason:
    | 'FORMAL_SAVE_TARGET_IDENTITY_MISMATCH'
    | 'FORMAL_SAVE_TARGET_CONTENT_MISMATCH'
    | 'FORMAL_SAVE_TARGET_REVISION_ADVANCED';
  draftId: string;
  draftRevision: number;
  operationId: string;
  kind: 'SAVE' | 'SAVE_AS';
  targetMotionId: string;
  targetMotionRevision: number;
  expectedMotionRevision: number | null;
  actualTargetRevision: number | null;
  startedAt: string;
}

interface UseStudioDraftSessionOptions {
  dispatch: Dispatch<StudioEditorAction>;
  editor: StudioEditorState;
  entry: StudioEntry;
  playheadS: number;
  runtime: RuntimeStatus;
  setPlayheadS: Dispatch<SetStateAction<number>>;
  setTimelineScrollS: Dispatch<SetStateAction<number>>;
  setTimelineZoom: Dispatch<SetStateAction<number>>;
  timelineScrollS: number;
  timelineZoom: number;
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function positiveInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1 ? value : null;
}

function formalSaveRecovery(error: unknown): StudioFormalSaveRecovery | null {
  if (!(error instanceof ApiError) || error.status !== 409 || error.code !== 'REVISION_CONFLICT') {
    return null;
  }
  const details = record(error.details);
  if (!details || typeof details.reason !== 'string' || !FORMAL_SAVE_RECOVERY_REASONS.has(
    details.reason as StudioFormalSaveRecovery['reason'],
  )) return null;
  const draftRevision = positiveInteger(details.draft_revision);
  const targetMotionRevision = positiveInteger(details.target_motion_revision);
  const expectedMotionRevision = details.expected_motion_revision === null
    ? null
    : positiveInteger(details.expected_motion_revision);
  const actualTargetRevision = details.actual_target_revision === null || details.actual_target_revision === undefined
    ? null
    : positiveInteger(details.actual_target_revision);
  if (
    typeof details.draft_id !== 'string' ||
    typeof details.operation_id !== 'string' ||
    (details.kind !== 'SAVE' && details.kind !== 'SAVE_AS') ||
    typeof details.target_motion_id !== 'string' ||
    typeof details.started_at !== 'string' ||
    draftRevision === null ||
    targetMotionRevision === null ||
    (details.expected_motion_revision !== null && expectedMotionRevision === null) ||
    (details.actual_target_revision !== null &&
      details.actual_target_revision !== undefined &&
      actualTargetRevision === null)
  ) return null;
  return {
    reason: details.reason as StudioFormalSaveRecovery['reason'],
    draftId: details.draft_id,
    draftRevision,
    operationId: details.operation_id,
    kind: details.kind,
    targetMotionId: details.target_motion_id,
    targetMotionRevision,
    expectedMotionRevision,
    actualTargetRevision,
    startedAt: details.started_at,
  };
}

function id(): string {
  return globalThis.crypto.randomUUID();
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : '编排操作失败。';
}

function revisionDetails(error: ApiError): { actual: number | null; expected: number | null } {
  if (typeof error.details !== 'object' || error.details === null) {
    return { actual: null, expected: null };
  }
  const details = error.details as Record<string, unknown>;
  return {
    actual: typeof details.actual_revision === 'number' ? details.actual_revision : null,
    expected: typeof details.expected_revision === 'number' ? details.expected_revision : null,
  };
}

function revisionConflictEntity(error: unknown): StudioConflict['scope'] | null {
  if (!(error instanceof ApiError) || error.status !== 409 || error.code !== 'REVISION_CONFLICT') {
    return null;
  }
  const details = record(error.details);
  if (details?.entity === 'MotionDraft') return 'draft';
  if (details?.entity === 'Motion') return 'motion';
  return null;
}

function hasFormalSaveConflictReason(error: unknown): boolean {
  if (!(error instanceof ApiError) || error.status !== 409 || error.code !== 'REVISION_CONFLICT') {
    return false;
  }
  const reason = record(error.details)?.reason;
  return typeof reason === 'string' && reason.startsWith('FORMAL_SAVE_');
}

function documentFromDraft(draft: MotionDraft): StudioDraftDocument {
  const document = motionKeyframesToStudioDocument(draft.keyframes, {
    name: draft.name,
    description: draft.description,
    robotVariant: draft.robot_variant,
    tags: draft.tags,
    playbackDefaults: draft.playback_defaults,
  });
  const persistedDefaults = draft.editor_metadata.default_edges;
  if (!persistedDefaults) return document;
  const defaultIds = new Set(
    persistedDefaults.map((edge) => `${edge.from_keyframe_id}->${edge.to_keyframe_id}`),
  );
  return {
    ...document,
    edges: document.edges.map((edge) => ({
      ...edge,
      isDefault: defaultIds.has(`${edge.fromFrameId}->${edge.toFrameId}`),
    })),
  };
}

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, nested]) => [key, canonical(nested)]),
    );
  }
  return value;
}

function documentSignature(document: StudioDraftDocument): string {
  return JSON.stringify(canonical(document));
}

function formalDocumentSignature(document: StudioDraftDocument): string {
  return JSON.stringify(canonical({
    name: document.name,
    description: document.description,
    robotVariant: document.robotVariant,
    keyframes: studioDocumentToDraftKeyframes(document),
    tags: document.tags,
    playbackDefaults: document.playbackDefaults,
  }));
}

function persistedSignature(
  document: StudioDraftDocument,
  metadata: MotionDraftEditorMetadata,
): string {
  return JSON.stringify(canonical({ document, metadata }));
}

function editorMetadata(
  selectedFrameId: string | null,
  playheadS: number,
  timelineZoom: number,
  timelineScrollS: number,
  document?: StudioDraftDocument,
): MotionDraftEditorMetadata {
  return {
    selected_keyframe_id: selectedFrameId,
    playhead_s: playheadS,
    timeline_zoom: timelineZoom,
    timeline_scroll_s: timelineScrollS,
    default_edges: document?.edges
      .filter((edge) => edge.isDefault)
      .map((edge) => ({
        from_keyframe_id: edge.fromFrameId,
        to_keyframe_id: edge.toFrameId,
      })) ?? [],
  };
}

function autosaveLabel(status: StudioEditorState['autosave']): string {
  if (status.status === 'saving') return '正在自动保存草稿…';
  if (status.status === 'error') return `自动保存失败 · ${status.error ?? '需要重试'}`;
  if (status.status === 'saved' && status.lastSavedAt) {
    return `草稿已自动保存 · ${new Date(status.lastSavedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
  }
  return status.persistedRevision ? '草稿自动保存就绪' : '正在创建草稿…';
}

export function useStudioDraftSession({
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
}: UseStudioDraftSessionOptions) {
  const [draft, setDraft] = useState<MotionDraft | null>(null);
  const [savedMotion, setSavedMotion] = useState<MotionEntity | null>(null);
  const [formalBaseline, setFormalBaseline] = useState<string | null>(null);
  const [initializing, setInitializing] = useState(true);
  const [action, setAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [recoveryMessage, setRecoveryMessage] = useState<string | null>(null);
  const [conflict, setConflict] = useState<StudioConflict | null>(null);
  const [draftPreflight, setDraftPreflight] = useState<TrajectoryPreflightReport | null>(null);
  const [draftValidation, setDraftValidation] = useState<MotionDraftValidation | null>(null);
  const [preview, setPreview] = useState<TrajectoryPreview | null>(null);
  const [conflictAcknowledged, setConflictAcknowledged] = useState(false);
  const [formalSaveRecoveryState, setFormalSaveRecoveryState] = useState<StudioFormalSaveRecovery | null>(null);
  const entryKey = `${entry.draftId ?? ''}|${entry.motionId ?? ''}|${entry.poseId ?? ''}`;
  const [loadedEntryKey, setLoadedEntryKey] = useState<string | null>(null);
  const initializationCompleteRef = useRef(false);
  const initializationEntryRef = useRef<string | null>(null);
  const initializationGenerationRef = useRef(0);
  const mounted = useRef(true);
  const editorRef = useRef(editor);
  const draftRef = useRef(draft);
  const metadataRef = useRef<MotionDraftEditorMetadata>(editorMetadata(null, 0, 1, 0));
  const persistedSignatureRef = useRef<string | null>(null);
  const persistPromiseRef = useRef<Promise<MotionDraft> | null>(null);
  const persistContextRef = useRef<{ draftId: string; generation: number } | null>(null);
  const conflictRef = useRef<StudioConflict | null>(null);
  const workspaceGenerationRef = useRef(0);

  editorRef.current = editor;
  draftRef.current = draft;
  metadataRef.current = editorMetadata(
    editor.selectedFrameId,
    playheadS,
    timelineZoom,
    timelineScrollS,
    editor.document,
  );
  conflictRef.current = conflict;

  const clearCompiledState = useCallback(() => {
    setDraftValidation(null);
    setDraftPreflight(null);
    setPreview(null);
  }, []);

  const loadDraft = useCallback((loadedDraft: MotionDraft, sourceMotion: MotionEntity | null) => {
    workspaceGenerationRef.current += 1;
    const document = documentFromDraft(loadedDraft);
    const metadata = loadedDraft.editor_metadata;
    setDraft(loadedDraft);
    draftRef.current = loadedDraft;
    dispatch({
      type: 'document/load',
      document,
      persistedRevision: loadedDraft.revision,
      selectedFrameId: metadata.selected_keyframe_id,
    });
    setPlayheadS(metadata.playhead_s);
    setTimelineZoom(metadata.timeline_zoom);
    setTimelineScrollS(metadata.timeline_scroll_s);
    metadataRef.current = metadata;
    persistedSignatureRef.current = persistedSignature(document, metadata);
    setSavedMotion(sourceMotion);
    setFormalBaseline(sourceMotion ? formalDocumentSignature(motionToStudioDocument(sourceMotion)) : null);
    clearCompiledState();
    setError(null);
    setFormalSaveRecoveryState(null);
    setConflict(null);
    setConflictAcknowledged(false);
  }, [clearCompiledState, dispatch, setPlayheadS, setTimelineScrollS, setTimelineZoom]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (runtime.backend !== 'connected') return;
    if (
      entry.draftId &&
      draftRef.current?.id === entry.draftId &&
      initializationCompleteRef.current
    ) {
      initializationEntryRef.current = entryKey;
      setLoadedEntryKey(entryKey);
      return;
    }
    if (
      initializationEntryRef.current === entryKey &&
      initializationCompleteRef.current
    ) return;
    const entryChanged = initializationEntryRef.current !== entryKey;
    initializationEntryRef.current = entryKey;
    initializationCompleteRef.current = false;
    if (entryChanged) {
      workspaceGenerationRef.current += 1;
      setInitializing(true);
      setDraft(null);
      draftRef.current = null;
      setSavedMotion(null);
      setFormalBaseline(null);
      setLoadedEntryKey(null);
      setRecoveryMessage(null);
      setError(null);
      setFormalSaveRecoveryState(null);
    }
    const generation = initializationGenerationRef.current + 1;
    initializationGenerationRef.current = generation;
    const controller = new AbortController();
    const current = () => (
      mounted.current &&
      !controller.signal.aborted &&
      initializationGenerationRef.current === generation
    );
    const finish = (loadedDraft: MotionDraft, sourceMotion: MotionEntity | null) => {
      if (!current()) return false;
      initializationCompleteRef.current = true;
      loadDraft(loadedDraft, sourceMotion);
      setLoadedEntryKey(entryKey);
      return true;
    };
    void (async () => {
      try {
        if (entry.draftId) {
          const recovered = await getMotionDraft(entry.draftId, controller.signal);
          if (!current()) return;
          let source: MotionEntity | null = null;
          if (recovered.source_motion_id) {
            try {
              source = await getMotion(recovered.source_motion_id, controller.signal);
            } catch {
              source = null;
            }
          }
          if (!finish(recovered, source)) return;
          setRecoveryMessage('已恢复指定的自动保存草稿，没有覆盖任何正式运动。');
          return;
        }

        if (entry.motionId) {
          const motion = await getMotion(entry.motionId, controller.signal);
          if (!current()) return;
          const created = await createMotionDraftFromMotion(motion.id, motion.revision);
          if (!finish(created, motion)) return;
          setRecoveryMessage(`已将“${motion.name}”作为自动保存的工作草稿打开。`);
          return;
        }

        if (entry.poseId) {
          const pose = await getPose(entry.poseId, controller.signal);
          if (!current()) return;
          const created = await createMotionDraft({
            name: `${pose.name} Motion`,
            robot_variant: pose.snapshot.robot_variant,
            keyframes: [{
              id: id(),
              label: pose.name,
              pose_snapshot: pose.snapshot,
              source_pose_id: pose.id,
              hold_s: 0,
              incoming_transition: null,
            }],
            editor_metadata: editorMetadata(null, 0, 1, 0),
          });
          if (!finish(created, null)) return;
          setRecoveryMessage(`已将机位“${pose.name}”添加到新草稿。`);
          return;
        }

        const available = await getMotionDrafts(1, 20, controller.signal);
        if (!current()) return;
        if (available.items[0]) {
          const recovered = await getMotionDraft(available.items[0].id, controller.signal);
          if (!current()) return;
          let source: MotionEntity | null = null;
          if (recovered.source_motion_id) {
            try {
              source = await getMotion(recovered.source_motion_id, controller.signal);
            } catch {
              source = null;
            }
          }
          if (!finish(recovered, source)) return;
          setRecoveryMessage(`崩溃恢复已从草稿版本 ${recovered.revision} 恢复“${recovered.name}”。`);
          return;
        }

        const variant: RobotVariant = runtime.robot?.variant ?? 'V2';
        const created = await createMotionDraft({
          name: '未命名运动',
          robot_variant: variant,
          editor_metadata: editorMetadata(null, 0, 1, 0),
        });
        if (!finish(created, null)) return;
      } catch (caught) {
        if (current()) {
          const recovery = formalSaveRecovery(caught);
          if (recovery) {
            setFormalSaveRecoveryState(recovery);
            setError(null);
          } else {
            setError(message(caught));
          }
        }
      } finally {
        if (current()) setInitializing(false);
      }
    })();
    return () => controller.abort();
  }, [entry.draftId, entry.motionId, entry.poseId, entryKey, loadDraft, runtime.backend, runtime.robot?.variant]);

  const releaseFormalSaveRecovery = useCallback(async () => {
    const recovery = formalSaveRecoveryState;
    if (!recovery) return;
    setAction('abandon-save-intent');
    setError(null);
    try {
      const abandoned = await abandonMotionDraftSaveIntent(recovery.draftId, {
        expected_revision: recovery.draftRevision,
        operation_id: recovery.operationId,
        confirm: 'ABANDON_FORMAL_SAVE',
      });
      let reloaded = abandoned;
      try {
        reloaded = await getMotionDraft(recovery.draftId);
      } catch (caught) {
        const nextRecovery = formalSaveRecovery(caught);
        if (nextRecovery) {
          setFormalSaveRecoveryState(nextRecovery);
          throw caught;
        }
        // The successful abandon response is a complete authoritative draft;
        // retain availability if only the follow-up refresh transport fails.
      }
      let source: MotionEntity | null = null;
      if (reloaded.source_motion_id) {
        try {
          source = await getMotion(reloaded.source_motion_id);
        } catch {
          source = null;
        }
      }
      initializationCompleteRef.current = true;
      initializationEntryRef.current = entryKey;
      loadDraft(reloaded, source);
      setLoadedEntryKey(entryKey);
      setFormalSaveRecoveryState(null);
      setRecoveryMessage('已解除草稿恢复标记，目标运动没有发生变化。');
    } catch (caught) {
      setError(message(caught));
    } finally {
      setAction((currentAction) => currentAction === 'abandon-save-intent' ? null : currentAction);
    }
  }, [entryKey, formalSaveRecoveryState, loadDraft]);

  const recordSaveConflict = useCallback((
    caught: unknown,
    expectedRevisions: { draft: number | null; motion: number | null },
    allowMotion: boolean,
  ) => {
    // Active-session recovery markers must remain generic and fail closed.
    // The initialization-only recovery gate is the sole path allowed to abandon one.
    if (hasFormalSaveConflictReason(caught)) return false;
    const scope = revisionConflictEntity(caught);
    if (!scope || (scope === 'motion' && !allowMotion)) return false;
    const revisions = revisionDetails(caught as ApiError);
    setConflict({
      scope,
      actualRevision: revisions.actual,
      expectedRevision: revisions.expected ?? expectedRevisions[scope],
    });
    setConflictAcknowledged(false);
    return true;
  }, []);

  const persistWorkspace = useCallback(async (): Promise<MotionDraft> => {
    const active = persistPromiseRef.current;
    if (active) {
      const activeContext = persistContextRef.current;
      try {
        await active;
      } catch (caught) {
        const failedCurrentWorkspace = Boolean(
          activeContext &&
          activeContext.generation === workspaceGenerationRef.current &&
          activeContext.draftId === draftRef.current?.id,
        );
        if (failedCurrentWorkspace) throw caught;
      }
      if (conflictRef.current) throw new Error('请先解决版本冲突，再自动保存。');
      const current = draftRef.current;
      if (!current) throw new Error('草稿尚未就绪。');
      const currentSignature = persistedSignature(editorRef.current.document, metadataRef.current);
      if (currentSignature !== persistedSignatureRef.current) return persistWorkspace();
      return current;
    }

    const current = draftRef.current;
    if (!current) throw new Error('草稿尚未就绪。');
    const document = editorRef.current.document;
    const metadata = metadataRef.current;
    const signature = persistedSignature(document, metadata);
    if (signature === persistedSignatureRef.current) return current;

    const token = id();
    const generation = workspaceGenerationRef.current;
    const persistedDraftId = current.id;
    const context = { draftId: persistedDraftId, generation };
    dispatch({ type: 'autosave/start', token });
    const operation = updateMotionDraft(current.id, {
      expected_revision: current.revision,
      name: document.name.trim() || '未命名运动',
      description: document.description,
      robot_variant: document.robotVariant,
      keyframes: studioDocumentToDraftKeyframes(document),
      playback_defaults: document.playbackDefaults,
      tags: [...document.tags],
      editor_metadata: metadata,
    }).then((updated) => {
      if (!mounted.current) return updated;
      if (
        generation !== workspaceGenerationRef.current ||
        draftRef.current?.id !== persistedDraftId
      ) {
        return updated;
      }
      setDraft(updated);
      draftRef.current = updated;
      const acknowledgedDocument = documentFromDraft(updated);
      persistedSignatureRef.current = persistedSignature(
        acknowledgedDocument,
        updated.editor_metadata,
      );
      dispatch({
        type: 'autosave/succeed',
        token,
        persistedRevision: updated.revision,
        savedAt: updated.updated_at,
        acknowledgedDocument,
      });
      return updated;
    }).catch((caught: unknown) => {
      if (
        mounted.current &&
        generation === workspaceGenerationRef.current &&
        draftRef.current?.id === persistedDraftId
      ) {
        dispatch({ type: 'autosave/fail', token, error: message(caught) });
        recordSaveConflict(caught, { draft: current.revision, motion: null }, false);
      }
      throw caught;
    }).finally(() => {
      if (persistContextRef.current === context) {
        persistPromiseRef.current = null;
        persistContextRef.current = null;
      }
    });
    persistContextRef.current = context;
    persistPromiseRef.current = operation;
    return operation;
  }, [dispatch, recordSaveConflict]);

  const persistenceSignature = persistedSignature(editor.document, metadataRef.current);
  useEffect(() => {
    if (
      !draft ||
      initializing ||
      conflict ||
      runtime.backend !== 'connected' ||
      persistenceSignature === persistedSignatureRef.current
    ) return;
    const timer = window.setTimeout(() => {
      void persistWorkspace().catch(() => undefined);
    }, AUTOSAVE_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [conflict, draft, initializing, persistWorkspace, persistenceSignature, runtime.backend]);

  const recordDraftConflict = useCallback((
    caught: unknown,
    expectedRevision: number | null,
  ) => recordSaveConflict(caught, {
    draft: expectedRevision,
    motion: null,
  }, false), [recordSaveConflict]);
  const getWorkspaceGeneration = useCallback(() => workspaceGenerationRef.current, []);

  const validate = useCallback(async () => {
    const actionName = 'validate';
    let expectedDraftRevision = draftRef.current?.revision ?? null;
    setAction(actionName);
    setError(null);
    try {
      const persisted = await persistWorkspace();
      expectedDraftRevision = persisted.revision;
      const generation = workspaceGenerationRef.current;
      const signature = documentSignature(editorRef.current.document);
      const result = await validateMotionDraft(persisted.id, persisted.revision);
      if (
        generation !== workspaceGenerationRef.current ||
        signature !== documentSignature(editorRef.current.document)
      ) return;
      setDraftValidation(result);
    } catch (caught) {
      if (!recordSaveConflict(caught, {
        draft: expectedDraftRevision,
        motion: null,
      }, false)) setError(message(caught));
    } finally {
      setAction((currentAction) => currentAction === actionName ? null : currentAction);
    }
  }, [persistWorkspace, recordSaveConflict]);

  const compile = useCallback(async () => {
    const actionName = 'compile';
    let expectedDraftRevision = draftRef.current?.revision ?? null;
    setAction(actionName);
    setError(null);
    try {
      const persisted = await persistWorkspace();
      expectedDraftRevision = persisted.revision;
      const generation = workspaceGenerationRef.current;
      const signature = documentSignature(editorRef.current.document);
      const result = await compileMotionDraft(persisted.id, {
        expected_revision: persisted.revision,
        sample_rate_hz: 20,
      });
      if (
        generation !== workspaceGenerationRef.current ||
        signature !== documentSignature(editorRef.current.document)
      ) return;
      setDraftPreflight(result.preflight);
      setPreview(result.preview);
    } catch (caught) {
      if (!recordSaveConflict(caught, {
        draft: expectedDraftRevision,
        motion: null,
      }, false)) setError(message(caught));
    } finally {
      setAction((currentAction) => currentAction === actionName ? null : currentAction);
    }
  }, [persistWorkspace, recordSaveConflict]);

  const save = useCallback(async () => {
    const actionName = 'save';
    let submittedDraft: MotionDraft | null = null;
    setAction(actionName);
    setError(null);
    try {
      let persisted: MotionDraft;
      try {
        persisted = await persistWorkspace();
        submittedDraft = persisted;
      } catch (caught) {
        if (!recordSaveConflict(caught, {
          draft: draftRef.current?.revision ?? null,
          motion: null,
        }, false)) setError(message(caught));
        return;
      }
      const generation = workspaceGenerationRef.current;
      const signature = documentSignature(editorRef.current.document);
      const result = await saveMotionDraft(persisted.id, {
        expected_revision: persisted.revision,
        expected_source_revision: persisted.source_motion_revision,
        sample_rate_hz: 20,
      });
      if (generation !== workspaceGenerationRef.current) return;
      const currentSignature = documentSignature(editorRef.current.document);
      if (currentSignature === signature) {
        loadDraft(result.draft, result.motion);
      } else {
        const savedDocument = documentFromDraft(result.draft);
        setDraft(result.draft);
        draftRef.current = result.draft;
        persistedSignatureRef.current = persistedSignature(
          savedDocument,
          result.draft.editor_metadata,
        );
        setSavedMotion(result.motion);
        setFormalBaseline(formalDocumentSignature(motionToStudioDocument(result.motion)));
        setConflict(null);
        setConflictAcknowledged(false);
      }
      setDraftPreflight(result.preflight);
      setFormalBaseline(formalDocumentSignature(motionToStudioDocument(result.motion)));
      setRecoveryMessage(currentSignature === signature
        ? `已将正式运动“${result.motion.name}”保存为版本 ${result.motion.revision}。`
        : `已保存提交的运动版本 ${result.motion.revision}；较新的本地修改仍保留在自动保存草稿中。`);
    } catch (caught) {
      if (!recordSaveConflict(caught, {
        draft: submittedDraft?.revision ?? draftRef.current?.revision ?? null,
        motion: submittedDraft?.source_motion_revision ?? draftRef.current?.source_motion_revision ?? null,
      }, true)) {
        setError(message(caught));
      }
    } finally {
      setAction((currentAction) => currentAction === actionName ? null : currentAction);
    }
  }, [loadDraft, persistWorkspace, recordSaveConflict]);

  const saveAs = useCallback(async (name: string) => {
    const actionName = 'save-as';
    let submittedDraft: MotionDraft | null = null;
    setAction(actionName);
    setError(null);
    try {
      let persisted: MotionDraft;
      const activeConflict = conflictRef.current;
      if (activeConflict) {
        const conflictingDraft = draftRef.current;
        if (!conflictingDraft) throw new Error('草稿尚未就绪。');
        const localDocument = editorRef.current.document;
        const localMetadata = metadataRef.current;
        const latest = await getMotionDraft(conflictingDraft.id);
        const forked = await forkMotionDraft(conflictingDraft.id, {
          expected_revision: latest.revision,
        });
        persisted = await updateMotionDraft(forked.id, {
          expected_revision: forked.revision,
          name: localDocument.name.trim() || '未命名运动',
          description: localDocument.description,
          robot_variant: localDocument.robotVariant,
          keyframes: studioDocumentToDraftKeyframes(localDocument),
          playback_defaults: localDocument.playbackDefaults,
          tags: [...localDocument.tags],
          editor_metadata: localMetadata,
        });
        loadDraft(persisted, savedMotion);
      } else {
        persisted = await persistWorkspace();
      }
      submittedDraft = persisted;
      const result = await saveMotionDraftAs(persisted.id, {
        expected_revision: persisted.revision,
        name: name.trim(),
        sample_rate_hz: 20,
      });
      loadDraft(result.draft, result.motion);
      setDraftPreflight(result.preflight);
      setFormalBaseline(formalDocumentSignature(motionToStudioDocument(result.motion)));
      setRecoveryMessage(`已将新的正式运动“${result.motion.name}”保存为新 UUID。`);
      setConflict(null);
      return true;
    } catch (caught) {
      recordSaveConflict(caught, {
        draft: submittedDraft?.revision ?? draftRef.current?.revision ?? null,
        motion: null,
      }, false);
      setError(message(caught));
      return false;
    } finally {
      setAction((currentAction) => currentAction === actionName ? null : currentAction);
    }
  }, [loadDraft, persistWorkspace, recordSaveConflict, savedMotion]);

  const reloadConflict = useCallback(async () => {
    const activeConflict = conflict;
    const currentDraft = draftRef.current;
    if (!activeConflict || !currentDraft) return;
    setAction('reload');
    setError(null);
    try {
      if (activeConflict.scope === 'draft') {
        const latest = await getMotionDraft(currentDraft.id);
        let source: MotionEntity | null = null;
        if (latest.source_motion_id) {
          try {
            source = await getMotion(latest.source_motion_id);
          } catch {
            source = null;
          }
        }
        loadDraft(latest, source);
        setRecoveryMessage(`已重新加载草稿版本 ${latest.revision}，并丢弃发生冲突的本地修改。`);
      } else if (currentDraft.source_motion_id) {
        const latestMotion = await getMotion(currentDraft.source_motion_id);
        const freshDraft = await createMotionDraftFromMotion(latestMotion.id, latestMotion.revision);
        loadDraft(freshDraft, latestMotion);
        setRecoveryMessage(`已将“${latestMotion.name}”版本 ${latestMotion.revision} 重新加载到新草稿。`);
      }
      setConflict(null);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setAction((currentAction) => currentAction === 'reload' ? null : currentAction);
    }
  }, [conflict, loadDraft]);

  const createBlankDraft = useCallback(async () => {
    setAction('new');
    setError(null);
    try {
      await persistWorkspace();
      const variant = runtime.robot?.variant ?? editorRef.current.document.robotVariant;
      const created = await createMotionDraft({
        name: '未命名运动',
        robot_variant: variant,
        editor_metadata: editorMetadata(null, 0, 1, 0),
      });
      loadDraft(created, null);
      setRecoveryMessage('已创建空白自动保存草稿，之前的草稿仍可恢复。');
    } catch (caught) {
      setError(message(caught));
    } finally {
      setAction((currentAction) => currentAction === 'new' ? null : currentAction);
    }
  }, [loadDraft, persistWorkspace, runtime.robot?.variant]);

  const formalDirty = formalBaseline === null
    ? formalDocumentSignature(editor.document) !== formalDocumentSignature(createEmptyStudioDocument({
        robotVariant: editor.document.robotVariant,
        name: '未命名运动',
      }))
    : formalDocumentSignature(editor.document) !== formalBaseline;

  return {
    action,
    autosaveLabel: runtime.backend !== 'connected'
      ? '草稿离线 · 自动保存已暂停'
      : conflict ? '草稿版本冲突 · 自动保存已暂停' : autosaveLabel(editor.autosave),
    clearCompiledState,
    clearConflict: () => setConflictAcknowledged(true),
    clearError: () => setError(null),
    clearRecoveryMessage: () => setRecoveryMessage(null),
    compile,
    conflict,
    conflictAcknowledged,
    createBlankDraft,
    draft,
    draftPreflight,
    draftValidation,
    error,
    formalDirty,
    formalSaveRecovery: formalSaveRecoveryState,
    getWorkspaceGeneration,
    initializing,
    loadedEntryKey,
    persistWorkspace,
    preview,
    recordDraftConflict,
    recoveryMessage,
    releaseFormalSaveRecovery,
    reloadConflict,
    save,
    saveAs,
    savedMotion,
    setAction,
    setError,
    setRecoveryMessage,
    validate,
    workspaceGeneration: workspaceGenerationRef.current,
  };
}

export type StudioDraftSession = ReturnType<typeof useStudioDraftSession>;
