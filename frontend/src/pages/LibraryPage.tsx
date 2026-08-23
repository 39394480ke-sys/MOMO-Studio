import { PageIntro } from '../components/PageIntro';

export function LibraryPage() {
  return (
    <div className="page">
      <PageIntro
        title="Library"
        description="Pose and Motion Library is scheduled for Stage 4."
        detail="That stage adds safe, versioned pose and motion storage; Stage 3 remains direct control only."
      />
    </div>
  );
}
