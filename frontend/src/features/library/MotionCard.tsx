import { Copy, ExternalLink, Play, Trash2 } from 'lucide-react';
import { Link } from 'react-router-dom';

import type { MotionSummary } from '../../api/types';
import { formatEntityDate } from './libraryFormat';

interface MotionCardProps {
  motion: MotionSummary;
  busy: boolean;
  playBusy: boolean;
  viewBusy: boolean;
  deletePending: boolean;
  onDeleteCancel: () => void;
  onDeleteConfirm: (motion: MotionSummary) => void;
  onDeleteRequest: (motion: MotionSummary) => void;
  onDuplicate: (motion: MotionSummary) => void;
  onPlay: (motion: MotionSummary) => void;
  onTagSelect: (tag: string) => void;
  onView: (motion: MotionSummary) => void;
  playDisabledReason: string | null;
}

export function MotionCard({
  motion,
  busy,
  playBusy,
  viewBusy,
  deletePending,
  onDeleteCancel,
  onDeleteConfirm,
  onDeleteRequest,
  onDuplicate,
  onPlay,
  onTagSelect,
  onView,
  playDisabledReason,
}: MotionCardProps) {
  const titleId = `motion-title-${motion.id}`;

  return (
    <article aria-labelledby={titleId} className="library-card library-card--motion">
      <header className="library-card__header">
        <div>
          <span className="entity-kind">运动 · {motion.robot_variant}</span>
          <h3 id={titleId}>{motion.name}</h3>
        </div>
        <span className="entity-revision">版本 {motion.revision}</span>
      </header>

      {motion.description ? <p className="library-card__description">{motion.description}</p> : null}

      <dl className="entity-facts entity-facts--motion">
        <div>
          <dt>创建时间</dt>
          <dd>{formatEntityDate(motion.created_at)}</dd>
        </div>
        <div>
          <dt>关键帧</dt>
          <dd>{motion.keyframe_count}</dd>
        </div>
        <div>
          <dt>总时长</dt>
          <dd>{motion.total_duration_s.toFixed(2)} 秒</dd>
        </div>
        <div>
          <dt>运动类型</dt>
          <dd>{motion.motion_types.length > 0 ? motion.motion_types.join(' · ') : '无过渡'}</dd>
        </div>
      </dl>

      <div aria-label={`${motion.name} 的标签`} className="entity-tags">
        {motion.tags.length > 0 ? (
          motion.tags.map((tag) => (
            <button key={tag} onClick={() => onTagSelect(tag)} type="button">
              {tag}
            </button>
          ))
        ) : (
          <span>无标签</span>
        )}
      </div>

      <code className="entity-id" title={motion.id}>ID {motion.id}</code>

      <div className="library-card__actions">
        <button className="command-button" disabled={viewBusy} onClick={() => onView(motion)} type="button">
          查看详情
        </button>
        <Link
          aria-disabled={busy}
          className="command-button command-button--primary"
          onClick={(event) => {
            if (busy) event.preventDefault();
          }}
          tabIndex={busy ? -1 : undefined}
          to={`/studio?motion=${encodeURIComponent(motion.id)}`}
        >
          <ExternalLink aria-hidden="true" />
          在编排中打开
        </Link>
        <button
          aria-describedby={playDisabledReason ? `play-reason-${motion.id}` : undefined}
          className="command-button"
          disabled={playBusy || playDisabledReason !== null}
          onClick={() => onPlay(motion)}
          title={playDisabledReason ?? '打开此运动的播放流程'}
          type="button"
        >
          <Play aria-hidden="true" />
          播放
        </button>
        {playDisabledReason ? (
          <span className="visually-hidden" id={`play-reason-${motion.id}`}>
            播放不可用：{playDisabledReason}
          </span>
        ) : null}
        <button
          className="command-button"
          disabled={busy}
          onClick={() => onDuplicate(motion)}
          type="button"
        >
          <Copy aria-hidden="true" />
          复制
        </button>
        <button
          className="command-button command-button--danger"
          disabled={busy}
          onClick={() => onDeleteRequest(motion)}
          type="button"
        >
          <Trash2 aria-hidden="true" />
          删除
        </button>
      </div>
      {playDisabledReason ? <p className="stage-boundary-note">暂时无法播放 · {playDisabledReason}</p> : null}

      {deletePending ? (
        <div aria-labelledby={`delete-motion-${motion.id}`} className="delete-confirmation" role="alertdialog">
          <strong id={`delete-motion-${motion.id}`}>删除“{motion.name}”？</strong>
          <p>这会删除已保存的运动，但不会删除任何来源机位。</p>
          <div>
            <button className="command-button" disabled={busy} onClick={onDeleteCancel} type="button">
              取消
            </button>
            <button
              className="command-button command-button--danger-solid"
              disabled={busy}
              onClick={() => onDeleteConfirm(motion)}
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
