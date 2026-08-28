import { API_BASE_URL } from './config';
import type {
  AbandonMotionDraftSaveIntentRequest,
  BootstrapResponse,
  CalibrationStatus,
  CommissioningDirectControlResponse,
  CommissioningDirectJointMoveResponse,
  CommissioningDirectJointStateResponse,
  CommissioningMotionStatus,
  CommissioningMotionTestState,
  CommissioningRelativeTestRequest,
  CommissioningTestEvidence,
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
  FieldAcceptanceCapability,
  FieldAcceptanceProgress,
  FieldAcceptanceProgressState,
  FieldAcceptanceStatusResponse,
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
  JointStatePayload,
  KinematicsVerificationDraft,
  KinematicsVerificationEvidence,
  KinematicsVerificationJointState,
  KinematicsVerificationMeasurementRequest,
  KinematicsVerificationPoint,
  KinematicsVerificationStatus,
  KinematicsVerificationThresholds,
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
  DeviceAuthorizationOption,
  DeviceCapabilityDetail,
  DeviceCapabilityDetails,
  DeviceCapabilityKey,
  DeviceDiagnostics,
  DeviceReadiness,
  DeviceReadinessEvidence,
  DeviceServoDiagnostic,
  DeviceStopResponse,
  OperatorSessionResponse,
  OperatorSessionPurpose,
  OperatorSessionScope,
  RealStopOutcome,
  RawDirection,
  RawDirectionObservation,
  RawDirectionStatus,
  RawDirectionTestState,
  SecuritySessionResponse,
  SecuritySurface,
  CalibrationJointPreview,
  CalibrationDraft,
  CalibrationJointDraft,
  CalibrationRevisionSummary,
  CalibrationSavePreview,
  CalibrationWorkflowSource,
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

export function getForwardKinematicsForState(
  jointState: JointStatePayload,
): Promise<ForwardKinematicsResponse> {
  return postJson('/kinematics/fk', { joint_state: jointState });
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
  if (
    !sourceState ||
    !['DISABLED', 'READY', 'STREAMING', 'DISCONNECTED', 'FAULTED', 'CLOSED'].includes(sourceState) ||
    !robotState ||
    !blockedReason
  ) {
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
    source_state: sourceState as VisionStatus['source_state'],
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

export async function openLiveCamera(): Promise<VisionStatus> {
  return normalizeVisionStatus(await postJson<unknown>('/vision/camera/open', {
    confirm_read_only_open: true,
  }));
}

export async function closeLiveCamera(): Promise<VisionStatus> {
  return normalizeVisionStatus(await postJson<unknown>('/vision/camera/close', {}));
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

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function nullableUuid(value: unknown, field: string): string | null {
  const parsed = nullableString(value, field);
  if (parsed !== null && !UUID_PATTERN.test(parsed)) {
    throw new TypeError(`Backend returned an invalid ${field}`);
  }
  return parsed;
}

const OPERATOR_SESSION_PURPOSES = new Set<OperatorSessionPurpose>([
  'COMMISSIONING_READ_ONLY',
  'COMMISSIONING_MOTION_TEST',
  'RAW_DIRECTION_TEST',
  'REAL_MOTION',
]);

const OPERATOR_SESSION_SCOPES = new Set<OperatorSessionScope>([
  'DIAGNOSTICS_READ',
  'CALIBRATION_CAPTURE',
  'COMMISSIONING_SINGLE_JOINT_TEST',
  'RAW_DIRECTION_TEST',
  'REAL_JOINT_MOTION',
  'REAL_CARTESIAN_MOTION',
  'REAL_PLAYBACK',
  'REAL_VISION_FOLLOW',
]);

function operatorSessionPurpose(value: unknown, field: string): OperatorSessionPurpose {
  if (typeof value !== 'string' || !OPERATOR_SESSION_PURPOSES.has(value as OperatorSessionPurpose)) {
    throw new TypeError(`Backend returned an invalid ${field}`);
  }
  return value as OperatorSessionPurpose;
}

function operatorSessionScopes(value: unknown): OperatorSessionScope[] {
  const scopes = boundedArray(value, 'Operator Session scopes', OPERATOR_SESSION_SCOPES.size)
    .map((scope) => {
      if (typeof scope !== 'string' || !OPERATOR_SESSION_SCOPES.has(scope as OperatorSessionScope)) {
        throw new TypeError('Backend returned an invalid Operator Session scope');
      }
      return scope as OperatorSessionScope;
    });
  if (scopes.length === 0 || new Set(scopes).size !== scopes.length) {
    throw new TypeError('Backend returned incoherent Operator Session scopes');
  }
  return scopes;
}

function validateOperatorSessionScopes(
  purpose: OperatorSessionPurpose,
  scopes: OperatorSessionScope[],
): void {
  const actual = new Set(scopes);
  const commissioning = new Set<OperatorSessionScope>([
    'DIAGNOSTICS_READ',
    'CALIBRATION_CAPTURE',
  ]);
  const commissioningMotion = new Set<OperatorSessionScope>([
    'COMMISSIONING_SINGLE_JOINT_TEST',
  ]);
  const rawDirection = new Set<OperatorSessionScope>(['RAW_DIRECTION_TEST']);
  const realMotion = new Set<OperatorSessionScope>([
    'REAL_JOINT_MOTION',
    'REAL_CARTESIAN_MOTION',
    'REAL_PLAYBACK',
    'REAL_VISION_FOLLOW',
  ]);
  const exact = (expected: Set<OperatorSessionScope>) => (
    actual.size === expected.size && [...actual].every((scope) => expected.has(scope))
  );
  const valid = purpose === 'COMMISSIONING_READ_ONLY'
    ? exact(commissioning)
    : purpose === 'COMMISSIONING_MOTION_TEST'
      ? exact(commissioningMotion)
      : purpose === 'RAW_DIRECTION_TEST'
        ? exact(rawDirection)
        : actual.size > 0 && [...actual].every((scope) => realMotion.has(scope));
  if (!valid) {
    throw new TypeError('Backend returned scopes incoherent with Operator Session purpose');
  }
}

function deviceConfirmation(value: unknown): DeviceConfirmationEvidence {
  if (!isRecord(value) || value.physical_estop_required !== true ||
    typeof value.workspace_clear_required !== 'boolean') {
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
    robot_unit_id: nullableString(value.robot_unit_id, 'device robot unit ID'),
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
    session_purpose: operatorSessionPurpose(value.session_purpose, 'confirmation purpose'),
    field_acceptance_evidence_id: nullableUuid(
      value.field_acceptance_evidence_id,
      'Field Acceptance evidence ID',
    ),
    physical_estop_required: true,
    workspace_clear_required: value.workspace_clear_required,
    required_confirmation_text: requiredText,
  };
}

const DEVICE_CAPABILITY_KEYS: readonly DeviceCapabilityKey[] = [
  'commissioning_read_only',
  'commissioning_motion_test',
  'raw_direction_test',
  'real_joint_motion',
  'real_cartesian_motion',
  'real_playback',
  'real_vision_follow',
];

function boundedUniqueStrings(value: unknown, field: string): string[] {
  const values = boundedArray(value, field, 64).map((item) => {
    const parsed = stringValue(item);
    if (!parsed || parsed.length > 256) {
      throw new TypeError(`Backend returned an invalid ${field}`);
    }
    return parsed;
  });
  if (new Set(values).size !== values.length) {
    throw new TypeError(`Backend returned duplicate ${field}`);
  }
  return values;
}

function deviceCapabilityDetail(
  value: unknown,
  key: DeviceCapabilityKey,
): DeviceCapabilityDetail {
  if (!isRecord(value) || typeof value.ready !== 'boolean' ||
    typeof value.authorized !== 'boolean') {
    throw new TypeError(`Backend returned invalid ${key} capability detail`);
  }
  if (value.authorized && !value.ready) {
    throw new TypeError(`Backend authorized unavailable ${key} capability`);
  }
  return {
    ready: value.ready,
    authorized: value.authorized,
    blocked_reasons: boundedUniqueStrings(
      value.blocked_reasons,
      `${key} capability blocking reasons`,
    ),
    required_evidence: boundedUniqueStrings(
      value.required_evidence,
      `${key} capability evidence requirements`,
    ),
  };
}

function deviceCapabilityDetails(value: unknown): DeviceCapabilityDetails {
  if (!isRecord(value)) {
    throw new TypeError('Backend returned invalid Real capability details');
  }
  return Object.fromEntries(DEVICE_CAPABILITY_KEYS.map((key) => (
    [key, deviceCapabilityDetail(value[key], key)]
  ))) as DeviceCapabilityDetails;
}

function deviceAuthorizationOptions(value: unknown): DeviceAuthorizationOption[] {
  const options = boundedArray(value, 'Operator Session authorization options', 4)
    .map((item) => {
      if (!isRecord(item) || typeof item.authorizable !== 'boolean') {
        throw new TypeError('Backend returned an invalid Operator Session authorization option');
      }
      const purpose = operatorSessionPurpose(item.purpose, 'authorization option purpose');
      const confirmation = deviceConfirmation(item.confirmation);
      if (confirmation.session_purpose !== purpose) {
        throw new TypeError('Backend returned authorization evidence for another purpose');
      }
      return { purpose, authorizable: item.authorizable, confirmation };
    });
  const purposes = new Set(options.map((option) => option.purpose));
  if (options.length !== OPERATOR_SESSION_PURPOSES.size ||
    purposes.size !== options.length ||
    [...OPERATOR_SESSION_PURPOSES].some((purpose) => !purposes.has(purpose))) {
    throw new TypeError('Backend returned incoherent Operator Session authorization options');
  }
  return options;
}

export function normalizeDeviceReadiness(value: unknown): DeviceReadiness {
  if (!isRecord(value) || typeof value.ready !== 'boolean' ||
    typeof value.session_authorizable !== 'boolean' || typeof value.connected !== 'boolean' ||
    typeof value.calibration_configured !== 'boolean' ||
    typeof value.commissioning_session_authorizable !== 'boolean' ||
    typeof value.commissioning_motion_session_authorizable !== 'boolean' ||
    typeof value.raw_direction_session_authorizable !== 'boolean' ||
    typeof value.motion_session_authorizable !== 'boolean' ||
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
    const purpose = operatorSessionPurpose(value.session.purpose, 'Operator Session purpose');
    const scopes = operatorSessionScopes(value.session.scopes);
    validateOperatorSessionScopes(purpose, scopes);
    session = {
      active: value.session.active,
      session_id: sessionId,
      expires_at: expiresAt,
      purpose,
      scopes,
    };
  }
  if (value.ready && (!session?.active || blockingReasons.length > 0)) {
    throw new TypeError('Backend claimed Real readiness without a valid session');
  }
  const commissioningMotionSessionAuthorizable =
    value.commissioning_motion_session_authorizable;
  const rawDirectionSessionAuthorizable = value.raw_direction_session_authorizable;
  if (value.session_authorizable !== (
    value.commissioning_session_authorizable || commissioningMotionSessionAuthorizable ||
    rawDirectionSessionAuthorizable || value.motion_session_authorizable
  )) {
    throw new TypeError('Backend returned incoherent purpose-specific session readiness');
  }
  if (value.session_authorizable && (value.ready || session !== null)) {
    throw new TypeError('Backend returned incoherent Operator Session readiness');
  }
  const capabilities = {
    commissioning_diagnostics_ready: value.capabilities.commissioning_diagnostics_ready,
    calibration_capture_ready: value.capabilities.calibration_capture_ready,
    commissioning_motion_test_ready: value.capabilities.commissioning_motion_test_ready,
    raw_direction_test_ready: value.capabilities.raw_direction_test_ready,
    real_joint_motion_ready: value.capabilities.real_joint_motion_ready,
    real_cartesian_motion_ready: value.capabilities.real_cartesian_motion_ready,
    real_playback_ready: value.capabilities.real_playback_ready,
    real_vision_follow_ready: value.capabilities.real_vision_follow_ready,
  };
  if (Object.values(capabilities).some((item) => typeof item !== 'boolean')) {
    throw new TypeError('Backend returned invalid Real capability readiness');
  }
  const normalizedCapabilities = capabilities as DeviceReadiness['capabilities'];
  const motionCapabilities = [
    capabilities.real_joint_motion_ready,
    capabilities.real_cartesian_motion_ready,
    capabilities.real_playback_ready,
    capabilities.real_vision_follow_ready,
  ];
  if (value.ready && !motionCapabilities.every(Boolean)) {
    throw new TypeError('Backend claimed Real readiness without every capability');
  }
  if (value.commissioning_session_authorizable && !(
    capabilities.commissioning_diagnostics_ready && capabilities.calibration_capture_ready
  )) {
    throw new TypeError('Backend claimed Commissioning authorization without read-only capabilities');
  }
  const capabilityDetails = deviceCapabilityDetails(value.capability_details);
  if (Object.values(capabilityDetails).some((detail) => detail.authorized) && !session?.active) {
    throw new TypeError('Backend authorized a Real capability without an active Operator Session');
  }
  const confirmation = deviceConfirmation(value.confirmation);
  const authorizationOptions = deviceAuthorizationOptions(value.authorization_options);
  for (const option of authorizationOptions) {
    const expected = option.purpose === 'COMMISSIONING_READ_ONLY'
      ? value.commissioning_session_authorizable
      : option.purpose === 'COMMISSIONING_MOTION_TEST'
        ? commissioningMotionSessionAuthorizable
        : option.purpose === 'RAW_DIRECTION_TEST'
          ? rawDirectionSessionAuthorizable
          : value.motion_session_authorizable;
    if (option.authorizable !== expected) {
      throw new TypeError('Backend returned incoherent Operator Session authorization option');
    }
  }
  return {
    state,
    ready: value.ready,
    session_authorizable: value.session_authorizable,
    commissioning_session_authorizable: value.commissioning_session_authorizable,
    commissioning_motion_session_authorizable: commissioningMotionSessionAuthorizable,
    raw_direction_session_authorizable: rawDirectionSessionAuthorizable,
    motion_session_authorizable: value.motion_session_authorizable,
    blocking_reasons: blockingReasons,
    capabilities: normalizedCapabilities,
    capability_details: capabilityDetails,
    authorization_options: authorizationOptions,
    confirmation,
    session,
    calibration_configured: value.calibration_configured,
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
  if (!capturedAt || !adapterId || !licenseStatus || !notice ||
    !['DISABLED', 'READ_ONLY', 'FULL'].includes(hardwarePolicy ?? '') ||
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
    hardware_policy: hardwarePolicy as DeviceDiagnostics['hardware_policy'],
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
    // The backend uses an empty string as the no-error sentinel in its
    // DeviceDiagnosticsResponse. Normalize that wire value to the UI contract.
    last_error: value.last_error === ''
      ? null
      : nullableString(value.last_error, 'device diagnostic error'),
  };
}

function operatorSession(value: unknown): OperatorSessionResponse {
  if (!isRecord(value)) throw new TypeError('Backend returned invalid Operator Session');
  const sessionId = stringValue(value.session_id);
  const issuedAt = stringValue(value.issued_at);
  const expiresAt = stringValue(value.expires_at);
  if (!sessionId || !issuedAt || !expiresAt) {
    throw new TypeError('Backend returned incomplete Operator Session');
  }
  const purpose = operatorSessionPurpose(value.purpose, 'Operator Session purpose');
  const scopes = operatorSessionScopes(value.scopes);
  const evidence = deviceConfirmation(value.evidence);
  validateOperatorSessionScopes(purpose, scopes);
  if (evidence.session_purpose !== purpose) {
    throw new TypeError('Backend returned Operator Session evidence for another purpose');
  }
  return {
    session_id: sessionId,
    issued_at: issuedAt,
    expires_at: expiresAt,
    purpose,
    scopes,
    evidence,
  };
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

export function normalizeFieldAcceptanceStatus(value: unknown): FieldAcceptanceStatusResponse {
  if (!isRecord(value)) throw new TypeError('Backend returned invalid Field Acceptance status');
  const states = ['MISSING', 'STALE', 'STALE_LEGACY_EVIDENCE', 'VALID'] as const;
  const statuses = ['NOT_REQUIRED', 'PENDING', 'PASSED', 'FAILED'] as const;
  const state = stringValue(value.state);
  const effectiveStatus = stringValue(value.effective_status);
  const checklistVersion = stringValue(value.checklist_version);
  const requiredText = stringValue(value.required_confirmation_text);
  if (
    !state || !states.includes(state as typeof states[number]) ||
    !effectiveStatus || !statuses.includes(effectiveStatus as typeof statuses[number]) ||
    !checklistVersion || checklistVersion.length > 64 || !requiredText || requiredText.length > 200
  ) {
    throw new TypeError('Backend returned incomplete Field Acceptance status');
  }
  const staleFields = boundedArray(value.stale_fields, 'Field Acceptance stale fields', 16)
    .map((field) => {
      const parsed = stringValue(field);
      if (!parsed || parsed.length > 128) {
        throw new TypeError('Backend returned an invalid Field Acceptance stale field');
      }
      return parsed;
    });
  if (new Set(staleFields).size !== staleFields.length) {
    throw new TypeError('Backend returned duplicate Field Acceptance stale fields');
  }
  const acceptedAt = nullableString(value.accepted_at, 'Field Acceptance time');
  const acceptedBy = nullableString(value.accepted_by, 'Field Acceptance operator');
  if ((acceptedAt?.length ?? 0) > 64 || (acceptedBy?.length ?? 0) > 128) {
    throw new TypeError('Backend returned oversized Field Acceptance evidence');
  }
  return {
    state: state as FieldAcceptanceStatusResponse['state'],
    effective_status: effectiveStatus as FieldAcceptanceStatusResponse['effective_status'],
    checklist_version: checklistVersion,
    stale_fields: staleFields,
    evidence_id: nullableUuid(value.evidence_id, 'Field Acceptance evidence ID'),
    accepted_at: acceptedAt,
    accepted_by: acceptedBy,
    required_confirmation_text: requiredText,
  };
}

export async function getFieldAcceptanceStatus(
  signal?: AbortSignal,
): Promise<FieldAcceptanceStatusResponse> {
  return normalizeFieldAcceptanceStatus(await requestJson<unknown>(
    '/device/field-acceptance',
    { signal },
  ));
}

const FIELD_ACCEPTANCE_PROGRESS_STATES = new Set<FieldAcceptanceProgressState>([
  'NOT_STARTED',
  'READ_ONLY_COMMISSIONING_COMPLETE',
  'CALIBRATION_COMPLETE',
  'PRE_MOTION_CHECKS_COMPLETE',
  'JOINT_MOTION_TESTING',
  'JOINT_MOTION_ACCEPTED',
  'KINEMATICS_VERIFICATION_PENDING',
  'CARTESIAN_ACCEPTED',
  'PLAYBACK_ACCEPTED',
  'VISION_FOLLOW_ACCEPTED',
  'FULL_ACCEPTANCE_COMPLETE',
]);

const FIELD_ACCEPTANCE_CAPABILITIES = new Set<FieldAcceptanceCapability>([
  'PRE_MOTION_CHECKS',
  'JOINT_MOTION',
  'CARTESIAN',
  'PLAYBACK',
  'VISION_FOLLOW',
]);

function requiredUuid(value: unknown, field: string): string {
  const parsed = nullableUuid(value, field);
  if (parsed === null) throw new TypeError(`Backend returned a missing ${field}`);
  return parsed;
}

function boundedUniqueUuids(value: unknown, field: string, maximum = 128): string[] {
  const items = boundedArray(value, field, maximum)
    .map((item) => requiredUuid(item, field));
  if (new Set(items).size !== items.length) {
    throw new TypeError(`Backend returned duplicate ${field}`);
  }
  return items;
}

function fieldAcceptanceJoint(value: unknown): FieldAcceptanceProgress['joints'][number] {
  if (!isRecord(value) || typeof value.complete !== 'boolean' ||
    (value.unit !== 'mm' && value.unit !== 'deg')) {
    throw new TypeError('Backend returned an invalid Field Acceptance joint');
  }
  const jointId = stringValue(value.joint_id);
  if (!jointId || jointId.length > 64) {
    throw new TypeError('Backend returned an invalid Field Acceptance joint identity');
  }
  const positiveEvidenceId = nullableUuid(
    value.positive_evidence_id,
    'positive Commissioning evidence ID',
  );
  const negativeEvidenceId = nullableUuid(
    value.negative_evidence_id,
    'negative Commissioning evidence ID',
  );
  if (value.complete !== (positiveEvidenceId !== null && negativeEvidenceId !== null)) {
    throw new TypeError('Backend returned incoherent Field Acceptance joint progress');
  }
  return {
    joint_id: jointId,
    unit: value.unit,
    positive_evidence_id: positiveEvidenceId,
    negative_evidence_id: negativeEvidenceId,
    complete: value.complete,
  };
}

export function normalizeFieldAcceptanceProgress(value: unknown): FieldAcceptanceProgress {
  if (!isRecord(value) || value.physical_stop_verification !== 'PENDING') {
    throw new TypeError('Backend returned invalid Field Acceptance progress');
  }
  const state = stringValue(value.state);
  const robotUnitId = stringValue(value.robot_unit_id);
  const checklistVersion = stringValue(value.checklist_version);
  if (!state || !FIELD_ACCEPTANCE_PROGRESS_STATES.has(state as FieldAcceptanceProgressState) ||
    !robotUnitId || robotUnitId.length > 128 ||
    !checklistVersion || checklistVersion.length > 64) {
    throw new TypeError('Backend returned incomplete Field Acceptance progress');
  }
  const booleanFields = [
    value.pre_motion_checks_complete,
    value.joint_motion_tests_complete,
    value.joint_motion_accepted,
    value.ready_to_accept_joint_motion,
    value.full_acceptance_complete,
  ];
  if (booleanFields.some((item) => typeof item !== 'boolean')) {
    throw new TypeError('Backend returned invalid Field Acceptance completion state');
  }
  const validCapabilities = boundedArray(
    value.valid_capabilities,
    'Field Acceptance capabilities',
    FIELD_ACCEPTANCE_CAPABILITIES.size,
  ).map((item) => {
    if (typeof item !== 'string' ||
      !FIELD_ACCEPTANCE_CAPABILITIES.has(item as FieldAcceptanceCapability)) {
      throw new TypeError('Backend returned an invalid Field Acceptance capability');
    }
    return item as FieldAcceptanceCapability;
  });
  if (new Set(validCapabilities).size !== validCapabilities.length) {
    throw new TypeError('Backend returned duplicate Field Acceptance capabilities');
  }
  const joints = boundedArray(value.joints, 'Field Acceptance joints', 32)
    .map(fieldAcceptanceJoint);
  if (new Set(joints.map((item) => item.joint_id)).size !== joints.length) {
    throw new TypeError('Backend returned duplicate Field Acceptance joints');
  }
  const selectedIds = boundedUniqueUuids(
    value.selected_test_evidence_ids,
    'selected Commissioning evidence IDs',
    64,
  );
  const jointEvidenceIds = joints.flatMap((joint) => [
    joint.positive_evidence_id,
    joint.negative_evidence_id,
  ]).filter((item): item is string => item !== null);
  const completedDirections = integerValue(
    value.completed_joint_directions,
    'completed joint directions',
  );
  const requiredDirections = integerValue(
    value.required_joint_directions,
    'required joint directions',
  );
  const testsComplete = joints.length > 0 && completedDirections === requiredDirections;
  if (requiredDirections !== joints.length * 2 ||
    completedDirections !== selectedIds.length ||
    completedDirections !== jointEvidenceIds.length ||
    selectedIds.some((id, index) => id !== jointEvidenceIds[index]) ||
    value.joint_motion_tests_complete !== testsComplete ||
    value.pre_motion_checks_complete !== validCapabilities.includes('PRE_MOTION_CHECKS') ||
    value.joint_motion_accepted !== validCapabilities.includes('JOINT_MOTION') ||
    value.ready_to_accept_joint_motion !== (
      value.pre_motion_checks_complete && testsComplete && !value.joint_motion_accepted
    ) ||
    value.full_acceptance_complete !== (
      validCapabilities.length === FIELD_ACCEPTANCE_CAPABILITIES.size
    )) {
    throw new TypeError('Backend returned incoherent Field Acceptance progress');
  }
  return {
    state: state as FieldAcceptanceProgressState,
    robot_unit_id: robotUnitId,
    checklist_version: checklistVersion,
    valid_capabilities: validCapabilities,
    pre_motion_checks_complete: value.pre_motion_checks_complete,
    joint_motion_tests_complete: value.joint_motion_tests_complete,
    joint_motion_accepted: value.joint_motion_accepted,
    ready_to_accept_joint_motion: value.ready_to_accept_joint_motion,
    completed_joint_directions: completedDirections,
    required_joint_directions: requiredDirections,
    joints,
    selected_test_evidence_ids: selectedIds,
    rejected_test_evidence_ids: boundedUniqueUuids(
      value.rejected_test_evidence_ids,
      'rejected Commissioning evidence IDs',
    ),
    stale_field_acceptance_evidence_ids: boundedUniqueUuids(
      value.stale_field_acceptance_evidence_ids,
      'stale Field Acceptance evidence IDs',
    ),
    legacy_field_acceptance_evidence_ids: boundedUniqueUuids(
      value.legacy_field_acceptance_evidence_ids,
      'legacy Field Acceptance evidence IDs',
    ),
    physical_stop_verification: 'PENDING',
    full_acceptance_complete: value.full_acceptance_complete,
  };
}

export async function getFieldAcceptanceProgress(
  signal?: AbortSignal,
): Promise<FieldAcceptanceProgress> {
  return normalizeFieldAcceptanceProgress(await requestJson<unknown>(
    '/device/field-acceptance/progress',
    { signal },
  ));
}

function currentChecklistVersion(value: string): string {
  const normalized = value.trim();
  if (!normalized || normalized.length > 64) {
    throw new TypeError('Field Acceptance checklist version must contain 1–64 characters');
  }
  return normalized;
}

export async function completeFieldPreMotionChecks(
  checklistVersion: string,
): Promise<FieldAcceptanceProgress> {
  return normalizeFieldAcceptanceProgress(await postJson<unknown>(
    '/device/field-acceptance/pre-motion-checks',
    { checklist_version: currentChecklistVersion(checklistVersion) },
  ));
}

export async function acceptFieldJointMotion(
  checklistVersion: string,
): Promise<FieldAcceptanceProgress> {
  return normalizeFieldAcceptanceProgress(await postJson<unknown>(
    '/device/field-acceptance/joint-motion',
    { checklist_version: currentChecklistVersion(checklistVersion) },
  ));
}

function kinematicsThresholds(value: unknown): KinematicsVerificationThresholds {
  if (!isRecord(value)) {
    throw new TypeError('Backend returned invalid Kinematics verification thresholds');
  }
  const position = finiteNumber(
    value.max_position_error_mm,
    'Kinematics position-error threshold',
    Number.EPSILON,
  );
  const orientation = finiteNumber(
    value.max_orientation_error_deg,
    'Kinematics orientation-error threshold',
    Number.EPSILON,
  );
  if (position > 25 || orientation > 15) {
    throw new TypeError('Backend returned out-of-range Kinematics verification thresholds');
  }
  return {
    max_position_error_mm: position,
    max_orientation_error_deg: orientation,
  };
}

function kinematicsJointState(value: unknown): KinematicsVerificationJointState {
  if (!isRecord(value) || !isRecord(value.positions) ||
    !(value.units === null || isRecord(value.units))) {
    throw new TypeError('Backend returned an invalid Kinematics joint state');
  }
  const positionEntries = Object.entries(value.positions);
  if (positionEntries.length === 0 || positionEntries.length > 32) {
    throw new TypeError('Backend returned an invalid Kinematics joint-state size');
  }
  const positions: Record<string, number> = {};
  for (const [jointId, position] of positionEntries) {
    if (!jointId || jointId.length > 64) {
      throw new TypeError('Backend returned an invalid Kinematics joint identity');
    }
    positions[jointId] = signedFiniteNumber(position, `Kinematics ${jointId} position`);
  }
  let units: KinematicsVerificationJointState['units'] = null;
  if (value.units !== null) {
    const unitEntries = Object.entries(value.units);
    if (unitEntries.length !== positionEntries.length ||
      unitEntries.some(([jointId, unit]) => (
        !(jointId in positions) || (unit !== 'mm' && unit !== 'deg')
      ))) {
      throw new TypeError('Backend returned incoherent Kinematics joint units');
    }
    units = Object.fromEntries(unitEntries) as Record<string, 'mm' | 'deg'>;
  }
  return { positions, units };
}

function kinematicsTcpPose(value: unknown, field: string): KinematicsVerificationPoint['measured_tcp'] {
  if (!isRecord(value) || !isRecord(value.position_mm) ||
    !isRecord(value.orientation_quaternion_xyzw)) {
    throw new TypeError(`Backend returned an invalid ${field}`);
  }
  const frame = stringValue(value.frame);
  if (!frame || frame.length > 128) throw new TypeError(`Backend returned an invalid ${field} frame`);
  const orientation = {
    x: signedFiniteNumber(value.orientation_quaternion_xyzw.x, `${field} quaternion X`),
    y: signedFiniteNumber(value.orientation_quaternion_xyzw.y, `${field} quaternion Y`),
    z: signedFiniteNumber(value.orientation_quaternion_xyzw.z, `${field} quaternion Z`),
    w: signedFiniteNumber(value.orientation_quaternion_xyzw.w, `${field} quaternion W`),
  };
  const quaternionNormSquared = orientation.x ** 2 + orientation.y ** 2 +
    orientation.z ** 2 + orientation.w ** 2;
  if (quaternionNormSquared < 1e-24) {
    throw new TypeError(`Backend returned a zero-norm ${field} quaternion`);
  }
  return {
    frame,
    position_mm: {
      x: signedFiniteNumber(value.position_mm.x, `${field} X coordinate`),
      y: signedFiniteNumber(value.position_mm.y, `${field} Y coordinate`),
      z: signedFiniteNumber(value.position_mm.z, `${field} Z coordinate`),
    },
    orientation_quaternion_xyzw: orientation,
  };
}

function kinematicsPoint(value: unknown): KinematicsVerificationPoint {
  if (!isRecord(value)) throw new TypeError('Backend returned an invalid Kinematics point');
  const label = stringValue(value.label);
  const jointStateCapturedAt = stringValue(value.joint_state_captured_at);
  const measuredAt = stringValue(value.measured_at);
  if (!label || label.length > 128 || !jointStateCapturedAt || !measuredAt) {
    throw new TypeError('Backend returned an incomplete Kinematics point');
  }
  return {
    point_id: requiredUuid(value.point_id, 'Kinematics point ID'),
    label,
    joint_state: kinematicsJointState(value.joint_state),
    joint_state_sequence: integerValue(
      value.joint_state_sequence,
      'Kinematics joint-state sequence',
    ),
    joint_state_captured_at: jointStateCapturedAt,
    snapshot_session_id: requiredUuid(
      value.snapshot_session_id,
      'Kinematics snapshot Operator Session ID',
    ),
    predicted_tcp: kinematicsTcpPose(value.predicted_tcp, 'predicted TCP pose'),
    measured_tcp: kinematicsTcpPose(value.measured_tcp, 'measured TCP pose'),
    position_error_mm: finiteNumber(value.position_error_mm, 'Kinematics position error'),
    orientation_error_deg: finiteNumber(
      value.orientation_error_deg,
      'Kinematics orientation error',
    ),
    measured_at: measuredAt,
  };
}

export function normalizeKinematicsVerificationStatus(
  value: unknown,
): KinematicsVerificationStatus {
  if (!isRecord(value) || !['MISSING', 'STALE', 'VALID'].includes(String(value.state))) {
    throw new TypeError('Backend returned invalid Kinematics verification status');
  }
  const evidenceId = nullableUuid(value.evidence_id, 'Kinematics verification evidence ID');
  const pointCount = integerValue(value.point_count, 'Kinematics verification point count');
  const staleFields = boundedUniqueStrings(
    value.stale_fields,
    'Kinematics verification stale fields',
  );
  if ((value.state === 'MISSING' && (evidenceId !== null || pointCount !== 0)) ||
    (value.state === 'VALID' && (evidenceId === null || pointCount < 3))) {
    throw new TypeError('Backend returned incoherent Kinematics verification status');
  }
  return {
    state: value.state as KinematicsVerificationStatus['state'],
    stale_fields: staleFields,
    evidence_id: evidenceId,
    point_count: pointCount,
  };
}

export function normalizeKinematicsVerificationDraft(
  value: unknown,
): KinematicsVerificationDraft {
  if (!isRecord(value)) throw new TypeError('Backend returned an invalid Kinematics draft');
  const operatorId = stringValue(value.operator_id);
  const robotUnitId = stringValue(value.robot_unit_id);
  const softwareCommit = stringValue(value.software_commit);
  const checklist = stringValue(value.verification_checklist_version);
  if (!operatorId || operatorId.length > 128 || !robotUnitId || robotUnitId.length > 128 ||
    !softwareCommit || softwareCommit.length > 64 || !checklist || checklist.length > 64) {
    throw new TypeError('Backend returned an incomplete Kinematics draft');
  }
  const points = boundedArray(value.points, 'Kinematics verification points', 128)
    .map(kinematicsPoint);
  if (new Set(points.map((point) => point.point_id)).size !== points.length) {
    throw new TypeError('Backend returned duplicate Kinematics point IDs');
  }
  const operatorSessionId = requiredUuid(
    value.operator_session_id,
    'Kinematics Operator Session ID',
  );
  if (points.some((point) => point.snapshot_session_id !== operatorSessionId)) {
    throw new TypeError('Backend returned a Kinematics point from another Operator Session');
  }
  return {
    draft_id: requiredUuid(value.draft_id, 'Kinematics draft ID'),
    operator_session_id: operatorSessionId,
    operator_id: operatorId,
    robot_unit_id: robotUnitId,
    profile_fingerprint: fingerprint(value.profile_fingerprint, 'Kinematics Profile fingerprint'),
    calibration_fingerprint: fingerprint(
      value.calibration_fingerprint,
      'Kinematics Calibration fingerprint',
    ),
    device_fingerprint: fingerprint(value.device_fingerprint, 'Kinematics device fingerprint'),
    kinematics_fingerprint: fingerprint(
      value.kinematics_fingerprint,
      'Kinematics model fingerprint',
    ),
    software_commit: softwareCommit,
    verification_checklist_version: checklist,
    thresholds: kinematicsThresholds(value.thresholds),
    points,
  };
}

export function normalizeKinematicsVerificationEvidence(
  value: unknown,
): KinematicsVerificationEvidence {
  if (!isRecord(value) || value.schema_version !== 1 || value.revision !== 1 ||
    (value.variant !== 'V1' && value.variant !== 'V2')) {
    throw new TypeError('Backend returned invalid Kinematics verification evidence');
  }
  const robotUnitId = stringValue(value.robot_unit_id);
  const modelSchema = stringValue(value.kinematics_model_schema_version);
  const checklist = stringValue(value.verification_checklist_version);
  const acceptedAt = stringValue(value.accepted_at);
  const acceptedBy = stringValue(value.accepted_by);
  const softwareCommit = stringValue(value.software_commit);
  if (!robotUnitId || !modelSchema || !checklist || !acceptedAt || !acceptedBy ||
    !softwareCommit) {
    throw new TypeError('Backend returned incomplete Kinematics verification evidence');
  }
  const thresholds = kinematicsThresholds(value.thresholds);
  const points = boundedArray(value.test_points, 'Kinematics evidence points', 128)
    .map(kinematicsPoint);
  if (points.length < 3 || new Set(points.map((point) => point.point_id)).size !== points.length ||
    new Set(points.map((point) => point.joint_state_sequence)).size !== points.length ||
    points.some((point) => (
      point.position_error_mm > thresholds.max_position_error_mm ||
      point.orientation_error_deg > thresholds.max_orientation_error_deg
    ))) {
    throw new TypeError('Backend returned incoherent Kinematics verification evidence');
  }
  return {
    schema_version: 1,
    revision: 1,
    id: requiredUuid(value.id, 'Kinematics verification evidence ID'),
    robot_unit_id: robotUnitId,
    variant: value.variant,
    profile_fingerprint: fingerprint(value.profile_fingerprint, 'Kinematics Profile fingerprint'),
    calibration_fingerprint: fingerprint(
      value.calibration_fingerprint,
      'Kinematics Calibration fingerprint',
    ),
    device_fingerprint: fingerprint(value.device_fingerprint, 'Kinematics device fingerprint'),
    kinematics_fingerprint: fingerprint(
      value.kinematics_fingerprint,
      'Kinematics model fingerprint',
    ),
    kinematics_model_schema_version: modelSchema,
    verification_checklist_version: checklist,
    test_points: points,
    thresholds,
    accepted_at: acceptedAt,
    accepted_by: acceptedBy,
    software_commit: softwareCommit,
  };
}

export async function getKinematicsVerificationStatus(
  signal?: AbortSignal,
): Promise<KinematicsVerificationStatus> {
  return normalizeKinematicsVerificationStatus(await requestJson<unknown>(
    '/kinematics-verification',
    { signal },
  ));
}

export async function startKinematicsVerificationDraft(
  thresholds: KinematicsVerificationThresholds | null = null,
): Promise<KinematicsVerificationDraft> {
  const normalizedThresholds = thresholds === null ? null : kinematicsThresholds(thresholds);
  return normalizeKinematicsVerificationDraft(await postJson<unknown>(
    '/kinematics-verification/draft',
    { thresholds: normalizedThresholds },
  ));
}

export async function addKinematicsVerificationMeasurement(
  draftId: string,
  request: KinematicsVerificationMeasurementRequest,
): Promise<KinematicsVerificationDraft> {
  const normalizedDraftId = requiredUuid(draftId, 'Kinematics draft ID');
  const label = request.label.trim();
  if (!label || label.length > 128) {
    throw new TypeError('Kinematics measurement label must contain 1–128 characters');
  }
  return normalizeKinematicsVerificationDraft(await postJson<unknown>(
    `/kinematics-verification/draft/${encodeURIComponent(normalizedDraftId)}/measurement`,
    {
      label,
      measured_tcp: kinematicsTcpPose(request.measured_tcp, 'measured TCP pose'),
    },
  ));
}

export async function commitKinematicsVerificationDraft(
  draftId: string,
): Promise<KinematicsVerificationEvidence> {
  const normalizedDraftId = requiredUuid(draftId, 'Kinematics draft ID');
  return normalizeKinematicsVerificationEvidence(await postJson<unknown>(
    `/kinematics-verification/draft/${encodeURIComponent(normalizedDraftId)}/commit`,
  ));
}

export async function createOperatorSession(
  purpose: OperatorSessionPurpose,
  confirmationText: string,
  physicalEstopConfirmed: boolean,
  workspaceClearConfirmed = false,
): Promise<OperatorSessionResponse> {
  return operatorSession(await postJson<unknown>('/device/operator-session', {
    purpose,
    confirmation_text: confirmationText,
    physical_estop_confirmed: physicalEstopConfirmed,
    workspace_clear_confirmed: workspaceClearConfirmed,
  }));
}

export async function revokeOperatorSession(): Promise<void> {
  await requestJson<unknown>('/device/operator-session', {
    method: 'DELETE',
  });
}

export async function connectRealDevice(): Promise<DeviceDiagnostics> {
  const value = await postJson<unknown>('/device/connect');
  if (!isRecord(value)) throw new TypeError('Backend returned invalid Real connect result');
  return normalizeDeviceDiagnostics(value.diagnostics ?? value);
}

export async function disconnectRealDevice(): Promise<DeviceDiagnostics> {
  const value = await postJson<unknown>('/device/disconnect');
  if (!isRecord(value)) throw new TypeError('Backend returned invalid Real disconnect result');
  return normalizeDeviceDiagnostics(value.diagnostics ?? value);
}

export async function runDeviceDiagnostics(): Promise<DeviceDiagnostics> {
  return normalizeDeviceDiagnostics(await postJson<unknown>('/device/diagnostics'));
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

const COMMISSIONING_MOTION_STATES = new Set<CommissioningMotionTestState>([
  'IDLE',
  'AUTHORIZED',
  'ARMED',
  'MOVING',
  'VERIFYING',
  'STOPPING',
  'COMPLETED',
  'FAILED',
  'EXPIRED',
]);

export function normalizeCommissioningMotionStatus(value: unknown): CommissioningMotionStatus {
  if (!isRecord(value) || value.physical_stop_verification !== 'PENDING') {
    throw new TypeError('Backend returned invalid Commissioning Motion status');
  }
  const state = stringValue(value.state);
  if (!state || !COMMISSIONING_MOTION_STATES.has(state as CommissioningMotionTestState)) {
    throw new TypeError('Backend returned invalid Commissioning Motion state');
  }
  return {
    state: state as CommissioningMotionTestState,
    session_id: nullableUuid(value.session_id, 'Commissioning Motion session ID'),
    active_joint_id: nullableString(value.active_joint_id, 'Commissioning active joint'),
    command_count: integerValue(value.command_count, 'Commissioning command count'),
    session_expires_at: nullableString(
      value.session_expires_at,
      'Commissioning session expiry',
    ),
    deadman_expires_at: nullableString(
      value.deadman_expires_at,
      'Commissioning deadman expiry',
    ),
    last_evidence_id: nullableUuid(value.last_evidence_id, 'Commissioning evidence ID'),
    failure_reason: nullableString(value.failure_reason, 'Commissioning failure reason'),
    physical_stop_verification: 'PENDING',
  };
}

export function normalizeCommissioningDirectControl(
  value: unknown,
): CommissioningDirectControlResponse {
  if (!isRecord(value) || typeof value.running !== 'boolean') {
    throw new TypeError('Backend returned invalid direct-control status');
  }
  const mode = stringValue(value.mode);
  const message = stringValue(value.message);
  const jointId = nullableString(value.joint_id, 'Direct-control joint');
  const direction = value.direction;
  if (
    !mode || !['STEP', 'CONTINUOUS', 'IDLE'].includes(mode) || !message ||
    !(direction === null || direction === -1 || direction === 1)
  ) {
    throw new TypeError('Backend returned incomplete direct-control status');
  }
  const nullableFinite = (item: unknown, field: string): number | null =>
    item === null ? null : signedFiniteNumber(item, field);
  return {
    running: value.running,
    mode: mode as CommissioningDirectControlResponse['mode'],
    joint_id: jointId,
    direction: direction as -1 | 1 | null,
    requested_speed: nullableFinite(value.requested_speed, 'Direct-control speed'),
    logical_position: nullableFinite(value.logical_position, 'Direct-control position'),
    raw_position: value.raw_position === null
      ? null
      : integerValue(value.raw_position, 'Direct-control raw position', Number.MIN_SAFE_INTEGER),
    target_value: nullableFinite(value.target_value, 'Direct-control target'),
    message,
  };
}

function normalizeDirectJointMaps(value: Record<string, unknown>, prefix: string) {
  if (!isRecord(value.positions) || !isRecord(value.units) || !isRecord(value.raw_positions)) {
    throw new TypeError(`Backend returned invalid ${prefix} joint maps`);
  }
  const positions: Record<string, number> = {};
  const units: Record<string, 'mm' | 'deg'> = {};
  const rawPositions: Record<string, number> = {};
  for (const [jointId, rawValue] of Object.entries(value.positions)) {
    positions[jointId] = signedFiniteNumber(rawValue, `${prefix} ${jointId} position`);
    const unit = value.units[jointId];
    if (unit !== 'mm' && unit !== 'deg') throw new TypeError(`${prefix} ${jointId} unit is invalid`);
    units[jointId] = unit;
    rawPositions[jointId] = integerValue(
      value.raw_positions[jointId],
      `${prefix} ${jointId} raw position`,
      Number.MIN_SAFE_INTEGER,
    );
  }
  return { positions, units, raw_positions: rawPositions };
}

export function normalizeCommissioningDirectJointState(
  value: unknown,
): CommissioningDirectJointStateResponse {
  if (!isRecord(value) || typeof value.moving !== 'boolean') {
    throw new TypeError('Backend returned invalid direct joint state');
  }
  const capturedAt = stringValue(value.captured_at);
  const message = stringValue(value.message);
  if (!capturedAt || !message) throw new TypeError('Backend returned incomplete direct joint state');
  return {
    ...normalizeDirectJointMaps(value, 'direct state'),
    captured_at: capturedAt,
    moving: value.moving,
    message,
  };
}

export function normalizeCommissioningDirectJointMove(
  value: unknown,
): CommissioningDirectJointMoveResponse {
  if (!isRecord(value) || typeof value.completed !== 'boolean') {
    throw new TypeError('Backend returned invalid direct joint move');
  }
  const message = stringValue(value.message);
  if (!message) throw new TypeError('Backend returned incomplete direct joint move');
  return {
    ...normalizeDirectJointMaps(value, 'direct move'),
    duration_s: finiteNumber(value.duration_s, 'Direct move duration', 0.1),
    frame_count: integerValue(value.frame_count, 'Direct move frame count', 1),
    completed: value.completed,
    message,
  };
}

export function normalizeCommissioningTestEvidence(value: unknown): CommissioningTestEvidence {
  if (!isRecord(value) || value.schema_version !== 1 || value.revision !== 1 ||
    (value.robot_variant !== 'V1' && value.robot_variant !== 'V2') ||
    (value.unit !== 'mm' && value.unit !== 'deg')) {
    throw new TypeError('Backend returned invalid Commissioning Test evidence');
  }
  const id = nullableUuid(value.id, 'Commissioning Test evidence ID');
  const sessionId = nullableUuid(value.session_id, 'Commissioning Test session ID');
  const robotUnitId = stringValue(value.robot_unit_id);
  const jointId = stringValue(value.joint_id);
  const measuredResult = stringValue(value.measured_or_observed_result);
  const startedAt = stringValue(value.started_at);
  const completedAt = stringValue(value.completed_at);
  const softwareCommit = stringValue(value.software_commit);
  const operatorId = stringValue(value.operator_id);
  const requestId = stringValue(value.request_id);
  const directionExpected = value.direction_expected;
  const directionObserved = value.direction_observed;
  const stopBehavior = value.stop_behavior;
  const result = value.result;
  if (!id || !sessionId || !robotUnitId || !jointId || !measuredResult || !startedAt ||
    !completedAt || !softwareCommit || !operatorId || !requestId ||
    !['POSITIVE', 'NEGATIVE'].includes(String(directionExpected)) ||
    !(directionObserved === null || ['POSITIVE', 'NEGATIVE'].includes(String(directionObserved))) ||
    ![
      'NOT_REQUESTED',
      'SOFTWARE_PATH_VERIFIED',
      'SOFTWARE_PATH_FAILED',
      'PHYSICAL_BEHAVIOR_PENDING',
    ].includes(String(stopBehavior)) || !['PASSED', 'FAILED'].includes(String(result))) {
    throw new TypeError('Backend returned incomplete Commissioning Test evidence');
  }
  const failureReason = nullableString(
    value.failure_reason_optional,
    'Commissioning Test failure reason',
  );
  if ((result === 'PASSED' && failureReason !== null) ||
    (result === 'FAILED' && failureReason === null)) {
    throw new TypeError('Backend returned incoherent Commissioning Test evidence');
  }
  return {
    schema_version: 1,
    revision: 1,
    id,
    robot_unit_id: robotUnitId,
    robot_variant: value.robot_variant,
    profile_fingerprint: fingerprint(value.profile_fingerprint, 'Commissioning Profile fingerprint'),
    calibration_fingerprint: fingerprint(
      value.calibration_fingerprint,
      'Commissioning Calibration fingerprint',
    ),
    device_fingerprint: fingerprint(value.device_fingerprint, 'Commissioning device fingerprint'),
    joint_id: jointId,
    unit: value.unit,
    start_value: signedFiniteNumber(value.start_value, 'Commissioning start value'),
    requested_delta: signedFiniteNumber(value.requested_delta, 'Commissioning requested delta'),
    target_value: signedFiniteNumber(value.target_value, 'Commissioning target value'),
    final_value: signedFiniteNumber(value.final_value, 'Commissioning final value'),
    start_raw: integerValue(value.start_raw, 'Commissioning start raw', Number.MIN_SAFE_INTEGER),
    final_raw: integerValue(value.final_raw, 'Commissioning final raw', Number.MIN_SAFE_INTEGER),
    requested_speed: finiteNumber(value.requested_speed, 'Commissioning requested speed', Number.EPSILON),
    measured_or_observed_result: measuredResult,
    direction_expected: directionExpected as CommissioningTestEvidence['direction_expected'],
    direction_observed: directionObserved as CommissioningTestEvidence['direction_observed'],
    divergence: finiteNumber(value.divergence, 'Commissioning divergence'),
    stop_behavior: stopBehavior as CommissioningTestEvidence['stop_behavior'],
    started_at: startedAt,
    completed_at: completedAt,
    software_commit: softwareCommit,
    operator_id: operatorId,
    request_id: requestId,
    session_id: sessionId,
    prepared_target_raw: integerValue(
      value.prepared_target_raw,
      'Commissioning prepared raw target',
      Number.MIN_SAFE_INTEGER,
    ),
    result: result as CommissioningTestEvidence['result'],
    failure_reason_optional: failureReason,
  };
}

export async function getCommissioningMotionStatus(
  signal?: AbortSignal,
): Promise<CommissioningMotionStatus> {
  return normalizeCommissioningMotionStatus(await requestJson<unknown>(
    '/device/commissioning/status',
    { signal },
  ));
}

export async function startCommissioningMotionSession(): Promise<CommissioningMotionStatus> {
  return normalizeCommissioningMotionStatus(await postJson<unknown>(
    '/device/commissioning/session',
  ));
}

export async function armCommissioningJoint(
  jointId: string,
): Promise<CommissioningMotionStatus> {
  return normalizeCommissioningMotionStatus(await postJson<unknown>(
    `/device/commissioning/joints/${encodeURIComponent(jointId)}/arm`,
  ));
}

export async function startCommissioningJointTest(
  jointId: string,
  request: CommissioningRelativeTestRequest,
): Promise<CommissioningTestEvidence> {
  return normalizeCommissioningTestEvidence(await postJson<unknown>(
    `/device/commissioning/joints/${encodeURIComponent(jointId)}/tests/start`,
    request,
  ));
}

export async function heartbeatCommissioningMotionTest(): Promise<CommissioningMotionStatus> {
  return normalizeCommissioningMotionStatus(await postJson<unknown>(
    '/device/commissioning/tests/heartbeat',
  ));
}

export async function stopCommissioningMotionTest(
  reason: string,
): Promise<CommissioningMotionStatus> {
  const normalizedReason = reason.trim();
  if (!normalizedReason || normalizedReason.length > 128) {
    throw new TypeError('Commissioning Stop reason must contain 1–128 characters');
  }
  return normalizeCommissioningMotionStatus(await postJson<unknown>(
    '/device/commissioning/tests/stop',
    { reason: normalizedReason },
  ));
}

export async function directCommissioningStep(
  jointId: string,
  signedDelta: number,
  requestedSpeed: number,
): Promise<CommissioningDirectControlResponse> {
  return normalizeCommissioningDirectControl(await postJson<unknown>(
    `/device/commissioning/joints/${encodeURIComponent(jointId)}/direct/step`,
    { signed_delta: signedDelta, requested_speed: requestedSpeed },
  ));
}

export async function startCommissioningDirectJog(
  jointId: string,
  direction: -1 | 1,
  requestedSpeed: number,
): Promise<CommissioningDirectControlResponse> {
  return normalizeCommissioningDirectControl(await postJson<unknown>(
    `/device/commissioning/joints/${encodeURIComponent(jointId)}/direct/jog/start`,
    { direction, requested_speed: requestedSpeed },
  ));
}

export async function heartbeatCommissioningDirectJog(): Promise<CommissioningDirectControlResponse> {
  return normalizeCommissioningDirectControl(await postJson<unknown>(
    '/device/commissioning/direct/jog/heartbeat',
  ));
}

export async function stopCommissioningDirectJog(
  keepalive = false,
): Promise<CommissioningDirectControlResponse> {
  return normalizeCommissioningDirectControl(await postJson<unknown>(
    '/device/commissioning/direct/jog/stop',
    undefined,
    { keepalive },
  ));
}

export async function getCommissioningDirectJointState(): Promise<CommissioningDirectJointStateResponse> {
  return normalizeCommissioningDirectJointState(await requestJson<unknown>(
    '/device/commissioning/direct/joints/state',
  ));
}

export async function moveCommissioningDirectJoints(
  positions: Record<string, number>,
  durationS: number,
): Promise<CommissioningDirectJointMoveResponse> {
  return normalizeCommissioningDirectJointMove(await postJson<unknown>(
    '/device/commissioning/direct/joints/move',
    { positions, duration_s: durationS },
  ));
}

const RAW_DIRECTION_STATES = new Set<RawDirectionTestState>([
  'IDLE',
  'ZERO_CAPTURED',
  'ARMED',
  'MOVING',
  'STOPPING',
  'COMPLETED',
  'FAILED',
  'EXPIRED',
]);

function rawDirection(value: unknown): RawDirection {
  if (value !== 'RAW_PLUS' && value !== 'RAW_MINUS') {
    throw new TypeError('Backend returned an invalid Raw direction');
  }
  return value;
}

export function normalizeRawDirectionStatus(value: unknown): RawDirectionStatus {
  if (!isRecord(value)) throw new TypeError('Backend returned invalid Raw direction status');
  const state = stringValue(value.state);
  if (!state || !RAW_DIRECTION_STATES.has(state as RawDirectionTestState)) {
    throw new TypeError('Backend returned invalid Raw direction state');
  }
  let zeroSnapshot: RawDirectionStatus['zero_snapshot'] = null;
  if (value.zero_snapshot !== null) {
    if (!isRecord(value.zero_snapshot) || !isRecord(value.zero_snapshot.raw_by_joint)) {
      throw new TypeError('Backend returned invalid Raw zero snapshot');
    }
    const rawEntries = Object.entries(value.zero_snapshot.raw_by_joint);
    if (rawEntries.length === 0 || rawEntries.length > 32) {
      throw new TypeError('Backend returned an invalid Raw zero joint set');
    }
    zeroSnapshot = {
      session_id: nullableUuid(value.zero_snapshot.session_id, 'Raw zero session ID') ?? (() => {
        throw new TypeError('Backend omitted Raw zero session ID');
      })(),
      robot_unit_id: stringValue(value.zero_snapshot.robot_unit_id) ?? (() => {
        throw new TypeError('Backend omitted Raw zero robot unit');
      })(),
      captured_at: stringValue(value.zero_snapshot.captured_at) ?? (() => {
        throw new TypeError('Backend omitted Raw zero capture time');
      })(),
      raw_by_joint: Object.fromEntries(rawEntries.map(([jointId, raw]) => {
        if (!jointId || jointId.length > 32) throw new TypeError('Backend returned invalid Raw joint');
        return [jointId, integerValue(raw, `Raw zero ${jointId}`, -32767)];
      })),
    };
  }
  let observation: RawDirectionStatus['last_observation'] = null;
  const normalizeObservation = (rawObservation: unknown): RawDirectionObservation => {
    if (!isRecord(rawObservation)) {
      throw new TypeError('Backend returned invalid Raw direction observation');
    }
    const commandId = nullableUuid(rawObservation.command_id, 'Raw command ID');
    const jointId = stringValue(rawObservation.joint_id);
    const completedAt = stringValue(rawObservation.completed_at);
    if (!commandId || !jointId || !completedAt ||
      typeof rawObservation.software_only_adapter !== 'boolean') {
      throw new TypeError('Backend returned incomplete Raw direction observation');
    }
    return {
      command_id: commandId,
      joint_id: jointId,
      servo_id: integerValue(rawObservation.servo_id, 'Raw Servo ID'),
      direction: rawDirection(rawObservation.direction),
      zero_raw: integerValue(rawObservation.zero_raw, 'Raw zero', -32767),
      start_raw: integerValue(rawObservation.start_raw, 'Raw start', -32767),
      target_raw: integerValue(rawObservation.target_raw, 'Raw target', -32767),
      final_raw: integerValue(rawObservation.final_raw, 'Raw final', -32767),
      completed_at: completedAt,
      software_only_adapter: rawObservation.software_only_adapter,
    };
  };
  if (value.last_observation !== null) {
    observation = normalizeObservation(value.last_observation);
  }
  const observations = boundedArray(value.observations, 'Raw direction observations', 64)
    .map(normalizeObservation);
  let calibrationDraft: RawDirectionStatus['calibration_draft'] = null;
  if (value.calibration_draft !== null) {
    if (!isRecord(value.calibration_draft)) {
      throw new TypeError('Backend returned invalid Raw calibration draft');
    }
    const robotUnitId = stringValue(value.calibration_draft.robot_unit_id);
    const source = stringValue(value.calibration_draft.source);
    const sourceRevision = stringValue(value.calibration_draft.source_revision);
    if (!robotUnitId || !source || !sourceRevision ||
      typeof value.calibration_draft.complete_for_review !== 'boolean' ||
      typeof value.calibration_draft.confirmed_for_review !== 'boolean') {
      throw new TypeError('Backend returned incomplete Raw calibration draft');
    }
    const confirmedAt = nullableString(
      value.calibration_draft.confirmed_at,
      'Raw draft confirmation time',
    );
    if (value.calibration_draft.confirmed_for_review !== (confirmedAt !== null) ||
      (value.calibration_draft.confirmed_for_review &&
        !value.calibration_draft.complete_for_review)) {
      throw new TypeError('Backend returned incoherent Raw calibration draft confirmation');
    }
    const joints = boundedArray(value.calibration_draft.joints, 'Raw calibration joints', 32)
      .map((joint) => {
        if (!isRecord(joint) || typeof joint.matches_urdf !== 'boolean' &&
          joint.matches_urdf !== null) {
          throw new TypeError('Backend returned invalid Raw calibration joint');
        }
        const jointId = stringValue(joint.joint_id);
        const profileDirection = integerValue(
          joint.profile_direction_candidate,
          'Raw candidate sign',
          -1,
        );
        const resolvedDirection = joint.resolved_calibration_direction === null
          ? null
          : integerValue(joint.resolved_calibration_direction, 'Raw resolved sign', -1);
        const bounds = boundedArray(joint.raw_bounds_candidate, 'Raw bounds', 2);
        if (!jointId || ![-1, 1].includes(profileDirection) ||
          !(resolvedDirection === null || [-1, 1].includes(resolvedDirection)) ||
          bounds.length !== 2) {
          throw new TypeError('Backend returned incoherent Raw calibration joint');
        }
        return {
          joint_id: jointId,
          servo_id: integerValue(joint.servo_id, 'Raw draft Servo ID'),
          home_present_raw: integerValue(joint.home_present_raw, 'Raw draft zero', -32767),
          profile_direction_candidate: profileDirection as -1 | 1,
          matches_urdf: joint.matches_urdf,
          resolved_calibration_direction: resolvedDirection as -1 | 1 | null,
          phase_candidate: integerValue(joint.phase_candidate, 'Raw phase candidate'),
          raw_bounds_candidate: [
            integerValue(bounds[0], 'Raw lower bound', -32767),
            integerValue(bounds[1], 'Raw upper bound', -32767),
          ] as [number, number],
        };
      });
    calibrationDraft = {
      robot_unit_id: robotUnitId,
      profile_fingerprint: fingerprint(
        value.calibration_draft.profile_fingerprint,
        'Raw draft Profile fingerprint',
      ),
      source,
      source_revision: sourceRevision,
      complete_for_review: value.calibration_draft.complete_for_review,
      confirmed_for_review: value.calibration_draft.confirmed_for_review,
      confirmed_at: confirmedAt,
      joints,
    };
  }
  return {
    state: state as RawDirectionTestState,
    session_id: nullableUuid(value.session_id, 'Raw direction session ID'),
    active_joint_id: nullableString(value.active_joint_id, 'Raw direction active joint'),
    command_count: integerValue(value.command_count, 'Raw direction command count'),
    session_expires_at: nullableString(value.session_expires_at, 'Raw direction session expiry'),
    deadman_expires_at: nullableString(value.deadman_expires_at, 'Raw direction deadman expiry'),
    zero_snapshot: zeroSnapshot,
    last_observation: observation,
    observations,
    calibration_draft: calibrationDraft,
    failure_reason: nullableString(value.failure_reason, 'Raw direction failure reason'),
  };
}

export async function getRawDirectionStatus(signal?: AbortSignal): Promise<RawDirectionStatus> {
  return normalizeRawDirectionStatus(await requestJson<unknown>(
    '/device/commissioning/raw-direction/status',
    { signal },
  ));
}

export async function startRawDirectionSession(): Promise<RawDirectionStatus> {
  return normalizeRawDirectionStatus(await postJson<unknown>(
    '/device/commissioning/raw-direction/session',
  ));
}

export async function armRawDirectionJoint(jointId: string): Promise<RawDirectionStatus> {
  return normalizeRawDirectionStatus(await postJson<unknown>(
    `/device/commissioning/raw-direction/joints/${encodeURIComponent(jointId)}/arm`,
  ));
}

export async function stepRawDirectionJoint(
  jointId: string,
  direction: RawDirection,
): Promise<RawDirectionStatus> {
  return normalizeRawDirectionStatus(await postJson<unknown>(
    `/device/commissioning/raw-direction/joints/${encodeURIComponent(jointId)}/step`,
    { direction },
  ));
}

export async function heartbeatRawDirectionTest(): Promise<RawDirectionStatus> {
  return normalizeRawDirectionStatus(await postJson<unknown>(
    '/device/commissioning/raw-direction/heartbeat',
  ));
}

export async function recordRawDirectionAlignment(
  jointId: string,
  matchesUrdf: boolean,
): Promise<RawDirectionStatus> {
  return normalizeRawDirectionStatus(await postJson<unknown>(
    `/device/commissioning/raw-direction/joints/${encodeURIComponent(jointId)}/alignment`,
    { matches_urdf: matchesUrdf },
  ));
}

export async function confirmRawDirectionDraft(): Promise<RawDirectionStatus> {
  return normalizeRawDirectionStatus(await postJson<unknown>(
    '/device/commissioning/raw-direction/draft/confirm',
    { confirmation_text: 'I CONFIRM RAW ZERO AND DIRECTIONS FOR CALIBRATION DRAFT' },
  ));
}

export async function stopRawDirectionTest(): Promise<RawDirectionStatus> {
  return normalizeRawDirectionStatus(await postJson<unknown>(
    '/device/commissioning/raw-direction/stop',
  ));
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

function nullableFingerprint(value: unknown, field: string): string | null {
  return value === null ? null : fingerprint(value, field);
}

function nullableRevision(value: unknown, field: string): number | null {
  return value === null ? null : integerValue(value, field, 1);
}

function calibrationWorkflowSource(value: unknown): CalibrationWorkflowSource {
  if (value !== 'EXISTING_REAL' && value !== 'EXPLICIT_LEGACY_IMPORT') {
    throw new TypeError('Backend returned an invalid calibration source');
  }
  return value;
}

function nullableDraftInteger(value: unknown, field: string): number | null {
  return value === null
    ? null
    : integerValue(value, field, Number.MIN_SAFE_INTEGER);
}

function calibrationJointDraft(value: unknown): CalibrationJointDraft {
  if (!isRecord(value)) throw new TypeError('Backend returned an invalid calibration joint draft');
  const jointId = stringValue(value.joint_id);
  if (!jointId) throw new TypeError('Backend returned a calibration joint draft without identity');
  let rawBounds: [number, number] | null = null;
  if (value.raw_bounds !== null) {
    const bounds = arrayValue(value.raw_bounds, 'calibration draft raw bounds');
    if (bounds.length !== 2) throw new TypeError('Backend returned invalid calibration draft bounds');
    const lower = integerValue(bounds[0], 'calibration draft lower bound', Number.MIN_SAFE_INTEGER);
    const upper = integerValue(bounds[1], 'calibration draft upper bound', Number.MIN_SAFE_INTEGER);
    if (lower >= upper) throw new TypeError('Backend returned reversed calibration draft bounds');
    rawBounds = [lower, upper];
  }
  if (value.direction !== null && value.direction !== -1 && value.direction !== 1) {
    throw new TypeError('Backend returned an invalid calibration draft direction');
  }
  return {
    joint_id: jointId,
    servo_id: integerValue(value.servo_id, 'calibration draft Servo ID', 1),
    present_raw: nullableDraftInteger(value.present_raw, 'calibration draft present raw'),
    logical_value: value.logical_value === null
      ? null
      : signedFiniteNumber(value.logical_value, 'calibration draft logical value'),
    direction: value.direction,
    phase: nullableDraftInteger(value.phase, 'calibration draft phase'),
    raw_bounds: rawBounds,
    operating_mode: nullableString(value.operating_mode, 'calibration draft operating mode'),
  };
}

function calibrationDraft(value: unknown): CalibrationDraft {
  if (!isRecord(value) || (value.robot_variant !== 'V1' && value.robot_variant !== 'V2')) {
    throw new TypeError('Backend returned an invalid calibration draft');
  }
  const createdAt = stringValue(value.created_at);
  if (!createdAt) throw new TypeError('Backend returned a calibration draft without creation time');
  const enabledJoints = boundedArray(value.enabled_joints, 'calibration draft joints', 32)
    .map((jointId) => {
      const parsed = stringValue(jointId);
      if (!parsed) throw new TypeError('Backend returned an invalid calibration draft joint ID');
      return parsed;
    });
  const joints = boundedArray(value.joints, 'calibration joint drafts', 32)
    .map(calibrationJointDraft);
  if (
    enabledJoints.length === 0 ||
    new Set(enabledJoints).size !== enabledJoints.length ||
    joints.length !== enabledJoints.length ||
    joints.some((joint, index) => joint.joint_id !== enabledJoints[index])
  ) {
    throw new TypeError('Backend returned incoherent calibration draft joints');
  }
  return {
    robot_variant: value.robot_variant,
    profile_fingerprint: fingerprint(value.profile_fingerprint, 'calibration draft Profile fingerprint'),
    enabled_joints: enabledJoints,
    created_at: createdAt,
    base_revision: nullableRevision(value.base_revision, 'calibration draft base revision'),
    base_calibration_fingerprint: nullableFingerprint(
      value.base_calibration_fingerprint,
      'calibration draft base fingerprint',
    ),
    joints,
  };
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
    base_revision: nullableRevision(value.base_revision, 'save preview base revision'),
    base_calibration_fingerprint: nullableFingerprint(
      value.base_calibration_fingerprint,
      'save preview base calibration fingerprint',
    ),
    source: calibrationWorkflowSource(value.source),
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
  const authorizationSessionId = stringValue(value.authorization_session_id);
  const robotId = stringValue(value.robot_id);
  const state = stringValue(value.state);
  const updatedAt = stringValue(value.updated_at);
  if (!sessionId || !authorizationSessionId || !robotId || !state ||
    !CALIBRATION_STATES.has(state as CalibrationWorkflowState) ||
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
  const draft = calibrationDraft(value.draft);
  const source = calibrationWorkflowSource(value.source);
  const baseRevision = nullableRevision(value.base_revision, 'calibration base revision');
  const baseFingerprint = nullableFingerprint(
    value.base_calibration_fingerprint,
    'base calibration fingerprint',
  );
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
    authorization_session_id: authorizationSessionId,
    robot_id: robotId,
    variant: value.variant,
    profile_fingerprint: fingerprint(value.profile_fingerprint, 'calibration Profile fingerprint'),
    base_revision: baseRevision,
    base_calibration_fingerprint: baseFingerprint,
    draft,
    source,
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

export async function startCalibrationSession(): Promise<CalibrationWorkflowStatus> {
  return normalizeCalibrationWorkflowStatus(await postJson<unknown>(
    '/device/calibration/sessions',
    { source: 'EXISTING_REAL' },
  ));
}

export async function readCalibrationJoint(
  sessionId: string,
  jointId: string,
): Promise<CalibrationWorkflowStatus> {
  return normalizeCalibrationWorkflowStatus(await postJson<unknown>(
    `/device/calibration/sessions/${encodeURIComponent(sessionId)}/read`,
    { joint_id: jointId },
  ));
}

type CalibrationJointPreviewRequest = {
  joint_id: string;
  logical_value: number;
  direction: -1 | 1;
  phase: number | null;
  raw_bounds: [number, number];
};

export async function previewCalibrationJoint(
  sessionId: string,
  request: CalibrationJointPreviewRequest,
): Promise<CalibrationJointPreview> {
  return calibrationJointPreview(await postJson<unknown>(
    `/device/calibration/sessions/${encodeURIComponent(sessionId)}/preview`,
    request,
  ));
}

export async function confirmCalibrationJoint(
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
  ));
}

export async function completeCalibrationSession(
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
  ));
}

export async function cancelCalibrationSession(
  sessionId: string,
): Promise<CalibrationWorkflowStatus> {
  return normalizeCalibrationWorkflowStatus(await requestJson<unknown>(
    `/device/calibration/sessions/${encodeURIComponent(sessionId)}`,
    { method: 'DELETE' },
  ));
}
