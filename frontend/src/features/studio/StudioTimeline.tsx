import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type KeyboardEvent,
  type PointerEvent,
} from 'react';
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  CirclePlus,
  Copy,
  GripVertical,
  Trash2,
} from 'lucide-react';

import type { MotionKeyframe } from '../../api/types';
import {
  clampTransitionDuration,
  timelineData,
  timeFromTrackPointer,
} from './studioTimelineMath';

interface StudioTimelineProps {
  disabled: boolean;
  defaultEdgeIds: ReadonlySet<string>;
  frameLimitReached: boolean;
  frames: MotionKeyframe[];
  initialScrollS: number;
  runtimeMode: 'DRY RUN' | 'REAL';
  playheadS: number;
  selectedFrameId: string | null;
  zoom: number;
  onAddAfter: (frameId: string | null) => void;
  onAddBefore: (frameId: string | null) => void;
  onDelete: (frameId: string) => void;
  onDuplicate: (frameId: string) => void;
  onMove: (frameId: string, direction: -1 | 1) => void;
  onPlayheadChange: (timeS: number) => void;
  onReorder: (frameId: string, targetIndex: number) => void;
  onScrollChange: (scrollS: number) => void;
  onSelect: (frameId: string) => void;
  onTransitionDurationChange: (frameId: string, durationS: number) => void;
  onZoomChange: (zoom: number) => void;
}

function edgeId(from: string, to: string): string {
  return `${from}->${to}`;
}

function markerLeft(time: number, duration: number): string {
  if (duration <= 0) return '84px';
  const ratio = Math.min(1, Math.max(0, time / duration));
  return `calc(84px + ${ratio * 100}% - ${ratio * 168}px)`;
}

export function StudioTimeline({
  disabled,
  defaultEdgeIds,
  frameLimitReached,
  frames,
  initialScrollS,
  runtimeMode,
  playheadS,
  selectedFrameId,
  zoom,
  onAddAfter,
  onAddBefore,
  onDelete,
  onDuplicate,
  onMove,
  onPlayheadChange,
  onReorder,
  onScrollChange,
  onSelect,
  onTransitionDurationChange,
  onZoomChange,
}: StudioTimelineProps) {
  const [draggedFrameId, setDraggedFrameId] = useState<string | null>(null);
  const [durationDraft, setDurationDraft] = useState<{ frameId: string; value: number } | null>(null);
  const durationDragRef = useRef<{
    frameId: string;
    pointerId: number;
    startDuration: number;
    startX: number;
    value: number;
  } | null>(null);
  const playheadPointerRef = useRef<number | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const data = useMemo(() => timelineData(frames), [frames]);
  const totalDuration = Math.max(data.duration, 0.01);
  const trackWidth = Math.max(680, frames.length * 180 * zoom, data.duration * 96 * zoom + 180);
  const selectedIndex = frames.findIndex((frame) => frame.id === selectedFrameId);

  useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    const intended = Math.max(0, initialScrollS * 96 * zoom);
    if (Math.abs(node.scrollLeft - intended) > 2) node.scrollLeft = intended;
  }, [initialScrollS, zoom]);

  const dropAt = (event: DragEvent, targetIndex: number) => {
    event.preventDefault();
    if (!disabled && draggedFrameId) onReorder(draggedFrameId, targetIndex);
    setDraggedFrameId(null);
  };

  const handleFrameKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    frameId: string,
  ) => {
    if (disabled) return;
    if (event.altKey && event.key === 'ArrowLeft') {
      event.preventDefault();
      onMove(frameId, -1);
    } else if (event.altKey && event.key === 'ArrowRight') {
      event.preventDefault();
      onMove(frameId, 1);
    }
  };

  const durationFor = (frameId: string, persisted: number) =>
    durationDraft?.frameId === frameId ? durationDraft.value : persisted;

  const beginDurationDrag = (
    event: PointerEvent<HTMLButtonElement>,
    frameId: string,
    durationS: number,
  ) => {
    if (disabled) return;
    event.preventDefault();
    event.stopPropagation();
    if (typeof event.currentTarget.setPointerCapture === 'function') {
      event.currentTarget.setPointerCapture(event.pointerId);
    }
    const drag = {
      frameId,
      pointerId: event.pointerId,
      startDuration: durationS,
      startX: event.clientX,
      value: durationS,
    };
    durationDragRef.current = drag;
    setDurationDraft({ frameId, value: durationS });
  };

  const updateDurationDrag = (event: PointerEvent<HTMLButtonElement>) => {
    const drag = durationDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    event.preventDefault();
    const pixelsPerSecond = Math.max(24, (trackWidth - 168) / totalDuration);
    const value = clampTransitionDuration(
      drag.startDuration + (event.clientX - drag.startX) / pixelsPerSecond,
    );
    durationDragRef.current = { ...drag, value };
    setDurationDraft({ frameId: drag.frameId, value });
  };

  const finishDurationDrag = (event: PointerEvent<HTMLButtonElement>, commit: boolean) => {
    const drag = durationDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    if (
      typeof event.currentTarget.hasPointerCapture === 'function' &&
      event.currentTarget.hasPointerCapture(event.pointerId) &&
      typeof event.currentTarget.releasePointerCapture === 'function'
    ) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    durationDragRef.current = null;
    setDurationDraft(null);
    if (commit && drag.value !== drag.startDuration) {
      onTransitionDurationChange(drag.frameId, drag.value);
    }
  };

  const setPlayheadFromPointer = (event: PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    onPlayheadChange(timeFromTrackPointer(event.clientX, rect.left, rect.width, totalDuration));
  };

  const beginPlayheadDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (disabled || event.button !== 0) return;
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest('.studio-keyframe, .studio-transition-resize')) return;
    event.preventDefault();
    if (typeof event.currentTarget.setPointerCapture === 'function') {
      event.currentTarget.setPointerCapture(event.pointerId);
    }
    playheadPointerRef.current = event.pointerId;
    setPlayheadFromPointer(event);
  };

  return (
    <section aria-busy={disabled} aria-labelledby="studio-timeline-heading" className="studio-timeline-panel">
      <header className="studio-panel-heading">
        <div>
          <p className="section-kicker">编辑时间轴</p>
          <h2 id="studio-timeline-heading">关键帧与过渡</h2>
        </div>
        <div className="studio-timeline-tools">
          <label>
            <span>缩放</span>
            <input
              aria-label="时间轴缩放"
              disabled={disabled}
              max="8"
              min="0.25"
              onChange={(event) => onZoomChange(Number(event.target.value))}
              step="0.25"
              type="range"
              value={zoom}
            />
            <output>{Math.round(zoom * 100)}%</output>
          </label>
          <span>{data.duration.toFixed(2)} 秒 · {frames.length} 个关键帧</span>
        </div>
      </header>

      <div className="studio-timeline-toolbar">
        <button
          className="command-button"
          disabled={disabled || frames.length === 0 || frameLimitReached}
          onClick={() => onAddBefore(selectedFrameId)}
          title={frameLimitReached
            ? '草稿已达到 1000 个关键帧上限'
            : frames.length === 0 ? '请先捕获或添加第一个关键帧' : '选择一个机位，插入到当前关键帧之前'}
          type="button"
        >
          <ArrowLeft aria-hidden="true" /> 插入到前面
        </button>
        <button className="command-button" disabled={disabled || frameLimitReached} onClick={() => onAddAfter(selectedFrameId)} type="button">
          <CirclePlus aria-hidden="true" /> {frames.length === 0 ? '添加第一个关键帧' : '插入到后面'}
        </button>
        <button
          aria-label="将所选关键帧前移"
          className="mini-command"
          disabled={disabled || selectedIndex <= 0}
          onClick={() => selectedFrameId && onMove(selectedFrameId, -1)}
          title="将所选关键帧前移（Alt + 左方向键）"
          type="button"
        >
          <ChevronLeft aria-hidden="true" />
        </button>
        <button
          aria-label="将所选关键帧后移"
          className="mini-command"
          disabled={disabled || selectedIndex < 0 || selectedIndex >= frames.length - 1}
          onClick={() => selectedFrameId && onMove(selectedFrameId, 1)}
          title="将所选关键帧后移（Alt + 右方向键）"
          type="button"
        >
          <ChevronRight aria-hidden="true" />
        </button>
        <button
          className="command-button"
          disabled={disabled || !selectedFrameId || frameLimitReached}
          onClick={() => selectedFrameId && onDuplicate(selectedFrameId)}
          type="button"
        >
          <Copy aria-hidden="true" /> 复制
        </button>
        <button
          className="command-button command-button--danger"
          disabled={disabled || !selectedFrameId}
          onClick={() => selectedFrameId && onDelete(selectedFrameId)}
          type="button"
        >
          <Trash2 aria-hidden="true" /> 删除
        </button>
      </div>

      {frames.length === 0 ? (
        <div className="studio-timeline-empty">
          <CirclePlus aria-hidden="true" />
          <strong>空白运动草稿</strong>
          <span>捕获当前{runtimeMode === 'REAL' ? '真机' : '仿真'}机械臂状态，或添加已保存的机位以开始编排。</span>
        </div>
      ) : (
        <div
          aria-label="可横向滚动的运动时间轴"
          className="studio-timeline-scroll"
          data-testid="studio-timeline-scroll"
          onScroll={(event) => {
            if (!disabled) onScrollChange(event.currentTarget.scrollLeft / (96 * zoom));
          }}
          ref={scrollRef}
          tabIndex={0}
        >
          <div
            className="studio-timeline-track"
            onPointerCancel={(event) => {
              if (playheadPointerRef.current === event.pointerId) playheadPointerRef.current = null;
            }}
            onPointerDown={beginPlayheadDrag}
            onPointerMove={(event) => {
              if (playheadPointerRef.current === event.pointerId) setPlayheadFromPointer(event);
            }}
            onPointerUp={(event) => {
              if (playheadPointerRef.current !== event.pointerId) return;
              setPlayheadFromPointer(event);
              playheadPointerRef.current = null;
              if (
                typeof event.currentTarget.hasPointerCapture === 'function' &&
                event.currentTarget.hasPointerCapture(event.pointerId) &&
                typeof event.currentTarget.releasePointerCapture === 'function'
              ) {
                event.currentTarget.releasePointerCapture(event.pointerId);
              }
            }}
            style={{ width: `${trackWidth}px` }}
          >
            <div className="studio-time-ruler" aria-hidden="true">
              {Array.from({ length: 9 }, (_, index) => (
                <span key={index} style={{ left: `${4 + index * 11.5}%` }}>
                  {(data.duration * index / 8).toFixed(1)}s
                </span>
              ))}
            </div>

            <button
              aria-label="拖动时间轴播放头"
              className="studio-playhead"
              disabled={disabled}
              style={{ left: markerLeft(Math.min(playheadS, totalDuration), totalDuration) }}
              title={`${Math.min(playheadS, totalDuration).toFixed(2)} 秒`}
              type="button"
            />

            <ol className="studio-keyframe-track">
              {data.markers.map(({ frame, index, time }) => {
                const incoming = frame.incoming_transition;
                const previous = index > 0 ? frames[index - 1] : null;
                const isDefault = Boolean(
                  previous && defaultEdgeIds.has(edgeId(previous.id, frame.id)),
                );
                return (
                  <li
                    className="studio-keyframe-slot"
                    key={frame.id}
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={(event) => dropAt(event, index)}
                    style={{ left: markerLeft(time, totalDuration) }}
                  >
                    {index > 0 && incoming ? (
                      <span
                        className={`studio-segment-chip${isDefault ? ' studio-segment-chip--default' : ''}`}
                        title={isDefault ? '新相邻帧使用编辑器默认过渡' : '保留原有相邻帧过渡'}
                      >
                        <span>
                          {incoming.motion_mode === 'CARTESIAN_LINEAR' ? 'TCP 直线' : '关节'} · {durationFor(frame.id, incoming.duration_s).toFixed(2)} 秒
                          {isDefault ? ' · 默认' : ''}
                        </span>
                        <button
                          aria-label={`调整第 ${index} 段过渡时长`}
                          aria-valuemax={600}
                          aria-valuemin={0.05}
                          aria-valuenow={durationFor(frame.id, incoming.duration_s)}
                          className="studio-transition-resize"
                          disabled={disabled}
                          onKeyDown={(event) => {
                            if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
                            event.preventDefault();
                            const delta = (event.shiftKey ? 0.5 : 0.05) * (event.key === 'ArrowLeft' ? -1 : 1);
                            onTransitionDurationChange(
                              frame.id,
                              clampTransitionDuration(incoming.duration_s + delta),
                            );
                          }}
                          onPointerCancel={(event) => finishDurationDrag(event, false)}
                          onPointerDown={(event) => beginDurationDrag(event, frame.id, incoming.duration_s)}
                          onPointerMove={updateDurationDrag}
                          onPointerUp={(event) => finishDurationDrag(event, true)}
                          title="左右拖动调整时长；方向键微调，Shift + 方向键大步调整"
                          type="button"
                        >
                          <span aria-hidden="true" />
                        </button>
                      </span>
                    ) : null}
                    <button
                      aria-label={`关键帧 ${index + 1}：${frame.label}。按 Alt 加方向键可调整顺序。`}
                      aria-pressed={frame.id === selectedFrameId}
                      className={`studio-keyframe${frame.id === selectedFrameId ? ' studio-keyframe--selected' : ''}`}
                      disabled={disabled}
                      draggable={!disabled}
                      onClick={() => onSelect(frame.id)}
                      onDragEnd={() => setDraggedFrameId(null)}
                      onDragStart={(event) => {
                        if (disabled) return;
                        setDraggedFrameId(frame.id);
                        event.dataTransfer.effectAllowed = 'move';
                        event.dataTransfer.setData('text/plain', frame.id);
                      }}
                      onKeyDown={(event) => handleFrameKeyDown(event, frame.id)}
                      type="button"
                    >
                      <GripVertical aria-hidden="true" />
                      <span>
                        <strong>K{index + 1} · {frame.label}</strong>
                        <small>{time.toFixed(2)} 秒 · 停留 {frame.hold_s.toFixed(2)} 秒</small>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </div>
        </div>
      )}

      <label className="studio-playhead-control">
        <span>播放头</span>
        <input
          aria-label="时间轴播放头"
          disabled={disabled || frames.length === 0}
          max={totalDuration}
          min="0"
          onChange={(event) => onPlayheadChange(Number(event.target.value))}
          step="0.01"
          type="range"
          value={Math.min(playheadS, totalDuration)}
        />
        <output>{Math.min(playheadS, totalDuration).toFixed(2)} s</output>
      </label>

      <p className="studio-keyboard-hint">
        拖动关键帧可以调整顺序；也可以聚焦关键帧后按 Alt + 左/右方向键。只有未改变的相邻帧会保留原过渡，新形成的相邻关系会标记为“默认”。
      </p>
    </section>
  );
}
