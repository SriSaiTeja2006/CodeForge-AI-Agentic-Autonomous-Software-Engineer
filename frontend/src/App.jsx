import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import NewTask from './pages/NewTask';
import ExecutionCenter from './pages/ExecutionCenter';
import CodeChanges from './pages/CodeChanges';
import TestResults from './pages/TestResults';
import PullRequest from './pages/PullRequest';
import Repositories from './pages/Repositories';
import History from './pages/History';
import Settings from './pages/Settings';

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="new" element={<NewTask />} />
          <Route path="tasks" element={<ExecutionCenter />} />
          <Route path="tasks/:taskId" element={<ExecutionCenter />} />
          <Route path="changes" element={<CodeChanges />} />
          <Route path="tasks/:taskId/changes" element={<CodeChanges />} />
          <Route path="tests" element={<TestResults />} />
          <Route path="tasks/:taskId/tests" element={<TestResults />} />
          <Route path="pr" element={<PullRequest />} />
          <Route path="pull-request" element={<PullRequest />} />
          <Route path="tasks/:taskId/pr" element={<PullRequest />} />
          <Route path="tasks/:taskId/pull-request" element={<PullRequest />} />
          <Route path="repositories" element={<Repositories />} />
          <Route path="history" element={<History />} />
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
