import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  abandonMotionDraftSaveIntent,
  captureStudioSnapshot,
  compileMotionDraft,
  createMotionDraft,
  forkMotionDraft,
  gotoMotionDraftKeyframe,
  updateMotionDraft,
} from './client';
import type { MotionDraft, PoseSnapshot } from './types';

const DRAFT_ID = '11111111-1111-4111-8111-111111111111';
const FRAME_ID = '22222222-2222-4222-8222-222222222222';

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

function snapshot(): PoseSnapshot {
  return {
    robot_variant: 'V1',
    joint_state: {
      positions: { j11: 0, j12: 0, j13: 0, j14: 0, j15: 0 },
      units: { j11: 'deg', j12: 'deg', j13: 'deg', j14: 'deg', j15: 'deg' },
    },
    tcp_pose: {
      frame: 'base',
      position_mm: { x: 100, y: 200, z: 300 },
      orientation_quaternion_xyzw: { x: 0, y: 0, z: 0, w: 1 },
    },
    profile_fingerprint: 'a'.repeat(64),
    kinematics_fingerprint: 'b'.repeat(64),
    state_sequence: 1,
    hardware_snapshot: null,
    calibration_fingerprint: null,
    captured_at: '2026-08-24T00:00:00Z',
  };
}

function draft(): MotionDraft {
  return {
    schema_version: '1.0.0',
    id: DRAFT_ID,
    source_motion_id: null,
    source_motion_revision: null,
    name: 'Draft',
    description: '',
    robot_variant: 'V1',
    keyframes: [],
    playback_defaults: { loop: false, speed_multiplier: 1 },
    tags: [],
    source_metadata: null,
    trusted_legacy_snapshot_sha256: [],
    editor_metadata: {
      selected_keyframe_id: null,
      playhead_s: 0,
      timeline_zoom: 1,
      timeline_scroll_s: 0,
      default_edges: [],
    },
    save_intent: null,
    revision: 1,
    created_at: '2026-08-24T00:00:00Z',
    updated_at: '2026-08-24T00:00:00Z',
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('Stage 6 Studio API client', () => {
  it('uses bounded server-owned draft and capture routes with complete autosave payloads', async () => {
    const requests: Array<{ path: string; method: string; body: unknown }> = [];
    const entity: MotionDraft = {
      ...draft(),
      source_metadata: {
        importer: 'momo.tools.import_legacy_actions',
        source_file_name: 'legacy-motion.json',
        source_sha256: 'c'.repeat(64),
        legacy_id: 'legacy-motion-1',
        legacy_source: 'web_record:arm_a',
        warnings: ['Legacy timing was normalized.'],
      },
      trusted_legacy_snapshot_sha256: ['d'.repeat(64)],
      save_intent: {
        operation_id: '33333333-3333-4333-8333-333333333333',
        kind: 'SAVE_AS',
        target_motion_id: '44444444-4444-4444-8444-444444444444',
        target_motion_revision: 1,
        expected_motion_revision: null,
        target_name: 'Recovered target',
        target_motion_created_at: '2026-08-24T00:00:01Z',
        started_at: '2026-08-24T00:00:02Z',
      },
    };
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).replace('/api/v1', '');
      const method = init?.method ?? 'GET';
      const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined;
      requests.push({ path, method, body });
      if (path === '/studio/drafts') return response(entity, 201);
      if (path === `/studio/drafts/${DRAFT_ID}/fork`) {
        return response({ ...entity, id: '55555555-5555-4555-8555-555555555555', revision: 1 }, 201);
      }
      if (path === `/studio/drafts/${DRAFT_ID}`) return response({ ...entity, revision: 2 });
      if (path === `/studio/drafts/${DRAFT_ID}/save-intent/abandon`) {
        return response({ ...entity, save_intent: null, revision: 2 });
      }
      if (path === '/studio/capture') return response(snapshot());
      if (path === `/studio/drafts/${DRAFT_ID}/keyframes/${FRAME_ID}/goto`) {
        return response({
          command_id: 'studio-goto-command',
          status: 'ACCEPTED',
          preflight: null,
          hardware_accessed: false,
        }, 202);
      }
      throw new Error(`unexpected path ${path}`);
    }));

    const created = await createMotionDraft({ name: 'Draft', robot_variant: 'V1' });
    expect(created.source_metadata?.source_file_name).toBe('legacy-motion.json');
    expect(created.trusted_legacy_snapshot_sha256).toEqual(['d'.repeat(64)]);
    expect(created.save_intent?.target_motion_created_at).toBe('2026-08-24T00:00:01Z');
    await updateMotionDraft(DRAFT_ID, {
      expected_revision: 1,
      name: 'Draft',
      description: '',
      robot_variant: 'V1',
      keyframes: [],
      playback_defaults: { loop: false, speed_multiplier: 1 },
      tags: [],
      editor_metadata: entity.editor_metadata,
    });
    const forked = await forkMotionDraft(DRAFT_ID, { expected_revision: 2 });
    expect(forked.source_metadata).toEqual(entity.source_metadata);
    expect(forked.trusted_legacy_snapshot_sha256).toEqual(['d'.repeat(64)]);
    expect(await captureStudioSnapshot()).toEqual(snapshot());
    await abandonMotionDraftSaveIntent(DRAFT_ID, {
      expected_revision: 1,
      operation_id: '33333333-3333-4333-8333-333333333333',
      confirm: 'ABANDON_FORMAL_SAVE',
    });
    await gotoMotionDraftKeyframe(DRAFT_ID, FRAME_ID, {
      expected_revision: 2,
      duration_s: 1,
      speed_scale: 0.25,
      idempotency_key: 'studio-goto-idempotency',
    });

    expect(requests).toEqual([
      { path: '/studio/drafts', method: 'POST', body: { name: 'Draft', robot_variant: 'V1' } },
      {
        path: `/studio/drafts/${DRAFT_ID}`,
        method: 'PUT',
        body: {
          expected_revision: 1,
          name: 'Draft',
          description: '',
          robot_variant: 'V1',
          keyframes: [],
          playback_defaults: { loop: false, speed_multiplier: 1 },
          tags: [],
          editor_metadata: entity.editor_metadata,
        },
      },
      {
        path: `/studio/drafts/${DRAFT_ID}/fork`,
        method: 'POST',
        body: { expected_revision: 2 },
      },
      { path: '/studio/capture', method: 'POST', body: {} },
      {
        path: `/studio/drafts/${DRAFT_ID}/save-intent/abandon`,
        method: 'POST',
        body: {
          expected_revision: 1,
          operation_id: '33333333-3333-4333-8333-333333333333',
          confirm: 'ABANDON_FORMAL_SAVE',
        },
      },
      {
        path: `/studio/drafts/${DRAFT_ID}/keyframes/${FRAME_ID}/goto`,
        method: 'POST',
        body: {
          expected_revision: 2,
          duration_s: 1,
          speed_scale: 0.25,
          idempotency_key: 'studio-goto-idempotency',
        },
      },
    ]);
  });

  it('normalizes compiler output and rejects any draft response marked executable', async () => {
    const result = {
      draft_id: DRAFT_ID,
      draft_revision: 4,
      preflight: {
        passed: true,
        digest: 'sha256:draft',
        motion_id: DRAFT_ID,
        motion_revision: 1,
        duration_s: 1,
        sample_count: 21,
        segment_count: 1,
        sample_rate_hz: 20,
        violations: [],
        checks: [{ name: 'limits', passed: true, detail: 'safe' }],
        prepared_at: '2026-08-24T00:00:00Z',
        real_motion_ready: false,
        field_acceptance_ready: false,
        hardware_accessed: false,
      },
      preview: {
        digest: 'sha256:draft',
        motion_id: DRAFT_ID,
        duration_s: 1,
        sample_rate_hz: 20,
        sample_count: 21,
        segments: [],
        joint_series: {},
        tcp_path: [],
        keyframe_markers: [],
      },
      executable: false,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(result))
      .mockResolvedValueOnce(response({ ...result, executable: true }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(compileMotionDraft(DRAFT_ID, {
      expected_revision: 4,
      sample_rate_hz: 20,
    })).resolves.toMatchObject({
      draft_id: DRAFT_ID,
      draft_revision: 4,
      executable: false,
      preflight: { passed: true, digest: 'sha256:draft' },
      preview: { sample_count: 21 },
    });
    await expect(compileMotionDraft(DRAFT_ID, { expected_revision: 4 })).rejects.toThrow(
      'invalid non-executable draft compile result',
    );
  });

  it('preserves structured revision conflicts for Reload and Save As decisions', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      code: 'REVISION_CONFLICT',
      message: 'Draft revision changed',
      details: { entity: 'MotionDraft', expected_revision: 1, actual_revision: 2 },
    }, 409)));

    const request = updateMotionDraft(DRAFT_ID, {
      expected_revision: 1,
      name: 'Draft',
      description: '',
      robot_variant: 'V1',
      keyframes: [],
      playback_defaults: { loop: false, speed_multiplier: 1 },
      tags: [],
      editor_metadata: draft().editor_metadata,
    });
    await expect(request).rejects.toMatchObject({
      status: 409,
      code: 'REVISION_CONFLICT',
      details: { entity: 'MotionDraft', expected_revision: 1, actual_revision: 2 },
    });
  });
});
