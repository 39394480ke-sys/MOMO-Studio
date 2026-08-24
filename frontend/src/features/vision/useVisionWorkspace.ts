import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  clearVisionTarget,
  detectVisionTarget,
  getVisionCapabilities,
  getVisionStatus,
  heartbeatVisionFollow,
  resetVisionTracking,
  selectVisionTarget,
  startVisionFollow,
  stopVisionFollow,
} from '../../api/client';
import type {
  NormalizedBoundingBox,
  VisionCapabilities,
  VisionDetection,
  VisionFollowConfiguration,
  VisionFollowMapping,
  VisionStatus,
} from '../../api/types';
import type { RuntimeStatus } from '../../components/runtimeStatusContext';

const STATUS_POLL_MS = 250;

export const DEFAULT_FOLLOW_CONFIGURATION: VisionFollowConfiguration = {
  dead_zone_x: 0.08,
  dead_zone_y: 0.08,
  ema_alpha: 0.35,
  gain: 0.5,
  max_step: 2,
  max_rate: 4,
  confidence_threshold: 0.55,
  frame_freshness_limit_s: 0.75,
  target_lost_limit_s: 0.5,
  lease_ttl_s: 2,
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Vision operation failed.';
}

function followMapping(runtime: RuntimeStatus): VisionFollowMapping | null {
  const definitions = runtime.profile?.profile.joint_definitions ?? [];
  const enabled = new Set(runtime.profile?.profile.enabled_joints ?? []);
  const angular = definitions.filter(
    (definition) => enabled.has(definition.joint_id) && definition.domain_unit === 'deg',
  );
  if (angular.length < 2) return null;
  return {
    pan_joint: angular[0].joint_id,
    tilt_joint: angular[1].joint_id,
    pan_sign: 1,
    tilt_sign: -1,
    verification_status: 'VERIFIED_FOR_DRY_RUN',
  };
}

export function useVisionWorkspace(runtime: RuntimeStatus) {
  const [capabilities, setCapabilities] = useState<VisionCapabilities | null>(null);
  const [status, setStatus] = useState<VisionStatus | null>(null);
  const [detections, setDetections] = useState<VisionDetection[]>([]);
  const [configuration, setConfiguration] = useState(DEFAULT_FOLLOW_CONFIGURATION);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [streamFailed, setStreamFailed] = useState(false);
  const [statusReachable, setStatusReachable] = useState(false);
  const mountedRef = useRef(true);
  const requestGenerationRef = useRef(0);
  const priorityEpochRef = useRef(0);
  const pendingLeaseRef = useRef<string | null>(null);
  const statusRef = useRef(status);
  statusRef.current = status;

  const mapping = useMemo(() => followMapping(runtime), [runtime]);
  const online = runtime.backend === 'connected' && !runtime.stale;

  const refreshStatus = useCallback(async (signal?: AbortSignal) => {
    const generation = requestGenerationRef.current;
    const next = await getVisionStatus(signal);
    if (!mountedRef.current || generation !== requestGenerationRef.current) return;
    setStatus(next);
    setStatusReachable(true);
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      priorityEpochRef.current += 1;
      requestGenerationRef.current += 1;
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | null = null;
    let cancelled = false;

    const schedulePoll = () => {
      if (cancelled || controller.signal.aborted) return;
      timer = window.setTimeout(() => {
        void refreshStatus(controller.signal).catch((caught) => {
          if (!mountedRef.current || controller.signal.aborted) return;
          setStatusReachable(false);
          setError(errorMessage(caught));
        }).finally(schedulePoll);
      }, STATUS_POLL_MS);
    };

    if (!online) {
      priorityEpochRef.current += 1;
      setCapabilities(null);
      setStatus(null);
      setDetections([]);
      setStreamFailed(false);
      setStatusReachable(false);
      return () => {
        cancelled = true;
        requestGenerationRef.current += 1;
        controller.abort();
      };
    }
    void Promise.all([
      getVisionCapabilities(controller.signal),
      getVisionStatus(controller.signal),
    ]).then(([nextCapabilities, nextStatus]) => {
      if (!mountedRef.current || controller.signal.aborted) return;
      setCapabilities(nextCapabilities);
      setStatus(nextStatus);
      setStatusReachable(true);
      setError(null);
    }).catch((caught) => {
      if (!mountedRef.current || controller.signal.aborted) return;
      setStatusReachable(false);
      setError(errorMessage(caught));
    }).finally(schedulePoll);
    return () => {
      cancelled = true;
      requestGenerationRef.current += 1;
      controller.abort();
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [online, refreshStatus]);

  useEffect(() => {
    const leaseId = status?.follow.active ? status.follow.lease_id : null;
    if (!online || !leaseId) return;
    const heartbeatMs = Math.max(250, Math.floor(configuration.lease_ttl_s * 400));
    let timer: number | null = null;
    let cancelled = false;
    const scheduleHeartbeat = () => {
      if (cancelled) return;
      timer = window.setTimeout(() => {
        void sendHeartbeat();
      }, heartbeatMs);
    };
    const sendHeartbeat = async () => {
      const epoch = priorityEpochRef.current;
      try {
        const response = await heartbeatVisionFollow(leaseId);
        if (!mountedRef.current || epoch !== priorityEpochRef.current) return;
        pendingLeaseRef.current = response.lease_id;
        setStatus(response.status);
      } catch (caught) {
        if (!mountedRef.current || epoch !== priorityEpochRef.current) return;
        setError(`Follow heartbeat failed: ${errorMessage(caught)}`);
        void refreshStatus().catch(() => undefined);
      } finally {
        scheduleHeartbeat();
      }
    };
    scheduleHeartbeat();
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [configuration.lease_ttl_s, online, refreshStatus, status?.follow.active, status?.follow.lease_id]);

  const selectTarget = useCallback(async (
    frameId: string,
    box: NormalizedBoundingBox,
  ) => {
    if (!frameId) {
      setError('Wait for a current Synthetic frame before selecting a target.');
      return;
    }
    setBusy('selection');
    setError(null);
    try {
      const next = await selectVisionTarget(frameId, box);
      if (mountedRef.current) {
        setStatus(next);
        setDetections([]);
      }
    } catch (caught) {
      if (mountedRef.current) setError(errorMessage(caught));
    } finally {
      if (mountedRef.current) setBusy((current) => current === 'selection' ? null : current);
    }
  }, []);

  const clearTarget = useCallback(async () => {
    priorityEpochRef.current += 1;
    setBusy('clear');
    setError(null);
    try {
      const next = await clearVisionTarget();
      if (mountedRef.current) {
        setStatus(next);
        setDetections([]);
      }
    } catch (caught) {
      if (mountedRef.current) setError(errorMessage(caught));
    } finally {
      if (mountedRef.current) setBusy((current) => current === 'clear' ? null : current);
    }
  }, []);

  const detect = useCallback(async (detector: 'person' | 'face') => {
    const frameId = statusRef.current?.latest_frame?.frame_id;
    if (!frameId) {
      setError('Wait for a current Synthetic frame before running detection.');
      return;
    }
    setBusy(`detect-${detector}`);
    setError(null);
    try {
      const result = await detectVisionTarget(detector, frameId);
      if (!mountedRef.current) return;
      setDetections(result.detections);
      if (!result.capability.available) {
        setError(result.capability.reason ?? `${detector} detector is unavailable.`);
        return;
      }
      const first = result.detections[0];
      if (!first) {
        setError(`No ${detector} target was detected in the current frame.`);
        return;
      }
      const next = await selectVisionTarget(first.frame_id, first.bounding_box);
      if (mountedRef.current) setStatus(next);
    } catch (caught) {
      if (mountedRef.current) setError(errorMessage(caught));
    } finally {
      if (mountedRef.current) setBusy((current) => current === `detect-${detector}` ? null : current);
    }
  }, []);

  const resetTracking = useCallback(async () => {
    setBusy('reset');
    setError(null);
    try {
      const next = await resetVisionTracking();
      if (mountedRef.current) setStatus(next);
    } catch (caught) {
      if (mountedRef.current) setError(errorMessage(caught));
    } finally {
      if (mountedRef.current) setBusy((current) => current === 'reset' ? null : current);
    }
  }, []);

  const startFollow = useCallback(async () => {
    if (!mapping) {
      setError('The active Profile does not provide two enabled angular joints for Follow mapping.');
      return;
    }
    const epoch = priorityEpochRef.current;
    setBusy('start-follow');
    setError(null);
    try {
      const response = await startVisionFollow({ configuration, mapping });
      if (!mountedRef.current || epoch !== priorityEpochRef.current) {
        try {
          await stopVisionFollow(response.lease_id);
        } catch (caught) {
          if (mountedRef.current) {
            setError(`Compensating Follow Stop failed: ${errorMessage(caught)}`);
          }
        }
        return;
      }
      pendingLeaseRef.current = response.lease_id;
      setStatus(response.status);
    } catch (caught) {
      if (mountedRef.current && epoch === priorityEpochRef.current) setError(errorMessage(caught));
    } finally {
      if (mountedRef.current) setBusy((current) => current === 'start-follow' ? null : current);
    }
  }, [configuration, mapping]);

  const stopFollow = useCallback(async () => {
    priorityEpochRef.current += 1;
    const leaseId = statusRef.current?.follow.lease_id ?? pendingLeaseRef.current;
    setBusy('stop-follow');
    setError(null);
    try {
      if (leaseId) {
        const next = await stopVisionFollow(leaseId);
        pendingLeaseRef.current = null;
        if (mountedRef.current) setStatus(next);
      } else {
        await refreshStatus();
      }
    } catch (caught) {
      if (mountedRef.current) setError(`Follow Stop failed: ${errorMessage(caught)}`);
    } finally {
      if (mountedRef.current) setBusy((current) => current === 'stop-follow' ? null : current);
    }
  }, [refreshStatus]);

  return {
    busy,
    capabilities,
    clearError: () => setError(null),
    clearTarget,
    configuration,
    detect,
    detections,
    error,
    mapping,
    online,
    resetTracking,
    selectTarget,
    setConfiguration,
    startFollow,
    status,
    statusReachable,
    stopFollow,
    streamFailed,
    setStreamFailed,
  };
}

export type VisionWorkspace = ReturnType<typeof useVisionWorkspace>;
