import { ApiError } from '../../api/client';
import type { RobotVariant } from '../../api/types';

export interface StudioKeyframeCompatibilityIssue {
  readonly keyframeId: string;
  readonly keyframeIndex: number;
  readonly keyframeName: string;
  readonly sourcePoseId: string | null;
  readonly checks: readonly string[];
  readonly expectedJointIds: readonly string[];
  readonly actualJointIds: readonly string[];
  readonly missingJointIds: readonly string[];
  readonly extraJointIds: readonly string[];
  readonly expectedUnits: Readonly<Record<string, string>>;
  readonly actualUnits: Readonly<Record<string, string>>;
  readonly expectedProfileFingerprint: string;
  readonly actualProfileFingerprint: string;
  readonly expectedKinematicsFingerprint: string;
  readonly actualKinematicsFingerprint: string;
  readonly tcpMismatch: boolean;
  readonly stateSequenceIssue: boolean;
  readonly provenanceIssue: boolean;
}

export interface StudioCompatibilityIssue {
  readonly errorCode: 'STUDIO_DRAFT_CONTRACT_INCOMPATIBLE';
  readonly draftVariant: RobotVariant;
  readonly activeVariant: RobotVariant;
  readonly checks: readonly string[];
  readonly keyframes: readonly StudioKeyframeCompatibilityIssue[];
}

const CHECK_LABELS: Readonly<Record<string, string>> = {
  robot_variant: '机械臂型号不匹配',
  profile_fingerprint: 'Profile 配置指纹不匹配',
  kinematics_fingerprint: '运动学模型指纹不匹配',
  missing_joint_ids: '缺少启用关节',
  extra_joint_ids: '包含额外关节',
  joint_units: '关节单位不匹配',
  joint_state: '关节状态不符合当前合同',
  tcp_pose: 'TCP 与关节状态重算结果不一致',
  state_sequence: '状态序列缺失或不受信任',
  hardware_snapshot_must_be_null: '包含客户端不可提交的硬件来源数据',
  calibration_fingerprint_must_be_null: '包含客户端不可提交的标定来源数据',
};

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function variant(value: unknown): RobotVariant | null {
  return value === 'V1' || value === 'V2' ? value : null;
}

function strings(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string')) return null;
  return value as string[];
}

function stringRecord(value: unknown): Record<string, string> | null {
  const parsed = record(value);
  if (!parsed || Object.values(parsed).some((item) => typeof item !== 'string')) return null;
  return parsed as Record<string, string>;
}

function keyframeIssue(value: unknown): StudioKeyframeCompatibilityIssue | null {
  const item = record(value);
  if (!item) return null;
  const checks = strings(item.checks);
  const expectedJointIds = strings(item.expected_joint_ids);
  const actualJointIds = strings(item.actual_joint_ids);
  const missingJointIds = strings(item.missing_joint_ids);
  const extraJointIds = strings(item.extra_joint_ids);
  const expectedUnits = stringRecord(item.expected_units);
  const actualUnits = stringRecord(item.actual_units);
  if (
    typeof item.keyframe_id !== 'string'
    || typeof item.keyframe_index !== 'number'
    || !Number.isInteger(item.keyframe_index)
    || item.keyframe_index < 0
    || typeof item.keyframe_name !== 'string'
    || (item.source_pose_id !== null && typeof item.source_pose_id !== 'string')
    || checks === null
    || expectedJointIds === null
    || actualJointIds === null
    || missingJointIds === null
    || extraJointIds === null
    || expectedUnits === null
    || actualUnits === null
    || typeof item.expected_profile_fingerprint !== 'string'
    || typeof item.actual_profile_fingerprint !== 'string'
    || typeof item.expected_kinematics_fingerprint !== 'string'
    || typeof item.actual_kinematics_fingerprint !== 'string'
    || typeof item.tcp_mismatch !== 'boolean'
    || typeof item.state_sequence_issue !== 'boolean'
    || typeof item.provenance_issue !== 'boolean'
  ) return null;
  return {
    keyframeId: item.keyframe_id,
    keyframeIndex: item.keyframe_index,
    keyframeName: item.keyframe_name || `关键帧 ${item.keyframe_index + 1}`,
    sourcePoseId: item.source_pose_id,
    checks,
    expectedJointIds,
    actualJointIds,
    missingJointIds,
    extraJointIds,
    expectedUnits,
    actualUnits,
    expectedProfileFingerprint: item.expected_profile_fingerprint,
    actualProfileFingerprint: item.actual_profile_fingerprint,
    expectedKinematicsFingerprint: item.expected_kinematics_fingerprint,
    actualKinematicsFingerprint: item.actual_kinematics_fingerprint,
    tcpMismatch: item.tcp_mismatch,
    stateSequenceIssue: item.state_sequence_issue,
    provenanceIssue: item.provenance_issue,
  };
}

export function studioCompatibilityIssue(error: unknown): StudioCompatibilityIssue | null {
  if (!(error instanceof ApiError) || error.status !== 422 || error.code !== 'POSE_INCOMPATIBLE') {
    return null;
  }
  const details = record(error.details);
  const draftVariant = variant(details?.draft_variant);
  const activeVariant = variant(details?.active_variant);
  const checks = strings(details?.checks);
  const keyframes = Array.isArray(details?.keyframes)
    ? details.keyframes.map(keyframeIssue)
    : [];
  if (
    details?.error_code !== 'STUDIO_DRAFT_CONTRACT_INCOMPATIBLE'
    || draftVariant === null
    || activeVariant === null
    || checks === null
    || keyframes.length === 0
    || keyframes.some((item) => item === null)
  ) return null;
  return {
    errorCode: details.error_code,
    draftVariant,
    activeVariant,
    checks,
    keyframes: keyframes as StudioKeyframeCompatibilityIssue[],
  };
}

export function studioCompatibilityCheckLabel(check: string): string {
  return CHECK_LABELS[check] ?? check;
}
