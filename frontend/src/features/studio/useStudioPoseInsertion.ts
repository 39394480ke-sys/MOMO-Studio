import { useCallback, useEffect, useRef, useState } from 'react';

import { getPose, getPoses } from '../../api/client';
import type { MotionKeyframe, PoseSummary } from '../../api/types';
import type {
  StudioDraftDocument,
  StudioEditorAction,
  StudioInsertPosition,
} from './studioEditorState';

const MAX_STUDIO_FRAMES = 1000;

export interface PoseInsertion {
  anchorFrameId: string | null;
  position: StudioInsertPosition;
}

interface UseStudioPoseInsertionOptions {
  document: StudioDraftDocument;
  edit: (action: StudioEditorAction) => void;
  getWorkspaceGeneration: () => number;
  workspaceGeneration: number;
}

function id(): string {
  return globalThis.crypto.randomUUID();
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : '编排操作失败。';
}

export function snapshotCompatibilityReason(
  snapshot: MotionKeyframe['pose_snapshot'],
  document: StudioDraftDocument,
  ignoredFrameId?: string,
): string | null {
  if (snapshot.robot_variant !== document.robotVariant) {
    return `当前机械臂是 ${snapshot.robot_variant}，但草稿型号是 ${document.robotVariant}。`;
  }
  const reference = document.frames.find((frame) => frame.id !== ignoredFrameId)?.poseSnapshot;
  if (!reference) return null;
  if (snapshot.profile_fingerprint !== reference.profile_fingerprint) {
    return '当前机械臂配置与草稿内嵌快照不匹配。';
  }
  if (snapshot.kinematics_fingerprint !== reference.kinematics_fingerprint) {
    return '当前机械臂运动学模型与草稿内嵌快照不匹配。';
  }
  return null;
}

export function useStudioPoseInsertion({
  document,
  edit,
  getWorkspaceGeneration,
  workspaceGeneration,
}: UseStudioPoseInsertionOptions) {
  const [action, setAction] = useState<string | null>(null);
  const [poseInsertion, setPoseInsertion] = useState<PoseInsertion | null>(null);
  const [poses, setPoses] = useState<PoseSummary[]>([]);
  const [poseSearch, setPoseSearch] = useState('');
  const [posesBusy, setPosesBusy] = useState(false);
  const [poseError, setPoseError] = useState<string | null>(null);
  const documentRef = useRef(document);
  const poseInsertionRef = useRef(poseInsertion);
  const poseCommitAbortRef = useRef<AbortController | null>(null);

  documentRef.current = document;
  poseInsertionRef.current = poseInsertion;

  useEffect(() => () => {
    poseCommitAbortRef.current?.abort();
  }, []);

  const reset = useCallback(() => {
    poseCommitAbortRef.current?.abort();
    poseCommitAbortRef.current = null;
    poseInsertionRef.current = null;
    setPoseInsertion(null);
  }, []);

  useEffect(() => {
    reset();
  }, [reset, workspaceGeneration]);

  const startPoseInsertion = useCallback((
    position: StudioInsertPosition,
    anchorFrameId: string | null,
  ) => {
    poseCommitAbortRef.current?.abort();
    poseCommitAbortRef.current = null;
    setPoseInsertion({ position, anchorFrameId });
    setPoseSearch('');
    setPoseError(null);
  }, []);

  useEffect(() => {
    if (!poseInsertion) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setPosesBusy(true);
      void getPoses({
        page: 1,
        page_size: 24,
        search: poseSearch,
        sort: 'updated_at',
        order: 'desc',
      }, controller.signal).then((page) => {
        if (!controller.signal.aborted) setPoses(page.items);
      }).catch((caught: unknown) => {
        if (!controller.signal.aborted) setPoseError(message(caught));
      }).finally(() => {
        if (!controller.signal.aborted) setPosesBusy(false);
      });
    }, poseSearch ? 180 : 0);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [poseInsertion, poseSearch]);

  const addPose = useCallback(async (pose: PoseSummary) => {
    const insertion = poseInsertion;
    if (!insertion) return;
    if (documentRef.current.frames.length >= MAX_STUDIO_FRAMES) {
      setPoseError(`一个编排草稿最多支持 ${MAX_STUDIO_FRAMES} 个关键帧。`);
      return;
    }
    poseCommitAbortRef.current?.abort();
    const controller = new AbortController();
    poseCommitAbortRef.current = controller;
    const generation = getWorkspaceGeneration();
    setAction('add-pose');
    setPosesBusy(true);
    setPoseError(null);
    try {
      const full = await getPose(pose.id, controller.signal);
      if (
        controller.signal.aborted ||
        generation !== getWorkspaceGeneration() ||
        poseInsertionRef.current !== insertion
      ) return;
      const incompatibility = snapshotCompatibilityReason(full.snapshot, documentRef.current);
      if (incompatibility) throw new Error(incompatibility);
      edit({
        type: 'frame/add-pose',
        position: insertion.position,
        anchorFrameId: insertion.anchorFrameId,
        frameId: id(),
        pose: { id: full.id, name: full.name, snapshot: full.snapshot },
      });
      setPoseInsertion(null);
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === 'AbortError')) {
        setPoseError(message(caught));
      }
    } finally {
      if (poseCommitAbortRef.current === controller) {
        poseCommitAbortRef.current = null;
        setPosesBusy(false);
      }
      setAction((currentAction) => currentAction === 'add-pose' ? null : currentAction);
    }
  }, [edit, getWorkspaceGeneration, poseInsertion]);

  const closePoseInsertion = useCallback(() => {
    poseCommitAbortRef.current?.abort();
    poseCommitAbortRef.current = null;
    poseInsertionRef.current = null;
    setPosesBusy(false);
    setPoseInsertion(null);
  }, []);

  return {
    action,
    addPose,
    closePoseInsertion,
    poseError,
    poseInsertion,
    poseSearch,
    poses,
    posesBusy,
    reset,
    setPoseSearch,
    startPoseInsertion,
  };
}

export type StudioPoseInsertion = ReturnType<typeof useStudioPoseInsertion>;
