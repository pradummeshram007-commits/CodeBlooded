import React from 'react';
import { Routes, Route } from 'react-router-dom';
import LandingPage from './components/LandingPage';
import ThorPage from './components/ThorPage';
import NornsPage from './components/NornsPage';
import LokiPage from './components/LokiPage';
import HeimdallPage from './components/HeimdallPage';
import DashboardPage from './components/dashboard/DashboardPage';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/dashboard" element={<DashboardPage />} />
      <Route path="/thor" element={<ThorPage />} />
      <Route path="/norns" element={<NornsPage />} />
      <Route path="/loki" element={<LokiPage />} />
      <Route path="/heimdall" element={<HeimdallPage />} />
      <Route path="*" element={<LandingPage />} />
    </Routes>
  );
}

