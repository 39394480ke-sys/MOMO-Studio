import { createContext, useContext } from 'react';

import type {
  CalibrationStatus,
  DiagnosticsResponse,
  HardwareAccessPolicy,
  MetaResponse,
  ProfileResponse,
  RobotStatus,
} from '../api/types';

export interface RuntimeStatus {
  backend: 'connected' | 'unavailable';
  stale: boolean;
  controlMode: 'DRY RUN' | 'REAL';
  hardwareAccessPolicy: HardwareAccessPolicy;
  realMotionEnabled: boolean;
  meta: MetaResponse | null;
  robot: RobotStatus | null;
  profile: ProfileResponse | null;
  calibration: CalibrationStatus | null;
  diagnostics: DiagnosticsResponse | null;
  error: string | null;
  refresh: () => Promise<void>;
  connect: () => Promise<void>;
  disconnect: () => Promise<void>;
  stop: () => Promise<void>;
  switchVariant: (variant: 'V1' | 'V2') => Promise<void>;
  pendingAction: 'connect' | 'disconnect' | 'stop' | 'switch' | null;
}

export const SAFE_RUNTIME_STATUS: RuntimeStatus = {
  backend: 'unavailable',
  stale: false,
  controlMode: 'DRY RUN',
  hardwareAccessPolicy: 'DISABLED',
  realMotionEnabled: false,
  meta: null,
  robot: null,
  profile: null,
  calibration: null,
  diagnostics: null,
  error: null,
  refresh: async () => undefined,
  connect: async () => undefined,
  disconnect: async () => undefined,
  stop: async () => undefined,
  switchVariant: async () => undefined,
  pendingAction: null,
};

export const RuntimeStatusContext = createContext<RuntimeStatus>(SAFE_RUNTIME_STATUS);

export function useRuntimeStatus(): RuntimeStatus {
  return useContext(RuntimeStatusContext);
}
