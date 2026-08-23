import { Navigate, Route, Routes } from 'react-router-dom';

import { AppShell } from '../layouts/AppShell';
import { ControlPage } from '../pages/ControlPage';
import { LibraryPage } from '../pages/LibraryPage';
import { SettingsPage } from '../pages/SettingsPage';
import { StudioPage } from '../pages/StudioPage';
import { VisionPage } from '../pages/VisionPage';

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate replace to="/control" />} />
        <Route path="control" element={<ControlPage />} />
        <Route path="studio" element={<StudioPage />} />
        <Route path="library" element={<LibraryPage />} />
        <Route path="vision" element={<VisionPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate replace to="/control" />} />
      </Route>
    </Routes>
  );
}
