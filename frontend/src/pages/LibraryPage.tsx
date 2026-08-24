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
): string | null {
  if (runtime.backend !== 'connected') return 'backend offline';
  if (runtime.stale || runtime.robot?.stale !== false) return 'robot state is stale';
  if (!runtime.robot?.connected) return 'Dry Run robot is disconnected';
  if (runtime.pendingAction !== null) return 'robot lifecycle action is pending';
  if (pose.robot_variant !== runtime.robot.variant) return 'robot variant mismatch';
  if (!runtime.profile || runtime.profile.profile.variant !== runtime.robot.variant) {
    return 'active profile is unavailable';
  }
  if (pose.profile_fingerprint !== runtime.robot.profile_fingerprint) {
    return 'profile fingerprint mismatch';
  }
  if (
    !runtime.profile.kinematics_fingerprint ||
    pose.kinematics_fingerprint !== runtime.profile.kinematics_fingerprint
  ) {
    return 'kinematics fingerprint mismatch';
  }
  const snapshotJoints = new Set(Object.keys(pose.joint_state.positions));
  const enabledJoints = runtime.profile.profile.enabled_joints;
  if (
    snapshotJoints.size !== enabledJoints.length ||
    enabledJoints.some((jointId) => !snapshotJoints.has(jointId))
  ) {
    return 'enabled joint set mismatch';
  }
  return null;
}

function playbackDisabledReason(
  motion: Pick<MotionSummary, 'robot_variant'>,
  runtime: ReturnType<typeof useRuntimeStatus>,
): string | null {
  if (runtime.backend !== 'connected') return 'backend offline';
  if (runtime.stale || runtime.robot?.stale !== false) return 'robot state is stale';
  if (!runtime.robot?.connected) return 'Dry Run robot is disconnected';
  if (runtime.pendingAction !== null) return 'robot lifecycle action is pending';
  if (motion.robot_variant !== runtime.robot.variant) return 'robot variant mismatch';
  if (!runtime.profile || runtime.profile.profile.variant !== runtime.robot.variant) {
    return 'active profile is unavailable';
  }
  return null;
}

function closestPlaybackRate(value: number): number {
  return PLAYBACK_RATES.reduce((closest, option) => (
    Math.abs(option - value) < Math.abs(closest - value) ? option : closest
  ), PLAYBACK_RATES[0]);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Library request failed';
}

function isRevisionConflict(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 409 && error.code === 'REVISION_CONFLICT';
}

export function LibraryPage() {
  const runtime = useRuntimeStatus();
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
        setPlaybackPollError(`Playback status unavailable: ${errorMessage(error)}`);
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
      setActionMessage(`Captured Pose “${pose.name}” · revision ${pose.revision}.`);
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
            message: 'A selected Pose changed after the source list was loaded.',
            details: {
              start_expected: draft.start_pose_revision,
              start_actual: start.revision,
              end_expected: draft.end_pose_revision,
              end_actual: end.revision,
            },
          });
        }
        if (start.snapshot.robot_variant !== end.snapshot.robot_variant) {
          throw new Error('Selected Pose details no longer use the same robot variant.');
        }
        if (
          start.snapshot.hardware_snapshot !== null ||
          end.snapshot.hardware_snapshot !== null
        ) {
          throw new Error('Motion creation cannot embed hardware snapshots in the Stage 4 Dry Run library.');
        }
        return createMotion({
          name: draft.name,
          description: draft.description,
          robot_variant: start.snapshot.robot_variant,
          keyframes: [
            {
              label: 'Start',
              pose_snapshot: start.snapshot,
              source_pose_id: start.id,
              hold_s: 0,
              incoming_transition: null,
            },
            {
              label: 'End',
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
        setActionMessage(`Created Motion “${motion.name}” with ${motion.keyframes.length} embedded keyframes.`);
      },
    );
  }

  function duplicateSelectedPose(pose: PoseSummary) {
    void mutate(
      `duplicate-pose-${pose.id}`,
      () => duplicatePose(pose.id, { expected_revision: pose.revision }),
      (duplicate) => setActionMessage(`Duplicated Pose as “${duplicate.name}”.`),
    );
  }

  function deleteSelectedPose(pose: PoseSummary) {
    void mutate(
      `delete-pose-${pose.id}`,
      () => deletePose(pose.id, pose.revision),
      () => setActionMessage(`Deleted Pose “${pose.name}”. Embedded Motion snapshots are unchanged.`),
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
        setActionMessage(`Goto submitted for “${pose.name}”; command state is ${submission.command.state}.`);
      },
    );
  }

  function duplicateSelectedMotion(motion: MotionSummary) {
    void mutate(
      `duplicate-motion-${motion.id}`,
      () => duplicateMotion(motion.id, { expected_revision: motion.revision }),
      (duplicate) => setActionMessage(`Duplicated Motion as “${duplicate.name}”.`),
    );
  }

  function deleteSelectedMotion(motion: MotionSummary) {
    void mutate(
      `delete-motion-${motion.id}`,
      () => deleteMotion(motion.id, motion.revision),
      () => setActionMessage(`Deleted Motion “${motion.name}”.`),
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
      playbackDisabledReason(motion, runtime)
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
            throw new TypeError('Trajectory preview does not match the prepared Motion');
          }
          setTrajectoryPreview(preview);
        } catch (error) {
          if (generation !== preflightGeneration.current || controller.signal.aborted) return;
          setPreflightError(`Preview unavailable: ${errorMessage(error)}`);
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
        title="Library"
        description="Capture immutable Pose snapshots, preflight compiled trajectories, and control Dry Run Motion playback."
        detail="Goto and Motion playback pass through the reviewed safety gateway; this interface never enables hardware access."
      />

      <div className="library-stage-banner">
        <Archive aria-hidden="true" />
        <div>
          <strong>Stage 5 · Compiled Dry Run playback</strong>
          <span>Digest-bound trajectories · live status · hardware access disabled</span>
        </div>
      </div>

      <div aria-label="Library entity type" className="library-tabs" role="tablist">
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
          POSES
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
          MOTIONS
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
            robotLabel={runtime.robot ? `${runtime.robot.robot_id} · ${runtime.robot.variant}` : 'Robot unavailable'}
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
              <p className="section-kicker">Stored entities</p>
              <h2 id="saved-library-heading">Saved {tab === 'poses' ? 'Poses' : 'Motions'}</h2>
            </div>
            <span>{activePage.total} total</span>
          </header>

          <LibraryToolbar disabled={!online} filters={filters} onChange={changeFilters} />

          {loadState === 'offline' ? (
            <div className="library-notice library-notice--offline" role="status">
              <WifiOff aria-hidden="true" />
              <div>
                <strong>Library offline</strong>
                <span>Stored entities cannot be refreshed or changed until the backend returns.</span>
              </div>
              <button className="command-button" onClick={() => void runtime.refresh()} type="button">
                <RefreshCw aria-hidden="true" />
                Retry
              </button>
            </div>
          ) : null}

          {loadState === 'error' ? (
            <div className="library-notice library-notice--error" role="alert">
              <TriangleAlert aria-hidden="true" />
              <div>
                <strong>Library request failed</strong>
                <span>{loadError}</span>
              </div>
              <button className="command-button" onClick={reload} type="button">
                <RefreshCw aria-hidden="true" />
                Retry
              </button>
            </div>
          ) : null}

          {actionError ? (
            <div className={actionError.conflict ? 'library-notice library-notice--conflict' : 'library-notice library-notice--error'} role="alert">
              <TriangleAlert aria-hidden="true" />
              <div>
                <strong>{actionError.conflict ? 'Revision conflict' : 'Library action failed'}</strong>
                <span>{actionError.message}</span>
                {actionError.conflict ? <span>Your draft or pending selection was kept. Reload before retrying.</span> : null}
              </div>
              {actionError.conflict ? (
                <button className="command-button" onClick={reload} type="button">
                  <RefreshCw aria-hidden="true" />
                  Reload
                </button>
              ) : null}
            </div>
          ) : null}

          {actionMessage ? <p className="library-success" role="status">{actionMessage}</p> : null}

          {gotoResult ? (
            <div className="goto-result" role="status">
              <strong>Goto · {gotoResult.poseName} · {gotoResult.submission.command.state}</strong>
              <code>{gotoResult.submission.command_id}</code>
              <span>
                Preflight {gotoResult.submission.preflight?.accepted === false ? 'rejected' : 'accepted'}
              </span>
              {gotoResult.submission.preflight?.checks?.length ? (
                <ul>
                  {gotoResult.submission.preflight.checks.map((check, index) => (
                    <li key={`${check.name}-${index}`}>
                      {check.passed ? 'PASS' : 'FAIL'} · {check.name} · {check.detail}
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
                  <p className="section-kicker">Validated entity detail</p>
                  <h3 id="library-detail-heading">
                    {detail.status === 'ready'
                      ? detail.entity.name
                      : `${detail.kind === 'pose' ? 'Pose' : 'Motion'} details`}
                  </h3>
                </div>
                <button className="command-button" onClick={closeDetail} type="button">Close details</button>
              </header>
              {detail.status === 'loading' ? <p role="status">Loading UUID {detail.id}…</p> : null}
              {detail.status === 'error' ? (
                <div className="library-notice library-notice--error" role="alert">
                  <TriangleAlert aria-hidden="true" />
                  <div>
                    <strong>Detail request failed</strong>
                    <span>{detail.message}</span>
                  </div>
                  <button className="command-button" onClick={() => void viewEntity(detail.kind, detail.id)} type="button">Retry</button>
                </div>
              ) : null}
              {detail.status === 'ready' && detail.kind === 'pose' ? (
                <dl className="library-detail__facts">
                  <div><dt>UUID</dt><dd><code>{detail.entity.id}</code></dd></div>
                  <div><dt>Schema / revision</dt><dd>{detail.entity.schema_version} · rev {detail.entity.revision}</dd></div>
                  <div><dt>Profile fingerprint</dt><dd><code>{detail.entity.snapshot.profile_fingerprint}</code></dd></div>
                  <div><dt>Kinematics fingerprint</dt><dd><code>{detail.entity.snapshot.kinematics_fingerprint}</code></dd></div>
                  <div><dt>State sequence</dt><dd>{detail.entity.snapshot.state_sequence ?? 'Imported · unavailable'}</dd></div>
                  <div><dt>Captured at</dt><dd>{detail.entity.snapshot.captured_at}</dd></div>
                </dl>
              ) : null}
              {detail.status === 'ready' && detail.kind === 'motion' ? (
                <>
                  <dl className="library-detail__facts">
                    <div><dt>UUID</dt><dd><code>{detail.entity.id}</code></dd></div>
                    <div><dt>Schema / revision</dt><dd>{detail.entity.schema_version} · rev {detail.entity.revision}</dd></div>
                    <div><dt>Robot variant</dt><dd>{detail.entity.robot_variant}</dd></div>
                    <div><dt>Playback defaults</dt><dd>{detail.entity.playback_defaults.speed_multiplier}× · {detail.entity.playback_defaults.loop ? 'loop' : 'no loop'}</dd></div>
                  </dl>
                  <ol className="motion-detail-keyframes">
                    {detail.entity.keyframes.map((keyframe, index) => (
                      <li key={keyframe.id}>
                        <strong>{index + 1}. {keyframe.label}</strong>
                        <span>{keyframe.pose_snapshot.robot_variant} · hold {keyframe.hold_s.toFixed(2)} s</span>
                        <span>
                          {keyframe.incoming_transition
                            ? `${keyframe.incoming_transition.motion_mode} · ${keyframe.incoming_transition.duration_s.toFixed(2)} s · ${keyframe.incoming_transition.easing}`
                            : 'Start keyframe · no incoming transition'}
                        </span>
                        <code>source {keyframe.source_pose_id ?? 'none (embedded snapshot)'}</code>
                      </li>
                    ))}
                  </ol>
                  <MotionPlaybackPanel
                    actionKey={actionKey}
                    disabledReason={playbackDisabledReason(detail.entity, runtime)}
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
                    stopDisabled={!online}
                  />
                  <p className="stage-boundary-note">Playback uses immutable embedded snapshots. Timeline authoring remains in the separate Studio workspace.</p>
                </>
              ) : null}
            </section>
          ) : null}

          {loadState === 'loading' && activePage.items.length === 0 ? (
            <div aria-live="polite" className="library-loading" role="status">
              <RefreshCw aria-hidden="true" />
              Loading {tab}…
            </div>
          ) : null}

          {loadState !== 'loading' && activePage.items.length === 0 && loadState === 'ready' ? (
            <div className="library-empty-state">
              <Archive aria-hidden="true" />
              <strong>{hasFilters ? `No ${tab} match these filters` : `No saved ${tab} yet`}</strong>
              <span>
                {hasFilters
                  ? 'Try a different search or tag filter.'
                  : tab === 'poses'
                    ? 'Capture the current Dry Run state to create the first Pose.'
                    : 'Select two compatible Poses above to create the first Motion.'}
              </span>
            </div>
          ) : null}

          {activePage.items.length > 0 ? (
            <>
              {loadState === 'loading' ? <p className="library-refreshing" role="status">Refreshing results…</p> : null}
              <div className="library-card-grid">
                {tab === 'poses'
                  ? posePage.items.map((pose) => (
                      <PoseCard
                        busy={anyActionBusy || !online}
                        deletePending={confirmation?.kind === 'delete-pose' && confirmation.id === pose.id}
                        gotoDisabledReason={gotoDisabledReason(pose, runtime)}
                        gotoPending={confirmation?.kind === 'goto-pose' && confirmation.id === pose.id}
                        key={pose.id}
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
                        playDisabledReason={playbackDisabledReason(motion, runtime)}
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
            <nav aria-label={`${tab} pages`} className="library-pagination">
              <button
                className="command-button"
                disabled={pageNumber <= 1 || loadState === 'loading'}
                onClick={() => setPageNumber((current) => Math.max(1, current - 1))}
                type="button"
              >
                Previous
              </button>
              <span>Page {pageNumber} of {totalPages}</span>
              <button
                className="command-button"
                disabled={pageNumber >= totalPages || loadState === 'loading'}
                onClick={() => setPageNumber((current) => Math.min(totalPages, current + 1))}
                type="button"
              >
                Next
              </button>
            </nav>
          ) : null}
        </section>
      </div>
    </div>
  );
}
