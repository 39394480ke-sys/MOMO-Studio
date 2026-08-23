export interface HealthResponse {
  status: string;
  product: string;
  version: string;
  control_mode: string;
  real_motion_enabled: boolean;
}

export interface MetaResponse {
  product: string;
  version: string;
  api_version: 'v1';
  stage: 1;
  active_robot_variant: 'V1' | 'V2';
  supported_robot_variants: Array<'V1' | 'V2'>;
  supported_control_modes: Array<'DRY_RUN' | 'REAL'>;
  real_motion_enabled: false;
}

export interface BootstrapResponse {
  health: HealthResponse;
  meta: MetaResponse;
}
