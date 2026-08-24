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
  control_mode: 'DRY_RUN' | 'REAL';
  hardware_access_policy: 'DISABLED' | 'READ_ONLY' | 'FULL';
  real_motion_enabled: boolean;
}

export interface MetaResponse {
  product: string;
  version: string;
  api_version: 'v1';
  stage: ProductStage;
  active_robot_variant: RobotVariant;
  supported_robot_variants: RobotVariant[];
  supported_control_modes: Array<'DRY_RUN' | 'REAL'>;
  active_control_mode: 'DRY_RUN' | 'REAL';
  hardware_access_policy: 'DISABLED' | 'READ_ONLY' | 'FULL';
  real_motion_enabled: boolean;
  release_status: 'FIELD_ACCEPTANCE_REQUIRED';
  dry_run_validated: true;
  real_hardware_field_acceptance: 'PENDING';
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
  kinematics_fingerprint: string;
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

export type EntitySortField = 'created_at' | 'updated_at' | 'name';
export type SortOrder = 'asc' | 'desc';

export interface EntityListQuery {
  page: number;
  page_size: number;
  search?: string;
  tags?: string[];
  sort: EntitySortField;
  order: SortOrder;
}

export interface EntityPage<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

export interface PoseSnapshot {
  robot_variant: RobotVariant;
  joint_state: JointStatePayload;
  tcp_pose: TcpPose;
  profile_fingerprint: string;
  kinematics_fingerprint: string;
  state_sequence: number | null;
  hardware_snapshot: Record<string, unknown> | null;
  calibration_fingerprint: string | null;
  captured_at: string;
}

export interface PoseSummary {
  id: string;
  name: string;
  description: string;
  tags: string[];
  robot_variant: RobotVariant;
  joint_state: JointStatePayload;
  tcp_pose: TcpPose;
  profile_fingerprint: string;
  kinematics_fingerprint: string;
  state_sequence: number | null;
  created_at: string;
  updated_at: string;
  revision: number;
}

export interface PoseEntity extends Omit<
  PoseSummary,
  | 'robot_variant'
  | 'joint_state'
  | 'tcp_pose'
  | 'profile_fingerprint'
  | 'kinematics_fingerprint'
  | 'state_sequence'
> {
  schema_version: '2.0.0';
  snapshot: PoseSnapshot;
}

export interface CreatePoseRequest {
  name: string;
  description?: string;
  tags?: string[];
  snapshot: PoseSnapshot;
}

export interface CapturePoseRequest {
  name: string;
  description?: string;
  tags?: string[];
}

export interface UpdatePoseRequest {
  expected_revision: number;
  name?: string;
  description?: string;
  tags?: string[];
}

export interface DuplicateEntityRequest {
  expected_revision: number;
  name?: string;
}

export interface GotoPoseRequest {
  expected_revision: number;
  duration_s?: number;
  speed_scale?: number;
  idempotency_key: string;
}

export type MotionMode = 'JOINT' | 'CARTESIAN_LINEAR';
export type MotionEasing = 'LINEAR' | 'SMOOTHSTEP' | 'EASE_IN_OUT';

export interface MotionTransition {
  duration_s: number;
  motion_mode: MotionMode;
  easing: MotionEasing;
}

export interface MotionKeyframe {
  id: string;
  label: string;
  pose_snapshot: PoseSnapshot;
  source_pose_id: string | null;
  hold_s: number;
  incoming_transition: MotionTransition | null;
}

export interface MotionPlaybackDefaults {
  loop: boolean;
  speed_multiplier: number;
}

export interface LegacyImportMetadata {
  importer: 'momo.tools.import_legacy_actions';
  source_file_name: string;
  source_sha256: string;
  legacy_id: string | null;
  legacy_source: string | null;
  warnings: string[];
}

export interface MotionSummary {
  id: string;
  name: string;
  description: string;
  robot_variant: RobotVariant;
  keyframe_count: number;
  total_duration_s: number;
  motion_types: MotionMode[];
  tags: string[];
  created_at: string;
  updated_at: string;
  revision: number;
}

export interface MotionEntity extends Omit<MotionSummary, 'keyframe_count' | 'total_duration_s' | 'motion_types'> {
  schema_version: '2.0.0';
  keyframes: MotionKeyframe[];
  playback_defaults: MotionPlaybackDefaults;
  /** Importer-owned sanitized provenance; clients must never submit it. */
  source_metadata: LegacyImportMetadata | null;
}

export interface MotionDraftEditorMetadata {
  selected_keyframe_id: string | null;
  playhead_s: number;
  timeline_zoom: number;
  timeline_scroll_s: number;
  default_edges: Array<{
    from_keyframe_id: string;
    to_keyframe_id: string;
  }>;
}

export interface MotionDraftSaveIntent {
  operation_id: string;
  kind: 'SAVE' | 'SAVE_AS';
  target_motion_id: string;
  target_motion_revision: number;
  expected_motion_revision: number | null;
  target_name: string;
  target_motion_created_at: string;
  started_at: string;
}

export interface MotionDraft {
  schema_version: '1.0.0';
  id: string;
  source_motion_id: string | null;
  source_motion_revision: number | null;
  name: string;
  description: string;
  robot_variant: RobotVariant;
  keyframes: MotionKeyframe[];
  playback_defaults: MotionPlaybackDefaults;
  tags: string[];
  /** Importer-owned sanitized provenance; clients must never submit it. */
  source_metadata: LegacyImportMetadata | null;
  /** Backend-owned trust registry for embedded Legacy snapshots; clients must never submit it. */
  trusted_legacy_snapshot_sha256: string[];
  editor_metadata: MotionDraftEditorMetadata;
  /** Backend-owned write-ahead recovery marker; clients must never submit it. */
  save_intent: MotionDraftSaveIntent | null;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface MotionDraftSummary {
  id: string;
  source_motion_id: string | null;
  source_motion_revision: number | null;
  name: string;
  robot_variant: RobotVariant;
  keyframe_count: number;
  created_at: string;
  updated_at: string;
  revision: number;
}

export interface CreateMotionDraftRequest {
  name: string;
  description?: string;
  robot_variant: RobotVariant;
  keyframes?: MotionKeyframe[];
  playback_defaults?: MotionPlaybackDefaults;
  tags?: string[];
  editor_metadata?: MotionDraftEditorMetadata;
}

export interface UpdateMotionDraftRequest {
  expected_revision: number;
  name: string;
  description: string;
  robot_variant: RobotVariant;
  keyframes: MotionKeyframe[];
  playback_defaults: MotionPlaybackDefaults;
  tags: string[];
  editor_metadata: MotionDraftEditorMetadata;
}

export interface ForkMotionDraftRequest {
  expected_revision: number;
}

export interface AbandonMotionDraftSaveIntentRequest {
  expected_revision: number;
  operation_id: string;
  confirm: 'ABANDON_FORMAL_SAVE';
}

export interface MotionDraftIssue {
  code: string;
  message: string;
}

export interface MotionDraftValidation {
  draft_id: string;
  draft_revision: number;
  valid: boolean;
  issues: MotionDraftIssue[];
}

export interface CompileMotionDraftRequest {
  expected_revision: number;
  sample_rate_hz?: number;
}

export interface MotionDraftCompileResponse {
  draft_id: string;
  draft_revision: number;
  preflight: TrajectoryPreflightReport;
  preview: TrajectoryPreview | null;
  executable: false;
}

export interface SaveMotionDraftRequest {
  expected_revision: number;
  expected_source_revision?: number | null;
  sample_rate_hz?: number;
}

export interface SaveAsMotionDraftRequest {
  expected_revision: number;
  name?: string;
  sample_rate_hz?: number;
}

export interface GotoMotionDraftKeyframeRequest {
  expected_revision: number;
  duration_s: number;
  speed_scale: number;
  idempotency_key: string;
}

export interface MotionDraftSaveResponse {
  draft: MotionDraft;
  motion: MotionEntity;
  preflight: TrajectoryPreflightReport;
}

export interface CreateMotionKeyframeRequest {
  label: string;
  pose_snapshot: PoseSnapshot;
  source_pose_id?: string | null;
  hold_s?: number;
  incoming_transition: MotionTransition | null;
}

export interface CreateMotionRequest {
  name: string;
  description?: string;
  robot_variant: RobotVariant;
  keyframes: CreateMotionKeyframeRequest[];
  playback_defaults?: MotionPlaybackDefaults;
  tags?: string[];
}

export interface UpdateMotionRequest {
  expected_revision: number;
  name?: string;
  description?: string;
  robot_variant?: RobotVariant;
  keyframes?: CreateMotionKeyframeRequest[];
  tags?: string[];
  playback_defaults?: MotionPlaybackDefaults;
}

export interface PreflightMotionRequest {
  expected_revision: number;
  sample_rate_hz?: number;
}

export interface TrajectoryViolation {
  code: string;
  message: string;
  segment_index?: number | null;
  keyframe_id?: string | null;
  check?: string | null;
  sample_index?: number | null;
  joint_id?: string | null;
  actual?: number | null;
  limit?: number | null;
  unit?: DomainUnit | null;
  blocking?: boolean;
}

export interface TrajectoryCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface TrajectoryPreflightReport {
  passed: boolean;
  digest: string | null;
  motion_id: string;
  motion_revision: number;
  duration_s: number;
  sample_count: number;
  segment_count: number;
  sample_rate_hz: number;
  violations: TrajectoryViolation[];
  checks: TrajectoryCheck[];
  prepared_at?: string | null;
}

export interface PlayMotionRequest {
  expected_revision: number;
  trajectory_digest: string;
  loop: boolean;
  rate: number;
}

export type PlaybackState =
  | 'IDLE'
  | 'PREFLIGHTING'
  | 'READY'
  | 'PLAYING'
  | 'PAUSED'
  | 'STOPPING'
  | 'STOPPED'
  | 'COMPLETED'
  | 'FAULTED';

export interface PlaybackStatus {
  session_id?: string | null;
  state: PlaybackState;
  motion_id?: string | null;
  trajectory_digest?: string | null;
  progress: number;
  elapsed_s: number;
  duration_s: number;
  current_keyframe_id?: string | null;
  current_segment_index?: number | null;
  current_sample_index?: number | null;
  loop: boolean;
  rate: number;
  error?: string | null;
  updated_at: string;
  hardware_accessed: false;
}

export type TrajectorySegmentMode = MotionMode | 'HOLD';

export interface TrajectoryPreviewSegment {
  segment_index: number;
  motion_mode: TrajectorySegmentMode;
  start_time_s: number;
  end_time_s: number;
  sample_count: number;
  start_keyframe_id?: string | null;
  end_keyframe_id?: string | null;
}

export interface JointTrajectoryPoint {
  time_s: number;
  value: number;
  unit: DomainUnit;
}

export interface TcpTrajectoryPoint {
  time_s: number;
  x_mm: number;
  y_mm: number;
  z_mm: number;
}

export interface TrajectoryKeyframeMarker {
  keyframe_id: string;
  label: string;
  time_s: number;
  sample_index: number;
}

export interface TrajectoryPreview {
  digest: string;
  motion_id: string;
  duration_s: number;
  sample_rate_hz: number;
  sample_count: number;
  segments: TrajectoryPreviewSegment[];
  joint_series: Record<string, JointTrajectoryPoint[]>;
  tcp_path: TcpTrajectoryPoint[];
  keyframe_markers: TrajectoryKeyframeMarker[];
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

export type CameraAccessPolicy = 'DISABLED' | 'SYNTHETIC_ONLY' | 'LIVE_CAMERA_ALLOWED';

export interface NormalizedBoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface VisionFrameMetadata {
  frame_id: string;
  width_px: number;
  height_px: number;
  captured_at: string;
  source_id: string;
  age_ms: number;
}

export interface VisionProviderCapability {
  provider_id: string;
  kind: string;
  available: boolean;
  active: boolean;
  model_source: string;
  notice: string;
  reason: string | null;
}

export interface VisionCapabilities {
  camera_access_policy: CameraAccessPolicy;
  source: VisionProviderCapability;
  trackers: VisionProviderCapability[];
  detectors: VisionProviderCapability[];
  stream: VisionProviderCapability;
  real_follow_allowed: false;
  real_follow_blocked_reason: string;
}

export interface VisionTargetSelection {
  frame_id: string;
  bounding_box: NormalizedBoundingBox;
}

export type VisionTrackingState = 'LOCKED' | 'LOST' | 'STALE' | 'FAULTED';

export interface VisionTrackingResult {
  frame_id: string;
  source_id: string;
  captured_at: string;
  bounding_box: NormalizedBoundingBox | null;
  confidence: number;
  status: VisionTrackingState;
  error: string | null;
}

export interface VisionFollowStatus {
  active: boolean;
  lease_id: string | null;
  expires_at: string | null;
  stop_reason: string | null;
  error_x: number | null;
  error_y: number | null;
  ema_error_x: number | null;
  ema_error_y: number | null;
  last_command_id: string | null;
}

export interface VisionStatus {
  camera_access_policy: CameraAccessPolicy;
  source_state: string;
  latest_frame: VisionFrameMetadata | null;
  selection: VisionTargetSelection | null;
  tracking: VisionTrackingResult | null;
  follow: VisionFollowStatus;
  robot_state: string;
  dry_run: true;
  real_follow_blocked_reason: string;
}

export interface VisionDetection {
  detection_id: string;
  frame_id: string;
  source_id: string;
  captured_at: string;
  bounding_box: NormalizedBoundingBox;
  confidence: number;
  label: string;
}

export interface VisionDetectionResponse {
  capability: VisionProviderCapability;
  detections: VisionDetection[];
}

export interface VisionFollowConfiguration {
  dead_zone_x: number;
  dead_zone_y: number;
  ema_alpha: number;
  gain: number;
  max_step: number;
  max_rate: number;
  confidence_threshold: number;
  frame_freshness_limit_s: number;
  target_lost_limit_s: number;
  lease_ttl_s: number;
}

export interface VisionFollowMapping {
  pan_joint: string;
  tilt_joint: string;
  pan_sign: -1 | 1;
  tilt_sign: -1 | 1;
  verification_status: 'VERIFIED_FOR_DRY_RUN';
}

export interface StartVisionFollowRequest {
  configuration: VisionFollowConfiguration;
  mapping: VisionFollowMapping;
}

export interface VisionFollowLeaseResponse {
  lease_id: string;
  expires_at: string;
  status: VisionStatus;
}

export interface DeviceConfirmationEvidence {
  robot_id: string | null;
  variant: RobotVariant | null;
  profile_fingerprint: string | null;
  calibration_fingerprint: string | null;
  kinematics_fingerprint: string | null;
  masked_serial_port: string | null;
  masked_servo_ids: string[];
  protocol: string | null;
  physical_estop_required: true;
  required_confirmation_text: string;
}

export interface DeviceSessionSummary {
  active: boolean;
  session_id: string;
  expires_at: string;
}

export interface DeviceCapabilityReadiness {
  real_joint_motion_ready: boolean;
  real_cartesian_motion_ready: boolean;
  real_playback_ready: boolean;
  real_vision_follow_ready: boolean;
}

export interface DeviceReadiness {
  state: string;
  ready: boolean;
  session_authorizable: boolean;
  blocking_reasons: string[];
  capabilities: DeviceCapabilityReadiness;
  confirmation: DeviceConfirmationEvidence;
  session: DeviceSessionSummary | null;
  connected: boolean;
}

export interface OperatorSessionResponse {
  session_token: string;
  session_id: string;
  issued_at: string;
  expires_at: string;
  evidence: DeviceConfirmationEvidence;
}

export type SecuritySurface = 'REST' | 'CONTROL' | 'WEBSOCKET' | 'VISION';

export interface SecuritySessionResponse {
  principal_id: string;
  issued_at: string;
  expires_at: string;
  surfaces: SecuritySurface[];
}

export interface DeviceDependencyStatus {
  adapter_id: string;
  state: 'AVAILABLE' | 'UNAVAILABLE' | 'PENDING_ADAPTER_VERIFICATION';
  package_name: string | null;
  license_status: string;
  notice: string;
}

export interface DeviceReadinessEvidence {
  configured: boolean;
  fingerprint: string | null;
  verification_status: string | null;
  template: boolean | null;
  ready_for_real: boolean;
}

export interface DeviceServoDiagnostic {
  joint_id: string;
  masked_servo_id: string;
  ping_responded: boolean;
  operating_mode: string | null;
  present_raw: number | null;
  logical_value: number | null;
  raw_bounds: [number, number] | null;
  torque_enabled: boolean | null;
}

export interface DeviceDiagnostics {
  connected: boolean;
  captured_at: string;
  dependency: DeviceDependencyStatus;
  hardware_policy: string;
  masked_serial_port: string | null;
  masked_servo_ids: string[];
  protocol: string | null;
  profile: DeviceReadinessEvidence;
  calibration: DeviceReadinessEvidence;
  kinematics: DeviceReadinessEvidence;
  field_acceptance: string;
  readiness: string;
  records: DeviceServoDiagnostic[];
  last_error: string | null;
}

export type RealStopOutcome =
  | 'STOPPED_AND_VERIFIED'
  | 'HOLD_REQUESTED'
  | 'TORQUE_DISABLE_REQUESTED'
  | 'NOT_CONNECTED'
  | 'FAILED'
  | 'SAFETY_STATE_UNCERTAIN';

export interface DeviceStopResponse {
  result: RealStopOutcome;
  physical_estop_required: boolean;
  detail: string;
}

export type CalibrationWorkflowState =
  | 'ACTIVE'
  | 'READY_TO_SAVE'
  | 'SAVED'
  | 'CANCELLED'
  | 'EXPIRED';

export interface CalibrationJointPreview {
  session_id: string;
  joint_id: string;
  servo_id: number;
  observed_raw: number;
  logical_value: number;
  unit: DomainUnit;
  operating_mode: string;
  direction: -1 | 1;
  home_present_raw: number;
  phase: number | null;
  raw_bounds: [number, number];
  round_trip_logical_value: number;
  mapping_error: number;
  preview_fingerprint: string;
}

export interface CalibrationAggregateJoint {
  joint_id: string;
  servo_id: number;
  operating_mode: string;
  direction: -1 | 1;
  home_present_raw: number;
  phase: number | null;
  raw_bounds: [number, number];
}

export interface CalibrationSavePreview {
  session_id: string;
  base_revision: number;
  base_calibration_fingerprint: string;
  proposed_calibration_fingerprint: string;
  joints: CalibrationAggregateJoint[];
}

export interface CalibrationWorkflowStatus {
  session_id: string;
  robot_id: string;
  variant: RobotVariant;
  profile_fingerprint: string;
  base_revision: number;
  base_calibration_fingerprint: string;
  state: CalibrationWorkflowState;
  required_joint_ids: string[];
  confirmed_joint_ids: string[];
  selected_joint_id: string | null;
  observed_raw: number | null;
  preview: CalibrationJointPreview | null;
  save_preview: CalibrationSavePreview | null;
  saved_revision: number | null;
  saved_calibration_fingerprint: string | null;
  updated_at: string;
}

export interface CalibrationRevisionSummary {
  revision: number;
  calibration_fingerprint: string;
  previous_calibration_fingerprint: string | null;
  variant: RobotVariant;
  created_at: string;
}
