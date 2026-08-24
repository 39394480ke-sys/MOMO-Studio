import { describe, expect, it } from 'vitest';

import type {
  MotionEntity,
  MotionKeyframe,
  PoseSnapshot,
  RobotVariant,
} from '../../api/types';
import {
  DEFAULT_STUDIO_EDGE,
  STUDIO_HISTORY_LIMIT,
  STUDIO_KEYFRAME_LIMIT,
  createEmptyStudioDocument,
  createStudioEditorState,
  createStudioFrame,
  motionKeyframesToStudioDocument,
  motionToStudioDocument,
  studioDocumentToCreateKeyframes,
  studioDocumentToDraftKeyframes,
  studioDocumentToMotionKeyframes,
  studioEditorReducer,
  validatePlayableStudioDocument,
  type StudioDraftDocument,
  type StudioEditorState,
} from './studioEditorState';

const PROFILE = 'a'.repeat(64);
const KINEMATICS = 'b'.repeat(64);

function snapshot(
  marker: number,
  options: {
    variant?: RobotVariant;
    profile?: string;
    kinematics?: string;
  } = {},
): PoseSnapshot {
  const variant = options.variant ?? 'V2';
  const positions: Record<string, number> = variant === 'V2'
    ? { j10: marker, j11: marker + 1 }
    : { j11: marker + 1 };
  const units: Record<string, 'mm' | 'deg'> = variant === 'V2'
    ? { j10: 'mm', j11: 'deg' }
    : { j11: 'deg' };
  return {
    robot_variant: variant,
    joint_state: { positions, units },
    tcp_pose: {
      frame: 'base',
      position_mm: { x: marker, y: marker + 1, z: marker + 2 },
      orientation_quaternion_xyzw: { x: 0, y: 0, z: 0, w: 1 },
    },
    profile_fingerprint: options.profile ?? PROFILE,
    kinematics_fingerprint: options.kinematics ?? KINEMATICS,
    state_sequence: marker,
    hardware_snapshot: null,
    calibration_fingerprint: null,
    captured_at: `2026-08-24T00:00:${String(marker).padStart(2, '0')}Z`,
  };
}

function frame(id: string, marker = id.charCodeAt(0), variant: RobotVariant = 'V2') {
  return createStudioFrame({
    id,
    label: `Frame ${id.toUpperCase()}`,
    poseSnapshot: snapshot(marker, { variant }),
    sourcePoseId: `pose-${id}`,
  });
}

function buildDocument(ids: readonly string[]): StudioDraftDocument {
  let state = createStudioEditorState(createEmptyStudioDocument({
    robotVariant: 'V2',
    name: 'Draft motion',
  }));
  ids.forEach((id) => {
    state = studioEditorReducer(state, {
      type: 'frame/add-after',
      anchorFrameId: null,
      frame: frame(id),
    });
  });
  return state.document;
}

function fresh(ids: readonly string[]): StudioEditorState {
  return createStudioEditorState(buildDocument(ids), { selectedFrameId: ids[0] ?? null });
}

function ids(state: StudioEditorState): string[] {
  return state.document.frames.map((candidate) => candidate.id);
}

describe('studio editor construction and invariants', () => {
  it('creates an empty draft without weakening the formal Motion invariant', () => {
    const document = createEmptyStudioDocument({ robotVariant: 'V1' });

    expect(document).toEqual({
      name: '',
      description: '',
      robotVariant: 'V1',
      frames: [],
      edges: [],
      tags: [],
      playbackDefaults: { loop: false, speed_multiplier: 1 },
    });
    expect(studioDocumentToDraftKeyframes(document)).toEqual([]);
    expect(validatePlayableStudioDocument(document)).toEqual({
      valid: false,
      errors: [
        'Motion name is required.',
        'A playable Motion requires at least two keyframes.',
      ],
    });
    expect(() => studioDocumentToMotionKeyframes(document)).toThrow(
      'A playable Motion requires at least two keyframes',
    );
  });

  it('normalizes arbitrary supplied edges to exactly the directed adjacencies', () => {
    const base = buildDocument(['a', 'b', 'c']);
    const state = createStudioEditorState({
      ...base,
      edges: [
        { fromFrameId: 'a', toFrameId: 'b', durationS: 4, motionMode: 'JOINT', easing: 'LINEAR', isDefault: false },
        { fromFrameId: 'c', toFrameId: 'a', durationS: 9, motionMode: 'JOINT', easing: 'LINEAR', isDefault: false },
      ],
    });

    expect(state.document.edges).toEqual([
      { fromFrameId: 'a', toFrameId: 'b', durationS: 4, motionMode: 'JOINT', easing: 'LINEAR', isDefault: false },
      { fromFrameId: 'b', toFrameId: 'c', ...DEFAULT_STUDIO_EDGE, isDefault: true },
    ]);
    expect(state.document.edges.some((edge) => edge.toFrameId === 'a')).toBe(false);
  });

  it('bounds configurable history and uses the documented default', () => {
    expect(createStudioEditorState(buildDocument([])).historyLimit).toBe(STUDIO_HISTORY_LIMIT);
    expect(createStudioEditorState(buildDocument([]), { historyLimit: 0 }).historyLimit).toBe(1);
    expect(createStudioEditorState(buildDocument([]), { historyLimit: 900 }).historyLimit).toBe(500);
    expect(createStudioEditorState(buildDocument([]), { historyLimit: Number.NaN }).historyLimit)
      .toBe(STUDIO_HISTORY_LIMIT);
  });
});

describe('frame insertion, capture, replacement, and deletion', () => {
  it('adds before and after anchors, including empty/start/end insertion', () => {
    let state = fresh([]);
    state = studioEditorReducer(state, {
      type: 'frame/add-before', anchorFrameId: null, frame: frame('b'),
    });
    state = studioEditorReducer(state, {
      type: 'frame/add-before', anchorFrameId: 'b', frame: frame('a'),
    });
    state = studioEditorReducer(state, {
      type: 'frame/add-after', anchorFrameId: 'b', frame: frame('c'),
    });
    state = studioEditorReducer(state, {
      type: 'frame/add-after', anchorFrameId: null, frame: frame('d'),
    });

    expect(ids(state)).toEqual(['a', 'b', 'c', 'd']);
    expect(state.document.edges).toHaveLength(3);
    expect(state.document.edges.every((edge) => edge.isDefault)).toBe(true);
    expect(state.selectedFrameId).toBe('d');
  });

  it('ignores missing anchors and duplicate frame IDs', () => {
    const state = fresh(['a']);
    const missing = studioEditorReducer(state, {
      type: 'frame/add-after', anchorFrameId: 'missing', frame: frame('b'),
    });
    const duplicate = studioEditorReducer(state, {
      type: 'frame/add-after', anchorFrameId: 'a', frame: frame('a'),
    });

    expect(missing).toBe(state);
    expect(duplicate).toBe(state);
  });

  it('allows frame 1000 and rejects every insertion path at the backend limit', () => {
    const template = frame('template');
    const frames = Array.from({ length: STUDIO_KEYFRAME_LIMIT - 1 }, (_, index) => ({
      ...template,
      id: `frame-${index}`,
      label: `Frame ${index + 1}`,
    }));
    let state = createStudioEditorState({
      ...createEmptyStudioDocument({ robotVariant: 'V2', name: 'Bounded' }),
      frames,
    });
    state = studioEditorReducer(state, {
      type: 'frame/add-after', anchorFrameId: null, frame: frame('last'),
    });
    expect(state.document.frames).toHaveLength(STUDIO_KEYFRAME_LIMIT);

    const blockedActions = [
      { type: 'frame/add-before', anchorFrameId: null, frame: frame('overflow-before') },
      { type: 'frame/add-after', anchorFrameId: null, frame: frame('overflow-after') },
      {
        type: 'frame/add-pose', position: 'after', anchorFrameId: null,
        frameId: 'overflow-pose', pose: { id: 'pose-limit', name: 'Limit', snapshot: snapshot(1) },
      },
      {
        type: 'frame/capture', position: 'after', anchorFrameId: null,
        frameId: 'overflow-capture', label: 'Limit capture', snapshot: snapshot(2),
      },
      { type: 'frame/duplicate', frameId: 'last', duplicateFrameId: 'overflow-copy' },
    ] as const;
    for (const action of blockedActions) {
      expect(studioEditorReducer(state, action)).toBe(state);
    }
    expect(state.document.frames).toHaveLength(STUDIO_KEYFRAME_LIMIT);
  });

  it('adds Pose provenance and a captured snapshot without Pose provenance', () => {
    let state = fresh([]);
    state = studioEditorReducer(state, {
      type: 'frame/add-pose',
      position: 'after',
      anchorFrameId: null,
      frameId: 'pose-frame',
      pose: { id: 'pose-1', name: 'Ready', snapshot: snapshot(1) },
    });
    state = studioEditorReducer(state, {
      type: 'frame/capture',
      position: 'after',
      anchorFrameId: 'pose-frame',
      frameId: 'capture-frame',
      label: 'Live capture',
      snapshot: snapshot(2),
    });

    expect(state.document.frames[0]).toMatchObject({
      id: 'pose-frame', label: 'Ready', sourcePoseId: 'pose-1', holdS: 0,
    });
    expect(state.document.frames[1]).toMatchObject({
      id: 'capture-frame', label: 'Live capture', sourcePoseId: null, holdS: 0,
    });
  });

  it('detaches inserted and replacement snapshots from action payloads', () => {
    const insertedSnapshot = snapshot(1);
    let state = createStudioEditorState(createEmptyStudioDocument({ robotVariant: 'V2' }));
    state = studioEditorReducer(state, {
      type: 'frame/capture', position: 'after', anchorFrameId: null,
      frameId: 'a', label: 'A', snapshot: insertedSnapshot,
    });
    insertedSnapshot.joint_state.positions.j10 = 999;
    expect(state.document.frames[0].poseSnapshot.joint_state.positions.j10).toBe(1);

    const replacement = snapshot(2);
    state = studioEditorReducer(state, {
      type: 'frame/replace-snapshot', frameId: 'a', snapshot: replacement, sourcePoseId: 'pose-2',
    });
    replacement.joint_state.positions.j10 = 888;
    expect(state.document.frames[0].poseSnapshot.joint_state.positions.j10).toBe(2);
    expect(state.document.frames[0].sourcePoseId).toBe('pose-2');
  });

  it('deletes the selected frame, chooses a nearby selection, and rebuilds only adjacency', () => {
    let state = fresh(['a', 'b', 'c']);
    state = studioEditorReducer(state, { type: 'selection/set', frameId: 'b' });
    state = studioEditorReducer(state, { type: 'edge/set-duration', toFrameId: 'b', durationS: 2 });
    state = studioEditorReducer(state, { type: 'edge/set-duration', toFrameId: 'c', durationS: 3 });
    state = studioEditorReducer(state, { type: 'frame/delete', frameId: 'b' });

    expect(ids(state)).toEqual(['a', 'c']);
    expect(state.selectedFrameId).toBe('c');
    expect(state.document.edges).toEqual([
      { fromFrameId: 'a', toFrameId: 'c', ...DEFAULT_STUDIO_EDGE, isDefault: true },
    ]);
    expect(studioEditorReducer(state, { type: 'frame/delete', frameId: 'missing' })).toBe(state);
  });

  it('preserves an adjacency that still exists after deleting an unrelated frame', () => {
    let state = fresh(['a', 'b', 'c']);
    state = studioEditorReducer(state, { type: 'edge/set-duration', toFrameId: 'c', durationS: 7 });
    state = studioEditorReducer(state, { type: 'frame/delete', frameId: 'a' });

    expect(state.document.edges).toEqual([
      {
        fromFrameId: 'b', toFrameId: 'c', durationS: 7,
        motionMode: 'JOINT', easing: 'SMOOTHSTEP', isDefault: false,
      },
    ]);
  });

  it('duplicates payload data but creates explicit default edges for new adjacencies', () => {
    let state = fresh(['a', 'b']);
    state = studioEditorReducer(state, { type: 'edge/set-duration', toFrameId: 'b', durationS: 8 });
    state = studioEditorReducer(state, {
      type: 'frame/duplicate', frameId: 'a', duplicateFrameId: 'copy', label: 'A duplicate',
    });

    expect(ids(state)).toEqual(['a', 'copy', 'b']);
    expect(state.document.frames[1]).toMatchObject({
      id: 'copy', label: 'A duplicate', sourcePoseId: 'pose-a',
    });
    expect(state.document.frames[1].poseSnapshot).toEqual(state.document.frames[0].poseSnapshot);
    expect(state.document.frames[1].poseSnapshot).not.toBe(state.document.frames[0].poseSnapshot);
    expect(state.document.edges).toEqual([
      { fromFrameId: 'a', toFrameId: 'copy', ...DEFAULT_STUDIO_EDGE, isDefault: true },
      { fromFrameId: 'copy', toFrameId: 'b', ...DEFAULT_STUDIO_EDGE, isDefault: true },
    ]);
  });
});

describe('directed adjacency and reorder semantics', () => {
  it('preserves only original directed adjacencies and defaults every new pair', () => {
    let state = fresh(['a', 'b', 'c', 'd']);
    state = studioEditorReducer(state, { type: 'edge/set-duration', toFrameId: 'b', durationS: 2 });
    state = studioEditorReducer(state, { type: 'edge/set-duration', toFrameId: 'c', durationS: 3 });
    state = studioEditorReducer(state, { type: 'edge/set-duration', toFrameId: 'd', durationS: 4 });
    state = studioEditorReducer(state, { type: 'frame/reorder', frameId: 'd', toIndex: 2 });

    expect(ids(state)).toEqual(['a', 'b', 'd', 'c']);
    expect(state.document.edges).toEqual([
      {
        fromFrameId: 'a', toFrameId: 'b', durationS: 2,
        motionMode: 'JOINT', easing: 'SMOOTHSTEP', isDefault: false,
      },
      { fromFrameId: 'b', toFrameId: 'd', ...DEFAULT_STUDIO_EDGE, isDefault: true },
      { fromFrameId: 'd', toFrameId: 'c', ...DEFAULT_STUDIO_EDGE, isDefault: true },
    ]);
  });

  it('supports keyboard-style moves, clamps boundaries, and keeps selection', () => {
    let state = fresh(['a', 'b', 'c']);
    state = studioEditorReducer(state, { type: 'selection/set', frameId: 'b' });
    state = studioEditorReducer(state, { type: 'frame/move', frameId: 'b', direction: 'forward' });
    expect(ids(state)).toEqual(['a', 'c', 'b']);
    expect(state.selectedFrameId).toBe('b');

    const atEnd = studioEditorReducer(state, {
      type: 'frame/move', frameId: 'b', direction: 'forward',
    });
    expect(atEnd).toBe(state);
    const missing = studioEditorReducer(state, {
      type: 'frame/reorder', frameId: 'missing', toIndex: 1,
    });
    expect(missing).toBe(state);
  });

  it('gives a former first frame a default incoming edge when moved later', () => {
    let state = fresh(['a', 'b', 'c']);
    state = studioEditorReducer(state, { type: 'edge/set-duration', toFrameId: 'b', durationS: 8 });
    state = studioEditorReducer(state, { type: 'edge/set-duration', toFrameId: 'c', durationS: 9 });
    state = studioEditorReducer(state, { type: 'frame/reorder', frameId: 'a', toIndex: 2 });

    expect(ids(state)).toEqual(['b', 'c', 'a']);
    expect(state.document.edges).toEqual([
      {
        fromFrameId: 'b', toFrameId: 'c', durationS: 9,
        motionMode: 'JOINT', easing: 'SMOOTHSTEP', isDefault: false,
      },
      { fromFrameId: 'c', toFrameId: 'a', ...DEFAULT_STUDIO_EDGE, isDefault: true },
    ]);
    expect(studioDocumentToDraftKeyframes(state.document)[0].incoming_transition).toBeNull();
  });

  it('updates duration, mode, and easing on the target incoming edge only', () => {
    let state = fresh(['a', 'b', 'c']);
    state = studioEditorReducer(state, { type: 'edge/set-duration', toFrameId: 'b', durationS: 2.5 });
    state = studioEditorReducer(state, {
      type: 'edge/set-mode', toFrameId: 'b', motionMode: 'CARTESIAN_LINEAR',
    });
    state = studioEditorReducer(state, {
      type: 'edge/set-easing', toFrameId: 'b', easing: 'EASE_IN_OUT',
    });

    expect(state.document.edges[0]).toEqual({
      fromFrameId: 'a', toFrameId: 'b', durationS: 2.5,
      motionMode: 'CARTESIAN_LINEAR', easing: 'EASE_IN_OUT', isDefault: false,
    });
    expect(state.document.edges[1].isDefault).toBe(true);
    expect(studioEditorReducer(state, {
      type: 'edge/set-duration', toFrameId: 'a', durationS: 3,
    })).toBe(state);
  });

  it.each([
    Number.NaN,
    Number.POSITIVE_INFINITY,
    Number.NEGATIVE_INFINITY,
    -1,
    0,
    600.000_001,
  ])('rejects invalid transition duration %s before it reaches history or autosave', (durationS) => {
    const state = fresh(['a', 'b']);
    const next = studioEditorReducer(state, {
      type: 'edge/set-duration', toFrameId: 'b', durationS,
    });

    expect(next).toBe(state);
    expect(next.document.edges[0].durationS).toBe(DEFAULT_STUDIO_EDGE.durationS);
    expect(next.undoStack).toHaveLength(0);
    expect(next.dirty).toBe(false);
  });

  it('accepts both valid transition duration boundaries', () => {
    let state = fresh(['a', 'b']);
    state = studioEditorReducer(state, {
      type: 'edge/set-duration', toFrameId: 'b', durationS: Number.MIN_VALUE,
    });
    expect(state.document.edges[0].durationS).toBe(Number.MIN_VALUE);
    state = studioEditorReducer(state, {
      type: 'edge/set-duration', toFrameId: 'b', durationS: 600,
    });
    expect(state.document.edges[0].durationS).toBe(600);
  });
});

describe('document fields, history, dirty state, and selection', () => {
  it('edits all document and frame fields through immutable actions', () => {
    let state = fresh(['a', 'b']);
    const original = state.document;
    state = studioEditorReducer(state, { type: 'document/set-name', name: 'Inspection' });
    state = studioEditorReducer(state, { type: 'document/set-description', description: 'Line A' });
    state = studioEditorReducer(state, { type: 'document/set-tags', tags: ['qa', 'line-a'] });
    state = studioEditorReducer(state, {
      type: 'document/set-playback-defaults', playbackDefaults: { loop: true, speed_multiplier: 0.5 },
    });
    state = studioEditorReducer(state, { type: 'frame/set-label', frameId: 'a', label: 'Start' });
    state = studioEditorReducer(state, { type: 'frame/set-hold', frameId: 'a', holdS: 1.25 });

    expect(state.document).not.toBe(original);
    expect(original.name).toBe('Draft motion');
    expect(state.document).toMatchObject({
      name: 'Inspection', description: 'Line A', tags: ['qa', 'line-a'],
      playbackDefaults: { loop: true, speed_multiplier: 0.5 },
    });
    expect(state.document.frames[0]).toMatchObject({ label: 'Start', holdS: 1.25 });
    expect(state.dirty).toBe(true);
  });

  it.each([
    Number.NaN,
    Number.POSITIVE_INFINITY,
    Number.NEGATIVE_INFINITY,
    -0.000_001,
    600.000_001,
  ])('rejects invalid keyframe hold %s before it reaches history or autosave', (holdS) => {
    const state = fresh(['a', 'b']);
    const next = studioEditorReducer(state, { type: 'frame/set-hold', frameId: 'a', holdS });

    expect(next).toBe(state);
    expect(next.document.frames[0].holdS).toBe(0);
    expect(next.undoStack).toHaveLength(0);
    expect(next.dirty).toBe(false);
  });

  it('accepts both valid hold boundaries', () => {
    let state = fresh(['a', 'b']);
    state = studioEditorReducer(state, { type: 'frame/set-hold', frameId: 'a', holdS: 600 });
    expect(state.document.frames[0].holdS).toBe(600);
    state = studioEditorReducer(state, { type: 'frame/set-hold', frameId: 'a', holdS: 0 });
    expect(state.document.frames[0].holdS).toBe(0);
  });

  it('keeps selection ephemeral and rejects selection of unknown frames', () => {
    const state = fresh(['a', 'b']);
    const selected = studioEditorReducer(state, { type: 'selection/set', frameId: 'b' });
    expect(selected.selectedFrameId).toBe('b');
    expect(selected.undoStack).toHaveLength(0);
    expect(selected.dirty).toBe(false);

    const unknown = studioEditorReducer(selected, { type: 'selection/set', frameId: 'unknown' });
    expect(unknown.selectedFrameId).toBeNull();
    expect(unknown.undoStack).toHaveLength(0);
  });

  it('supports bounded undo/redo, clears dirty at the saved snapshot, and invalidates redo', () => {
    let state = createStudioEditorState(buildDocument(['a', 'b']), { historyLimit: 2 });
    state = studioEditorReducer(state, { type: 'document/set-name', name: 'One' });
    state = studioEditorReducer(state, { type: 'document/set-name', name: 'Two' });
    state = studioEditorReducer(state, { type: 'document/set-name', name: 'Three' });
    expect(state.undoStack).toHaveLength(2);

    state = studioEditorReducer(state, { type: 'history/undo' });
    expect(state.document.name).toBe('Two');
    state = studioEditorReducer(state, { type: 'history/undo' });
    expect(state.document.name).toBe('One');
    expect(studioEditorReducer(state, { type: 'history/undo' })).toBe(state);

    state = studioEditorReducer(state, { type: 'history/redo' });
    expect(state.document.name).toBe('Two');
    state = studioEditorReducer(state, { type: 'document/set-name', name: 'Branch' });
    expect(state.redoStack).toHaveLength(0);
    expect(studioEditorReducer(state, { type: 'history/redo' })).toBe(state);
  });

  it('does not record no-op edits and an undo back to the persisted document clears dirty', () => {
    let state = fresh(['a', 'b']);
    expect(studioEditorReducer(state, {
      type: 'document/set-name', name: state.document.name,
    })).toBe(state);

    state = studioEditorReducer(state, { type: 'document/set-name', name: 'Changed' });
    expect(state.dirty).toBe(true);
    state = studioEditorReducer(state, { type: 'history/undo' });
    expect(state.document.name).toBe('Draft motion');
    expect(state.dirty).toBe(false);
  });
});

describe('autosave markers and conflict-safe snapshots', () => {
  it('marks only the document captured by the matching save token as persisted', () => {
    let state = fresh(['a', 'b']);
    state = studioEditorReducer(state, { type: 'document/set-name', name: 'Save me' });
    state = studioEditorReducer(state, { type: 'autosave/start', token: 'save-1' });
    state = studioEditorReducer(state, { type: 'document/set-name', name: 'Newer edit' });
    state = studioEditorReducer(state, {
      type: 'autosave/succeed', token: 'save-1', persistedRevision: 4,
      savedAt: '2026-08-24T12:00:00Z',
    });

    expect(state.document.name).toBe('Newer edit');
    expect(state.savedDocument.name).toBe('Save me');
    expect(state.dirty).toBe(true);
    expect(state.autosave).toMatchObject({
      status: 'saved', persistedRevision: 4, lastSavedAt: '2026-08-24T12:00:00Z', error: null,
    });
    expect(state.undoStack.length).toBeGreaterThan(0);
    state = studioEditorReducer(state, { type: 'history/undo' });
    expect(state.document.name).toBe('Save me');
    expect(state.dirty).toBe(false);
    state = studioEditorReducer(state, { type: 'history/redo' });
    expect(state.document.name).toBe('Newer edit');
    expect(state.dirty).toBe(true);
  });

  it('reconciles a canonical server acknowledgement without adding undo history', () => {
    let state = fresh(['a', 'b']);
    state = studioEditorReducer(state, { type: 'document/set-name', name: '  Canonical name  ' });
    const undoDepth = state.undoStack.length;
    state = studioEditorReducer(state, { type: 'autosave/start', token: 'canonical' });
    state = studioEditorReducer(state, {
      type: 'autosave/succeed',
      token: 'canonical',
      persistedRevision: 4,
      savedAt: '2026-08-24T12:00:00Z',
      acknowledgedDocument: { ...state.document, name: 'Canonical name' },
    });

    expect(state.document.name).toBe('Canonical name');
    expect(state.savedDocument.name).toBe('Canonical name');
    expect(state.dirty).toBe(false);
    expect(state.undoStack).toHaveLength(undoDepth);
    state = studioEditorReducer(state, { type: 'history/undo' });
    expect(state.document.name).toBe('Draft motion');
  });

  it('ignores stale completions after a newer autosave starts', () => {
    let state = fresh(['a', 'b']);
    state = studioEditorReducer(state, { type: 'autosave/start', token: 'old' });
    state = studioEditorReducer(state, { type: 'document/set-name', name: 'Newest' });
    state = studioEditorReducer(state, { type: 'autosave/start', token: 'new' });
    const stale = studioEditorReducer(state, {
      type: 'autosave/succeed', token: 'old', persistedRevision: 2, savedAt: 'old-time',
    });
    expect(stale).toBe(state);

    state = studioEditorReducer(state, {
      type: 'autosave/succeed', token: 'new', persistedRevision: 3, savedAt: 'new-time',
    });
    expect(state.dirty).toBe(false);
    expect(state.autosave.persistedRevision).toBe(3);
  });

  it('retains and dismisses a save failure without changing editor content', () => {
    let state = fresh(['a', 'b']);
    state = studioEditorReducer(state, { type: 'autosave/start', token: 'save' });
    expect(studioEditorReducer(state, {
      type: 'autosave/fail', token: 'stale', error: 'wrong',
    })).toBe(state);
    state = studioEditorReducer(state, {
      type: 'autosave/fail', token: 'save', error: 'Revision conflict',
    });
    expect(state.autosave).toMatchObject({ status: 'error', error: 'Revision conflict' });
    expect(state.document.name).toBe('Draft motion');

    state = studioEditorReducer(state, { type: 'autosave/dismiss-error' });
    expect(state.autosave).toMatchObject({ status: 'idle', error: null });
  });

  it('loads a server document as a clean revision and clears history/pending saves', () => {
    let state = fresh(['a', 'b']);
    state = studioEditorReducer(state, { type: 'document/set-name', name: 'Local' });
    state = studioEditorReducer(state, { type: 'autosave/start', token: 'pending' });
    const loaded = { ...buildDocument(['c', 'd']), name: 'Server' };
    state = studioEditorReducer(state, {
      type: 'document/load', document: loaded, persistedRevision: 9, selectedFrameId: 'd',
    });

    expect(state.document.name).toBe('Server');
    expect(state.selectedFrameId).toBe('d');
    expect(state.undoStack).toEqual([]);
    expect(state.redoStack).toEqual([]);
    expect(state.dirty).toBe(false);
    expect(state.autosave).toMatchObject({
      status: 'idle', persistedRevision: 9, pendingToken: null, pendingDocument: null,
    });
  });
});

describe('backend and formal Motion boundary conversion', () => {
  function keyframe(id: string, marker: number, incoming: MotionKeyframe['incoming_transition']): MotionKeyframe {
    return {
      id,
      label: `Keyframe ${id}`,
      pose_snapshot: snapshot(marker),
      source_pose_id: `pose-${id}`,
      hold_s: marker / 10,
      incoming_transition: incoming,
    };
  }

  it('round-trips backend keyframes through explicit directed edges', () => {
    const backendFrames = [
      keyframe('a', 1, null),
      keyframe('b', 2, { duration_s: 2.5, motion_mode: 'CARTESIAN_LINEAR', easing: 'EASE_IN_OUT' }),
      keyframe('c', 3, { duration_s: 1, motion_mode: 'JOINT', easing: 'SMOOTHSTEP' }),
    ];
    const document = motionKeyframesToStudioDocument(backendFrames, {
      name: 'Round trip', robotVariant: 'V2', description: 'Description', tags: ['demo'],
      playbackDefaults: { loop: true, speed_multiplier: 0.5 },
    });

    expect(document.edges).toEqual([
      {
        fromFrameId: 'a', toFrameId: 'b', durationS: 2.5,
        motionMode: 'CARTESIAN_LINEAR', easing: 'EASE_IN_OUT', isDefault: false,
      },
      { fromFrameId: 'b', toFrameId: 'c', ...DEFAULT_STUDIO_EDGE, isDefault: false },
    ]);
    expect(studioDocumentToDraftKeyframes(document)).toEqual(backendFrames);

    backendFrames[0].pose_snapshot.joint_state.positions.j10 = 999;
    expect(document.frames[0].poseSnapshot.joint_state.positions.j10).toBe(1);
  });

  it('gives malformed missing backend transitions an explicit editor default', () => {
    const document = motionKeyframesToStudioDocument([
      keyframe('a', 1, null), keyframe('b', 2, null),
    ], { name: 'Recoverable draft', robotVariant: 'V2' });

    expect(document.edges).toEqual([
      { fromFrameId: 'a', toFrameId: 'b', ...DEFAULT_STUDIO_EDGE, isDefault: true },
    ]);
    expect(studioDocumentToDraftKeyframes(document)[1].incoming_transition).toEqual({
      duration_s: 1, motion_mode: 'JOINT', easing: 'SMOOTHSTEP',
    });
  });

  it('never emits an ambiguous later draft keyframe from a malformed editor document', () => {
    const malformed = { ...buildDocument(['a', 'b']), edges: [] };
    expect(() => studioDocumentToDraftKeyframes(malformed)).toThrow(
      'Keyframe 2 is missing its incoming transition edge',
    );
  });

  it('creates formal API keyframes only after validation and strips editor-only IDs', () => {
    const document = buildDocument(['a', 'b']);
    const formal = studioDocumentToMotionKeyframes(document);
    const createPayload = studioDocumentToCreateKeyframes(document);

    expect(formal).toHaveLength(2);
    expect(formal[0].incoming_transition).toBeNull();
    expect(formal[1].incoming_transition).toEqual({
      duration_s: 1, motion_mode: 'JOINT', easing: 'SMOOTHSTEP',
    });
    expect(createPayload[0]).not.toHaveProperty('id');
    expect(createPayload[0].pose_snapshot).not.toBe(document.frames[0].poseSnapshot);
  });

  it('converts a full Motion entity with metadata', () => {
    const keyframes = studioDocumentToMotionKeyframes(buildDocument(['a', 'b']));
    const motion: MotionEntity = {
      schema_version: '2.0.0',
      id: 'motion-1',
      name: 'Saved motion',
      description: 'A saved sequence',
      robot_variant: 'V2',
      keyframes,
      playback_defaults: { loop: true, speed_multiplier: 0.75 },
      tags: ['saved'],
      source_metadata: null,
      created_at: '2026-08-24T00:00:00Z',
      updated_at: '2026-08-24T01:00:00Z',
      revision: 3,
    };

    expect(motionToStudioDocument(motion)).toMatchObject({
      name: 'Saved motion', description: 'A saved sequence', robotVariant: 'V2',
      playbackDefaults: { loop: true, speed_multiplier: 0.75 }, tags: ['saved'],
    });
  });

  it('reports all formal boundary violations without restricting draft edits', () => {
    const invalid: StudioDraftDocument = {
      ...buildDocument(['a', 'b']),
      name: ' ',
      robotVariant: 'V1',
      frames: [
        { ...frame('same', 1), label: '', holdS: -1 },
        {
          ...frame('same', 2),
          poseSnapshot: snapshot(2, { profile: 'different', kinematics: 'different' }),
        },
      ],
      edges: [{
        fromFrameId: 'same', toFrameId: 'same', durationS: 0,
        motionMode: 'JOINT', easing: 'LINEAR', isDefault: false,
      }],
    };
    const result = validatePlayableStudioDocument(invalid);

    expect(result.valid).toBe(false);
    expect(result.errors).toEqual(expect.arrayContaining([
      'Motion name is required.',
      'Keyframe 1 requires a label.',
      'Keyframe 1 hold must be between 0 and 600 seconds.',
      'Keyframe 1 robot variant does not match the draft.',
      'Keyframe 2 has a duplicate ID.',
      'Keyframe 2 robot variant does not match the draft.',
      'Transition 1 duration must be greater than 0 and at most 600 seconds.',
      'Keyframe 2 profile fingerprint does not match the Motion.',
      'Keyframe 2 kinematics fingerprint does not match the Motion.',
    ]));
    expect(() => studioDocumentToMotionKeyframes(invalid)).toThrow();
  });

  it('validates one-frame drafts only when formal conversion is requested', () => {
    let state = fresh([]);
    state = studioEditorReducer(state, {
      type: 'frame/add-after', anchorFrameId: null, frame: frame('a'),
    });

    expect(state.document.frames).toHaveLength(1);
    expect(state.document.edges).toEqual([]);
    expect(studioDocumentToDraftKeyframes(state.document)).toHaveLength(1);
    expect(validatePlayableStudioDocument(state.document)).toMatchObject({ valid: false });
    expect(() => studioDocumentToMotionKeyframes(state.document)).toThrow(
      'A playable Motion requires at least two keyframes',
    );
  });
});
