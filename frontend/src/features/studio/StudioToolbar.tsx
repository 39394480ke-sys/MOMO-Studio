import {
  ArrowLeft,
  FilePlus2,
  Library,
  Redo2,
  Save,
  SaveAll,
  Undo2,
} from 'lucide-react';
import { Link } from 'react-router-dom';

import type { RobotVariant } from '../../api/types';

interface StudioToolbarProps {
  autosaveLabel: string;
  busy: boolean;
  canRedo: boolean;
  canSaveMotion: boolean;
  canUndo: boolean;
  dirty: boolean;
  draftName: string;
  draftRevision: number | null;
  robotVariant: RobotVariant;
  saveDisabledReason: string | null;
  onNameChange: (name: string) => void;
  onNew: () => void;
  onRedo: () => void;
  onSave: () => void;
  onSaveAs: () => void;
  onUndo: () => void;
}

export function StudioToolbar({
  autosaveLabel,
  busy,
  canRedo,
  canSaveMotion,
  canUndo,
  dirty,
  draftName,
  draftRevision,
  robotVariant,
  saveDisabledReason,
  onNameChange,
  onNew,
  onRedo,
  onSave,
  onSaveAs,
  onUndo,
}: StudioToolbarProps) {
  return (
    <header className="studio-toolbar" aria-label="Studio document controls">
      <div className="studio-toolbar__identity">
        <label htmlFor="studio-motion-name">Motion name</label>
        <input
          autoComplete="off"
          disabled={busy}
          id="studio-motion-name"
          maxLength={200}
          onChange={(event) => onNameChange(event.target.value)}
          value={draftName}
        />
        <div className="studio-document-meta" aria-live="polite">
          <span className={`studio-dirty-state${dirty ? ' studio-dirty-state--dirty' : ''}`}>
            {dirty ? 'Unsaved Motion changes' : 'Motion up to date'}
          </span>
          <span>{autosaveLabel}</span>
          <span>{robotVariant}</span>
          {draftRevision ? <span>draft rev {draftRevision}</span> : null}
        </div>
      </div>

      <div className="studio-toolbar__actions">
        <button
          aria-label="Undo last Studio edit"
          className="mini-command"
          disabled={busy || !canUndo}
          onClick={onUndo}
          title={canUndo ? 'Undo last edit (Ctrl/⌘ Z)' : 'Nothing to undo'}
          type="button"
        >
          <Undo2 aria-hidden="true" />
          <span>Undo</span>
        </button>
        <button
          aria-label="Redo last Studio edit"
          className="mini-command"
          disabled={busy || !canRedo}
          onClick={onRedo}
          title={canRedo ? 'Redo last edit (Ctrl/⌘ Shift Z)' : 'Nothing to redo'}
          type="button"
        >
          <Redo2 aria-hidden="true" />
          <span>Redo</span>
        </button>
        <button className="command-button" disabled={busy} onClick={onNew} type="button">
          <FilePlus2 aria-hidden="true" />
          New draft
        </button>
        <button
          aria-describedby={saveDisabledReason ? 'studio-save-disabled-reason' : undefined}
          className="command-button command-button--primary"
          disabled={busy || !canSaveMotion}
          onClick={onSave}
          title={saveDisabledReason ?? 'Validate, compile, and save this Motion'}
          type="button"
        >
          <Save aria-hidden="true" />
          Save
        </button>
        <button
          aria-describedby={saveDisabledReason ? 'studio-save-disabled-reason' : undefined}
          className="command-button"
          disabled={busy || !canSaveMotion}
          onClick={onSaveAs}
          title={saveDisabledReason ?? 'Save a new Motion with a new UUID'}
          type="button"
        >
          <SaveAll aria-hidden="true" />
          Save As
        </button>
        <Link className="command-button studio-library-link" to="/library">
          <Library aria-hidden="true" />
          Library
        </Link>
      </div>

      {saveDisabledReason ? (
        <p className="studio-toolbar__reason" id="studio-save-disabled-reason">
          <ArrowLeft aria-hidden="true" /> Save unavailable · {saveDisabledReason}
        </p>
      ) : null}
    </header>
  );
}
