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
          <span className="entity-kind">Pose · {pose.robot_variant}</span>
          <h3 id={titleId}>{pose.name}</h3>
        </div>
        <span className="entity-revision">rev {pose.revision}</span>
      </header>

      {pose.description ? <p className="library-card__description">{pose.description}</p> : null}

      <dl className="entity-facts">
        <div>
          <dt>Captured</dt>
          <dd>{formatEntityDate(pose.created_at)}</dd>
        </div>
        <div>
          <dt>TCP · {pose.tcp_pose.frame}</dt>
          <dd>
            X {number(position.x)} · Y {number(position.y)} · Z {number(position.z)} mm
          </dd>
        </div>
        <div className="entity-facts__wide">
          <dt>Joints</dt>
          <dd className="entity-joints">
            {joints.map(([jointId, value]) => (
              <span key={jointId}>
                {jointId.toUpperCase()} {number(value)} {pose.joint_state.units[jointId]}
              </span>
            ))}
          </dd>
        </div>
      </dl>

      <div aria-label={`${pose.name} tags`} className="entity-tags">
        {pose.tags.length > 0 ? (
          pose.tags.map((tag) => (
            <button key={tag} onClick={() => onTagSelect(tag)} type="button">
              {tag}
            </button>
          ))
        ) : (
          <span>No tags</span>
        )}
      </div>

      <code className="entity-id" title={pose.id}>ID {pose.id}</code>

      <div className="library-card__actions">
        <button className="command-button" disabled={busy} onClick={() => onView(pose)} type="button">
          View details
        </button>
        <button
          className="command-button command-button--primary"
          disabled={busy || gotoDisabledReason !== null}
          onClick={() => onGotoRequest(pose)}
          title={gotoDisabledReason ?? 'Send this snapshot through the Dry Run safety gateway'}
          type="button"
        >
          <Navigation aria-hidden="true" />
          Goto
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
          Add to Studio
        </Link>
        <button
          className="command-button"
          disabled={busy}
          onClick={() => onDuplicate(pose)}
          type="button"
        >
          <Copy aria-hidden="true" />
          Duplicate
        </button>
        <button
          className="command-button command-button--danger"
          disabled={busy}
          onClick={() => onDeleteRequest(pose)}
          type="button"
        >
          <Trash2 aria-hidden="true" />
          Delete
        </button>
      </div>

      {gotoDisabledReason ? <p className="stage-boundary-note">Goto unavailable · {gotoDisabledReason}</p> : null}

      {gotoPending ? (
        <div aria-labelledby={`goto-pose-${pose.id}`} className="goto-confirmation" role="alertdialog">
          <strong id={`goto-pose-${pose.id}`}>Goto “{pose.name}”?</strong>
          <p>
            Submit a Joint Motion through the single Dry Run safety gateway. This does not enable real motion.
          </p>
          <div>
            <button className="command-button" disabled={busy} onClick={onGotoCancel} type="button">
              Cancel
            </button>
            <button
              className="command-button command-button--primary"
              disabled={busy}
              onClick={() => onGotoConfirm(pose)}
              type="button"
            >
              Confirm Dry Run Goto
            </button>
          </div>
        </div>
      ) : null}

      {deletePending ? (
        <div aria-labelledby={`delete-pose-${pose.id}`} className="delete-confirmation" role="alertdialog">
          <strong id={`delete-pose-${pose.id}`}>Delete “{pose.name}”?</strong>
          <p>Existing motions keep their embedded snapshots. This named Pose will be removed.</p>
          <div>
            <button className="command-button" disabled={busy} onClick={onDeleteCancel} type="button">
              Cancel
            </button>
            <button
              className="command-button command-button--danger-solid"
              disabled={busy}
              onClick={() => onDeleteConfirm(pose)}
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
