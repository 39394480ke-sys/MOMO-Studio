import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  acceptFieldJointMotion,
  addKinematicsVerificationMeasurement,
  armCommissioningJoint,
  commitKinematicsVerificationDraft,
  completeFieldPreMotionChecks,
  connectRealDevice,
  disconnectRealDevice,
  getCommissioningMotionStatus,
  getFieldAcceptanceProgress,
  getFieldAcceptanceStatus,
  getKinematicsVerificationStatus,
  heartbeatCommissioningMotionTest,
  runDeviceDiagnostics,
  startCommissioningJointTest,
  startCommissioningMotionSession,
  startKinematicsVerificationDraft,
  stopCommissioningMotionTest,
} from '../../api/client';
import type {
  CommissioningMotionStatus,
  DeviceAuthorizationOption,
  DeviceCapabilityDetails,
  DeviceConfirmationEvidence,
  DeviceDiagnostics,
  DeviceReadiness,
  DeviceSessionSummary,
  FieldAcceptanceProgress,
  KinematicsVerificationDraft,
  OperatorSessionResponse,
  RobotProfile,
  RobotStatus,
} from '../../api/types';
import {
  RealSessionContext,
  type RealSessionContextValue,
} from '../../components/realSessionContext';
import {
  RuntimeStatusContext,
  SAFE_RUNTIME_STATUS,
} from '../../components/runtimeStatusContext';
import { realSessionFixture } from '../../test/realSessionFixtures';
import { robotFor, stage3Ids, v2Profile } from '../../test/stage3Fixtures';
import { RealHardwarePanel } from './RealHardwarePanel';

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>();
  return {
    ...actual,
    acceptFieldJointMotion: vi.fn(),
    addKinematicsVerificationMeasurement: vi.fn(),
    armCommissioningJoint: vi.fn(),
    commitKinematicsVerificationDraft: vi.fn(),
    completeFieldPreMotionChecks: vi.fn(),
    connectRealDevice: vi.fn(),
    disconnectRealDevice: vi.fn(),
    getCommissioningMotionStatus: vi.fn(),
    getFieldAcceptanceProgress: vi.fn(),
    getFieldAcceptanceStatus: vi.fn(),
    getKinematicsVerificationStatus: vi.fn(),
    heartbeatCommissioningMotionTest: vi.fn(),
    runDeviceDiagnostics: vi.fn(),
    startCommissioningJointTest: vi.fn(),
    startCommissioningMotionSession: vi.fn(),
    startKinematicsVerificationDraft: vi.fn(),
    stopCommissioningMotionTest: vi.fn(),
    stopRealDevice: vi.fn(),
  };
});

const READ_ONLY_CONFIRMATION = 'I UNDERSTAND COMMISSIONING IS READ ONLY';
const MOTION_TEST_CONFIRMATION = 'I CONFIRM LOW-SPEED SINGLE-JOINT COMMISSIONING';
const SESSION_ID = '11111111-1111-4111-8111-111111111111';

function confirmation(
  purpose: DeviceConfirmationEvidence['session_purpose'],
): DeviceConfirmationEvidence {
  return {
    robot_id: 'primary',
    robot_unit_id: 'MOMO-V2-UNIT-001',
    variant: 'V2',
    profile_fingerprint: stage3Ids.profileFingerprint,
    calibration_fingerprint: 'c'.repeat(64),
    kinematics_fingerprint: stage3Ids.kinematicsFingerprint,
    masked_serial_port: '/dev/***USB0',
    masked_servo_ids: ['**1', '**2'],
    protocol: 'STS',
    session_purpose: purpose,
    field_acceptance_evidence_id: null,
    physical_estop_required: true,
    workspace_clear_required: purpose === 'COMMISSIONING_MOTION_TEST',
    required_confirmation_text: purpose === 'COMMISSIONING_MOTION_TEST'
      ? MOTION_TEST_CONFIRMATION
      : READ_ONLY_CONFIRMATION,
  };
}

function capabilityDetails(
  authorized: 'NONE' | 'READ_ONLY' | 'MOTION_TEST' | 'REAL_JOINT' = 'NONE',
): DeviceCapabilityDetails {
  const blocked = (reason: string, evidence: string[] = []) => ({
    ready: false,
    authorized: false,
    blocked_reasons: [reason],
    required_evidence: evidence,
  });
  return {
    commissioning_read_only: authorized === 'READ_ONLY'
      ? { ready: true, authorized: true, blocked_reasons: [], required_evidence: [] }
      : { ready: true, authorized: false, blocked_reasons: ['READ_ONLY_SESSION_REQUIRED'], required_evidence: [] },
    commissioning_motion_test: authorized === 'MOTION_TEST'
      ? { ready: true, authorized: true, blocked_reasons: [], required_evidence: [] }
      : blocked('COMMISSIONING_MOTION_SESSION_REQUIRED', ['PER_JOINT_DIRECTION_EVIDENCE']),
    raw_direction_test: blocked('RAW_DIRECTION_TEST_NOT_ENABLED', ['ZERO_RAW_SNAPSHOT']),
    real_joint_motion: authorized === 'REAL_JOINT'
      ? { ready: true, authorized: true, blocked_reasons: [], required_evidence: [] }
      : blocked('JOINT_ACCEPTANCE_PENDING', ['PER_JOINT_DIRECTION_EVIDENCE']),
    real_cartesian_motion: blocked('KINEMATICS_FIELD_VERIFICATION_PENDING', ['KINEMATICS_FIELD_EVIDENCE']),
    real_playback: blocked('PLAYBACK_ACCEPTANCE_PENDING', ['PLAYBACK_FIELD_ACCEPTANCE']),
    real_vision_follow: blocked('VISION_FOLLOW_ACCEPTANCE_PENDING', ['VISION_FOLLOW_FIELD_ACCEPTANCE']),
  };
}

const authorizationOptions: DeviceAuthorizationOption[] = [
  {
    purpose: 'COMMISSIONING_READ_ONLY',
    authorizable: true,
    confirmation: confirmation('COMMISSIONING_READ_ONLY'),
  },
  {
    purpose: 'COMMISSIONING_MOTION_TEST',
    authorizable: true,
    confirmation: confirmation('COMMISSIONING_MOTION_TEST'),
  },
  {
    purpose: 'RAW_DIRECTION_TEST',
    authorizable: false,
    confirmation: confirmation('RAW_DIRECTION_TEST'),
  },
  {
    purpose: 'REAL_MOTION',
    authorizable: false,
    confirmation: confirmation('REAL_MOTION'),
  },
];

function readiness(
  session: DeviceSessionSummary | null = null,
  connected = false,
): DeviceReadiness {
  const authorized = session?.purpose === 'COMMISSIONING_READ_ONLY'
    ? 'READ_ONLY'
    : session?.purpose === 'COMMISSIONING_MOTION_TEST'
      ? 'MOTION_TEST'
      : session?.purpose === 'REAL_MOTION'
        ? 'REAL_JOINT'
      : 'NONE';
  return {
    state: session ? 'OPERATOR_SESSION_ACTIVE' : 'COMMISSIONING_READY',
    ready: false,
    session_authorizable: session === null,
    commissioning_session_authorizable: session === null,
    commissioning_motion_session_authorizable: session === null,
    raw_direction_session_authorizable: false,
    motion_session_authorizable: false,
    blocking_reasons: ['REAL_FIELD_ACCEPTANCE_PENDING'],
    capabilities: {
      commissioning_diagnostics_ready: true,
      calibration_capture_ready: true,
      commissioning_motion_test_ready: true,
      raw_direction_test_ready: false,
      real_joint_motion_ready: false,
      real_cartesian_motion_ready: false,
      real_playback_ready: false,
      real_vision_follow_ready: false,
    },
    capability_details: capabilityDetails(authorized),
    authorization_options: session ? authorizationOptions.map((option) => ({
      ...option,
      authorizable: false,
    })) : authorizationOptions,
    confirmation: confirmation('COMMISSIONING_READ_ONLY'),
    session,
    calibration_configured: true,
    connected,
  };
}

const readOnlySession: DeviceSessionSummary = {
  active: true,
  session_id: SESSION_ID,
  expires_at: '2099-08-25T00:00:00Z',
  purpose: 'COMMISSIONING_READ_ONLY',
  scopes: ['DIAGNOSTICS_READ', 'CALIBRATION_CAPTURE'],
};

const motionTestSession: DeviceSessionSummary = {
  active: true,
  session_id: SESSION_ID,
  expires_at: '2099-08-25T00:00:00Z',
  purpose: 'COMMISSIONING_MOTION_TEST',
  scopes: ['COMMISSIONING_SINGLE_JOINT_TEST'],
};

const realJointSession: DeviceSessionSummary = {
  active: true,
  session_id: SESSION_ID,
  expires_at: '2099-08-25T00:00:00Z',
  purpose: 'REAL_MOTION',
  scopes: ['REAL_JOINT_MOTION'],
};

const diagnostics: DeviceDiagnostics = {
  connected: true,
  captured_at: '2026-08-25T01:02:03Z',
  dependency: {
    adapter_id: 'fake-servo-bus',
    state: 'AVAILABLE',
    package_name: null,
    license_status: 'TEST_ONLY',
    notice: 'Fake adapter',
  },
  hardware_policy: 'READ_ONLY',
  masked_serial_port: '/dev/***USB0',
  masked_servo_ids: ['**1', '**2'],
  protocol: 'STS',
  profile: { configured: true, fingerprint: stage3Ids.profileFingerprint, verification_status: 'VERIFIED_FOR_REAL', template: false, ready_for_real: true },
  calibration: { configured: true, fingerprint: 'c'.repeat(64), verification_status: 'FIELD_VERIFIED', template: false, ready_for_real: true },
  kinematics: { configured: true, fingerprint: stage3Ids.kinematicsFingerprint, verification_status: 'PROVISIONAL_DRY_RUN', template: null, ready_for_real: false },
  field_acceptance: 'PENDING',
  readiness: 'COMMISSIONING_READ_ONLY',
  records: [{
    joint_id: 'j11',
    masked_servo_id: '**1',
    ping_responded: true,
    operating_mode: 'POSITION',
    present_raw: 2048,
    logical_value: 0,
    raw_bounds: [1024, 3072],
    torque_enabled: false,
  }],
  last_error: null,
};

const authorizedStatus: CommissioningMotionStatus = {
  state: 'AUTHORIZED',
  session_id: SESSION_ID,
  active_joint_id: null,
  command_count: 0,
  session_expires_at: '2099-08-25T00:00:00Z',
  deadman_expires_at: null,
  last_evidence_id: null,
  failure_reason: null,
  physical_stop_verification: 'PENDING',
};

const progressFixture: FieldAcceptanceProgress = {
  state: 'PRE_MOTION_CHECKS_COMPLETE',
  robot_unit_id: 'MOMO-V2-UNIT-001',
  checklist_version: 'field-v2',
  valid_capabilities: ['PRE_MOTION_CHECKS'],
  pre_motion_checks_complete: true,
  joint_motion_tests_complete: false,
  joint_motion_accepted: false,
  ready_to_accept_joint_motion: false,
  completed_joint_directions: 0,
  required_joint_directions: v2Profile.enabled_joints.length * 2,
  joints: v2Profile.enabled_joints.map((jointId) => ({
    joint_id: jointId,
    unit: jointId === 'j10' ? 'mm' : 'deg',
    positive_evidence_id: null,
    negative_evidence_id: null,
    complete: false,
  })),
  selected_test_evidence_ids: [],
  rejected_test_evidence_ids: [],
  stale_field_acceptance_evidence_ids: [],
  legacy_field_acceptance_evidence_ids: [],
  physical_stop_verification: 'PENDING',
  full_acceptance_complete: false,
};

const readyJointProgress: FieldAcceptanceProgress = {
  ...progressFixture,
  state: 'JOINT_MOTION_TESTING',
  joint_motion_tests_complete: true,
  ready_to_accept_joint_motion: true,
  completed_joint_directions: progressFixture.required_joint_directions,
};

const jointAcceptedProgress: FieldAcceptanceProgress = {
  ...readyJointProgress,
  state: 'KINEMATICS_VERIFICATION_PENDING',
  valid_capabilities: ['PRE_MOTION_CHECKS', 'JOINT_MOTION'],
  joint_motion_accepted: true,
  ready_to_accept_joint_motion: false,
};

const kinematicsDraft: KinematicsVerificationDraft = {
  draft_id: '88888888-8888-4888-8888-888888888888',
  operator_session_id: SESSION_ID,
  operator_id: 'operator',
  robot_unit_id: 'MOMO-V2-UNIT-001',
  profile_fingerprint: stage3Ids.profileFingerprint,
  calibration_fingerprint: 'c'.repeat(64),
  device_fingerprint: 'd'.repeat(64),
  kinematics_fingerprint: stage3Ids.kinematicsFingerprint,
  software_commit: 'abcdef1',
  verification_checklist_version: 'kinematics-v1',
  thresholds: {
    max_position_error_mm: 5,
    max_orientation_error_deg: 5,
  },
  points: [],
};

function renderPanel(options: {
  session?: DeviceSessionSummary | null;
  connected?: boolean;
  authorize?: RealSessionContextValue['authorize'];
  revoke?: RealSessionContextValue['revoke'];
  refresh?: RealSessionContextValue['refresh'];
} = {}) {
  const session = options.session ?? null;
  const currentReadiness = readiness(session, options.connected ?? false);
  const authorized = session?.purpose === 'COMMISSIONING_READ_ONLY'
    ? 'READ_ONLY'
    : session?.purpose === 'COMMISSIONING_MOTION_TEST'
      ? 'MOTION_TEST'
      : session?.purpose === 'REAL_MOTION'
        ? 'REAL_JOINT'
      : 'NONE';
  const context = realSessionFixture({
    readiness: currentReadiness,
    session,
    authorizationOptions: currentReadiness.authorization_options,
    capabilities: capabilityDetails(authorized),
    authorize: options.authorize,
    revoke: options.revoke,
    refresh: options.refresh,
  });
  return render(
    <RuntimeStatusContext.Provider value={{
      ...SAFE_RUNTIME_STATUS,
      backend: 'connected',
      controlMode: 'REAL',
      hardwareAccessPolicy: 'READ_ONLY',
      robot: robotFor('V2', true) as RobotStatus,
      profile: {
        profile: v2Profile as RobotProfile,
        fingerprint: stage3Ids.profileFingerprint,
        kinematics_fingerprint: stage3Ids.kinematicsFingerprint,
        real_eligible: false,
      },
    }}>
      <RealSessionContext.Provider value={context}>
        <RealHardwarePanel />
      </RealSessionContext.Provider>
    </RuntimeStatusContext.Provider>,
  );
}

function openAdvancedDiagnostics() {
  fireEvent.click(screen.getByText('高级诊断与后续验收阶段'));
}

beforeEach(() => {
  vi.mocked(getFieldAcceptanceProgress).mockReset();
  vi.mocked(getFieldAcceptanceProgress).mockResolvedValue(progressFixture);
  vi.mocked(getFieldAcceptanceStatus).mockReset();
  vi.mocked(getFieldAcceptanceStatus).mockResolvedValue({
    state: 'MISSING',
    effective_status: 'PENDING',
    checklist_version: '1',
    stale_fields: [],
    evidence_id: null,
    accepted_at: null,
    accepted_by: null,
    required_confirmation_text: 'FIELD ACCEPTANCE REQUIRES REVIEW',
  });
  vi.mocked(getCommissioningMotionStatus).mockReset();
  vi.mocked(getCommissioningMotionStatus).mockResolvedValue(authorizedStatus);
  vi.mocked(getKinematicsVerificationStatus).mockReset();
  vi.mocked(getKinematicsVerificationStatus).mockResolvedValue({
    state: 'MISSING',
    stale_fields: [],
    evidence_id: null,
    point_count: 0,
  });
  vi.mocked(acceptFieldJointMotion).mockReset();
  vi.mocked(addKinematicsVerificationMeasurement).mockReset();
  vi.mocked(armCommissioningJoint).mockReset();
  vi.mocked(commitKinematicsVerificationDraft).mockReset();
  vi.mocked(completeFieldPreMotionChecks).mockReset();
  vi.mocked(heartbeatCommissioningMotionTest).mockReset();
  vi.mocked(startCommissioningJointTest).mockReset();
  vi.mocked(startCommissioningMotionSession).mockReset();
  vi.mocked(startKinematicsVerificationDraft).mockReset();
  vi.mocked(stopCommissioningMotionTest).mockReset();
  vi.mocked(connectRealDevice).mockReset();
  vi.mocked(disconnectRealDevice).mockReset();
  vi.mocked(runDeviceDiagnostics).mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('RealHardwarePanel', () => {
  it('renders backend capability blockers, physical identity, and staged progress', async () => {
    renderPanel();
    openAdvancedDiagnostics();

    expect((await screen.findAllByText('MOMO-V2-UNIT-001')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('KINEMATICS_FIELD_VERIFICATION_PENDING').length)
      .toBeGreaterThan(0);
    expect(screen.getAllByText(/Required evidence: KINEMATICS_FIELD_EVIDENCE/).length)
      .toBeGreaterThan(0);
    expect(screen.getByRole('heading', { name: 'COMMISSIONING MOTION TEST' })).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Commissioning progress' })).toBeVisible();
    expect(screen.getByText('Physical E-stop must remain reachable.')).toBeVisible();
    expect(screen.getByText('Software Stop physical behavior: NOT YET FIELD VERIFIED')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Authorize Motion Test' })).toBeEnabled();
    expect(screen.queryByText(/session_token|raw token/i)).not.toBeInTheDocument();
  });

  it('requires robot-unit, E-stop, and workspace-clear confirmation for Motion Test', async () => {
    const authorize = vi.fn(async (): Promise<OperatorSessionResponse> => ({
      session_id: SESSION_ID,
      issued_at: '2026-08-25T00:00:00Z',
      expires_at: '2099-08-25T00:00:00Z',
      purpose: 'COMMISSIONING_MOTION_TEST',
      scopes: ['COMMISSIONING_SINGLE_JOINT_TEST'],
      evidence: confirmation('COMMISSIONING_MOTION_TEST'),
    }));
    renderPanel({ authorize });

    fireEvent.click(await screen.findByRole('button', { name: 'Authorize Motion Test' }));
    expect(screen.getAllByText('MOMO-V2-UNIT-001').length).toBeGreaterThan(0);
    const confirmButton = screen.getByRole('button', { name: 'Authorize Motion Test session' });
    fireEvent.change(screen.getByLabelText(/Type the exact confirmation text/), {
      target: { value: MOTION_TEST_CONFIRMATION },
    });
    fireEvent.click(screen.getByLabelText(/tested physical E-stop/));
    expect(confirmButton).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/workspace is clear and guarded/));
    fireEvent.click(confirmButton);

    await waitFor(() => expect(authorize).toHaveBeenCalledWith(
      'COMMISSIONING_MOTION_TEST',
      MOTION_TEST_CONFIRMATION,
      true,
      true,
    ));
  });

  it('invokes protected read-only device calls without a JavaScript token', async () => {
    vi.mocked(runDeviceDiagnostics).mockResolvedValue(diagnostics);
    vi.mocked(disconnectRealDevice).mockResolvedValue(diagnostics);
    renderPanel({ session: readOnlySession, connected: true });
    openAdvancedDiagnostics();

    fireEvent.click(await screen.findByRole('button', { name: 'Diagnostics' }));
    await waitFor(() => expect(runDeviceDiagnostics).toHaveBeenCalledWith());
    expect(await screen.findByRole('cell', { name: '2048' })).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Disconnect' }));
    await waitFor(() => expect(disconnectRealDevice).toHaveBeenCalledWith());
    expect(connectRealDevice).not.toHaveBeenCalled();
  });

  it('keeps a protected device error visible after readiness refresh succeeds', async () => {
    vi.mocked(runDeviceDiagnostics).mockRejectedValue(
      new Error('Backend returned an invalid device diagnostic error'),
    );
    renderPanel({ session: readOnlySession, connected: true });

    fireEvent.click(await screen.findByRole('button', { name: 'Diagnostics' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Backend returned an invalid device diagnostic error',
    );
    expect(getFieldAcceptanceStatus).toHaveBeenCalled();
  });

  it('records pre-motion checks only through the connected read-only session', async () => {
    const beforePreMotion: FieldAcceptanceProgress = {
      ...progressFixture,
      state: 'CALIBRATION_COMPLETE',
      valid_capabilities: [],
      pre_motion_checks_complete: false,
    };
    vi.mocked(getFieldAcceptanceProgress).mockResolvedValue(beforePreMotion);
    vi.mocked(completeFieldPreMotionChecks).mockResolvedValue(progressFixture);
    renderPanel({ session: readOnlySession, connected: true });

    const action = await screen.findByRole('button', { name: 'Record pre-motion checks' });
    await waitFor(() => expect(action).toBeEnabled());
    fireEvent.click(action);

    await waitFor(() => expect(completeFieldPreMotionChecks).toHaveBeenCalledWith('field-v2'));
    expect(acceptFieldJointMotion).not.toHaveBeenCalled();
  });

  it('accepts only backend-selected joint evidence in the motion-test session', async () => {
    vi.mocked(getFieldAcceptanceProgress).mockResolvedValue(readyJointProgress);
    vi.mocked(acceptFieldJointMotion).mockResolvedValue(jointAcceptedProgress);
    renderPanel({ session: motionTestSession, connected: true });

    const action = await screen.findByRole('button', {
      name: 'Accept persisted joint evidence',
    });
    await waitFor(() => expect(action).toBeEnabled());
    fireEvent.click(action);

    await waitFor(() => expect(acceptFieldJointMotion).toHaveBeenCalledWith('field-v2'));
    expect(completeFieldPreMotionChecks).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: /mark.*pass|accept all/i })).not.toBeInTheDocument();
  });

  it('captures an explicit measured TCP while the backend owns the joint snapshot', async () => {
    const robot = robotFor('V2', true) as RobotStatus;
    const tcp = {
      frame: 'base',
      position_mm: { x: 100, y: 200, z: 300 },
      orientation_quaternion_xyzw: { x: 0, y: 0, z: 0, w: 1 },
    };
    vi.mocked(getFieldAcceptanceProgress).mockResolvedValue(jointAcceptedProgress);
    vi.mocked(startKinematicsVerificationDraft).mockResolvedValue(kinematicsDraft);
    vi.mocked(addKinematicsVerificationMeasurement).mockResolvedValue({
      ...kinematicsDraft,
      points: [{
        point_id: '99999999-9999-4999-8999-999999999999',
        label: 'front-low gauge',
        joint_state: {
          positions: robot.positions,
          units: robot.units,
        },
        joint_state_sequence: 7,
        joint_state_captured_at: '2026-08-25T01:59:59Z',
        snapshot_session_id: SESSION_ID,
        predicted_tcp: tcp,
        measured_tcp: tcp,
        position_error_mm: 0,
        orientation_error_deg: 0,
        measured_at: '2026-08-25T02:00:00Z',
      }],
    });
    renderPanel({ session: realJointSession, connected: true });
    openAdvancedDiagnostics();
    await waitFor(() => expect(getKinematicsVerificationStatus).toHaveBeenCalledTimes(1));

    const start = await screen.findByRole('button', { name: 'Start measured-TCP draft' });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    await waitFor(() => expect(startKinematicsVerificationDraft).toHaveBeenCalledWith({
      max_position_error_mm: 5,
      max_orientation_error_deg: 5,
    }));

    fireEvent.change(screen.getByLabelText('Measurement label'), {
      target: { value: 'front-low gauge' },
    });
    fireEvent.change(screen.getByLabelText('Measured X (mm)'), { target: { value: '100' } });
    fireEvent.change(screen.getByLabelText('Measured Y (mm)'), { target: { value: '200' } });
    fireEvent.change(screen.getByLabelText('Measured Z (mm)'), { target: { value: '300' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add measured point' }));

    await waitFor(() => expect(addKinematicsVerificationMeasurement).toHaveBeenCalledWith(
      kinematicsDraft.draft_id,
      {
        label: 'front-low gauge',
        measured_tcp: tcp,
      },
    ));
    expect(screen.getByText(/backend captures and validates a fresh hardware readback/i))
      .toBeVisible();
    expect(await screen.findByText(
      /Sequence 7.*captured 2026-08-25T01:59:59Z.*j10: 0 mm.*j11: 0 deg/,
    )).toHaveAttribute('title', `Operator Session ${SESSION_ID}`);
    expect(screen.getByRole('button', {
      name: 'Commit measured Kinematics evidence',
    })).toBeDisabled();
    expect(screen.queryByText(/mark.*kinematics.*verified/i)).not.toBeInTheDocument();
  });

  it('enforces press-hold heartbeat, bounded request, release Stop, and STOP TEST', async () => {
    vi.useFakeTimers();
    vi.mocked(startCommissioningMotionSession).mockResolvedValue(authorizedStatus);
    vi.mocked(armCommissioningJoint).mockResolvedValue({
      ...authorizedStatus,
      state: 'ARMED',
      active_joint_id: 'j11',
    });
    vi.mocked(heartbeatCommissioningMotionTest).mockResolvedValue({
      ...authorizedStatus,
      state: 'MOVING',
      active_joint_id: 'j11',
      deadman_expires_at: '2099-08-25T00:00:01Z',
    });
    vi.mocked(stopCommissioningMotionTest).mockResolvedValue(authorizedStatus);
    vi.mocked(startCommissioningJointTest).mockImplementation(() => new Promise(() => undefined));
    renderPanel({ session: motionTestSession });

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    const hold = screen.getByRole('button', {
      name: 'Hold J11 positive commissioning test',
    });
    expect(hold).toBeEnabled();
    const pointerDown = new Event('pointerdown', { bubbles: true, cancelable: true });
    Object.defineProperties(pointerDown, {
      button: { value: 0 },
      pointerId: { value: 7 },
    });
    fireEvent(hold, pointerDown);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(armCommissioningJoint).toHaveBeenCalledWith('j11');
    expect(startCommissioningJointTest).toHaveBeenCalledWith('j11', expect.objectContaining({
      signed_delta: 1,
      requested_speed: 1,
      requested_acceleration: 2,
      command_duration_s: 1,
      request_id: expect.any(String),
    }));

    await act(async () => {
      vi.advanceTimersByTime(151);
      await Promise.resolve();
    });
    expect(heartbeatCommissioningMotionTest).toHaveBeenCalled();

    fireEvent.pointerUp(hold, { pointerId: 7 });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(stopCommissioningMotionTest).toHaveBeenCalledWith('POINTER_RELEASE');

    fireEvent.click(screen.getByRole('button', { name: 'STOP TEST' }));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(stopCommissioningMotionTest).toHaveBeenCalledWith('OPERATOR_STOP_TEST');
  });
});
