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
        description="Track an explicit Synthetic target and drive lease-bound Dry Run Follow."
        detail="Frame identity, provider capability, target freshness, and the Motion Safety Gateway remain visible at every step."
      />
      <div className="vision-safety-strip" role="status">
        <span>{sourceMode}</span>
        <span>{workspace.capabilities?.camera_access_policy ?? 'POLICY PENDING'}</span>
        <span>{workspace.runtimePolicy === 'READ_ONLY' ? 'READ ONLY' : workspace.runtimeMode}</span>
        <span>REAL FOLLOW BLOCKED</span>
      </div>
      <div className="vision-workspace">
        <VisionCanvas workspace={workspace} />
        <VisionControls workspace={workspace} />
      </div>
    </div>
  );
}
