import type { RobotViewerAssetManifest } from './viewerAssets';

/** V2 URLs live in a variant-only lazy chunk. */
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
