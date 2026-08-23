import { PageIntro } from '../components/PageIntro';
import { StagePlaceholder } from '../components/StagePlaceholder';

export function ControlPage() {
  return (
    <div className="page">
      <PageIntro
        title="Control"
        description="This is Stage 1 of MOMO Studio. Motion controls are not available yet."
        detail="We’re laying the foundation for safe, precise robot-arm motion."
      />
      <div className="placeholder-list">
        <StagePlaceholder
          title="Connection"
          icon="connection"
          description="Hardware connection is not available in Stage 1."
          detail="Connection status and controls will be introduced in a later stage."
        />
        <StagePlaceholder
          title="Joint control"
          icon="joint"
          description="Joint motion controls are not available in Stage 1."
          detail="Manual joint control and related functionality will be introduced in a later stage."
        />
        <StagePlaceholder
          title="Cartesian control"
          icon="cartesian"
          description="Cartesian motion controls are not available in Stage 1."
          detail="Position and orientation controls will be introduced in a later stage."
        />
      </div>
    </div>
  );
}
