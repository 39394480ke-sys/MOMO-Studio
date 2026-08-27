import type {
  CreateMotionKeyframeRequest,
  MotionEasing,
  MotionEntity,
  MotionKeyframe,
  MotionMode,
  MotionPlaybackDefaults,
  PoseEntity,
  PoseSnapshot,
  RobotVariant,
} from '../../api/types';

export const STUDIO_HISTORY_LIMIT = 100;
export const STUDIO_KEYFRAME_LIMIT = 1000;

export interface StudioEdgeSettings {
  durationS: number;
  motionMode: MotionMode;
  easing: MotionEasing;
}

export const DEFAULT_STUDIO_EDGE: Readonly<StudioEdgeSettings> = Object.freeze({
  durationS: 1,
  motionMode: 'JOINT',
  easing: 'SMOOTHSTEP',
});

export interface StudioFrame {
  id: string;
  label: string;
  poseSnapshot: PoseSnapshot;
  sourcePoseId: string | null;
  holdS: number;
}

/**
 * Transition settings live on a directed adjacency, not on either visual card.
 * This makes reorder behavior explicit and prevents transition settings from
 * silently following a keyframe to an unrelated neighbor.
 */
export interface StudioEdge extends StudioEdgeSettings {
  fromFrameId: string;
  toFrameId: string;
  /** True only while this adjacency still uses the explicit editor default. */
  isDefault: boolean;
}

export interface StudioDraftDocument {
  name: string;
  description: string;
  robotVariant: RobotVariant;
  frames: readonly StudioFrame[];
  edges: readonly StudioEdge[];
  tags: readonly string[];
  playbackDefaults: MotionPlaybackDefaults;
}

export type StudioAutosaveStatus = 'idle' | 'saving' | 'saved' | 'error';

export interface StudioAutosaveState {
  status: StudioAutosaveStatus;
  pendingToken: string | null;
  pendingDocument: StudioDraftDocument | null;
  persistedRevision: number | null;
  lastSavedAt: string | null;
  error: string | null;
}

export interface StudioEditorState {
  document: StudioDraftDocument;
  selectedFrameId: string | null;
  undoStack: readonly StudioDraftDocument[];
  redoStack: readonly StudioDraftDocument[];
  historyLimit: number;
  savedDocument: StudioDraftDocument;
  dirty: boolean;
  autosave: StudioAutosaveState;
}

export interface StudioPoseSource {
  id: PoseEntity['id'];
  name: PoseEntity['name'];
  snapshot: PoseEntity['snapshot'];
}

export type StudioInsertPosition = 'before' | 'after';

export type StudioEditorAction =
  | { type: 'selection/set'; frameId: string | null }
  | { type: 'document/set-name'; name: string }
  | { type: 'document/set-description'; description: string }
  | { type: 'document/set-tags'; tags: readonly string[] }
  | { type: 'document/set-playback-defaults'; playbackDefaults: MotionPlaybackDefaults }
  | { type: 'frame/add-before'; anchorFrameId: string | null; frame: StudioFrame }
  | { type: 'frame/add-after'; anchorFrameId: string | null; frame: StudioFrame }
  | {
      type: 'frame/add-pose';
      position: StudioInsertPosition;
      anchorFrameId: string | null;
      frameId: string;
      pose: StudioPoseSource;
    }
  | {
      type: 'frame/capture';
      position: StudioInsertPosition;
      anchorFrameId: string | null;
      frameId: string;
      label: string;
      snapshot: PoseSnapshot;
    }
  | {
      type: 'frame/replace-snapshot';
      frameId: string;
      snapshot: PoseSnapshot;
      sourcePoseId: string | null;
    }
  | { type: 'frame/delete'; frameId: string }
  | { type: 'frame/duplicate'; frameId: string; duplicateFrameId: string; label?: string }
  | { type: 'frame/reorder'; frameId: string; toIndex: number }
  | { type: 'frame/move'; frameId: string; direction: 'backward' | 'forward' }
  | { type: 'frame/set-label'; frameId: string; label: string }
  | { type: 'frame/set-hold'; frameId: string; holdS: number }
  | { type: 'edge/set-duration'; toFrameId: string; durationS: number }
  | { type: 'edge/set-mode'; toFrameId: string; motionMode: MotionMode }
  | { type: 'edge/set-easing'; toFrameId: string; easing: MotionEasing }
  | { type: 'history/undo' }
  | { type: 'history/redo' }
  | { type: 'autosave/start'; token: string }
  | {
      type: 'autosave/succeed';
      token: string;
      persistedRevision: number;
      savedAt: string;
      acknowledgedDocument?: StudioDraftDocument;
    }
  | { type: 'autosave/fail'; token: string; error: string }
  | { type: 'autosave/dismiss-error' }
  | {
      type: 'document/load';
      document: StudioDraftDocument;
      persistedRevision: number | null;
      selectedFrameId?: string | null;
    };

export interface CreateStudioFrameInput {
  id: string;
  label: string;
  poseSnapshot: PoseSnapshot;
  sourcePoseId?: string | null;
  holdS?: number;
}

export interface CreateEmptyStudioDocumentInput {
  robotVariant: RobotVariant;
  name?: string;
  description?: string;
  tags?: readonly string[];
  playbackDefaults?: MotionPlaybackDefaults;
}

export interface MotionKeyframeDocumentMetadata extends CreateEmptyStudioDocumentInput {
  name: string;
}

export interface CreateStudioEditorStateOptions {
  historyLimit?: number;
  persistedRevision?: number | null;
  selectedFrameId?: string | null;
}

export interface PlayableStudioValidation {
  valid: boolean;
  errors: readonly string[];
}

function cloneValue<T>(value: T): T {
  return structuredClone(value);
}

function edgeKey(fromFrameId: string, toFrameId: string): string {
  return `${fromFrameId}\u0000${toFrameId}`;
}

function makeDefaultEdge(fromFrameId: string, toFrameId: string): StudioEdge {
  return {
    fromFrameId,
    toFrameId,
    isDefault: true,
    ...DEFAULT_STUDIO_EDGE,
  };
}

function rebuildEdges(
  frames: readonly StudioFrame[],
  previousEdges: readonly StudioEdge[],
): readonly StudioEdge[] {
  if (frames.length < 2) return [];

  const previousByAdjacency = new Map(
    previousEdges.map((edge) => [edgeKey(edge.fromFrameId, edge.toFrameId), edge]),
  );
  const edges: StudioEdge[] = [];
  for (let index = 1; index < frames.length; index += 1) {
    const fromFrameId = frames[index - 1].id;
    const toFrameId = frames[index].id;
    const preserved = previousByAdjacency.get(edgeKey(fromFrameId, toFrameId));
    edges.push(preserved === undefined ? makeDefaultEdge(fromFrameId, toFrameId) : preserved);
  }
  return edges;
}

function normalizeDocument(document: StudioDraftDocument): StudioDraftDocument {
  const frames = document.frames.map((frame) => createStudioFrame({
    id: frame.id,
    label: frame.label,
    poseSnapshot: frame.poseSnapshot,
    sourcePoseId: frame.sourcePoseId,
    holdS: frame.holdS,
  }));
  const suppliedEdges = document.edges.map((edge) => ({ ...edge }));
  return {
    name: document.name,
    description: document.description,
    robotVariant: document.robotVariant,
    frames,
    edges: rebuildEdges(frames, suppliedEdges),
    tags: [...document.tags],
    playbackDefaults: { ...document.playbackDefaults },
  };
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, nested]) => [key, canonicalize(nested)]),
    );
  }
  return value;
}

function documentsEqual(left: StudioDraftDocument, right: StudioDraftDocument): boolean {
  if (left === right) return true;
  return JSON.stringify(canonicalize(left)) === JSON.stringify(canonicalize(right));
}

function selectionIfPresent(
  document: StudioDraftDocument,
  selectedFrameId: string | null,
): string | null {
  if (selectedFrameId === null) return null;
  return document.frames.some((frame) => frame.id === selectedFrameId) ? selectedFrameId : null;
}

function boundedHistoryLimit(value: number | undefined): number {
  if (value === undefined || !Number.isFinite(value)) return STUDIO_HISTORY_LIMIT;
  return Math.max(1, Math.min(500, Math.floor(value)));
}

function afterDocumentEdit(autosave: StudioAutosaveState): StudioAutosaveState {
  if (autosave.status !== 'saved') return autosave;
  return { ...autosave, status: 'idle' };
}

function commitDocument(
  state: StudioEditorState,
  nextDocument: StudioDraftDocument,
  selectedFrameId = state.selectedFrameId,
): StudioEditorState {
  if (documentsEqual(nextDocument, state.document)) {
    const nextSelection = selectionIfPresent(state.document, selectedFrameId);
    return nextSelection === state.selectedFrameId
      ? state
      : { ...state, selectedFrameId: nextSelection };
  }

  const nextUndoStack = [...state.undoStack, state.document].slice(-state.historyLimit);
  return {
    ...state,
    document: nextDocument,
    selectedFrameId: selectionIfPresent(nextDocument, selectedFrameId),
    undoStack: nextUndoStack,
    redoStack: [],
    dirty: !documentsEqual(nextDocument, state.savedDocument),
    autosave: afterDocumentEdit(state.autosave),
  };
}

function withFrames(
  document: StudioDraftDocument,
  frames: readonly StudioFrame[],
): StudioDraftDocument {
  return {
    ...document,
    frames,
    edges: rebuildEdges(frames, document.edges),
  };
}

function insertFrame(
  state: StudioEditorState,
  position: StudioInsertPosition,
  anchorFrameId: string | null,
  frame: StudioFrame,
): StudioEditorState {
  if (state.document.frames.length >= STUDIO_KEYFRAME_LIMIT) return state;
  if (state.document.frames.some((candidate) => candidate.id === frame.id)) return state;

  let insertionIndex: number;
  if (anchorFrameId === null) {
    insertionIndex = position === 'before' ? 0 : state.document.frames.length;
  } else {
    const anchorIndex = state.document.frames.findIndex((candidate) => candidate.id === anchorFrameId);
    if (anchorIndex < 0) return state;
    insertionIndex = position === 'before' ? anchorIndex : anchorIndex + 1;
  }

  const detachedFrame = createStudioFrame({
    id: frame.id,
    label: frame.label,
    poseSnapshot: frame.poseSnapshot,
    sourcePoseId: frame.sourcePoseId,
    holdS: frame.holdS,
  });
  const frames = [...state.document.frames];
  frames.splice(insertionIndex, 0, detachedFrame);
  return commitDocument(state, withFrames(state.document, frames), detachedFrame.id);
}

function updateFrame(
  state: StudioEditorState,
  frameId: string,
  update: (frame: StudioFrame) => StudioFrame,
): StudioEditorState {
  const index = state.document.frames.findIndex((frame) => frame.id === frameId);
  if (index < 0) return state;
  const frames = [...state.document.frames];
  frames[index] = update(frames[index]);
  return commitDocument(state, { ...state.document, frames });
}

function updateIncomingEdge(
  state: StudioEditorState,
  toFrameId: string,
  update: (edge: StudioEdge) => StudioEdge,
): StudioEditorState {
  const index = state.document.edges.findIndex((edge) => edge.toFrameId === toFrameId);
  if (index < 0) return state;
  const edges = [...state.document.edges];
  edges[index] = update(edges[index]);
  return commitDocument(state, { ...state.document, edges });
}

export function createStudioFrame(input: CreateStudioFrameInput): StudioFrame {
  return {
    id: input.id,
    label: input.label,
    poseSnapshot: cloneValue(input.poseSnapshot),
    sourcePoseId: input.sourcePoseId ?? null,
    holdS: input.holdS ?? 0,
  };
}

export function createEmptyStudioDocument(
  input: CreateEmptyStudioDocumentInput,
): StudioDraftDocument {
  return {
    name: input.name ?? '',
    description: input.description ?? '',
    robotVariant: input.robotVariant,
    frames: [],
    edges: [],
    tags: [...(input.tags ?? [])],
    playbackDefaults: { ...(input.playbackDefaults ?? { loop: false, speed_multiplier: 1 }) },
  };
}

export function createStudioEditorState(
  document: StudioDraftDocument,
  options: CreateStudioEditorStateOptions = {},
): StudioEditorState {
  const normalized = normalizeDocument(document);
  return {
    document: normalized,
    selectedFrameId: selectionIfPresent(normalized, options.selectedFrameId ?? null),
    undoStack: [],
    redoStack: [],
    historyLimit: boundedHistoryLimit(options.historyLimit),
    savedDocument: normalized,
    dirty: false,
    autosave: {
      status: 'idle',
      pendingToken: null,
      pendingDocument: null,
      persistedRevision: options.persistedRevision ?? null,
      lastSavedAt: null,
      error: null,
    },
  };
}

export function studioEditorReducer(
  state: StudioEditorState,
  action: StudioEditorAction,
): StudioEditorState {
  switch (action.type) {
    case 'selection/set': {
      const selectedFrameId = selectionIfPresent(state.document, action.frameId);
      return selectedFrameId === state.selectedFrameId ? state : { ...state, selectedFrameId };
    }
    case 'document/set-name':
      return commitDocument(state, { ...state.document, name: action.name });
    case 'document/set-description':
      return commitDocument(state, { ...state.document, description: action.description });
    case 'document/set-tags':
      return commitDocument(state, { ...state.document, tags: [...action.tags] });
    case 'document/set-playback-defaults':
      return commitDocument(state, {
        ...state.document,
        playbackDefaults: { ...action.playbackDefaults },
      });
    case 'frame/add-before':
      return insertFrame(state, 'before', action.anchorFrameId, action.frame);
    case 'frame/add-after':
      return insertFrame(state, 'after', action.anchorFrameId, action.frame);
    case 'frame/add-pose':
      return insertFrame(
        state,
        action.position,
        action.anchorFrameId,
        createStudioFrame({
          id: action.frameId,
          label: action.pose.name,
          poseSnapshot: action.pose.snapshot,
          sourcePoseId: action.pose.id,
        }),
      );
    case 'frame/capture':
      return insertFrame(
        state,
        action.position,
        action.anchorFrameId,
        createStudioFrame({
          id: action.frameId,
          label: action.label,
          poseSnapshot: action.snapshot,
          sourcePoseId: null,
        }),
      );
    case 'frame/replace-snapshot':
      return updateFrame(state, action.frameId, (frame) => ({
        ...frame,
        poseSnapshot: cloneValue(action.snapshot),
        sourcePoseId: action.sourcePoseId,
      }));
    case 'frame/delete': {
      const removedIndex = state.document.frames.findIndex((frame) => frame.id === action.frameId);
      if (removedIndex < 0) return state;
      const frames = state.document.frames.filter((frame) => frame.id !== action.frameId);
      let selection = state.selectedFrameId;
      if (selection === action.frameId) {
        selection = frames[Math.min(removedIndex, frames.length - 1)]?.id ?? null;
      }
      return commitDocument(state, withFrames(state.document, frames), selection);
    }
    case 'frame/duplicate': {
      const sourceIndex = state.document.frames.findIndex((frame) => frame.id === action.frameId);
      if (sourceIndex < 0) return state;
      const source = state.document.frames[sourceIndex];
      return insertFrame(
        state,
        'after',
        source.id,
        createStudioFrame({
          id: action.duplicateFrameId,
          label: action.label ?? `${source.label} copy`,
          poseSnapshot: source.poseSnapshot,
          sourcePoseId: source.sourcePoseId,
          holdS: source.holdS,
        }),
      );
    }
    case 'frame/reorder': {
      const sourceIndex = state.document.frames.findIndex((frame) => frame.id === action.frameId);
      if (sourceIndex < 0 || state.document.frames.length < 2) return state;
      const destination = Math.max(0, Math.min(state.document.frames.length - 1, action.toIndex));
      if (sourceIndex === destination) return state;
      const frames = [...state.document.frames];
      const [moved] = frames.splice(sourceIndex, 1);
      frames.splice(destination, 0, moved);
      return commitDocument(state, withFrames(state.document, frames));
    }
    case 'frame/move': {
      const sourceIndex = state.document.frames.findIndex((frame) => frame.id === action.frameId);
      if (sourceIndex < 0) return state;
      const delta = action.direction === 'backward' ? -1 : 1;
      return studioEditorReducer(state, {
        type: 'frame/reorder',
        frameId: action.frameId,
        toIndex: sourceIndex + delta,
      });
    }
    case 'frame/set-label':
      return updateFrame(state, action.frameId, (frame) => ({ ...frame, label: action.label }));
    case 'frame/set-hold':
      if (!Number.isFinite(action.holdS) || action.holdS < 0 || action.holdS > 600) return state;
      return updateFrame(state, action.frameId, (frame) => ({ ...frame, holdS: action.holdS }));
    case 'edge/set-duration':
      if (
        !Number.isFinite(action.durationS)
        || action.durationS <= 0
        || action.durationS > 600
      ) return state;
      return updateIncomingEdge(state, action.toFrameId, (edge) => ({
        ...edge,
        durationS: action.durationS,
        isDefault: false,
      }));
    case 'edge/set-mode':
      return updateIncomingEdge(state, action.toFrameId, (edge) => ({
        ...edge,
        motionMode: action.motionMode,
        isDefault: false,
      }));
    case 'edge/set-easing':
      return updateIncomingEdge(state, action.toFrameId, (edge) => ({
        ...edge,
        easing: action.easing,
        isDefault: false,
      }));
    case 'history/undo': {
      const previous = state.undoStack.at(-1);
      if (previous === undefined) return state;
      return {
        ...state,
        document: previous,
        selectedFrameId: selectionIfPresent(previous, state.selectedFrameId),
        undoStack: state.undoStack.slice(0, -1),
        redoStack: [...state.redoStack, state.document].slice(-state.historyLimit),
        dirty: !documentsEqual(previous, state.savedDocument),
        autosave: afterDocumentEdit(state.autosave),
      };
    }
    case 'history/redo': {
      const next = state.redoStack.at(-1);
      if (next === undefined) return state;
      return {
        ...state,
        document: next,
        selectedFrameId: selectionIfPresent(next, state.selectedFrameId),
        undoStack: [...state.undoStack, state.document].slice(-state.historyLimit),
        redoStack: state.redoStack.slice(0, -1),
        dirty: !documentsEqual(next, state.savedDocument),
        autosave: afterDocumentEdit(state.autosave),
      };
    }
    case 'autosave/start':
      return {
        ...state,
        autosave: {
          ...state.autosave,
          status: 'saving',
          pendingToken: action.token,
          pendingDocument: state.document,
          error: null,
        },
      };
    case 'autosave/succeed': {
      if (state.autosave.pendingToken !== action.token || state.autosave.pendingDocument === null) {
        return state;
      }
      const pendingDocument = state.autosave.pendingDocument;
      const savedDocument = action.acknowledgedDocument === undefined
        ? pendingDocument
        : normalizeDocument(action.acknowledgedDocument);
      const document = documentsEqual(state.document, pendingDocument)
        ? savedDocument
        : state.document;
      return {
        ...state,
        document,
        selectedFrameId: selectionIfPresent(document, state.selectedFrameId),
        savedDocument,
        dirty: !documentsEqual(document, savedDocument),
        autosave: {
          status: 'saved',
          pendingToken: null,
          pendingDocument: null,
          persistedRevision: action.persistedRevision,
          lastSavedAt: action.savedAt,
          error: null,
        },
      };
    }
    case 'autosave/fail':
      if (state.autosave.pendingToken !== action.token) return state;
      return {
        ...state,
        autosave: {
          ...state.autosave,
          status: 'error',
          pendingToken: null,
          pendingDocument: null,
          error: action.error,
        },
      };
    case 'autosave/dismiss-error':
      if (state.autosave.status !== 'error') return state;
      return {
        ...state,
        autosave: { ...state.autosave, status: 'idle', error: null },
      };
    case 'document/load': {
      const loaded = normalizeDocument(action.document);
      return {
        document: loaded,
        selectedFrameId: selectionIfPresent(loaded, action.selectedFrameId ?? null),
        undoStack: [],
        redoStack: [],
        historyLimit: state.historyLimit,
        savedDocument: loaded,
        dirty: false,
        autosave: {
          status: 'idle',
          pendingToken: null,
          pendingDocument: null,
          persistedRevision: action.persistedRevision,
          lastSavedAt: null,
          error: null,
        },
      };
    }
  }
}

function transitionFromEdge(edge: StudioEdge) {
  return {
    duration_s: edge.durationS,
    motion_mode: edge.motionMode,
    easing: edge.easing,
  };
}

function edgeForFrame(document: StudioDraftDocument, frameIndex: number): StudioEdge | null {
  if (frameIndex === 0) return null;
  const fromFrameId = document.frames[frameIndex - 1].id;
  const toFrameId = document.frames[frameIndex].id;
  return document.edges.find(
    (edge) => edge.fromFrameId === fromFrameId && edge.toFrameId === toFrameId,
  ) ?? null;
}

export function motionKeyframesToStudioDocument(
  keyframes: readonly MotionKeyframe[],
  metadata: MotionKeyframeDocumentMetadata,
): StudioDraftDocument {
  const frames = keyframes.map((keyframe) => createStudioFrame({
    id: keyframe.id,
    label: keyframe.label,
    poseSnapshot: keyframe.pose_snapshot,
    sourcePoseId: keyframe.source_pose_id,
    holdS: keyframe.hold_s,
  }));
  const edges: StudioEdge[] = [];
  for (let index = 1; index < keyframes.length; index += 1) {
    const transition = keyframes[index].incoming_transition;
    const fromFrameId = frames[index - 1].id;
    const toFrameId = frames[index].id;
    edges.push(transition === null
      ? makeDefaultEdge(fromFrameId, toFrameId)
      : {
          fromFrameId,
          toFrameId,
          durationS: transition.duration_s,
          motionMode: transition.motion_mode,
          easing: transition.easing,
          // A persisted transition is an authored edge, even when its values
          // happen to equal today's editor default. Only a newly synthesized
          // adjacency is marked as default.
          isDefault: false,
        });
  }
  return {
    ...createEmptyStudioDocument(metadata),
    frames,
    edges,
  };
}

export function motionToStudioDocument(motion: MotionEntity): StudioDraftDocument {
  return motionKeyframesToStudioDocument(motion.keyframes, {
    name: motion.name,
    description: motion.description,
    robotVariant: motion.robot_variant,
    tags: motion.tags,
    playbackDefaults: motion.playback_defaults,
  });
}

/** Convert the 0+ frame editor model to the draft/backend keyframe shape. */
export function studioDocumentToDraftKeyframes(
  document: StudioDraftDocument,
): MotionKeyframe[] {
  return document.frames.map((frame, index) => {
    const edge = edgeForFrame(document, index);
    if (index > 0 && edge === null) {
      throw new Error(`关键帧 ${index + 1} 缺少进入过渡边。`);
    }
    return {
      id: frame.id,
      label: frame.label,
      pose_snapshot: cloneValue(frame.poseSnapshot),
      source_pose_id: frame.sourcePoseId,
      hold_s: frame.holdS,
      incoming_transition: edge === null ? null : transitionFromEdge(edge),
    };
  });
}

export function studioDocumentToCreateKeyframes(
  document: StudioDraftDocument,
): CreateMotionKeyframeRequest[] {
  return studioDocumentToDraftKeyframes(document).map((frame) => ({
    label: frame.label,
    pose_snapshot: cloneValue(frame.pose_snapshot),
    source_pose_id: frame.source_pose_id,
    hold_s: frame.hold_s,
    incoming_transition: frame.incoming_transition === null
      ? null
      : { ...frame.incoming_transition },
  }));
}

export function validatePlayableStudioDocument(
  document: StudioDraftDocument,
): PlayableStudioValidation {
  const errors: string[] = [];
  if (document.name.trim().length === 0) errors.push('必须填写运动名称。');
  if (document.frames.length < 2) errors.push('可播放的运动至少需要两个关键帧。');
  if (document.frames.length > 1000) errors.push('一个运动不能包含超过 1000 个关键帧。');

  const frameIds = new Set<string>();
  document.frames.forEach((frame, index) => {
    if (frameIds.has(frame.id)) errors.push(`关键帧 ${index + 1} 的 ID 重复。`);
    frameIds.add(frame.id);
    if (frame.label.trim().length === 0) errors.push(`关键帧 ${index + 1} 必须填写名称。`);
    if (!Number.isFinite(frame.holdS) || frame.holdS < 0 || frame.holdS > 600) {
      errors.push(`关键帧 ${index + 1} 的停留时长必须在 0 到 600 秒之间。`);
    }
    if (frame.poseSnapshot.robot_variant !== document.robotVariant) {
      errors.push(`关键帧 ${index + 1} 的机械臂型号与草稿不匹配。`);
    }
  });

  if (document.edges.length !== Math.max(0, document.frames.length - 1)) {
    errors.push('每一对相邻关键帧之间必须且只能有一条过渡边。');
  }
  for (let index = 1; index < document.frames.length; index += 1) {
    const edge = edgeForFrame(document, index);
    if (edge === null) {
      errors.push(`关键帧 ${index + 1} 缺少进入过渡。`);
      continue;
    }
    if (!Number.isFinite(edge.durationS) || edge.durationS <= 0 || edge.durationS > 600) {
      errors.push(`第 ${index} 段过渡时长必须大于 0 且不超过 600 秒。`);
    }
  }

  const firstSnapshot = document.frames[0]?.poseSnapshot;
  if (firstSnapshot !== undefined) {
    document.frames.forEach((frame, index) => {
      if (frame.poseSnapshot.profile_fingerprint !== firstSnapshot.profile_fingerprint) {
        errors.push(`关键帧 ${index + 1} 的配置指纹与当前运动不匹配。`);
      }
      if (frame.poseSnapshot.kinematics_fingerprint !== firstSnapshot.kinematics_fingerprint) {
        errors.push(`关键帧 ${index + 1} 的运动学指纹与当前运动不匹配。`);
      }
    });
  }

  return { valid: errors.length === 0, errors };
}

/**
 * Formal-Motion conversion is the only editor boundary that enforces the 2+
 * invariant. Draft conversion intentionally accepts zero or one keyframe.
 */
export function studioDocumentToMotionKeyframes(
  document: StudioDraftDocument,
): MotionKeyframe[] {
  const validation = validatePlayableStudioDocument(document);
  if (!validation.valid) throw new Error(validation.errors.join(' '));
  return studioDocumentToDraftKeyframes(document);
}
