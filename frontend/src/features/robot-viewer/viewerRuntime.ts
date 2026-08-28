import {
  Box3,
  BufferGeometry,
  Color,
  DirectionalLight,
  GridHelper,
  HemisphereLight,
  LoadingManager,
  Material,
  Mesh,
  Object3D,
  PCFSoftShadowMap,
  PerspectiveCamera,
  Scene,
  SRGBColorSpace,
  Texture,
  Vector3,
  WebGLRenderer,
} from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import URDFLoader, { type URDFRobot } from 'urdf-loader';

import {
  ROBOT_VIEWER_ASSETS,
  type RobotViewerAssetManifest,
  type RobotViewerAssetVariant,
} from './viewerAssets';

export type RobotViewerRuntimeErrorCode =
  | 'WEBGL_UNAVAILABLE'
  | 'RESIZE_OBSERVER_UNAVAILABLE'
  | 'ASSET_LOAD_FAILED'
  | 'INVALID_MODEL'
  | 'JOINT_MAPPING_MISMATCH';

export class RobotViewerRuntimeError extends Error {
  readonly code: RobotViewerRuntimeErrorCode;

  constructor(code: RobotViewerRuntimeErrorCode, message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = 'RobotViewerRuntimeError';
    this.code = code;
  }
}

export interface RobotViewerRuntime {
  setJointValues(values: Readonly<Record<string, number>>): void;
  dispose(): void;
}

export interface CreateRobotViewerRuntimeOptions {
  readonly host: HTMLElement;
  readonly canvas: HTMLCanvasElement;
  readonly variant: RobotViewerAssetVariant;
  readonly assets?: RobotViewerAssetManifest;
  readonly initialJointValues: Readonly<Record<string, number>>;
  readonly onReady: () => void;
  readonly onError: (error: RobotViewerRuntimeError) => void;
}

function textureValues(material: Material): Texture[] {
  return Object.values(material as unknown as Record<string, unknown>).filter(
    (value): value is Texture => value instanceof Texture,
  );
}

interface ObjectResourceDisposalRegistry {
  readonly geometries: WeakSet<BufferGeometry>;
  readonly materials: WeakSet<Material>;
  readonly textures: WeakSet<Texture>;
}

function createDisposalRegistry(): ObjectResourceDisposalRegistry {
  return {
    geometries: new WeakSet(),
    materials: new WeakSet(),
    textures: new WeakSet(),
  };
}

function disposeMaterial(
  material: Material,
  registry: ObjectResourceDisposalRegistry,
): void {
  for (const texture of textureValues(material)) {
    if (registry.textures.has(texture)) continue;
    registry.textures.add(texture);
    texture.dispose();
  }
  if (registry.materials.has(material)) return;
  registry.materials.add(material);
  material.dispose();
}

/** Dispose geometries, materials and direct material textures exactly once. */
export function disposeObjectResources(
  root: Object3D,
  registry = createDisposalRegistry(),
): void {
  const geometries = new Set<BufferGeometry>();
  const materials = new Set<Material>();

  root.traverse((object) => {
    const resourceObject = object as Object3D & {
      geometry?: BufferGeometry;
      material?: Material | Material[];
    };
    if (resourceObject.geometry instanceof BufferGeometry) {
      geometries.add(resourceObject.geometry);
    }
    const objectMaterials = resourceObject.material === undefined
      ? []
      : Array.isArray(resourceObject.material)
        ? resourceObject.material
        : [resourceObject.material];
    for (const material of objectMaterials) materials.add(material);
  });

  for (const geometry of geometries) {
    if (registry.geometries.has(geometry)) continue;
    registry.geometries.add(geometry);
    geometry.dispose();
  }
  for (const material of materials) disposeMaterial(material, registry);
}

function filenameFromUrl(url: string): string {
  const cleanUrl = url.split(/[?#]/, 1)[0] ?? url;
  const encodedFilename = cleanUrl.slice(cleanUrl.lastIndexOf('/') + 1);
  try {
    return decodeURIComponent(encodedFilename);
  } catch {
    return encodedFilename;
  }
}

function configureModel(robot: URDFRobot): void {
  // Product profile limits are validated and applied at the named domain -> URDF
  // boundary before values reach this runtime. Imported authored URDF files can carry
  // provisional limits that differ from the active Product Profile, so the runtime must
  // not silently clamp the already-bounded display values a second time.
  for (const joint of Object.values(robot.joints)) joint.ignoreLimits = true;

  robot.rotation.x = -Math.PI / 2;
  robot.traverse((object) => {
    if (!(object instanceof Mesh)) return;
    object.castShadow = true;
    object.receiveShadow = true;
    object.geometry.computeVertexNormals();

    const materials = Array.isArray(object.material) ? object.material : [object.material];
    for (const material of materials) {
      const colored = material as Material & { color?: Color };
      colored.color?.set('#7f8b94');
      material.needsUpdate = true;
    }
  });
}

function frameModel(
  robot: URDFRobot,
  camera: PerspectiveCamera,
  controls: OrbitControls,
): boolean {
  const bounds = new Box3().setFromObject(robot);
  if (bounds.isEmpty()) return false;

  const size = bounds.getSize(new Vector3());
  const largestDimension = Math.max(size.x, size.y, size.z);
  if (!Number.isFinite(largestDimension) || largestDimension <= 0) return false;

  robot.scale.setScalar(0.82 / largestDimension);
  const scaled = new Box3().setFromObject(robot);
  const center = scaled.getCenter(new Vector3());
  robot.position.set(-center.x, -scaled.min.y, -center.z);

  const framed = new Box3().setFromObject(robot);
  const framedCenter = framed.getCenter(new Vector3());
  const framedSize = framed.getSize(new Vector3());
  const radius = Math.max(framedSize.length(), 0.5);
  controls.target.copy(framedCenter);
  camera.position.copy(framedCenter).add(
    new Vector3(radius * 1.1, radius * 0.8, radius * 1.25),
  );
  camera.near = radius / 100;
  camera.far = radius * 100;
  camera.updateProjectionMatrix();
  controls.update();
  return true;
}

function asRuntimeError(
  error: unknown,
  variant: RobotViewerAssetVariant,
): RobotViewerRuntimeError {
  if (error instanceof RobotViewerRuntimeError) return error;
  return new RobotViewerRuntimeError(
    'ASSET_LOAD_FAILED',
    `The ${variant} URDF or one of its STL assets could not be loaded.`,
    { cause: error },
  );
}

export function createRobotViewerRuntime({
  host,
  canvas,
  variant,
  assets,
  initialJointValues,
  onReady,
  onError,
}: CreateRobotViewerRuntimeOptions): RobotViewerRuntime {
  const selectedAssets = assets ?? ROBOT_VIEWER_ASSETS[variant];
  let renderer: WebGLRenderer;
  try {
    renderer = new WebGLRenderer({
      canvas,
      antialias: true,
      powerPreference: 'high-performance',
    });
  } catch (error) {
    throw new RobotViewerRuntimeError(
      'WEBGL_UNAVAILABLE',
      'WebGL could not be initialized for the 3D viewer.',
      { cause: error },
    );
  }

  if (typeof ResizeObserver === 'undefined') {
    renderer.dispose();
    renderer.forceContextLoss();
    throw new RobotViewerRuntimeError(
      'RESIZE_OBSERVER_UNAVAILABLE',
      'ResizeObserver is unavailable, so the 3D viewport cannot be sized safely.',
    );
  }

  const scene = new Scene();
  scene.background = new Color('#eef2f4');
  const camera = new PerspectiveCamera(38, 1, 0.005, 50);
  camera.position.set(1.15, 0.85, 1.25);

  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = PCFSoftShadowMap;
  renderer.outputColorSpace = SRGBColorSpace;

  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.enableRotate = true;
  controls.enableZoom = true;
  controls.enablePan = true;
  controls.target.set(0, 0.28, 0);
  controls.minDistance = 0.2;
  controls.maxDistance = 5;

  scene.add(new HemisphereLight(0xffffff, 0x52606a, 1.35));
  const keyLight = new DirectionalLight(0xffffff, 1.75);
  keyLight.position.set(1.6, 2.4, 1.4);
  keyLight.castShadow = true;
  scene.add(keyLight);
  const fillLight = new DirectionalLight(0xb8d4ff, 0.5);
  fillLight.position.set(-1.2, 0.9, -1.4);
  scene.add(fillLight);
  scene.add(new GridHelper(1.8, 18, 0x87949c, 0xcbd3d8));

  let disposed = false;
  let failed = false;
  let robot: URDFRobot | null = null;
  let jointValues = initialJointValues;
  const abortController = new AbortController();
  const disposalRegistry = createDisposalRegistry();

  const fail = (error: unknown): void => {
    if (disposed || failed) return;
    failed = true;
    onError(asRuntimeError(error, variant));
  };

  const applyJointValues = (): void => {
    if (robot === null) return;
    for (const [profileJointId, value] of Object.entries(jointValues)) {
      if (!Number.isFinite(value)) continue;
      const urdfJointName = selectedAssets.jointNamesByProfileJointId[profileJointId];
      if (urdfJointName === undefined || robot.joints[urdfJointName] === undefined) {
        fail(new RobotViewerRuntimeError(
          'JOINT_MAPPING_MISMATCH',
          `${variant} viewer joint mapping is incomplete for ${profileJointId}.`,
        ));
        return;
      }
      robot.setJointValue(urdfJointName, value);
    }
  };

  const manager = new LoadingManager();
  manager.setURLModifier((url) => {
    const emittedUrl = selectedAssets.meshUrlsByFilename[filenameFromUrl(url)];
    return emittedUrl ?? url;
  });
  manager.onError = (url) => {
    fail(new RobotViewerRuntimeError(
      'ASSET_LOAD_FAILED',
      `A required ${variant} model asset failed to load: ${filenameFromUrl(url) || 'unknown asset'}.`,
    ));
  };
  manager.onLoad = () => {
    if (robot === null) return;
    if (disposed) {
      disposeObjectResources(robot, disposalRegistry);
      return;
    }
    if (failed) return;
    if (!frameModel(robot, camera, controls)) {
      fail(new RobotViewerRuntimeError(
        'INVALID_MODEL',
        `The ${variant} model loaded without usable geometry.`,
      ));
      return;
    }
    onReady();
  };

  const loader = new URDFLoader(manager);
  loader.parseCollision = false;
  loader.fetchOptions = { signal: abortController.signal };
  loader.load(
    selectedAssets.urdfUrl,
    (loadedRobot) => {
      robot = loadedRobot;
      if (disposed) {
        disposeObjectResources(loadedRobot, disposalRegistry);
        return;
      }
      configureModel(loadedRobot);
      applyJointValues();
      scene.add(loadedRobot);
    },
    undefined,
    fail,
  );

  const resize = (): void => {
    if (disposed) return;
    const width = Math.max(1, host.clientWidth);
    const height = Math.max(1, host.clientHeight);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  };
  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(host);
  resize();

  renderer.setAnimationLoop(() => {
    if (disposed) return;
    controls.update();
    renderer.render(scene, camera);
  });

  return {
    setJointValues(values) {
      if (disposed || failed) return;
      jointValues = values;
      applyJointValues();
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      abortController.abort();
      resizeObserver.disconnect();
      renderer.setAnimationLoop(null);
      controls.dispose();
      disposeObjectResources(scene, disposalRegistry);
      scene.clear();
      renderer.renderLists.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
    },
  };
}
