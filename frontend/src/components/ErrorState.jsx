import React from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

const ErrorState = ({ message, onRetry }) => (
  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '3rem', gap: '0.75rem', color: '#f87171' }}>
    <AlertTriangle size={32} style={{ opacity: 0.7 }} />
    <div style={{ fontWeight: 600 }}>Failed to load</div>
    <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>{message}</div>
    {onRetry && <button className="btn-secondary" onClick={onRetry}><RefreshCw size={14} /> Retry</button>}
  </div>
);

export default ErrorState;
