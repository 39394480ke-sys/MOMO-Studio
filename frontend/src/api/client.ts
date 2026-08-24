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
  CameraAccessPolicy,
  NormalizedBoundingBox,
  StartVisionFollowRequest,
  VisionCapabilities,
  VisionDetectionResponse,
  VisionFollowLeaseResponse,
  VisionProviderCapability,
  VisionStatus,
  VisionTrackingState,
  DeviceConfirmationEvidence,
  DeviceDiagnostics,
  DeviceReadiness,
  DeviceReadinessEvidence,
  DeviceServoDiagnostic,
  DeviceStopResponse,
  OperatorSessionResponse,
  RealStopOutcome,
  SecuritySessionResponse,
  SecuritySurface,
  CalibrationJointPreview,
  CalibrationRevisionSummary,
  CalibrationSavePreview,
  CalibrationWorkflowState,
  CalibrationWorkflowStatus,
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

function unitIntervalNumber(value: unknown, field: string): number {
  const numeric = finiteNumber(value, field);
  if (numeric > 1) throw new TypeError(`Backend returned an invalid ${field}`);
  return numeric;
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
    credentials: 'include',
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

function cameraAccessPolicy(value: unknown): CameraAccessPolicy {
  if (value !== 'DISABLED' && value !== 'SYNTHETIC_ONLY' && value !== 'LIVE_CAMERA_ALLOWED') {
    throw new TypeError('Backend returned an invalid camera access policy');
  }
  return value;
}

function normalizedBoundingBox(value: unknown, field: string): NormalizedBoundingBox {
  if (!isRecord(value)) throw new TypeError(`Backend returned an invalid ${field}`);
  const x = signedFiniteNumber(value.x, `${field} x`);
  const y = signedFiniteNumber(value.y, `${field} y`);
  const width = finiteNumber(value.width, `${field} width`);
  const height = finiteNumber(value.height, `${field} height`);
  if (width <= 0 || height <= 0 || x < 0 || y < 0 || x + width > 1 || y + height > 1) {
    throw new TypeError(`Backend returned an out-of-range ${field}`);
  }
  return { x, y, width, height };
}

function visionCapability(value: unknown, field: string): VisionProviderCapability {
  if (!isRecord(value)) throw new TypeError(`Backend returned an invalid ${field}`);
  const providerId = stringValue(value.provider_id);
  const kind = stringValue(value.kind);
  const modelSource = stringValue(value.model_source);
  const notice = stringValue(value.notice);
  if (
    !providerId || !kind || !modelSource || !notice ||
    typeof value.available !== 'boolean' || typeof value.active !== 'boolean' ||
    (!value.available && value.active)
  ) {
    throw new TypeError(`Backend returned an invalid ${field}`);
  }
  return {
    provider_id: providerId,
    kind,
    available: value.available,
    active: value.active,
    model_source: modelSource,
    notice,
    reason: optionalString(value.reason, `${field} reason`) ?? null,
  };
}

export function normalizeVisionCapabilities(value: unknown): VisionCapabilities {
  if (!isRecord(value) || value.real_follow_allowed !== false) {
    throw new TypeError('Backend returned invalid Vision capabilities');
  }
  const blockedReason = stringValue(value.real_follow_blocked_reason);
  if (!blockedReason) throw new TypeError('Vision capabilities omitted the Real Follow block');
  return {
    camera_access_policy: cameraAccessPolicy(value.camera_access_policy),
    source: visionCapability(value.source, 'Vision source capability'),
    trackers: boundedArray(value.trackers, 'Vision tracker capabilities', 16).map(
      (item, index) => visionCapability(item, `Vision tracker capability ${index}`),
    ),
    detectors: boundedArray(value.detectors, 'Vision detector capabilities', 16).map(
      (item, index) => visionCapability(item, `Vision detector capability ${index}`),
    ),
    stream: visionCapability(value.stream, 'Vision stream capability'),
    real_follow_allowed: false,
    real_follow_blocked_reason: blockedReason,
  };
}

export function normalizeVisionStatus(value: unknown): VisionStatus {
  if (!isRecord(value) || !isRecord(value.follow) || value.dry_run !== true) {
    throw new TypeError('Backend returned an invalid Vision status');
  }
  const sourceState = stringValue(value.source_state);
  const robotState = stringValue(value.robot_state);
  const blockedReason = stringValue(value.real_follow_blocked_reason);
  if (!sourceState || !robotState || !blockedReason) {
    throw new TypeError('Backend returned an incomplete Vision status');
  }
  const frame = value.latest_frame;
  let latestFrame: VisionStatus['latest_frame'] = null;
  if (frame !== null) {
    if (!isRecord(frame)) throw new TypeError('Backend returned invalid Vision frame metadata');
    const frameId = stringValue(frame.frame_id);
    const capturedAt = stringValue(frame.captured_at);
    const sourceId = stringValue(frame.source_id);
    if (!frameId || !capturedAt || !sourceId) {
      throw new TypeError('Backend returned incomplete Vision frame metadata');
    }
    const widthPx = integerValue(frame.width_px, 'Vision frame width', 1);
    const heightPx = integerValue(frame.height_px, 'Vision frame height', 1);
    if (widthPx > 4096 || heightPx > 4096 || widthPx * heightPx > 1920 * 1080) {
      throw new TypeError('Backend returned oversized Vision frame metadata');
    }
    latestFrame = {
      frame_id: frameId,
      width_px: widthPx,
      height_px: heightPx,
      captured_at: capturedAt,
      source_id: sourceId,
      age_ms: finiteNumber(frame.age_ms, 'Vision frame age'),
    };
  }
  const selection = value.selection;
  let parsedSelection: VisionStatus['selection'] = null;
  if (selection !== null) {
    if (!isRecord(selection) || !stringValue(selection.frame_id)) {
      throw new TypeError('Backend returned an invalid Vision selection');
    }
    parsedSelection = {
      frame_id: String(selection.frame_id),
      bounding_box: normalizedBoundingBox(selection.bounding_box, 'Vision selection box'),
    };
  }
  const tracking = value.tracking;
  let parsedTracking: VisionStatus['tracking'] = null;
  if (tracking !== null) {
    if (!isRecord(tracking)) throw new TypeError('Backend returned an invalid tracking result');
    const frameId = stringValue(tracking.frame_id);
    const sourceId = stringValue(tracking.source_id);
    const capturedAt = stringValue(tracking.captured_at);
    const trackingStatus = stringValue(tracking.status);
    if (
      !frameId || !sourceId || !capturedAt ||
      !trackingStatus || !['LOCKED', 'LOST', 'STALE', 'FAULTED'].includes(trackingStatus)
    ) {
      throw new TypeError('Backend returned an invalid tracking result');
    }
    const trackingBox = tracking.bounding_box === null
      ? null
      : normalizedBoundingBox(tracking.bounding_box, 'tracking box');
    if ((trackingStatus === 'LOCKED') !== (trackingBox !== null)) {
      throw new TypeError('Backend returned an incoherent tracking box');
    }
    parsedTracking = {
      frame_id: frameId,
      source_id: sourceId,
      captured_at: capturedAt,
      bounding_box: trackingBox,
      confidence: unitIntervalNumber(tracking.confidence, 'tracking confidence'),
      status: trackingStatus as VisionTrackingState,
      error: optionalString(tracking.error, 'tracking error') ?? null,
    };
  }
  const follow = value.follow;
  if (typeof follow.active !== 'boolean') throw new TypeError('Backend returned invalid follow state');
  const followLeaseId = optionalString(follow.lease_id, 'follow lease id') ?? null;
  const followExpiresAt = optionalString(follow.expires_at, 'follow expiry') ?? null;
  if (follow.active && (!followLeaseId || !followExpiresAt)) {
    throw new TypeError('Backend returned an active Follow without a lease');
  }
  return {
    camera_access_policy: cameraAccessPolicy(value.camera_access_policy),
    source_state: sourceState,
    latest_frame: latestFrame,
    selection: parsedSelection,
    tracking: parsedTracking,
    follow: {
      active: follow.active,
      lease_id: followLeaseId,
      expires_at: followExpiresAt,
      stop_reason: optionalString(follow.stop_reason, 'follow stop reason') ?? null,
      error_x: optionalSignedNumber(follow.error_x, 'follow x error') ?? null,
      error_y: optionalSignedNumber(follow.error_y, 'follow y error') ?? null,
      ema_error_x: optionalSignedNumber(follow.ema_error_x, 'follow EMA x error') ?? null,
      ema_error_y: optionalSignedNumber(follow.ema_error_y, 'follow EMA y error') ?? null,
      last_command_id: optionalString(follow.last_command_id, 'follow command id') ?? null,
    },
    robot_state: robotState,
    dry_run: true,
    real_follow_blocked_reason: blockedReason,
  };
}

function normalizeVisionFollowLease(value: unknown): VisionFollowLeaseResponse {
  if (!isRecord(value)) throw new TypeError('Backend returned an invalid Follow lease');
  const leaseId = stringValue(value.lease_id);
  const expiresAt = stringValue(value.expires_at);
  if (!leaseId || !expiresAt) throw new TypeError('Backend returned an incomplete Follow lease');
  return { lease_id: leaseId, expires_at: expiresAt, status: normalizeVisionStatus(value.status) };
}

export const visionFrameUrl = `${API_BASE_URL}/vision/frame`;
export const visionStreamUrl = `${API_BASE_URL}/vision/stream`;

export async function getVisionCapabilities(signal?: AbortSignal): Promise<VisionCapabilities> {
  return normalizeVisionCapabilities(await requestJson<unknown>('/vision/capabilities', { signal }));
}

export async function getVisionStatus(signal?: AbortSignal): Promise<VisionStatus> {
  return normalizeVisionStatus(await requestJson<unknown>('/vision/status', { signal }));
}

export async function selectVisionTarget(
  frameId: string,
  boundingBox: NormalizedBoundingBox,
): Promise<VisionStatus> {
  return normalizeVisionStatus(await postJson<unknown>('/vision/selection', {
    frame_id: frameId,
    bounding_box: boundingBox,
  }));
}

export async function clearVisionTarget(): Promise<VisionStatus> {
  return normalizeVisionStatus(await requestJson<unknown>('/vision/selection', { method: 'DELETE' }));
}

export async function detectVisionTarget(
  detector: 'person' | 'face',
  frameId: string,
): Promise<VisionDetectionResponse> {
  const value = await postJson<unknown>(`/vision/detect/${detector}`, { frame_id: frameId });
  if (!isRecord(value)) throw new TypeError('Backend returned an invalid detection response');
  return {
    capability: visionCapability(value.capability, `${detector} detector capability`),
    detections: boundedArray(value.detections, `${detector} detections`, 100).map((item, index) => {
      if (!isRecord(item)) throw new TypeError(`Backend returned invalid detection ${index}`);
      const detectionId = stringValue(item.detection_id);
      const detectionFrameId = stringValue(item.frame_id);
      const sourceId = stringValue(item.source_id);
      const capturedAt = stringValue(item.captured_at);
      const label = stringValue(item.label);
      if (!detectionId || !detectionFrameId || !sourceId || !capturedAt || !label) {
        throw new TypeError(`Backend returned incomplete detection ${index}`);
      }
      return {
        detection_id: detectionId,
        frame_id: detectionFrameId,
        source_id: sourceId,
        captured_at: capturedAt,
        bounding_box: normalizedBoundingBox(item.bounding_box, `detection ${index} box`),
        confidence: unitIntervalNumber(item.confidence, `detection ${index} confidence`),
        label,
      };
    }),
  };
}

export async function resetVisionTracking(): Promise<VisionStatus> {
  return normalizeVisionStatus(await postJson<unknown>('/vision/tracking/reset', {}));
}

export async function startVisionFollow(
  request: StartVisionFollowRequest,
): Promise<VisionFollowLeaseResponse> {
  return normalizeVisionFollowLease(await postJson<unknown>('/vision/follow/start', request));
}

export async function heartbeatVisionFollow(leaseId: string): Promise<VisionFollowLeaseResponse> {
  return normalizeVisionFollowLease(await postJson<unknown>(
    `/vision/follow/${encodeURIComponent(leaseId)}/heartbeat`,
    {},
  ));
}

export async function stopVisionFollow(leaseId: string): Promise<VisionStatus> {
  return normalizeVisionStatus(await postJson<unknown>(
    `/vision/follow/${encodeURIComponent(leaseId)}/stop`,
    {},
  ));
}

function nullableString(value: unknown, field: string): string | null {
  const parsed = optionalString(value, field);
  return parsed ?? null;
}

function deviceConfirmation(value: unknown): DeviceConfirmationEvidence {
  if (!isRecord(value) || value.physical_estop_required !== true) {
    throw new TypeError('Backend returned invalid device confirmation evidence');
  }
  const requiredText = stringValue(value.required_confirmation_text);
  const variant = value.variant === null || value.variant === 'V1' || value.variant === 'V2'
    ? value.variant
    : undefined;
  if (!requiredText || variant === undefined) {
    throw new TypeError('Backend returned incomplete device confirmation evidence');
  }
  return {
    robot_id: nullableString(value.robot_id, 'device robot ID'),
    variant,
    profile_fingerprint: nullableString(value.profile_fingerprint, 'device Profile fingerprint'),
    calibration_fingerprint: nullableString(value.calibration_fingerprint, 'device Calibration fingerprint'),
    kinematics_fingerprint: nullableString(value.kinematics_fingerprint, 'device Kinematics fingerprint'),
    masked_serial_port: nullableString(value.masked_serial_port, 'masked serial port'),
    masked_servo_ids: boundedArray(value.masked_servo_ids, 'masked Servo IDs', 32).map((item) => {
      const parsed = stringValue(item);
      if (!parsed) throw new TypeError('Backend returned an invalid masked Servo ID');
      return parsed;
    }),
    protocol: nullableString(value.protocol, 'device protocol'),
    physical_estop_required: true,
    required_confirmation_text: requiredText,
  };
}

export function normalizeDeviceReadiness(value: unknown): DeviceReadiness {
  if (!isRecord(value) || typeof value.ready !== 'boolean' ||
    typeof value.session_authorizable !== 'boolean' || typeof value.connected !== 'boolean' ||
    !isRecord(value.capabilities)) {
    throw new TypeError('Backend returned invalid Real readiness');
  }
  const state = stringValue(value.state);
  if (!state) throw new TypeError('Backend returned Real readiness without state');
  const blockingReasons = boundedArray(value.blocking_reasons, 'Real blocking reasons', 64)
    .map((item) => {
      const parsed = stringValue(item);
      if (!parsed) throw new TypeError('Backend returned an invalid Real blocking reason');
      return parsed;
    });
  let session: DeviceReadiness['session'] = null;
  if (value.session !== null) {
    if (!isRecord(value.session) || typeof value.session.active !== 'boolean') {
      throw new TypeError('Backend returned invalid Operator Session status');
    }
    const sessionId = stringValue(value.session.session_id);
    const expiresAt = stringValue(value.session.expires_at);
    if (!sessionId || !expiresAt) throw new TypeError('Operator Session status is incomplete');
    session = { active: value.session.active, session_id: sessionId, expires_at: expiresAt };
  }
  if (value.ready && (!session?.active || blockingReasons.length > 0)) {
    throw new TypeError('Backend claimed Real readiness without a valid session');
  }
  if (value.session_authorizable && value.ready) {
    throw new TypeError('Backend returned incoherent Operator Session readiness');
  }
  const capabilities = {
    real_joint_motion_ready: value.capabilities.real_joint_motion_ready,
    real_cartesian_motion_ready: value.capabilities.real_cartesian_motion_ready,
    real_playback_ready: value.capabilities.real_playback_ready,
    real_vision_follow_ready: value.capabilities.real_vision_follow_ready,
  };
  if (Object.values(capabilities).some((item) => typeof item !== 'boolean')) {
    throw new TypeError('Backend returned invalid Real capability readiness');
  }
  if (value.ready && !Object.values(capabilities).every(Boolean)) {
    throw new TypeError('Backend claimed Real readiness without every capability');
  }
  return {
    state,
    ready: value.ready,
    session_authorizable: value.session_authorizable,
    blocking_reasons: blockingReasons,
    capabilities: capabilities as DeviceReadiness['capabilities'],
    confirmation: deviceConfirmation(value.confirmation),
    session,
    connected: value.connected,
  };
}

function readinessEvidence(value: unknown, field: string): DeviceReadinessEvidence {
  if (!isRecord(value) || typeof value.configured !== 'boolean' ||
    typeof value.ready_for_real !== 'boolean') {
    throw new TypeError(`Backend returned invalid ${field}`);
  }
  const template = value.template;
  if (template !== null && typeof template !== 'boolean') {
    throw new TypeError(`Backend returned invalid ${field} template state`);
  }
  return {
    configured: value.configured,
    fingerprint: nullableString(value.fingerprint, `${field} fingerprint`),
    verification_status: nullableString(value.verification_status, `${field} verification`),
    template,
    ready_for_real: value.ready_for_real,
  };
}

function servoDiagnostic(value: unknown): DeviceServoDiagnostic {
  if (!isRecord(value) || typeof value.ping_responded !== 'boolean') {
    throw new TypeError('Backend returned invalid Servo diagnostics');
  }
  const jointId = stringValue(value.joint_id);
  const maskedServoId = stringValue(value.masked_servo_id);
  if (!jointId || !maskedServoId) throw new TypeError('Servo diagnostics omitted identity');
  const bounds = value.raw_bounds;
  let rawBounds: [number, number] | null = null;
  if (bounds !== null) {
    if (!Array.isArray(bounds) || bounds.length !== 2) {
      throw new TypeError('Backend returned invalid Servo raw bounds');
    }
    rawBounds = [
      integerValue(bounds[0], 'Servo raw lower bound', Number.MIN_SAFE_INTEGER),
      integerValue(bounds[1], 'Servo raw upper bound', Number.MIN_SAFE_INTEGER),
    ];
    if (rawBounds[0] >= rawBounds[1]) throw new TypeError('Servo raw bounds are reversed');
  }
  const torque = value.torque_enabled;
  if (torque !== null && typeof torque !== 'boolean') {
    throw new TypeError('Backend returned invalid Servo torque state');
  }
  return {
    joint_id: jointId,
    masked_servo_id: maskedServoId,
    ping_responded: value.ping_responded,
    operating_mode: nullableString(value.operating_mode, 'Servo operating mode'),
    present_raw: value.present_raw === null
      ? null
      : integerValue(value.present_raw, 'Servo present raw', Number.MIN_SAFE_INTEGER),
    logical_value: value.logical_value === null
      ? null
      : signedFiniteNumber(value.logical_value, 'Servo logical value'),
    raw_bounds: rawBounds,
    torque_enabled: torque,
  };
}

export function normalizeDeviceDiagnostics(value: unknown): DeviceDiagnostics {
  if (!isRecord(value) || typeof value.connected !== 'boolean' || !isRecord(value.dependency)) {
    throw new TypeError('Backend returned invalid device diagnostics');
  }
  const capturedAt = stringValue(value.captured_at);
  const adapterId = stringValue(value.dependency.adapter_id);
  const dependencyState = stringValue(value.dependency.state);
  const licenseStatus = stringValue(value.dependency.license_status);
  const notice = stringValue(value.dependency.notice);
  const hardwarePolicy = stringValue(value.hardware_policy);
  const fieldAcceptance = stringValue(value.field_acceptance);
  const readiness = stringValue(value.readiness);
  if (!capturedAt || !adapterId || !licenseStatus || !notice || !hardwarePolicy ||
    !fieldAcceptance || !readiness || !['AVAILABLE', 'UNAVAILABLE', 'PENDING_ADAPTER_VERIFICATION'].includes(dependencyState ?? '')) {
    throw new TypeError('Backend returned incomplete device diagnostics');
  }
  return {
    connected: value.connected,
    captured_at: capturedAt,
    dependency: {
      adapter_id: adapterId,
      state: dependencyState as DeviceDiagnostics['dependency']['state'],
      package_name: nullableString(value.dependency.package_name, 'adapter package'),
      license_status: licenseStatus,
      notice,
    },
    hardware_policy: hardwarePolicy,
    masked_serial_port: nullableString(value.masked_serial_port, 'diagnostic serial port'),
    masked_servo_ids: boundedArray(value.masked_servo_ids, 'diagnostic Servo IDs', 32).map((item) => {
      const parsed = stringValue(item);
      if (!parsed) throw new TypeError('Backend returned invalid diagnostic Servo ID');
      return parsed;
    }),
    protocol: nullableString(value.protocol, 'diagnostic protocol'),
    profile: readinessEvidence(value.profile, 'Profile readiness'),
    calibration: readinessEvidence(value.calibration, 'Calibration readiness'),
    kinematics: readinessEvidence(value.kinematics, 'Kinematics readiness'),
    field_acceptance: fieldAcceptance,
    readiness,
    records: boundedArray(value.records, 'Servo diagnostics', 32).map(servoDiagnostic),
    last_error: nullableString(value.last_error, 'device diagnostic error'),
  };
}

function operatorSession(value: unknown): OperatorSessionResponse {
  if (!isRecord(value)) throw new TypeError('Backend returned invalid Operator Session');
  const sessionToken = stringValue(value.session_token);
  const sessionId = stringValue(value.session_id);
  const issuedAt = stringValue(value.issued_at);
  const expiresAt = stringValue(value.expires_at);
  if (!sessionToken || !sessionId || !issuedAt || !expiresAt) {
    throw new TypeError('Backend returned incomplete Operator Session');
  }
  return {
    session_token: sessionToken,
    session_id: sessionId,
    issued_at: issuedAt,
    expires_at: expiresAt,
    evidence: deviceConfirmation(value.evidence),
  };
}

function sessionHeaders(token: string): HeadersInit {
  if (!token) throw new TypeError('Operator Session token is required');
  return { 'X-MOMO-Operator-Session': token };
}

const SECURITY_SURFACES = new Set<SecuritySurface>([
  'REST',
  'CONTROL',
  'WEBSOCKET',
  'VISION',
]);

function securitySession(value: unknown): SecuritySessionResponse {
  if (!isRecord(value)) throw new TypeError('Backend returned an invalid security session');
  const principalId = stringValue(value.principal_id);
  const issuedAt = stringValue(value.issued_at);
  const expiresAt = stringValue(value.expires_at);
  const rawSurfaces = boundedArray(value.surfaces, 'security session surfaces', 4);
  const surfaces = rawSurfaces.map((surface) => {
    if (typeof surface !== 'string' || !SECURITY_SURFACES.has(surface as SecuritySurface)) {
      throw new TypeError('Backend returned an invalid security session surface');
    }
    return surface as SecuritySurface;
  });
  if (!principalId || !issuedAt || !expiresAt || new Set(surfaces).size !== surfaces.length) {
    throw new TypeError('Backend returned an incomplete security session');
  }
  return { principal_id: principalId, issued_at: issuedAt, expires_at: expiresAt, surfaces };
}

export async function createLanSecuritySession(
  bearerToken: string,
): Promise<SecuritySessionResponse> {
  if (bearerToken.length < 32 || bearerToken.length > 512 || /\s/.test(bearerToken)) {
    throw new TypeError('LAN bearer token must be 32–512 non-whitespace characters');
  }
  return securitySession(await postJson<unknown>('/security/session', undefined, {
    headers: { Authorization: `Bearer ${bearerToken}` },
  }));
}

export async function revokeLanSecuritySession(): Promise<void> {
  await requestJson<unknown>('/security/session', { method: 'DELETE' });
}

export async function getDeviceReadiness(signal?: AbortSignal): Promise<DeviceReadiness> {
  return normalizeDeviceReadiness(await requestJson<unknown>('/device/readiness', { signal }));
}

export async function createOperatorSession(
  confirmationText: string,
  physicalEstopConfirmed: boolean,
): Promise<OperatorSessionResponse> {
  return operatorSession(await postJson<unknown>('/device/operator-session', {
    confirmation_text: confirmationText,
    physical_estop_confirmed: physicalEstopConfirmed,
  }));
}

export async function revokeOperatorSession(token: string): Promise<void> {
  await requestJson<unknown>('/device/operator-session', {
    method: 'DELETE',
    headers: sessionHeaders(token),
  });
}

export async function connectRealDevice(token: string): Promise<DeviceDiagnostics> {
  const value = await postJson<unknown>('/device/connect', undefined, {
    headers: sessionHeaders(token),
  });
  if (!isRecord(value)) throw new TypeError('Backend returned invalid Real connect result');
  return normalizeDeviceDiagnostics(value.diagnostics ?? value);
}

export async function disconnectRealDevice(token: string): Promise<DeviceDiagnostics> {
  const value = await postJson<unknown>('/device/disconnect', undefined, {
    headers: sessionHeaders(token),
  });
  if (!isRecord(value)) throw new TypeError('Backend returned invalid Real disconnect result');
  return normalizeDeviceDiagnostics(value.diagnostics ?? value);
}

export async function runDeviceDiagnostics(token: string): Promise<DeviceDiagnostics> {
  return normalizeDeviceDiagnostics(await postJson<unknown>('/device/diagnostics', undefined, {
    headers: sessionHeaders(token),
  }));
}

export async function stopRealDevice(): Promise<DeviceStopResponse> {
  const value = await postJson<unknown>('/device/stop', {});
  if (!isRecord(value)) throw new TypeError('Backend returned invalid Real Stop result');
  const result = stringValue(value.result);
  const detail = stringValue(value.detail);
  const outcomes: RealStopOutcome[] = [
    'STOPPED_AND_VERIFIED', 'HOLD_REQUESTED', 'TORQUE_DISABLE_REQUESTED',
    'NOT_CONNECTED', 'FAILED', 'SAFETY_STATE_UNCERTAIN',
  ];
  if (!result || !outcomes.includes(result as RealStopOutcome) || !detail ||
    typeof value.physical_estop_required !== 'boolean') {
    throw new TypeError('Backend returned invalid Real Stop outcome');
  }
  return {
    result: result as RealStopOutcome,
    physical_estop_required: value.physical_estop_required,
    detail,
  };
}

const CALIBRATION_STATES = new Set<CalibrationWorkflowState>([
  'ACTIVE', 'READY_TO_SAVE', 'SAVED', 'CANCELLED', 'EXPIRED',
]);

function fingerprint(value: unknown, field: string): string {
  const parsed = stringValue(value);
  if (!parsed || !/^[0-9a-f]{64}$/.test(parsed)) {
    throw new TypeError(`Backend returned an invalid ${field}`);
  }
  return parsed;
}

function calibrationJointPreview(value: unknown): CalibrationJointPreview {
  if (!isRecord(value)) throw new TypeError('Backend returned an invalid calibration preview');
  const sessionId = stringValue(value.session_id);
  const jointId = stringValue(value.joint_id);
  const operatingMode = stringValue(value.operating_mode);
  if (!sessionId || !jointId || !operatingMode ||
    (value.unit !== 'deg' && value.unit !== 'mm') ||
    (value.direction !== -1 && value.direction !== 1)) {
    throw new TypeError('Backend returned an incomplete calibration preview');
  }
  const rawBounds = arrayValue(value.raw_bounds, 'calibration raw bounds');
  if (rawBounds.length !== 2) throw new TypeError('Backend returned invalid calibration raw bounds');
  const lower = integerValue(rawBounds[0], 'calibration raw lower bound', Number.MIN_SAFE_INTEGER);
  const upper = integerValue(rawBounds[1], 'calibration raw upper bound', Number.MIN_SAFE_INTEGER);
  if (lower >= upper) throw new TypeError('Backend returned reversed calibration raw bounds');
  const phase = value.phase === null
    ? null
    : integerValue(value.phase, 'calibration phase', Number.MIN_SAFE_INTEGER);
  return {
    session_id: sessionId,
    joint_id: jointId,
    servo_id: integerValue(value.servo_id, 'calibration Servo ID', 1),
    observed_raw: integerValue(value.observed_raw, 'calibration observed raw', Number.MIN_SAFE_INTEGER),
    logical_value: signedFiniteNumber(value.logical_value, 'calibration logical value'),
    unit: value.unit,
    operating_mode: operatingMode,
    direction: value.direction,
    home_present_raw: integerValue(value.home_present_raw, 'calibration Home raw', Number.MIN_SAFE_INTEGER),
    phase,
    raw_bounds: [lower, upper],
    round_trip_logical_value: signedFiniteNumber(
      value.round_trip_logical_value,
      'calibration round-trip value',
    ),
    mapping_error: finiteNumber(value.mapping_error, 'calibration mapping error'),
    preview_fingerprint: fingerprint(value.preview_fingerprint, 'calibration preview fingerprint'),
  };
}

function calibrationSavePreview(value: unknown): CalibrationSavePreview {
  if (!isRecord(value) || !isRecord(value.proposed_calibration)) {
    throw new TypeError('Backend returned an invalid complete calibration preview');
  }
  const sessionId = stringValue(value.session_id);
  if (!sessionId) throw new TypeError('Backend returned a calibration save preview without a session');
  const joints = boundedArray(
    value.proposed_calibration.joints,
    'complete calibration joints',
    32,
  ).map((item) => {
    if (!isRecord(item)) throw new TypeError('Backend returned an invalid aggregate joint');
    const jointId = stringValue(item.joint_id);
    const operatingMode = stringValue(item.operating_mode);
    if (!jointId || !operatingMode || (item.direction !== -1 && item.direction !== 1)) {
      throw new TypeError('Backend returned an incomplete aggregate joint');
    }
    const direction: -1 | 1 = item.direction;
    const bounds = arrayValue(item.raw_bounds, 'aggregate calibration raw bounds');
    if (bounds.length !== 2) throw new TypeError('Backend returned invalid aggregate bounds');
    const lower = integerValue(bounds[0], 'aggregate lower bound', Number.MIN_SAFE_INTEGER);
    const upper = integerValue(bounds[1], 'aggregate upper bound', Number.MIN_SAFE_INTEGER);
    if (lower >= upper) throw new TypeError('Backend returned reversed aggregate bounds');
    return {
      joint_id: jointId,
      servo_id: integerValue(item.servo_id, 'aggregate Servo ID', 1),
      operating_mode: operatingMode,
      direction,
      home_present_raw: integerValue(
        item.home_present_raw,
        'aggregate Home raw',
        Number.MIN_SAFE_INTEGER,
      ),
      phase: item.phase === null
        ? null
        : integerValue(item.phase, 'aggregate phase', Number.MIN_SAFE_INTEGER),
      raw_bounds: [lower, upper] as [number, number],
    };
  });
  return {
    session_id: sessionId,
    base_revision: integerValue(value.base_revision, 'save preview base revision', 1),
    base_calibration_fingerprint: fingerprint(
      value.base_calibration_fingerprint,
      'save preview base calibration fingerprint',
    ),
    proposed_calibration_fingerprint: fingerprint(
      value.proposed_calibration_fingerprint,
      'proposed calibration fingerprint',
    ),
    joints,
  };
}

export function normalizeCalibrationWorkflowStatus(value: unknown): CalibrationWorkflowStatus {
  if (!isRecord(value)) throw new TypeError('Backend returned an invalid calibration session');
  const sessionId = stringValue(value.session_id);
  const robotId = stringValue(value.robot_id);
  const state = stringValue(value.state);
  const updatedAt = stringValue(value.updated_at);
  if (!sessionId || !robotId || !state || !CALIBRATION_STATES.has(state as CalibrationWorkflowState) ||
    !updatedAt || (value.variant !== 'V1' && value.variant !== 'V2')) {
    throw new TypeError('Backend returned an incomplete calibration session');
  }
  const required = boundedArray(value.required_joint_ids, 'calibration joints', 32).map((item) => {
    const parsed = stringValue(item);
    if (!parsed) throw new TypeError('Backend returned an invalid calibration joint ID');
    return parsed;
  });
  const confirmed = boundedArray(value.confirmed_joint_ids, 'confirmed calibration joints', 32)
    .map((item) => {
      const parsed = stringValue(item);
      if (!parsed) throw new TypeError('Backend returned an invalid confirmed joint ID');
      return parsed;
    });
  if (new Set(required).size !== required.length ||
    new Set(confirmed).size !== confirmed.length ||
    confirmed.some((item) => !required.includes(item))) {
    throw new TypeError('Backend returned incoherent calibration joint sets');
  }
  const selected = nullableString(value.selected_joint_id, 'selected calibration joint');
  const preview = value.preview === null ? null : calibrationJointPreview(value.preview);
  const savePreview = value.save_preview === null
    ? null
    : calibrationSavePreview(value.save_preview);
  if (preview && (preview.session_id !== sessionId || preview.joint_id !== selected)) {
    throw new TypeError('Backend returned a calibration preview for another selection');
  }
  if (savePreview && (
    savePreview.session_id !== sessionId ||
    savePreview.base_revision !== value.base_revision ||
    savePreview.base_calibration_fingerprint !== value.base_calibration_fingerprint
  )) {
    throw new TypeError('Backend returned a calibration save preview for another revision');
  }
  return {
    session_id: sessionId,
    robot_id: robotId,
    variant: value.variant,
    profile_fingerprint: fingerprint(value.profile_fingerprint, 'calibration Profile fingerprint'),
    base_revision: integerValue(value.base_revision, 'calibration base revision', 1),
    base_calibration_fingerprint: fingerprint(
      value.base_calibration_fingerprint,
      'base calibration fingerprint',
    ),
    state: state as CalibrationWorkflowState,
    required_joint_ids: required,
    confirmed_joint_ids: confirmed,
    selected_joint_id: selected,
    observed_raw: value.observed_raw === null
      ? null
      : integerValue(value.observed_raw, 'calibration observed raw', Number.MIN_SAFE_INTEGER),
    preview,
    save_preview: savePreview,
    saved_revision: value.saved_revision === null
      ? null
      : integerValue(value.saved_revision, 'saved calibration revision', 1),
    saved_calibration_fingerprint: value.saved_calibration_fingerprint === null
      ? null
      : fingerprint(value.saved_calibration_fingerprint, 'saved calibration fingerprint'),
    updated_at: updatedAt,
  };
}

function calibrationRevision(value: unknown): CalibrationRevisionSummary {
  if (!isRecord(value) || (value.variant !== 'V1' && value.variant !== 'V2')) {
    throw new TypeError('Backend returned an invalid calibration revision');
  }
  const createdAt = stringValue(value.created_at);
  if (!createdAt) throw new TypeError('Backend returned a calibration revision without time');
  return {
    revision: integerValue(value.revision, 'calibration revision', 1),
    calibration_fingerprint: fingerprint(
      value.calibration_fingerprint,
      'calibration fingerprint',
    ),
    previous_calibration_fingerprint: value.previous_calibration_fingerprint === null
      ? null
      : fingerprint(value.previous_calibration_fingerprint, 'previous calibration fingerprint'),
    variant: value.variant,
    created_at: createdAt,
  };
}

export async function startCalibrationSession(token: string): Promise<CalibrationWorkflowStatus> {
  return normalizeCalibrationWorkflowStatus(await postJson<unknown>(
    '/device/calibration/sessions',
    { source: 'EXISTING_REAL' },
    { headers: sessionHeaders(token) },
  ));
}

export async function readCalibrationJoint(
  token: string,
  sessionId: string,
  jointId: string,
): Promise<CalibrationWorkflowStatus> {
  return normalizeCalibrationWorkflowStatus(await postJson<unknown>(
    `/device/calibration/sessions/${encodeURIComponent(sessionId)}/read`,
    { joint_id: jointId },
    { headers: sessionHeaders(token) },
  ));
}

export async function previewCalibrationJoint(
  token: string,
  sessionId: string,
  request: {
    joint_id: string;
    logical_value: number;
    direction: -1 | 1;
    phase: number | null;
    raw_bounds: [number, number];
  },
): Promise<CalibrationJointPreview> {
  return calibrationJointPreview(await postJson<unknown>(
    `/device/calibration/sessions/${encodeURIComponent(sessionId)}/preview`,
    request,
    { headers: sessionHeaders(token) },
  ));
}

export async function confirmCalibrationJoint(
  token: string,
  sessionId: string,
  jointId: string,
  previewFingerprint: string,
  confirmation: string,
): Promise<CalibrationWorkflowStatus> {
  return normalizeCalibrationWorkflowStatus(await postJson<unknown>(
    `/device/calibration/sessions/${encodeURIComponent(sessionId)}/confirm`,
    {
      joint_id: jointId,
      preview_fingerprint: previewFingerprint,
      confirmation,
    },
    { headers: sessionHeaders(token) },
  ));
}

export async function completeCalibrationSession(
  token: string,
  sessionId: string,
  proposedCalibrationFingerprint: string,
  confirmation: string,
): Promise<CalibrationRevisionSummary> {
  return calibrationRevision(await postJson<unknown>(
    `/device/calibration/sessions/${encodeURIComponent(sessionId)}/complete`,
    {
      proposed_calibration_fingerprint: proposedCalibrationFingerprint,
      confirmation,
    },
    { headers: sessionHeaders(token) },
  ));
}

export async function cancelCalibrationSession(
  token: string,
  sessionId: string,
): Promise<CalibrationWorkflowStatus> {
  return normalizeCalibrationWorkflowStatus(await requestJson<unknown>(
    `/device/calibration/sessions/${encodeURIComponent(sessionId)}`,
    { method: 'DELETE', headers: sessionHeaders(token) },
  ));
}
