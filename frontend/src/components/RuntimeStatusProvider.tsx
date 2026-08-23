import { useEffect, useState, type ReactNode } from 'react';

import { getBootstrapData } from '../api/client';
import {
  RuntimeStatusContext,
  SAFE_RUNTIME_STATUS,
  type RuntimeStatus,
} from './runtimeStatusContext';

function isSafeHealthResponse(
  status: string,
  controlMode: string,
  realMotionEnabled: boolean,
): boolean {
  const normalizedStatus = status.trim().toLowerCase();
  const normalizedMode = controlMode.trim().toUpperCase().replaceAll('_', ' ');
  return (
    ['ok', 'healthy', 'online'].includes(normalizedStatus) &&
    normalizedMode === 'DRY RUN' &&
    realMotionEnabled === false
  );
}

export function RuntimeStatusProvider({ children }: { children: ReactNode }) {
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus>(
    SAFE_RUNTIME_STATUS,
  );

  useEffect(() => {
    let isCurrent = true;

    void getBootstrapData()
      .then(({ health, meta }) => {
        if (!isCurrent) {
          return;
        }

        setRuntimeStatus({
          ...SAFE_RUNTIME_STATUS,
          backend: isSafeHealthResponse(
            health.status,
            health.control_mode,
            health.real_motion_enabled,
          )
            ? 'connected'
            : 'unavailable',
          meta,
        });
      })
      .catch(() => {
        if (isCurrent) {
          setRuntimeStatus({
            ...SAFE_RUNTIME_STATUS,
            backend: 'unavailable',
          });
        }
      });

    return () => {
      isCurrent = false;
    };
  }, []);

  return (
    <RuntimeStatusContext.Provider value={runtimeStatus}>
      {children}
    </RuntimeStatusContext.Provider>
  );
}
