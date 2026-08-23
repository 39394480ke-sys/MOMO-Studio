interface PageIntroProps {
  title: string;
  description: string;
  detail: string;
}

export function PageIntro({ title, description, detail }: PageIntroProps) {
  return (
    <header className="page-intro">
      <h1>{title}</h1>
      <p>{description}</p>
      <p>{detail}</p>
    </header>
  );
}
