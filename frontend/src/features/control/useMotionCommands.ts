import { useCallback, useEffect, useRef, useState } from 'react';

import {
  ApiError,
  getMotionCommand,
  jogJointStep,
  moveCartesian,
  moveHome,
  moveJoints,
  movePose,
  stopMotion,
} from '../../api/client';
import type {
  CartesianJogRequest,
  HomeRequest,
  JointJogStepRequest,
  MotionCommandStatus,
  MotionCommandSubmission,
  MotionPreflightReport,
  MoveJointsRequest,
  MovePoseRequest,
} from '../../api/types';
import { errorMessage } from './controlMath';

const TERMINAL_STATES = new Set(['STOPPED', 'CANCELLED', 'COMPLETED', 'FAULTED', 'REJECTED']);
const MAX_COMMAND_POLL_DURATION_MS = 65_000;
const MAX_COMMAND_POLL_ATTEMPTS = 180;
const MAX_CONSECUTIVE_POLL_ERRORS = 5;

interface CommandPollBudget {
  commandId: string;
  startedAt: number;
  attempts: number;
  consecutiveErrors: number;
  exhausted: boolean;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function rejectedPreflightFrom(reason: unknown): MotionPreflightReport | null {
  if (!(reason instanceof ApiError) || !isRecord(reason.details)) return null;
  const value = reason.details.preflight;
  if (
    !isRecord(value) ||
    value.accepted !== false ||
    !Array.isArray(value.checks) ||
    !Array.isArray(value.warnings)
  ) return null;
  const checks = value.checks.flatMap((check) => {
    if (
      !isRecord(check) ||
      typeof check.name !== 'string' ||
      typeof check.passed !== 'boolean' ||
      typeof check.detail !== 'string'
    ) return [];
    return [{ name: check.name, passed: check.passed, detail: check.detail }];
  });
  if (checks.length !== value.checks.length) return null;
  const warnings = value.warnings.filter((warning): warning is string => typeof warning === 'string');
  if (warnings.length !== value.warnings.length) return null;
  return {
    accepted: false,
    command_id: typeof value.command_id === 'string' ? value.command_id : undefined,
    checks,
    warnings,
    profile_fingerprint:
      typeof value.profile_fingerprint === 'string' ? value.profile_fingerprint : undefined,
    kinematics_fingerprint:
      typeof value.kinematics_fingerprint === 'string' ? value.kinematics_fingerprint : undefined,
  };
}

type PendingCommand =
  | 'move-joints'
  | 'jog-step'
  | 'cartesian-jog'
  | 'move-pose'
  | 'home'
  | 'stop';

export function useMotionCommands(options: {
  socketCommand: MotionCommandStatus | null;
  refreshRuntime: () => Promise<void>;
}) {
  const { socketCommand, refreshRuntime } = options;
  const [command, setCommand] = useState<MotionCommandStatus | null>(null);
  const [pending, setPending] = useState<PendingCommand | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stopError, setStopError] = useState<string | null>(null);
  const [stopUncertain, setStopUncertain] = useState(false);
  const [rejectedPreflight, setRejectedPreflight] =
    useState<MotionPreflightReport | null>(null);
  const pollBudgetRef = useRef<CommandPollBudget | null>(null);

  const registerSubmission = useCallback((submission: MotionCommandSubmission) => {
    setCommand(submission.command);
    setError(null);
    setRejectedPreflight(null);
  }, []);

  const registerStatus = useCallback((status: MotionCommandStatus) => {
    setCommand(status);
    setError(null);
    setRejectedPreflight(null);
  }, []);

  const reportError = useCallback((reason: unknown) => {
    setError(errorMessage(reason));
    setRejectedPreflight(rejectedPreflightFrom(reason));
  }, []);

  const execute = useCallback(
    async (
      kind: PendingCommand,
      operation: () => Promise<MotionCommandSubmission>,
    ): Promise<MotionCommandSubmission | null> => {
      setPending(kind);
      setError(null);
      setRejectedPreflight(null);
      try {
        const submission = await operation();
        registerSubmission(submission);
        return submission;
      } catch (reason) {
        reportError(reason);
        return null;
      } finally {
        setPending(null);
      }
    },
    [registerSubmission, reportError],
  );

  useEffect(() => {
    if (!socketCommand) return;
    setCommand((current) =>
      current === null || current.command_id === socketCommand.command_id ? socketCommand : current,
    );
  }, [socketCommand]);

  useEffect(() => {
    const commandId = command?.command_id;
    const state = command?.state;
    if (!commandId || !state) return;
    if (TERMINAL_STATES.has(state)) {
      if (pollBudgetRef.current?.commandId === commandId) pollBudgetRef.current = null;
      return;
    }
    if (pollBudgetRef.current?.commandId !== commandId) {
      pollBudgetRef.current = {
        commandId,
        startedAt: Date.now(),
        attempts: 0,
        consecutiveErrors: 0,
        exhausted: false,
      };
    }
    const budget = pollBudgetRef.current;
    if (budget.exhausted) return;
    let disposed = false;
    let timer: number | null = null;
    const exhaust = (message: string) => {
      budget.exhausted = true;
      setError(
        `${message} Motion remains locked; use STOP MOTION or restore backend status updates.`,
      );
    };
    const budgetExceeded = () => {
      if (budget.attempts >= MAX_COMMAND_POLL_ATTEMPTS) {
        exhaust(`Command status polling stopped after ${MAX_COMMAND_POLL_ATTEMPTS} attempts.`);
        return true;
      }
      if (Date.now() - budget.startedAt >= MAX_COMMAND_POLL_DURATION_MS) {
        exhaust('Command status polling stopped after the 65 second duration budget.');
        return true;
      }
      return false;
    };
    const schedule = (delayMs: number) => {
      if (disposed || budget.exhausted) return;
      const remainingMs = MAX_COMMAND_POLL_DURATION_MS - (Date.now() - budget.startedAt);
      timer = window.setTimeout(() => void poll(), Math.max(0, Math.min(delayMs, remainingMs)));
    };
    const poll = async () => {
      if (disposed || budget.exhausted || budgetExceeded()) return;
      budget.attempts += 1;
      try {
        const status = await getMotionCommand(commandId);
        if (disposed) return;
        budget.consecutiveErrors = 0;
        setError(null);
        setCommand(status);
        if (TERMINAL_STATES.has(status.state)) {
          void refreshRuntime();
          return;
        }
        schedule(400);
      } catch (reason) {
        if (disposed) return;
        budget.consecutiveErrors += 1;
        const detail = errorMessage(reason);
        if (budget.consecutiveErrors >= MAX_CONSECUTIVE_POLL_ERRORS) {
          exhaust(
            `Command status polling stopped after ${MAX_CONSECUTIVE_POLL_ERRORS} consecutive failures. Last error: ${detail}`,
          );
          return;
        }
        setError(detail);
        schedule(1000);
      }
    };
    schedule(400);
    return () => {
      disposed = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [command?.command_id, command?.state, refreshRuntime]);

  const requestStop = useCallback(async () => {
    setPending('stop');
    setError(null);
    try {
      const response = await stopMotion();
      const stable = response.result === 'STOPPED' || response.result === 'NOT_CONNECTED';
      setStopUncertain(!stable);
      setStopError(
        stable
          ? null
          : `Motion Stop returned ${response.result}. Safety state is not confirmed; motion remains locked. Retry STOP MOTION and inspect backend diagnostics.`,
      );
      if (command?.command_id) {
        try {
          setCommand(await getMotionCommand(command.command_id));
        } catch (reason) {
          setError(`Command status refresh failed after Stop: ${errorMessage(reason)}`);
        }
      }
      try {
        await refreshRuntime();
      } catch (reason) {
        setError(`Runtime refresh failed after Stop: ${errorMessage(reason)}`);
      }
    } catch (reason) {
      setStopUncertain(true);
      setStopError(
        `Motion Stop request failed. Safety state is not confirmed; motion remains locked. ${errorMessage(reason)}`,
      );
    } finally {
      setPending(null);
    }
  }, [command?.command_id, refreshRuntime]);

  const requestMoveJoints = useCallback(
    (request: MoveJointsRequest) => execute('move-joints', () => moveJoints(request)),
    [execute],
  );
  const requestJogStep = useCallback(
    (request: JointJogStepRequest) => execute('jog-step', () => jogJointStep(request)),
    [execute],
  );
  const requestCartesianJog = useCallback(
    (request: CartesianJogRequest) => execute('cartesian-jog', () => moveCartesian(request)),
    [execute],
  );
  const requestMovePose = useCallback(
    (request: MovePoseRequest) => execute('move-pose', () => movePose(request)),
    [execute],
  );
  const requestHome = useCallback(
    (request: HomeRequest) => execute('home', () => moveHome(request)),
    [execute],
  );

  return {
    command,
    pending,
    error: stopError ?? error,
    stopUncertain,
    rejectedPreflight,
    clearError: () => setError(null),
    reportError,
    registerSubmission,
    registerStatus,
    moveJoints: requestMoveJoints,
    jogStep: requestJogStep,
    cartesianJog: requestCartesianJog,
    movePose: requestMovePose,
    home: requestHome,
    stop: requestStop,
  };
}
