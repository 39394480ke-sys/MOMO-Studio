import { API_BASE_URL } from './config';
import type {
  BootstrapResponse,
  CalibrationStatus,
  CartesianJogRequest,
  DiagnosticsResponse,
  ErrorResponse,
  ForwardKinematicsResponse,
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
  MotionPreflightReport,
  MotionStopResponse,
  MoveJointsRequest,
  MovePoseRequest,
  ProfileResponse,
  RobotStatus,
  RobotVariant,
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
