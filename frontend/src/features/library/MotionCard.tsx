import { Copy, MoreHorizontal, Pencil, Trash2, TriangleAlert } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { getMotion } from '../../api/client';
import type { MotionEntity, MotionSummary } from '../../api/types';
import {
  motionLegacyCompatibility,
  type LibraryCompatibilityContract,
} from './legacyCompatibility';
import { ResourceSimulationThumbnail } from './ResourceSimulationThumbnail';

const previewCache = new Map<string, MotionEntity>();

interface MotionCardProps {
  motion: MotionSummary;
  busy: boolean;
  selected: boolean;
  deletePending: boolean;
  onDeleteCancel: () => void;
  onDeleteConfirm: (motion: MotionSummary) => void;
  onDeleteRequest: (motion: MotionSummary) => void;
  onDuplicate: (motion: MotionSummary) => void;
  onRename: (motion: MotionSummary) => void;
  onSelect: (motion: MotionSummary) => void;
  onTagSelect: (tag: string) => void;
  compatibilityContract: LibraryCompatibilityContract | null;
}

export function MotionCard({
  motion,
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
}: MotionCardProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const cacheKey = `${motion.id}:${motion.revision}`;
  const [preview, setPreview] = useState<MotionEntity | null>(() => previewCache.get(cacheKey) ?? null);
  const [previewState, setPreviewState] = useState<'idle' | 'loading' | 'error'>(preview ? 'idle' : 'loading');
  const cardRef = useRef<HTMLElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const titleId = `motion-title-${motion.id}`;
  const compatibility = motionLegacyCompatibility(motion, preview, compatibilityContract);

  useEffect(() => {
    if (previewCache.has(cacheKey)) return undefined;
    const host = cardRef.current;
    if (!host || typeof IntersectionObserver === 'undefined') {
      setPreviewState('error');
      return undefined;
    }
    const controller = new AbortController();
    let disposed = false;
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      setPreviewState('loading');
      void getMotion(motion.id, controller.signal)
        .then((entity) => {
          if (disposed) return;
          previewCache.set(cacheKey, entity);
          setPreview(entity);
          setPreviewState('idle');
        })
        .catch(() => {
          if (!disposed && !controller.signal.aborted) setPreviewState('error');
        });
    }, { rootMargin: '160px' });
    observer.observe(host);
    return () => {
      disposed = true;
      controller.abort();
      observer.disconnect();
    };
  }, [cacheKey, motion.id]);

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
      data-resource-id={motion.id}
      ref={cardRef}
    >
      <button
        aria-label={`打开动作详情 · ${motion.name}`}
        aria-pressed={selected}
        className="library-card__select"
        onClick={() => onSelect(motion)}
        type="button"
      >
        <div className="library-card__visual">
          <ResourceSimulationThumbnail
            label={`${motion.name} 真实动作仿真缩略图`}
            loading={previewState === 'loading'}
            motion={preview}
            unavailable={previewState === 'error'}
          />
          <span>{motion.keyframe_count} 帧 · {motion.total_duration_s.toFixed(1)} s</span>
        </div>
        <div className="library-card__copy">
          <div>
            <h3 id={titleId}>{motion.name}</h3>
            <p>运动 · {motion.robot_variant}</p>
          </div>
          <small>{motion.motion_types.length > 0 ? motion.motion_types.join(' · ') : 'HOLD'}</small>
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
        <div aria-label={`${motion.name} 的标签`} className="entity-tags">
          {motion.tags.length > 0 ? motion.tags.slice(0, 2).map((tag) => (
            <button key={tag} onClick={() => onTagSelect(tag)} type="button">{tag}</button>
          )) : <span>MOTION</span>}
        </div>
        <div className="resource-more" ref={menuRef}>
          <button
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            aria-label={`更多操作 · ${motion.name}`}
            className="resource-more__trigger"
            disabled={busy}
            onClick={() => setMenuOpen((open) => !open)}
            type="button"
          >
            <MoreHorizontal aria-hidden="true" />
          </button>
          {menuOpen ? (
            <div aria-label={`${motion.name} 管理操作`} className="resource-more__menu" role="menu">
              {deletePending ? (
                <div className="resource-more__confirmation" role="alertdialog" aria-label={`删除“${motion.name}”？`}>
                  <strong>删除这个动作？</strong>
                  <span>来源机位不会被删除。</span>
                  <div>
                    <button onClick={onDeleteCancel} type="button">取消</button>
                    <button className="is-danger" onClick={() => onDeleteConfirm(motion)} type="button">确认删除</button>
                  </div>
                </div>
              ) : (
                <>
                  <button onClick={() => { setMenuOpen(false); onRename(motion); }} role="menuitem" type="button"><Pencil aria-hidden="true" />重命名</button>
                  <button onClick={() => { setMenuOpen(false); onDuplicate(motion); }} role="menuitem" type="button"><Copy aria-hidden="true" />复制</button>
                  <button className="is-danger" onClick={() => onDeleteRequest(motion)} role="menuitem" type="button"><Trash2 aria-hidden="true" />删除</button>
                </>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </article>
  );
}
