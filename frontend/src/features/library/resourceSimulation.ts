import type {
  JointStatePayload,
  MotionEasing,
  MotionEntity,
  MotionKeyframe,
  TcpPose,
} from '../../api/types';

export interface SimulationSample {
  jointState: JointStatePayload;
  tcpPose: TcpPose;
  activeKeyframeIndex: number;
}

function easingProgress(easing: MotionEasing, progress: number): number {
  const bounded = Math.min(1, Math.max(0, progress));
  if (easing === 'LINEAR') return bounded;
  if (easing === 'SMOOTHSTEP') return bounded * bounded * (3 - 2 * bounded);
  return bounded < 0.5
    ? 2 * bounded * bounded
    : 1 - ((-2 * bounded + 2) ** 2) / 2;
}

function interpolateValue(from: number, to: number, progress: number): number {
  return from + (to - from) * progress;
}

function interpolateTcp(from: TcpPose, to: TcpPose, progress: number): TcpPose {
  const orientation = {
    x: interpolateValue(
      from.orientation_quaternion_xyzw.x,
      to.orientation_quaternion_xyzw.x,
      progress,
    ),
    y: interpolateValue(
      from.orientation_quaternion_xyzw.y,
      to.orientation_quaternion_xyzw.y,
      progress,
    ),
    z: interpolateValue(
      from.orientation_quaternion_xyzw.z,
      to.orientation_quaternion_xyzw.z,
      progress,
    ),
    w: interpolateValue(
      from.orientation_quaternion_xyzw.w,
      to.orientation_quaternion_xyzw.w,
      progress,
    ),
  };
  const norm = Math.hypot(orientation.x, orientation.y, orientation.z, orientation.w) || 1;
  return {
    frame: from.frame,
    position_mm: {
      x: interpolateValue(from.position_mm.x, to.position_mm.x, progress),
      y: interpolateValue(from.position_mm.y, to.position_mm.y, progress),
      z: interpolateValue(from.position_mm.z, to.position_mm.z, progress),
    },
    orientation_quaternion_xyzw: {
      x: orientation.x / norm,
      y: orientation.y / norm,
      z: orientation.z / norm,
      w: orientation.w / norm,
    },
  };
}

function frameSample(frame: MotionKeyframe, index: number): SimulationSample {
  return {
    jointState: frame.pose_snapshot.joint_state,
    tcpPose: frame.pose_snapshot.tcp_pose,
    activeKeyframeIndex: index,
  };
}

export function motionSimulationDuration(motion: MotionEntity): number {
  return motion.keyframes.reduce(
    (duration, frame) => duration + frame.hold_s + (frame.incoming_transition?.duration_s ?? 0),
    0,
  );
}

export function sampleMotionAtTime(motion: MotionEntity, requestedTime: number): SimulationSample {
  const frames = motion.keyframes;
  if (frames.length === 0) {
    throw new Error('Motion does not contain a simulation keyframe');
  }
  const duration = motionSimulationDuration(motion);
  const time = Number.isFinite(requestedTime)
    ? Math.min(duration, Math.max(0, requestedTime))
    : 0;
  let cursor = 0;

  for (let index = 0; index < frames.length; index += 1) {
    const frame = frames[index];
    const transition = frame.incoming_transition;
    if (index > 0 && transition) {
      const transitionEnd = cursor + transition.duration_s;
      if (time <= transitionEnd) {
        const previous = frames[index - 1];
        const rawProgress = transition.duration_s > 0
          ? (time - cursor) / transition.duration_s
          : 1;
        const progress = easingProgress(transition.easing, rawProgress);
        const positions: Record<string, number> = {};
        for (const jointId of Object.keys(frame.pose_snapshot.joint_state.positions)) {
          const from = previous.pose_snapshot.joint_state.positions[jointId];
          const to = frame.pose_snapshot.joint_state.positions[jointId];
          if (Number.isFinite(from) && Number.isFinite(to)) {
            positions[jointId] = interpolateValue(from, to, progress);
          }
        }
        return {
          jointState: {
            positions,
            units: frame.pose_snapshot.joint_state.units,
          },
          tcpPose: interpolateTcp(
            previous.pose_snapshot.tcp_pose,
            frame.pose_snapshot.tcp_pose,
            progress,
          ),
          activeKeyframeIndex: index,
        };
      }
      cursor = transitionEnd;
    }

    const holdEnd = cursor + frame.hold_s;
    if (time <= holdEnd || index === frames.length - 1) return frameSample(frame, index);
    cursor = holdEnd;
  }

  return frameSample(frames[frames.length - 1], frames.length - 1);
}

export function formatSimulationTime(seconds: number): string {
  const safe = Math.max(0, Number.isFinite(seconds) ? seconds : 0);
  const minutes = Math.floor(safe / 60);
  const remainder = safe - minutes * 60;
  return `${String(minutes).padStart(2, '0')}:${remainder.toFixed(1).padStart(4, '0')}`;
}
