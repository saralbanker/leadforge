import React from 'react';
import { RefreshCw } from 'lucide-react';

const LoadingSpinner = ({ label }) => (
  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '3rem', gap: '0.75rem', color: 'var(--text-muted)' }}>
    <RefreshCw size={20} style={{ animation: 'spin 1s linear infinite' }} />
    <span>{label || 'Loading…'}</span>
  </div>
);

export default LoadingSpinner;
