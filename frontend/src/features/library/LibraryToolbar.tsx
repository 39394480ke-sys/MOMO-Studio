import { Search } from 'lucide-react';

import type { EntitySortField, SortOrder } from '../../api/types';

export interface LibraryFilters {
  search: string;
  tags: string;
  sort: EntitySortField;
  order: SortOrder;
}

interface LibraryToolbarProps {
  filters: LibraryFilters;
  disabled: boolean;
  onChange: (filters: LibraryFilters) => void;
}

const SORT_OPTIONS: Array<{
  label: string;
  sort: EntitySortField;
  order: SortOrder;
}> = [
  { label: 'Newest created', sort: 'created_at', order: 'desc' },
  { label: 'Recently updated', sort: 'updated_at', order: 'desc' },
  { label: 'Name A–Z', sort: 'name', order: 'asc' },
  { label: 'Name Z–A', sort: 'name', order: 'desc' },
];

export function LibraryToolbar({ filters, disabled, onChange }: LibraryToolbarProps) {
  const selectedSort = `${filters.sort}:${filters.order}`;

  return (
    <div className="library-toolbar" aria-label="Library filters">
      <label className="library-search">
        <span>Search</span>
        <span className="library-search__field">
          <Search aria-hidden="true" />
          <input
            disabled={disabled}
            maxLength={200}
            onChange={(event) => onChange({ ...filters, search: event.target.value })}
            placeholder="Name or description"
            type="search"
            value={filters.search}
          />
        </span>
      </label>
      <label>
        <span>Tags</span>
        <input
          disabled={disabled}
          maxLength={2079}
          onChange={(event) => onChange({ ...filters, tags: event.target.value })}
          placeholder="demo, reach"
          type="text"
          value={filters.tags}
        />
      </label>
      <label>
        <span>Sort</span>
        <select
          disabled={disabled}
          onChange={(event) => {
            const [sort, order] = event.target.value.split(':') as [
              EntitySortField,
              SortOrder,
            ];
            onChange({ ...filters, sort, order });
          }}
          value={selectedSort}
        >
          {SORT_OPTIONS.map((option) => (
            <option key={`${option.sort}:${option.order}`} value={`${option.sort}:${option.order}`}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
