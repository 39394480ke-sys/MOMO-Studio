import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type {
  MotionEntity,
  MotionSummary,
  PlaybackStatus,
  PoseEntity,
  PoseSnapshot,
  PoseSummary,
  RobotVariant,
  TrajectoryPreflightReport,
  TrajectoryPreview,
} from '../api/types';
import {
  RuntimeStatusContext,
  SAFE_RUNTIME_STATUS,
  type RuntimeStatus,
} from '../components/runtimeStatusContext';
import { robotFor, stage3Ids, v2Profile } from '../test/stage3Fixtures';
import { LibraryPage } from './LibraryPage';

const START_ID = '11111111-1111-4111-8111-111111111111';
const END_ID = '22222222-2222-4222-8222-222222222222';
const MOTION_ID = '33333333-3333-4333-8333-333333333333';
const START_KEYFRAME_ID = '44444444-4444-4444-8444-444444444444';
const END_KEYFRAME_ID = '55555555-5555-4555-8555-555555555555';

function snapshot(x: number, variant: RobotVariant = 'V2'): PoseSnapshot {
  const jointIds = variant === 'V2' ? ['j10', 'j11', 'j12', 'j13', 'j14', 'j15'] : ['j11', 'j12', 'j13', 'j14', 'j15'];
  return {
    robot_variant: variant,
    joint_state: {
      positions: Object.fromEntries(jointIds.map((jointId, index) => [jointId, index + x])),
      units: Object.fromEntries(
        jointIds.map((jointId) => [jointId, jointId === 'j10' ? 'mm' : 'deg']),
      ) as Record<string, 'mm' | 'deg'>,
    },
    tcp_pose: {
      frame: 'base',
      position_mm: { x, y: 202, z: 303 },
      orientation_quaternion_xyzw: { x: 0, y: 0, z: 0, w: 1 },
    },
    profile_fingerprint: stage3Ids.profileFingerprint,
    kinematics_fingerprint: stage3Ids.kinematicsFingerprint,
    state_sequence: 7,
    hardware_snapshot: null,
    calibration_fingerprint: null,
    captured_at: '2026-08-24T00:00:00Z',
  };
}

function pose(id: string, name: string, x: number): PoseEntity {
  return {
    schema_version: '2.0.0',
    id,
    name,
    description: `${name} description`,
    tags: name === 'Ready' ? ['demo', 'reach'] : ['demo'],
    snapshot: snapshot(x),
    created_at: '2026-08-24T01:00:00Z',
    updated_at: '2026-08-24T01:00:00Z',
    revision: 1,
  };
}

function poseSummary(entity: PoseEntity): PoseSummary {
  return {
    id: entity.id,
    name: entity.name,
    description: entity.description,
    tags: entity.tags,
    robot_variant: entity.snapshot.robot_variant,
    joint_state: entity.snapshot.joint_state,
    tcp_pose: entity.snapshot.tcp_pose,
    profile_fingerprint: entity.snapshot.profile_fingerprint,
    kinematics_fingerprint: entity.snapshot.kinematics_fingerprint,
    state_sequence: entity.snapshot.state_sequence,
    created_at: entity.created_at,
    updated_at: entity.updated_at,
    revision: entity.revision,
  };
}

const startPose = pose(START_ID, 'Ready', 101);
const endPose = pose(END_ID, 'Drop', 151);

const fullMotion: MotionEntity = {
  schema_version: '2.0.0',
  id: MOTION_ID,
  name: 'Pick and place',
  description: 'Two embedded snapshots',
  robot_variant: 'V2',
  keyframes: [
    {
      id: START_KEYFRAME_ID,
      label: 'Start',
      pose_snapshot: startPose.snapshot,
      source_pose_id: START_ID,
      hold_s: 0.25,
      incoming_transition: null,
    },
    {
      id: END_KEYFRAME_ID,
      label: 'End',
      pose_snapshot: endPose.snapshot,
      source_pose_id: END_ID,
      hold_s: 0,
      incoming_transition: {
        duration_s: 2,
        motion_mode: 'JOINT',
        easing: 'SMOOTHSTEP',
      },
    },
  ],
  playback_defaults: { loop: false, speed_multiplier: 1 },
  tags: ['demo'],
  source_metadata: null,
  created_at: '2026-08-24T02:00:00Z',
  updated_at: '2026-08-24T02:00:00Z',
  revision: 4,
};

const motionSummary: MotionSummary = {
  id: fullMotion.id,
  name: fullMotion.name,
  description: fullMotion.description,
  robot_variant: fullMotion.robot_variant,
  keyframe_count: 2,
  total_duration_s: 2.25,
  motion_types: ['JOINT'],
  tags: fullMotion.tags,
  created_at: fullMotion.created_at,
  updated_at: fullMotion.updated_at,
  revision: fullMotion.revision,
};

const passedPreflight: TrajectoryPreflightReport = {
  passed: true,
  digest: 'sha256:prepared-trajectory',
  motion_id: MOTION_ID,
  motion_revision: fullMotion.revision,
  duration_s: 2.25,
  sample_count: 46,
  segment_count: 2,
  sample_rate_hz: 20,
  violations: [],
  checks: [
    { name: 'profile', passed: true, detail: 'Profile fingerprint matches' },
    { name: 'limits', passed: true, detail: 'All samples remain within limits' },
  ],
  prepared_at: '2026-08-24T02:30:00Z',
};

const trajectoryPreview: TrajectoryPreview = {
  digest: passedPreflight.digest as string,
  motion_id: MOTION_ID,
  duration_s: 2.25,
  sample_rate_hz: 20,
  sample_count: 46,
  segments: [
    {
      segment_index: 0,
      motion_mode: 'JOINT',
      start_time_s: 0,
      end_time_s: 2,
      sample_count: 41,
      start_keyframe_id: START_KEYFRAME_ID,
      end_keyframe_id: END_KEYFRAME_ID,
    },
    {
      segment_index: 1,
      motion_mode: 'HOLD',
      start_time_s: 2,
      end_time_s: 2.25,
      sample_count: 5,
      start_keyframe_id: END_KEYFRAME_ID,
      end_keyframe_id: END_KEYFRAME_ID,
    },
  ],
  joint_series: {
    j10: [
      { time_s: 0, value: 101, unit: 'mm' },
      { time_s: 2.25, value: 151, unit: 'mm' },
    ],
    j11: [
      { time_s: 0, value: -20, unit: 'deg' },
      { time_s: 2.25, value: 35, unit: 'deg' },
    ],
  },
  tcp_path: [
    { time_s: 0, x_mm: 101, y_mm: 202, z_mm: 303 },
    { time_s: 2.25, x_mm: 151, y_mm: 212, z_mm: 318 },
  ],
  keyframe_markers: [
    { keyframe_id: START_KEYFRAME_ID, label: 'Start', time_s: 0, sample_index: 0 },
    { keyframe_id: END_KEYFRAME_ID, label: 'End', time_s: 2, sample_index: 40 },
  ],
};

const idlePlayback: PlaybackStatus = {
  session_id: null,
  state: 'IDLE',
  motion_id: null,
  trajectory_digest: null,
  progress: 0,
  elapsed_s: 0,
  duration_s: 0,
  current_keyframe_id: null,
  current_segment_index: null,
  current_sample_index: null,
  loop: false,
  rate: 1,
  error: null,
  updated_at: '2026-08-24T02:00:00Z',
  hardware_accessed: false,
};

function runtime(overrides: Partial<RuntimeStatus> = {}): RuntimeStatus {
  return {
    ...SAFE_RUNTIME_STATUS,
    backend: 'connected',
    stale: false,
    robot: robotFor('V2', true),
    profile: {
      profile: v2Profile,
      fingerprint: stage3Ids.profileFingerprint,
      kinematics_fingerprint: stage3Ids.kinematicsFingerprint,
      real_eligible: false,
    },
    ...overrides,
  } as RuntimeStatus;
}

interface RequestRecord {
  path: string;
  method: string;
  body: unknown;
}

interface BackendOptions {
  empty?: boolean;
  listError?: boolean;
  duplicateConflict?: boolean;
  changedSourceRevision?: boolean;
  preflightPassed?: boolean;
  playbackStatus?: PlaybackStatus;
  playbackGetResponse?: Promise<Response>;
  preflightResponse?: Promise<Response>;
  previewResponse?: Promise<Response>;
  pauseErrorOnce?: boolean;
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

function mockLibraryBackend(options: BackendOptions = {}) {
  const requests: RequestRecord[] = [];
  let playbackStatus = options.playbackStatus ?? idlePlayback;
  let delayedPlaybackResponse = options.playbackGetResponse;
  let pauseErrorPending = options.pauseErrorOnce ?? false;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://momo.test');
    const path = url.pathname.replace(/^\/api\/v1/, '');
    const method = init?.method ?? 'GET';
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined;
    requests.push({ path: `${path}${url.search}`, method, body });

    if (path === '/poses' && method === 'GET') {
      if (options.listError) {
        return jsonResponse({ code: 'ENTITY_INVALID', message: 'Repository index unavailable', details: {} }, 500);
      }
      const filtered = url.searchParams.get('search') === 'missing';
      const items = options.empty || filtered ? [] : [poseSummary(startPose), poseSummary(endPose)];
      return jsonResponse({ items, page: 1, page_size: Number(url.searchParams.get('page_size')), total: items.length });
    }
    if (path === '/motions' && method === 'GET') {
      return jsonResponse({ items: options.empty ? [] : [motionSummary], page: 1, page_size: 24, total: options.empty ? 0 : 1 });
    }
    if (path === `/poses/${START_ID}` && method === 'GET') {
      return jsonResponse(options.changedSourceRevision ? { ...startPose, revision: 2 } : startPose);
    }
    if (path === `/poses/${END_ID}` && method === 'GET') return jsonResponse(endPose);
    if (path === `/motions/${MOTION_ID}` && method === 'GET') return jsonResponse(fullMotion);
    if (path === `/motions/${MOTION_ID}/preflight` && method === 'POST') {
      playbackStatus = {
        ...idlePlayback,
        state: 'PREFLIGHTING',
        motion_id: MOTION_ID,
      };
      if (options.preflightResponse) return options.preflightResponse;
      if (options.preflightPassed === false) {
        playbackStatus = {
          ...playbackStatus,
          state: 'FAULTED',
          error: 'Trajectory preflight rejected',
        };
        return jsonResponse({
          ...passedPreflight,
          passed: false,
          digest: null,
          sample_count: 0,
          violations: [{
            code: 'JOINT_LIMIT',
            message: 'Joint J11 exceeds its configured limit in a deliberately long violation message that must wrap safely.',
            segment_index: 0,
            keyframe_id: END_KEYFRAME_ID,
            check: 'joint_limits',
            sample_index: 21,
            joint_id: 'j11',
            actual: 93,
            limit: 90,
            unit: 'deg',
            blocking: true,
          }],
          checks: [{ name: 'limits', passed: false, detail: 'One or more samples exceed limits' }],
        });
      }
      playbackStatus = {
        ...idlePlayback,
        state: 'READY',
        motion_id: MOTION_ID,
        trajectory_digest: passedPreflight.digest,
        duration_s: passedPreflight.duration_s,
      };
      return jsonResponse(passedPreflight);
    }
    if (path === `/trajectory/${encodeURIComponent(passedPreflight.digest as string)}/preview` && method === 'GET') {
      if (options.previewResponse) return options.previewResponse;
      return jsonResponse(trajectoryPreview);
    }
    if (path === `/motions/${MOTION_ID}/play` && method === 'POST') {
      playbackStatus = {
        ...idlePlayback,
        session_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        state: 'PLAYING',
        motion_id: MOTION_ID,
        trajectory_digest: passedPreflight.digest,
        duration_s: passedPreflight.duration_s,
        current_keyframe_id: START_KEYFRAME_ID,
        current_segment_index: 0,
        current_sample_index: 0,
        loop: (body as { loop: boolean }).loop,
        rate: (body as { rate: number }).rate,
      };
      return jsonResponse(playbackStatus, 202);
    }
    if (path === '/playback' && method === 'GET') {
      if (delayedPlaybackResponse) {
        const response = delayedPlaybackResponse;
        delayedPlaybackResponse = undefined;
        return response;
      }
      return jsonResponse(playbackStatus);
    }
    if (path === '/playback/pause' && method === 'POST') {
      if (pauseErrorPending) {
        pauseErrorPending = false;
        return jsonResponse({
          code: 'MOTION_CONFLICT',
          message: 'Pause was rejected because the runner changed state',
          details: { state: playbackStatus.state },
        }, 409);
      }
      playbackStatus = { ...playbackStatus, state: 'PAUSED' };
      return jsonResponse(playbackStatus);
    }
    if (path === '/playback/resume' && method === 'POST') {
      playbackStatus = { ...playbackStatus, state: 'PLAYING' };
      return jsonResponse(playbackStatus);
    }
    if (path === '/playback/stop' && method === 'POST') {
      playbackStatus = { ...playbackStatus, state: 'STOPPED' };
      return jsonResponse(playbackStatus);
    }
    if (path === '/playback/rate' && method === 'PUT') {
      playbackStatus = { ...playbackStatus, rate: (body as { rate: number }).rate };
      return jsonResponse(playbackStatus);
    }
    if (path === '/playback/loop' && method === 'PUT') {
      playbackStatus = { ...playbackStatus, loop: (body as { loop: boolean }).loop };
      return jsonResponse(playbackStatus);
    }
    if (path === '/poses/capture' && method === 'POST') {
      return jsonResponse({ ...startPose, id: '66666666-6666-4666-8666-666666666666', name: (body as { name: string }).name }, 201);
    }
    if (path === `/poses/${START_ID}/duplicate` && method === 'POST') {
      if (options.duplicateConflict) {
        return jsonResponse({ code: 'REVISION_CONFLICT', message: 'Expected revision 1 but found 2', details: { expected: 1, actual: 2 } }, 409);
      }
      return jsonResponse({ ...startPose, id: '77777777-7777-4777-8777-777777777777', name: 'Ready copy' }, 201);
    }
    if (path === `/poses/${START_ID}/goto` && method === 'POST') {
      return jsonResponse({
        command_id: '88888888-8888-4888-8888-888888888888',
        status: 'ACCEPTED',
        preflight: {
          accepted: true,
          checks: [{ name: 'profile_fingerprint', passed: true, detail: 'Snapshot matches active profile' }],
          warnings: ['Dry Run only'],
        },
        hardware_accessed: false,
      }, 202);
    }
    if (path === `/poses/${START_ID}` && method === 'DELETE') {
      return { ok: true, status: 204, json: vi.fn() } as unknown as Response;
    }
    if (path === '/motions' && method === 'POST') {
      return jsonResponse({ ...fullMotion, name: (body as { name: string }).name }, 201);
    }
    if (path === `/motions/${MOTION_ID}/duplicate` && method === 'POST') {
      return jsonResponse({ ...fullMotion, id: '99999999-9999-4999-8999-999999999999', name: 'Pick and place copy' }, 201);
    }
    if (path === `/motions/${MOTION_ID}` && method === 'DELETE') {
      return { ok: true, status: 204, json: vi.fn() } as unknown as Response;
    }
    throw new Error(`Unhandled ${method} ${path}${url.search}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  return {
    fetchMock,
    requests,
    requestsMatching: (fragment: string) => requests.filter((request) => request.path.includes(fragment)),
    setNextPlaybackResponse: (response: Promise<Response>) => {
      delayedPlaybackResponse = response;
    },
    setPlaybackStatus: (next: PlaybackStatus) => {
      playbackStatus = next;
    },
  };
}

function renderLibrary(status: RuntimeStatus = runtime()) {
  return render(
    <MemoryRouter initialEntries={['/library']}>
      <RuntimeStatusContext.Provider value={status}>
        <LibraryPage />
      </RuntimeStatusContext.Provider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('Stage 5 Library', () => {
  it('blocks Goto and Playback in Commissioning READ ONLY without reusing Dry Run routes', async () => {
    const user = userEvent.setup();
    const backend = mockLibraryBackend();
    renderLibrary(runtime({
      controlMode: 'REAL',
      hardwareAccessPolicy: 'READ_ONLY',
      realMotionEnabled: false,
    }));

    expect((await screen.findAllByText(/Commissioning READ ONLY permits diagnostics and calibration only/)).length)
      .toBeGreaterThan(0);
    expect(screen.getAllByRole('button', { name: 'Goto' })[0]).toBeDisabled();
    await user.click(screen.getByRole('tab', { name: 'MOTIONS' }));
    const play = await screen.findByRole('button', { name: 'Play' });
    expect(play).toBeDisabled();
    expect(screen.getAllByText(/Commissioning READ ONLY permits no playback/).length)
      .toBeGreaterThan(0);
    expect(backend.requestsMatching('/goto').filter((request) => request.method === 'POST')).toHaveLength(0);
    expect(
      backend.requestsMatching('/play').filter(
        (request) => request.path.endsWith('/play') && request.method === 'POST',
      ),
    ).toHaveLength(0);
  });

  it('renders Pose summaries, loads explicit detail, and uses UUID-only Studio links', async () => {
    const user = userEvent.setup();
    const backend = mockLibraryBackend();
    renderLibrary();

    expect(await screen.findByRole('heading', { name: 'Ready' })).toBeVisible();
    expect(screen.getAllByText('Pose · V2')[0]).toBeVisible();
    expect(screen.getByText(/X 101.0 · Y 202.0 · Z 303.0 mm/)).toBeVisible();
    expect(screen.getByText(/J10 101.0 mm/)).toBeVisible();
    expect(screen.getAllByText(`ID ${START_ID}`)[0]).toBeVisible();
    expect(screen.getAllByRole('link', { name: 'Add to Studio' })[0]).toHaveAttribute(
      'href',
      `/studio?pose=${START_ID}`,
    );

    await user.click(screen.getAllByRole('button', { name: 'View details' })[0]);
    expect(await screen.findByRole('dialog', { name: 'Ready' })).toBeVisible();
    expect(screen.getByText(stage3Ids.profileFingerprint)).toBeVisible();
    expect(backend.requestsMatching(`/poses/${START_ID}`)).toHaveLength(1);
    await user.click(screen.getByRole('button', { name: 'Close details' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('closes and invalidates Pose detail work when switching to Motions', async () => {
    const user = userEvent.setup();
    let resolvePoseDetail!: (response: Response) => void;
    const pendingPoseDetail = new Promise<Response>((resolve) => {
      resolvePoseDetail = resolve;
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://momo.test');
      const path = url.pathname.replace(/^\/api\/v1/, '');
      const method = init?.method ?? 'GET';
      if (path === `/poses/${START_ID}` && method === 'GET') return pendingPoseDetail;
      if (path === '/poses' && method === 'GET') {
        return jsonResponse({
          items: [poseSummary(startPose), poseSummary(endPose)],
          page: 1,
          page_size: Number(url.searchParams.get('page_size')),
          total: 2,
        });
      }
      if (path === '/motions' && method === 'GET') {
        return jsonResponse({ items: [motionSummary], page: 1, page_size: 24, total: 1 });
      }
      throw new Error(`Unhandled ${method} ${path}${url.search}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderLibrary();

    expect(await screen.findByRole('heading', { name: 'Ready' })).toBeVisible();
    await user.click(screen.getAllByRole('button', { name: 'View details' })[0]);
    expect(screen.getByRole('dialog', { name: 'Pose details' })).toBeVisible();

    await user.click(screen.getByRole('tab', { name: 'MOTIONS' }));
    expect(await screen.findByRole('heading', { name: 'Pick and place' })).toBeVisible();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await act(async () => {
      resolvePoseDetail(jsonResponse(startPose));
      await pendingPoseDetail;
    });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('captures normalized metadata and enforces public entity bounds', async () => {
    const user = userEvent.setup();
    const backend = mockLibraryBackend();
    renderLibrary();
    await screen.findByRole('heading', { name: 'Ready' });

    await user.type(screen.getByLabelText('Name'), '  Inspection  ');
    await user.type(screen.getByLabelText('Description'), 'A coherent snapshot');
    await user.type(screen.getByLabelText(/Tags · comma separated/), ' demo, reach, demo ');
    await user.click(screen.getByRole('button', { name: 'Capture current pose' }));

    expect(await screen.findByText(/Captured Pose “Inspection”/)).toBeVisible();
    expect(backend.requestsMatching('/poses/capture')[0]?.body).toEqual({
      name: 'Inspection',
      description: 'A coherent snapshot',
      tags: ['demo', 'reach'],
    });
    expect(screen.getByLabelText('Description')).toHaveAttribute('maxlength', '5000');

    await user.type(screen.getByLabelText('Name'), 'Too many tags');
    await user.type(
      screen.getByLabelText(/Tags · comma separated/),
      Array.from({ length: 33 }, (_, index) => `tag${index}`).join(','),
    );
    await user.click(screen.getByRole('button', { name: 'Capture current pose' }));
    expect(await screen.findByText('Use no more than 32 tags.')).toBeVisible();
    expect(backend.requestsMatching('/poses/capture')).toHaveLength(1);
  });

  it('disables capture while a robot lifecycle action is pending', async () => {
    mockLibraryBackend();
    renderLibrary(runtime({ pendingAction: 'connect' }));

    expect(await screen.findByRole('heading', { name: 'Ready' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Capture current pose' })).toBeDisabled();
    expect(screen.getByLabelText('Name')).toBeDisabled();
  });

  it('locks every Library mutation form while one action is in flight', async () => {
    const user = userEvent.setup();
    let resolveCapture!: (response: Response) => void;
    const pendingCapture = new Promise<Response>((resolve) => {
      resolveCapture = resolve;
    });
    const backend = mockLibraryBackend();
    backend.fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://momo.test');
      if (url.pathname.endsWith('/poses/capture') && (init?.method ?? 'GET') === 'POST') {
        return pendingCapture;
      }
      return jsonResponse({ items: [], page: 1, page_size: 24, total: 0 });
    });
    renderLibrary();

    await screen.findByText('No saved poses yet');
    await user.type(screen.getByLabelText('Name'), 'Pending capture');
    await user.click(screen.getByRole('button', { name: 'Capture current pose' }));
    expect(screen.getByRole('button', { name: 'Capturing…' })).toBeDisabled();

    await user.click(screen.getByRole('tab', { name: 'MOTIONS' }));
    expect(await screen.findByRole('button', { name: 'Creating…' })).toBeDisabled();
    expect(screen.getByLabelText('Name')).toBeDisabled();

    await act(async () => {
      resolveCapture(jsonResponse({
        ...startPose,
        id: '66666666-6666-4666-8666-666666666666',
        name: 'Pending capture',
      }, 201));
      await pendingCapture;
    });
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Creating…' })).not.toBeInTheDocument());
  });

  it('confirms Goto inline, submits revision intent, and shows command preflight evidence', async () => {
    const user = userEvent.setup();
    const backend = mockLibraryBackend();
    renderLibrary();
    await screen.findByRole('heading', { name: 'Ready' });

    await user.click(screen.getAllByRole('button', { name: 'Goto' })[0]);
    expect(screen.getByRole('alertdialog', { name: 'Goto “Ready”?' })).toBeVisible();
    expect(backend.requestsMatching('/goto')).toHaveLength(0);
    await user.click(screen.getByRole('button', { name: 'Confirm Dry Run Goto' }));

    expect(await screen.findByText(/Goto submitted for “Ready”; command state is ACCEPTED/)).toBeVisible();
    expect(screen.getByText('Preflight accepted')).toBeVisible();
    expect(screen.getByText(/PASS · profile_fingerprint/)).toBeVisible();
    expect(backend.requestsMatching(`/poses/${START_ID}/goto`)[0]?.body).toEqual(
      expect.objectContaining({ expected_revision: 1, duration_s: 1, speed_scale: 0.5 }),
    );
  });

  it('uses inline delete confirmation and sends UUID plus expected revision', async () => {
    const user = userEvent.setup();
    const backend = mockLibraryBackend();
    renderLibrary();
    await screen.findByRole('heading', { name: 'Ready' });

    await user.click(screen.getAllByRole('button', { name: 'Delete' })[0]);
    expect(screen.getByRole('alertdialog', { name: 'Delete “Ready”?' })).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(backend.requestsMatching(`poses/${START_ID}?expected_revision`)).toHaveLength(0);
    await user.click(screen.getAllByRole('button', { name: 'Delete' })[0]);
    await user.click(screen.getByRole('button', { name: 'Confirm delete' }));

    expect(await screen.findByText(/Deleted Pose “Ready”/)).toBeVisible();
    expect(backend.requestsMatching(`/poses/${START_ID}?expected_revision=1`)).toHaveLength(1);
  });

  it('returns to the last valid page after deleting the sole item on a trailing page', async () => {
    const user = userEvent.setup();
    let deleted = false;
    const requestedPages: number[] = [];
    const firstPageItems = Array.from({ length: 24 }, (_, index) => ({
      ...poseSummary(endPose),
      id: `aaaaaaaa-aaaa-4aaa-8aaa-${String(index + 1).padStart(12, '0')}`,
      name: `First page Pose ${index + 1}`,
    }));
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://momo.test');
      const path = url.pathname.replace(/^\/api\/v1/, '');
      const method = init?.method ?? 'GET';
      if (path === '/poses' && method === 'GET') {
        const requestedPage = Number(url.searchParams.get('page'));
        requestedPages.push(requestedPage);
        return jsonResponse({
          items: requestedPage === 1 ? firstPageItems : deleted ? [] : [poseSummary(startPose)],
          page: requestedPage,
          page_size: 24,
          total: deleted ? 24 : 25,
        });
      }
      if (path === `/poses/${START_ID}` && method === 'DELETE') {
        deleted = true;
        return { ok: true, status: 204, json: vi.fn() } as unknown as Response;
      }
      throw new Error(`Unhandled ${method} ${path}${url.search}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderLibrary();

    expect(await screen.findByRole('heading', { name: 'First page Pose 1' })).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(await screen.findByRole('heading', { name: 'Ready' })).toBeVisible();
    expect(screen.queryByRole('heading', { name: 'First page Pose 1' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Delete' }));
    await user.click(screen.getByRole('button', { name: 'Confirm delete' }));

    expect(await screen.findByRole('heading', { name: 'First page Pose 1' })).toBeVisible();
    expect(screen.queryByText('No saved poses yet')).not.toBeInTheDocument();
    await waitFor(() => expect(requestedPages).toEqual([1, 2, 2, 1]));
  });

  it('creates a playable Motion from two freshly loaded full Pose snapshots', async () => {
    const user = userEvent.setup();
    const backend = mockLibraryBackend();
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: 'MOTIONS' }));
    expect(await screen.findByRole('heading', { name: 'Pick and place' })).toBeVisible();

    await user.type(screen.getByLabelText('Name'), 'Transfer');
    await user.type(screen.getByLabelText('Description'), 'Stored transfer');
    await user.selectOptions(screen.getByLabelText('Start Pose'), START_ID);
    await user.selectOptions(screen.getByLabelText('End Pose'), END_ID);
    await user.selectOptions(screen.getByLabelText('Transition type'), 'CARTESIAN_LINEAR');
    await user.clear(screen.getByLabelText(/Duration · seconds/));
    await user.type(screen.getByLabelText(/Duration · seconds/), '3.5');
    await user.type(screen.getByLabelText(/Tags · comma separated/), 'transfer, demo');
    await user.click(screen.getByRole('button', { name: 'Create motion' }));

    expect(await screen.findByText(/Created Motion “Transfer” with 2 embedded keyframes/)).toBeVisible();
    const request = backend.requests.find((entry) => entry.path === '/motions' && entry.method === 'POST');
    expect(request?.body).toEqual(expect.objectContaining({
      name: 'Transfer',
      robot_variant: 'V2',
      tags: ['transfer', 'demo'],
      keyframes: [
        expect.objectContaining({ source_pose_id: START_ID, incoming_transition: null }),
        expect.objectContaining({
          source_pose_id: END_ID,
          incoming_transition: {
            duration_s: 3.5,
            motion_mode: 'CARTESIAN_LINEAR',
            easing: 'SMOOTHSTEP',
          },
        }),
      ],
    }));
    expect((request?.body as { keyframes: Array<{ pose_snapshot: { hardware_snapshot: unknown } }> }).keyframes[0].pose_snapshot.hardware_snapshot).toBeNull();
    expect(backend.requestsMatching(`/poses/${START_ID}`)).toHaveLength(1);
    expect(backend.requestsMatching(`/poses/${END_ID}`)).toHaveLength(1);
  });

  it('renders bounded Motion summaries and opens full playback detail only on demand', async () => {
    const user = userEvent.setup();
    const backend = mockLibraryBackend();
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: 'MOTIONS' }));
    expect(await screen.findByText('2.25 s')).toBeVisible();
    expect(screen.getByText('JOINT')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Play' })).toBeEnabled();
    expect(screen.getByRole('link', { name: 'Open in Studio' })).toHaveAttribute(
      'href',
      `/studio?motion=${MOTION_ID}`,
    );

    expect(backend.requestsMatching(`/motions/${MOTION_ID}`)).toHaveLength(0);
    await user.click(screen.getByRole('button', { name: 'Play' }));
    expect(await screen.findByRole('dialog', { name: 'Pick and place' })).toBeVisible();
    expect(screen.getByText(/Start keyframe · no incoming transition/)).toBeVisible();
    expect(screen.getByText(/JOINT · 2.00 s · SMOOTHSTEP/)).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Preflight & playback' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Run preflight' })).toBeEnabled();
    expect(backend.requestsMatching(`/motions/${MOTION_ID}`)).toHaveLength(1);
  });

  it('preflights, renders the responsive trajectory, and drives every playback transition', async () => {
    const user = userEvent.setup();
    const backend = mockLibraryBackend();
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: 'MOTIONS' }));
    await user.click(await screen.findByRole('button', { name: 'Play' }));
    const dialog = await screen.findByRole('dialog', { name: 'Pick and place' });
    const controls = within(dialog);

    await user.click(controls.getByRole('button', { name: 'Run preflight' }));
    expect(await controls.findByText('Preflight passed')).toBeVisible();
    const report = controls.getByRole('region', { name: 'Preflight result' });
    expect(within(report).getByText('2.25 s')).toBeVisible();
    expect(within(report).getByText('46')).toBeVisible();
    expect(within(report).getByText('2')).toBeVisible();
    expect(within(report).getByText('20 Hz')).toBeVisible();
    expect(await controls.findByRole('heading', { name: 'Trajectory preview' })).toBeVisible();
    expect(controls.getByRole('img', { name: /Joint trajectory over 2.3 seconds/ })).toHaveAttribute(
      'viewBox',
      '0 0 720 250',
    );
    expect(controls.getByText('JOINT · segment 1')).toBeVisible();
    expect(controls.getByText('HOLD · segment 2')).toBeVisible();
    expect(controls.getAllByText(/101.0–151.0 mm/).length).toBeGreaterThan(0);
    expect(controls.getByText(/303.0–318.0 mm/)).toBeVisible();
    expect(backend.requestsMatching(`/motions/${MOTION_ID}/preflight`)[0]?.body).toEqual({
      expected_revision: 4,
    });
    await waitFor(() => expect(controls.getByRole('button', { name: 'Play' })).toBeEnabled());

    await user.selectOptions(controls.getByLabelText('Playback rate'), '1.5');
    await user.click(controls.getByRole('checkbox', { name: 'Loop playback' }));
    await user.click(controls.getByRole('button', { name: 'Play' }));
    await waitFor(() => expect(controls.getAllByText('PLAYING').length).toBeGreaterThan(0));
    expect(backend.requestsMatching(`/motions/${MOTION_ID}/play`)[0]?.body).toEqual({
      expected_revision: 4,
      trajectory_digest: passedPreflight.digest,
      loop: true,
      rate: 1.5,
    });
    expect(screen.getByLabelText('Name')).toBeDisabled();
    expect(screen.getByRole('link', { name: 'Open in Studio' })).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByRole('button', { name: 'Duplicate' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Delete' })).toBeDisabled();

    await user.click(controls.getByRole('button', { name: 'Pause' }));
    await waitFor(() => expect(controls.getAllByText('PAUSED').length).toBeGreaterThan(0));
    expect(controls.getByRole('button', { name: 'Resume' })).toBeEnabled();
    await user.click(controls.getByRole('button', { name: 'Resume' }));
    await waitFor(() => expect(controls.getAllByText('PLAYING').length).toBeGreaterThan(0));

    await user.selectOptions(controls.getByLabelText('Playback rate'), '2');
    await waitFor(() => expect(
      backend.requests.filter(
        (request) => request.path === '/playback/rate' && request.method === 'PUT',
      ).at(-1)?.body,
    ).toEqual({ rate: 2 }));
    await user.click(controls.getByRole('checkbox', { name: 'Loop playback' }));
    await waitFor(() => expect(
      backend.requests.filter(
        (request) => request.path === '/playback/loop' && request.method === 'PUT',
      ).at(-1)?.body,
    ).toEqual({ loop: false }));

    await user.click(controls.getByRole('button', { name: 'Stop' }));
    await waitFor(() => expect(controls.getAllByText('STOPPED').length).toBeGreaterThan(0));
    expect(backend.requests.some((request) => request.path === '/playback/pause')).toBe(true);
    expect(backend.requests.some((request) => request.path === '/playback/resume')).toBe(true);
    expect(backend.requests.some((request) => request.path === '/playback/stop')).toBe(true);
  });

  it('shows structured preflight violations and never enables Play without a digest', async () => {
    const user = userEvent.setup();
    mockLibraryBackend({ preflightPassed: false });
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: 'MOTIONS' }));
    await user.click(await screen.findByRole('button', { name: 'Play' }));
    const dialog = await screen.findByRole('dialog', { name: 'Pick and place' });
    const controls = within(dialog);

    await user.click(controls.getByRole('button', { name: 'Run preflight' }));
    expect(await controls.findByText('Preflight rejected')).toBeVisible();
    expect(controls.getByText('JOINT_LIMIT')).toBeVisible();
    expect(controls.getByText(/deliberately long violation message/)).toBeVisible();
    expect(controls.getByText(`Keyframe ${END_KEYFRAME_ID}`)).toBeVisible();
    expect(controls.getByText('Segment 1')).toBeVisible();
    expect(controls.getByText('Check joint_limits')).toBeVisible();
    expect(controls.getByText('Sample 21')).toBeVisible();
    expect(controls.getByText(/Joint j11 · actual 93 deg · limit 90 deg/)).toBeVisible();
    expect(controls.getByRole('button', { name: 'Play' })).toBeDisabled();
    expect(controls.queryByRole('heading', { name: 'Trajectory preview' })).not.toBeInTheDocument();
  });

  it('shows polled progress and lets the active Motion reopen while other Library actions stay locked', async () => {
    const user = userEvent.setup();
    mockLibraryBackend({
      playbackStatus: {
        ...idlePlayback,
        session_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        state: 'PLAYING',
        motion_id: MOTION_ID,
        trajectory_digest: passedPreflight.digest,
        progress: 0.42,
        elapsed_s: 0.95,
        duration_s: 2.25,
        current_keyframe_id: END_KEYFRAME_ID,
        current_segment_index: 1,
        current_sample_index: 19,
        loop: true,
        rate: 1.5,
      },
    });
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: 'MOTIONS' }));
    const cardPlay = await screen.findByRole('button', { name: 'Play' });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Duplicate' })).toBeDisabled());
    expect(cardPlay).toBeEnabled();
    await user.click(cardPlay);
    const dialog = await screen.findByRole('dialog', { name: 'Pick and place' });
    const controls = within(dialog);

    expect(controls.getByText('42%')).toBeVisible();
    expect(controls.getByText('0.95 s / 2.25 s')).toBeVisible();
    expect(controls.getByText('End')).toBeVisible();
    expect(controls.getByText('19')).toBeVisible();
    expect(controls.getByRole('checkbox', { name: 'Loop playback' })).toBeChecked();
    expect(controls.getByLabelText('Playback rate')).toHaveValue('1.5');
    expect(controls.getByRole('button', { name: 'Stop' })).toBeEnabled();
    expect(controls.getByRole('button', { name: 'Run preflight' })).toBeDisabled();
  });

  it('keeps polling playback after switching to Poses so completed sessions release the Library lock', async () => {
    const user = userEvent.setup();
    const playing: PlaybackStatus = {
      ...idlePlayback,
      session_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      state: 'PLAYING',
      motion_id: MOTION_ID,
      trajectory_digest: passedPreflight.digest,
      duration_s: passedPreflight.duration_s,
    };
    const backend = mockLibraryBackend({ playbackStatus: playing });
    renderLibrary();

    await user.click(screen.getByRole('tab', { name: 'MOTIONS' }));
    await screen.findByRole('heading', { name: 'Pick and place' });
    await waitFor(() => expect(screen.getByLabelText('Name')).toBeDisabled());
    await user.click(screen.getByRole('tab', { name: 'POSES' }));
    await screen.findByRole('heading', { name: 'Ready' });
    expect(screen.getByLabelText('Name')).toBeDisabled();

    backend.setPlaybackStatus({
      ...playing,
      state: 'COMPLETED',
      progress: 1,
      elapsed_s: passedPreflight.duration_s,
    });

    await waitFor(
      () => expect(screen.getByLabelText('Name')).toBeEnabled(),
      { timeout: 2_000 },
    );
    expect(screen.getByRole('button', { name: 'Capture current pose' })).toBeEnabled();
  });

  it('keeps a rejected playback command visible across healthy polls until it is dismissed', async () => {
    const user = userEvent.setup();
    const backend = mockLibraryBackend({
      pauseErrorOnce: true,
      playbackStatus: {
        ...idlePlayback,
        session_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        state: 'PLAYING',
        motion_id: MOTION_ID,
        trajectory_digest: passedPreflight.digest,
        duration_s: passedPreflight.duration_s,
      },
    });
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: 'MOTIONS' }));
    await user.click(await screen.findByRole('button', { name: 'Play' }));
    const controls = within(await screen.findByRole('dialog', { name: 'Pick and place' }));
    await waitFor(() => expect(controls.getByRole('button', { name: 'Pause' })).toBeEnabled());

    await user.click(controls.getByRole('button', { name: 'Pause' }));
    expect(await controls.findByText('Pause was rejected because the runner changed state')).toBeVisible();
    const pollsAfterError = backend.requests.filter(
      (request) => request.path === '/playback' && request.method === 'GET',
    ).length;
    await waitFor(() => expect(backend.requests.filter(
      (request) => request.path === '/playback' && request.method === 'GET',
    ).length).toBeGreaterThan(pollsAfterError), { timeout: 2_000 });
    expect(controls.getByText('Pause was rejected because the runner changed state')).toBeVisible();

    await user.click(controls.getByRole('button', { name: 'Dismiss playback error' }));
    expect(controls.queryByText('Pause was rejected because the runner changed state')).not.toBeInTheDocument();
  });

  it('gates controls exactly during PREFLIGHTING, STOPPING, and terminal playback states', async () => {
    const user = userEvent.setup();
    const preflighting: PlaybackStatus = {
      ...idlePlayback,
      state: 'PREFLIGHTING',
      motion_id: MOTION_ID,
    };
    const backend = mockLibraryBackend({ playbackStatus: preflighting });
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: 'MOTIONS' }));
    await user.click(await screen.findByRole('button', { name: 'Play' }));
    const controls = within(await screen.findByRole('dialog', { name: 'Pick and place' }));
    await waitFor(() => expect(controls.getAllByText('PREFLIGHTING').length).toBeGreaterThan(0));

    expect(controls.getByRole('button', { name: 'Run preflight' })).toBeDisabled();
    expect(controls.getByRole('button', { name: 'Play' })).toBeDisabled();
    expect(controls.getByRole('button', { name: 'Pause' })).toBeDisabled();
    expect(controls.getByRole('button', { name: 'Resume' })).toBeDisabled();
    expect(controls.getByRole('button', { name: 'Stop' })).toBeEnabled();
    expect(controls.getByLabelText('Playback rate')).toBeDisabled();
    expect(controls.getByRole('checkbox', { name: 'Loop playback' })).toBeDisabled();

    backend.setPlaybackStatus({ ...preflighting, state: 'STOPPING' });
    await waitFor(
      () => expect(controls.getAllByText('STOPPING').length).toBeGreaterThan(0),
      { timeout: 2_000 },
    );
    expect(controls.getByRole('button', { name: 'Stop' })).toBeDisabled();
    expect(controls.getByLabelText('Playback rate')).toBeDisabled();
    expect(controls.getByRole('checkbox', { name: 'Loop playback' })).toBeDisabled();

    backend.setPlaybackStatus({ ...preflighting, state: 'COMPLETED', progress: 1 });
    await waitFor(
      () => expect(controls.getAllByText('COMPLETED').length).toBeGreaterThan(0),
      { timeout: 2_000 },
    );
    expect(controls.getByRole('button', { name: 'Play' })).toBeDisabled();
    expect(controls.getByRole('button', { name: 'Stop' })).toBeDisabled();
    expect(controls.getByLabelText('Playback rate')).toBeDisabled();
    expect(controls.getByRole('checkbox', { name: 'Loop playback' })).toBeDisabled();
  });

  it('lets Stop supersede an in-flight preflight and ignores its late result', async () => {
    const user = userEvent.setup();
    let resolvePreflight!: (response: Response) => void;
    const pendingPreflight = new Promise<Response>((resolve) => {
      resolvePreflight = resolve;
    });
    const backend = mockLibraryBackend({ preflightResponse: pendingPreflight });
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: 'MOTIONS' }));
    await user.click(await screen.findByRole('button', { name: 'Play' }));
    const controls = within(await screen.findByRole('dialog', { name: 'Pick and place' }));

    await user.click(controls.getByRole('button', { name: 'Run preflight' }));
    await waitFor(
      () => expect(controls.getByRole('button', { name: 'Stop' })).toBeEnabled(),
      { timeout: 2_000 },
    );
    expect(controls.getByRole('button', { name: 'Preflighting…' })).toBeDisabled();
    expect(controls.getByLabelText('Playback rate')).toBeDisabled();

    await user.click(controls.getByRole('button', { name: 'Stop' }));
    await waitFor(() => expect(backend.requestsMatching('/playback/stop')).toHaveLength(1));
    await waitFor(() => expect(controls.getAllByText('STOPPED').length).toBeGreaterThan(0));

    await act(async () => {
      resolvePreflight(jsonResponse(passedPreflight));
      await pendingPreflight;
    });
    expect(controls.queryByText('Preflight passed')).not.toBeInTheDocument();
    expect(controls.getAllByText('STOPPED').length).toBeGreaterThan(0);
    expect(controls.getByRole('button', { name: 'Run preflight' })).toBeEnabled();
  });

  it('ignores an older playback poll that resolves after a Play command response', async () => {
    const user = userEvent.setup();
    let resolveOldPoll!: (response: Response) => void;
    const oldPoll = new Promise<Response>((resolve) => {
      resolveOldPoll = resolve;
    });
    const backend = mockLibraryBackend();
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: 'MOTIONS' }));
    await user.click(await screen.findByRole('button', { name: 'Play' }));
    const dialog = await screen.findByRole('dialog', { name: 'Pick and place' });
    const controls = within(dialog);
    await user.click(controls.getByRole('button', { name: 'Run preflight' }));
    await controls.findByText('Preflight passed');
    await waitFor(() => expect(controls.getByRole('button', { name: 'Play' })).toBeEnabled());
    const pollsBeforeDelay = backend.requests.filter(
      (request) => request.path === '/playback' && request.method === 'GET',
    ).length;
    backend.setNextPlaybackResponse(oldPoll);
    await waitFor(() => expect(backend.requests.filter(
      (request) => request.path === '/playback' && request.method === 'GET',
    ).length).toBeGreaterThan(pollsBeforeDelay), { timeout: 2_000 });
    await user.click(controls.getByRole('button', { name: 'Play' }));
    await waitFor(() => expect(controls.getAllByText('PLAYING').length).toBeGreaterThan(0));

    await act(async () => {
      resolveOldPoll(jsonResponse(idlePlayback));
      await oldPoll;
    });
    expect(controls.getAllByText('PLAYING').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Duplicate' })).toBeDisabled();
  });

  it('disables preflight and card playback for offline-quality robot state', async () => {
    const user = userEvent.setup();
    mockLibraryBackend();
    renderLibrary(runtime({
      stale: true,
      robot: { ...robotFor('V2', true), stale: true } as NonNullable<RuntimeStatus['robot']>,
    }));
    await user.click(screen.getByRole('tab', { name: 'MOTIONS' }));
    expect(await screen.findByRole('button', { name: 'Play' })).toBeDisabled();
    expect(screen.getByText('Playback unavailable · robot state is stale')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'View details' }));
    const dialog = await screen.findByRole('dialog', { name: 'Pick and place' });
    expect(within(dialog).getByRole('button', { name: 'Run preflight' })).toBeDisabled();
    expect(within(dialog).getByText('Playback unavailable · robot state is stale')).toBeVisible();
  });

  it('ignores a late trajectory preview after Motion details close', async () => {
    const user = userEvent.setup();
    let resolvePreview!: (response: Response) => void;
    const pendingPreview = new Promise<Response>((resolve) => {
      resolvePreview = resolve;
    });
    const backend = mockLibraryBackend({ previewResponse: pendingPreview });
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: 'MOTIONS' }));
    await user.click(await screen.findByRole('button', { name: 'Play' }));
    const dialog = await screen.findByRole('dialog', { name: 'Pick and place' });
    await user.click(within(dialog).getByRole('button', { name: 'Run preflight' }));
    expect(await within(dialog).findByText('Loading bounded trajectory preview…')).toBeVisible();
    await user.click(within(dialog).getByRole('button', { name: 'Close details' }));

    await act(async () => {
      resolvePreview(jsonResponse(trajectoryPreview));
      await pendingPreview;
    });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Trajectory preview' })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Play' })).toBeEnabled());
    expect(backend.requestsMatching('/trajectory/')).toHaveLength(1);
  });

  it('shows an explicit conflict, keeps the Motion draft, and offers Reload', async () => {
    const user = userEvent.setup();
    const backend = mockLibraryBackend({ changedSourceRevision: true });
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: 'MOTIONS' }));
    await screen.findByRole('heading', { name: 'Pick and place' });

    await user.type(screen.getByLabelText('Name'), 'Draft survives');
    await user.selectOptions(screen.getByLabelText('Start Pose'), START_ID);
    await user.selectOptions(screen.getByLabelText('End Pose'), END_ID);
    await user.click(screen.getByRole('button', { name: 'Create motion' }));

    expect(await screen.findByText('Revision conflict')).toBeVisible();
    expect(screen.getByText(/selected Pose changed/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Reload' })).toBeVisible();
    expect(screen.getByLabelText('Name')).toHaveValue('Draft survives');
    expect(screen.getByLabelText('Start Pose')).toHaveValue(START_ID);
    expect(screen.getByLabelText('End Pose')).toHaveValue(END_ID);
    expect(backend.requests.filter((entry) => entry.path === '/motions' && entry.method === 'POST')).toHaveLength(0);
  });

  it('distinguishes true empty, filtered empty, general error, and offline states', async () => {
    const user = userEvent.setup();
    mockLibraryBackend({ empty: true });
    const first = renderLibrary();
    expect(await screen.findByText('No saved poses yet')).toBeVisible();
    first.unmount();

    mockLibraryBackend();
    const second = renderLibrary();
    await screen.findByRole('heading', { name: 'Ready' });
    await user.type(screen.getByLabelText('Search'), 'missing');
    expect(await screen.findByText('No poses match these filters')).toBeVisible();
    second.unmount();

    mockLibraryBackend({ listError: true });
    const third = renderLibrary();
    expect(await screen.findByText('Library request failed')).toBeVisible();
    expect(screen.getByText('Repository index unavailable')).toBeVisible();
    third.unmount();

    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    renderLibrary(runtime({ backend: 'unavailable', robot: null, profile: null }));
    expect(screen.getByText('Library offline')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Capture current pose' })).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('keeps cached cards but disables Goto and mutations when the runtime goes offline', async () => {
    mockLibraryBackend();
    const view = render(
      <MemoryRouter initialEntries={['/library']}>
        <RuntimeStatusContext.Provider value={runtime()}>
          <LibraryPage />
        </RuntimeStatusContext.Provider>
      </MemoryRouter>,
    );
    expect(await screen.findByRole('heading', { name: 'Ready' })).toBeVisible();

    view.rerender(
      <MemoryRouter initialEntries={['/library']}>
        <RuntimeStatusContext.Provider value={runtime({ backend: 'unavailable' })}>
          <LibraryPage />
        </RuntimeStatusContext.Provider>
      </MemoryRouter>,
    );

    expect(await screen.findByText('Library offline')).toBeVisible();
    expect(screen.getAllByRole('button', { name: 'Goto' })[0]).toBeDisabled();
    expect(screen.getAllByText(/Goto unavailable · backend offline/)[0]).toBeVisible();
    expect(screen.getAllByRole('button', { name: 'Duplicate' })[0]).toBeDisabled();
    expect(screen.getAllByRole('button', { name: 'Delete' })[0]).toBeDisabled();
  });

  it('shows initial loading and ignores a late response from an aborted filter generation', async () => {
    let resolveInitial!: (response: Response) => void;
    let resolveSlow!: (response: Response) => void;
    let resolveFast!: (response: Response) => void;
    const initial = new Promise<Response>((resolve) => { resolveInitial = resolve; });
    const slow = new Promise<Response>((resolve) => { resolveSlow = resolve; });
    const fast = new Promise<Response>((resolve) => { resolveFast = resolve; });
    const requestedSearches: string[] = [];
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://momo.test');
      const search = url.searchParams.get('search') ?? '';
      requestedSearches.push(search);
      if (!search) return initial;
      if (search === 'slow') return slow;
      if (search === 'fast') return fast;
      return Promise.resolve(jsonResponse({ items: [], page: 1, page_size: 24, total: 0 }));
    });
    vi.stubGlobal('fetch', fetchMock);
    renderLibrary();

    expect(screen.getByText('Loading poses…')).toBeVisible();
    await act(async () => {
      resolveInitial(jsonResponse({ items: [poseSummary(startPose)], page: 1, page_size: 24, total: 1 }));
      await initial;
    });
    expect(await screen.findByRole('heading', { name: 'Ready' })).toBeVisible();

    fireEvent.change(screen.getByLabelText('Search'), { target: { value: 'slow' } });
    await waitFor(() => expect(requestedSearches).toContain('slow'));
    fireEvent.change(screen.getByLabelText('Search'), { target: { value: 'fast' } });
    await waitFor(() => expect(requestedSearches).toContain('fast'));

    const fastResult = { ...poseSummary(endPose), name: 'Fast result' };
    await act(async () => {
      resolveFast(jsonResponse({ items: [fastResult], page: 1, page_size: 24, total: 1 }));
      await fast;
    });
    expect(await screen.findByRole('heading', { name: 'Fast result' })).toBeVisible();

    const slowResult = { ...poseSummary(startPose), name: 'Slow result' };
    await act(async () => {
      resolveSlow(jsonResponse({ items: [slowResult], page: 1, page_size: 24, total: 1 }));
      await slow;
    });
    expect(screen.getByRole('heading', { name: 'Fast result' })).toBeVisible();
    expect(screen.queryByRole('heading', { name: 'Slow result' })).not.toBeInTheDocument();
  });
});
