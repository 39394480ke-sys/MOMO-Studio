interface NavIconProps {
  name: 'control' | 'studio' | 'library' | 'vision' | 'settings';
}

export function NavIcon({ name }: NavIconProps) {
  if (name === 'control') {
    return (
      <svg aria-hidden="true" viewBox="0 0 32 32">
        <path d="M4 9h8m5 0h11M4 23h13m5 0h6M12 5v8m5 6v8" />
        <circle cx="14.5" cy="9" r="2.5" />
        <circle cx="19.5" cy="23" r="2.5" />
      </svg>
    );
  }

  if (name === 'studio') {
    return (
      <svg aria-hidden="true" viewBox="0 0 32 32">
        <path d="M5 9h5l2-3h8l2 3h5v17H5z" />
        <circle cx="16" cy="17.5" r="5.5" />
      </svg>
    );
  }

  if (name === 'library') {
    return (
      <svg aria-hidden="true" viewBox="0 0 32 32">
        <path d="M4.5 8.5h8l2.5 3h12.5v15H4.5z" />
      </svg>
    );
  }

  if (name === 'vision') {
    return (
      <svg aria-hidden="true" viewBox="0 0 32 32">
        <path d="M3 16s4.5-7 13-7 13 7 13 7-4.5 7-13 7S3 16 3 16Z" />
        <circle cx="16" cy="16" r="4" />
      </svg>
    );
  }

  return (
    <svg aria-hidden="true" viewBox="0 0 32 32">
      <path d="m12.5 4-.8 3.6-2.5 1.5-3.5-1.2-2.4 4.2 2.7 2.4v3L3.3 20l2.4 4.1 3.5-1.2 2.5 1.5.8 3.6h4.9l.8-3.6 2.6-1.5 3.5 1.2 2.4-4.1-2.8-2.5v-3l2.8-2.4-2.4-4.2-3.5 1.2-2.6-1.5-.8-3.6Z" />
      <circle cx="15" cy="16" r="4" />
    </svg>
  );
}
