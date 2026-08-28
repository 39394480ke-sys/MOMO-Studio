import { PanelRightOpen } from 'lucide-react';

import type {
  DomainUnit,
  MotionKeyframe,
  ProfileJointDefinition,
  RobotVariant,
} from '../../api/types';
import { Robot3DViewer } from '../robot-viewer';

interface StudioViewerProps {
  runtimeMode: 'DRY RUN' | 'REAL';
  selectedFrame: MotionKeyframe | null;
  viewerEnabledJointIds: readonly string[];
  viewerJointDefinitions: readonly ProfileJointDefinition[];
  viewerJointPositions: Readonly<Record<string, number>>;
  viewerJointUnits: Readonly<Record<string, DomainUnit | undefined>>;
  viewerVariant: RobotVariant;
  onOpenInspector: () => void;
}

export function StudioViewer({
  runtimeMode,
  selectedFrame,
  viewerEnabledJointIds,
  viewerJointDefinitions,
  viewerJointPositions,
  viewerJointUnits,
  viewerVariant,
  onOpenInspector,
}: StudioViewerProps) {
  return (
    <section aria-labelledby="studio-viewer-heading" className="studio-viewer">
      <header className="studio-panel-heading studio-viewer__heading">
        <div>
          <p className="section-kicker">Camera / trajectory preview</p>
          <h2 id="studio-viewer-heading">3D 仿真视图</h2>
        </div>
        <div className="studio-viewer__badges">
          <span className="dry-run-badge">{runtimeMode}</span>
          <span className="simulation-badge">SIMULATION</span>
          {selectedFrame ? <span className="studio-keyframe-badge">{selectedFrame.label}</span> : null}
          <button
            aria-label="打开关键帧属性"
            className="mini-command studio-viewer__inspector-button"
            disabled={!selectedFrame}
            onClick={onOpenInspector}
            type="button"
          >
            <PanelRightOpen aria-hidden="true" />
          </button>
        </div>
      </header>

      <Robot3DViewer
        ariaLabel={`${viewerVariant} Studio 仿真预览三维视图`}
        className="studio-robot-viewer"
        enabledJointIds={viewerEnabledJointIds}
        jointDefinitions={viewerJointDefinitions}
        jointPositions={viewerJointPositions}
        jointUnits={viewerJointUnits}
        variant={viewerVariant}
      />
    </section>
  );
}
