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
  kindLabel: '机位' | '运动';
  onChange: (filters: LibraryFilters) => void;
}

const SORT_OPTIONS: Array<{
  label: string;
  sort: EntitySortField;
  order: SortOrder;
}> = [
  { label: '最新创建', sort: 'created_at', order: 'desc' },
  { label: '最近更新', sort: 'updated_at', order: 'desc' },
  { label: '名称 A–Z', sort: 'name', order: 'asc' },
  { label: '名称 Z–A', sort: 'name', order: 'desc' },
];

export function LibraryToolbar({ filters, disabled, kindLabel, onChange }: LibraryToolbarProps) {
  const selectedSort = `${filters.sort}:${filters.order}`;

  return (
    <div className="library-toolbar" aria-label="资源库筛选">
      <label className="library-search">
        <span>搜索</span>
        <span className="library-search__field">
          <Search aria-hidden="true" />
          <input
            disabled={disabled}
            maxLength={200}
            onChange={(event) => onChange({ ...filters, search: event.target.value })}
            placeholder={`搜索${kindLabel}名称、说明…`}
            type="search"
            value={filters.search}
          />
        </span>
      </label>
      <label>
        <span>标签</span>
        <input
          disabled={disabled}
          maxLength={2079}
          onChange={(event) => onChange({ ...filters, tags: event.target.value })}
          placeholder="产品, 正面"
          type="text"
          value={filters.tags}
        />
      </label>
      <label>
        <span>排序</span>
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
