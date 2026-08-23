export type RobotVariant = 'V1' | 'V2';
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
  stage: 2;
  control_mode: 'DRY_RUN';
  hardware_access_policy: 'DISABLED';
  real_motion_enabled: false;
}

export interface MetaResponse {
  product: string;
  version: string;
  api_version: 'v1';
  stage: 2;
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
  units: Record<string, 'mm' | 'deg'>;
  raw_positions: Record<string, number> | null;
  last_error: string | null;
  updated_at: string;
  state_sequence: number;
  hardware_accessed: false;
  stale?: boolean;
}

export interface ProfileJointDefinition {
  joint_id: string;
  joint_type: 'REVOLUTE' | 'PRISMATIC';
  domain_unit: 'mm' | 'deg';
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
  real_readiness: 'BLOCKED_BY_STAGE_POLICY' | 'READY';
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
  stage_policy: 'STAGE_2_DRY_RUN_ONLY';
  active_profile_fingerprint: string;
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
