import { Link, useSearchParams } from 'react-router-dom';

import { PageIntro } from '../components/PageIntro';

export function StudioPage() {
  const [searchParams] = useSearchParams();
  const poseId = searchParams.get('pose');
  const motionId = searchParams.get('motion');
  const selectedId = poseId ?? motionId;
  const selectedKind = poseId ? 'Pose' : motionId ? 'Motion' : null;

  return (
    <div className="page">
      <PageIntro
        title="Studio"
        description="The timeline sequence workspace is scheduled for Stage 6."
        detail="Stage 4 can hand off a stored UUID, but it does not enable timeline authoring or playback."
      />
      {selectedId && selectedKind ? (
        <section className="studio-handoff" aria-labelledby="studio-handoff-title">
          <p className="section-kicker">Stage 4 handoff</p>
          <h2 id="studio-handoff-title">{selectedKind} selected for future Studio use</h2>
          <p>
            Only the stored UUID was handed off. Stage 6 will load and validate the entity before authoring; no command was sent.
          </p>
          <code>{selectedId}</code>
          <Link className="command-button" to="/library">Return to Library</Link>
        </section>
      ) : null}
    </div>
  );
}
