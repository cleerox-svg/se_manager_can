const NAV_ITEMS = [
  { page: 'dashboard', icon: '▦', label: 'Dashboard' },
  { page: 'team', icon: '▤', label: 'Team' },
  { page: 'tech-forecast', icon: '▲', label: 'Technical Forecast' },
  { page: 'settings', icon: '⚙', label: 'Settings' },
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
            <span className="sidebar-icon">{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </div>
      <div className="sidebar-footer">
        <button className="btn" id="theme-toggle-btn" onClick={onToggleTheme}>
          {lightMode ? '☾ Dark mode' : '☀ Light mode'}
        </button>
      </div>
    </nav>
  );
}
