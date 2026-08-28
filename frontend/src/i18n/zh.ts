const STATUS_LABELS: Record<string, string> = {
  ACCEPTED: '已接受',
  ACTIVE: '运行中',
  AVAILABLE: '可用',
  AUTHORIZED: '已授权',
  BLOCKED: '已阻止',
  BLOCKED_BY_STAGE_POLICY: '受阶段策略限制',
  COMMISSIONING: '现场验收',
  COMPLETED: '已完成',
  CONFIGURED: '已配置',
  CONNECTED: '已连接',
  CLOSED: '已关闭',
  DISABLED: '已禁用',
  DISCONNECTED: '未连接',
  DRY_RUN: '仿真运行',
  DRY_RUN_ONLY: '仅仿真运行',
  DRAFT: '草稿',
  ENABLED: '已启用',
  FAILED: '失败',
  FULL: '完整权限',
  IDLE: '空闲',
  LIVE: '实时相机',
  LIVE_CAMERA_ALLOWED: '允许实时相机',
  LOADING: '加载中',
  LOCKED: '已锁定',
  LOST: '目标丢失',
  INVALID: '无效',
  NOT_AUTHORIZED: '未授权',
  NOT_BOUND: '未绑定',
  NOT_CONFIGURED: '未配置',
  OFFLINE: '离线',
  PAUSED: '已暂停',
  PASSED: '已通过',
  PENDING: '待处理',
  POLICY_PENDING: '策略待定',
  PLAYING: '播放中',
  PREFLIGHTING: '预检中',
  READ_ONLY: '只读',
  READY: '已就绪',
  REAL: '真实硬件',
  REJECTED: '已拒绝',
  REST: '静止',
  RUNNING: '运行中',
  SOURCE_DISABLED: '图像源已禁用',
  STALE: '已过期',
  STALE_LEGACY_EVIDENCE: '旧版证据已过期',
  STOPPED: '已停止',
  STOPPING: '停止中',
  STREAMING: '视频流中',
  SYNTHETIC: '合成画面',
  SYNTHETIC_ONLY: '仅合成画面',
  TEMPLATE_ONLY: '仅模板',
  UNAVAILABLE: '不可用',
  VALID: '有效',
  VERIFIED: '已验证',
  VERIFIED_FOR_DRY_RUN: '已通过仿真验证',
};

const MESSAGE_LABELS: Record<string, string> = {
  'Backend unavailable': '后端不可用',
  'No saved runtime state': '没有已保存的运行状态',
  'No saved runtime state; using profile Home values': '没有已保存的运行状态，当前使用配置中的 Home 值',
  'Runtime state loaded and validated': '运行状态已加载并验证',
  'Stage 3 hardware access policy is DISABLED': 'Stage 3 实体硬件访问策略已禁用',
  'Template calibration cannot authorize real hardware': '模板标定不能授权真实硬件',
  'Waiting for backend diagnostics': '正在等待后端诊断',
};

/** Translate product-facing status values while keeping unknown protocol values intact. */
export function zhStatus(value: string | null | undefined, fallback = '待加载'): string {
  if (!value) return fallback;
  return STATUS_LABELS[value] ?? value;
}

/** Translate known backend explanations without hiding an unfamiliar diagnostic. */
export function zhBackendMessage(value: string | null | undefined, fallback = '暂无信息'): string {
  if (!value) return fallback;
  return MESSAGE_LABELS[value] ?? value
    .replace('Required evidence:', '需要验收证据：')
    .replace('is unavailable', '不可用')
    .replace('is disabled', '已禁用');
}

export function zhBoolean(value: boolean | null | undefined): string {
  if (value === true) return '是';
  if (value === false) return '否';
  return '未配置';
}
