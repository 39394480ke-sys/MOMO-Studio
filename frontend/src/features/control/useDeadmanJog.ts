import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';

import { heartbeatJogSession, startJogSession, stopJogSession } from '../../api/client';
import type {
  JogSessionResponse,
  JogSessionStartRequest,
} from '../../api/types';

interface JogIntent {
  jointId: string;
  direction: -1 | 1;
}

interface ActiveJog extends JogIntent {
  sessionId: string;
}

export function useDeadmanJog(options: {
  enabled: boolean;
  canStart: boolean;
  buildRequest: (intent: JogIntent) => JogSessionStartRequest | null;
  onSubmission: (submission: JogSessionResponse) => void;
  onError: (error: unknown) => void;
}) {
  const { enabled, canStart, buildRequest, onSubmission, onError } = options;
  const [active, setActive] = useState<ActiveJog | null>(null);
  const [starting, setStarting] = useState<JogIntent | null>(null);
  const sessionRef = useRef<string | null>(null);
  const heartbeatTimerRef = useRef<number | null>(null);
  const heartbeatInFlightRef = useRef(false);
  const pressedRef = useRef(false);
  const generationRef = useRef(0);

  const clearHeartbeat = useCallback(() => {
    if (heartbeatTimerRef.current !== null) {
      window.clearInterval(heartbeatTimerRef.current);
      heartbeatTimerRef.current = null;
    }
    heartbeatInFlightRef.current = false;
  }, []);

  const stopActive = useCallback(
    (keepalive = false) => {
      pressedRef.current = false;
      generationRef.current += 1;
      clearHeartbeat();
      const sessionId = sessionRef.current;
      sessionRef.current = null;
      setStarting(null);
      setActive(null);
      if (sessionId) {
        void stopJogSession(sessionId, { keepalive }).catch((reason: unknown) => {
          if (!keepalive) onError(reason);
        });
      }
    },
    [clearHeartbeat, onError],
  );

  const begin = useCallback(
    async (intent: JogIntent) => {
      if (!enabled || !canStart || pressedRef.current) return;
      const request = buildRequest(intent);
      if (!request) return;

      pressedRef.current = true;
      const generation = generationRef.current + 1;
      generationRef.current = generation;
      setStarting(intent);
      try {
        const response = await startJogSession(request);
        if (
          generationRef.current !== generation ||
          !pressedRef.current ||
          !enabled
        ) {
          void stopJogSession(response.jog_session_id).catch(() => undefined);
          return;
        }
        sessionRef.current = response.jog_session_id;
        setStarting(null);
        setActive({ ...intent, sessionId: response.jog_session_id });
        onSubmission(response);
        heartbeatTimerRef.current = window.setInterval(() => {
          const sessionId = sessionRef.current;
          if (!sessionId || heartbeatInFlightRef.current) return;
          heartbeatInFlightRef.current = true;
          void heartbeatJogSession(sessionId)
            .catch((reason: unknown) => {
              onError(reason);
              stopActive();
            })
            .finally(() => {
              heartbeatInFlightRef.current = false;
            });
        }, 150);
      } catch (reason) {
        if (generationRef.current === generation) {
          pressedRef.current = false;
          setStarting(null);
          onError(reason);
        }
      }
    },
    [buildRequest, canStart, enabled, onError, onSubmission, stopActive],
  );

  useEffect(() => {
    if (!enabled) stopActive();
  }, [enabled, stopActive]);

  useEffect(() => {
    const stop = () => stopActive();
    const stopForUnload = () => stopActive(true);
    const stopWhenHidden = () => {
      if (document.visibilityState === 'hidden') stopActive();
    };
    window.addEventListener('blur', stop);
    window.addEventListener('pagehide', stopForUnload);
    window.addEventListener('beforeunload', stopForUnload);
    document.addEventListener('visibilitychange', stopWhenHidden);
    return () => {
      window.removeEventListener('blur', stop);
      window.removeEventListener('pagehide', stopForUnload);
      window.removeEventListener('beforeunload', stopForUnload);
      document.removeEventListener('visibilitychange', stopWhenHidden);
      stopActive(true);
    };
  }, [stopActive]);

  const handlersFor = useCallback(
    (jointId: string, direction: -1 | 1) => ({
      onPointerDown: (event: PointerEvent<HTMLButtonElement>) => {
        event.preventDefault();
        if (typeof event.currentTarget.setPointerCapture === 'function') {
          event.currentTarget.setPointerCapture(event.pointerId);
        }
        void begin({ jointId, direction });
      },
      onPointerUp: (event: PointerEvent<HTMLButtonElement>) => {
        if (
          typeof event.currentTarget.hasPointerCapture === 'function' &&
          event.currentTarget.hasPointerCapture(event.pointerId) &&
          typeof event.currentTarget.releasePointerCapture === 'function'
        ) {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
        stopActive();
      },
      onPointerCancel: () => stopActive(),
      onLostPointerCapture: () => stopActive(),
      onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => {
        if (!event.repeat && (event.key === ' ' || event.key === 'Enter')) {
          event.preventDefault();
          void begin({ jointId, direction });
        }
      },
      onKeyUp: (event: KeyboardEvent<HTMLButtonElement>) => {
        if (event.key === ' ' || event.key === 'Enter') stopActive();
      },
      onBlur: () => stopActive(),
    }),
    [begin, stopActive],
  );

  return {
    active,
    starting,
    handlersFor,
    stopActive,
  };
}
