import { API_BASE_URL } from './config';
import type {
  CalibrationStatus,
  BootstrapResponse,
  DiagnosticsResponse,
  HealthResponse,
  MetaResponse,
  ProfileResponse,
  RobotStatus,
  RobotVariant,
} from './types';

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Accept: 'application/json' },
    ...init,
  });

  if (!response.ok) {
    let detail = `MOMO Studio API request failed with ${response.status}.`;
    try {
      const error = (await response.json()) as { message?: string };
      if (error.message) detail = error.message;
    } catch {
      // Keep a stable, human-readable fallback for non-JSON proxy errors.
    }
    throw new Error(detail);
  }

  return (await response.json()) as T;
}

export function getHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>('/health');
}

export function getMeta(): Promise<MetaResponse> {
  return requestJson<MetaResponse>('/meta');
}

export function getRobotStatus(): Promise<RobotStatus> {
  return requestJson<RobotStatus>('/robot');
}

export function getRobotProfile(): Promise<ProfileResponse> {
  return requestJson<ProfileResponse>('/robot/profile');
}

export function getRobotDiagnostics(): Promise<DiagnosticsResponse> {
  return requestJson<DiagnosticsResponse>('/robot/diagnostics');
}

export function getCalibrationStatus(): Promise<CalibrationStatus> {
  return requestJson<CalibrationStatus>('/calibration/status');
}

async function postCommand<T>(path: string, init?: RequestInit): Promise<T> {
  return requestJson<T>(path, {
    method: 'POST',
    ...init,
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });
}

export function connectRobot(): Promise<{ status: RobotStatus; hardware_accessed: false }> {
  return postCommand('/robot/connect');
}

export function disconnectRobot(): Promise<{ status: RobotStatus; hardware_accessed: false }> {
  return postCommand('/robot/disconnect');
}

export function stopRobot(): Promise<{
  result: 'STOPPED' | 'NOT_CONNECTED' | 'FAILED' | 'SAFETY_STATE_UNCERTAIN';
  status: RobotStatus;
  hardware_accessed: false;
}> {
  return postCommand('/robot/stop');
}

export function switchRobotVariant(
  variant: RobotVariant,
): Promise<{ status: RobotStatus; hardware_accessed: false }> {
  return requestJson('/robot/variant', {
    method: 'PUT',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify({ variant }),
  });
}

export async function getBootstrapData(): Promise<BootstrapResponse> {
  const [health, meta, robot, profile, calibration, diagnostics] = await Promise.all([
    getHealth(),
    getMeta(),
    getRobotStatus(),
    getRobotProfile(),
    getCalibrationStatus(),
    getRobotDiagnostics(),
  ]);
  return { health, meta, robot, profile, calibration, diagnostics };
}
