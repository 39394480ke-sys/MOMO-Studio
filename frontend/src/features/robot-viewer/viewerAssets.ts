export interface RobotViewerAssetManifest {
  readonly variant: RobotViewerAssetVariant;
  readonly urdfUrl: string;
  readonly meshUrlsByFilename: Readonly<Record<string, string>>;
  readonly jointNamesByProfileJointId: Readonly<Record<string, string>>;
}

export type RobotViewerAssetVariant = 'V1' | 'V2';

/** Load only the selected variant's URL manifest and asset chunk. */
export async function loadRobotViewerAssets(
  variant: RobotViewerAssetVariant,
): Promise<RobotViewerAssetManifest> {
  if (variant === 'V1') {
    return (await import('./viewerAssetsV1')).ROBOT_V1_ASSETS;
  }
  return (await import('./viewerAssetsV2')).ROBOT_V2_ASSETS;
}
