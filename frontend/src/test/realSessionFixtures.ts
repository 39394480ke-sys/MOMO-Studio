import type {
  DeviceAuthorizationOption,
  DeviceCapabilityDetail,
  DeviceCapabilityKey,
  DeviceReadiness,
  DeviceSessionSummary,
} from '../api/types';
import {
  closedCapabilityDetails,
  REAL_CAPABILITY_KEYS,
  type RealSessionContextValue,
  type RealSessionSummary,
} from '../components/realSessionContext';

interface RealSessionFixtureOptions {
  authorizationOptions?: DeviceAuthorizationOption[];
  capabilities?: Partial<Record<DeviceCapabilityKey, Partial<DeviceCapabilityDetail>>>;
  error?: string | null;
  readiness?: DeviceReadiness | null;
  session?: DeviceSessionSummary | null;
  stale?: boolean;
  authorize?: RealSessionContextValue['authorize'];
  revoke?: RealSessionContextValue['revoke'];
  refresh?: RealSessionContextValue['refresh'];
}

export function realSessionFixture(
  options: RealSessionFixtureOptions = {},
): RealSessionContextValue {
  const closed = closedCapabilityDetails('BACKEND_CAPABILITY_NOT_AUTHORIZED');
  const capabilityDetails = Object.fromEntries(REAL_CAPABILITY_KEYS.map((key) => [key, {
    ...closed[key],
    ...options.capabilities?.[key],
  }])) as RealSessionSummary['capabilityDetails'];
  const summary: RealSessionSummary = {
    readiness: options.readiness ?? null,
    session: options.session ?? null,
    capabilityDetails,
    authorizationOptions: options.authorizationOptions ?? [],
    loading: false,
    stale: options.stale ?? false,
    error: options.error ?? null,
    updatedAt: '2026-08-25T00:00:00Z',
  };
  return {
    summary,
    pendingAction: null,
    authorize: options.authorize ?? (async () => {
      throw new Error('Unexpected authorization request');
    }),
    revoke: options.revoke ?? (async () => undefined),
    refresh: options.refresh ?? (async () => undefined),
  };
}
