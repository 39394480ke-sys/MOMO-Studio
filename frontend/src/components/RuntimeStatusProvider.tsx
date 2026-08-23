import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';

import {
  connectRobot,
  disconnectRobot,
  getBootstrapData,
  stopRobot,
  switchRobotVariant,
} from '../api/client';
import type { BootstrapResponse, RobotStatus } from '../api/types';
import {
  RuntimeStatusContext,
  SAFE_RUNTIME_STATUS,
  type RuntimeStatus,
} from './runtimeStatusContext';

function isSafeBootstrap(data: BootstrapResponse): boolean {
  return (
    data.health.status === 'ok' &&
    data.health.control_mode === 'DRY_RUN' &&
    data.health.hardware_access_policy === 'DISABLED' &&
    data.health.real_motion_enabled === false &&
    data.meta.active_control_mode === 'DRY_RUN' &&
    data.meta.hardware_access_policy === 'DISABLED' &&
    data.meta.real_motion_enabled === false &&
    data.robot.control_mode === 'DRY_RUN' &&
    data.robot.hardware_access_policy === 'DISABLED' &&
    data.robot.hardware_accessed === false
  );
}

export function RuntimeStatusProvider({ children }: { children: ReactNode }) {
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus>(SAFE_RUNTIME_STATUS);
  const mounted = useRef(true);

  const applyBootstrap = useCallback((data: BootstrapResponse) => {
    if (!isSafeBootstrap(data)) {
      throw new Error('Backend returned an unsafe runtime policy');
    }
    setRuntimeStatus((current) => ({
      ...current,
      backend: 'connected',
      stale: false,
      error: null,
      meta: data.meta,
      robot: data.robot,
      profile: data.profile,
      calibration: data.calibration,
      diagnostics: data.diagnostics,
    }));
  }, []);

  const refresh = useCallback(async () => {
    try {
      const data = await getBootstrapData();
      if (mounted.current) applyBootstrap(data);
    } catch (error) {
      if (!mounted.current) return;
      setRuntimeStatus((current) => ({
        ...current,
        backend: 'unavailable',
        stale: current.robot !== null,
        error: error instanceof Error ? error.message : 'Backend unavailable',
      }));
    }
  }, [applyBootstrap]);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const timer = window.setInterval(() => void refresh(), 1000);
    return () => {
      mounted.current = false;
      window.clearInterval(timer);
    };
  }, [refresh]);

  const runAction = useCallback(
    async (
      action: NonNullable<RuntimeStatus['pendingAction']>,
      operation: () => Promise<{ status: RobotStatus }>,
    ) => {
      setRuntimeStatus((current) => ({ ...current, pendingAction: action, error: null }));
      try {
        const response = await operation();
        if (!mounted.current) return;
        setRuntimeStatus((current) => {
          const variantChanged = current.robot?.variant !== response.status.variant;
          return {
            ...current,
            backend: 'connected',
            stale: false,
            robot: response.status,
            meta: current.meta
              ? { ...current.meta, active_robot_variant: response.status.variant }
              : current.meta,
            profile: variantChanged ? null : current.profile,
            calibration: variantChanged ? null : current.calibration,
            diagnostics: variantChanged ? null : current.diagnostics,
            pendingAction: null,
            error: null,
          };
        });
        if (action === 'switch') {
          void refresh();
        }
      } catch (error) {
        if (!mounted.current) return;
        setRuntimeStatus((current) => ({
          ...current,
          pendingAction: null,
          error: error instanceof Error ? error.message : 'Backend command failed',
        }));
      }
    },
    [refresh],
  );

  const value: RuntimeStatus = {
    ...runtimeStatus,
    refresh,
    connect: () => runAction('connect', connectRobot),
    disconnect: () => runAction('disconnect', disconnectRobot),
    stop: () => runAction('stop', stopRobot),
    switchVariant: (variant) => runAction('switch', () => switchRobotVariant(variant)),
  };

  return <RuntimeStatusContext.Provider value={value}>{children}</RuntimeStatusContext.Provider>;
}
