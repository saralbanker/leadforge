import React from 'react';

const EmptyState = ({ icon: Icon, message, sub }) => (
  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '3rem', gap: '0.75rem', color: 'var(--text-muted)' }}>
    <Icon size={40} style={{ opacity: 0.25 }} />
    <div style={{ fontWeight: 500 }}>{message}</div>
    {sub && <div style={{ fontSize: '0.85rem' }}>{sub}</div>}
  </div>
);

export default EmptyState;
