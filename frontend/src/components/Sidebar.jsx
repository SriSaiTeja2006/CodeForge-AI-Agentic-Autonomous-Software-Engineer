import React, { useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  PlusCircle,
  PlayCircle,
  GitCompare,
  CheckSquare,
  GitPullRequest,
  FolderGit2,
  History,
  Settings,
  Cpu,
  X,
} from 'lucide-react';
import { api } from '../api/client';

export function Sidebar({ isOpen, onClose }) {
  const [healthStatus, setHealthStatus] = useState('checking');

  useEffect(() => {
    let isMounted = true;
    async function checkHealth() {
      try {
        const res = await api.getHealth();
        if (isMounted) {
          setHealthStatus(res.status === 'healthy' ? 'healthy' : 'degraded');
        }
      } catch {
        if (isMounted) {
          setHealthStatus('offline');
        }
      }
    }

    checkHealth();
    const interval = setInterval(checkHealth, 15000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  const navItems = [
    { to: '/', label: 'Dashboard', icon: <LayoutDashboard size={18} />, end: true },
    { to: '/new', label: 'New Task', icon: <PlusCircle size={18} /> },
    { to: '/tasks', label: 'Execution Center', icon: <PlayCircle size={18} /> },
    { to: '/changes', label: 'Code Changes', icon: <GitCompare size={18} /> },
    { to: '/tests', label: 'Test Results', icon: <CheckSquare size={18} /> },
    { to: '/pr', label: 'Pull Request', icon: <GitPullRequest size={18} /> },
    { to: '/repositories', label: 'Repositories', icon: <FolderGit2 size={18} /> },
    { to: '/history', label: 'Task History', icon: <History size={18} /> },
    { to: '/settings', label: 'Settings', icon: <Settings size={18} /> },
  ];

  return (
    <aside className={`sidebar ${isOpen ? 'open' : ''}`}>
      <div className="sidebar-brand">
        <div className="sidebar-logo-icon">
          <Cpu size={16} />
        </div>
        <div style={{ flex: 1 }}>
          <div className="sidebar-brand-name">CodeForge AI</div>
        </div>
        <span className="sidebar-brand-badge">Agent</span>
        {isOpen && (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onClose}
            style={{ display: 'none', padding: '0.2rem' }}
          >
            <X size={16} />
          </button>
        )}
      </div>

      <nav className="sidebar-nav">
        <div className="sidebar-section-title">Workflow</div>
        {navItems.slice(0, 6).map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
            onClick={onClose}
          >
            {item.icon}
            <span>{item.label}</span>
          </NavLink>
        ))}

        <div className="sidebar-section-title" style={{ marginTop: '0.75rem' }}>
          Management
        </div>
        {navItems.slice(6).map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
            onClick={onClose}
          >
            {item.icon}
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className="system-status-indicator" title={`System status: ${healthStatus}`}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span className={`status-dot ${healthStatus}`} />
            <span>API & Engine</span>
          </div>
          <span style={{ textTransform: 'capitalize', fontWeight: 600, fontSize: '0.7rem' }}>
            {healthStatus}
          </span>
        </div>
      </div>
    </aside>
  );
}

export default Sidebar;
