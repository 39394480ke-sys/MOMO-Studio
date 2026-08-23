import { BrowserRouter } from 'react-router-dom';

import { RuntimeStatusProvider } from '../components/RuntimeStatusProvider';
import { AppRoutes } from './AppRoutes';

export function AppContent() {
  return (
    <RuntimeStatusProvider>
      <AppRoutes />
    </RuntimeStatusProvider>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <AppContent />
    </BrowserRouter>
  );
}
