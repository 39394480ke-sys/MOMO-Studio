import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './app/App';
import './styles/global.css';
import './styles/tokens.css';
import './styles/shell.css';
import './styles/ui.css';
import './styles/control.css';
import './styles/studio.css';
import './styles/library.css';
import './styles/vision.css';
import './styles/settings.css';

const rootElement = document.getElementById('root');

if (!rootElement) {
  throw new Error('MOMO Studio root element was not found.');
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
