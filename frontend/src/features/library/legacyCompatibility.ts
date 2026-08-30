import type {
  DomainUnit,
  MotionEntity,
  MotionSummary,
  PoseSnapshot,
  PoseSummary,
  RobotVariant,
} from '../../api/types';

export interface LibraryCompatibilityContract {
  variant: RobotVariant;
  enabledJointIds: string[];
  jointUnits: Record<string, DomainUnit>;
  profileFingerprint: string;
  kinematicsFingerprint: string;
}

export interface LegacyCompatibilityStatus {
  state: 'compatible' | 'incompatible' | 'unverified';
  summary: string;
  detail: string;
}

type SnapshotContract = Pick<
  PoseSnapshot,
  | 'robot_variant'
  | 'joint_state'
  | 'profile_fingerprint'
  | 'kinematics_fingerprint'
>;

const RECOVERY = '不会自动换算；请打开详情，在 Studio 中替换关键帧，或切换到匹配的机械臂配置。';

function snapshotIssues(
  snapshot: SnapshotContract,
  contract: LibraryCompatibilityContract,
): string[] {
  const issues: string[] = [];
  if (snapshot.robot_variant !== contract.variant) {
    issues.push(`型号应为 ${contract.variant}，实际为 ${snapshot.robot_variant}`);
  }

  const actualJointIds = Object.keys(snapshot.joint_state.positions).sort();
  const expectedJointIds = [...contract.enabledJointIds].sort();
  const missing = expectedJointIds.filter((jointId) => !actualJointIds.includes(jointId));
  const extra = actualJointIds.filter((jointId) => !expectedJointIds.includes(jointId));
  if (missing.length > 0) issues.push(`缺少关节 ${missing.join('、')}`);
  if (extra.length > 0) issues.push(`多余关节 ${extra.join('、')}`);

  for (const jointId of expectedJointIds) {
    const expectedUnit = contract.jointUnits[jointId];
    const actualUnit = snapshot.joint_state.units[jointId];
    if (expectedUnit && actualUnit !== expectedUnit) {
      issues.push(`${jointId} 单位应为 ${expectedUnit}，实际为 ${actualUnit ?? '缺失'}`);
    }
  }
  if (snapshot.profile_fingerprint !== contract.profileFingerprint) {
    issues.push('Profile 指纹不匹配');
  }
  if (snapshot.kinematics_fingerprint !== contract.kinematicsFingerprint) {
    issues.push('运动学指纹不匹配');
  }
  return issues;
}

function statusFromIssues(issues: string[]): LegacyCompatibilityStatus {
  if (issues.length === 0) {
    return {
      state: 'compatible',
      summary: 'Legacy 导入 · 列表合同匹配',
      detail: '当前可见的型号、关节、单位与指纹匹配；执行前仍须通过后端安全预检。',
    };
  }
  return {
    state: 'incompatible',
    summary: `Legacy 导入 · 当前配置不兼容：${issues.join('；')}`,
    detail: RECOVERY,
  };
}

export function poseLegacyCompatibility(
  pose: PoseSummary,
  contract: LibraryCompatibilityContract | null,
): LegacyCompatibilityStatus | null {
  if (!pose.tags.includes('legacy-import') && pose.state_sequence !== null) return null;
  if (!contract) {
    return {
      state: 'unverified',
      summary: 'Legacy 导入 · 当前配置尚未验证',
      detail: `当前 Profile 不可用。${RECOVERY}`,
    };
  }
  return statusFromIssues(snapshotIssues({
    robot_variant: pose.robot_variant,
    joint_state: pose.joint_state,
    profile_fingerprint: pose.profile_fingerprint,
    kinematics_fingerprint: pose.kinematics_fingerprint,
  }, contract));
}

export function motionLegacyCompatibility(
  motion: MotionSummary,
  entity: MotionEntity | null,
  contract: LibraryCompatibilityContract | null,
): LegacyCompatibilityStatus | null {
  const legacy = motion.tags.includes('legacy-import')
    || entity?.source_metadata !== null && entity?.source_metadata !== undefined
    || entity?.keyframes.some((frame) => frame.pose_snapshot.state_sequence === null) === true;
  if (!legacy) return null;
  if (!entity) {
    return {
      state: 'unverified',
      summary: 'Legacy 导入 · 等待关键帧合同验证',
      detail: '动作列表摘要不含关键帧指纹；打开详情后才会读取不可变快照并验证，不会猜测或自动换算。',
    };
  }
  if (!contract) {
    return {
      state: 'unverified',
      summary: 'Legacy 导入 · 当前配置尚未验证',
      detail: `当前 Profile 不可用。${RECOVERY}`,
    };
  }

  const incompatibleFrames = entity.keyframes.flatMap((frame, index) => {
    const issues = snapshotIssues(frame.pose_snapshot, contract);
    return issues.length > 0 ? [`关键帧 ${index + 1}（${frame.label}）：${issues.join('、')}`] : [];
  });
  return statusFromIssues(incompatibleFrames);
}
