import type { ComponentProps, ReactNode } from 'react';

import type {
  ForwardKinematicsResponse,
  ProfileJointDefinition,
  RobotStatus,
} from '../../api/types';
import { Robot3DViewer } from '../robot-viewer';
import { quaternionToRpyDegrees } from './controlMath';
import { MotionParametersPanel } from './MotionParametersPanel';
import { ProductMotionControlPanel } from './ProductMotionControlPanel';

interface StatusRow {
  label: string;
  value: ReactNode;
}

interface ControlWorkspaceViewProps {
  safetyBar: ReactNode;
  robot: RobotStatus | null;
  definitions: ProfileJointDefinition[];
  enabledJointIds: string[] | null;
  fk: ForwardKinematicsResponse | null;
  previewPill: string;
  viewerAriaLabel: string;
  viewerBadgeLabel: string;
  viewerSafetyNote: string;
  viewerPlaceholder: string;
  viewerPlaceholderDetail: string;
  emptyControlText: string;
  motionPanelProps: Omit<
    ComponentProps<typeof ProductMotionControlPanel>,
    'definitions' | 'fk' | 'robot'
  >;
  parametersPanelProps: ComponentProps<typeof MotionParametersPanel>;
  statusRows: StatusRow[];
  statusPanel: ReactNode;
}

export function ControlWorkspaceView({
  safetyBar,
  robot,
  definitions,
  enabledJointIds,
  fk,
  previewPill,
  viewerAriaLabel,
  viewerBadgeLabel,
  viewerSafetyNote,
  viewerPlaceholder,
  viewerPlaceholderDetail,
  emptyControlText,
  motionPanelProps,
  parametersPanelProps,
  statusRows,
  statusPanel,
}: ControlWorkspaceViewProps) {
  const rotation = fk
    ? quaternionToRpyDegrees(fk.tcp_pose.orientation_quaternion_xyzw)
    : null;

  return (
    <>
      {safetyBar}
      <div className="control-workspace-grid control-product-grid">
        <section className="robot-preview-panel" aria-labelledby="robot-preview-title">
          <header className="product-panel-header">
            <h2 id="robot-preview-title">机械臂预览</h2>
            <span className="product-status-pill">{previewPill}</span>
          </header>
          {robot && enabledJointIds ? (
            <Robot3DViewer
              ariaLabel={viewerAriaLabel}
              badgeLabel={viewerBadgeLabel}
              className="control-robot-viewer"
              enabledJointIds={enabledJointIds}
              jointDefinitions={definitions}
              jointPositions={robot.positions}
              jointUnits={robot.units}
              safetyNote={viewerSafetyNote}
              variant={robot.variant}
            />
          ) : (
            <div className="robot-viewer-placeholder" role="status">
              <p>{viewerPlaceholder}</p>
              <small>{viewerPlaceholderDetail}</small>
            </div>
          )}
        </section>

        {robot && definitions.length > 0 ? (
          <ProductMotionControlPanel
            {...motionPanelProps}
            definitions={definitions}
            fk={fk}
            robot={robot}
          />
        ) : (
          <section className="product-motion-panel">
            <p className="empty-state">{emptyControlText}</p>
          </section>
        )}

        <section className="control-summary-panel control-end-effector" aria-labelledby="end-effector-title">
          <header className="product-panel-header"><h2 id="end-effector-title">末端执行器</h2></header>
          {fk && rotation ? (
            <dl className="end-effector-metrics">
              <div><dt>X</dt><dd>{fk.tcp_pose.position_mm.x.toFixed(1)} mm</dd></div>
              <div><dt>Roll</dt><dd>{rotation.x.toFixed(1)}°</dd></div>
              <div><dt>Y</dt><dd>{fk.tcp_pose.position_mm.y.toFixed(1)} mm</dd></div>
              <div><dt>Pitch</dt><dd>{rotation.y.toFixed(1)}°</dd></div>
              <div><dt>Z</dt><dd>{fk.tcp_pose.position_mm.z.toFixed(1)} mm</dd></div>
              <div><dt>Yaw</dt><dd>{rotation.z.toFixed(1)}°</dd></div>
            </dl>
          ) : <p className="empty-state">正在等待 FK 状态。</p>}
        </section>

        <section className="control-summary-panel control-runtime-summary" aria-labelledby="runtime-summary-title">
          <header className="product-panel-header"><h2 id="runtime-summary-title">状态</h2></header>
          <dl className="runtime-summary-list">
            {statusRows.map((row) => (
              <div key={row.label}><dt>{row.label}</dt><dd>{row.value}</dd></div>
            ))}
          </dl>
        </section>

        <div className="control-product-advanced control-workspace-sidebar">
          <MotionParametersPanel {...parametersPanelProps} />
          {statusPanel}
        </div>
      </div>
    </>
  );
}
