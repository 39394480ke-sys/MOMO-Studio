import { Copy, MoreHorizontal, Pencil, Trash2, TriangleAlert } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import type { PoseSummary } from '../../api/types';
import {
  poseLegacyCompatibility,
  type LibraryCompatibilityContract,
} from './legacyCompatibility';
import { ResourceSimulationThumbnail } from './ResourceSimulationThumbnail';

interface PoseCardProps {
  pose: PoseSummary;
  busy: boolean;
  selected: boolean;
  deletePending: boolean;
  onDeleteCancel: () => void;
  onDeleteConfirm: (pose: PoseSummary) => void;
  onDeleteRequest: (pose: PoseSummary) => void;
  onDuplicate: (pose: PoseSummary) => void;
  onRename: (pose: PoseSummary) => void;
  onSelect: (pose: PoseSummary) => void;
  onTagSelect: (tag: string) => void;
  compatibilityContract: LibraryCompatibilityContract | null;
}

function number(value: number): string {
  return Number.isFinite(value) ? value.toFixed(1) : '—';
}

export function PoseCard({
  pose,
  busy,
  selected,
  deletePending,
  onDeleteCancel,
  onDeleteConfirm,
  onDeleteRequest,
  onDuplicate,
  onRename,
  onSelect,
  onTagSelect,
  compatibilityContract,
}: PoseCardProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const titleId = `pose-title-${pose.id}`;
  const position = pose.tcp_pose.position_mm;
  const compatibility = poseLegacyCompatibility(pose, compatibilityContract);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const close = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false);
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', escape);
    };
  }, [menuOpen]);

  return (
    <article
      aria-labelledby={titleId}
      className={selected ? 'library-card library-card--selected' : 'library-card'}
      data-resource-id={pose.id}
    >
      <button
        aria-label={`打开机位详情 · ${pose.name}`}
        aria-pressed={selected}
        className="library-card__select"
        onClick={() => onSelect(pose)}
        type="button"
      >
        <div className="library-card__visual">
          <ResourceSimulationThumbnail
            label={`${pose.name} 真实姿态仿真缩略图`}
            pose={pose}
          />
          <span>{pose.robot_variant} · {Object.keys(pose.joint_state.positions).length} 关节</span>
        </div>
        <div className="library-card__copy">
          <div>
            <h3 id={titleId}>{pose.name}</h3>
            <p>机位 · {pose.robot_variant}</p>
          </div>
          <small>
            X {number(position.x)} · Y {number(position.y)} · Z {number(position.z)} mm
          </small>
          {compatibility ? (
            <span
              className={`library-legacy-status library-legacy-status--${compatibility.state}`}
              title={compatibility.detail}
            >
              <TriangleAlert aria-hidden="true" />
              {compatibility.summary}
            </span>
          ) : null}
        </div>
      </button>

      <div className="library-card__footer">
        <div aria-label={`${pose.name} 的标签`} className="entity-tags">
          {pose.tags.length > 0 ? pose.tags.slice(0, 2).map((tag) => (
            <button key={tag} onClick={() => onTagSelect(tag)} type="button">{tag}</button>
          )) : <span>POSE</span>}
        </div>
        <div className="resource-more" ref={menuRef}>
          <button
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            aria-label={`更多操作 · ${pose.name}`}
            className="resource-more__trigger"
            disabled={busy}
            onClick={() => setMenuOpen((open) => !open)}
            type="button"
          >
            <MoreHorizontal aria-hidden="true" />
          </button>
          {menuOpen ? (
            <div aria-label={`${pose.name} 管理操作`} className="resource-more__menu" role="menu">
              {deletePending ? (
                <div className="resource-more__confirmation" role="alertdialog" aria-label={`删除“${pose.name}”？`}>
                  <strong>删除这个机位？</strong>
                  <span>运动中的内嵌快照不会改变。</span>
                  <div>
                    <button onClick={onDeleteCancel} type="button">取消</button>
                    <button className="is-danger" onClick={() => onDeleteConfirm(pose)} type="button">确认删除</button>
                  </div>
                </div>
              ) : (
                <>
                  <button onClick={() => { setMenuOpen(false); onRename(pose); }} role="menuitem" type="button"><Pencil aria-hidden="true" />重命名</button>
                  <button onClick={() => { setMenuOpen(false); onDuplicate(pose); }} role="menuitem" type="button"><Copy aria-hidden="true" />复制</button>
                  <button className="is-danger" onClick={() => onDeleteRequest(pose)} role="menuitem" type="button"><Trash2 aria-hidden="true" />删除</button>
                </>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </article>
  );
}
