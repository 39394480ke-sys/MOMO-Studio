import { StageIcon } from './StageIcon';

interface StagePlaceholderProps {
  title: string;
  description: string;
  detail: string;
  icon: Parameters<typeof StageIcon>[0]['kind'];
}

export function StagePlaceholder({
  title,
  description,
  detail,
  icon,
}: StagePlaceholderProps) {
  return (
    <section className="stage-placeholder" aria-labelledby={`${icon}-title`}>
      <h2 id={`${icon}-title`}>{title}</h2>
      <div className="stage-placeholder__body">
        <StageIcon kind={icon} />
        <div>
          <p>{description}</p>
          <p>{detail}</p>
        </div>
      </div>
    </section>
  );
}
