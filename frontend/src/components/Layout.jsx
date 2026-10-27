import React, { useState } from 'react';
import { Outlet, useLocation, Link } from 'react-router-dom';
import { Menu, PlusCircle, ExternalLink } from 'lucide-react';
import Sidebar from './Sidebar';

export function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();

  // Determine page title based on path
  const getPageTitle = (path) => {
    if (path === '/') return 'Dashboard';
    if (path === '/new') return 'Create New Task';
    if (path.startsWith('/tasks')) return 'Execution Center';
    if (path.startsWith('/changes')) return 'Code Changes & Patches';
    if (path.startsWith('/tests')) return 'Test Verification';
    if (path.startsWith('/pr')) return 'Pull Request';
    if (path === '/repositories') return 'Repositories';
    if (path === '/history') return 'Task History';
    if (path === '/settings') return 'Settings & Engine Status';
    return 'CodeForge AI';
  };

  return (
    <div className="app-container">
      <Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      {sidebarOpen && (
        <div
          onClick={() => setSidebarOpen(false)}
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0,0,0,0.6)',
            zIndex: 40,
          }}
        />
      )}

      <div className="main-content">
        <header className="topbar">
          <div className="topbar-left">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setSidebarOpen(!sidebarOpen)}
              style={{ display: 'none', padding: '0.4rem' }}
              aria-label="Toggle navigation menu"
            >
              <Menu size={18} />
            </button>
            <div>
              <h1 className="topbar-title">{getPageTitle(location.pathname)}</h1>
            </div>
          </div>

          <div className="topbar-right">
            <a
              href="https://github.com"
              target="_blank"
              rel="noreferrer"
              className="btn btn-ghost btn-sm"
              style={{ gap: '0.35rem' }}
            >
              <span>GitHub</span>
              <ExternalLink size={13} />
            </a>

            {location.pathname !== '/new' && (
              <Link to="/new" className="btn btn-primary btn-sm">
                <PlusCircle size={14} />
                <span>New Task</span>
              </Link>
            )}
          </div>
        </header>

        <main className="page-wrapper">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export default Layout;
