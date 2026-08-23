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

const BOOTSTRAP_TIMEOUT_MS = 900;

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
  const actionInFlight = useRef(false);
  const bootstrapGeneration = useRef(0);
  const bootstrapInFlight = useRef<{
    controller: AbortController;
    generation: number;
    promise: Promise<void>;
    timeoutId: number | null;
  } | null>(null);

  const applyBootstrap = useCallback((data: BootstrapResponse) => {
    if (!isSafeBootstrap(data)) {
      throw new Error('Backend returned an unsafe runtime policy');
    }
    setRuntimeStatus((current) => ({
      ...current,
      backend: 'connected',
      stale: data.robot.stale !== false,
      error: null,
      meta: data.meta,
      robot: data.robot,
      profile: data.profile,
      calibration: data.calibration,
      diagnostics: data.diagnostics,
    }));
  }, []);

  const invalidateBootstrap = useCallback(() => {
    bootstrapGeneration.current += 1;
    const activeRequest = bootstrapInFlight.current;
    bootstrapInFlight.current = null;
    if (activeRequest?.timeoutId !== null && activeRequest?.timeoutId !== undefined) {
      window.clearTimeout(activeRequest.timeoutId);
    }
    activeRequest?.controller.abort();
  }, []);

  const refresh = useCallback((): Promise<void> => {
    if (!mounted.current || actionInFlight.current) return Promise.resolve();

    const currentRequest = bootstrapInFlight.current;
    if (currentRequest) return currentRequest.promise;

    const controller = new AbortController();
    const generation = bootstrapGeneration.current;
    let timeoutId: number | null = null;
    const promise = (async () => {
      try {
        const data = await getBootstrapData(controller.signal);
        if (
          mounted.current &&
          !controller.signal.aborted &&
          generation === bootstrapGeneration.current
        ) {
          applyBootstrap(data);
        }
      } catch (error) {
        if (
          !mounted.current ||
          controller.signal.aborted ||
          generation !== bootstrapGeneration.current
        ) {
          return;
        }
        setRuntimeStatus((current) => ({
          ...current,
          backend: 'unavailable',
          stale: current.robot !== null,
          error: error instanceof Error ? error.message : 'Backend unavailable',
        }));
      } finally {
        if (timeoutId !== null) window.clearTimeout(timeoutId);
        const activeRequest = bootstrapInFlight.current;
        if (
          activeRequest?.controller === controller &&
          activeRequest.generation === generation
        ) {
          bootstrapInFlight.current = null;
        }
      }
    })();

    const request = { controller, generation, promise, timeoutId: null as number | null };
    bootstrapInFlight.current = request;
    timeoutId = window.setTimeout(() => {
      const activeRequest = bootstrapInFlight.current;
      if (
        activeRequest !== request ||
        !mounted.current ||
        actionInFlight.current ||
        generation !== bootstrapGeneration.current
      ) {
        return;
      }
      request.timeoutId = null;
      timeoutId = null;
      controller.abort();
      setRuntimeStatus((current) => ({
        ...current,
        backend: 'unavailable',
        stale: current.robot !== null,
        error: `Backend refresh timed out after ${BOOTSTRAP_TIMEOUT_MS} ms`,
      }));
    }, BOOTSTRAP_TIMEOUT_MS);
    request.timeoutId = timeoutId;
    return promise;
  }, [applyBootstrap]);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const timer = window.setInterval(() => void refresh(), 1000);
    return () => {
      mounted.current = false;
      invalidateBootstrap();
      bootstrapInFlight.current = null;
      window.clearInterval(timer);
    };
  }, [invalidateBootstrap, refresh]);

  const runAction = useCallback(
    async (
      action: NonNullable<RuntimeStatus['pendingAction']>,
      operation: () => Promise<{ status: RobotStatus }>,
    ) => {
      actionInFlight.current = true;
      invalidateBootstrap();
      setRuntimeStatus((current) => ({ ...current, pendingAction: action, error: null }));
      try {
        const response = await operation();
        if (!mounted.current) return;
        setRuntimeStatus((current) => {
          const variantChanged = current.robot?.variant !== response.status.variant;
          return {
            ...current,
            backend: 'connected',
            stale: response.status.stale !== false,
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
        actionInFlight.current = false;
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
      } finally {
        actionInFlight.current = false;
      }
    },
    [invalidateBootstrap, refresh],
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
