import type { RobotViewerAssetManifest } from './viewerAssets';

/** V1 URLs live in a variant-only lazy chunk. */
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
