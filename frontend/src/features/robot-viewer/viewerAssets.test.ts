import { describe, expect, it } from 'vitest';

import v1UrdfSource from '../../assets/robot-v1/urdf/v1/soarmoce_urdf.urdf?raw';
import v2UrdfSource from '../../assets/robot-v2/urdf/v2/soarmoce_urdf.urdf?raw';
import assetLoaderSource from './viewerAssets.ts?raw';
import { loadRobotViewerAssets } from './viewerAssets';

function referencedMeshes(urdf: string): string[] {
  return Array.from(
    urdf.matchAll(/<mesh\s+filename="[^"]*\/([^/"]+\.stl)"\s*\/>/g),
    (match) => match[1],
  );
}

describe('robot viewer asset manifests', () => {
  it('adapts the authored Legacy V1 geometry to the no-rail product contract', () => {
    expect(v1UrdfSource).toContain('<joint name="V1_BASE_FIXED" type="fixed">');
    expect(v1UrdfSource).not.toMatch(/<joint name="J10"/);
    expect(v1UrdfSource).not.toMatch(/type="prismatic"/);
    expect(v1UrdfSource).toMatch(/<joint name="J11" type="revolute">/);
    expect(v1UrdfSource).toMatch(/<joint name="J15" type="revolute">/);
  });

  it('maps every referenced mesh and keeps V1/V2 manifests in lazy variant chunks', async () => {
    const ROBOT_V1_ASSETS = await loadRobotViewerAssets('V1');
    const ROBOT_V2_ASSETS = await loadRobotViewerAssets('V2');
    const v1References = new Set(referencedMeshes(v1UrdfSource));
    const v2References = new Set(referencedMeshes(v2UrdfSource));
    expect(v1References).toEqual(new Set(Object.keys(ROBOT_V1_ASSETS.meshUrlsByFilename)));
    expect(v1References).toEqual(new Set([
      'base_link.stl',
      'Link_1.stl',
      'Link_2.stl',
      'Link_3.stl',
      'Link_4.stl',
      'Link_5.stl',
      'Link_6.stl',
    ]));
    expect(v2References).toEqual(new Set(Object.keys(ROBOT_V2_ASSETS.meshUrlsByFilename)));
    expect(v2UrdfSource).toMatch(/<joint name="J10" type="prismatic">/);
    expect(v2UrdfSource).toMatch(/<joint name="J15" type="revolute">/);
    expect(ROBOT_V1_ASSETS.meshUrlsByFilename).not.toHaveProperty('Link_7.stl');
    expect(ROBOT_V2_ASSETS.meshUrlsByFilename).not.toHaveProperty('Link_1.stl');
    expect(ROBOT_V1_ASSETS.jointNamesByProfileJointId).toEqual({
      j11: 'J11',
      j12: 'J12',
      j13: 'J13',
      j14: 'J14',
      j15: 'J15',
    });
    expect(ROBOT_V1_ASSETS.jointNamesByProfileJointId).not.toHaveProperty('j10');
    expect(ROBOT_V2_ASSETS.jointNamesByProfileJointId).toHaveProperty('j10', 'J10');
    expect(assetLoaderSource).toContain("import('./viewerAssetsV1')");
    expect(assetLoaderSource).toContain("import('./viewerAssetsV2')");
    expect(assetLoaderSource).not.toMatch(/robot-v[12]\/meshes/);
  });
});
