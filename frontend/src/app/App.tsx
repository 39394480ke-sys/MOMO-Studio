import { BrowserRouter } from 'react-router-dom';

import { RealSessionProvider } from '../components/RealSessionProvider';
import { RuntimeStatusProvider } from '../components/RuntimeStatusProvider';
import { AppRoutes } from './AppRoutes';

export function AppContent() {
  return (
    <RuntimeStatusProvider>
      <RealSessionProvider>
        <AppRoutes />
      </RealSessionProvider>
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
