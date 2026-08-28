import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { MotionKeyframe } from '../../api/types';
import { StudioTimeline } from './StudioTimeline';

function frame(id: string, incoming: MotionKeyframe['incoming_transition']): MotionKeyframe {
  return {
    id,
    label: id,
    hold_s: 0.2,
    incoming_transition: incoming,
    source_pose_id: null,
    pose_snapshot: {} as MotionKeyframe['pose_snapshot'],
  };
}

const frames = [
  frame('K1', null),
  frame('K2', { duration_s: 1, motion_mode: 'JOINT', easing: 'SMOOTHSTEP' }),
];

function renderTimeline(options?: {
  onPlayheadChange?: (value: number) => void;
  onTransitionDurationChange?: (frameId: string, value: number) => void;
}) {
  render(
    <StudioTimeline
      defaultEdgeIds={new Set(['K1->K2'])}
      disabled={false}
      frameLimitReached={false}
      frames={frames}
      initialScrollS={0}
      onAddAfter={vi.fn()}
      onAddBefore={vi.fn()}
      onDelete={vi.fn()}
      onDuplicate={vi.fn()}
      onMove={vi.fn()}
      onPlayheadChange={options?.onPlayheadChange ?? vi.fn()}
      onReorder={vi.fn()}
      onScrollChange={vi.fn()}
      onSelect={vi.fn()}
      onTransitionDurationChange={options?.onTransitionDurationChange ?? vi.fn()}
      onZoomChange={vi.fn()}
      playheadS={0}
      runtimeMode="DRY RUN"
      selectedFrameId="K1"
      zoom={1}
    />,
  );
}

describe('StudioTimeline product interactions', () => {
  it('offers keyboard duration resizing with the same bounded authoring callback', async () => {
    const user = userEvent.setup();
    const onTransitionDurationChange = vi.fn();
    renderTimeline({ onTransitionDurationChange });

    const resize = screen.getByRole('button', { name: '调整第 1 段过渡时长' });
    resize.focus();
    await user.keyboard('{ArrowRight}');

    expect(onTransitionDurationChange).toHaveBeenCalledWith('K2', 1.05);
  });

  it('scrubs the visualization playhead without invoking a motion callback', () => {
    const onPlayheadChange = vi.fn();
    renderTimeline({ onPlayheadChange });

    fireEvent.change(screen.getByLabelText('时间轴播放头'), { target: { value: '0.75' } });
    expect(onPlayheadChange).toHaveBeenCalledWith(0.75);
  });
});
