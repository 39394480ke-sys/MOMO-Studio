import { PageIntro } from '../components/PageIntro';
import { useRuntimeStatus } from '../components/runtimeStatusContext';
import { VisionCanvas } from '../features/vision/VisionCanvas';
import { VisionControls } from '../features/vision/VisionControls';
import { useVisionWorkspace } from '../features/vision/useVisionWorkspace';

export function VisionPage() {
  const runtime = useRuntimeStatus();
  const workspace = useVisionWorkspace(runtime);
  const sourceMode = workspace.capabilities?.camera_access_policy === 'DISABLED'
    ? 'SOURCE DISABLED'
    : workspace.capabilities?.source.provider_id.toLowerCase().includes('synthetic')
      ? 'SYNTHETIC'
      : workspace.capabilities
        ? 'LIVE'
        : 'SOURCE PENDING';

  return (
    <div className="page vision-page">
      <PageIntro
        title="Vision"
        description={workspace.readOnlyLiveCamera
          ? 'Preview one explicitly configured local camera without recording or robot motion.'
          : 'Track an explicit target and drive lease-bound Follow through backend capability gates.'}
        detail={workspace.readOnlyLiveCamera
          ? 'The camera opens only after operator action; selection, detection, tracking, and Follow remain disabled.'
          : 'Frame identity, provider capability, target freshness, and the Motion Safety Gateway remain visible at every step.'}
      />
      <div className="vision-safety-strip" role="status">
        <span>{sourceMode}</span>
        <span>{workspace.capabilities?.camera_access_policy ?? 'POLICY PENDING'}</span>
        <span>{workspace.readOnlyLiveCamera
          ? 'READ ONLY CAMERA'
          : workspace.runtimePolicy === 'READ_ONLY'
            ? 'READ ONLY'
            : workspace.runtimeMode}</span>
        <span>{workspace.runtimeMode === 'REAL'
          ? workspace.realVisionCapability.allowed
            ? 'REAL FOLLOW AUTHORIZED'
            : `REAL FOLLOW BLOCKED · ${workspace.realVisionCapability.reason}`
          : 'REAL FOLLOW BLOCKED'}</span>
      </div>
      <div className="vision-workspace">
        <VisionCanvas workspace={workspace} />
        <VisionControls workspace={workspace} />
      </div>
    </div>
  );
}
