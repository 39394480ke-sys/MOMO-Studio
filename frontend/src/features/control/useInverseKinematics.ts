import { useCallback, useState } from 'react';

import { solveInverseKinematics } from '../../api/client';
import type { InverseKinematicsRequest, InverseKinematicsResponse } from '../../api/types';
import { errorMessage } from './controlMath';

export function useInverseKinematics() {
  const [result, setResult] = useState<InverseKinematicsResponse | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const solve = useCallback(async (request: InverseKinematicsRequest) => {
    setPending(true);
    setError(null);
    try {
      const next = await solveInverseKinematics(request);
      setResult(next);
      return next;
    } catch (reason) {
      setError(errorMessage(reason));
      return null;
    } finally {
      setPending(false);
    }
  }, []);

  return { result, pending, error, solve };
}
