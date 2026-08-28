import './styles/variables.css';
import './styles/global.css';
import './styles/layout.css';
import './styles/components.css';
import './styles/responsive.css';

import './services/firebase';
import { AppShell } from './components/layout/AppShell';
import { initShaderBackground } from './utils/shaderBackground';

import { OrcaApiService } from './services/orcaApiService';
import { HistoryRouter } from './services/historyRouter';

document.addEventListener('DOMContentLoaded', () => {
  const root = document.getElementById('app');
  if (root) {
    const appShell = new AppShell();
    root.appendChild(appShell.getElement());
    // Initialize subtle maritime ocean drift network shader
    initShaderBackground('app');
    // Acquire live device GPS for coastal forecasting & 'Where am I?' queries
    void OrcaApiService.acquireLiveGps();
    // Initialize Browser Back-Button and Route History Manager
    HistoryRouter.getInstance();
  }
});
