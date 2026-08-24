import { useEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent } from 'react';
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

interface TimelineMarker {
  frame: MotionKeyframe;
  index: number;
  time: number;
}

interface TimelineSegment {
  duration: number;
  from: MotionKeyframe;
  to: MotionKeyframe;
  isDefault: boolean;
  mode: string;
}

interface StudioTimelineProps {
  disabled: boolean;
  defaultEdgeIds: ReadonlySet<string>;
  frameLimitReached: boolean;
  frames: MotionKeyframe[];
  initialScrollS: number;
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
  onZoomChange: (zoom: number) => void;
}

function edgeId(from: string, to: string): string {
  return `${from}->${to}`;
}

function timelineData(frames: MotionKeyframe[]): {
  duration: number;
  markers: TimelineMarker[];
  segments: TimelineSegment[];
} {
  let cursor = 0;
  const markers: TimelineMarker[] = [];
  const segments: TimelineSegment[] = [];
  frames.forEach((frame, index) => {
    if (index > 0) {
      const previous = frames[index - 1];
      const transition = frame.incoming_transition;
      if (previous && transition) {
        segments.push({
          duration: transition.duration_s,
          from: previous,
          to: frame,
          isDefault: false,
          mode: transition.motion_mode,
        });
        cursor += transition.duration_s;
      }
    }
    markers.push({ frame, index, time: cursor });
    cursor += frame.hold_s;
  });
  return { duration: cursor, markers, segments };
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
  onZoomChange,
}: StudioTimelineProps) {
  const [draggedFrameId, setDraggedFrameId] = useState<string | null>(null);
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

  return (
    <section aria-busy={disabled} aria-labelledby="studio-timeline-heading" className="studio-timeline-panel">
      <header className="studio-panel-heading">
        <div>
          <p className="section-kicker">Editor timeline</p>
          <h2 id="studio-timeline-heading">Keyframes & transitions</h2>
        </div>
        <div className="studio-timeline-tools">
          <label>
            <span>Zoom</span>
            <input
              aria-label="Timeline zoom"
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
          <span>{data.duration.toFixed(2)} s · {frames.length} keyframes</span>
        </div>
      </header>

      <div className="studio-timeline-toolbar">
        <button
          className="command-button"
          disabled={disabled || frames.length === 0 || frameLimitReached}
          onClick={() => onAddBefore(selectedFrameId)}
          title={frameLimitReached
            ? 'The draft has reached the 1000-keyframe limit'
            : frames.length === 0 ? 'Capture or add the first keyframe first' : 'Choose a Pose to insert before the selection'}
          type="button"
        >
          <ArrowLeft aria-hidden="true" /> Add before
        </button>
        <button className="command-button" disabled={disabled || frameLimitReached} onClick={() => onAddAfter(selectedFrameId)} type="button">
          <CirclePlus aria-hidden="true" /> Add {frames.length === 0 ? 'first keyframe' : 'after'}
        </button>
        <button
          aria-label="Move selected keyframe earlier"
          className="mini-command"
          disabled={disabled || selectedIndex <= 0}
          onClick={() => selectedFrameId && onMove(selectedFrameId, -1)}
          title="Move selected keyframe earlier (Alt + Left Arrow)"
          type="button"
        >
          <ChevronLeft aria-hidden="true" />
        </button>
        <button
          aria-label="Move selected keyframe later"
          className="mini-command"
          disabled={disabled || selectedIndex < 0 || selectedIndex >= frames.length - 1}
          onClick={() => selectedFrameId && onMove(selectedFrameId, 1)}
          title="Move selected keyframe later (Alt + Right Arrow)"
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
          <Copy aria-hidden="true" /> Duplicate
        </button>
        <button
          className="command-button command-button--danger"
          disabled={disabled || !selectedFrameId}
          onClick={() => selectedFrameId && onDelete(selectedFrameId)}
          type="button"
        >
          <Trash2 aria-hidden="true" /> Delete
        </button>
      </div>

      {frames.length === 0 ? (
        <div className="studio-timeline-empty">
          <CirclePlus aria-hidden="true" />
          <strong>Blank Motion draft</strong>
          <span>Capture the current Dry Run robot state or add a saved Pose to begin.</span>
        </div>
      ) : (
        <div
          aria-label="Horizontally scrollable Motion timeline"
          className="studio-timeline-scroll"
          data-testid="studio-timeline-scroll"
          onScroll={(event) => {
            if (!disabled) onScrollChange(event.currentTarget.scrollLeft / (96 * zoom));
          }}
          ref={scrollRef}
          tabIndex={0}
        >
          <div className="studio-timeline-track" style={{ width: `${trackWidth}px` }}>
            <div className="studio-time-ruler" aria-hidden="true">
              {Array.from({ length: 9 }, (_, index) => (
                <span key={index} style={{ left: `${4 + index * 11.5}%` }}>
                  {(data.duration * index / 8).toFixed(1)}s
                </span>
              ))}
            </div>

            <div
              aria-hidden="true"
              className="studio-playhead"
              style={{ left: markerLeft(Math.min(playheadS, totalDuration), totalDuration) }}
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
                        title={isDefault ? 'New adjacency uses the Editor Default transition' : 'Preserved adjacent transition'}
                      >
                        {incoming.motion_mode === 'CARTESIAN_LINEAR' ? 'TCP linear' : 'Joint'} · {incoming.duration_s.toFixed(2)}s
                        {isDefault ? ' · default' : ''}
                      </span>
                    ) : null}
                    <button
                      aria-label={`Keyframe ${index + 1}: ${frame.label}. Alt plus arrow keys reorder.`}
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
                        <small>{time.toFixed(2)}s · hold {frame.hold_s.toFixed(2)}s</small>
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
        <span>Playhead</span>
        <input
          aria-label="Timeline playhead"
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
        Drag a keyframe to reorder, or focus it and press Alt + Left/Right Arrow. Only an unchanged directed adjacency keeps its transition; new adjacencies are marked “default”.
      </p>
    </section>
  );
}
