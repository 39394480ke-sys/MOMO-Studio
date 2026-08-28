import { useEffect, useMemo, useRef, useState } from 'react';
import { Pause, Play, RotateCcw } from 'lucide-react';

import type { MotionEntity, ProfileJointDefinition } from '../../api/types';
import { Robot3DViewer } from '../robot-viewer';
import { ResourceSimulationThumbnail } from './ResourceSimulationThumbnail';
import {
  formatSimulationTime,
  motionSimulationDuration,
  sampleMotionAtTime,
} from './resourceSimulation';

interface MotionSimulationPlayerProps {
  motion: MotionEntity;
  profileVariant: 'V1' | 'V2' | null;
  enabledJointIds: readonly string[];
  jointDefinitions: readonly ProfileJointDefinition[];
}

export function MotionSimulationPlayer({
  motion,
  profileVariant,
  enabledJointIds,
  jointDefinitions,
}: MotionSimulationPlayerProps) {
  const duration = motionSimulationDuration(motion);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const timeRef = useRef(0);
  const animation = useRef<number | null>(null);
  const sample = useMemo(() => sampleMotionAtTime(motion, time), [motion, time]);
  const viewerAvailable = profileVariant === motion.robot_variant && enabledJointIds.length > 0;

  useEffect(() => {
    setTime(0);
    timeRef.current = 0;
    setPlaying(false);
  }, [motion.id, motion.revision]);

  useEffect(() => {
    if (!playing || duration <= 0) return undefined;
    const startedAt = performance.now() - timeRef.current * 1000;
    const tick = (now: number) => {
      const next = Math.min(duration, Math.max(0, (now - startedAt) / 1000));
      timeRef.current = next;
      setTime(next);
      if (next >= duration) {
        setPlaying(false);
        animation.current = null;
        return;
      }
      animation.current = requestAnimationFrame(tick);
    };
    animation.current = requestAnimationFrame(tick);
    return () => {
      if (animation.current !== null) cancelAnimationFrame(animation.current);
      animation.current = null;
    };
  }, [duration, playing]);

  const toggle = () => {
    if (duration <= 0) return;
    if (playing) {
      setPlaying(false);
      return;
    }
    if (timeRef.current >= duration) {
      timeRef.current = 0;
      setTime(0);
    }
    setPlaying(true);
  };

  return (
    <section aria-label="动作仿真预览" className="motion-simulation-player">
      <div className="motion-simulation-player__viewer">
        {viewerAvailable ? (
          <Robot3DViewer
            ariaLabel={`${motion.name} 动作仿真三维预览`}
            className="library-resource-viewer"
            enabledJointIds={enabledJointIds}
            jointDefinitions={jointDefinitions}
            jointPositions={sample.jointState.positions}
            jointUnits={sample.jointState.units}
            variant={motion.robot_variant}
          />
        ) : (
          <ResourceSimulationThumbnail
            label={`${motion.name} 动作静态仿真预览`}
            motion={motion}
          />
        )}
        <span className="simulation-only-pill">SIMULATION ONLY</span>
      </div>
      <div className="motion-simulation-player__transport">
        <button
          aria-label={playing ? '暂停仿真' : '仿真播放'}
          className="simulation-play-button"
          disabled={duration <= 0}
          onClick={toggle}
          type="button"
        >
          {playing ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
        </button>
        <div className="motion-simulation-player__timeline">
          <div>
            <strong>{formatSimulationTime(time)} / {formatSimulationTime(duration)}</strong>
            <span>关键帧 {Math.min(motion.keyframes.length, sample.activeKeyframeIndex + 1)} / {motion.keyframes.length}</span>
          </div>
          <input
            aria-label="仿真进度"
            max={Math.max(duration, 0.001)}
            min="0"
            onChange={(event) => {
              setPlaying(false);
              const next = Number(event.target.value);
              timeRef.current = next;
              setTime(next);
            }}
            step="0.01"
            type="range"
            value={Math.min(time, Math.max(duration, 0.001))}
          />
        </div>
        <button
          aria-label="重新开始仿真"
          className="simulation-reset-button"
          onClick={() => {
            setPlaying(false);
            timeRef.current = 0;
            setTime(0);
          }}
          type="button"
        >
          <RotateCcw aria-hidden="true" />
        </button>
      </div>
      <p className="simulation-safety-copy">只更新三维画面，不会调用机械臂播放或运动接口。</p>
    </section>
  );
}
