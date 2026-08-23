import { createContext, useContext } from 'react';

import type { MetaResponse } from '../api/types';

export interface RuntimeStatus {
  backend: 'connected' | 'unavailable';
  controlMode: 'DRY RUN';
  realMotionEnabled: false;
  meta: MetaResponse | null;
}

export const SAFE_RUNTIME_STATUS: RuntimeStatus = {
  backend: 'unavailable',
  controlMode: 'DRY RUN',
  realMotionEnabled: false,
  meta: null,
};

export const RuntimeStatusContext = createContext<RuntimeStatus>(
  SAFE_RUNTIME_STATUS,
);

export function useRuntimeStatus(): RuntimeStatus {
  return useContext(RuntimeStatusContext);
}
