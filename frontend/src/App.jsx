import React from 'react';
import { Routes, Route } from 'react-router-dom';
import LandingPage from './components/LandingPage';
import ThorPage from './components/ThorPage';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/thor" element={<ThorPage />} />
      <Route path="*" element={<LandingPage />} />
    </Routes>
  );
}
