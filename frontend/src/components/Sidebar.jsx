import { LayoutGrid, Users, TrendingUp, Pencil, Settings, Moon, Sun } from 'lucide-react';

const NAV_ITEMS = [
  { page: 'dashboard', Icon: LayoutGrid, label: 'Dashboard' },
  { page: 'team', Icon: Users, label: 'Team' },
  { page: 'tech-forecast', Icon: TrendingUp, label: 'Technical Forecast' },
  { page: 'actions', Icon: Pencil, label: 'Actions' },
  { page: 'settings', Icon: Settings, label: 'Settings' },
];

export default function Sidebar({ currentPage, onNavigate, lightMode, onToggleTheme }) {
  return (
    <nav id="sidebar">
      <div className="sidebar-header">
        <div className="logo-mark">SE</div>
        <div>
          <div className="sidebar-wordmark">SE Manager Hub</div>
          <div className="sidebar-sub">Team pipeline &amp; check-ins</div>
        </div>
      </div>
      <div className="sidebar-nav">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.page}
            className={`sidebar-btn${currentPage === item.page ? ' active' : ''}`}
            onClick={() => onNavigate(item.page)}
          >
            <span className="sidebar-icon">
              <item.Icon size={16} strokeWidth={2} />
            </span>
            <span>{item.label}</span>
          </button>
        ))}
      </div>
      <div className="sidebar-footer">
        <button className="btn" id="theme-toggle-btn" onClick={onToggleTheme}>
          {lightMode ? <Moon size={14} strokeWidth={2} /> : <Sun size={14} strokeWidth={2} />}
          {lightMode ? ' Dark mode' : ' Light mode'}
        </button>
      </div>
    </nav>
  );
}
