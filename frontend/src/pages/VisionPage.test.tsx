import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AppContent } from '../app/App';
import { mockStage7Backend, stage7Ids } from '../test/stage7Fixtures';

function renderVision() {
  return render(
    <MemoryRouter initialEntries={['/vision']}>
      <AppContent />
    </MemoryRouter>,
  );
}

function dispatchPointer(
  target: Element,
  type: 'pointercancel' | 'pointerdown' | 'pointermove' | 'pointerup',
  values: { pointerId: number; clientX: number; clientY: number; button?: number },
) {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperties(event, {
    pointerId: { value: values.pointerId },
    clientX: { value: values.clientX },
    clientY: { value: values.clientY },
    button: { value: values.button ?? 0 },
  });
  fireEvent(target, event);
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('Stage 7 Vision workspace', () => {
  it('keeps Vision Follow blocked in REAL / READ_ONLY commissioning', async () => {
    const backend = mockStage7Backend({
      controlMode: 'REAL',
      hardwareAccessPolicy: 'READ_ONLY',
      realMotionEnabled: false,
    });
    backend.selectDefaultTarget();
    renderVision();

    expect((await screen.findAllByText('READ ONLY')).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Start Real Follow' })).toBeDisabled();
    expect((await screen.findAllByText(/Commissioning READ ONLY · 禁止运动/)).length)
      .toBeGreaterThan(0);
    expect(backend.requestsFor('/vision/follow/start')).toHaveLength(0);
  });

  it('still obeys the Vision backend gate after the global Real capability is authorized', async () => {
    const backend = mockStage7Backend({
      controlMode: 'REAL',
      hardwareAccessPolicy: 'FULL',
      realMotionEnabled: true,
      realSessionScopes: ['REAL_VISION_FOLLOW'],
    });
    backend.selectDefaultTarget();
    renderVision();

    const start = await screen.findByRole('button', { name: 'Start Real Follow' });
    await waitFor(() => expect(start).toBeDisabled());
    expect((await screen.findAllByText(/Real Follow requires Stage 8 field acceptance/)).length)
      .toBeGreaterThan(0);
    expect(backend.requestsFor('/vision/follow/start')).toHaveLength(0);
  });

  it('renders an honest Synthetic-only provider workspace with no capture or director tools', async () => {
    mockStage7Backend();
    const view = renderVision();

    expect((await screen.findAllByText('SYNTHETIC_ONLY')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('synthetic-frame-source').length).toBeGreaterThan(0);
    expect(screen.getByText('opencv-haar-face')).toBeVisible();
    expect(screen.getByText('Optional OpenCV provider is not installed.')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Face detect' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Start Dry Run Follow' })).toBeDisabled();
    expect(screen.getByText('REAL FOLLOW BLOCKED')).toBeVisible();
    expect(screen.getByText('Not opened')).toBeVisible();
    expect(screen.queryByRole('button', { name: /photo|record|material|gesture|cinematic/i })).not.toBeInTheDocument();
    expect(view.container.querySelector('.vision-workspace')).toBeInTheDocument();
    expect(view.container.querySelector('.vision-controls')).toBeInTheDocument();
  });

  it('maps a pointer drag to the exact normalized frame ROI and starts then stops Dry Run Follow', async () => {
    const user = userEvent.setup();
    const backend = mockStage7Backend();
    renderVision();
    expect(await screen.findByText('synthetic-primary')).toBeVisible();
    const surface = await screen.findByRole('region', { name: 'Synthetic frame target selection surface' });
    vi.spyOn(surface, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, left: 0, top: 0, right: 1000, bottom: 500,
      width: 1000, height: 500, toJSON: () => ({}),
    });

    dispatchPointer(surface, 'pointerdown', { pointerId: 4, button: 0, clientX: 100, clientY: 100 });
    dispatchPointer(surface, 'pointermove', { pointerId: 4, clientX: 500, clientY: 300 });
    dispatchPointer(surface, 'pointerup', { pointerId: 4, clientX: 500, clientY: 300 });

    await waitFor(() => expect(backend.requestsFor('/vision/selection')).toHaveLength(1));
    const selectionBody = backend.lastBody('/vision/selection') as {
      frame_id: string;
      bounding_box: { x: number; y: number; width: number; height: number };
    };
    expect(selectionBody.frame_id).toBe(stage7Ids.frameId);
    expect(selectionBody.bounding_box.x).toBeCloseTo(0.1);
    expect(selectionBody.bounding_box.y).toBeCloseTo(0.2);
    expect(selectionBody.bounding_box.width).toBeCloseTo(0.4);
    expect(selectionBody.bounding_box.height).toBeCloseTo(0.4);
    expect((await screen.findAllByText('LOCKED')).length).toBeGreaterThan(0);

    const start = screen.getByRole('button', { name: 'Start Dry Run Follow' });
    expect(start).toBeEnabled();
    await user.click(start);
    await waitFor(() => expect(backend.requestsFor('/vision/follow/start')).toHaveLength(1));
    expect(backend.lastBody('/vision/follow/start')).toEqual(expect.objectContaining({
      mapping: {
        pan_joint: 'j11',
        tilt_joint: 'j12',
        pan_sign: 1,
        tilt_sign: -1,
        verification_status: 'VERIFIED_FOR_DRY_RUN',
      },
      configuration: expect.objectContaining({
        dead_zone_x: 0.08,
        dead_zone_y: 0.08,
        ema_alpha: 0.35,
        max_step: 2,
      }),
    }));
    expect(await screen.findByText('ACTIVE')).toBeVisible();
    expect(screen.getByText('0.160 / -0.080')).toBeVisible();

    await user.click(screen.getByRole('button', { name: /Stop Follow/ }));
    await waitFor(() => expect(backend.requestsFor(`/vision/follow/${stage7Ids.leaseId}/stop`)).toHaveLength(1));
    expect(await screen.findByText('Last stop · OPERATOR_STOP')).toBeVisible();
  });

  it('maps overlays to a configurable frame aspect and keeps ROI bound to pointer-down frame identity', async () => {
    const backend = mockStage7Backend({ frameWidthPx: 800, frameHeightPx: 600 });
    renderVision();
    await screen.findByText('synthetic-primary');
    const surface = await screen.findByRole('region', { name: 'Synthetic frame target selection surface' });
    expect((surface as HTMLElement).style.aspectRatio).toBe('800 / 600');
    vi.spyOn(surface, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, left: 0, top: 0, right: 800, bottom: 600,
      width: 800, height: 600, toJSON: () => ({}),
    });

    dispatchPointer(surface, 'pointerdown', { pointerId: 6, clientX: 80, clientY: 60 });
    dispatchPointer(surface, 'pointercancel', { pointerId: 6, clientX: 400, clientY: 300 });
    expect(backend.requestsFor('/vision/selection')).toHaveLength(0);

    const statusCount = backend.requestsFor('/vision/status').length;
    dispatchPointer(surface, 'pointerdown', { pointerId: 7, clientX: 80, clientY: 60 });
    backend.setFrameId('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa');
    await waitFor(() => expect(backend.requestsFor('/vision/status').length).toBeGreaterThan(statusCount));
    dispatchPointer(surface, 'pointermove', { pointerId: 7, clientX: 400, clientY: 300 });
    dispatchPointer(surface, 'pointerup', { pointerId: 7, clientX: 400, clientY: 300 });

    await waitFor(() => expect(backend.requestsFor('/vision/selection')).toHaveLength(1));
    expect(backend.lastBody('/vision/selection')).toEqual({
      frame_id: stage7Ids.frameId,
      bounding_box: { x: 0.1, y: 0.1, width: 0.4, height: 0.4 },
    });
  });

  it('runs an available local person detector, shows the detection, and binds it as the target', async () => {
    const user = userEvent.setup();
    const backend = mockStage7Backend();
    renderVision();

    await user.click(await screen.findByRole('button', { name: 'Person detect' }));
    await waitFor(() => expect(backend.requestsFor('/vision/detect/person')).toHaveLength(1));
    expect(backend.lastBody('/vision/detect/person')).toEqual({ frame_id: stage7Ids.frameId });
    await waitFor(() => expect(backend.requestsFor('/vision/selection')).toHaveLength(1));
    expect(await screen.findByLabelText('Tracked target bounding box')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Start Dry Run Follow' })).toBeEnabled();
  });

  it('lets priority Stop supersede an in-flight Follow start and compensates a late lease', async () => {
    const user = userEvent.setup();
    let releaseStart!: () => void;
    const startGate = new Promise<void>((resolve) => { releaseStart = resolve; });
    const backend = mockStage7Backend({ startGate });
    backend.selectDefaultTarget();
    renderVision();

    const start = await screen.findByRole('button', { name: 'Start Dry Run Follow' });
    expect(start).toBeEnabled();
    await user.click(start);
    expect(screen.getByRole('button', { name: /Stop Follow/ })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: /Stop Follow/ }));
    await act(async () => releaseStart());

    await waitFor(() => expect(
      backend.requestsFor(`/vision/follow/${stage7Ids.leaseId}/stop`),
    ).toHaveLength(1));
    expect(screen.queryByText('ACTIVE')).not.toBeInTheDocument();
  });

  it('compensates a Follow lease that arrives after the Vision page unmounts', async () => {
    const user = userEvent.setup();
    let releaseStart!: () => void;
    const startGate = new Promise<void>((resolve) => { releaseStart = resolve; });
    const backend = mockStage7Backend({ startGate });
    backend.selectDefaultTarget();
    const view = renderVision();

    await user.click(await screen.findByRole('button', { name: 'Start Dry Run Follow' }));
    await waitFor(() => expect(backend.requestsFor('/vision/follow/start')).toHaveLength(1));
    view.unmount();
    await act(async () => releaseStart());

    await waitFor(() => expect(
      backend.requestsFor(`/vision/follow/${stage7Ids.leaseId}/stop`),
    ).toHaveLength(1));
  });

  it('compensates a late Follow lease when runtime connectivity turns unavailable', async () => {
    const user = userEvent.setup();
    let releaseStart!: () => void;
    const startGate = new Promise<void>((resolve) => { releaseStart = resolve; });
    const backend = mockStage7Backend({ startGate });
    backend.selectDefaultTarget();
    renderVision();

    await user.click(await screen.findByRole('button', { name: 'Start Dry Run Follow' }));
    await waitFor(() => expect(backend.requestsFor('/vision/follow/start')).toHaveLength(1));
    backend.goOffline();
    await screen.findByText('Vision backend offline', {}, { timeout: 2500 });
    await act(async () => releaseStart());

    await waitFor(() => expect(
      backend.requestsFor(`/vision/follow/${stage7Ids.leaseId}/stop`),
    ).toHaveLength(1));
    expect(screen.queryByText('ACTIVE')).not.toBeInTheDocument();
  });

  it('serializes slow status polls so a stalled backend cannot accumulate requests', async () => {
    let releasePoll!: () => void;
    const pollStatusGate = new Promise<void>((resolve) => { releasePoll = resolve; });
    const backend = mockStage7Backend({ pollStatusGate });
    const view = renderVision();
    await screen.findByText('synthetic-primary');

    await waitFor(() => expect(backend.requestsFor('/vision/status')).toHaveLength(2));
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 650));
    });
    expect(backend.requestsFor('/vision/status')).toHaveLength(2);

    view.unmount();
    await act(async () => releasePoll());
  });

  it('surfaces target loss and stale tracking without reusing the last direction', async () => {
    const backend = mockStage7Backend();
    backend.selectDefaultTarget();
    renderVision();
    expect((await screen.findAllByText('LOCKED')).length).toBeGreaterThan(0);

    backend.setTrackingState('LOST');
    expect((await screen.findAllByText('LOST')).length).toBeGreaterThan(0);
    expect(screen.queryByLabelText('Tracked target bounding box')).not.toBeInTheDocument();
    expect(screen.getByText('Last stop · TARGET_LOST')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Start Dry Run Follow' })).toBeDisabled();

    backend.setTrackingState('STALE');
    expect((await screen.findAllByText('STALE')).length).toBeGreaterThan(0);
    expect(screen.getByText('Last stop · TARGET_STALE')).toBeVisible();
  });

  it('fails closed on a disconnected Vision source or a broken stream image', async () => {
    const backend = mockStage7Backend();
    backend.selectDefaultTarget();
    renderVision();
    const start = await screen.findByRole('button', { name: 'Start Dry Run Follow' });
    expect(start).toBeEnabled();

    const stream = screen.getByRole('img', { name: /Synthetic vision stream/ });
    fireEvent.error(stream);
    expect(await screen.findByText('Vision stream disconnected')).toBeVisible();
    expect(start).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Person detect' })).toBeDisabled();
    fireEvent.load(stream);
    expect(start).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Person detect' })).toBeEnabled();

    backend.setSourceState('DISCONNECTED');
    expect(await screen.findByText('Vision source disconnected')).toBeVisible();
    expect(start).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Person detect' })).toBeDisabled();
  });

  it('fails closed while Vision status polling is unavailable and recovers on a fresh status', async () => {
    const backend = mockStage7Backend();
    backend.selectDefaultTarget();
    renderVision();
    const start = await screen.findByRole('button', { name: 'Start Dry Run Follow' });
    expect(start).toBeEnabled();

    backend.setVisionStatusAvailable(false);
    expect(await screen.findByText('Vision status unavailable', {
      selector: '.vision-canvas__offline strong',
    })).toBeVisible();
    expect(start).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Person detect' })).toBeDisabled();

    backend.setVisionStatusAvailable(true);
    await waitFor(() => expect(screen.queryByText('Vision status unavailable', {
      selector: '.vision-canvas__offline strong',
    })).not.toBeInTheDocument());
    expect(start).toBeEnabled();
  });

  it('fails closed when the backend becomes unavailable and keeps Stop/source state explicit', async () => {
    const backend = mockStage7Backend();
    renderVision();
    expect((await screen.findAllByText('SYNTHETIC_ONLY')).length).toBeGreaterThan(0);
    backend.goOffline();

    expect(await screen.findByText('Vision backend offline', {}, { timeout: 2500 })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Start Dry Run Follow' })).toBeDisabled();
    expect(screen.getByText('POLICY PENDING')).toBeVisible();
  });
});
