import { ApiError } from '../../api/client';
import type { QuaternionXYZW, Vector3 } from '../../api/types';

const DEGREES_PER_RADIAN = 180 / Math.PI;
const RADIANS_PER_DEGREE = Math.PI / 180;

export const ZERO_VECTOR: Readonly<Vector3> = Object.freeze({ x: 0, y: 0, z: 0 });

export function rpyDegreesToQuaternion(rotation: Vector3): QuaternionXYZW {
  const roll = rotation.x * RADIANS_PER_DEGREE * 0.5;
  const pitch = rotation.y * RADIANS_PER_DEGREE * 0.5;
  const yaw = rotation.z * RADIANS_PER_DEGREE * 0.5;
  const sr = Math.sin(roll);
  const cr = Math.cos(roll);
  const sp = Math.sin(pitch);
  const cp = Math.cos(pitch);
  const sy = Math.sin(yaw);
  const cy = Math.cos(yaw);
  const quaternion = {
    x: sr * cp * cy - cr * sp * sy,
    y: cr * sp * cy + sr * cp * sy,
    z: cr * cp * sy - sr * sp * cy,
    w: cr * cp * cy + sr * sp * sy,
  };
  const norm = Math.hypot(quaternion.x, quaternion.y, quaternion.z, quaternion.w);
  if (!Number.isFinite(norm) || norm < 1e-12) return { x: 0, y: 0, z: 0, w: 1 };
  return {
    x: quaternion.x / norm,
    y: quaternion.y / norm,
    z: quaternion.z / norm,
    w: quaternion.w / norm,
  };
}

export function quaternionToRpyDegrees(quaternion: QuaternionXYZW): Vector3 {
  const norm = Math.hypot(quaternion.x, quaternion.y, quaternion.z, quaternion.w);
  const scale = Number.isFinite(norm) && norm >= 1e-12 ? 1 / norm : 1;
  const x = quaternion.x * scale;
  const y = quaternion.y * scale;
  const z = quaternion.z * scale;
  const w = quaternion.w * scale;
  const sinPitch = Math.max(-1, Math.min(1, 2 * (w * y - z * x)));
  return {
    x: Math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y)) * DEGREES_PER_RADIAN,
    y: Math.asin(sinPitch) * DEGREES_PER_RADIAN,
    z: Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)) * DEGREES_PER_RADIAN,
  };
}

export function finiteOr(value: number, fallback: number): number {
  return Number.isFinite(value) ? value : fallback;
}

export function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return `${error.code}: ${error.message}`;
  return error instanceof Error ? error.message : 'The command failed unexpectedly.';
}

export function createIdempotencyKey(prefix: string): string {
  const suffix =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `control-${prefix}-${suffix}`;
}
