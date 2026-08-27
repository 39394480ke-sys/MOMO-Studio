import { useEffect, useMemo, useRef, useState, type PointerEvent } from 'react';
import { Crosshair } from 'lucide-react';

import { visionStreamUrl } from '../../api/client';
import type { NormalizedBoundingBox } from '../../api/types';
import type { VisionWorkspace } from './useVisionWorkspace';

interface Point {
  x: number;
  y: number;
}

function clamp(value: number): number {
  return Math.min(1, Math.max(0, value));
}

function pointFor(event: PointerEvent<HTMLDivElement>): Point {
  const bounds = event.currentTarget.getBoundingClientRect();
  return {
    x: clamp((event.clientX - bounds.left) / Math.max(1, bounds.width)),
    y: clamp((event.clientY - bounds.top) / Math.max(1, bounds.height)),
  };
}

function boxBetween(start: Point, end: Point): NormalizedBoundingBox {
  return {
    x: Math.min(start.x, end.x),
    y: Math.min(start.y, end.y),
    width: Math.abs(end.x - start.x),
    height: Math.abs(end.y - start.y),
  };
}

function boxStyle(box: NormalizedBoundingBox) {
  return {
    left: `${box.x * 100}%`,
    top: `${box.y * 100}%`,
    width: `${box.width * 100}%`,
    height: `${box.height * 100}%`,
  };
}

export function VisionCanvas({ workspace }: { workspace: VisionWorkspace }) {
  const [dragStart, setDragStart] = useState<Point | null>(null);
  const [dragCurrent, setDragCurrent] = useState<Point | null>(null);
  const pointerRef = useRef<number | null>(null);
  const dragFrameIdRef = useRef<string | null>(null);
  const draftBox = useMemo(
    () => dragStart && dragCurrent ? boxBetween(dragStart, dragCurrent) : null,
    [dragCurrent, dragStart],
  );
  const tracking = workspace.status?.tracking ?? null;
  const displayBox = tracking
    ? tracking.bounding_box
    : workspace.status?.selection?.bounding_box ?? null;
  const latestFrame = workspace.status?.latest_frame ?? null;
  const sourceState = workspace.status?.source_state ?? null;
  const syntheticSource = workspace.capabilities?.source.provider_id
    .toLowerCase().includes('synthetic') ?? false;
  const sourceLabel = syntheticSource ? 'Synthetic' : workspace.readOnlyLiveCamera ? 'Live' : 'Vision';
  const sourceOperational = sourceState === 'READY' || sourceState === 'STREAMING';
  const frameFresh = latestFrame !== null
    && latestFrame.age_ms <= workspace.configuration.frame_freshness_limit_s * 1000;
  const streamCapable = workspace.online
    && workspace.capabilities?.camera_access_policy !== 'DISABLED'
    && workspace.capabilities?.source.available === true
    && workspace.capabilities.stream.available;
  const streamEnabled = streamCapable && sourceOperational;
  const canSelect = streamEnabled
    && !workspace.readOnlyLiveCamera
    && sourceOperational
    && frameFresh
    && workspace.statusReachable
    && !workspace.streamFailed
    && workspace.busy === null;
  const visibleDetections = workspace.detections.filter(
    (detection) => detection.frame_id === latestFrame?.frame_id,
  );

  useEffect(() => {
    if (canSelect || pointerRef.current === null) return;
    pointerRef.current = null;
    dragFrameIdRef.current = null;
    setDragStart(null);
    setDragCurrent(null);
  }, [canSelect]);

  const clearDrag = (surface: HTMLDivElement, pointerId: number) => {
    pointerRef.current = null;
    dragFrameIdRef.current = null;
    setDragStart(null);
    setDragCurrent(null);
    if (surface.hasPointerCapture?.(pointerId)) surface.releasePointerCapture?.(pointerId);
  };

  const startDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (!canSelect || event.button !== 0) return;
    event.preventDefault();
    pointerRef.current = event.pointerId;
    dragFrameIdRef.current = latestFrame?.frame_id ?? null;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const point = pointFor(event);
    setDragStart(point);
    setDragCurrent(point);
  };

  const moveDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (pointerRef.current !== event.pointerId || !dragStart) return;
    setDragCurrent(pointFor(event));
  };

  const finishDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (pointerRef.current !== event.pointerId || !dragStart) return;
    const completed = boxBetween(dragStart, pointFor(event));
    const frameId = dragFrameIdRef.current;
    clearDrag(event.currentTarget, event.pointerId);
    if (!frameId || completed.width < 0.01 || completed.height < 0.01) return;
    void workspace.selectTarget(frameId, completed);
  };

  const cancelDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (pointerRef.current !== event.pointerId) return;
    clearDrag(event.currentTarget, event.pointerId);
  };

  let unavailableHeading: string | null = null;
  let unavailableDetail: string | null = null;
  if (!workspace.online) {
    unavailableHeading = 'Vision backend offline';
    unavailableDetail = 'Selection and Follow remain disabled.';
  } else if (!workspace.capabilities) {
    unavailableHeading = 'Checking Vision providers';
    unavailableDetail = 'Selection waits for an explicit source capability.';
  } else if (!streamCapable) {
    unavailableHeading = workspace.capabilities.camera_access_policy === 'DISABLED'
      ? 'Vision source disabled'
      : 'Vision stream unavailable';
    unavailableDetail = workspace.capabilities.source.reason
      ?? workspace.capabilities.stream.reason
      ?? 'Selection and Follow remain disabled.';
  } else if (workspace.streamFailed) {
    unavailableHeading = 'Vision stream disconnected';
    unavailableDetail = 'Selection and Follow remain disabled until the stream reconnects.';
  } else if (!workspace.statusReachable) {
    unavailableHeading = 'Vision status unavailable';
    unavailableDetail = 'Selection and Follow remain disabled until status polling recovers.';
  } else if (sourceState !== null && !sourceOperational) {
    unavailableHeading = workspace.readOnlyLiveCamera && sourceState === 'CLOSED'
      ? 'Live camera closed'
      : `Vision source ${String(sourceState).toLowerCase()}`;
    unavailableDetail = workspace.readOnlyLiveCamera
      ? 'Use Open live camera in Source & policy. No robot motion is enabled.'
      : 'Selection and Follow remain disabled.';
  } else if (!latestFrame) {
    unavailableHeading = 'Waiting for the first frame';
    unavailableDetail = 'Selection will unlock after a frame identity is published.';
  } else if (!frameFresh) {
    unavailableHeading = 'Vision frame stale';
    unavailableDetail = 'Reselect only after a fresh frame arrives.';
  }

  return (
    <section className="vision-stage" aria-labelledby="vision-stage-title">
      <div className="vision-stage__header">
        <div>
          <p className="eyebrow">{sourceLabel} video</p>
          <h2 id="vision-stage-title">Target workspace</h2>
        </div>
        <span
          className={`status-pill status-pill--${workspace.status?.tracking?.status === 'LOCKED' ? 'ready' : 'idle'}`}
          role="status"
        >
          {workspace.readOnlyLiveCamera ? 'READ ONLY' : workspace.status?.tracking?.status ?? 'NO TARGET'}
        </span>
      </div>

      <div
        className={`vision-canvas${canSelect ? ' vision-canvas--selectable' : ''}`}
        aria-label={`${sourceLabel} frame target selection surface`}
        aria-describedby="vision-selection-instructions"
        onPointerDown={startDrag}
        onPointerMove={moveDrag}
        onPointerUp={finishDrag}
        onPointerCancel={cancelDrag}
        role="region"
        style={{
          aspectRatio: latestFrame
            ? `${latestFrame.width_px} / ${latestFrame.height_px}`
            : '16 / 9',
        }}
        tabIndex={canSelect ? 0 : -1}
      >
        {streamEnabled ? (
          <img
            alt={`${sourceLabel} vision stream`}
            className="vision-canvas__image"
            draggable={false}
            onError={() => workspace.setStreamFailed(true)}
            onLoad={() => workspace.setStreamFailed(false)}
            src={visionStreamUrl}
          />
        ) : null}
        {unavailableHeading ? (
          <div className="vision-canvas__offline" role="status">
            <Crosshair aria-hidden="true" />
            <strong>{unavailableHeading}</strong>
            <span>{unavailableDetail}</span>
          </div>
        ) : null}
        {!workspace.readOnlyLiveCamera ? (
          <>
            <div className="vision-crosshair" aria-hidden="true"><span /><span /></div>
            <div
              aria-label="Follow dead zone"
              className="vision-dead-zone"
              style={{
                left: `${(0.5 - workspace.configuration.dead_zone_x) * 100}%`,
                top: `${(0.5 - workspace.configuration.dead_zone_y) * 100}%`,
                width: `${workspace.configuration.dead_zone_x * 200}%`,
                height: `${workspace.configuration.dead_zone_y * 200}%`,
              }}
            />
          </>
        ) : null}
        {visibleDetections.map((detection) => (
          <div
            className="vision-box vision-box--detection"
            key={detection.detection_id}
            style={boxStyle(detection.bounding_box)}
          >
            <span>{detection.label} · {Math.round(detection.confidence * 100)}%</span>
          </div>
        ))}
        {displayBox ? (
          <div
            aria-label="Tracked target bounding box"
            className={`vision-box vision-box--${workspace.status?.tracking?.status.toLowerCase() ?? 'selected'}`}
            style={boxStyle(displayBox)}
          >
            <span>
              {workspace.status?.tracking?.status ?? 'SELECTED'}
              {workspace.status?.tracking ? ` · ${Math.round(workspace.status.tracking.confidence * 100)}%` : ''}
            </span>
          </div>
        ) : null}
        {draftBox ? (
          <div aria-label="Target selection preview" className="vision-box vision-box--draft" style={boxStyle(draftBox)} />
        ) : null}
      </div>

      <dl className="vision-metrics" aria-label="Vision frame and tracking metrics">
        <div><dt>Source</dt><dd title={sourceState ?? undefined}>{latestFrame?.source_id ?? (workspace.online ? 'Waiting' : 'OFFLINE')}</dd></div>
        <div><dt>Frame age</dt><dd>{latestFrame ? `${frameFresh ? '' : 'STALE · '}${Math.round(latestFrame.age_ms)} ms` : '—'}</dd></div>
        <div><dt>Target</dt><dd>{tracking?.status ?? (workspace.status?.selection ? 'SELECTED' : 'None')}</dd></div>
        <div><dt>Confidence</dt><dd>{workspace.status?.tracking ? `${Math.round(workspace.status.tracking.confidence * 100)}%` : '—'}</dd></div>
        <div><dt>Follow</dt><dd>{workspace.status?.follow.active ? 'ACTIVE' : 'STOPPED'}</dd></div>
        <div><dt>Robot</dt><dd>{workspace.status?.robot_state ?? 'Unknown'}</dd></div>
      </dl>
      <p className="vision-stage__hint" id="vision-selection-instructions">
        {workspace.readOnlyLiveCamera
          ? 'Live preview is read-only. Frames are not recorded, and tracking or Follow cannot be started.'
          : `Drag directly on a fresh ${sourceLabel} frame to select any target. The frame identity is captured when the drag begins; an expired frame is rejected.`}
      </p>
    </section>
  );
}
