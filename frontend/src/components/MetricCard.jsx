import React from 'react';

const MetricCard = ({ Icon, value, label, accent }) => (
  <div className="metric-card">
    <div className="metric-icon-wrapper" style={accent ? { borderColor: `${accent}33`, color: accent } : {}}>
      <Icon size={18} />
    </div>
    <div className="metric-info">
      <div className="metric-value" style={accent ? { color: accent } : {}}>{value}</div>
      <div className="metric-label">{label}</div>
    </div>
  </div>
);

export default MetricCard;
