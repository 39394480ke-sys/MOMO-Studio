export interface RobotViewerAssetManifest {
  readonly variant: RobotViewerAssetVariant;
  readonly urdfUrl: string;
  readonly meshUrlsByFilename: Readonly<Record<string, string>>;
  readonly jointNamesByProfileJointId: Readonly<Record<string, string>>;
}

export type RobotViewerAssetVariant = 'V1' | 'V2';

/**
 * Every mesh is referenced explicitly so Vite emits it even though the URDF discovers
 * mesh paths at runtime. The runtime URL modifier resolves those authored references.
 */
export const ROBOT_V1_ASSETS: RobotViewerAssetManifest = Object.freeze({
  variant: 'V1',
  urdfUrl: new URL(
    '../../assets/robot-v1/urdf/v1/soarmoce_urdf.urdf',
    import.meta.url,
  ).href,
  meshUrlsByFilename: Object.freeze({
    'base_link.stl': new URL(
      '../../assets/robot-v1/meshes/v1/base_link.stl',
      import.meta.url,
    ).href,
    'Link_1.stl': new URL(
      '../../assets/robot-v1/meshes/v1/Link_1.stl',
      import.meta.url,
    ).href,
    'Link_2.stl': new URL(
      '../../assets/robot-v1/meshes/v1/Link_2.stl',
      import.meta.url,
    ).href,
    'Link_3.stl': new URL(
      '../../assets/robot-v1/meshes/v1/Link_3.stl',
      import.meta.url,
    ).href,
    'Link_4.stl': new URL(
      '../../assets/robot-v1/meshes/v1/Link_4.stl',
      import.meta.url,
    ).href,
    'Link_5.stl': new URL(
      '../../assets/robot-v1/meshes/v1/Link_5.stl',
      import.meta.url,
    ).href,
    'Link_6.stl': new URL(
      '../../assets/robot-v1/meshes/v1/Link_6.stl',
      import.meta.url,
    ).href,
  }),
  jointNamesByProfileJointId: Object.freeze({
    j11: 'J11',
    j12: 'J12',
    j13: 'J13',
    j14: 'J14',
    j15: 'J15',
  }),
});

export const ROBOT_V2_ASSETS: RobotViewerAssetManifest = Object.freeze({
  variant: 'V2',
  urdfUrl: new URL(
    '../../assets/robot-v2/urdf/v2/soarmoce_urdf.urdf',
    import.meta.url,
  ).href,
  meshUrlsByFilename: Object.freeze({
    'base_link.stl': new URL(
      '../../assets/robot-v2/meshes/v2/base_link.stl',
      import.meta.url,
    ).href,
    'Link_2.stl': new URL(
      '../../assets/robot-v2/meshes/v2/Link_2.stl',
      import.meta.url,
    ).href,
    'Link_3.stl': new URL(
      '../../assets/robot-v2/meshes/v2/Link_3.stl',
      import.meta.url,
    ).href,
    'Link_4.stl': new URL(
      '../../assets/robot-v2/meshes/v2/Link_4.stl',
      import.meta.url,
    ).href,
    'Link_5.stl': new URL(
      '../../assets/robot-v2/meshes/v2/Link_5.stl',
      import.meta.url,
    ).href,
    'Link_6.stl': new URL(
      '../../assets/robot-v2/meshes/v2/Link_6.stl',
      import.meta.url,
    ).href,
    'Link_7.stl': new URL(
      '../../assets/robot-v2/meshes/v2/Link_7.stl',
      import.meta.url,
    ).href,
  }),
  jointNamesByProfileJointId: Object.freeze({
    j10: 'J10',
    j11: 'J11',
    j12: 'J12',
    j13: 'J13',
    j14: 'J14',
    j15: 'J15',
  }),
});

export const ROBOT_VIEWER_ASSETS: Readonly<
  Record<RobotViewerAssetVariant, RobotViewerAssetManifest>
> = Object.freeze({
  V1: ROBOT_V1_ASSETS,
  V2: ROBOT_V2_ASSETS,
});
