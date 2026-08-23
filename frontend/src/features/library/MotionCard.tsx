import { Copy, ExternalLink, Play, Trash2 } from 'lucide-react';
import { Link } from 'react-router-dom';

import type { MotionSummary } from '../../api/types';
import { formatEntityDate } from './libraryFormat';

interface MotionCardProps {
  motion: MotionSummary;
  busy: boolean;
  deletePending: boolean;
  onDeleteCancel: () => void;
  onDeleteConfirm: (motion: MotionSummary) => void;
  onDeleteRequest: (motion: MotionSummary) => void;
  onDuplicate: (motion: MotionSummary) => void;
  onTagSelect: (tag: string) => void;
  onView: (motion: MotionSummary) => void;
}

export function MotionCard({
  motion,
  busy,
  deletePending,
  onDeleteCancel,
  onDeleteConfirm,
  onDeleteRequest,
  onDuplicate,
  onTagSelect,
  onView,
}: MotionCardProps) {
  const titleId = `motion-title-${motion.id}`;

  return (
    <article aria-labelledby={titleId} className="library-card library-card--motion">
      <header className="library-card__header">
        <div>
          <span className="entity-kind">Motion · {motion.robot_variant}</span>
          <h3 id={titleId}>{motion.name}</h3>
        </div>
        <span className="entity-revision">rev {motion.revision}</span>
      </header>

      {motion.description ? <p className="library-card__description">{motion.description}</p> : null}

      <dl className="entity-facts entity-facts--motion">
        <div>
          <dt>Created</dt>
          <dd>{formatEntityDate(motion.created_at)}</dd>
        </div>
        <div>
          <dt>Keyframes</dt>
          <dd>{motion.keyframe_count}</dd>
        </div>
        <div>
          <dt>Total duration</dt>
          <dd>{motion.total_duration_s.toFixed(2)} s</dd>
        </div>
        <div>
          <dt>Motion type</dt>
          <dd>{motion.motion_types.length > 0 ? motion.motion_types.join(' · ') : 'No transitions'}</dd>
        </div>
      </dl>

      <div aria-label={`${motion.name} tags`} className="entity-tags">
        {motion.tags.length > 0 ? (
          motion.tags.map((tag) => (
            <button key={tag} onClick={() => onTagSelect(tag)} type="button">
              {tag}
            </button>
          ))
        ) : (
          <span>No tags</span>
        )}
      </div>

      <code className="entity-id" title={motion.id}>ID {motion.id}</code>

      <div className="library-card__actions">
        <button className="command-button" disabled={busy} onClick={() => onView(motion)} type="button">
          View details
        </button>
        <Link className="command-button command-button--primary" to={`/studio?motion=${encodeURIComponent(motion.id)}`}>
          <ExternalLink aria-hidden="true" />
          Open in Studio
        </Link>
        <button
          aria-describedby={`play-stage-${motion.id}`}
          className="command-button"
          disabled
          type="button"
        >
          <Play aria-hidden="true" />
          Play
        </button>
        <span className="visually-hidden" id={`play-stage-${motion.id}`}>
          Playback becomes available in Stage 5
        </span>
        <button
          className="command-button"
          disabled={busy}
          onClick={() => onDuplicate(motion)}
          type="button"
        >
          <Copy aria-hidden="true" />
          Duplicate
        </button>
        <button
          className="command-button command-button--danger"
          disabled={busy}
          onClick={() => onDeleteRequest(motion)}
          type="button"
        >
          <Trash2 aria-hidden="true" />
          Delete
        </button>
      </div>
      <p className="stage-boundary-note">Play is unavailable until Stage 5.</p>

      {deletePending ? (
        <div aria-labelledby={`delete-motion-${motion.id}`} className="delete-confirmation" role="alertdialog">
          <strong id={`delete-motion-${motion.id}`}>Delete “{motion.name}”?</strong>
          <p>This removes the stored Motion. It does not delete any source Pose.</p>
          <div>
            <button className="command-button" disabled={busy} onClick={onDeleteCancel} type="button">
              Cancel
            </button>
            <button
              className="command-button command-button--danger-solid"
              disabled={busy}
              onClick={() => onDeleteConfirm(motion)}
              type="button"
            >
              Confirm delete
            </button>
          </div>
        </div>
      ) : null}
    </article>
  );
}
