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
  getPose,
  getPoses,
  gotoPose,
} from '../api/client';
import type {
  CapturePoseRequest,
  EntityListQuery,
  EntityPage,
  MotionCommandSubmission,
  MotionEntity,
  MotionSummary,
  PoseEntity,
  PoseSummary,
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
import { PoseCard } from '../features/library/PoseCard';
import { libraryIdempotencyKey, parseTags } from '../features/library/libraryFormat';

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

  const activePage = tab === 'poses' ? posePage : motionPage;
  const totalPages = Math.max(1, Math.ceil(activePage.total / activePage.page_size));
  const hasFilters = deferredSearch.trim().length > 0 || parseTags(deferredTags).length > 0;
  const online = runtime.backend === 'connected';
  const anyActionBusy = actionKey !== null;

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
    if (actionInFlight.current) return false;
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

  async function viewEntity(kind: 'pose' | 'motion', id: string) {
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
        setDetail({ status: 'ready', kind, entity: entity as MotionEntity });
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
    setDetail(null);
  }

  return (
    <div className="page library-page">
      <PageIntro
        title="Library"
        description="Capture immutable Pose snapshots and organize playable Motion records."
        detail="All Goto commands remain Dry Run and pass through the reviewed motion safety gateway."
      />

      <div className="library-stage-banner">
        <Archive aria-hidden="true" />
        <div>
          <strong>Stage 4 · Versioned file library</strong>
          <span>UUID identity · optimistic revisions · no client file paths</span>
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
                  <p className="stage-boundary-note">Detail is read-only in Stage 4. Timeline authoring remains gated to Stage 6.</p>
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
                        onTagSelect={selectTag}
                        onView={(selected) => void viewEntity('motion', selected.id)}
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
