import { PageIntro } from '../components/PageIntro';

export function StudioPage() {
  return (
    <div className="page">
      <PageIntro
        title="Studio"
        description="The timeline sequence workspace is scheduled for Stage 6."
        detail="Stage 3 provides direct control only; later stages add reusable motions, playback, and timeline authoring."
      />
    </div>
  );
}
