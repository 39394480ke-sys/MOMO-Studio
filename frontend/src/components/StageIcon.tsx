interface StageIconProps {
  kind: 'connection' | 'joint' | 'cartesian';
}

export function StageIcon({ kind }: StageIconProps) {
  const symbol = (() => {
    switch (kind) {
      case 'connection':
        return (
          <>
            <path d="M23 11h12v13H23zM26 24v8h6v5m-9-20h12" />
            <path d="M20 8 40 40" className="stage-icon__slash" />
          </>
        );
      case 'joint':
        return (
          <>
            <circle cx="18" cy="30" r="6" />
            <circle cx="34" cy="18" r="5" />
            <circle cx="31" cy="39" r="3" />
            <path d="m22 26 8-6m-7 13 6 4m-6-11 8 11" />
            <path d="M11 11 41 41" className="stage-icon__slash" />
          </>
        );
      case 'cartesian':
        return (
          <>
            <path d="M26 35V13m0 22 14 5m-14-5-12 9m12-31-4 5m4-5 4 5m10 22-7-1m7 1-4 5m-22-1 2-7m-2 7h7" />
            <path d="M11 11 41 41" className="stage-icon__slash" />
          </>
        );
    }
  })();

  return (
    <span className="stage-icon" aria-hidden="true">
      <svg viewBox="0 0 52 52">{symbol}</svg>
    </span>
  );
}
