import { PageIntro } from '../components/PageIntro';

export function LibraryPage() {
  return (
    <div className="page">
      <PageIntro
        title="Library"
        description="The reusable motion library is not available in Stage 1."
        detail="The repository contracts are being prepared for safe, versioned local storage."
      />
    </div>
  );
}
