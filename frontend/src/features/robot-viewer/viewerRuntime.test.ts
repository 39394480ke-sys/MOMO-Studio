import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const runtimeSpies = vi.hoisted(() => ({
  controlsDispose: vi.fn(),
  controlsRemoveEventListener: vi.fn(),
  controlsUpdate: vi.fn(),
  cancelAnimationFrame: vi.fn(),
  geometryDispose: vi.fn(),
  materialDispose: vi.fn(),
  observerDisconnect: vi.fn(),
  observerObserve: vi.fn(),
  intersectionDisconnect: vi.fn(),
  intersectionObserve: vi.fn(),
  rendererDispose: vi.fn(),
  renderListsDispose: vi.fn(),
  rendererForceContextLoss: vi.fn(),
  rendererSetAnimationLoop: vi.fn(),
  rendererSetPixelRatio: vi.fn(),
  rendererSetSize: vi.fn(),
  rendererRender: vi.fn(),
  requestAnimationFrame: vi.fn(),
  robotSetJointValue: vi.fn(),
}));

const runtimeState = vi.hoisted(() => ({
  completeLoad: null as null | (() => void),
  deferLoad: false,
  joint: { ignoreLimits: false },
  loadedUrls: [] as string[],
  animationCallbacks: new Map<number, FrameRequestCallback>(),
  controlListeners: new Map<string, Set<() => void>>(),
  nextAnimationFrame: 1,
  intersectionCallback: null as IntersectionObserverCallback | null,
  mediaListeners: new Set<(event: MediaQueryListEvent) => void>(),
  reducedMotion: false,
}));

vi.mock('three', async (importOriginal) => {
  const actual = await importOriginal<typeof import('three')>();

  class TestWebGLRenderer {
    readonly shadowMap = { enabled: false, type: 0 };
    readonly renderLists = { dispose: runtimeSpies.renderListsDispose };
    outputColorSpace = '';
    setAnimationLoop = runtimeSpies.rendererSetAnimationLoop;
    setPixelRatio = runtimeSpies.rendererSetPixelRatio;
    setSize = runtimeSpies.rendererSetSize;
    render = runtimeSpies.rendererRender;
    dispose = runtimeSpies.rendererDispose;
    forceContextLoss = runtimeSpies.rendererForceContextLoss;
  }

  return { ...actual, WebGLRenderer: TestWebGLRenderer };
});

vi.mock('three/examples/jsm/controls/OrbitControls.js', () => ({
  OrbitControls: class TestOrbitControls {
    enableDamping = false;
    dampingFactor = 0;
    enableRotate = false;
    enableZoom = false;
    enablePan = false;
    minDistance = 0;
    maxDistance = 0;
    target = {
      set: vi.fn(),
      copy: vi.fn(),
    };
    update = runtimeSpies.controlsUpdate;
    dispose = runtimeSpies.controlsDispose;
    addEventListener(type: string, listener: () => void) {
      const listeners = runtimeState.controlListeners.get(type) ?? new Set();
      listeners.add(listener);
      runtimeState.controlListeners.set(type, listeners);
    }
    removeEventListener(type: string, listener: () => void) {
      runtimeSpies.controlsRemoveEventListener(type, listener);
      runtimeState.controlListeners.get(type)?.delete(listener);
    }
  },
}));

vi.mock('urdf-loader', async () => {
  const three = await import('three');
  return {
    default: class TestUrdfLoader {
      parseCollision = true;
      fetchOptions: RequestInit = {};
      constructor(private readonly manager: import('three').LoadingManager) {}
      load(
        url: string,
        onLoad: (robot: import('urdf-loader').URDFRobot) => void,
      ) {
        runtimeState.loadedUrls.push(url);
        this.manager.itemStart(url);
        const completeLoad = () => {
          const geometry = new three.BoxGeometry(1, 1, 1);
          const material = new three.MeshBasicMaterial();
          geometry.dispose = runtimeSpies.geometryDispose;
          material.dispose = runtimeSpies.materialDispose;
          const robot = new three.Group() as unknown as import('urdf-loader').URDFRobot;
          robot.joints = { J10: runtimeState.joint as import('urdf-loader').URDFJoint };
          robot.setJointValue = runtimeSpies.robotSetJointValue;
          robot.add(new three.Mesh(geometry, material));
          onLoad(robot);
          this.manager.itemEnd(url);
        };
        if (runtimeState.deferLoad) {
          runtimeState.completeLoad = completeLoad;
        } else {
          completeLoad();
        }
      }
    },
  };
});

import { createRobotViewerRuntime } from './viewerRuntime';
import type { RobotViewerAssetManifest, RobotViewerAssetVariant } from './viewerAssets';

class TestResizeObserver implements ResizeObserver {
  readonly disconnect = runtimeSpies.observerDisconnect;
  readonly observe = runtimeSpies.observerObserve;
  readonly unobserve = vi.fn();
}

class TestIntersectionObserver implements IntersectionObserver {
  readonly root = null;
  readonly rootMargin = '0px';
  readonly thresholds = [0];
  readonly disconnect = runtimeSpies.intersectionDisconnect;
  readonly observe = runtimeSpies.intersectionObserve;
  readonly takeRecords = () => [];
  readonly unobserve = vi.fn();

  constructor(callback: IntersectionObserverCallback) {
    runtimeState.intersectionCallback = callback;
  }
}

function testAssets(variant: RobotViewerAssetVariant): RobotViewerAssetManifest {
  return {
    variant,
    urdfUrl: `/robot-${variant.toLowerCase()}/urdf/${variant.toLowerCase()}/soarmoce_urdf.urdf`,
    meshUrlsByFilename: {},
    jointNamesByProfileJointId: { j10: 'J10' },
  };
}

function flushAnimationFrame(time = 0): void {
  const next = runtimeState.animationCallbacks.entries().next().value as
    | [number, FrameRequestCallback]
    | undefined;
  if (!next) throw new Error('No animation frame was scheduled');
  runtimeState.animationCallbacks.delete(next[0]);
  next[1](time);
}

function emitControlEvent(type: 'start' | 'change' | 'end'): void {
  for (const listener of runtimeState.controlListeners.get(type) ?? []) listener();
}

function setDocumentVisibility(state: DocumentVisibilityState): void {
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: state });
  document.dispatchEvent(new Event('visibilitychange'));
}

describe('robot viewer runtime cleanup', () => {
  beforeEach(() => {
    for (const spy of Object.values(runtimeSpies)) spy.mockReset();
    runtimeState.joint.ignoreLimits = false;
    runtimeState.completeLoad = null;
    runtimeState.deferLoad = false;
    runtimeState.loadedUrls.length = 0;
    runtimeState.animationCallbacks.clear();
    runtimeState.controlListeners.clear();
    runtimeState.nextAnimationFrame = 1;
    runtimeState.intersectionCallback = null;
    runtimeState.mediaListeners.clear();
    runtimeState.reducedMotion = false;
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    runtimeSpies.controlsUpdate.mockReturnValue(false);
    runtimeSpies.requestAnimationFrame.mockImplementation((callback: FrameRequestCallback) => {
      const frame = runtimeState.nextAnimationFrame;
      runtimeState.nextAnimationFrame += 1;
      runtimeState.animationCallbacks.set(frame, callback);
      return frame;
    });
    runtimeSpies.cancelAnimationFrame.mockImplementation((frame: number) => {
      runtimeState.animationCallbacks.delete(frame);
    });
    vi.stubGlobal('ResizeObserver', TestResizeObserver);
    vi.stubGlobal('requestAnimationFrame', runtimeSpies.requestAnimationFrame);
    vi.stubGlobal('cancelAnimationFrame', runtimeSpies.cancelAnimationFrame);
    vi.stubGlobal('matchMedia', vi.fn().mockImplementation(() => ({
      matches: runtimeState.reducedMotion,
      addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
        runtimeState.mediaListeners.add(listener);
      },
      removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
        runtimeState.mediaListeners.delete(listener);
      },
    })));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('cleans the loop, controls, observer, scene resources and WebGL renderer', () => {
    const host = document.createElement('div');
    Object.defineProperty(host, 'clientWidth', { configurable: true, value: 640 });
    Object.defineProperty(host, 'clientHeight', { configurable: true, value: 480 });
    const canvas = document.createElement('canvas');
    const onReady = vi.fn();
    const onError = vi.fn();

    const runtime = createRobotViewerRuntime({
      assets: testAssets('V2'),
      host,
      canvas,
      variant: 'V2',
      initialJointValues: { j10: 0.125 },
      onReady,
      onError,
    });

    expect(onError).not.toHaveBeenCalled();
    expect(onReady).toHaveBeenCalledTimes(1);
    expect(runtimeSpies.robotSetJointValue).toHaveBeenCalledWith('J10', 0.125);
    expect(runtimeState.joint.ignoreLimits).toBe(true);
    expect(runtimeSpies.observerObserve).toHaveBeenCalledWith(host);
    expect(runtimeSpies.rendererSetSize).toHaveBeenCalledWith(640, 480, false);
    expect(runtimeSpies.rendererSetAnimationLoop).not.toHaveBeenCalled();
    flushAnimationFrame();
    expect(runtimeSpies.rendererRender).toHaveBeenCalledTimes(1);
    expect(runtimeState.animationCallbacks.size).toBe(0);

    runtime.dispose();
    runtime.dispose();

    expect(runtimeSpies.observerDisconnect).toHaveBeenCalledTimes(1);
    expect(runtimeSpies.rendererSetAnimationLoop).toHaveBeenLastCalledWith(null);
    expect(runtimeSpies.controlsDispose).toHaveBeenCalledTimes(1);
    expect(runtimeSpies.geometryDispose).toHaveBeenCalledTimes(1);
    expect(runtimeSpies.materialDispose).toHaveBeenCalledTimes(1);
    expect(runtimeSpies.renderListsDispose).toHaveBeenCalledTimes(1);
    expect(runtimeSpies.rendererDispose).toHaveBeenCalledTimes(1);
    expect(runtimeSpies.rendererForceContextLoss).toHaveBeenCalledTimes(1);
  });

  it('selects the requested V1 asset manifest', () => {
    const host = document.createElement('div');
    Object.defineProperty(host, 'clientWidth', { configurable: true, value: 320 });
    Object.defineProperty(host, 'clientHeight', { configurable: true, value: 240 });
    const runtime = createRobotViewerRuntime({
      assets: testAssets('V1'),
      host,
      canvas: document.createElement('canvas'),
      variant: 'V1',
      initialJointValues: {},
      onReady: vi.fn(),
      onError: vi.fn(),
    });

    expect(runtimeState.loadedUrls).toHaveLength(1);
    expect(runtimeState.loadedUrls[0]).toMatch(/robot-v1\/urdf\/v1\/soarmoce_urdf\.urdf/);

    runtime.dispose();
  });

  it('disposes resources exactly once when loading completes after teardown', () => {
    runtimeState.deferLoad = true;
    const host = document.createElement('div');
    Object.defineProperty(host, 'clientWidth', { configurable: true, value: 320 });
    Object.defineProperty(host, 'clientHeight', { configurable: true, value: 240 });
    const onReady = vi.fn();
    const runtime = createRobotViewerRuntime({
      assets: testAssets('V2'),
      host,
      canvas: document.createElement('canvas'),
      variant: 'V2',
      initialJointValues: { j10: 0 },
      onReady,
      onError: vi.fn(),
    });

    runtime.dispose();
    expect(runtimeSpies.geometryDispose).not.toHaveBeenCalled();
    runtimeState.completeLoad?.();

    expect(onReady).not.toHaveBeenCalled();
    expect(runtimeSpies.geometryDispose).toHaveBeenCalledTimes(1);
    expect(runtimeSpies.materialDispose).toHaveBeenCalledTimes(1);
    expect(runtimeSpies.rendererDispose).toHaveBeenCalledTimes(1);
    expect(runtimeSpies.rendererForceContextLoss).toHaveBeenCalledTimes(1);
  });

  it('fails closed and refuses later updates when a Profile joint is absent from the loaded URDF', () => {
    const host = document.createElement('div');
    Object.defineProperty(host, 'clientWidth', { configurable: true, value: 320 });
    Object.defineProperty(host, 'clientHeight', { configurable: true, value: 240 });
    const onReady = vi.fn();
    const onError = vi.fn();
    const runtime = createRobotViewerRuntime({
      assets: testAssets('V2'),
      host,
      canvas: document.createElement('canvas'),
      variant: 'V2',
      initialJointValues: { j11: 0 },
      onReady,
      onError,
    });

    expect(onReady).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({
      code: 'JOINT_MAPPING_MISMATCH',
    }));
    runtime.setJointValues({ j10: 0.25 });
    expect(runtimeSpies.robotSetJointValue).not.toHaveBeenCalled();

    runtime.dispose();
  });

  it('renders static state only on invalidation from joints or Orbit interaction', () => {
    const host = document.createElement('div');
    const runtime = createRobotViewerRuntime({
      assets: testAssets('V2'),
      host,
      canvas: document.createElement('canvas'),
      variant: 'V2',
      initialJointValues: { j10: 0 },
      onReady: vi.fn(),
      onError: vi.fn(),
    });

    flushAnimationFrame();
    expect(runtimeState.animationCallbacks.size).toBe(0);

    runtime.setJointValues({ j10: 0.1 });
    expect(runtimeState.animationCallbacks.size).toBe(1);
    flushAnimationFrame();
    expect(runtimeState.animationCallbacks.size).toBe(0);

    emitControlEvent('start');
    flushAnimationFrame();
    expect(runtimeState.animationCallbacks.size).toBe(1);
    emitControlEvent('end');
    flushAnimationFrame();
    expect(runtimeState.animationCallbacks.size).toBe(0);
    expect(runtimeSpies.rendererRender).toHaveBeenCalledTimes(4);

    runtime.dispose();
  });

  it('renders continuously only while playback is active and stops after pause', () => {
    const runtime = createRobotViewerRuntime({
      assets: testAssets('V2'),
      host: document.createElement('div'),
      canvas: document.createElement('canvas'),
      variant: 'V2',
      initialJointValues: { j10: 0 },
      onReady: vi.fn(),
      onError: vi.fn(),
    });
    flushAnimationFrame();

    runtime.setPlaybackActive(true);
    flushAnimationFrame();
    expect(runtimeState.animationCallbacks.size).toBe(1);
    runtime.setPlaybackActive(false);
    flushAnimationFrame();
    expect(runtimeState.animationCallbacks.size).toBe(0);

    runtime.dispose();
  });

  it('pauses while the document is hidden and resumes when visible', () => {
    const runtime = createRobotViewerRuntime({
      assets: testAssets('V2'),
      host: document.createElement('div'),
      canvas: document.createElement('canvas'),
      variant: 'V2',
      initialJointValues: { j10: 0 },
      onReady: vi.fn(),
      onError: vi.fn(),
    });
    flushAnimationFrame();
    runtime.setPlaybackActive(true);
    expect(runtimeState.animationCallbacks.size).toBe(1);

    setDocumentVisibility('hidden');
    expect(runtimeState.animationCallbacks.size).toBe(0);
    setDocumentVisibility('visible');
    expect(runtimeState.animationCallbacks.size).toBe(1);
    flushAnimationFrame();
    expect(runtimeState.animationCallbacks.size).toBe(1);

    runtime.dispose();
  });

  it('does not render while offscreen and invalidates once when intersecting again', () => {
    vi.stubGlobal('IntersectionObserver', TestIntersectionObserver);
    const host = document.createElement('div');
    const runtime = createRobotViewerRuntime({
      assets: testAssets('V2'),
      host,
      canvas: document.createElement('canvas'),
      variant: 'V2',
      initialJointValues: { j10: 0 },
      onReady: vi.fn(),
      onError: vi.fn(),
    });
    expect(runtimeSpies.intersectionObserve).toHaveBeenCalledWith(host);
    expect(runtimeState.animationCallbacks.size).toBe(0);

    runtimeState.intersectionCallback?.([
      { target: host, isIntersecting: true } as unknown as IntersectionObserverEntry,
    ], {} as IntersectionObserver);
    expect(runtimeState.animationCallbacks.size).toBe(1);
    flushAnimationFrame();

    runtime.setJointValues({ j10: 0.2 });
    runtimeState.intersectionCallback?.([
      { target: host, isIntersecting: false } as unknown as IntersectionObserverEntry,
    ], {} as IntersectionObserver);
    expect(runtimeState.animationCallbacks.size).toBe(0);
    runtime.setJointValues({ j10: 0.3 });
    expect(runtimeState.animationCallbacks.size).toBe(0);

    runtimeState.intersectionCallback?.([
      { target: host, isIntersecting: true } as unknown as IntersectionObserverEntry,
    ], {} as IntersectionObserver);
    flushAnimationFrame();
    expect(runtimeSpies.rendererRender).toHaveBeenCalledTimes(2);

    runtime.dispose();
    expect(runtimeSpies.intersectionDisconnect).toHaveBeenCalledTimes(1);
  });

  it('honors reduced motion by avoiding a continuous playback render loop', () => {
    runtimeState.reducedMotion = true;
    const runtime = createRobotViewerRuntime({
      assets: testAssets('V2'),
      host: document.createElement('div'),
      canvas: document.createElement('canvas'),
      variant: 'V2',
      initialJointValues: { j10: 0 },
      onReady: vi.fn(),
      onError: vi.fn(),
    });
    flushAnimationFrame();
    runtime.setPlaybackActive(true);
    flushAnimationFrame();
    expect(runtimeState.animationCallbacks.size).toBe(0);

    runtime.dispose();
  });
});
