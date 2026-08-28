import { createContext, useContext } from 'react';

import type {
  DeviceAuthorizationOption,
  DeviceCapabilityDetails,
  DeviceCapabilityKey,
  DeviceReadiness,
  DeviceSessionSummary,
  OperatorSessionPurpose,
  OperatorSessionResponse,
} from '../api/types';

export const REAL_CAPABILITY_KEYS: readonly DeviceCapabilityKey[] = [
  'commissioning_read_only',
  'commissioning_motion_test',
  'raw_direction_test',
  'real_joint_motion',
  'real_cartesian_motion',
  'real_playback',
  'real_vision_follow',
];

export type RealSessionPendingAction = 'authorize' | 'revoke' | null;

export interface RealSessionSummary {
  readiness: DeviceReadiness | null;
  session: DeviceSessionSummary | null;
  capabilityDetails: DeviceCapabilityDetails;
  authorizationOptions: DeviceAuthorizationOption[];
  loading: boolean;
  stale: boolean;
  error: string | null;
  updatedAt: string | null;
}

export interface RealSessionContextValue {
  summary: RealSessionSummary;
  pendingAction: RealSessionPendingAction;
  authorize: (
    purpose: OperatorSessionPurpose,
    confirmationText: string,
    physicalEstopConfirmed: boolean,
    workspaceClearConfirmed?: boolean,
  ) => Promise<OperatorSessionResponse>;
  revoke: () => Promise<void>;
  refresh: () => Promise<void>;
}

export interface RealCapabilityAvailability {
  allowed: boolean;
  reason: string;
  blockedReasons: string[];
  requiredEvidence: string[];
}

export function realCapabilityAvailability(
  summary: RealSessionSummary,
  capability: DeviceCapabilityKey,
): RealCapabilityAvailability {
  const detail = summary.capabilityDetails[capability];
  if (summary.stale) {
    return {
      allowed: false,
      reason: summary.error ?? 'Real capability status is stale',
      blockedReasons: detail.blocked_reasons,
      requiredEvidence: detail.required_evidence,
    };
  }
  if (detail.ready && detail.authorized) {
    return {
      allowed: true,
      reason: 'Backend capability authorized',
      blockedReasons: [],
      requiredEvidence: [],
    };
  }
  const reasons = [
    ...detail.blocked_reasons,
    ...detail.required_evidence.map((item) => `Required evidence: ${item}`),
  ];
  return {
    allowed: false,
    reason: reasons.join(' · ') || 'Backend capability is not ready and authorized',
    blockedReasons: detail.blocked_reasons,
    requiredEvidence: detail.required_evidence,
  };
}

export function closedCapabilityDetails(reason: string): DeviceCapabilityDetails {
  const detail = () => ({
    ready: false,
    authorized: false,
    blocked_reasons: [reason],
    required_evidence: [],
  });
  return {
    commissioning_read_only: detail(),
    commissioning_motion_test: detail(),
    raw_direction_test: detail(),
    real_joint_motion: detail(),
    real_cartesian_motion: detail(),
    real_playback: detail(),
    real_vision_follow: detail(),
  };
}

export const SAFE_REAL_SESSION_SUMMARY: RealSessionSummary = {
  readiness: null,
  session: null,
  capabilityDetails: closedCapabilityDetails('REAL_CONTROL_MODE_REQUIRED'),
  authorizationOptions: [],
  loading: false,
  stale: false,
  error: null,
  updatedAt: null,
};

const rejectUnavailable = async (): Promise<never> => {
  throw new Error('Real Session provider is unavailable');
};

export const SAFE_REAL_SESSION: RealSessionContextValue = {
  summary: SAFE_REAL_SESSION_SUMMARY,
  pendingAction: null,
  authorize: rejectUnavailable,
  revoke: rejectUnavailable,
  refresh: async () => undefined,
};

export const RealSessionContext = createContext<RealSessionContextValue>(SAFE_REAL_SESSION);

export function useRealSession(): RealSessionContextValue {
  return useContext(RealSessionContext);
}
