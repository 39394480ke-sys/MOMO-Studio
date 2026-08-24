import { API_BASE_URL } from './config';
import type {
  AbandonMotionDraftSaveIntentRequest,
  BootstrapResponse,
  CalibrationStatus,
  CapturePoseRequest,
  CartesianJogRequest,
  CreateMotionRequest,
  CreateMotionDraftRequest,
  CreatePoseRequest,
  DiagnosticsResponse,
  DuplicateEntityRequest,
  EntityListQuery,
  EntityPage,
  ErrorResponse,
  ForwardKinematicsResponse,
  ForkMotionDraftRequest,
  GotoPoseRequest,
  GotoMotionDraftKeyframeRequest,
  HealthResponse,
  HomeRequest,
  InverseKinematicsRequest,
  InverseKinematicsResponse,
  JogSessionResponse,
  JogSessionStartRequest,
  JointJogStepRequest,
  MetaResponse,
  MotionCommandState,
  MotionCommandStatus,
  MotionCommandSubmission,
  MotionEntity,
  MotionDraft,
  MotionDraftCompileResponse,
  MotionDraftSaveResponse,
  MotionDraftSummary,
  MotionDraftValidation,
  MotionSummary,
  MotionPreflightReport,
  MotionStopResponse,
  MoveJointsRequest,
  MovePoseRequest,
  PlaybackState,
  PlaybackStatus,
  PlayMotionRequest,
  PoseEntity,
  PoseSnapshot,
  PoseSummary,
  PreflightMotionRequest,
  ProfileResponse,
  RobotStatus,
  RobotVariant,
  TrajectoryCheck,
  TrajectoryKeyframeMarker,
  TrajectoryPreflightReport,
  TrajectoryPreview,
  TrajectoryPreviewSegment,
  TrajectoryViolation,
  CompileMotionDraftRequest,
  SaveAsMotionDraftRequest,
  SaveMotionDraftRequest,
  UpdateMotionDraftRequest,
  UpdateMotionRequest,
  UpdatePoseRequest,
} from './types';

const COMMAND_STATES = new Set<MotionCommandState>([
  'ACCEPTED',
  'PREFLIGHTING',
  'READY',
  'RUNNING',
  'PLAYING',
  'PAUSED',
  'STOPPING',
  'STOPPED',
  'CANCELLED',
  'COMPLETED',
  'FAULTED',
  'REJECTED',
]);

const PLAYBACK_STATES = new Set<PlaybackState>([
  'IDLE',
  'PREFLIGHTING',
  'READY',
  'PLAYING',
  'PAUSED',
  'STOPPING',
  'STOPPED',
  'COMPLETED',
  'FAULTED',
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function commandState(value: unknown): MotionCommandState {
  if (typeof value !== 'string' || !COMMAND_STATES.has(value as MotionCommandState)) {
    throw new TypeError('Backend returned an invalid motion command state');
  }
  return value as MotionCommandState;
}

function commandProgress(value: unknown): number | undefined {
  if (value === undefined) return undefined;
  if (
    typeof value !== 'number' ||
    !Number.isFinite(value) ||
    value < 0 ||
    value > 1
  ) {
    throw new TypeError('Backend returned an invalid motion command progress');
  }
  return value;
}

function finiteNumber(value: unknown, field: string, minimum = 0): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < minimum) {
    throw new TypeError(`Backend returned an invalid ${field}`);
  }
  return value;
}

function signedFiniteNumber(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new TypeError(`Backend returned an invalid ${field}`);
  }
  return value;
}

function integerValue(value: unknown, field: string, minimum = 0): number {
  const numeric = finiteNumber(value, field, minimum);
  if (!Number.isInteger(numeric)) throw new TypeError(`Backend returned an invalid ${field}`);
  return numeric;
}

function optionalString(value: unknown, field: string): string | null | undefined {
  if (value === undefined) return undefined;
  if (value === null) return null;
  const parsed = stringValue(value);
  if (!parsed) throw new TypeError(`Backend returned an invalid ${field}`);
  return parsed;
}

function optionalIndex(value: unknown, field: string): number | null | undefined {
  if (value === undefined) return undefined;
  if (value === null) return null;
  return integerValue(value, field);
}

function optionalSignedNumber(value: unknown, field: string): number | null | undefined {
  if (value === undefined) return undefined;
  if (value === null) return null;
  return signedFiniteNumber(value, field);
}

function optionalDomainUnit(value: unknown, field: string): 'deg' | 'mm' | null | undefined {
  if (value === undefined || value === null) return value;
  if (value !== 'deg' && value !== 'mm') {
    throw new TypeError(`Backend returned an invalid ${field}`);
  }
  return value;
}

function optionalBoolean(value: unknown, field: string): boolean | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== 'boolean') throw new TypeError(`Backend returned an invalid ${field}`);
  return value;
}

function arrayValue(value: unknown, field: string): unknown[] {
  if (!Array.isArray(value)) throw new TypeError(`Backend returned invalid ${field}`);
  return value;
}

function boundedArray(value: unknown, field: string, maximum: number): unknown[] {
  const parsed = arrayValue(value, field);
  if (parsed.length > maximum) throw new TypeError(`Backend returned oversized ${field}`);
  return parsed;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly requestId: string | null;

  constructor(options: {
    status: number;
    code: string;
    message: string;
    details?: unknown;
    requestId?: string | null;
  }) {
    super(options.message);
    this.name = 'ApiError';
    this.status = options.status;
    this.code = options.code;
    this.details = options.details ?? {};
    this.requestId = options.requestId ?? null;
  }
}

function errorEnvelope(value: unknown): Partial<ErrorResponse> {
  if (!isRecord(value)) return {};
  const detail = isRecord(value.detail) ? value.detail : null;
  const source = detail ?? value;
  return {
    code: stringValue(source.code) ?? undefined,
    message:
      stringValue(source.message) ??
      (typeof value.detail === 'string' ? value.detail : undefined),
    details: source.details,
    request_id: stringValue(source.request_id),
  };
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      // A proxy or network appliance may return a non-JSON error page.
    }
    const envelope = errorEnvelope(payload);
    throw new ApiError({
      status: response.status,
      code: envelope.code ?? `HTTP_${response.status}`,
      message:
        envelope.message ?? `MOMO Studio API request failed with ${response.status}.`,
      details: envelope.details,
      requestId: envelope.request_id,
    });
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function postJson<T>(path: string, body?: unknown, init?: RequestInit): Promise<T> {
  return requestJson<T>(path, {
    ...init,
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

function patchJson<T>(path: string, body: unknown): Promise<T> {
  return requestJson<T>(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

function putJson<T>(path: string, body: unknown): Promise<T> {
  return requestJson<T>(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

function entityListPath(path: '/poses' | '/motions', query: EntityListQuery): string {
  const params = new URLSearchParams({
    page: String(Math.max(1, Math.trunc(query.page))),
    page_size: String(Math.min(50, Math.max(1, Math.trunc(query.page_size)))),
    sort: query.sort,
    order: query.order,
  });
  const search = query.search?.trim();
  if (search && search.length > 200) {
    throw new RangeError('Library search must be 200 characters or fewer');
  }
  if (search) params.set('search', search);
  const tags = Array.from(
    new Set(query.tags?.map((value) => value.trim()).filter(Boolean) ?? []),
  );
  if (tags.length > 32) throw new RangeError('Library filters accept at most 32 tags');
  if (tags.some((tag) => tag.length > 64)) {
    throw new RangeError('Library filter tags must be 64 characters or fewer');
  }
  for (const tag of tags) {
    params.append('tag', tag);
  }
  return `${path}?${params.toString()}`;
}

function entityPath(path: '/poses' | '/motions', entityId: string): string {
  return `${path}/${encodeURIComponent(entityId)}`;
}

function studioDraftPath(draftId: string): string {
  return `/studio/drafts/${encodeURIComponent(draftId)}`;
}

function asPreflight(value: unknown): MotionPreflightReport | null {
  return isRecord(value) ? (value as unknown as MotionPreflightReport) : null;
}

export function normalizeCommandStatus(value: unknown): MotionCommandStatus {
  if (!isRecord(value)) {
    throw new TypeError('Backend returned an invalid motion command status');
  }
  const commandId = stringValue(value.command_id);
  if (!commandId) throw new TypeError('Motion command status is missing command_id');
  return {
    command_id: commandId,
    state: commandState(value.state ?? value.status),
    source: stringValue(value.source) ?? undefined,
    progress: commandProgress(value.progress),
    message: stringValue(value.message),
    error: stringValue(value.error),
    preflight: asPreflight(value.preflight),
    started_at: stringValue(value.started_at),
    updated_at: stringValue(value.updated_at) ?? undefined,
    finished_at: stringValue(value.finished_at),
    hardware_accessed: value.hardware_accessed === false ? false : undefined,
  };
}

function normalizeSubmission(value: unknown): MotionCommandSubmission {
  if (!isRecord(value)) throw new TypeError('Backend returned an invalid motion response');
  const nested = isRecord(value.command) ? value.command : null;
  const commandId = stringValue(value.command_id) ?? stringValue(nested?.command_id);
  if (!commandId) throw new TypeError('Motion response is missing command_id');
  const preflight = asPreflight(value.preflight ?? nested?.preflight);
  const command = normalizeCommandStatus({
    command_id: commandId,
    state: nested?.state ?? nested?.status ?? value.state ?? value.status,
    progress: nested?.progress ?? value.progress ?? 0,
    source: nested?.source,
    message: nested?.message ?? value.message,
    error: nested?.error ?? value.error,
    preflight,
  });
  return {
    command_id: commandId,
    command,
    preflight,
    hardware_accessed: value.hardware_accessed === false ? false : undefined,
  };
}

function playbackState(value: unknown): PlaybackState {
  if (typeof value !== 'string' || !PLAYBACK_STATES.has(value as PlaybackState)) {
    throw new TypeError('Backend returned an invalid playback state');
  }
  return value as PlaybackState;
}

function normalizeViolation(value: unknown): TrajectoryViolation {
  if (!isRecord(value)) throw new TypeError('Backend returned an invalid preflight violation');
  const code = stringValue(value.code);
  const message = stringValue(value.message);
  if (!code || !message) throw new TypeError('Backend returned an invalid preflight violation');
  return {
    code,
    message,
    segment_index: optionalIndex(value.segment_index, 'violation segment index'),
    keyframe_id: optionalString(value.keyframe_id, 'violation keyframe ID'),
    check: optionalString(value.check, 'violation check'),
    sample_index: optionalIndex(value.sample_index, 'violation sample index'),
    joint_id: optionalString(value.joint_id, 'violation joint ID'),
    actual: optionalSignedNumber(value.actual, 'violation actual value'),
    limit: optionalSignedNumber(value.limit, 'violation limit'),
    unit: optionalDomainUnit(value.unit, 'violation unit'),
    blocking: optionalBoolean(value.blocking, 'violation blocking flag'),
  };
}

function normalizeCheck(value: unknown): TrajectoryCheck {
  if (!isRecord(value)) throw new TypeError('Backend returned an invalid preflight check');
  const name = stringValue(value.name);
  const detail = stringValue(value.detail);
  if (!name || !detail || typeof value.passed !== 'boolean') {
    throw new TypeError('Backend returned an invalid preflight check');
  }
  return { name, passed: value.passed, detail };
}

export function normalizeTrajectoryPreflight(value: unknown): TrajectoryPreflightReport {
  if (!isRecord(value)) throw new TypeError('Backend returned an invalid trajectory preflight');
  const motionId = stringValue(value.motion_id);
  if (!motionId || typeof value.passed !== 'boolean') {
    throw new TypeError('Backend returned an invalid trajectory preflight');
  }
  const digest = value.digest === null ? null : stringValue(value.digest);
  if (value.passed && !digest) {
    throw new TypeError('Passed trajectory preflight is missing its digest');
  }
  if (!value.passed && value.digest !== null) {
    throw new TypeError('Rejected trajectory preflight must not include a digest');
  }
  const sampleCount = integerValue(value.sample_count, 'preflight sample count');
  const segmentCount = integerValue(value.segment_count, 'preflight segment count');
  if (sampleCount > 20_000 || segmentCount > 2_000) {
    throw new TypeError('Backend returned an oversized trajectory preflight');
  }
  return {
    passed: value.passed,
    digest,
    motion_id: motionId,
    motion_revision: integerValue(value.motion_revision, 'preflight motion revision', 1),
    duration_s: finiteNumber(value.duration_s, 'preflight duration'),
    sample_count: sampleCount,
    segment_count: segmentCount,
    sample_rate_hz: finiteNumber(value.sample_rate_hz, 'preflight sample rate', Number.EPSILON),
    violations: boundedArray(value.violations, 'preflight violations', 2_000).map(normalizeViolation),
    checks: boundedArray(value.checks, 'preflight checks', 2_000).map(normalizeCheck),
    prepared_at: optionalString(value.prepared_at, 'preflight timestamp'),
  };
}

export function normalizePlaybackStatus(value: unknown): PlaybackStatus {
  if (!isRecord(value)) throw new TypeError('Backend returned an invalid playback status');
  const progress = finiteNumber(value.progress, 'playback progress');
  const rate = finiteNumber(value.rate, 'playback rate', 0.25);
  const updatedAt = stringValue(value.updated_at);
  if (progress > 1) throw new TypeError('Backend returned an invalid playback progress');
  if (rate > 2) throw new TypeError('Backend returned an invalid playback rate');
  if (typeof value.loop !== 'boolean' || !updatedAt || value.hardware_accessed !== false) {
    throw new TypeError('Backend returned an invalid playback status');
  }
  return {
    session_id: optionalString(value.session_id, 'playback session ID'),
    state: playbackState(value.state),
    motion_id: optionalString(value.motion_id, 'playback motion ID'),
    trajectory_digest: optionalString(value.trajectory_digest, 'trajectory digest'),
    progress,
    elapsed_s: finiteNumber(value.elapsed_s, 'playback elapsed time'),
    duration_s: finiteNumber(value.duration_s, 'playback duration'),
    current_keyframe_id: optionalString(value.current_keyframe_id, 'current keyframe ID'),
    current_segment_index: optionalIndex(value.current_segment_index, 'current segment index'),
    current_sample_index: optionalIndex(value.current_sample_index, 'current sample index'),
    loop: value.loop,
    rate,
    error: optionalString(value.error, 'playback error'),
    updated_at: updatedAt,
    hardware_accessed: false,
  };
}

function normalizePreviewSegment(value: unknown): TrajectoryPreviewSegment {
  if (!isRecord(value)) throw new TypeError('Backend returned an invalid preview segment');
  const mode = value.motion_mode;
  if (mode !== 'JOINT' && mode !== 'CARTESIAN_LINEAR' && mode !== 'HOLD') {
    throw new TypeError('Backend returned an invalid preview segment mode');
  }
  const startTime = finiteNumber(value.start_time_s, 'preview segment start time');
  const endTime = finiteNumber(value.end_time_s, 'preview segment end time');
  if (endTime < startTime) throw new TypeError('Backend returned an invalid preview segment range');
  return {
    segment_index: integerValue(value.segment_index, 'preview segment index'),
    motion_mode: mode,
    start_time_s: startTime,
    end_time_s: endTime,
    sample_count: integerValue(value.sample_count, 'preview segment sample count'),
    start_keyframe_id: optionalString(value.start_keyframe_id, 'preview start keyframe ID'),
    end_keyframe_id: optionalString(value.end_keyframe_id, 'preview end keyframe ID'),
  };
}

function normalizeMarker(value: unknown): TrajectoryKeyframeMarker {
  if (!isRecord(value)) throw new TypeError('Backend returned an invalid keyframe marker');
  const keyframeId = stringValue(value.keyframe_id);
  const label = stringValue(value.label);
  if (!keyframeId || !label) throw new TypeError('Backend returned an invalid keyframe marker');
  return {
    keyframe_id: keyframeId,
    label,
    time_s: finiteNumber(value.time_s, 'keyframe marker time'),
    sample_index: integerValue(value.sample_index, 'keyframe marker sample index'),
  };
}

export function normalizeTrajectoryPreview(value: unknown): TrajectoryPreview {
  if (!isRecord(value) || !isRecord(value.joint_series)) {
    throw new TypeError('Backend returned an invalid trajectory preview');
  }
  const digest = stringValue(value.digest);
  const motionId = stringValue(value.motion_id);
  if (!digest || !motionId) throw new TypeError('Backend returned an invalid trajectory preview');
  const jointSeries: TrajectoryPreview['joint_series'] = {};
  const jointEntries = Object.entries(value.joint_series);
  if (jointEntries.length > 32) throw new TypeError('Backend returned oversized joint trajectory series');
  for (const [jointId, points] of jointEntries) {
    if (!jointId || !Array.isArray(points)) {
      throw new TypeError('Backend returned an invalid joint trajectory series');
    }
    if (points.length > 20_000) {
      throw new TypeError('Backend returned oversized joint trajectory series');
    }
    jointSeries[jointId] = points.map((point) => {
      if (!isRecord(point) || (point.unit !== 'deg' && point.unit !== 'mm')) {
        throw new TypeError('Backend returned an invalid joint trajectory point');
      }
      return {
        time_s: finiteNumber(point.time_s, 'joint trajectory time'),
        value: signedFiniteNumber(point.value, 'joint trajectory value'),
        unit: point.unit,
      };
    });
  }
  const tcpPath = boundedArray(value.tcp_path, 'TCP trajectory path', 20_000).map((point) => {
    if (!isRecord(point)) throw new TypeError('Backend returned an invalid TCP trajectory point');
    return {
      time_s: finiteNumber(point.time_s, 'TCP trajectory time'),
      x_mm: signedFiniteNumber(point.x_mm, 'TCP X coordinate'),
      y_mm: signedFiniteNumber(point.y_mm, 'TCP Y coordinate'),
      z_mm: signedFiniteNumber(point.z_mm, 'TCP Z coordinate'),
    };
  });
  const sampleCount = integerValue(value.sample_count, 'preview sample count');
  if (sampleCount > 20_000) throw new TypeError('Backend returned an oversized trajectory preview');
  return {
    digest,
    motion_id: motionId,
    duration_s: finiteNumber(value.duration_s, 'preview duration'),
    sample_rate_hz: finiteNumber(value.sample_rate_hz, 'preview sample rate', Number.EPSILON),
    sample_count: sampleCount,
    segments: boundedArray(value.segments, 'preview segments', 2_000).map(normalizePreviewSegment),
    joint_series: jointSeries,
    tcp_path: tcpPath,
    keyframe_markers: boundedArray(value.keyframe_markers, 'keyframe markers', 2_000).map(normalizeMarker),
  };
}

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return requestJson<HealthResponse>('/health', { signal });
}

export function getMeta(signal?: AbortSignal): Promise<MetaResponse> {
  return requestJson<MetaResponse>('/meta', { signal });
}

export function getRobotStatus(signal?: AbortSignal): Promise<RobotStatus> {
  return requestJson<RobotStatus>('/robot', { signal });
}

export function getRobotProfile(signal?: AbortSignal): Promise<ProfileResponse> {
  return requestJson<ProfileResponse>('/robot/profile', { signal });
}

export function getRobotDiagnostics(signal?: AbortSignal): Promise<DiagnosticsResponse> {
  return requestJson<DiagnosticsResponse>('/robot/diagnostics', { signal });
}

export function getCalibrationStatus(signal?: AbortSignal): Promise<CalibrationStatus> {
  return requestJson<CalibrationStatus>('/calibration/status', { signal });
}

export function connectRobot(): Promise<{ status: RobotStatus; hardware_accessed: false }> {
  return postJson('/robot/connect');
}

export function disconnectRobot(): Promise<{ status: RobotStatus; hardware_accessed: false }> {
  return postJson('/robot/disconnect');
}

export function stopRobot(): Promise<{
  result: 'STOPPED' | 'NOT_CONNECTED' | 'FAILED' | 'SAFETY_STATE_UNCERTAIN';
  status: RobotStatus;
  hardware_accessed: false;
}> {
  return postJson('/robot/stop');
}

export function switchRobotVariant(
  variant: RobotVariant,
): Promise<{ status: RobotStatus; hardware_accessed: false }> {
  return requestJson('/robot/variant', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ variant }),
  });
}

export async function getBootstrapData(signal?: AbortSignal): Promise<BootstrapResponse> {
  const [health, meta, robot, profile, calibration, diagnostics] = await Promise.all([
    getHealth(signal),
    getMeta(signal),
    getRobotStatus(signal),
    getRobotProfile(signal),
    getCalibrationStatus(signal),
    getRobotDiagnostics(signal),
  ]);
  return { health, meta, robot, profile, calibration, diagnostics };
}

export function getForwardKinematics(signal?: AbortSignal): Promise<ForwardKinematicsResponse> {
  return requestJson<ForwardKinematicsResponse>('/robot/fk', { signal });
}

export function solveInverseKinematics(
  request: InverseKinematicsRequest,
): Promise<InverseKinematicsResponse> {
  return postJson('/kinematics/ik', request);
}

export async function moveJoints(request: MoveJointsRequest): Promise<MotionCommandSubmission> {
  return normalizeSubmission(await postJson<unknown>('/motion/joints', request));
}

export async function jogJointStep(
  request: JointJogStepRequest,
): Promise<MotionCommandSubmission> {
  return normalizeSubmission(await postJson<unknown>('/motion/jog-step', request));
}

export async function moveCartesian(
  request: CartesianJogRequest,
): Promise<MotionCommandSubmission> {
  return normalizeSubmission(await postJson<unknown>('/motion/cartesian-jog', request));
}

export async function movePose(request: MovePoseRequest): Promise<MotionCommandSubmission> {
  return normalizeSubmission(await postJson<unknown>('/motion/pose', request));
}

export async function moveHome(request: HomeRequest): Promise<MotionCommandSubmission> {
  return normalizeSubmission(await postJson<unknown>('/motion/home', request));
}

export async function startJogSession(
  request: JogSessionStartRequest,
): Promise<JogSessionResponse> {
  const raw = await postJson<unknown>('/motion/jog/start', request);
  if (!isRecord(raw)) throw new TypeError('Backend returned an invalid jog session response');
  const jogSessionId = stringValue(raw.jog_session_id) ?? stringValue(raw.session_id);
  const commandId = stringValue(raw.command_id);
  if (!jogSessionId) throw new TypeError('Jog response is missing jog_session_id');
  if (!commandId) throw new TypeError('Jog response is missing command_id');
  return {
    jog_session_id: jogSessionId,
    command_id: commandId,
    lease_expires_in_ms:
      typeof raw.lease_expires_in_ms === 'number' ? raw.lease_expires_in_ms : 0,
    status: commandState(raw.status),
  };
}

export function heartbeatJogSession(jogSessionId: string): Promise<unknown> {
  return postJson(`/motion/jog/${encodeURIComponent(jogSessionId)}/heartbeat`);
}

export function stopJogSession(
  jogSessionId: string,
  options?: { keepalive?: boolean },
): Promise<unknown> {
  return postJson(`/motion/jog/${encodeURIComponent(jogSessionId)}/stop`, undefined, {
    keepalive: options?.keepalive,
  });
}

export async function getMotionCommand(commandId: string): Promise<MotionCommandStatus> {
  return normalizeCommandStatus(
    await requestJson<unknown>(`/motion/commands/${encodeURIComponent(commandId)}`),
  );
}

export function stopMotion(): Promise<MotionStopResponse> {
  return postJson<MotionStopResponse>('/motion/stop');
}

export function getPoses(
  query: EntityListQuery,
  signal?: AbortSignal,
): Promise<EntityPage<PoseSummary>> {
  return requestJson(entityListPath('/poses', query), { signal });
}

export function createPose(request: CreatePoseRequest): Promise<PoseEntity> {
  return postJson('/poses', request);
}

export function capturePose(request: CapturePoseRequest): Promise<PoseEntity> {
  return postJson('/poses/capture', request);
}

export function getPose(poseId: string, signal?: AbortSignal): Promise<PoseEntity> {
  return requestJson(entityPath('/poses', poseId), { signal });
}

export function updatePose(poseId: string, request: UpdatePoseRequest): Promise<PoseEntity> {
  return patchJson(entityPath('/poses', poseId), request);
}

export function deletePose(poseId: string, expectedRevision: number): Promise<void> {
  const params = new URLSearchParams({ expected_revision: String(expectedRevision) });
  return requestJson(`${entityPath('/poses', poseId)}?${params.toString()}`, {
    method: 'DELETE',
  });
}

export function duplicatePose(
  poseId: string,
  request: DuplicateEntityRequest,
): Promise<PoseEntity> {
  return postJson(`${entityPath('/poses', poseId)}/duplicate`, request);
}

export async function gotoPose(
  poseId: string,
  request: GotoPoseRequest,
): Promise<MotionCommandSubmission> {
  return normalizeSubmission(
    await postJson<unknown>(`${entityPath('/poses', poseId)}/goto`, request),
  );
}

export function getMotions(
  query: EntityListQuery,
  signal?: AbortSignal,
): Promise<EntityPage<MotionSummary>> {
  return requestJson(entityListPath('/motions', query), { signal });
}

export function createMotion(request: CreateMotionRequest): Promise<MotionEntity> {
  return postJson('/motions', request);
}

export function getMotion(motionId: string, signal?: AbortSignal): Promise<MotionEntity> {
  return requestJson(entityPath('/motions', motionId), { signal });
}

export function updateMotion(
  motionId: string,
  request: UpdateMotionRequest,
): Promise<MotionEntity> {
  return patchJson(entityPath('/motions', motionId), request);
}

export function deleteMotion(motionId: string, expectedRevision: number): Promise<void> {
  const params = new URLSearchParams({ expected_revision: String(expectedRevision) });
  return requestJson(`${entityPath('/motions', motionId)}?${params.toString()}`, {
    method: 'DELETE',
  });
}

export function duplicateMotion(
  motionId: string,
  request: DuplicateEntityRequest,
): Promise<MotionEntity> {
  return postJson(`${entityPath('/motions', motionId)}/duplicate`, request);
}

export async function preflightMotion(
  motionId: string,
  request: PreflightMotionRequest,
  signal?: AbortSignal,
): Promise<TrajectoryPreflightReport> {
  return normalizeTrajectoryPreflight(
    await postJson<unknown>(`${entityPath('/motions', motionId)}/preflight`, request, { signal }),
  );
}

export async function playMotion(
  motionId: string,
  request: PlayMotionRequest,
): Promise<PlaybackStatus> {
  return normalizePlaybackStatus(
    await postJson<unknown>(`${entityPath('/motions', motionId)}/play`, request),
  );
}

export async function pausePlayback(): Promise<PlaybackStatus> {
  return normalizePlaybackStatus(await postJson<unknown>('/playback/pause'));
}

export async function resumePlayback(): Promise<PlaybackStatus> {
  return normalizePlaybackStatus(await postJson<unknown>('/playback/resume'));
}

export async function stopPlayback(): Promise<PlaybackStatus> {
  return normalizePlaybackStatus(await postJson<unknown>('/playback/stop'));
}

export function setPlaybackRate(rate: number): Promise<PlaybackStatus> {
  if (!Number.isFinite(rate) || rate < 0.25 || rate > 2) {
    throw new RangeError('Playback rate must be between 0.25× and 2×');
  }
  return putJson<unknown>('/playback/rate', { rate }).then(normalizePlaybackStatus);
}

export async function setPlaybackLoop(loop: boolean): Promise<PlaybackStatus> {
  return normalizePlaybackStatus(await putJson<unknown>('/playback/loop', { loop }));
}

export async function getPlayback(signal?: AbortSignal): Promise<PlaybackStatus> {
  return normalizePlaybackStatus(await requestJson<unknown>('/playback', { signal }));
}

export async function getTrajectoryPreview(
  digest: string,
  signal?: AbortSignal,
): Promise<TrajectoryPreview> {
  return normalizeTrajectoryPreview(
    await requestJson<unknown>(`/trajectory/${encodeURIComponent(digest)}/preview`, { signal }),
  );
}

export function getMotionDrafts(
  page = 1,
  pageSize = 20,
  signal?: AbortSignal,
): Promise<EntityPage<MotionDraftSummary>> {
  const query = new URLSearchParams({
    page: String(Math.max(1, Math.trunc(page))),
    page_size: String(Math.min(50, Math.max(1, Math.trunc(pageSize)))),
  });
  return requestJson(`/studio/drafts?${query.toString()}`, { signal });
}

export function createMotionDraft(request: CreateMotionDraftRequest): Promise<MotionDraft> {
  return postJson('/studio/drafts', request);
}

export function createMotionDraftFromMotion(
  motionId: string,
  expectedRevision: number,
): Promise<MotionDraft> {
  return postJson(`/studio/drafts/from-motion/${encodeURIComponent(motionId)}`, {
    expected_revision: expectedRevision,
  });
}

export function getMotionDraft(
  draftId: string,
  signal?: AbortSignal,
): Promise<MotionDraft> {
  return requestJson(studioDraftPath(draftId), { signal });
}

export function forkMotionDraft(
  draftId: string,
  request: ForkMotionDraftRequest,
): Promise<MotionDraft> {
  return postJson(`${studioDraftPath(draftId)}/fork`, request);
}

export function updateMotionDraft(
  draftId: string,
  request: UpdateMotionDraftRequest,
): Promise<MotionDraft> {
  return putJson(studioDraftPath(draftId), request);
}

export function abandonMotionDraftSaveIntent(
  draftId: string,
  request: AbandonMotionDraftSaveIntentRequest,
): Promise<MotionDraft> {
  return postJson(`${studioDraftPath(draftId)}/save-intent/abandon`, request);
}

export function deleteMotionDraft(draftId: string, expectedRevision: number): Promise<void> {
  const query = new URLSearchParams({ expected_revision: String(expectedRevision) });
  return requestJson(`${studioDraftPath(draftId)}?${query.toString()}`, {
    method: 'DELETE',
  });
}

export function validateMotionDraft(
  draftId: string,
  expectedRevision: number,
): Promise<MotionDraftValidation> {
  return postJson(`${studioDraftPath(draftId)}/validate`, {
    expected_revision: expectedRevision,
  });
}

export async function compileMotionDraft(
  draftId: string,
  request: CompileMotionDraftRequest,
): Promise<MotionDraftCompileResponse> {
  const raw = await postJson<unknown>(`${studioDraftPath(draftId)}/compile`, request);
  if (!isRecord(raw) || raw.executable !== false) {
    throw new TypeError('Backend returned an invalid non-executable draft compile result');
  }
  const draftIdValue = stringValue(raw.draft_id);
  if (!draftIdValue) throw new TypeError('Draft compile result is missing draft_id');
  return {
    draft_id: draftIdValue,
    draft_revision: integerValue(raw.draft_revision, 'draft compile revision', 1),
    preflight: normalizeTrajectoryPreflight(raw.preflight),
    preview: raw.preview === null ? null : normalizeTrajectoryPreview(raw.preview),
    executable: false,
  };
}

function normalizeDraftSave(value: unknown): MotionDraftSaveResponse {
  if (!isRecord(value) || !isRecord(value.draft) || !isRecord(value.motion)) {
    throw new TypeError('Backend returned an invalid draft save result');
  }
  return {
    draft: value.draft as unknown as MotionDraft,
    motion: value.motion as unknown as MotionEntity,
    preflight: normalizeTrajectoryPreflight(value.preflight),
  };
}

export async function saveMotionDraft(
  draftId: string,
  request: SaveMotionDraftRequest,
): Promise<MotionDraftSaveResponse> {
  return normalizeDraftSave(await postJson<unknown>(`${studioDraftPath(draftId)}/save`, request));
}

export async function saveMotionDraftAs(
  draftId: string,
  request: SaveAsMotionDraftRequest,
): Promise<MotionDraftSaveResponse> {
  return normalizeDraftSave(
    await postJson<unknown>(`${studioDraftPath(draftId)}/save-as`, request),
  );
}

export function captureStudioSnapshot(): Promise<PoseSnapshot> {
  return postJson('/studio/capture', {});
}

export async function gotoMotionDraftKeyframe(
  draftId: string,
  keyframeId: string,
  request: GotoMotionDraftKeyframeRequest,
): Promise<MotionCommandSubmission> {
  return normalizeSubmission(await postJson<unknown>(
    `${studioDraftPath(draftId)}/keyframes/${encodeURIComponent(keyframeId)}/goto`,
    request,
  ));
}
