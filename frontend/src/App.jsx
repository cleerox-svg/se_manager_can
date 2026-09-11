import { useEffect, useState } from 'react';
import Sidebar from './components/Sidebar.jsx';
import Topbar from './components/Topbar.jsx';
import Toasts from './components/Toasts.jsx';
import Dashboard from './pages/Dashboard.jsx';
import Team from './pages/Team.jsx';
import Person from './pages/Person.jsx';
import Settings from './pages/Settings.jsx';
import TechForecast from './pages/TechForecast/TechForecast.jsx';
import Actions from './pages/Actions.jsx';
import { initTheme, setTheme } from './theme.js';
import { subscribeToasts } from './toast.js';

const PAGE_TITLES = {
  dashboard: 'Dashboard',
  team: 'Team',
  person: 'Person',
  'tech-forecast': 'Technical Forecast',
  actions: 'Actions',
  settings: 'Settings',
};

function PageContent({ page, selectedRepId, onSelectPerson }) {
  switch (page) {
    case 'dashboard':
      return <Dashboard />;
    case 'team':
      return <Team onSelectPerson={onSelectPerson} />;
    case 'person':
      return <Person repId={selectedRepId} />;
    case 'tech-forecast':
      return <TechForecast />;
    case 'actions':
      return <Actions />;
    case 'settings':
      return <Settings />;
    default:
      return <h1>{PAGE_TITLES[page] || page}</h1>;
  }
}

export default function App() {
  const [currentPage, setCurrentPage] = useState('dashboard');
  const [selectedRepId, setSelectedRepId] = useState(null);
  const [lightMode, setLightMode] = useState(false);
  const [toasts, setToasts] = useState([]);

  useEffect(() => {
    setLightMode(initTheme());
  }, []);

  useEffect(() => subscribeToasts((entry) => {
    setToasts((prev) => [...prev, entry]);
    const timeout = entry.type === 'error' ? 8000 : 3500;
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== entry.id));
    }, timeout);
  }), []);

  function handleToggleTheme() {
    const next = !lightMode;
    setLightMode(next);
    setTheme(next);
  }

  function dismissToast(id) {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }

  function handleSelectPerson(repId) {
    setSelectedRepId(repId);
    setCurrentPage('person');
  }

  return (
    <>
      <Sidebar
        currentPage={currentPage}
        onNavigate={setCurrentPage}
        lightMode={lightMode}
        onToggleTheme={handleToggleTheme}
      />
      <div id="app">
        <Topbar title={PAGE_TITLES[currentPage] || currentPage} />
        <div className="page active">
          <PageContent
            page={currentPage}
            selectedRepId={selectedRepId}
            onSelectPerson={handleSelectPerson}
          />
        </div>
      </div>
      <Toasts toasts={toasts} onDismiss={dismissToast} />
    </>
  );
}
