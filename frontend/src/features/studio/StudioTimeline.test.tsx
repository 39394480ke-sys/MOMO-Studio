import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

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
  frames?: MotionKeyframe[];
  isPlaying?: boolean;
  onMoveFrameTime?: (frameId: string, value: number) => void;
  onPause?: () => void;
  onPlay?: () => void;
  onPlayheadChange?: (value: number) => void;
  onScrollChange?: (value: number) => void;
  onSelect?: (frameId: string) => void;
}) {
  const timelineFrames = options?.frames ?? frames;
  render(
    <StudioTimeline
      disabled={false}
      frameLimitReached={false}
      frames={timelineFrames}
      initialScrollS={0}
      isPlaying={options?.isPlaying ?? false}
      motionName="Camera move"
      onAdd={vi.fn()}
      onMoveFrameTime={options?.onMoveFrameTime ?? vi.fn()}
      onPause={options?.onPause ?? vi.fn()}
      onPlay={options?.onPlay ?? vi.fn()}
      onPlayheadChange={options?.onPlayheadChange ?? vi.fn()}
      onScrollChange={options?.onScrollChange ?? vi.fn()}
      onSelect={options?.onSelect ?? vi.fn()}
      playheadS={0}
      selectedFrameId="K1"
    />,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('StudioTimeline product interactions', () => {
  it('renders the selected keyframe as the only filled marker state', () => {
    renderTimeline();

    expect(screen.getByRole('button', { name: /关键帧 1：K1/ })).toHaveClass('studio-keyframe-marker--selected');
    expect(screen.getByRole('button', { name: /关键帧 2：K2/ })).not.toHaveClass('studio-keyframe-marker--selected');
    expect(screen.getByRole('button', { name: /关键帧 3：K3/ })).not.toHaveClass('studio-keyframe-marker--selected');
  });

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
    expect(onPlayheadChange).toHaveBeenCalledWith(1.25);
    fireEvent(track as HTMLElement, new MouseEvent('pointerdown', { bubbles: true, button: 0, clientX: 740 }));
    expect(onPlayheadChange).toHaveBeenLastCalledWith(2);
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
    fireEvent(keyframe, new MouseEvent('pointermove', { bubbles: true, buttons: 1, clientX: 380 }));
    fireEvent(keyframe, new MouseEvent('pointerup', { bubbles: true, button: 0, clientX: 380 }));

    expect(onMoveFrameTime).toHaveBeenCalledOnce();
    expect(onMoveFrameTime).toHaveBeenCalledWith('K2', 1.25);
  });

  it('resizes a short-motion track with its observed viewport width', async () => {
    let resizeCallback: ResizeObserverCallback | null = null;
    class ResizeObserverMock {
      constructor(callback: ResizeObserverCallback) {
        resizeCallback = callback;
      }
      disconnect() {}
      observe() {}
      unobserve() {}
    }
    vi.stubGlobal('ResizeObserver', ResizeObserverMock);
    renderTimeline();
    const track = screen.getByRole('slider', { name: '拖动时间轴播放头' }).parentElement as HTMLElement;

    act(() => {
      resizeCallback?.([{ contentRect: { width: 1180 } } as ResizeObserverEntry], {} as ResizeObserver);
    });
    await waitFor(() => expect(track.style.width).toBe('1180px'));

    act(() => {
      resizeCallback?.([{ contentRect: { width: 920 } } as ResizeObserverEntry], {} as ResizeObserver);
    });
    await waitFor(() => expect(track.style.width).toBe('920px'));
  });

  it('extends and scrolls the track while dragging the last keyframe at the right edge', () => {
    const onMoveFrameTime = vi.fn();
    let animationFrame: FrameRequestCallback | null = null;
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      animationFrame = callback;
      return 1;
    });
    vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => undefined);
    renderTimeline({ onMoveFrameTime });
    const keyframe = screen.getByRole('button', { name: /关键帧 3：K3/ });
    const track = screen.getByRole('slider', { name: '拖动时间轴播放头' }).parentElement as HTMLElement;
    const scroll = track.parentElement as HTMLElement;
    vi.spyOn(track, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, left: 0, top: 0, right: 760, bottom: 120, width: 760, height: 120,
      toJSON: () => ({}),
    });
    vi.spyOn(scroll, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, left: 0, top: 0, right: 760, bottom: 120, width: 760, height: 120,
      toJSON: () => ({}),
    });

    fireEvent(keyframe, new MouseEvent('pointerdown', { bubbles: true, button: 0, clientX: 574 }));
    fireEvent(keyframe, new MouseEvent('pointermove', { bubbles: true, buttons: 1, clientX: 750 }));
    act(() => animationFrame?.(16));
    fireEvent(keyframe, new MouseEvent('pointerup', { bubbles: true, button: 0, clientX: 750 }));

    expect(scroll.scrollLeft).toBeGreaterThan(0);
    expect(onMoveFrameTime).toHaveBeenCalledOnce();
    expect(onMoveFrameTime.mock.calls[0]?.[0]).toBe('K3');
    expect(onMoveFrameTime.mock.calls[0]?.[1]).toBeGreaterThan(2);
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
