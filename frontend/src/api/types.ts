export type ProductStage = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8;
export type RobotVariant = 'V1' | 'V2';
export type DomainUnit = 'mm' | 'deg';
export type CartesianFrame = 'BASE' | 'TOOL';
export type ConnectionState =
  | 'DISCONNECTED'
  | 'CONNECTING'
  | 'CONNECTED'
  | 'DISCONNECTING'
  | 'FAULTED';

export interface HealthResponse {
  status: 'ok';
  product: string;
  version: string;
  stage: ProductStage;
  control_mode: 'DRY_RUN';
  hardware_access_policy: 'DISABLED';
  real_motion_enabled: false;
}

export interface MetaResponse {
  product: string;
  version: string;
  api_version: 'v1';
  stage: ProductStage;
  active_robot_variant: RobotVariant;
  supported_robot_variants: RobotVariant[];
  supported_control_modes: Array<'DRY_RUN' | 'REAL'>;
  active_control_mode: 'DRY_RUN';
  hardware_access_policy: 'DISABLED';
  real_motion_enabled: false;
}

export interface RobotStatus {
  robot_id: string;
  variant: RobotVariant;
  control_mode: 'DRY_RUN';
  hardware_access_policy: 'DISABLED';
  connection_state: ConnectionState;
  connected: boolean;
  profile_fingerprint: string;
  profile_verification_status: 'UNVERIFIED' | 'VERIFIED_FOR_DRY_RUN' | 'VERIFIED_FOR_REAL';
  calibration_status:
    | 'NOT_CONFIGURED'
    | 'TEMPLATE_ONLY'
    | 'VARIANT_MISMATCH'
    | 'PROFILE_MISMATCH'
    | 'JOINT_SET_MISMATCH'
    | 'INCOMPLETE'
    | 'VALID_FOR_DRY_RUN'
    | 'READY_FOR_REAL';
  positions: Record<string, number>;
  units: Record<string, DomainUnit>;
  raw_positions: Record<string, number> | null;
  last_error: string | null;
  updated_at: string;
  state_sequence: number;
  hardware_accessed: false;
  stale: boolean;
}

export interface ProfileJointDefinition {
  joint_id: string;
  joint_type: 'REVOLUTE' | 'PRISMATIC';
  domain_unit: DomainUnit;
  minimum: number;
  maximum: number;
  home: number;
  servo_id: number | null;
  motor_degrees_per_domain_unit: number | null;
  raw_counts_per_motor_revolution: number;
  direction: -1 | 1;
  operating_mode: 'MULTI_TURN' | 'SINGLE_TURN';
  home_present_raw: number | null;
  raw_bounds: [number, number] | null;
  raw_reachable: boolean;
}

export interface RobotProfile {
  schema_version: '1.0.0';
  variant: RobotVariant;
  display_name: string;
  has_linear_rail: boolean;
  enabled_joints: string[];
  joint_definitions: ProfileJointDefinition[];
  urdf_reference: string | null;
  tcp_link: string;
  template: boolean;
  verification_status: 'UNVERIFIED' | 'VERIFIED_FOR_DRY_RUN' | 'VERIFIED_FOR_REAL';
  source: string;
  source_revision: string;
  description: string;
}

export interface ProfileResponse {
  profile: RobotProfile;
  fingerprint: string;
  kinematics_fingerprint?: string;
  real_eligible: false;
}

export interface CalibrationStatus {
  status: RobotStatus['calibration_status'];
  configured: boolean;
  template: boolean | null;
  variant_match: boolean | null;
  profile_match: boolean | null;
  joint_set_match: boolean | null;
  mapping_match: boolean | null;
  complete: boolean | null;
  calibration_valid: boolean;
  real_readiness: string;
  blocking_reasons: string[];
}

export interface DiagnosticsResponse {
  hardware_access_policy: 'DISABLED';
  runtime_state_path: string;
  runtime_state_valid: boolean;
  runtime_state_diagnostic: string;
  quarantined_runtime_file: string | null;
  backend_version: string;
  legacy_source_commit: string;
  stage_policy: string;
  active_profile_fingerprint: string;
  active_kinematics_fingerprint?: string;
  hardware_accessed: false;
}

export interface ErrorResponse {
  code: string;
  message: string;
  details: unknown;
  request_id?: string | null;
}

export interface BootstrapResponse {
  health: HealthResponse;
  meta: MetaResponse;
  robot: RobotStatus;
  profile: ProfileResponse;
  calibration: CalibrationStatus;
  diagnostics: DiagnosticsResponse;
}

export interface Vector3 {
  x: number;
  y: number;
  z: number;
}

export interface QuaternionXYZW {
  x: number;
  y: number;
  z: number;
  w: number;
}

export interface TcpPose {
  frame: string;
  position_mm: Vector3;
  orientation_quaternion_xyzw: QuaternionXYZW;
}

export interface JointStatePayload {
  positions: Record<string, number>;
  units: Record<string, DomainUnit>;
}

export interface ForwardKinematicsResponse {
  robot_id: string;
  variant: RobotVariant;
  tcp_pose: TcpPose;
  state_sequence: number;
  profile_fingerprint: string;
  kinematics_fingerprint: string;
  hardware_accessed: false;
}

export interface MotionRequestContext {
  source: 'CONTROL';
  expected_state_sequence: number;
  expected_profile_fingerprint: string;
  expected_kinematics_fingerprint: string;
  speed_scale: number;
  idempotency_key: string;
}

export interface MoveJointsRequest extends MotionRequestContext {
  joint_state: JointStatePayload;
  duration_s: number;
}

export interface JointJogStepRequest extends MotionRequestContext {
  joint_id: string;
  delta: number;
  unit: DomainUnit;
  duration_s: number;
}

export interface JogSessionStartRequest extends MotionRequestContext {
  joint_id: string;
  direction: -1 | 1;
  speed_units_s: number;
  unit: DomainUnit;
}

export interface CartesianJogRequest extends MotionRequestContext {
  frame: CartesianFrame;
  delta_position_mm: Vector3;
  delta_rotation_deg: Vector3;
  translation_unit: 'mm';
  rotation_unit: 'deg';
  duration_s: number;
}

export interface MovePoseRequest extends MotionRequestContext {
  target_pose: TcpPose;
  position_unit: 'mm';
  orientation_unit: 'quaternion_xyzw';
  duration_s: number;
}

export interface HomeRequest extends MotionRequestContext {
  confirm: 'HOME';
  duration_s: number;
}

export interface InverseKinematicsRequest {
  target_pose: TcpPose;
  position_unit: 'mm';
  orientation_unit: 'quaternion_xyzw';
  seed_joint_state?: JointStatePayload;
  position_only: boolean;
  maximum_iterations: number;
}

export interface InverseKinematicsResponse {
  success: boolean;
  joint_state_optional: JointStatePayload | null;
  best_joint_state: JointStatePayload | null;
  iterations: number;
  position_error_mm: number;
  orientation_error_deg: number | null;
  termination_reason: string;
  warnings: string[];
  kinematics_fingerprint?: string;
}

export interface PreflightViolation {
  code: string;
  message: string;
  field?: string | null;
  severity?: 'ERROR' | 'WARNING';
}

export interface MotionPreflightReport {
  accepted: boolean;
  command_id?: string;
  checks: Array<{ name: string; passed: boolean; detail: string }>;
  warnings: string[];
  profile_fingerprint?: string;
  kinematics_fingerprint?: string;
  violations?: PreflightViolation[];
}

export type MotionCommandState =
  | 'ACCEPTED'
  | 'PREFLIGHTING'
  | 'READY'
  | 'RUNNING'
  | 'PLAYING'
  | 'PAUSED'
  | 'STOPPING'
  | 'STOPPED'
  | 'CANCELLED'
  | 'COMPLETED'
  | 'FAULTED'
  | 'REJECTED';

export interface MotionCommandStatus {
  command_id: string;
  state: MotionCommandState;
  source?: string;
  progress?: number;
  message?: string | null;
  error?: string | null;
  preflight?: MotionPreflightReport | null;
  started_at?: string | null;
  updated_at?: string;
  finished_at?: string | null;
  hardware_accessed?: false;
}

export interface MotionCommandSubmission {
  command_id: string;
  command: MotionCommandStatus;
  preflight?: MotionPreflightReport | null;
  hardware_accessed?: false;
}

export interface JogSessionResponse {
  jog_session_id: string;
  command_id: string;
  lease_expires_in_ms: number;
  status: MotionCommandState;
}

export interface MotionStopResponse {
  result: 'STOPPED' | 'NOT_CONNECTED' | 'FAILED' | 'SAFETY_STATE_UNCERTAIN';
  status: RobotStatus;
  hardware_accessed: false;
}

export type RobotWebSocketState = 'disabled' | 'connecting' | 'open' | 'closed' | 'unsupported';

export interface RobotSocketSnapshot {
  robot: RobotStatus | null;
  tcpPose: TcpPose | null;
  stateSequence: number | null;
  command: MotionCommandStatus | null;
}
