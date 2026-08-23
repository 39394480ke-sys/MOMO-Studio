import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type {
  MotionEntity,
  MotionSummary,
  PoseEntity,
  PoseSnapshot,
  PoseSummary,
  RobotVariant,
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
      id: '44444444-4444-4444-8444-444444444444',
      label: 'Start',
      pose_snapshot: startPose.snapshot,
      source_pose_id: START_ID,
      hold_s: 0.25,
      incoming_transition: null,
    },
    {
      id: '55555555-5555-4555-8555-555555555555',
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

describe('Stage 4 Library', () => {
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

  it('renders bounded Motion summaries, keeps Play gated, and loads full keyframes only on View', async () => {
    const user = userEvent.setup();
    const backend = mockLibraryBackend();
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: 'MOTIONS' }));
    expect(await screen.findByText('2.25 s')).toBeVisible();
    expect(screen.getByText('JOINT')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Play' })).toBeDisabled();
    expect(screen.getByText('Play is unavailable until Stage 5.')).toBeVisible();
    expect(screen.getByRole('link', { name: 'Open in Studio' })).toHaveAttribute(
      'href',
      `/studio?motion=${MOTION_ID}`,
    );

    expect(backend.requestsMatching(`/motions/${MOTION_ID}`)).toHaveLength(0);
    await user.click(screen.getByRole('button', { name: 'View details' }));
    expect(await screen.findByRole('dialog', { name: 'Pick and place' })).toBeVisible();
    expect(screen.getByText(/Start keyframe · no incoming transition/)).toBeVisible();
    expect(screen.getByText(/JOINT · 2.00 s · SMOOTHSTEP/)).toBeVisible();
    expect(backend.requestsMatching(`/motions/${MOTION_ID}`)).toHaveLength(1);
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
