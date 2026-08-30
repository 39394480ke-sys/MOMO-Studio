import { AlertTriangle, Camera, FolderOpen, Trash2, X } from 'lucide-react';

import {
  studioCompatibilityCheckLabel,
  type StudioCompatibilityIssue,
  type StudioKeyframeCompatibilityIssue,
} from './studioCompatibility';

interface StudioCompatibilityNoticeProps {
  readonly issue: StudioCompatibilityIssue;
  readonly busy: boolean;
  readonly canSwitchVariant: boolean;
  readonly frameCount: number;
  readonly frameIds: ReadonlySet<string>;
  readonly onCaptureReplace: (frameId: string) => void;
  readonly onDelete: (frameId: string) => void;
  readonly onDismiss: () => void;
  readonly onDiscardDraft: () => void;
  readonly onReplaceFromLibrary: (frameId: string) => void;
  readonly onSelect: (frameId: string) => void;
  readonly onSwitchVariant: () => void;
}

function issueSummary(issue: StudioKeyframeCompatibilityIssue): string {
  const labels = issue.checks.map(studioCompatibilityCheckLabel);
  if (issue.missingJointIds.length > 0) {
    labels.push(`缺少 ${issue.missingJointIds.join('、')}`);
  }
  if (issue.extraJointIds.length > 0) {
    labels.push(`多出 ${issue.extraJointIds.join('、')}`);
  }
  return [...new Set(labels)].join('；');
}

export function StudioCompatibilityNotice({
  issue,
  busy,
  canSwitchVariant,
  frameCount,
  frameIds,
  onCaptureReplace,
  onDelete,
  onDismiss,
  onDiscardDraft,
  onReplaceFromLibrary,
  onSelect,
  onSwitchVariant,
}: StudioCompatibilityNoticeProps) {
  return (
    <section
      aria-labelledby="studio-compatibility-heading"
      className="studio-compatibility-notice"
      role="alert"
    >
      <header className="studio-compatibility-notice__header">
        <AlertTriangle aria-hidden="true" />
        <div>
          <h2 id="studio-compatibility-heading">该动作与当前机械臂配置不兼容</h2>
          <p>
            部分关键帧无法通过当前 MOMO {issue.activeVariant} 的姿态合同校验，
            因此暂时不能进行仿真预览或播放。
          </p>
        </div>
        <button
          aria-label="关闭兼容性提示"
          className="mini-command"
          onClick={onDismiss}
          type="button"
        >
          <X aria-hidden="true" />
        </button>
      </header>

      <ol className="studio-compatibility-notice__keyframes">
        {issue.keyframes.map((keyframe) => {
          const exists = frameIds.has(keyframe.keyframeId);
          const canDelete = exists && frameCount > 2;
          return (
            <li key={keyframe.keyframeId}>
              <button
                className="studio-compatibility-notice__select"
                disabled={!exists}
                onClick={() => onSelect(keyframe.keyframeId)}
                type="button"
              >
                <strong>
                  关键帧 {keyframe.keyframeIndex + 1} · {keyframe.keyframeName}
                </strong>
                <span>{issueSummary(keyframe)}</span>
              </button>
              <div className="studio-compatibility-notice__frame-actions">
                <button
                  className="command-button"
                  disabled={busy || !exists}
                  onClick={() => onReplaceFromLibrary(keyframe.keyframeId)}
                  type="button"
                >
                  <FolderOpen aria-hidden="true" /> 从资产库替换
                </button>
                <button
                  className="command-button"
                  disabled={busy || !exists}
                  onClick={() => onCaptureReplace(keyframe.keyframeId)}
                  type="button"
                >
                  <Camera aria-hidden="true" /> 捕获当前姿态替换
                </button>
                <button
                  className="command-button command-button--danger"
                  disabled={busy || !canDelete}
                  onClick={() => onDelete(keyframe.keyframeId)}
                  title={canDelete ? '删除该问题关键帧' : '可播放运动至少保留两个关键帧'}
                  type="button"
                >
                  <Trash2 aria-hidden="true" /> 删除该关键帧
                </button>
              </div>
            </li>
          );
        })}
      </ol>

      <footer className="studio-compatibility-notice__footer">
        {issue.activeVariant !== issue.draftVariant ? (
          <button
            className="command-button"
            disabled={busy || !canSwitchVariant}
            onClick={onSwitchVariant}
            title={canSwitchVariant
              ? `切换到草稿匹配的 ${issue.draftVariant}`
              : '仅可在 DRY RUN、机械臂断开且没有生命周期操作时切换型号'}
            type="button"
          >
            切换到 {issue.draftVariant}
          </button>
        ) : null}
        <button
          className="command-button"
          disabled
          title="当前没有经过审查的确定性关节与单位转换规则，不能自动迁移"
          type="button"
        >
          创建兼容副本
        </button>
        <span>尚无确定转换规则；系统不会补零、删关节或替换指纹。</span>
        <button
          className="command-button command-button--danger"
          disabled={busy}
          onClick={onDiscardDraft}
          type="button"
        >
          放弃当前草稿
        </button>
      </footer>
    </section>
  );
}
