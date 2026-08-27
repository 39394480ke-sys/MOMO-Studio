import { useEffect, useMemo, useRef, useState, type PointerEvent } from 'react';
import { Crosshair } from 'lucide-react';

import { visionStreamUrl } from '../../api/client';
import type { NormalizedBoundingBox } from '../../api/types';
import { zhStatus } from '../../i18n/zh';
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
  const sourceLabel = syntheticSource ? '合成' : workspace.readOnlyLiveCamera ? '实时' : '视觉';
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
    unavailableHeading = '视觉后端离线';
    unavailableDetail = '目标选择和跟随保持禁用。';
  } else if (!workspace.capabilities) {
    unavailableHeading = '正在检查视觉能力';
    unavailableDetail = '确认明确的图像源能力后才能选择目标。';
  } else if (!streamCapable) {
    unavailableHeading = workspace.capabilities.camera_access_policy === 'DISABLED'
      ? '视觉图像源已禁用'
      : '视觉视频流不可用';
    unavailableDetail = workspace.capabilities.source.reason
      ?? workspace.capabilities.stream.reason
      ?? '目标选择和跟随保持禁用。';
  } else if (workspace.streamFailed) {
    unavailableHeading = '视觉视频流已断开';
    unavailableDetail = '视频流重新连接前，目标选择和跟随保持禁用。';
  } else if (!workspace.statusReachable) {
    unavailableHeading = '视觉状态不可用';
    unavailableDetail = '状态轮询恢复前，目标选择和跟随保持禁用。';
  } else if (sourceState !== null && !sourceOperational) {
    unavailableHeading = workspace.readOnlyLiveCamera && sourceState === 'CLOSED'
      ? '实时相机已关闭'
      : `视觉图像源：${zhStatus(sourceState)}`;
    unavailableDetail = workspace.readOnlyLiveCamera
      ? '请在“图像源与策略”中打开实时相机；不会启用机械臂运动。'
      : '目标选择和跟随保持禁用。';
  } else if (!latestFrame) {
    unavailableHeading = '正在等待第一帧画面';
    unavailableDetail = '后端发布画面身份后会解锁目标选择。';
  } else if (!frameFresh) {
    unavailableHeading = '视觉画面已过期';
    unavailableDetail = '请等待新画面到达后重新选择目标。';
  }

  return (
    <section className="vision-stage" aria-labelledby="vision-stage-title">
      <div className="vision-stage__header">
        <div>
          <p className="eyebrow">{sourceLabel}画面</p>
          <h2 id="vision-stage-title">目标工作区</h2>
        </div>
        <span
          className={`status-pill status-pill--${workspace.status?.tracking?.status === 'LOCKED' ? 'ready' : 'idle'}`}
          role="status"
        >
          {workspace.readOnlyLiveCamera ? '只读' : zhStatus(workspace.status?.tracking?.status, '无目标')}
        </span>
      </div>

      <div
        className={`vision-canvas${canSelect ? ' vision-canvas--selectable' : ''}`}
        aria-label={`${sourceLabel}画面目标选择区域`}
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
            alt={`${sourceLabel}视觉视频流`}
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
              aria-label="跟随死区"
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
            aria-label="跟踪目标边界框"
            className={`vision-box vision-box--${workspace.status?.tracking?.status.toLowerCase() ?? 'selected'}`}
            style={boxStyle(displayBox)}
          >
            <span>
              {zhStatus(workspace.status?.tracking?.status, '已选择')}
              {workspace.status?.tracking ? ` · ${Math.round(workspace.status.tracking.confidence * 100)}%` : ''}
            </span>
          </div>
        ) : null}
        {draftBox ? (
          <div aria-label="目标选择预览" className="vision-box vision-box--draft" style={boxStyle(draftBox)} />
        ) : null}
      </div>

      <dl className="vision-metrics" aria-label="视觉画面与跟踪指标">
        <div><dt>图像源</dt><dd title={sourceState ?? undefined}>{latestFrame?.source_id ?? (workspace.online ? '等待中' : '离线')}</dd></div>
        <div><dt>画面延迟</dt><dd>{latestFrame ? `${frameFresh ? '' : '已过期 · '}${Math.round(latestFrame.age_ms)} ms` : '—'}</dd></div>
        <div><dt>目标</dt><dd>{zhStatus(tracking?.status, workspace.status?.selection ? '已选择' : '无')}</dd></div>
        <div><dt>置信度</dt><dd>{workspace.status?.tracking ? `${Math.round(workspace.status.tracking.confidence * 100)}%` : '—'}</dd></div>
        <div><dt>跟随</dt><dd>{workspace.status?.follow.active ? '运行中' : '已停止'}</dd></div>
        <div><dt>机械臂</dt><dd>{zhStatus(workspace.status?.robot_state, '未知')}</dd></div>
      </dl>
      <p className="vision-stage__hint" id="vision-selection-instructions">
        {workspace.readOnlyLiveCamera
          ? '实时预览为只读模式：不会录像，也不能启动目标跟踪或视觉跟随。'
          : `在最新${sourceLabel}画面上直接拖框选择目标。开始拖动时会锁定画面身份；已经过期的画面会被拒绝。`}
      </p>
    </section>
  );
}
