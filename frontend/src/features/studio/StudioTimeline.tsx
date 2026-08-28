import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from 'react';
import { Pause, Play, Plus } from 'lucide-react';

import type { MotionKeyframe } from '../../api/types';
import {
  formatTimelineTime,
  framesWithTimelineTimeEdit,
  timelineData,
  timelineTimeEdit,
} from './studioTimelineMath';

interface StudioTimelineProps {
  disabled: boolean;
  frameLimitReached: boolean;
  frames: MotionKeyframe[];
  initialScrollS: number;
  isPlaying: boolean;
  motionName: string;
  playheadS: number;
  selectedFrameId: string | null;
  onAdd: () => void;
  onMoveFrameTime: (frameId: string, timeS: number) => void;
  onPause: () => void;
  onPlay: () => void;
  onPlayheadChange: (timeS: number) => void;
  onScrollChange: (scrollS: number) => void;
  onSelect: (frameId: string) => void;
}

interface FrameDrag {
  frameId: string;
  pointerId: number;
  timeS: number;
}

const TRACK_PADDING_PX = 56;

function boundedPlayhead(playheadS: number, durationS: number): number {
  return Math.min(Math.max(0, durationS), Math.max(0, playheadS));
}

export function StudioTimeline({
  disabled,
  frameLimitReached,
  frames,
  initialScrollS,
  isPlaying,
  motionName,
  playheadS,
  selectedFrameId,
  onAdd,
  onMoveFrameTime,
  onPause,
  onPlay,
  onPlayheadChange,
  onScrollChange,
  onSelect,
}: StudioTimelineProps) {
  const [frameDrag, setFrameDrag] = useState<FrameDrag | null>(null);
  const frameDragRef = useRef<FrameDrag | null>(null);
  const playheadPointerRef = useRef<number | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const draftEdit = useMemo(
    () => frameDrag ? timelineTimeEdit(frames, frameDrag.frameId, frameDrag.timeS) : null,
    [frameDrag, frames],
  );
  const displayFrames = useMemo(
    () => framesWithTimelineTimeEdit(frames, draftEdit),
    [draftEdit, frames],
  );
  const data = useMemo(() => timelineData(displayFrames), [displayFrames]);
  const totalDuration = Math.max(data.duration, 0.05);
  const trackWidth = Math.max(760, TRACK_PADDING_PX * 2 + totalDuration * 112);
  const usableWidth = trackWidth - TRACK_PADDING_PX * 2;
  const pixelsPerSecond = usableWidth / totalDuration;

  const leftForTime = (timeS: number) => TRACK_PADDING_PX + timeS * pixelsPerSecond;
  const timeFromPointer = (clientX: number) => {
    const rect = trackRef.current?.getBoundingClientRect();
    if (!rect) return 0;
    const localX = clientX - rect.left - TRACK_PADDING_PX;
    return Math.round(Math.min(totalDuration, Math.max(0, localX / pixelsPerSecond)) * 100) / 100;
  };

  useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    const intended = Math.max(0, initialScrollS * pixelsPerSecond);
    if (Math.abs(node.scrollLeft - intended) > 2) node.scrollLeft = intended;
  }, [initialScrollS, pixelsPerSecond]);

  const selectFrame = (frameId: string, timeS: number) => {
    onSelect(frameId);
    onPlayheadChange(timeS);
  };

  const beginFrameDrag = (
    event: PointerEvent<HTMLButtonElement>,
    frameId: string,
    timeS: number,
    index: number,
  ) => {
    if (disabled || index === 0 || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const drag = { frameId, pointerId: event.pointerId, timeS };
    frameDragRef.current = drag;
    setFrameDrag(drag);
    selectFrame(frameId, timeS);
  };

  const updateFrameDrag = (event: PointerEvent<HTMLButtonElement>) => {
    const drag = frameDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    event.preventDefault();
    const timing = timelineTimeEdit(frames, drag.frameId, timeFromPointer(event.clientX));
    if (!timing) return;
    const next = { ...drag, timeS: timing.timeS };
    frameDragRef.current = next;
    setFrameDrag(next);
    onPlayheadChange(timing.timeS);
  };

  const finishFrameDrag = (event: PointerEvent<HTMLButtonElement>, commit: boolean) => {
    const drag = frameDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture?.(event.pointerId);
    }
    frameDragRef.current = null;
    setFrameDrag(null);
    if (commit) onMoveFrameTime(drag.frameId, drag.timeS);
  };

  const handleFrameKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    frameId: string,
    timeS: number,
    index: number,
  ) => {
    if (disabled || index === 0 || (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight')) return;
    event.preventDefault();
    const step = event.shiftKey ? 0.25 : 0.05;
    const timing = timelineTimeEdit(
      frames,
      frameId,
      timeS + (event.key === 'ArrowLeft' ? -step : step),
    );
    if (!timing) return;
    onMoveFrameTime(frameId, timing.timeS);
    onPlayheadChange(timing.timeS);
  };

  const setPlayheadFromPointer = (event: PointerEvent<HTMLDivElement>) => {
    onPlayheadChange(timeFromPointer(event.clientX));
  };

  const beginPlayheadDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (disabled || event.button !== 0) return;
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest('.studio-keyframe-marker')) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    playheadPointerRef.current = event.pointerId;
    setPlayheadFromPointer(event);
  };

  const tickCount = 5;
  const currentTime = boundedPlayhead(playheadS, totalDuration);

  return (
    <section aria-busy={disabled} aria-labelledby="studio-timeline-heading" className="studio-timeline-panel">
      <header className="studio-timeline-header">
        <div className="studio-timeline-title">
          <span>MOTION</span>
          <strong id="studio-timeline-heading">{motionName || 'Untitled Motion'}</strong>
        </div>
        <div aria-label="仿真预览控制" className="studio-simulation-controls">
          <button aria-label="播放仿真预览" disabled={disabled || isPlaying || frames.length < 2} onClick={onPlay} type="button">
            <Play aria-hidden="true" /> <span>Play</span>
          </button>
          <button aria-label="暂停仿真预览" disabled={disabled || !isPlaying} onClick={onPause} type="button">
            <Pause aria-hidden="true" /> <span>Pause</span>
          </button>
          <output aria-live="polite">{formatTimelineTime(currentTime)} / {formatTimelineTime(totalDuration)}</output>
        </div>
        <button className="command-button studio-add-keyframe" disabled={disabled || frameLimitReached} onClick={onAdd} type="button">
          <Plus aria-hidden="true" /> 添加关键帧
        </button>
      </header>

      {frames.length === 0 ? (
        <div className="studio-timeline-empty">
          <strong>空白运动草稿</strong>
          <span>使用右上角“添加关键帧”捕获当前姿态，或从资源库选择 Pose。</span>
        </div>
      ) : (
        <div
          aria-label="可横向滚动的运动时间轴"
          className="studio-timeline-scroll"
          data-testid="studio-timeline-scroll"
          onScroll={(event) => {
            if (!disabled) onScrollChange(event.currentTarget.scrollLeft / pixelsPerSecond);
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
              if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture?.(event.pointerId);
            }}
            ref={trackRef}
            style={{ width: `${trackWidth}px` }}
          >
            <div className="studio-time-ruler" aria-hidden="true">
              {Array.from({ length: tickCount + 1 }, (_, index) => {
                const timeS = totalDuration * index / tickCount;
                return <span key={index} style={{ left: `${leftForTime(timeS)}px` }}>{formatTimelineTime(timeS)}</span>;
              })}
            </div>

            <div className="studio-segment-layer" aria-hidden="true">
              {data.segments.map((segment, index) => {
                const from = data.markers[index];
                const to = data.markers[index + 1];
                if (!from || !to) return null;
                const left = leftForTime(from.time);
                const right = leftForTime(to.time);
                return (
                  <span className="studio-timeline-segment" key={`${segment.from.id}-${segment.to.id}`} style={{ left: `${left}px`, width: `${Math.max(24, right - left)}px` }}>
                    <span>{segment.duration.toFixed(2)} s</span>
                  </span>
                );
              })}
            </div>

            <div aria-label="拖动时间轴播放头" aria-valuemax={totalDuration} aria-valuemin={0} aria-valuenow={currentTime} className="studio-playhead" role="slider" style={{ left: `${leftForTime(currentTime)}px` }} tabIndex={0}>
              <span>{formatTimelineTime(currentTime)}</span>
            </div>

            <ol className="studio-keyframe-track">
              {data.markers.map(({ frame, index, time }) => (
                <li className="studio-keyframe-slot" key={frame.id} style={{ left: `${leftForTime(time)}px` }}>
                  <button
                    aria-label={`关键帧 ${index + 1}：${frame.label}，时间 ${time.toFixed(2)} 秒`}
                    aria-pressed={frame.id === selectedFrameId}
                    className={`studio-keyframe-marker${frame.id === selectedFrameId ? ' studio-keyframe-marker--selected' : ''}`}
                    disabled={disabled}
                    onClick={() => selectFrame(frame.id, time)}
                    onKeyDown={(event) => handleFrameKeyDown(event, frame.id, time, index)}
                    onPointerCancel={(event) => finishFrameDrag(event, false)}
                    onPointerDown={(event) => beginFrameDrag(event, frame.id, time, index)}
                    onPointerMove={updateFrameDrag}
                    onPointerUp={(event) => finishFrameDrag(event, true)}
                    title={index === 0 ? '起始关键帧固定在 00:00' : '左右拖动以调整关键帧时间'}
                    type="button"
                  >
                    <span className="studio-keyframe-dot" />
                    <span className="studio-keyframe-label"><strong>K{index + 1}</strong><small>{frame.label}</small></span>
                  </button>
                </li>
              ))}
            </ol>
          </div>
        </div>
      )}
    </section>
  );
}
