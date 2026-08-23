import { useEffect, useMemo, useState } from 'react';

import { getForwardKinematics } from '../../api/client';
import type { ForwardKinematicsResponse, TcpPose } from '../../api/types';
import { errorMessage } from './controlMath';

export function useForwardKinematics(options: {
  enabled: boolean;
  stateSequence: number | null;
  socketTcpPose: TcpPose | null;
  socketStateSequence: number | null;
}) {
  const [fetched, setFetched] = useState<ForwardKinematicsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!options.enabled) {
      setLoading(false);
      setFetched(null);
      setError(null);
      return;
    }
    const controller = new AbortController();
    setFetched(null);
    setLoading(true);
    void getForwardKinematics(controller.signal)
      .then((result) => {
        setFetched(result);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === 'AbortError') return;
        setError(errorMessage(reason));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [options.enabled, options.stateSequence]);

  const fk = useMemo(() => {
    if (!fetched || !options.socketTcpPose) return fetched;
    return {
      ...fetched,
      tcp_pose: options.socketTcpPose,
      state_sequence: options.socketStateSequence ?? fetched.state_sequence,
    };
  }, [fetched, options.socketStateSequence, options.socketTcpPose]);

  return {
    fk,
    loading,
    error,
  };
}
