import { PageIntro } from '../components/PageIntro';

export function SettingsPage() {
  return (
    <div className="page">
      <PageIntro
        title="Settings"
        description="Configuration editing is not available in Stage 1."
        detail="The current foundation remains locked to a safe local development configuration."
      />
    </div>
  );
}
