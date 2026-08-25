import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import {
  createOperatorSession,
  getDeviceReadiness,
  revokeOperatorSession,
} from '../api/client';
import type {
  DeviceCapabilityDetails,
  DeviceReadiness,
  OperatorSessionPurpose,
  OperatorSessionResponse,
} from '../api/types';
import {
  RealSessionContext,
  closedCapabilityDetails,
  REAL_CAPABILITY_KEYS,
  SAFE_REAL_SESSION_SUMMARY,
  type RealSessionContextValue,
  type RealSessionPendingAction,
  type RealSessionSummary,
} from './realSessionContext';
import { useRuntimeStatus } from './runtimeStatusContext';

const READINESS_POLL_INTERVAL_MS = 5_000;
const READINESS_TIMEOUT_MS = 2_500;
const MAX_BROWSER_TIMER_MS = 2_147_000_000;

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function addReason(reasons: string[], reason: string): string[] {
  return reasons.includes(reason) ? [...reasons] : [...reasons, reason];
}

function closeDetails(
  details: DeviceCapabilityDetails | undefined,
  reason: string,
): DeviceCapabilityDetails {
  if (!details) return closedCapabilityDetails(reason);
  return Object.fromEntries(REAL_CAPABILITY_KEYS.map((key) => [key, {
    ...details[key],
    ready: false,
    authorized: false,
    blocked_reasons: addReason(details[key].blocked_reasons, reason),
  }])) as DeviceCapabilityDetails;
}

function failClosedReadiness(
  readiness: DeviceReadiness | null,
  reason: string,
): DeviceReadiness | null {
  if (!readiness) return null;
  return {
    ...readiness,
    state: 'REAL_SESSION_STALE',
    ready: false,
    session_authorizable: false,
    commissioning_session_authorizable: false,
    commissioning_motion_session_authorizable: false,
    motion_session_authorizable: false,
    blocking_reasons: addReason(readiness.blocking_reasons, reason),
    capabilities: {
      commissioning_diagnostics_ready: false,
      calibration_capture_ready: false,
      commissioning_motion_test_ready: false,
      real_joint_motion_ready: false,
      real_cartesian_motion_ready: false,
      real_playback_ready: false,
      real_vision_follow_ready: false,
    },
    capability_details: closeDetails(readiness.capability_details, reason),
    authorization_options: (readiness.authorization_options ?? []).map((option) => ({
      ...option,
      authorizable: false,
    })),
    session: null,
  };
}

function failClosedSummary(
  current: RealSessionSummary,
  reason: string,
  error: string,
): RealSessionSummary {
  const readiness = failClosedReadiness(current.readiness, reason);
  return {
    ...current,
    readiness,
    session: null,
    capabilityDetails: closeDetails(
      readiness?.capability_details ?? current.capabilityDetails,
      reason,
    ),
    authorizationOptions: (readiness?.authorization_options ?? current.authorizationOptions)
      .map((option) => ({ ...option, authorizable: false })),
    loading: false,
    stale: true,
    error,
  };
}

function backendCapabilityDetails(readiness: DeviceReadiness): DeviceCapabilityDetails {
  const details = readiness.capability_details;
  if (!details) {
    throw new TypeError('Backend omitted the Real capability matrix');
  }
  return details;
}

function summaryFromReadiness(readiness: DeviceReadiness): RealSessionSummary {
  if (!readiness.authorization_options) {
    throw new TypeError('Backend omitted Operator Session authorization options');
  }
  const session = readiness.session?.active ? readiness.session : null;
  const capabilityDetails = backendCapabilityDetails(readiness);
  const base: RealSessionSummary = {
    readiness: {
      ...readiness,
      capability_details: capabilityDetails,
      session,
    },
    session,
    capabilityDetails,
    authorizationOptions: readiness.authorization_options,
    loading: false,
    stale: false,
    error: null,
    updatedAt: new Date().toISOString(),
  };
  if (!session) return base;

  const expiry = Date.parse(session.expires_at);
  if (!Number.isFinite(expiry)) {
    return failClosedSummary(
      base,
      'OPERATOR_SESSION_EXPIRY_INVALID',
      'Backend returned an invalid Operator Session expiry.',
    );
  }
  if (expiry <= Date.now()) {
    return failClosedSummary(
      base,
      'OPERATOR_SESSION_EXPIRED',
      'Operator Session expired. Authorize again before Real hardware access.',
    );
  }
  return base;
}

export function RealSessionProvider({ children }: { children: ReactNode }) {
  const runtime = useRuntimeStatus();
  const [summary, setSummary] = useState<RealSessionSummary>(SAFE_REAL_SESSION_SUMMARY);
  const [pendingAction, setPendingAction] = useState<RealSessionPendingAction>(null);
  const mounted = useRef(true);
  const generation = useRef(0);
  const requestInFlight = useRef<{
    controller: AbortController;
    generation: number;
    promise: Promise<void>;
  } | null>(null);

  const realRuntimeAvailable = runtime.controlMode === 'REAL' &&
    runtime.backend === 'connected' && !runtime.stale;

  const invalidateRequest = useCallback(() => {
    generation.current += 1;
    requestInFlight.current?.controller.abort();
    requestInFlight.current = null;
  }, []);

  const refresh = useCallback((): Promise<void> => {
    if (!mounted.current || !realRuntimeAvailable) return Promise.resolve();
    if (requestInFlight.current) return requestInFlight.current.promise;

    const controller = new AbortController();
    const requestGeneration = generation.current;
    const promise = (async () => {
      let timeoutId: number | null = null;
      try {
        setSummary((current) => ({
          ...current,
          loading: current.readiness === null,
          error: null,
        }));
        const timeout = new Promise<never>((_, reject) => {
          timeoutId = window.setTimeout(() => {
            controller.abort();
            reject(new Error(`Real readiness timed out after ${READINESS_TIMEOUT_MS} ms`));
          }, READINESS_TIMEOUT_MS);
        });
        const readiness = await Promise.race([
          getDeviceReadiness(controller.signal),
          timeout,
        ]);
        if (!mounted.current || controller.signal.aborted ||
          requestGeneration !== generation.current) {
          return;
        }
        setSummary(summaryFromReadiness(readiness));
      } catch (error) {
        if (!mounted.current || requestGeneration !== generation.current) return;
        setSummary((current) => failClosedSummary(
          current,
          'REAL_READINESS_UNAVAILABLE',
          errorMessage(error, 'Real readiness is unavailable.'),
        ));
      } finally {
        if (timeoutId !== null) window.clearTimeout(timeoutId);
        if (requestInFlight.current?.generation === requestGeneration) {
          requestInFlight.current = null;
        }
      }
    })();
    requestInFlight.current = { controller, generation: requestGeneration, promise };
    return promise;
  }, [realRuntimeAvailable]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      invalidateRequest();
    };
  }, [invalidateRequest]);

  useEffect(() => {
    invalidateRequest();
    if (runtime.controlMode !== 'REAL') {
      setSummary(SAFE_REAL_SESSION_SUMMARY);
      return undefined;
    }
    if (!realRuntimeAvailable) {
      const reason = runtime.stale ? 'RUNTIME_STATUS_STALE' : 'BACKEND_UNAVAILABLE';
      const message = runtime.stale
        ? 'Runtime status is stale; every Real capability is closed.'
        : 'Backend is unavailable; every Real capability is closed.';
      setSummary((current) => failClosedSummary(current, reason, message));
      return undefined;
    }

    setSummary((current) => ({
      ...current,
      loading: current.readiness === null,
      stale: current.readiness === null,
      error: null,
    }));
    void refresh();
    const pollTimer = window.setInterval(() => void refresh(), READINESS_POLL_INTERVAL_MS);
    return () => {
      window.clearInterval(pollTimer);
      invalidateRequest();
    };
  }, [invalidateRequest, realRuntimeAvailable, refresh, runtime.controlMode, runtime.stale]);

  useEffect(() => {
    const session = summary.session;
    if (!session) return undefined;

    let expiryTimer: number | undefined;
    const expire = () => {
      setSummary((current) => {
        if (current.session?.session_id !== session.session_id) return current;
        return failClosedSummary(
          current,
          'OPERATOR_SESSION_EXPIRED',
          'Operator Session expired. Authorize again before Real hardware access.',
        );
      });
      void refresh();
    };
    const schedule = () => {
      const remaining = Date.parse(session.expires_at) - Date.now();
      if (!Number.isFinite(remaining) || remaining <= 0) {
        expire();
        return;
      }
      expiryTimer = window.setTimeout(schedule, Math.min(remaining, MAX_BROWSER_TIMER_MS));
    };
    schedule();
    return () => {
      if (expiryTimer !== undefined) window.clearTimeout(expiryTimer);
    };
  }, [refresh, summary.session]);

  const authorize = useCallback(async (
    purpose: OperatorSessionPurpose,
    confirmationText: string,
    physicalEstopConfirmed: boolean,
    workspaceClearConfirmed = false,
  ): Promise<OperatorSessionResponse> => {
    setPendingAction('authorize');
    invalidateRequest();
    try {
      const issued = await createOperatorSession(
        purpose,
        confirmationText,
        physicalEstopConfirmed,
        workspaceClearConfirmed,
      );
      if (mounted.current) await refresh();
      return issued;
    } catch (error) {
      if (mounted.current) {
        setSummary((current) => failClosedSummary(
          current,
          'OPERATOR_SESSION_AUTHORIZATION_FAILED',
          errorMessage(error, 'Operator Session authorization failed.'),
        ));
      }
      throw error;
    } finally {
      if (mounted.current) setPendingAction(null);
    }
  }, [invalidateRequest, refresh]);

  const revoke = useCallback(async (): Promise<void> => {
    setPendingAction('revoke');
    invalidateRequest();
    try {
      await revokeOperatorSession();
      if (mounted.current) await refresh();
    } catch (error) {
      if (mounted.current) {
        setSummary((current) => failClosedSummary(
          current,
          'OPERATOR_SESSION_REVOCATION_FAILED',
          errorMessage(error, 'Operator Session revocation failed.'),
        ));
      }
      throw error;
    } finally {
      if (mounted.current) setPendingAction(null);
    }
  }, [invalidateRequest, refresh]);

  const value = useMemo<RealSessionContextValue>(() => ({
    summary,
    pendingAction,
    authorize,
    revoke,
    refresh,
  }), [authorize, pendingAction, refresh, revoke, summary]);

  return <RealSessionContext.Provider value={value}>{children}</RealSessionContext.Provider>;
}
