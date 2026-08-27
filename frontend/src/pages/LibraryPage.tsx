import {
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Archive, RefreshCw, TriangleAlert, WifiOff } from 'lucide-react';

import {
  ApiError,
  capturePose,
  createMotion,
  deleteMotion,
  deletePose,
  duplicateMotion,
  duplicatePose,
  getMotion,
  getMotions,
  getPlayback,
  getPose,
  getPoses,
  getTrajectoryPreview,
  gotoPose,
  pausePlayback,
  playMotion,
  preflightMotion,
  resumePlayback,
  setPlaybackLoop,
  setPlaybackRate,
  stopPlayback,
} from '../api/client';
import type {
  CapturePoseRequest,
  EntityListQuery,
  EntityPage,
  MotionCommandSubmission,
  MotionEntity,
  MotionSummary,
  PlaybackStatus,
  PoseEntity,
  PoseSummary,
  TrajectoryPreflightReport,
  TrajectoryPreview,
} from '../api/types';
import { PageIntro } from '../components/PageIntro';
import {
  realCapabilityAvailability,
  useRealSession,
  type RealSessionSummary,
} from '../components/realSessionContext';
import { useRuntimeStatus } from '../components/runtimeStatusContext';
import {
  MotionCreateForm,
  PoseCaptureForm,
  type MotionCreationDraft,
} from '../features/library/LibraryCreatePanel';
import {
  LibraryToolbar,
  type LibraryFilters,
} from '../features/library/LibraryToolbar';
import { MotionCard } from '../features/library/MotionCard';
import { MotionPlaybackPanel } from '../features/library/MotionPlaybackPanel';
import { PoseCard } from '../features/library/PoseCard';
import { libraryIdempotencyKey, parseTags } from '../features/library/libraryFormat';
import { playbackLocksLibrary } from '../features/library/playbackState';

type LibraryTab = 'poses' | 'motions';
type LoadState = 'idle' | 'loading' | 'ready' | 'offline' | 'error';
type Confirmation =
  | { kind: 'delete-pose'; id: string }
  | { kind: 'goto-pose'; id: string }
  | { kind: 'delete-motion'; id: string };

const PAGE_SIZE = 24;
const SOURCE_POSE_LIMIT = 50;
const EMPTY_POSE_PAGE: EntityPage<PoseSummary> = {
  items: [],
  page: 1,
  page_size: PAGE_SIZE,
  total: 0,
};
const EMPTY_MOTION_PAGE: EntityPage<MotionSummary> = {
  items: [],
  page: 1,
  page_size: PAGE_SIZE,
  total: 0,
};
const INITIAL_FILTERS: LibraryFilters = {
  search: '',
  tags: '',
  sort: 'created_at',
  order: 'desc',
};
const PLAYBACK_POLL_INTERVAL_MS = 750;
const PLAYBACK_RATES = [0.25, 0.5, 1, 1.5, 2] as const;

function gotoDisabledReason(
  pose: PoseSummary,
  runtime: ReturnType<typeof useRuntimeStatus>,
  realSession: RealSessionSummary,
): string | null {
  if (runtime.backend !== 'connected') return '后端离线';
  if (runtime.controlMode === 'REAL') {
    const capability = realCapabilityAvailability(realSession, 'real_joint_motion');
    if (!capability.allowed) return capability.reason;
  } else if (runtime.hardwareAccessPolicy !== 'DISABLED' || runtime.realMotionEnabled) {
    return '仿真运行的硬件隔离不可用';
  }
  if (runtime.stale || runtime.robot?.stale !== false) return '机械臂状态已经过期';
  if (!runtime.robot?.connected) {
    return runtime.controlMode === 'REAL'
      ? '后端报告真机机械臂未连接'
      : '仿真机械臂未连接';
  }
  if (runtime.pendingAction !== null) return '机械臂连接状态正在切换';
  if (pose.robot_variant !== runtime.robot.variant) return '机械臂型号不匹配';
  if (!runtime.profile || runtime.profile.profile.variant !== runtime.robot.variant) {
    return '当前机械臂配置不可用';
  }
  if (pose.profile_fingerprint !== runtime.robot.profile_fingerprint) {
    return '配置指纹不匹配';
  }
  if (
    !runtime.profile.kinematics_fingerprint ||
    pose.kinematics_fingerprint !== runtime.profile.kinematics_fingerprint
  ) {
    return '运动学指纹不匹配';
  }
  const snapshotJoints = new Set(Object.keys(pose.joint_state.positions));
  const enabledJoints = runtime.profile.profile.enabled_joints;
  if (
    snapshotJoints.size !== enabledJoints.length ||
    enabledJoints.some((jointId) => !snapshotJoints.has(jointId))
  ) {
    return '启用关节集合不匹配';
  }
  return null;
}

function playbackDisabledReason(
  motion: Pick<MotionSummary, 'robot_variant'>,
  runtime: ReturnType<typeof useRuntimeStatus>,
  realSession: RealSessionSummary,
): string | null {
  if (runtime.backend !== 'connected') return '后端离线';
  if (runtime.controlMode === 'REAL') {
    const capability = realCapabilityAvailability(realSession, 'real_playback');
    if (!capability.allowed) return capability.reason;
  } else if (runtime.hardwareAccessPolicy !== 'DISABLED' || runtime.realMotionEnabled) {
    return '仿真运行的硬件隔离不可用';
  }
  if (runtime.stale || runtime.robot?.stale !== false) return '机械臂状态已经过期';
  if (!runtime.robot?.connected) {
    return runtime.controlMode === 'REAL'
      ? '后端报告真机机械臂未连接'
      : '仿真机械臂未连接';
  }
  if (runtime.pendingAction !== null) return '机械臂连接状态正在切换';
  if (motion.robot_variant !== runtime.robot.variant) return '机械臂型号不匹配';
  if (!runtime.profile || runtime.profile.profile.variant !== runtime.robot.variant) {
    return '当前机械臂配置不可用';
  }
  return null;
}

function closestPlaybackRate(value: number): number {
  return PLAYBACK_RATES.reduce((closest, option) => (
    Math.abs(option - value) < Math.abs(closest - value) ? option : closest
  ), PLAYBACK_RATES[0]);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '资源库请求失败';
}

function isRevisionConflict(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 409 && error.code === 'REVISION_CONFLICT';
}

export function LibraryPage() {
  const runtime = useRuntimeStatus();
  const { summary: realSession } = useRealSession();
  const [tab, setTab] = useState<LibraryTab>('poses');
  const [filters, setFilters] = useState<LibraryFilters>(INITIAL_FILTERS);
  const [pageNumber, setPageNumber] = useState(1);
  const deferredSearch = useDeferredValue(filters.search);
  const deferredTags = useDeferredValue(filters.tags);
  const [posePage, setPosePage] = useState<EntityPage<PoseSummary>>(EMPTY_POSE_PAGE);
  const [motionPage, setMotionPage] = useState<EntityPage<MotionSummary>>(EMPTY_MOTION_PAGE);
  const [sourcePoses, setSourcePoses] = useState<EntityPage<PoseSummary>>({
    ...EMPTY_POSE_PAGE,
    page_size: SOURCE_POSE_LIMIT,
  });
  const [loadState, setLoadState] = useState<LoadState>('idle');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadVersion, setReloadVersion] = useState(0);
  const requestGeneration = useRef(0);
  const actionInFlight = useRef(false);
  const [actionKey, setActionKey] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<{
    conflict: boolean;
    message: string;
  } | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [gotoResult, setGotoResult] = useState<{
    poseName: string;
    submission: MotionCommandSubmission;
  } | null>(null);
  const detailGeneration = useRef(0);
  const detailRequest = useRef<AbortController | null>(null);
  const preflightGeneration = useRef(0);
  const preflightRequest = useRef<AbortController | null>(null);
  const playbackPollGeneration = useRef(0);
  const playbackStatusRequest = useRef(0);
  const playbackCommandGeneration = useRef(0);
  const [preflight, setPreflight] = useState<TrajectoryPreflightReport | null>(null);
  const [trajectoryPreview, setTrajectoryPreview] = useState<TrajectoryPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [preflightError, setPreflightError] = useState<string | null>(null);
  const [playbackStatus, setPlaybackStatus] = useState<PlaybackStatus | null>(null);
  const [playbackError, setPlaybackError] = useState<string | null>(null);
  const [playbackPollError, setPlaybackPollError] = useState<string | null>(null);
  const [playbackLoop, setPlaybackLoopState] = useState(false);
  const [playbackRate, setPlaybackRateState] = useState<number>(1);
  const [detail, setDetail] = useState<
    | { status: 'loading'; kind: 'pose' | 'motion'; id: string }
    | { status: 'error'; kind: 'pose' | 'motion'; id: string; message: string }
    | { status: 'ready'; kind: 'pose'; entity: PoseEntity }
    | { status: 'ready'; kind: 'motion'; entity: MotionEntity }
    | null
  >(null);

  useEffect(() => () => {
    detailGeneration.current += 1;
    detailRequest.current?.abort();
    preflightGeneration.current += 1;
    preflightRequest.current?.abort();
  }, []);

  const query = useMemo<EntityListQuery>(
    () => ({
      page: pageNumber,
      page_size: PAGE_SIZE,
      search: deferredSearch,
      tags: parseTags(deferredTags),
      sort: filters.sort,
      order: filters.order,
    }),
    [deferredSearch, deferredTags, filters.order, filters.sort, pageNumber],
  );

  useEffect(() => {
    const generation = ++requestGeneration.current;
    if (runtime.backend !== 'connected') {
      setLoadState('offline');
      setLoadError(null);
      return;
    }

    const controller = new AbortController();
    setLoadState('loading');
    setLoadError(null);

    async function load() {
      try {
        if (tab === 'poses') {
          const page = await getPoses(query, controller.signal);
          if (generation !== requestGeneration.current || controller.signal.aborted) return;
          const lastPage = Math.max(1, Math.ceil(page.total / Math.max(1, page.page_size)));
          if (query.page > lastPage) {
            setPageNumber(lastPage);
            return;
          }
          setPosePage(page);
        } else {
          const [motions, poses] = await Promise.all([
            getMotions(query, controller.signal),
            getPoses(
              {
                page: 1,
                page_size: SOURCE_POSE_LIMIT,
                sort: 'name',
                order: 'asc',
              },
              controller.signal,
            ),
          ]);
          if (generation !== requestGeneration.current || controller.signal.aborted) return;
          const lastPage = Math.max(
            1,
            Math.ceil(motions.total / Math.max(1, motions.page_size)),
          );
          if (query.page > lastPage) {
            setSourcePoses(poses);
            setPageNumber(lastPage);
            return;
          }
          setMotionPage(motions);
          setSourcePoses(poses);
        }
        setLoadState('ready');
      } catch (error) {
        if (generation !== requestGeneration.current || controller.signal.aborted) return;
        setLoadError(errorMessage(error));
        setLoadState('error');
      }
    }

    void load();
    return () => controller.abort();
  }, [query, reloadVersion, runtime.backend, tab]);

  useEffect(() => {
    const generation = ++playbackPollGeneration.current;
    if (runtime.backend !== 'connected') return;
    let disposed = false;
    let inFlight = false;
    let controller: AbortController | null = null;

    async function pollPlayback() {
      if (disposed || inFlight) return;
      inFlight = true;
      const request = ++playbackStatusRequest.current;
      const currentController = new AbortController();
      controller = currentController;
      try {
        const next = await getPlayback(currentController.signal);
        if (
          disposed ||
          generation !== playbackPollGeneration.current ||
          request !== playbackStatusRequest.current
        ) return;
        setPlaybackStatus(next);
        setPlaybackPollError(null);
        if (next.motion_id && next.state !== 'IDLE') {
          setPlaybackLoopState(next.loop);
          setPlaybackRateState(closestPlaybackRate(next.rate));
        }
      } catch (error) {
        if (
          disposed ||
          currentController.signal.aborted ||
          generation !== playbackPollGeneration.current ||
          request !== playbackStatusRequest.current
        ) return;
        setPlaybackPollError(`无法获取播放状态：${errorMessage(error)}`);
      } finally {
        inFlight = false;
      }
    }

    void pollPlayback();
    const interval = window.setInterval(() => void pollPlayback(), PLAYBACK_POLL_INTERVAL_MS);
    return () => {
      disposed = true;
      controller?.abort();
      window.clearInterval(interval);
    };
  }, [runtime.backend]);

  const activePage = tab === 'poses' ? posePage : motionPage;
  const totalPages = Math.max(1, Math.ceil(activePage.total / activePage.page_size));
  const hasFilters = deferredSearch.trim().length > 0 || parseTags(deferredTags).length > 0;
  const online = runtime.backend === 'connected';
  const playbackActive = playbackLocksLibrary(playbackStatus);
  const anyActionBusy = actionKey !== null || playbackActive;

  function reload() {
    setActionError(null);
    setConfirmation(null);
    setReloadVersion((current) => current + 1);
  }

  function changeFilters(next: LibraryFilters) {
    setFilters(next);
    setPageNumber(1);
  }

  function selectTag(tag: string) {
    setFilters((current) => ({ ...current, tags: tag }));
    setPageNumber(1);
  }

  async function mutate<T>(
    key: string,
    operation: () => Promise<T>,
    onSuccess: (result: T) => void,
  ): Promise<boolean> {
    if (actionInFlight.current || playbackLocksLibrary(playbackStatus)) return false;
    actionInFlight.current = true;
    setActionKey(key);
    setActionError(null);
    setActionMessage(null);
    try {
      const result = await operation();
      onSuccess(result);
      setConfirmation(null);
      setReloadVersion((current) => current + 1);
      return true;
    } catch (error) {
      setActionError({
        conflict: isRevisionConflict(error),
        message: errorMessage(error),
      });
      return false;
    } finally {
      actionInFlight.current = false;
      setActionKey(null);
    }
  }

  function capture(request: CapturePoseRequest): Promise<boolean> {
    return mutate('capture-pose', () => capturePose(request), (pose) => {
      setActionMessage(`已捕获机位“${pose.name}” · 版本 ${pose.revision}。`);
    });
  }

  function create(draft: MotionCreationDraft): Promise<boolean> {
    return mutate(
      'create-motion',
      async () => {
        const [start, end] = await Promise.all([
          getPose(draft.start_pose_id),
          getPose(draft.end_pose_id),
        ]);
        if (
          start.revision !== draft.start_pose_revision ||
          end.revision !== draft.end_pose_revision
        ) {
          throw new ApiError({
            status: 409,
            code: 'REVISION_CONFLICT',
            message: '所选机位在资源列表加载后发生了变化。',
            details: {
              start_expected: draft.start_pose_revision,
              start_actual: start.revision,
              end_expected: draft.end_pose_revision,
              end_actual: end.revision,
            },
          });
        }
        if (start.snapshot.robot_variant !== end.snapshot.robot_variant) {
          throw new Error('所选机位不再使用相同的机械臂型号。');
        }
        if (
          start.snapshot.hardware_snapshot !== null ||
          end.snapshot.hardware_snapshot !== null
        ) {
          throw new Error('Stage 4 仿真资源库创建运动时不能内嵌硬件快照。');
        }
        return createMotion({
          name: draft.name,
          description: draft.description,
          robot_variant: start.snapshot.robot_variant,
          keyframes: [
            {
              label: '起点',
              pose_snapshot: start.snapshot,
              source_pose_id: start.id,
              hold_s: 0,
              incoming_transition: null,
            },
            {
              label: '终点',
              pose_snapshot: end.snapshot,
              source_pose_id: end.id,
              hold_s: 0,
              incoming_transition: {
                duration_s: draft.duration_s,
                motion_mode: draft.motion_mode,
                easing: 'SMOOTHSTEP',
              },
            },
          ],
          playback_defaults: { loop: false, speed_multiplier: 1 },
          tags: draft.tags,
        });
      },
      (motion) => {
        setActionMessage(`已创建运动“${motion.name}”，包含 ${motion.keyframes.length} 个内嵌关键帧。`);
      },
    );
  }

  function duplicateSelectedPose(pose: PoseSummary) {
    void mutate(
      `duplicate-pose-${pose.id}`,
      () => duplicatePose(pose.id, { expected_revision: pose.revision }),
      (duplicate) => setActionMessage(`已将机位复制为“${duplicate.name}”。`),
    );
  }

  function deleteSelectedPose(pose: PoseSummary) {
    void mutate(
      `delete-pose-${pose.id}`,
      () => deletePose(pose.id, pose.revision),
      () => setActionMessage(`已删除机位“${pose.name}”。已有运动中的内嵌快照不受影响。`),
    );
  }

  function gotoSelectedPose(pose: PoseSummary) {
    void mutate(
      `goto-pose-${pose.id}`,
      () => gotoPose(pose.id, {
        expected_revision: pose.revision,
        duration_s: 1,
        speed_scale: 0.5,
        idempotency_key: libraryIdempotencyKey(pose.id),
      }),
      (submission) => {
        setGotoResult({ poseName: pose.name, submission });
        setActionMessage(`已提交前往“${pose.name}”；命令状态为 ${submission.command.state}。`);
      },
    );
  }

  function duplicateSelectedMotion(motion: MotionSummary) {
    void mutate(
      `duplicate-motion-${motion.id}`,
      () => duplicateMotion(motion.id, { expected_revision: motion.revision }),
      (duplicate) => setActionMessage(`已将运动复制为“${duplicate.name}”。`),
    );
  }

  function deleteSelectedMotion(motion: MotionSummary) {
    void mutate(
      `delete-motion-${motion.id}`,
      () => deleteMotion(motion.id, motion.revision),
      () => setActionMessage(`已删除运动“${motion.name}”。`),
    );
  }

  async function runPlaybackCommand(
    key: string,
    operation: () => Promise<PlaybackStatus>,
    { priority = false }: { priority?: boolean } = {},
  ) {
    if (actionInFlight.current && !priority) return;
    const generation = ++playbackCommandGeneration.current;
    actionInFlight.current = true;
    ++playbackStatusRequest.current;
    setActionKey(key);
    setActionError(null);
    setPreflightError(null);
    setPlaybackError(null);
    setPlaybackPollError(null);
    try {
      const next = await operation();
      if (generation !== playbackCommandGeneration.current) return;
      ++playbackStatusRequest.current;
      setPlaybackStatus(next);
      setPlaybackLoopState(next.loop);
      setPlaybackRateState(closestPlaybackRate(next.rate));
    } catch (error) {
      if (generation !== playbackCommandGeneration.current) return;
      setPlaybackError(errorMessage(error));
    } finally {
      if (generation === playbackCommandGeneration.current) {
        actionInFlight.current = false;
        setActionKey(null);
      }
    }
  }

  function runMotionPreflight(motion: MotionEntity) {
    if (
      actionInFlight.current ||
      playbackLocksLibrary(playbackStatus) ||
      playbackDisabledReason(motion, runtime, realSession)
    ) return;
    preflightRequest.current?.abort();
    const controller = new AbortController();
    preflightRequest.current = controller;
    const generation = ++preflightGeneration.current;
    actionInFlight.current = true;
    setActionKey(`preflight-motion-${motion.id}`);
    setPreflight(null);
    setTrajectoryPreview(null);
    setPreviewLoading(false);
    setPreflightError(null);
    setPlaybackError(null);
    setPlaybackPollError(null);

    async function prepare() {
      try {
        const report = await preflightMotion(
          motion.id,
          { expected_revision: motion.revision },
          controller.signal,
        );
        if (generation !== preflightGeneration.current || controller.signal.aborted) return;
        setPreflight(report);
        if (!report.passed || !report.digest) return;
        setPreviewLoading(true);
        try {
          const preview = await getTrajectoryPreview(report.digest, controller.signal);
          if (generation !== preflightGeneration.current || controller.signal.aborted) return;
          if (preview.motion_id !== motion.id || preview.digest !== report.digest) {
            throw new TypeError('轨迹预览与已准备的运动不匹配');
          }
          setTrajectoryPreview(preview);
        } catch (error) {
          if (generation !== preflightGeneration.current || controller.signal.aborted) return;
          setPreflightError(`轨迹预览不可用：${errorMessage(error)}`);
        } finally {
          if (generation === preflightGeneration.current) setPreviewLoading(false);
        }
      } catch (error) {
        if (generation !== preflightGeneration.current || controller.signal.aborted) return;
        setPreflightError(errorMessage(error));
      } finally {
        if (preflightRequest.current === controller) {
          actionInFlight.current = false;
          setActionKey(null);
          preflightRequest.current = null;
        }
      }
    }

    void prepare();
  }

  function playSelectedMotion(motion: MotionEntity) {
    if (
      !preflight?.passed ||
      !preflight.digest ||
      preflight.motion_revision !== motion.revision ||
      playbackStatus?.state !== 'READY' ||
      playbackStatus.session_id != null ||
      playbackStatus.motion_id !== motion.id ||
      playbackStatus.trajectory_digest !== preflight.digest
    ) return;
    void runPlaybackCommand(
      `play-motion-${motion.id}`,
      () => playMotion(motion.id, {
        expected_revision: motion.revision,
        trajectory_digest: preflight.digest as string,
        loop: playbackLoop,
        rate: playbackRate,
      }),
    );
  }

  function pauseSelectedMotion(motion: MotionEntity) {
    void runPlaybackCommand(`pause-motion-${motion.id}`, pausePlayback);
  }

  function resumeSelectedMotion(motion: MotionEntity) {
    void runPlaybackCommand(`resume-motion-${motion.id}`, resumePlayback);
  }

  function stopSelectedMotion(motion: MotionEntity) {
    preflightGeneration.current += 1;
    preflightRequest.current?.abort();
    preflightRequest.current = null;
    setPreviewLoading(false);
    void runPlaybackCommand(
      `stop-motion-${motion.id}`,
      stopPlayback,
      { priority: true },
    );
  }

  function changePlaybackRate(motion: MotionEntity, next: number) {
    const state = playbackStatus?.state ?? 'IDLE';
    if (!['IDLE', 'READY', 'PLAYING', 'PAUSED'].includes(state)) return;
    const rate = closestPlaybackRate(next);
    setPreflightError(null);
    setPlaybackError(null);
    setPlaybackPollError(null);
    setPlaybackRateState(rate);
    if (!playbackLocksLibrary(playbackStatus) || playbackStatus?.motion_id !== motion.id) return;
    void runPlaybackCommand(
      `rate-motion-${motion.id}`,
      () => setPlaybackRate(rate),
    );
  }

  function changePlaybackLoop(motion: MotionEntity, next: boolean) {
    const state = playbackStatus?.state ?? 'IDLE';
    if (!['IDLE', 'READY', 'PLAYING', 'PAUSED'].includes(state)) return;
    setPreflightError(null);
    setPlaybackError(null);
    setPlaybackPollError(null);
    setPlaybackLoopState(next);
    if (!playbackLocksLibrary(playbackStatus) || playbackStatus?.motion_id !== motion.id) return;
    void runPlaybackCommand(
      `loop-motion-${motion.id}`,
      () => setPlaybackLoop(next),
    );
  }

  async function viewEntity(kind: 'pose' | 'motion', id: string) {
    preflightGeneration.current += 1;
    preflightRequest.current?.abort();
    setPreflight(null);
    setTrajectoryPreview(null);
    setPreviewLoading(false);
    setPreflightError(null);
    detailRequest.current?.abort();
    const controller = new AbortController();
    detailRequest.current = controller;
    const generation = ++detailGeneration.current;
    setDetail({ status: 'loading', kind, id });
    try {
      const entity = kind === 'pose'
        ? await getPose(id, controller.signal)
        : await getMotion(id, controller.signal);
      if (generation !== detailGeneration.current || controller.signal.aborted) return;
      if (kind === 'pose') {
        setDetail({ status: 'ready', kind, entity: entity as PoseEntity });
      } else {
        const motion = entity as MotionEntity;
        setDetail({ status: 'ready', kind, entity: motion });
        if (!playbackLocksLibrary(playbackStatus) || playbackStatus?.motion_id !== motion.id) {
          setPlaybackLoopState(motion.playback_defaults.loop);
          setPlaybackRateState(closestPlaybackRate(motion.playback_defaults.speed_multiplier));
        }
      }
    } catch (error) {
      if (generation !== detailGeneration.current || controller.signal.aborted) return;
      setDetail({ status: 'error', kind, id, message: errorMessage(error) });
    } finally {
      if (detailRequest.current === controller) detailRequest.current = null;
    }
  }

  function closeDetail() {
    detailGeneration.current += 1;
    detailRequest.current?.abort();
    detailRequest.current = null;
    preflightGeneration.current += 1;
    preflightRequest.current?.abort();
    setPreflight(null);
    setTrajectoryPreview(null);
    setPreviewLoading(false);
    setPreflightError(null);
    setDetail(null);
  }

  function dismissPlaybackError() {
    setPreflightError(null);
    setPlaybackError(null);
    setPlaybackPollError(null);
  }

  return (
    <div className="page library-page">
      <PageIntro
        title="资源库"
        description={`保存不可变的机位快照、预检编译轨迹，并控制${runtime.controlMode === 'REAL' ? '已授权真机' : '仿真'}运动播放。`}
        detail={runtime.controlMode === 'REAL'
          ? '前往机位和播放都需要后端授予对应能力，并保持有效的操作员会话。'
          : '前往机位和运动播放会经过已审核的仿真安全入口，实体硬件访问保持禁用。'}
      />

      <div className="library-stage-banner">
        <Archive aria-hidden="true" />
        <div>
          <strong>Stage 5 · 已编译的{runtime.controlMode === 'REAL' ? '真机授权' : '仿真'}播放</strong>
          <span>轨迹摘要绑定 · 实时状态 · {runtime.controlMode === 'REAL' ? '需要后端能力授权' : '实体硬件访问已禁用'}</span>
        </div>
      </div>

      <div aria-label="资源类型" className="library-tabs" role="tablist">
        <button
          aria-controls="poses-panel"
          aria-selected={tab === 'poses'}
          className={tab === 'poses' ? 'library-tab library-tab--active' : 'library-tab'}
          id="poses-tab"
          onClick={() => {
            if (tab !== 'poses') closeDetail();
            setTab('poses');
            setPageNumber(1);
            setConfirmation(null);
          }}
          role="tab"
          type="button"
        >
          机位
        </button>
        <button
          aria-controls="motions-panel"
          aria-selected={tab === 'motions'}
          className={tab === 'motions' ? 'library-tab library-tab--active' : 'library-tab'}
          id="motions-tab"
          onClick={() => {
            if (tab !== 'motions') closeDetail();
            setTab('motions');
            setPageNumber(1);
            setConfirmation(null);
          }}
          role="tab"
          type="button"
        >
          运动
        </button>
      </div>

      <div
        aria-labelledby={`${tab}-tab`}
        className="library-tab-panel"
        id={`${tab}-panel`}
        role="tabpanel"
      >
        {tab === 'poses' ? (
          <PoseCaptureForm
            busy={anyActionBusy}
            disabled={
              !online ||
              runtime.stale ||
              runtime.robot?.stale !== false ||
              runtime.robot?.connected !== true ||
              runtime.pendingAction !== null
            }
            onCapture={capture}
            robotLabel={runtime.robot ? `${runtime.robot.robot_id} · ${runtime.robot.variant}` : '机械臂不可用'}
          />
        ) : (
          <MotionCreateForm
            busy={anyActionBusy}
            disabled={!online}
            onCreate={create}
            poseTotal={sourcePoses.total}
            poses={sourcePoses.items}
          />
        )}

        <section aria-labelledby="saved-library-heading" className="saved-library">
          <header className="saved-library__heading">
            <div>
              <p className="section-kicker">已保存资源</p>
              <h2 id="saved-library-heading">已保存的{tab === 'poses' ? '机位' : '运动'}</h2>
            </div>
            <span>共 {activePage.total} 项</span>
          </header>

          <LibraryToolbar disabled={!online} filters={filters} onChange={changeFilters} />

          {loadState === 'offline' ? (
            <div className="library-notice library-notice--offline" role="status">
              <WifiOff aria-hidden="true" />
              <div>
                <strong>资源库离线</strong>
                <span>后端恢复前，无法刷新或修改已保存资源。</span>
              </div>
              <button className="command-button" onClick={() => void runtime.refresh()} type="button">
                <RefreshCw aria-hidden="true" />
                重试
              </button>
            </div>
          ) : null}

          {loadState === 'error' ? (
            <div className="library-notice library-notice--error" role="alert">
              <TriangleAlert aria-hidden="true" />
              <div>
                <strong>资源库请求失败</strong>
                <span>{loadError}</span>
              </div>
              <button className="command-button" onClick={reload} type="button">
                <RefreshCw aria-hidden="true" />
                重试
              </button>
            </div>
          ) : null}

          {actionError ? (
            <div className={actionError.conflict ? 'library-notice library-notice--conflict' : 'library-notice library-notice--error'} role="alert">
              <TriangleAlert aria-hidden="true" />
              <div>
                <strong>{actionError.conflict ? '版本冲突' : '资源库操作失败'}</strong>
                <span>{actionError.message}</span>
                {actionError.conflict ? <span>草稿或待处理选择已保留，请重新加载后再试。</span> : null}
              </div>
              {actionError.conflict ? (
                <button className="command-button" onClick={reload} type="button">
                  <RefreshCw aria-hidden="true" />
                  重新加载
                </button>
              ) : null}
            </div>
          ) : null}

          {actionMessage ? <p className="library-success" role="status">{actionMessage}</p> : null}

          {gotoResult ? (
            <div className="goto-result" role="status">
              <strong>前往 · {gotoResult.poseName} · {gotoResult.submission.command.state}</strong>
              <code>{gotoResult.submission.command_id}</code>
              <span>
                预检{gotoResult.submission.preflight?.accepted === false ? '未通过' : '已接受'}
              </span>
              {gotoResult.submission.preflight?.checks?.length ? (
                <ul>
                  {gotoResult.submission.preflight.checks.map((check, index) => (
                    <li key={`${check.name}-${index}`}>
                      {check.passed ? '通过' : '失败'} · {check.name} · {check.detail}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}

          {detail ? (
            <section
              aria-labelledby="library-detail-heading"
              className="library-detail"
              role="dialog"
            >
              <header>
                <div>
                  <p className="section-kicker">已校验资源详情</p>
                  <h3 id="library-detail-heading">
                    {detail.status === 'ready'
                      ? detail.entity.name
                      : `${detail.kind === 'pose' ? '机位' : '运动'}详情`}
                  </h3>
                </div>
                <button className="command-button" onClick={closeDetail} type="button">关闭详情</button>
              </header>
              {detail.status === 'loading' ? <p role="status">正在加载 UUID {detail.id}…</p> : null}
              {detail.status === 'error' ? (
                <div className="library-notice library-notice--error" role="alert">
                  <TriangleAlert aria-hidden="true" />
                  <div>
                    <strong>详情请求失败</strong>
                    <span>{detail.message}</span>
                  </div>
                  <button className="command-button" onClick={() => void viewEntity(detail.kind, detail.id)} type="button">重试</button>
                </div>
              ) : null}
              {detail.status === 'ready' && detail.kind === 'pose' ? (
                <dl className="library-detail__facts">
                  <div><dt>UUID</dt><dd><code>{detail.entity.id}</code></dd></div>
                  <div><dt>数据结构 / 版本</dt><dd>{detail.entity.schema_version} · 版本 {detail.entity.revision}</dd></div>
                  <div><dt>配置指纹</dt><dd><code>{detail.entity.snapshot.profile_fingerprint}</code></dd></div>
                  <div><dt>运动学指纹</dt><dd><code>{detail.entity.snapshot.kinematics_fingerprint}</code></dd></div>
                  <div><dt>状态序号</dt><dd>{detail.entity.snapshot.state_sequence ?? '导入数据 · 不可用'}</dd></div>
                  <div><dt>捕获时间</dt><dd>{detail.entity.snapshot.captured_at}</dd></div>
                </dl>
              ) : null}
              {detail.status === 'ready' && detail.kind === 'motion' ? (
                <>
                  <dl className="library-detail__facts">
                    <div><dt>UUID</dt><dd><code>{detail.entity.id}</code></dd></div>
                    <div><dt>数据结构 / 版本</dt><dd>{detail.entity.schema_version} · 版本 {detail.entity.revision}</dd></div>
                    <div><dt>机械臂型号</dt><dd>{detail.entity.robot_variant}</dd></div>
                    <div><dt>默认播放参数</dt><dd>{detail.entity.playback_defaults.speed_multiplier}× · {detail.entity.playback_defaults.loop ? '循环' : '不循环'}</dd></div>
                  </dl>
                  <ol className="motion-detail-keyframes">
                    {detail.entity.keyframes.map((keyframe, index) => (
                      <li key={keyframe.id}>
                        <strong>{index + 1}. {keyframe.label}</strong>
                        <span>{keyframe.pose_snapshot.robot_variant} · 停留 {keyframe.hold_s.toFixed(2)} 秒</span>
                        <span>
                          {keyframe.incoming_transition
                            ? `${keyframe.incoming_transition.motion_mode} · ${keyframe.incoming_transition.duration_s.toFixed(2)} s · ${keyframe.incoming_transition.easing}`
                            : '起始关键帧 · 无进入过渡'}
                        </span>
                        <code>来源 {keyframe.source_pose_id ?? '无（内嵌快照）'}</code>
                      </li>
                    ))}
                  </ol>
                  <MotionPlaybackPanel
                    actionKey={actionKey}
                    disabledReason={playbackDisabledReason(detail.entity, runtime, realSession)}
                    error={preflightError ?? playbackError ?? playbackPollError}
                    loop={playbackLoop}
                    motion={detail.entity}
                    onDismissError={dismissPlaybackError}
                    onLoopChange={(next) => changePlaybackLoop(detail.entity, next)}
                    onPause={() => pauseSelectedMotion(detail.entity)}
                    onPlay={() => playSelectedMotion(detail.entity)}
                    onPreflight={() => runMotionPreflight(detail.entity)}
                    onRateChange={(next) => changePlaybackRate(detail.entity, next)}
                    onResume={() => resumeSelectedMotion(detail.entity)}
                    onStop={() => stopSelectedMotion(detail.entity)}
                    playback={playbackStatus}
                    preflight={preflight}
                    preview={trajectoryPreview}
                    previewLoading={previewLoading}
                    rate={playbackRate}
                    runtimeMode={runtime.controlMode}
                    stopDisabled={!online}
                  />
                  <p className="stage-boundary-note">播放使用不可变的内嵌快照；时间轴编排请在独立的“编排”工作区完成。</p>
                </>
              ) : null}
            </section>
          ) : null}

          {loadState === 'loading' && activePage.items.length === 0 ? (
            <div aria-live="polite" className="library-loading" role="status">
              <RefreshCw aria-hidden="true" />
              正在加载{tab === 'poses' ? '机位' : '运动'}…
            </div>
          ) : null}

          {loadState !== 'loading' && activePage.items.length === 0 && loadState === 'ready' ? (
            <div className="library-empty-state">
              <Archive aria-hidden="true" />
              <strong>{hasFilters ? `没有${tab === 'poses' ? '机位' : '运动'}符合筛选条件` : `尚未保存${tab === 'poses' ? '机位' : '运动'}`}</strong>
              <span>
                {hasFilters
                  ? '请尝试其他搜索词或标签筛选。'
                  : tab === 'poses'
                    ? '捕获当前后端机械臂状态，以创建第一个机位。'
                    : '在上方选择两个兼容机位，以创建第一个运动。'}
              </span>
            </div>
          ) : null}

          {activePage.items.length > 0 ? (
            <>
              {loadState === 'loading' ? <p className="library-refreshing" role="status">正在刷新结果…</p> : null}
              <div className="library-card-grid">
                {tab === 'poses'
                  ? posePage.items.map((pose) => (
                      <PoseCard
                        busy={anyActionBusy || !online}
                        deletePending={confirmation?.kind === 'delete-pose' && confirmation.id === pose.id}
                        gotoDisabledReason={gotoDisabledReason(pose, runtime, realSession)}
                        gotoPending={confirmation?.kind === 'goto-pose' && confirmation.id === pose.id}
                        key={pose.id}
                        runtimeMode={runtime.controlMode}
                        onDeleteCancel={() => setConfirmation(null)}
                        onDeleteConfirm={deleteSelectedPose}
                        onDeleteRequest={(selected) => setConfirmation({ kind: 'delete-pose', id: selected.id })}
                        onDuplicate={duplicateSelectedPose}
                        onGotoCancel={() => setConfirmation(null)}
                        onGotoConfirm={gotoSelectedPose}
                        onGotoRequest={(selected) => setConfirmation({ kind: 'goto-pose', id: selected.id })}
                        onTagSelect={selectTag}
                        onView={(selected) => void viewEntity('pose', selected.id)}
                        pose={pose}
                      />
                    ))
                  : motionPage.items.map((motion) => (
                      <MotionCard
                        busy={anyActionBusy || !online}
                        deletePending={confirmation?.kind === 'delete-motion' && confirmation.id === motion.id}
                        key={motion.id}
                        motion={motion}
                        onDeleteCancel={() => setConfirmation(null)}
                        onDeleteConfirm={deleteSelectedMotion}
                        onDeleteRequest={(selected) => setConfirmation({ kind: 'delete-motion', id: selected.id })}
                        onDuplicate={duplicateSelectedMotion}
                        onPlay={(selected) => void viewEntity('motion', selected.id)}
                        onTagSelect={selectTag}
                        onView={(selected) => void viewEntity('motion', selected.id)}
                        playDisabledReason={playbackDisabledReason(motion, runtime, realSession)}
                        playBusy={
                          actionKey !== null ||
                          !online ||
                          (playbackActive && playbackStatus?.motion_id !== motion.id)
                        }
                        viewBusy={actionKey !== null || !online}
                      />
                    ))}
              </div>
            </>
          ) : null}

          {activePage.total > activePage.page_size ? (
            <nav aria-label={`${tab === 'poses' ? '机位' : '运动'}分页`} className="library-pagination">
              <button
                className="command-button"
                disabled={pageNumber <= 1 || loadState === 'loading'}
                onClick={() => setPageNumber((current) => Math.max(1, current - 1))}
                type="button"
              >
                上一页
              </button>
              <span>第 {pageNumber} / {totalPages} 页</span>
              <button
                className="command-button"
                disabled={pageNumber >= totalPages || loadState === 'loading'}
                onClick={() => setPageNumber((current) => Math.min(totalPages, current + 1))}
                type="button"
              >
                下一页
              </button>
            </nav>
          ) : null}
        </section>
      </div>
    </div>
  );
}
