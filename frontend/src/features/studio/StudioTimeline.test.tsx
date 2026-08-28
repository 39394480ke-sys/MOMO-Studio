import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { MotionKeyframe } from '../../api/types';
import { StudioTimeline } from './StudioTimeline';

function frame(id: string, incoming: MotionKeyframe['incoming_transition']): MotionKeyframe {
  return {
    id,
    label: id,
    hold_s: 0,
    incoming_transition: incoming,
    source_pose_id: null,
    pose_snapshot: {} as MotionKeyframe['pose_snapshot'],
  };
}

const frames = [
  frame('K1', null),
  frame('K2', { duration_s: 1, motion_mode: 'JOINT', easing: 'SMOOTHSTEP' }),
  frame('K3', { duration_s: 1, motion_mode: 'JOINT', easing: 'SMOOTHSTEP' }),
];

function renderTimeline(options?: {
  isPlaying?: boolean;
  onMoveFrameTime?: (frameId: string, value: number) => void;
  onPause?: () => void;
  onPlay?: () => void;
  onPlayheadChange?: (value: number) => void;
  onSelect?: (frameId: string) => void;
}) {
  render(
    <StudioTimeline
      disabled={false}
      frameLimitReached={false}
      frames={frames}
      initialScrollS={0}
      isPlaying={options?.isPlaying ?? false}
      motionName="Camera move"
      onAdd={vi.fn()}
      onMoveFrameTime={options?.onMoveFrameTime ?? vi.fn()}
      onPause={options?.onPause ?? vi.fn()}
      onPlay={options?.onPlay ?? vi.fn()}
      onPlayheadChange={options?.onPlayheadChange ?? vi.fn()}
      onScrollChange={vi.fn()}
      onSelect={options?.onSelect ?? vi.fn()}
      playheadS={0}
      selectedFrameId="K1"
    />,
  );
}

describe('StudioTimeline product interactions', () => {
  it('moves a keyframe in time with one bounded authoring callback', async () => {
    const user = userEvent.setup();
    const onMoveFrameTime = vi.fn();
    renderTimeline({ onMoveFrameTime });

    const keyframe = screen.getByRole('button', { name: /关键帧 2：K2/ });
    keyframe.focus();
    await user.keyboard('{ArrowRight}');

    expect(onMoveFrameTime).toHaveBeenCalledWith('K2', 1.05);
  });

  it('selects a keyframe and moves the playhead to the same time', async () => {
    const user = userEvent.setup();
    const onPlayheadChange = vi.fn();
    const onSelect = vi.fn();
    renderTimeline({ onPlayheadChange, onSelect });

    await user.click(screen.getByRole('button', { name: /关键帧 3：K3/ }));

    expect(onSelect).toHaveBeenCalledWith('K3');
    expect(onPlayheadChange).toHaveBeenCalledWith(2);
  });

  it('scrubs the red playhead directly from the proportional time track', () => {
    const onPlayheadChange = vi.fn();
    renderTimeline({ onPlayheadChange });
    const track = screen.getByRole('slider', { name: '拖动时间轴播放头' }).parentElement;
    expect(track).not.toBeNull();
    vi.spyOn(track as HTMLElement, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, left: 0, top: 0, right: 760, bottom: 120, width: 760, height: 120,
      toJSON: () => ({}),
    });

    fireEvent(track as HTMLElement, new MouseEvent('pointerdown', { bubbles: true, button: 0, clientX: 380 }));
    expect(onPlayheadChange).toHaveBeenCalledWith(1);
  });

  it('commits a directly dragged keyframe point as one absolute-time edit', () => {
    const onMoveFrameTime = vi.fn();
    renderTimeline({ onMoveFrameTime });
    const keyframe = screen.getByRole('button', { name: /关键帧 2：K2/ });
    const track = screen.getByRole('slider', { name: '拖动时间轴播放头' }).parentElement;
    expect(track).not.toBeNull();
    vi.spyOn(track as HTMLElement, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, left: 0, top: 0, right: 760, bottom: 120, width: 760, height: 120,
      toJSON: () => ({}),
    });

    fireEvent(keyframe, new MouseEvent('pointerdown', { bubbles: true, button: 0, clientX: 380 }));
    fireEvent(keyframe, new MouseEvent('pointermove', { bubbles: true, buttons: 1, clientX: 461 }));
    fireEvent(keyframe, new MouseEvent('pointerup', { bubbles: true, button: 0, clientX: 461 }));

    expect(onMoveFrameTime).toHaveBeenCalledOnce();
    expect(onMoveFrameTime).toHaveBeenCalledWith('K2', 1.25);
  });

  it('exposes client-only Play and Pause callbacks in the compact toolbar', async () => {
    const user = userEvent.setup();
    const onPlay = vi.fn();
    const onPause = vi.fn();
    const { rerender } = render(
      <StudioTimeline
        disabled={false}
        frameLimitReached={false}
        frames={frames}
        initialScrollS={0}
        isPlaying={false}
        motionName="Camera move"
        onAdd={vi.fn()}
        onMoveFrameTime={vi.fn()}
        onPause={onPause}
        onPlay={onPlay}
        onPlayheadChange={vi.fn()}
        onScrollChange={vi.fn()}
        onSelect={vi.fn()}
        playheadS={0}
        selectedFrameId="K1"
      />,
    );
    await user.click(screen.getByRole('button', { name: '播放仿真预览' }));
    expect(onPlay).toHaveBeenCalledOnce();

    rerender(
      <StudioTimeline
        disabled={false}
        frameLimitReached={false}
        frames={frames}
        initialScrollS={0}
        isPlaying
        motionName="Camera move"
        onAdd={vi.fn()}
        onMoveFrameTime={vi.fn()}
        onPause={onPause}
        onPlay={onPlay}
        onPlayheadChange={vi.fn()}
        onScrollChange={vi.fn()}
        onSelect={vi.fn()}
        playheadS={0.5}
        selectedFrameId="K1"
      />,
    );
    await user.click(screen.getByRole('button', { name: '暂停仿真预览' }));
    expect(onPause).toHaveBeenCalledOnce();
  });
});
