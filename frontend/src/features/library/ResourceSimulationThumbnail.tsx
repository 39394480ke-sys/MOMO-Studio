import { useEffect, useMemo, useRef, useState } from 'react';
import { TriangleAlert } from 'lucide-react';

import type { MotionEntity, PoseSummary, PoseSnapshot } from '../../api/types';

type SnapshotLike = Pick<PoseSnapshot, 'joint_state' | 'tcp_pose'>;

interface ResourceSimulationThumbnailProps {
  pose?: PoseSummary;
  motion?: MotionEntity | null;
  loading?: boolean;
  unavailable?: boolean;
  label: string;
}

const WIDTH = 640;
const HEIGHT = 280;

function finiteSnapshot(snapshot: SnapshotLike): boolean {
  const values = Object.values(snapshot.joint_state.positions);
  return values.length > 0 && values.every(Number.isFinite);
}

function armPoints(snapshot: SnapshotLike): Array<[number, number]> {
  const values = snapshot.joint_state.positions;
  const rail = Number.isFinite(values.j10) ? values.j10 : 0;
  const angles = ['j11', 'j12', 'j13', 'j14', 'j15'].map((id) => (
    Number.isFinite(values[id]) ? values[id] * (Math.PI / 180) : 0
  ));
  const lengths = [58, 52, 44, 34, 22];
  let x = WIDTH * 0.48 + rail * 1.25;
  let y = HEIGHT * 0.77;
  let angle = -Math.PI / 2.35;
  const points: Array<[number, number]> = [[x, y]];
  for (let index = 0; index < lengths.length; index += 1) {
    angle += angles[index] * 0.72;
    x += Math.cos(angle) * lengths[index];
    y += Math.sin(angle) * lengths[index];
    points.push([x, y]);
  }
  return points;
}

function drawArm(
  context: CanvasRenderingContext2D,
  snapshot: SnapshotLike,
  alpha: number,
  ghost: boolean,
) {
  const points = armPoints(snapshot);
  context.save();
  context.globalAlpha = alpha;
  context.lineCap = 'round';
  context.lineJoin = 'round';
  context.strokeStyle = ghost ? '#8f7af2' : '#26242d';
  context.lineWidth = ghost ? 8 : 13;
  context.beginPath();
  points.forEach(([x, y], index) => {
    if (index === 0) context.moveTo(x, y);
    else context.lineTo(x, y);
  });
  context.stroke();
  for (const [index, [x, y]] of points.entries()) {
    context.fillStyle = index === points.length - 1 ? '#7657e8' : '#ffffff';
    context.strokeStyle = ghost ? '#a99af3' : '#bcc1cd';
    context.lineWidth = 7;
    context.beginPath();
    context.arc(x, y, index === 0 ? 17 : 13, 0, Math.PI * 2);
    context.fill();
    context.stroke();
  }
  context.restore();
}

function drawTcpPath(context: CanvasRenderingContext2D, snapshots: SnapshotLike[]) {
  if (snapshots.length < 2) return;
  const positions = snapshots.map((snapshot) => snapshot.tcp_pose.position_mm);
  const xs = positions.map((point) => point.x);
  const zs = positions.map((point) => point.z);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minZ = Math.min(...zs);
  const maxZ = Math.max(...zs);
  const rangeX = Math.max(1, maxX - minX);
  const rangeZ = Math.max(1, maxZ - minZ);
  context.save();
  context.strokeStyle = '#9b85f6';
  context.lineWidth = 4;
  context.setLineDash([9, 8]);
  context.beginPath();
  positions.forEach((point, index) => {
    const x = 70 + ((point.x - minX) / rangeX) * (WIDTH - 140);
    const y = HEIGHT - 48 - ((point.z - minZ) / rangeZ) * 70;
    if (index === 0) context.moveTo(x, y);
    else context.lineTo(x, y);
  });
  context.stroke();
  context.restore();
}

function paint(context: CanvasRenderingContext2D, snapshots: SnapshotLike[]) {
  context.clearRect(0, 0, WIDTH, HEIGHT);
  context.fillStyle = '#faf9fd';
  context.fillRect(0, 0, WIDTH, HEIGHT);
  context.strokeStyle = '#eceaf2';
  context.lineWidth = 1;
  for (let x = 80; x < WIDTH; x += 120) {
    context.beginPath();
    context.moveTo(x, 0);
    context.lineTo(x, HEIGHT);
    context.stroke();
  }
  context.strokeStyle = '#b9a9ff';
  context.lineWidth = 3;
  context.beginPath();
  context.moveTo(34, HEIGHT - 34);
  context.lineTo(WIDTH - 34, HEIGHT - 34);
  context.stroke();

  drawTcpPath(context, snapshots);
  snapshots.slice(1).forEach((snapshot, index) => {
    drawArm(context, snapshot, Math.max(0.11, 0.24 - index * 0.025), true);
  });
  drawArm(context, snapshots[0], 1, false);
}

export function ResourceSimulationThumbnail({
  pose,
  motion,
  loading = false,
  unavailable = false,
  label,
}: ResourceSimulationThumbnailProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [canvasUnavailable, setCanvasUnavailable] = useState(false);
  const snapshots = useMemo<SnapshotLike[]>(() => (
    pose
      ? [{ joint_state: pose.joint_state, tcp_pose: pose.tcp_pose }]
      : motion?.keyframes.map((frame) => frame.pose_snapshot) ?? []
  ), [motion, pose]);
  const valid = snapshots.length > 0 && snapshots.every(finiteSnapshot);

  useEffect(() => {
    if (typeof navigator !== 'undefined' && /jsdom/i.test(navigator.userAgent)) return;
    const canvas = canvasRef.current;
    if (!canvas || !valid) return;
    try {
      const context = canvas.getContext('2d');
      if (!context) {
        setCanvasUnavailable(true);
        return;
      }
      paint(context, snapshots);
      setCanvasUnavailable(false);
    } catch {
      setCanvasUnavailable(true);
    }
  }, [valid, snapshots]);

  return (
    <div className="resource-simulation-thumbnail" data-preview-state={valid && !canvasUnavailable ? 'ready' : loading ? 'loading' : 'unavailable'}>
      <canvas aria-label={label} height={HEIGHT} ref={canvasRef} role="img" width={WIDTH} />
      {!valid || canvasUnavailable ? (
        <div className="resource-simulation-thumbnail__fallback" role="status">
          {unavailable || canvasUnavailable ? <TriangleAlert aria-hidden="true" /> : null}
          <span>{loading ? '正在生成真实姿态预览…' : '仿真预览暂不可用'}</span>
        </div>
      ) : null}
    </div>
  );
}
