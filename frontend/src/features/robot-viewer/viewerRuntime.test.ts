import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const runtimeSpies = vi.hoisted(() => ({
  controlsDispose: vi.fn(),
  controlsUpdate: vi.fn(),
  geometryDispose: vi.fn(),
  materialDispose: vi.fn(),
  observerDisconnect: vi.fn(),
  observerObserve: vi.fn(),
  rendererDispose: vi.fn(),
  renderListsDispose: vi.fn(),
  rendererForceContextLoss: vi.fn(),
  rendererSetAnimationLoop: vi.fn(),
  rendererSetPixelRatio: vi.fn(),
  rendererSetSize: vi.fn(),
  rendererRender: vi.fn(),
  robotSetJointValue: vi.fn(),
}));

const runtimeState = vi.hoisted(() => ({
  completeLoad: null as null | (() => void),
  deferLoad: false,
  joint: { ignoreLimits: false },
  loadedUrls: [] as string[],
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

class TestResizeObserver implements ResizeObserver {
  readonly disconnect = runtimeSpies.observerDisconnect;
  readonly observe = runtimeSpies.observerObserve;
  readonly unobserve = vi.fn();
}

describe('robot viewer runtime cleanup', () => {
  beforeEach(() => {
    for (const spy of Object.values(runtimeSpies)) spy.mockReset();
    runtimeState.joint.ignoreLimits = false;
    runtimeState.completeLoad = null;
    runtimeState.deferLoad = false;
    runtimeState.loadedUrls.length = 0;
    vi.stubGlobal('ResizeObserver', TestResizeObserver);
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
    expect(runtimeSpies.rendererSetAnimationLoop).toHaveBeenCalledWith(expect.any(Function));

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
});
