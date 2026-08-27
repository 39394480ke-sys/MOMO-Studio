import { Copy, Navigation, Plus, Trash2 } from 'lucide-react';
import { Link } from 'react-router-dom';

import type { PoseSummary } from '../../api/types';
import { formatEntityDate } from './libraryFormat';

interface PoseCardProps {
  pose: PoseSummary;
  busy: boolean;
  deletePending: boolean;
  gotoDisabledReason: string | null;
  gotoPending: boolean;
  runtimeMode: 'DRY RUN' | 'REAL';
  onDeleteCancel: () => void;
  onDeleteConfirm: (pose: PoseSummary) => void;
  onDeleteRequest: (pose: PoseSummary) => void;
  onDuplicate: (pose: PoseSummary) => void;
  onGotoCancel: () => void;
  onGotoConfirm: (pose: PoseSummary) => void;
  onGotoRequest: (pose: PoseSummary) => void;
  onView: (pose: PoseSummary) => void;
  onTagSelect: (tag: string) => void;
}

function number(value: number): string {
  return Number.isFinite(value) ? value.toFixed(1) : '—';
}

export function PoseCard({
  pose,
  busy,
  deletePending,
  gotoDisabledReason,
  gotoPending,
  runtimeMode,
  onDeleteCancel,
  onDeleteConfirm,
  onDeleteRequest,
  onDuplicate,
  onGotoCancel,
  onGotoConfirm,
  onGotoRequest,
  onTagSelect,
  onView,
}: PoseCardProps) {
  const titleId = `pose-title-${pose.id}`;
  const position = pose.tcp_pose.position_mm;
  const joints = Object.entries(pose.joint_state.positions);

  return (
    <article aria-labelledby={titleId} className="library-card library-card--pose">
      <header className="library-card__header">
        <div>
          <span className="entity-kind">机位 · {pose.robot_variant}</span>
          <h3 id={titleId}>{pose.name}</h3>
        </div>
        <span className="entity-revision">版本 {pose.revision}</span>
      </header>

      {pose.description ? <p className="library-card__description">{pose.description}</p> : null}

      <dl className="entity-facts">
        <div>
          <dt>捕获时间</dt>
          <dd>{formatEntityDate(pose.created_at)}</dd>
        </div>
        <div>
          <dt>TCP · {pose.tcp_pose.frame}</dt>
          <dd>
            X {number(position.x)} · Y {number(position.y)} · Z {number(position.z)} mm
          </dd>
        </div>
        <div className="entity-facts__wide">
          <dt>关节</dt>
          <dd className="entity-joints">
            {joints.map(([jointId, value]) => (
              <span key={jointId}>
                {jointId.toUpperCase()} {number(value)} {pose.joint_state.units[jointId]}
              </span>
            ))}
          </dd>
        </div>
      </dl>

      <div aria-label={`${pose.name} 的标签`} className="entity-tags">
        {pose.tags.length > 0 ? (
          pose.tags.map((tag) => (
            <button key={tag} onClick={() => onTagSelect(tag)} type="button">
              {tag}
            </button>
          ))
        ) : (
          <span>无标签</span>
        )}
      </div>

      <code className="entity-id" title={pose.id}>ID {pose.id}</code>

      <div className="library-card__actions">
        <button className="command-button" disabled={busy} onClick={() => onView(pose)} type="button">
          查看详情
        </button>
        <button
          className="command-button command-button--primary"
          disabled={busy || gotoDisabledReason !== null}
          onClick={() => onGotoRequest(pose)}
          title={gotoDisabledReason ?? `通过已审核的${runtimeMode === 'REAL' ? '真机能力' : '仿真'}入口提交此快照`}
          type="button"
        >
          <Navigation aria-hidden="true" />
          前往
        </button>
        <Link
          aria-disabled={busy}
          className="command-button"
          onClick={(event) => {
            if (busy) event.preventDefault();
          }}
          tabIndex={busy ? -1 : undefined}
          to={`/studio?pose=${encodeURIComponent(pose.id)}`}
        >
          <Plus aria-hidden="true" />
          添加到编排
        </Link>
        <button
          className="command-button"
          disabled={busy}
          onClick={() => onDuplicate(pose)}
          type="button"
        >
          <Copy aria-hidden="true" />
          复制
        </button>
        <button
          className="command-button command-button--danger"
          disabled={busy}
          onClick={() => onDeleteRequest(pose)}
          type="button"
        >
          <Trash2 aria-hidden="true" />
          删除
        </button>
      </div>

      {gotoDisabledReason ? <p className="stage-boundary-note">暂时无法前往 · {gotoDisabledReason}</p> : null}

      {gotoPending ? (
        <div aria-labelledby={`goto-pose-${pose.id}`} className="goto-confirmation" role="alertdialog">
          <strong id={`goto-pose-${pose.id}`}>前往“{pose.name}”？</strong>
          <p>
            {runtimeMode === 'REAL'
              ? '通过后端授权的真机关节运动入口提交关节运动。'
              : '通过唯一的仿真安全入口提交关节运动；不会启用实体硬件。'}
          </p>
          <div>
            <button className="command-button" disabled={busy} onClick={onGotoCancel} type="button">
              取消
            </button>
            <button
              className="command-button command-button--primary"
              disabled={busy}
              onClick={() => onGotoConfirm(pose)}
              type="button"
            >
              确认{runtimeMode === 'REAL' ? '真机' : '仿真'}前往
            </button>
          </div>
        </div>
      ) : null}

      {deletePending ? (
        <div aria-labelledby={`delete-pose-${pose.id}`} className="delete-confirmation" role="alertdialog">
          <strong id={`delete-pose-${pose.id}`}>删除“{pose.name}”？</strong>
          <p>已有运动会保留其内嵌快照；这里只删除这个命名机位。</p>
          <div>
            <button className="command-button" disabled={busy} onClick={onDeleteCancel} type="button">
              取消
            </button>
            <button
              className="command-button command-button--danger-solid"
              disabled={busy}
              onClick={() => onDeleteConfirm(pose)}
              type="button"
            >
              确认删除
            </button>
          </div>
        </div>
      ) : null}
    </article>
  );
}
