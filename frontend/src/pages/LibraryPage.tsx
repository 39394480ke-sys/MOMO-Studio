import { PageIntro } from '../components/PageIntro';

export function LibraryPage() {
  return (
    <div className="page">
      <PageIntro
        title="Library"
        description="The reusable motion library is not available in Stage 2."
        detail="Safe, versioned pose and motion storage will arrive after the robot core."
      />
    </div>
  );
}
