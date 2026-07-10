import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Play, Download, Terminal as TerminalIcon, Database, CheckCircle2,
  AlertTriangle, History, FileSpreadsheet, Clock, Search, MapPin,
  Tag, Building2, TrendingUp, Star, ChevronUp, ChevronDown,
  ChevronRight, X, RefreshCw, BarChart3, Zap, Globe, Phone,
  Award, Target, Filter, Settings, ChevronLeft, Layers,
  Activity, ShieldCheck, Info,
} from 'lucide-react';

const API_BASE = 'http://localhost:8000/api';

// ── CATEGORIES ──────────────────────────────────────────────────────────────────

const CATEGORIES = [
  'Manufacturers', 'Exporters', 'Wholesalers', 'Retailers', 'Distributors',
  'Restaurants', 'Hotels', 'Catering Services', 'Bakeries', 'Sweet Shops',
  'Clinics / Doctors', 'Dental Clinics', 'Hospitals', 'Pharmacies',
  'Real Estate Agents', 'Construction Companies', 'Interior Designers', 'Architects',
  'IT Companies', 'Web Design Agencies', 'Digital Marketing Agencies',
  'CA / Accountants', 'Lawyers', 'Event Planners',
  'Wedding Photographers', 'Photographers', 'Videographers',
  'Auto Repair Shops', 'Car Dealers', 'Driving Schools',
  'Beauty Salons', 'Hair Salons', 'Spas', 'Gyms / Fitness Centers',
  'Jewelers', 'Clothing Stores', 'Furniture Shops',
  'Hardware Stores', 'Electrical Shops', 'Plumbers', 'Electricians',
  'Pest Control Services', 'Packers & Movers', 'Courier Services',
  'Travel Agencies', 'Schools', 'Coaching Centers', 'Tuition Centers',
  'Printing Shops', 'Laundries', 'Tailoring Shops', 'Grocery Stores',
  'Supermarkets', 'Electronics Stores', 'Optical Shops', 'Pet Shops',
  'Nurseries / Plant Shops', 'Chartered Accountants', 'Insurance Agents',
];

// ── HELPERS ─────────────────────────────────────────────────────────────────────

const gradeColor = (g) => {
  switch (g) {
    case 'A': return '#10b981';
    case 'B': return '#14b8a6';
    case 'C': return '#f59e0b';
    case 'D': return '#f97316';
    case 'F': return '#ef4444';
    default:  return '#6b7280';
  }
};

const priorityColor = (p) => {
  const s = (p || '').toUpperCase();
  if (s === 'HIGH') return 'var(--priority-high)';
  if (s === 'LOW')  return '#6b7280';
  return 'var(--priority-medium)';
};

const priorityBg = (p) => {
  const s = (p || '').toUpperCase();
  if (s === 'HIGH') return 'var(--priority-high-bg)';
  if (s === 'LOW')  return 'rgba(107,114,128,0.1)';
  return 'var(--priority-medium-bg)';
};

const priorityBorder = (p) => {
  const s = (p || '').toUpperCase();
  if (s === 'HIGH') return 'var(--priority-high-border)';
  if (s === 'LOW')  return 'rgba(107,114,128,0.2)';
  return 'var(--priority-medium-border)';
};

const formatDate = (ts) => {
  if (!ts) return '—';
  try {
    if (typeof ts === 'number') return new Date(ts * 1000).toLocaleString();
    return new Date(ts).toLocaleString();
  } catch { return ts; }
};

const formatRuntime = (secs) => {
  if (!secs) return '0s';
  const s = Math.round(secs);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return rem > 0 ? `${m}m ${rem}s` : `${m}m`;
};

const formatPct = (v) => `${((v || 0) * 100).toFixed(1)}%`;

const TERM_LABELS = {
  REQUESTED_COUNT_REACHED: 'Target reached',
  SEARCH_SPACE_EXHAUSTED:  'Search space exhausted',
  SEARCH_BUDGET_EXHAUSTED: 'Search budget exhausted',
  IN_PROGRESS:             'Running…',
};

const termLabel = (r) => TERM_LABELS[r] || r || '—';

// ── SHARED COMPONENTS ─────────────────────────────────────────────────────────

const Stars = ({ rating }) => {
  if (rating == null) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  return (
    <span style={{ color: '#f59e0b', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: 2 }}>
      <Star size={11} />
      {parseFloat(rating).toFixed(1)}
    </span>
  );
};

const GradeBadge = ({ grade }) => {
  if (!grade) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  const c = gradeColor(grade);
  return (
    <span style={{
      display: 'inline-block',
      background: `${c}22`, border: `1px solid ${c}55`,
      color: c, borderRadius: 4, padding: '1px 6px', fontWeight: 700, fontSize: '0.75rem',
    }}>{grade}</span>
  );
};

const PriorityBadge = ({ priority }) => {
  const p = (priority || '').toUpperCase();
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 3,
      background: priorityBg(p), border: `1px solid ${priorityBorder(p)}`,
      color: priorityColor(p), borderRadius: 4, padding: '2px 7px',
      fontWeight: 700, fontSize: '0.72rem',
    }}>
      <Tag size={10} />{p || '—'}
    </span>
  );
};

const ConfidenceBadge = ({ priority }) => {
  const p = (priority || '').toUpperCase();
  const label = p === 'HIGH' ? 'HIGH' : p === 'LOW' ? 'LOW' : 'MED';
  return (
    <span style={{
      display: 'inline-block',
      background: priorityBg(p), border: `1px solid ${priorityBorder(p)}`,
      color: priorityColor(p), borderRadius: 4, padding: '2px 7px',
      fontWeight: 700, fontSize: '0.72rem',
    }}>{label}</span>
  );
};

const ScoreBadge = ({ score, priority }) => {
  const p = (priority || '').toUpperCase();
  return (
    <span style={{
      display: 'inline-block',
      background: priorityBg(p), border: `1px solid ${priorityBorder(p)}`,
      color: priorityColor(p), borderRadius: 4, padding: '2px 6px',
      fontWeight: 700, fontSize: '0.75rem',
    }}>{score != null ? score.toFixed(1) : '0'}</span>
  );
};

const LoadingSpinner = ({ label }) => (
  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '3rem', gap: '0.75rem', color: 'var(--text-muted)' }}>
    <RefreshCw size={20} style={{ animation: 'spin 1s linear infinite' }} />
    <span>{label || 'Loading…'}</span>
  </div>
);

const ErrorState = ({ message, onRetry }) => (
  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '3rem', gap: '0.75rem', color: '#f87171' }}>
    <AlertTriangle size={32} style={{ opacity: 0.7 }} />
    <div style={{ fontWeight: 600 }}>Failed to load</div>
    <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>{message}</div>
    {onRetry && <button className="btn-secondary" onClick={onRetry}><RefreshCw size={14} /> Retry</button>}
  </div>
);

const EmptyState = ({ icon: Icon, message, sub }) => (
  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '3rem', gap: '0.75rem', color: 'var(--text-muted)' }}>
    <Icon size={40} style={{ opacity: 0.25 }} />
    <div style={{ fontWeight: 500 }}>{message}</div>
    {sub && <div style={{ fontSize: '0.85rem' }}>{sub}</div>}
  </div>
);

const SortHeader = ({ label, col, sortState, onSort }) => {
  const active = sortState.col === col;
  return (
    <th onClick={() => onSort(col)} style={{ cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap' }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        {label}
        {active
          ? (sortState.dir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />)
          : <ChevronUp size={12} style={{ opacity: 0.25 }} />
        }
      </span>
    </th>
  );
};

const ProgressBar = ({ value, max, label }) => {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: 4 }}>
        <span>{label}</span>
        <span style={{ fontWeight: 600, color: 'var(--color-accent)' }}>{value} / {max}</span>
      </div>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
};

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

// ── BUSINESS DETAIL DRAWER ────────────────────────────────────────────────────

const BusinessDetailDrawer = ({ biz, detail, loading, onClose }) => {
  if (!biz) return null;
  return (
    <div className="detail-drawer">
      <div className="detail-drawer-overlay" onClick={onClose} />
      <div className="detail-drawer-panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.5rem' }}>
          <div>
            <h2 style={{ fontFamily: 'var(--display-font)', fontWeight: 700, fontSize: '1.15rem' }}>{biz.name}</h2>
            <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginTop: 2 }}>
              {biz.category || detail?.category}{biz.area || detail?.area ? ` • ${biz.area || detail?.area}` : ''}
            </div>
          </div>
          <button className="btn-secondary" style={{ padding: '0.4rem' }} onClick={onClose}><X size={16} /></button>
        </div>

        {loading && <LoadingSpinner label="Loading detail…" />}
        {!loading && !detail && <div style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '2rem' }}>Could not load detail.</div>}
        {!loading && detail && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', overflowY: 'auto', maxHeight: 'calc(100vh - 160px)', paddingRight: 4 }}>

            {/* Business Info */}
            <div>
              <div className="detail-section-title">Business Information</div>
              <div className="detail-row"><Phone size={13} />{detail.phone || '—'}</div>
              {detail.contact_email && <div className="detail-row"><Globe size={13} />{detail.contact_email}</div>}
              {detail.website && <div className="detail-row"><Globe size={13} /><a href={detail.website} target="_blank" rel="noreferrer" style={{ color: 'var(--color-accent)' }}>{detail.website}</a></div>}
              {detail.address && <div className="detail-row"><MapPin size={13} />{detail.address}{detail.city ? `, ${detail.city}` : ''}</div>}
              <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
                <Stars rating={detail.rating} />
                {detail.review_count != null && <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{detail.review_count} reviews</span>}
                {detail.business_status && (
                  <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', background: 'rgba(255,255,255,0.05)', borderRadius: 4, padding: '1px 6px' }}>
                    {detail.business_status}
                  </span>
                )}
              </div>
              {detail.opening_hours && (
                <div style={{ marginTop: '0.5rem', fontSize: '0.78rem', color: 'var(--text-secondary)', background: 'rgba(19,25,38,0.4)', borderRadius: 6, padding: '0.5rem 0.75rem' }}>
                  <Clock size={11} style={{ marginRight: 4, display: 'inline', verticalAlign: 'middle' }} />
                  {detail.opening_hours}
                </div>
              )}
            </div>

            {/* Confidence Breakdown */}
            {detail.opportunities?.length > 0 && (
              <div>
                <div className="detail-section-title">Confidence Breakdown</div>
                {detail.opportunities.map((opp, i) => {
                  const score = opp.score || 0;
                  const p = score >= 60 ? 'HIGH' : score >= 28 ? 'MEDIUM' : 'LOW';
                  return (
                    <div key={i} style={{ background: 'rgba(19,25,38,0.4)', border: '1px solid var(--border-color)', borderRadius: 8, padding: '0.75rem', marginBottom: '0.6rem' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.4rem' }}>
                        <span style={{ fontWeight: 600, fontSize: '0.82rem' }}>{opp.title?.split(' — ')[0] || opp.pipeline_stage || '—'}</span>
                        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                          <ConfidenceBadge priority={p} />
                          <span style={{ fontSize: '0.75rem', color: 'var(--color-accent)', fontWeight: 700 }}>{score.toFixed(1)}</span>
                        </div>
                      </div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'flex', gap: '1rem' }}>
                        <span>{(opp.close_probability * 100).toFixed(0)}% close prob.</span>
                        <span>₹{Number(opp.estimated_value).toLocaleString()} est.</span>
                      </div>
                      {opp.signals?.length > 0 && (
                        <div style={{ marginTop: '0.5rem', display: 'flex', flexDirection: 'column', gap: 3 }}>
                          {opp.signals.slice(0, 5).map((sig, j) => (
                            <div key={j} style={{ fontSize: '0.73rem', display: 'flex', justifyContent: 'space-between' }}>
                              <span style={{ color: 'var(--text-secondary)' }}>{sig.rule_name}</span>
                              <span style={{ color: sig.score_delta > 0 ? '#10b981' : '#ef4444', fontWeight: 600 }}>
                                {sig.score_delta > 0 ? '+' : ''}{sig.score_delta.toFixed(1)}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            {/* Digital Maturity */}
            {detail.maturity && (
              <div>
                <div className="detail-section-title">Digital Maturity</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.75rem' }}>
                  <GradeBadge grade={detail.maturity.grade} />
                  <div style={{ flexGrow: 1, background: 'var(--border-color)', borderRadius: 4, height: 5, overflow: 'hidden' }}>
                    <div style={{ width: `${detail.maturity.score || 0}%`, height: '100%', background: gradeColor(detail.maturity.grade), borderRadius: 4 }} />
                  </div>
                  <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>{(detail.maturity.score || 0).toFixed(0)}/100</span>
                </div>
                {detail.maturity.dimensions?.map((dim, i) => (
                  <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '0.3rem 0', borderBottom: '1px solid var(--border-color)', fontSize: '0.78rem' }}>
                    <span style={{ color: dim.gap ? '#f97316' : '#10b981' }}>
                      {dim.gap ? '✗' : '✓'} {dim.name}
                    </span>
                    <span style={{ color: 'var(--text-muted)' }}>{dim.score?.toFixed(0)}/{dim.max_score?.toFixed(0)}</span>
                  </div>
                ))}
                {detail.maturity.gaps?.length > 0 && (
                  <div style={{ marginTop: '0.5rem' }}>
                    <div style={{ fontSize: '0.72rem', color: '#f97316', fontWeight: 600, marginBottom: 2 }}>Gaps:</div>
                    {detail.maturity.gaps.map((g, i) => (
                      <div key={i} style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', paddingLeft: 8 }}>• {g}</div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Discovery */}
            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', paddingTop: '0.5rem', borderTop: '1px solid var(--border-color)' }}>
              <div>Discovery Date: {formatDate(detail.first_discovered_at)}</div>
              <div style={{ marginTop: 2 }}>Last Seen: {formatDate(detail.last_scraped_at)}</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

// ── APP ─────────────────────────────────────────────────────────────────────────

export default function App() {
  // Navigation
  const [activeTab, setActiveTab] = useState('campaign');

  // Campaign tab
  const [location, setLocation] = useState('Ahmedabad');
  const [category, setCategory] = useState('Manufacturers');
  const [targetLeads, setTargetLeads] = useState(10);
  const [status, setStatus] = useState({ is_running: false, current_task: null, last_result: null, error: null });
  const [metrics, setMetrics] = useState(null);
  const [logs, setLogs] = useState([]);
  const [history, setHistory] = useState([]);
  const consoleRef = useRef(null);
  const wasRunningRef = useRef(false);

  // Qualified Leads tab
  const [leads, setLeads] = useState([]);
  const [selectedCampaign, setSelectedCampaign] = useState('');
  const [leadsSearch, setLeadsSearch] = useState('');
  const [leadsSort, setLeadsSort] = useState({ col: 'score', dir: 'desc' });
  const [loadingLeads, setLoadingLeads] = useState(false);
  const [errorLeads, setErrorLeads] = useState(null);
  const [selectedLeadBiz, setSelectedLeadBiz] = useState(null);
  const [leadBizDetail, setLeadBizDetail] = useState(null);
  const [loadingLeadDetail, setLoadingLeadDetail] = useState(false);

  // Opportunities tab
  const [opps, setOpps] = useState([]);
  const [loadingOpps, setLoadingOpps] = useState(false);
  const [errorOpps, setErrorOpps] = useState(null);
  const [selectedService, setSelectedService] = useState(null);
  const [oppDetail, setOppDetail] = useState({});
  const [expandedOpp, setExpandedOpp] = useState(null);

  // Business Registry tab
  const [businesses, setBusinesses] = useState([]);
  const [bizSearch, setBizSearch] = useState('');
  const [bizSort, setBizSort] = useState({ col: 'score', dir: 'desc' });
  const [loadingBiz, setLoadingBiz] = useState(false);
  const [errorBiz, setErrorBiz] = useState(null);
  const [selectedBiz, setSelectedBiz] = useState(null);
  const [bizDetail, setBizDetail] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // Analytics tab
  const [analytics, setAnalytics] = useState(null);
  const [loadingAnalytics, setLoadingAnalytics] = useState(false);

  // Settings tab
  const [settingsData, setSettingsData] = useState({});
  const [loadingSettings, setLoadingSettings] = useState(false);
  const [editedSettings, setEditedSettings] = useState({});
  const [savingKey, setSavingKey] = useState(null);

  // ── Data fetching ──────────────────────────────────────────────────────────

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/status`);
      setStatus(await res.json());
    } catch { /* ignore */ }
  }, []);

  const fetchMetrics = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/metrics`);
      setMetrics(await res.json());
    } catch { /* ignore */ }
  }, []);

  const fetchLogs = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/logs?lines=80`);
      const data = await res.json();
      if (data.logs) setLogs(data.logs);
    } catch { /* ignore */ }
  }, []);

  const fetchHistory = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/history`);
      setHistory(await res.json());
    } catch { /* ignore */ }
  }, []);

  const fetchLeads = useCallback(async (filename) => {
    if (!filename) return;
    setLoadingLeads(true);
    setErrorLeads(null);
    try {
      const res = await fetch(`${API_BASE}/leads/${filename}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setLeads(await res.json());
    } catch (e) {
      setErrorLeads(e.message);
      setLeads([]);
    } finally {
      setLoadingLeads(false);
    }
  }, []);

  const fetchOpps = useCallback(async () => {
    setLoadingOpps(true);
    setErrorOpps(null);
    try {
      const res = await fetch(`${API_BASE}/opportunities?limit=500`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setOpps(await res.json());
    } catch (e) {
      setErrorOpps(e.message);
    } finally {
      setLoadingOpps(false);
    }
  }, []);

  const fetchBiz = useCallback(async () => {
    setLoadingBiz(true);
    setErrorBiz(null);
    try {
      const params = new URLSearchParams({ limit: 300, sort_by: bizSort.col, sort_dir: bizSort.dir });
      if (bizSearch) params.set('search', bizSearch);
      const res = await fetch(`${API_BASE}/businesses?${params}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setBusinesses(await res.json());
    } catch (e) {
      setErrorBiz(e.message);
    } finally {
      setLoadingBiz(false);
    }
  }, [bizSearch, bizSort]);

  const fetchBizDetail = useCallback(async (id) => {
    setLoadingDetail(true);
    try {
      const res = await fetch(`${API_BASE}/businesses/${id}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setBizDetail(await res.json());
    } catch {
      setBizDetail(null);
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  const fetchLeadBizDetail = useCallback(async (bizId) => {
    setLoadingLeadDetail(true);
    setLeadBizDetail(null);
    try {
      const res = await fetch(`${API_BASE}/businesses/${bizId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setLeadBizDetail(await res.json());
    } catch {
      setLeadBizDetail(null);
    } finally {
      setLoadingLeadDetail(false);
    }
  }, []);

  const fetchOppDetail = useCallback(async (id) => {
    if (oppDetail[id]) return;
    try {
      const res = await fetch(`${API_BASE}/opportunities/${id}`);
      if (!res.ok) return;
      const data = await res.json();
      setOppDetail(prev => ({ ...prev, [id]: data }));
    } catch { /* ignore */ }
  }, [oppDetail]);

  const fetchAnalytics = useCallback(async () => {
    setLoadingAnalytics(true);
    try {
      const res = await fetch(`${API_BASE}/analytics`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setAnalytics(await res.json());
    } catch { /* ignore */ } finally {
      setLoadingAnalytics(false);
    }
  }, []);

  const fetchSettings = useCallback(async () => {
    setLoadingSettings(true);
    try {
      const res = await fetch(`${API_BASE}/settings`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSettingsData(data);
      const init = {};
      Object.entries(data).forEach(([k, v]) => { init[k] = v.value; });
      setEditedSettings(init);
    } catch { /* ignore */ } finally {
      setLoadingSettings(false);
    }
  }, []);

  const saveSetting = async (key) => {
    setSavingKey(key);
    try {
      await fetch(`${API_BASE}/settings/${encodeURIComponent(key)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: editedSettings[key] }),
      });
      setSettingsData(prev => ({ ...prev, [key]: { ...prev[key], value: editedSettings[key] } }));
    } catch { /* ignore */ } finally {
      setSavingKey(null);
    }
  };

  // ── Lifecycle ──────────────────────────────────────────────────────────────

  useEffect(() => {
    fetchHistory();
    fetchStatus();
    fetchMetrics();
    fetchLogs();
    const iv = setInterval(() => {
      fetchStatus();
      fetchMetrics();
      fetchLogs();
    }, 2000);
    return () => clearInterval(iv);
  }, [fetchHistory, fetchStatus, fetchMetrics, fetchLogs]);

  useEffect(() => {
    const isRunning = status.is_running;
    const wasRunning = wasRunningRef.current;
    wasRunningRef.current = isRunning;

    const fn = status.last_result?.file_name;
    if (fn && !isRunning) {
      const justFinished = wasRunning && !isRunning;
      if (!selectedCampaign || justFinished) {
        if (selectedCampaign !== fn) {
          setSelectedCampaign(fn);
          fetchLeads(fn);
          fetchHistory();
        }
      }
    }
  }, [status.is_running, status.last_result, selectedCampaign, fetchLeads, fetchHistory]);

  useEffect(() => {
    if (consoleRef.current) consoleRef.current.scrollTop = consoleRef.current.scrollHeight;
  }, [logs]);

  useEffect(() => {
    if (activeTab === 'opportunities') fetchOpps();
    if (activeTab === 'businesses')    fetchBiz();
    if (activeTab === 'analytics')     fetchAnalytics();
    if (activeTab === 'settings')      fetchSettings();
  }, [activeTab, fetchOpps, fetchBiz, fetchAnalytics, fetchSettings]);

  // ── Derived data ──────────────────────────────────────────────────────────

  const filteredLeads = leads
    .filter(l => {
      const q = leadsSearch.toLowerCase();
      return !q || [l.name, l.phone, l.area, l.category, l.top_opportunity]
        .some(v => (v || '').toLowerCase().includes(q));
    })
    .sort((a, b) => {
      const { col, dir } = leadsSort;
      const va = a[col] ?? (col === 'score' ? 0 : '');
      const vb = b[col] ?? (col === 'score' ? 0 : '');
      const cmp = typeof va === 'number' ? va - vb : String(va).localeCompare(String(vb));
      return dir === 'asc' ? cmp : -cmp;
    });

  const toggleLeadsSort = (col) =>
    setLeadsSort(prev => ({ col, dir: prev.col === col && prev.dir === 'desc' ? 'asc' : 'desc' }));

  const toggleBizSort = (col) => {
    setBizSort(prev => ({ col, dir: prev.col === col && prev.dir === 'desc' ? 'asc' : 'desc' }));
  };

  const toggleOpp = (id) => {
    if (expandedOpp === id) { setExpandedOpp(null); return; }
    setExpandedOpp(id);
    fetchOppDetail(id);
  };

  // Group opportunities by service name extracted from title "Service — Business"
  const oppsByService = opps.reduce((acc, opp) => {
    const svc = (opp.title || '').split(' — ')[0].trim() || opp.pipeline_stage || 'Other';
    if (!acc[svc]) acc[svc] = [];
    acc[svc].push(opp);
    return acc;
  }, {});

  // Rejection telemetry from last result or live metrics
  const getRejectionData = () => {
    if (status.is_running && metrics) {
      const tier1 = metrics.tier1_rejections || {};
      const prog = metrics.progress || {};
      return {
        'No Phone':       tier1.NO_PHONE || 0,
        'Has Website':    tier1.HAS_WEBSITE || 0,
        'Closed':         tier1.CLOSED || 0,
        'No Name':        tier1.NO_NAME || 0,
        'Duplicate':      prog.duplicates || 0,
        'Wrong Category': 0,
        'Wrong City':     0,
        'Ghost Listing':  0,
      };
    }
    const lr = status.last_result;
    if (!lr) return null;
    return {
      'No Phone':        lr.no_phone_count || 0,
      'Has Website':     lr.has_website_count || 0,
      'Wrong Category':  lr.wrong_category_count || 0,
      'Wrong City':      lr.wrong_city_count || 0,
      'Ghost Listing':   lr.ghost_listing_count || 0,
      'Closed':          lr.permanently_closed_count || 0,
      'Duplicate':       lr.duplicate_count || 0,
      'Unverified Cat.': lr.category_unverified_count || 0,
    };
  };

  // Live campaign numbers (while running or from last result)
  const getCampaignNumbers = () => {
    if (status.is_running && metrics?.progress) {
      const p = metrics.progress;
      return {
        qualified: p.qualified || 0,
        requested: p.requested || targetLeads,
        visited:   p.visited || 0,
        rejected:  p.rejected || 0,
        duplicates: p.duplicates || 0,
        runtime:   metrics.elapsed_sec || 0,
        termination: metrics.active_termination_condition || 'IN_PROGRESS',
        yieldRate: metrics.yield_rate || 0,
        avgConfidence: metrics.avg_confidence || 0,
        isLive: true,
      };
    }
    const lr = status.last_result;
    if (lr) {
      return {
        qualified: lr.qualified_count || 0,
        requested: lr.requested_count || 0,
        visited:   lr.searched_count || 0,
        rejected:  lr.rejected_count || 0,
        duplicates: lr.duplicate_count || 0,
        runtime:   lr.duration_sec || 0,
        termination: lr.termination_reason || '',
        yieldRate: lr.searched_count > 0 ? (lr.qualified_count / lr.searched_count) : 0,
        avgConfidence: lr.avg_confidence || 0,
        isLive: false,
      };
    }
    return null;
  };

  // ── Campaign launch ────────────────────────────────────────────────────────

  const handleLaunchCampaign = async (e) => {
    e.preventDefault();
    if (status.is_running) return;
    try {
      const res = await fetch(`${API_BASE}/scrape`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ city: location, category, limit: Number(targetLeads), no_website_only: true }),
      });
      if (res.ok) {
        setLeads([]); setSelectedCampaign(''); fetchStatus(); fetchMetrics();
      } else {
        const d = await res.json();
        alert(`Failed to start: ${d.detail}`);
      }
    } catch {
      alert('API Error: make sure the server is running on port 8000.');
    }
  };

  // ── Export ─────────────────────────────────────────────────────────────────

  const handleExport = async (mode, campaignName) => {
    try {
      const res = await fetch(`${API_BASE}/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode, campaign_name: campaignName || null, limit: 1000 }),
      });
      if (!res.ok) { alert('Export failed.'); return; }
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      const cd   = res.headers.get('Content-Disposition') || '';
      const fn   = cd.match(/filename="?([^"]+)"?/)?.[1] || 'export.xlsx';
      a.href = url; a.download = fn; a.click();
      URL.revokeObjectURL(url);
    } catch { alert('Export failed.'); }
  };

  // ── TAB: Campaign ──────────────────────────────────────────────────────────

  const renderCampaign = () => {
    const nums = getCampaignNumbers();
    const rejections = getRejectionData();
    const isRunning = status.is_running;

    return (
      <div className="dashboard-grid">
        {/* Left column: form + history */}
        <section style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          <div className="panel">
            <h2 className="panel-title"><Play size={16} color="var(--color-accent)" /> Campaign Configuration</h2>
            <form onSubmit={handleLaunchCampaign}>
              <div className="form-group">
                <label className="form-label">Location</label>
                <input type="text" className="form-input" value={location}
                  onChange={e => setLocation(e.target.value)} disabled={isRunning} required
                  placeholder="City, area, or region…" />
              </div>
              <div className="form-group">
                <label className="form-label">Business Category</label>
                <input type="text" className="form-input" list="category-list"
                  value={category} onChange={e => setCategory(e.target.value)}
                  disabled={isRunning} placeholder="Type or select…" required />
                <datalist id="category-list">
                  {CATEGORIES.map(c => <option key={c} value={c} />)}
                </datalist>
              </div>
              <div className="form-group">
                <label className="form-label">Target Qualified Leads</label>
                <input type="number" className="form-input" value={targetLeads}
                  onChange={e => setTargetLeads(e.target.value)}
                  disabled={isRunning} min="1" max="300" required />
              </div>
              <button type="submit" className={`btn-primary ${isRunning ? '' : 'pulse-button'}`} disabled={isRunning}>
                <Play size={16} />
                {isRunning ? `Running… ${status.current_task ? `(${status.current_task})` : ''}` : 'Launch Campaign'}
              </button>
            </form>
            {status.error && (
              <div style={{ marginTop: '0.75rem', color: '#f87171', display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.82rem' }}>
                <AlertTriangle size={14} /> {status.error}
              </div>
            )}
          </div>

          {/* Campaign History */}
          <div className="panel">
            <h2 className="panel-title"><History size={16} color="var(--color-accent)" /> Recent Campaigns</h2>
            <div style={{ maxHeight: 280, overflowY: 'auto' }}>
              {history.length === 0
                ? <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>No campaigns yet.</div>
                : history.slice(0, 12).map((run, i) => (
                  <div key={i} className="history-item"
                    style={{ borderColor: selectedCampaign === run.filename ? 'var(--color-accent)' : 'var(--border-color)', cursor: 'pointer' }}
                    onClick={() => { setSelectedCampaign(run.filename); fetchLeads(run.filename); setActiveTab('qualified-leads'); }}>
                    <div className="history-details">
                      <div className="history-name"><MapPin size={11} style={{ display: 'inline', marginRight: 3, color: 'var(--text-muted)' }} />{run.city} — {run.category}</div>
                      <div className="history-meta">{run.status} · {formatDate(run.created_at)}</div>
                    </div>
                    <ChevronRight size={14} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
                  </div>
                ))
              }
            </div>
          </div>

          {/* Developer link */}
          <div className="panel" style={{ padding: '0.85rem 1.25rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-muted)', fontSize: '0.82rem' }}>
                <TerminalIcon size={13} />
                <span>Runtime logs are in the Developer tab.</span>
              </div>
              <button className="btn-secondary" style={{ fontSize: '0.78rem' }} onClick={() => setActiveTab('developer')}>
                View Logs
              </button>
            </div>
          </div>
        </section>

        {/* Right column: live dashboard */}
        <section style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {/* Campaign Status */}
          <div className="panel">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem' }}>
              <h2 style={{ fontFamily: 'var(--display-font)', fontWeight: 600, fontSize: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Activity size={16} color="var(--color-accent)" /> Campaign Dashboard
              </h2>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                {isRunning ? (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--color-accent)', fontSize: '0.8rem', fontWeight: 600 }}>
                    <span className="pulse-button" style={{ display: 'inline-block', width: 7, height: 7, background: 'var(--color-accent)', borderRadius: '50%' }} />
                    RUNNING
                  </span>
                ) : nums ? (
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', background: 'rgba(255,255,255,0.04)', border: '1px solid var(--border-color)', borderRadius: 4, padding: '2px 8px' }}>
                    COMPLETED
                  </span>
                ) : (
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>IDLE</span>
                )}
              </div>
            </div>

            {!nums ? (
              <EmptyState icon={Play} message="No campaign data" sub="Configure and launch a campaign to see live progress." />
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {/* Progress bar */}
                <ProgressBar value={nums.qualified} max={nums.requested} label="Qualified Progress" />

                {/* Metric cards */}
                <div className="metrics-row" style={{ marginBottom: 0 }}>
                  <MetricCard Icon={Target}      value={nums.requested}          label="Requested" />
                  <MetricCard Icon={CheckCircle2} value={nums.qualified}         label="Qualified" accent="var(--color-accent)" />
                  <MetricCard Icon={AlertTriangle} value={nums.rejected}         label="Rejected" />
                  <MetricCard Icon={Database}     value={Math.max(0, nums.requested - nums.qualified)} label="Remaining" />
                  <MetricCard Icon={Clock}        value={formatRuntime(nums.runtime)} label="Runtime" />
                  <MetricCard Icon={Search}       value={nums.visited}           label="Visited" />
                </div>

                {/* Secondary stats */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.75rem' }}>
                  {[
                    { label: 'Qualification Yield', value: formatPct(nums.yieldRate) },
                    { label: 'Avg Confidence',      value: formatPct(nums.avgConfidence) },
                    { label: 'Duplicates Skipped',  value: nums.duplicates },
                  ].map(({ label, value }) => (
                    <div key={label} style={{ background: 'rgba(19,25,38,0.5)', border: '1px solid var(--border-color)', borderRadius: 8, padding: '0.6rem 0.75rem', textAlign: 'center' }}>
                      <div style={{ fontSize: '1.1rem', fontWeight: 700, fontFamily: 'var(--display-font)', color: 'var(--text-primary)' }}>{value}</div>
                      <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: 2 }}>{label}</div>
                    </div>
                  ))}
                </div>

                {/* Termination reason */}
                {nums.termination && nums.termination !== 'IN_PROGRESS' && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.5rem 0.75rem', background: 'rgba(20,184,166,0.06)', border: '1px solid rgba(20,184,166,0.2)', borderRadius: 6 }}>
                    <ShieldCheck size={14} color="var(--color-accent)" />
                    <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                      Termination: <strong style={{ color: 'var(--color-accent)' }}>{termLabel(nums.termination)}</strong>
                    </span>
                  </div>
                )}

                {/* Export Verification */}
                {!isRunning && status.last_result && (() => {
                  const lr = status.last_result;
                  const sqlite = lr.sqlite_count ?? 0;
                  const exp    = lr.export_count ?? lr.qualified_count ?? 0;
                  const ok     = sqlite === exp;
                  return (
                    <div style={{ background: 'rgba(19,25,38,0.45)', border: '1px solid var(--border-color)', borderRadius: 8, padding: '0.75rem 1rem' }}>
                      <div style={{ fontSize: '0.68rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '0.5rem' }}>
                        Export Verification
                      </div>
                      <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                        <div style={{ textAlign: 'center' }}>
                          <div style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)' }}>{sqlite}</div>
                          <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)' }}>SQLite</div>
                        </div>
                        <span style={{ color: 'var(--text-muted)', fontWeight: 700 }}>=</span>
                        <div style={{ textAlign: 'center' }}>
                          <div style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)' }}>{exp}</div>
                          <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)' }}>Export</div>
                        </div>
                        <div style={{ marginLeft: 'auto' }}>
                          {ok ? (
                            <span style={{ display: 'flex', alignItems: 'center', gap: 4, color: '#10b981', fontSize: '0.8rem', fontWeight: 600 }}>
                              <CheckCircle2 size={13} /> Verified
                            </span>
                          ) : (
                            <span style={{ display: 'flex', alignItems: 'center', gap: 4, color: '#f87171', fontSize: '0.8rem', fontWeight: 600 }}>
                              <AlertTriangle size={13} /> Mismatch
                            </span>
                          )}
                        </div>
                      </div>
                      {lr.file_name && (
                        <div style={{ marginTop: '0.4rem', fontSize: '0.68rem', color: 'var(--text-muted)' }}>
                          {lr.file_name}
                        </div>
                      )}
                    </div>
                  );
                })()}

                {/* Campaign actions */}
                {!isRunning && selectedCampaign && (
                  <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                    <button className="btn-secondary" style={{ fontSize: '0.8rem' }}
                      onClick={() => { setActiveTab('qualified-leads'); }}>
                      <FileSpreadsheet size={13} /> View Leads
                    </button>
                    <button className="btn-secondary" style={{ fontSize: '0.8rem' }}
                      onClick={() => handleExport('campaign', selectedCampaign)}>
                      <Download size={13} /> Export Campaign
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Rejection Intelligence */}
          {rejections && (
            <div className="panel">
              <h2 className="panel-title"><Filter size={16} color="var(--color-accent)" /> Rejection Intelligence</h2>
              <div className="rejection-grid">
                {Object.entries(rejections).map(([label, count]) => (
                  <div key={label} className="rejection-card">
                    <div className="rejection-count">{count}</div>
                    <div className="rejection-label">{label}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      </div>
    );
  };

  // ── TAB: Qualified Leads ───────────────────────────────────────────────────

  const renderQualifiedLeads = () => (
    <div style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      {/* Campaign selector + exports */}
      <div className="panel" style={{ padding: '0.85rem 1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.75rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <CheckCircle2 size={16} color="var(--color-accent)" />
            <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>{selectedCampaign || 'No campaign loaded'}</span>
            {selectedCampaign && <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{leads.length} leads</span>}
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            {selectedCampaign && (
              <button className="btn-secondary" style={{ fontSize: '0.8rem' }} onClick={() => handleExport('campaign', selectedCampaign)}>
                <Download size={13} /> Export Campaign
              </button>
            )}
            <button className="btn-secondary" style={{ fontSize: '0.8rem' }} onClick={() => handleExport('high_priority', null)}>
              <Zap size={13} /> Export High Priority
            </button>
          </div>
        </div>
      </div>

      {/* History quick-select */}
      {history.length > 0 && (
        <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
          {history.slice(0, 8).map((run, i) => (
            <button key={i} className="btn-secondary"
              style={{ fontSize: '0.75rem', borderColor: selectedCampaign === run.filename ? 'var(--color-accent)' : 'var(--border-color)', color: selectedCampaign === run.filename ? 'var(--color-accent)' : undefined }}
              onClick={() => { setSelectedCampaign(run.filename); fetchLeads(run.filename); }}>
              <MapPin size={10} /> {run.city} / {run.category}
            </button>
          ))}
        </div>
      )}

      {/* Leads table */}
      <div className="panel" style={{ flexGrow: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
          <div style={{ position: 'relative', flexGrow: 1, minWidth: 200 }}>
            <input type="text" className="form-input" placeholder="Filter by name, phone, area, opportunity…"
              style={{ paddingLeft: '2.25rem' }} value={leadsSearch} onChange={e => setLeadsSearch(e.target.value)} />
            <Search size={14} style={{ position: 'absolute', left: '0.75rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
          </div>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{filteredLeads.length} of {leads.length}</span>
        </div>

        {loadingLeads && <LoadingSpinner label="Loading qualified leads…" />}
        {!loadingLeads && errorLeads && <ErrorState message={errorLeads} onRetry={() => fetchLeads(selectedCampaign)} />}
        {!loadingLeads && !errorLeads && leads.length === 0 && (
          <EmptyState icon={CheckCircle2} message="No qualified leads" sub="Select a campaign or launch a new one." />
        )}
        {!loadingLeads && !errorLeads && leads.length > 0 && (
          <div className="leads-table-container">
            <table className="leads-table">
              <thead>
                <tr>
                  <SortHeader label="Business"         col="name"          sortState={leadsSort} onSort={toggleLeadsSort} />
                  <th>Phone</th>
                  <SortHeader label="Area"             col="area"          sortState={leadsSort} onSort={toggleLeadsSort} />
                  <SortHeader label="Confidence"       col="score"         sortState={leadsSort} onSort={toggleLeadsSort} />
                  <th>Top Opportunity</th>
                  <SortHeader label="Priority"         col="priority"      sortState={leadsSort} onSort={toggleLeadsSort} />
                </tr>
              </thead>
              <tbody>
                {filteredLeads.map((lead, idx) => (
                  <tr key={idx} style={{ cursor: lead.business_id ? 'pointer' : 'default' }}
                    onClick={() => {
                      if (!lead.business_id) return;
                      setSelectedLeadBiz(lead);
                      fetchLeadBizDetail(lead.business_id);
                    }}>
                    <td>
                      <div style={{ fontWeight: 500, fontSize: '0.88rem' }}>{lead.name}</div>
                      <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{lead.category}</div>
                    </td>
                    <td style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>{lead.phone || '—'}</td>
                    <td style={{ fontSize: '0.82rem' }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                        <MapPin size={10} style={{ color: 'var(--text-muted)' }} />{lead.area || '—'}
                      </span>
                    </td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                        <ConfidenceBadge priority={lead.priority} />
                        <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{lead.score?.toFixed(1)}</span>
                      </div>
                    </td>
                    <td style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {(lead.top_opportunity || '').split(' — ')[0] || '—'}
                    </td>
                    <td><PriorityBadge priority={lead.priority} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Detail drawer for a selected lead */}
      <BusinessDetailDrawer
        biz={selectedLeadBiz}
        detail={leadBizDetail}
        loading={loadingLeadDetail}
        onClose={() => { setSelectedLeadBiz(null); setLeadBizDetail(null); }}
      />
    </div>
  );

  // ── TAB: Opportunities ─────────────────────────────────────────────────────

  const renderOpportunities = () => {
    const serviceNames = Object.keys(oppsByService).sort((a, b) => {
      const totA = oppsByService[a].reduce((s, o) => s + (o.score || 0), 0);
      const totB = oppsByService[b].reduce((s, o) => s + (o.score || 0), 0);
      return totB - totA;
    });

    if (selectedService && oppsByService[selectedService]) {
      const serviceOpps = oppsByService[selectedService];
      return (
        <div style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <button className="btn-secondary" style={{ fontSize: '0.8rem' }} onClick={() => setSelectedService(null)}>
              <ChevronLeft size={14} /> Services
            </button>
            <h2 style={{ fontFamily: 'var(--display-font)', fontWeight: 600, fontSize: '1rem', color: 'var(--color-accent)' }}>
              {selectedService}
            </h2>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{serviceOpps.length} businesses</span>
          </div>

          <div className="panel">
            <div className="leads-table-container">
              <table className="leads-table">
                <thead>
                  <tr>
                    <th>Business</th>
                    <th>Category</th>
                    <th>Score</th>
                    <th>Close Prob.</th>
                    <th>Est. Value</th>
                    <th>Maturity</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {serviceOpps.map(opp => {
                    const expanded = expandedOpp === opp.id;
                    const detail = oppDetail[opp.id];
                    return (
                      <React.Fragment key={opp.id}>
                        <tr style={{ cursor: 'pointer' }} onClick={() => toggleOpp(opp.id)}>
                          <td style={{ fontWeight: 500, fontSize: '0.88rem' }}>{opp.business_name}</td>
                          <td style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>{opp.business_category}</td>
                          <td><ScoreBadge score={opp.score} priority={opp.priority} /></td>
                          <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{(opp.close_probability * 100).toFixed(0)}%</td>
                          <td style={{ fontSize: '0.8rem', color: 'var(--color-accent)', fontWeight: 600 }}>₹{Number(opp.estimated_value).toLocaleString()}</td>
                          <td><GradeBadge grade={opp.maturity_grade} /></td>
                          <td>{expanded ? <ChevronUp size={14} /> : <ChevronRight size={14} />}</td>
                        </tr>
                        {expanded && (
                          <tr>
                            <td colSpan={7} style={{ background: 'rgba(19,25,38,0.3)', padding: '0.75rem 1rem' }}>
                              {!detail
                                ? <LoadingSpinner label="Loading signals…" />
                                : (
                                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                                    {(detail.signals || []).map((sig, i) => (
                                      <div key={i} style={{
                                        background: sig.score_delta > 0 ? 'rgba(16,185,129,0.06)' : 'rgba(239,68,68,0.06)',
                                        border: `1px solid ${sig.score_delta > 0 ? 'rgba(16,185,129,0.2)' : 'rgba(239,68,68,0.2)'}`,
                                        borderRadius: 6, padding: '0.4rem 0.6rem', fontSize: '0.75rem',
                                      }}>
                                        <span style={{ color: 'var(--text-secondary)' }}>{sig.rule_name}</span>
                                        <span style={{ marginLeft: 8, fontWeight: 700, color: sig.score_delta > 0 ? '#10b981' : '#ef4444' }}>
                                          {sig.score_delta > 0 ? '+' : ''}{sig.score_delta.toFixed(1)}
                                        </span>
                                      </div>
                                    ))}
                                    {(!detail.signals || detail.signals.length === 0) && (
                                      <span style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>No signals recorded.</span>
                                    )}
                                  </div>
                                )
                              }
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      );
    }

    // Service grid view
    return (
      <div style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Layers size={16} color="var(--color-accent)" />
            <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>Opportunities by Service</span>
          </div>
          <button className="btn-secondary" style={{ fontSize: '0.8rem' }} onClick={fetchOpps}>
            <RefreshCw size={13} />
          </button>
        </div>

        {loadingOpps && <LoadingSpinner label="Loading opportunities…" />}
        {!loadingOpps && errorOpps && <ErrorState message={errorOpps} onRetry={fetchOpps} />}
        {!loadingOpps && !errorOpps && serviceNames.length === 0 && (
          <EmptyState icon={TrendingUp} message="No opportunities yet" sub="Run a campaign to generate opportunity intelligence." />
        )}

        {!loadingOpps && !errorOpps && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '1rem' }}>
            {serviceNames.map(svc => {
              const svcOpps = oppsByService[svc];
              const totalValue    = svcOpps.reduce((s, o) => s + (o.estimated_value || 0), 0);
              const highCount     = svcOpps.filter(o => (o.priority || '').toUpperCase() === 'HIGH').length;
              const avgScore      = svcOpps.reduce((s, o) => s + (o.score || 0), 0) / svcOpps.length;
              const avgConfidence = svcOpps.reduce((s, o) => s + (o.close_probability || 0), 0) / svcOpps.length;
              return (
                <div key={svc} className="panel service-card" onClick={() => setSelectedService(svc)} style={{ cursor: 'pointer' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem' }}>
                    <div style={{ fontWeight: 600, fontSize: '0.92rem', color: 'var(--text-primary)', lineHeight: 1.3, maxWidth: '70%' }}>{svc}</div>
                    <ChevronRight size={16} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
                  </div>
                  <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
                    <div className="svc-stat"><span className="svc-stat-val">{svcOpps.length}</span><span className="svc-stat-lbl">Businesses</span></div>
                    <div className="svc-stat"><span className="svc-stat-val" style={{ color: 'var(--priority-high)' }}>{highCount}</span><span className="svc-stat-lbl">High Priority</span></div>
                    <div className="svc-stat"><span className="svc-stat-val">{avgScore.toFixed(0)}</span><span className="svc-stat-lbl">Avg Score</span></div>
                    <div className="svc-stat"><span className="svc-stat-val">{formatPct(avgConfidence)}</span><span className="svc-stat-lbl">Avg Conf.</span></div>
                  </div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--color-accent)', fontWeight: 600 }}>
                    ₹{Number(totalValue).toLocaleString()} est. pipeline
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  };

  // ── TAB: Business Registry ─────────────────────────────────────────────────

  const renderBusinessRegistry = () => (
    <div style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.25rem', position: 'relative' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', flexGrow: 1, minWidth: 200 }}>
          <input type="text" className="form-input" placeholder="Search by name, category, area…"
            style={{ paddingLeft: '2.25rem' }} value={bizSearch}
            onChange={e => setBizSearch(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') fetchBiz(); }} />
          <Search size={14} style={{ position: 'absolute', left: '0.75rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
        </div>
        <button className="btn-secondary" style={{ fontSize: '0.8rem' }} onClick={fetchBiz}><RefreshCw size={13} /></button>
        <button className="btn-secondary" style={{ fontSize: '0.8rem' }} onClick={() => handleExport('all', null)}>
          <Download size={13} /> Export All
        </button>
        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{businesses.length} businesses</span>
      </div>

      {loadingBiz && <LoadingSpinner label="Loading registry…" />}
      {!loadingBiz && errorBiz && <ErrorState message={errorBiz} onRetry={fetchBiz} />}
      {!loadingBiz && !errorBiz && businesses.length === 0 && (
        <EmptyState icon={Building2} message="Registry empty" sub="Run a campaign to populate the business registry." />
      )}

      {!loadingBiz && !errorBiz && businesses.length > 0 && (
        <div className="panel">
          <div className="leads-table-container">
            <table className="leads-table">
              <thead>
                <tr>
                  <SortHeader label="Business"   col="name"          sortState={bizSort} onSort={toggleBizSort} />
                  <th>Category</th>
                  <th>Phone</th>
                  <th>Website</th>
                  <th>Campaigns</th>
                  <th>Last Seen</th>
                  <th>Confidence</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {businesses.map((biz, idx) => (
                  <tr key={idx} style={{ cursor: 'pointer' }} onClick={() => { setSelectedBiz(biz); setBizDetail(null); fetchBizDetail(biz.id); }}>
                    <td>
                      <div style={{ fontWeight: 500, fontSize: '0.88rem' }}>{biz.name}</div>
                      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}><MapPin size={9} style={{ display: 'inline', marginRight: 2 }} />{biz.area || '—'}</div>
                    </td>
                    <td style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>{biz.category || '—'}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: '0.78rem' }}>{biz.phone || '—'}</td>
                    <td style={{ fontSize: '0.78rem' }}>
                      {biz.website
                        ? <a href={biz.website} target="_blank" rel="noreferrer" style={{ color: 'var(--color-accent)', textDecoration: 'none', fontSize: '0.75rem' }}
                            onClick={e => e.stopPropagation()}><Globe size={11} style={{ marginRight: 2 }} />Site</a>
                        : <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>None</span>
                      }
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      <span style={{ background: 'rgba(20,184,166,0.08)', border: '1px solid rgba(20,184,166,0.2)', borderRadius: 4, padding: '1px 7px', fontSize: '0.75rem', color: 'var(--color-accent)', fontWeight: 600 }}>
                        {biz.discovery_count || 1}
                      </span>
                    </td>
                    <td style={{ fontSize: '0.75rem', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                      {biz.last_scraped_at ? new Date(biz.last_scraped_at).toLocaleDateString() : '—'}
                    </td>
                    <td><ConfidenceBadge priority={biz.priority} /></td>
                    <td>
                      {biz.business_status ? (
                        <span style={{ fontSize: '0.7rem', color: biz.business_status === 'OPERATIONAL' ? '#10b981' : 'var(--text-muted)', background: 'rgba(255,255,255,0.04)', borderRadius: 4, padding: '1px 5px', border: '1px solid var(--border-color)' }}>
                          {biz.business_status}
                        </span>
                      ) : '—'}
                    </td>
                    <td><ChevronRight size={13} style={{ color: 'var(--text-muted)' }} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <BusinessDetailDrawer
        biz={selectedBiz}
        detail={bizDetail}
        loading={loadingDetail}
        onClose={() => { setSelectedBiz(null); setBizDetail(null); }}
      />
    </div>
  );

  // ── TAB: Analytics ─────────────────────────────────────────────────────────

  const renderAnalytics = () => {
    if (loadingAnalytics) return <LoadingSpinner label="Loading analytics…" />;
    if (!analytics) return <EmptyState icon={BarChart3} message="No analytics data" sub="Run campaigns to generate analytics." />;

    const { summary, campaigns } = analytics;

    return (
      <div style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        {/* Summary cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '1rem' }}>
          {[
            { Icon: Play,         label: 'Campaigns',           value: summary.total_campaigns },
            { Icon: CheckCircle2, label: 'Total Qualified',     value: summary.total_qualified,          accent: 'var(--color-accent)' },
            { Icon: Target,       label: 'Total Requested',     value: summary.total_requested },
            { Icon: BarChart3,    label: 'Qualification Yield', value: formatPct(summary.qualification_yield), accent: '#10b981' },
            { Icon: Clock,        label: 'Avg Runtime',         value: formatRuntime(summary.avg_runtime_sec) },
            { Icon: Award,        label: 'Avg Confidence',      value: formatPct(summary.avg_confidence),   accent: '#f59e0b' },
          ].map(({ Icon, label, value, accent }) => (
            <MetricCard key={label} Icon={Icon} value={value} label={label} accent={accent} />
          ))}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
          {/* Top Locations */}
          <div className="panel">
            <h2 className="panel-title"><MapPin size={15} color="var(--color-accent)" /> Top Locations</h2>
            {summary.top_locations.length === 0
              ? <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>No data yet.</div>
              : summary.top_locations.map(({ name, count }) => (
                <div key={name} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.4rem 0', borderBottom: '1px solid var(--border-color)' }}>
                  <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>{name}</span>
                  <span style={{ fontWeight: 600, fontSize: '0.8rem', color: 'var(--color-accent)' }}>{count} campaigns</span>
                </div>
              ))
            }
          </div>

          {/* Top Categories */}
          <div className="panel">
            <h2 className="panel-title"><Tag size={15} color="var(--color-accent)" /> Top Categories</h2>
            {summary.top_categories.length === 0
              ? <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>No data yet.</div>
              : summary.top_categories.map(({ name, count }) => (
                <div key={name} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.4rem 0', borderBottom: '1px solid var(--border-color)' }}>
                  <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>{name}</span>
                  <span style={{ fontWeight: 600, fontSize: '0.8rem', color: 'var(--color-accent)' }}>{count} campaigns</span>
                </div>
              ))
            }
          </div>
        </div>

        {/* Rejection Breakdown */}
        {Object.keys(summary.rejection_breakdown || {}).length > 0 && (
          <div className="panel">
            <h2 className="panel-title"><Filter size={15} color="var(--color-accent)" /> Rejection Breakdown (All Time)</h2>
            <div className="rejection-grid">
              {Object.entries(summary.rejection_breakdown)
                .sort(([, a], [, b]) => b - a)
                .map(([key, count]) => (
                  <div key={key} className="rejection-card">
                    <div className="rejection-count">{count}</div>
                    <div className="rejection-label">{key.replace(/_/g, ' ')}</div>
                  </div>
                ))
              }
            </div>
          </div>
        )}

        {/* Campaign History */}
        <div className="panel">
          <h2 className="panel-title"><History size={15} color="var(--color-accent)" /> Campaign History</h2>
          <div className="leads-table-container">
            <table className="leads-table">
              <thead>
                <tr>
                  <th>Location</th>
                  <th>Category</th>
                  <th>Status</th>
                  <th>Qualified</th>
                  <th>Requested</th>
                  <th>Runtime</th>
                  <th>Avg Confidence</th>
                  <th>Termination</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {campaigns.map((c, i) => (
                  <tr key={i}>
                    <td style={{ fontSize: '0.82rem', fontWeight: 500 }}>{c.city}</td>
                    <td style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>{c.category}</td>
                    <td>
                      <span style={{
                        fontSize: '0.7rem', fontWeight: 600, borderRadius: 4, padding: '1px 6px',
                        background: c.status === 'COMPLETED' ? 'rgba(16,185,129,0.1)' : c.status === 'RUNNING' ? 'rgba(20,184,166,0.1)' : 'rgba(239,68,68,0.08)',
                        color: c.status === 'COMPLETED' ? '#10b981' : c.status === 'RUNNING' ? 'var(--color-accent)' : '#f87171',
                        border: `1px solid ${c.status === 'COMPLETED' ? 'rgba(16,185,129,0.25)' : c.status === 'RUNNING' ? 'rgba(20,184,166,0.25)' : 'rgba(239,68,68,0.2)'}`,
                      }}>{c.status}</span>
                    </td>
                    <td style={{ fontWeight: 600, color: 'var(--color-accent)', fontSize: '0.85rem' }}>{c.qualified_count}</td>
                    <td style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>{c.requested_count}</td>
                    <td style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>{formatRuntime(c.duration_sec)}</td>
                    <td style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>{c.avg_confidence > 0 ? formatPct(c.avg_confidence) : '—'}</td>
                    <td style={{ fontSize: '0.73rem', color: 'var(--text-muted)', maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {termLabel(c.termination_reason)}
                    </td>
                    <td style={{ fontSize: '0.73rem', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                      {c.started_at ? new Date(c.started_at).toLocaleDateString() : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    );
  };

  // ── Factory Reset ──────────────────────────────────────────────────────────
  const [resetDialogOpen, setResetDialogOpen]   = useState(false);
  const [resetConfirmText, setResetConfirmText] = useState('');
  const [resetRunning, setResetRunning]         = useState(false);
  const [resetSuccess, setResetSuccess]         = useState(false);

  const executeFactoryReset = async () => {
    setResetRunning(true);
    try {
      const res = await fetch(`${API_BASE}/factory-reset`, { method: 'POST' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        alert(`Reset failed: ${err.detail}`);
        return;
      }
      setResetDialogOpen(false);
      setResetConfirmText('');
      setResetSuccess(true);
      setTimeout(() => setResetSuccess(false), 4000);
      // Refresh dependent state
      fetchSettings();
    } catch (e) {
      alert(`Reset failed: ${e.message}`);
    } finally {
      setResetRunning(false);
    }
  };

  // ── TAB: Settings ──────────────────────────────────────────────────────────

  const SETTING_GROUPS = [
    {
      label: 'Scraper & Network',
      keys: ['MAX_RETRIES', 'BASE_BACKOFF_SECONDS', 'THROTTLE_DELAY', 'REQUEST_TIMEOUT', 'USER_AGENT'],
    },
    {
      label: 'Performance Budgets',
      keys: ['PERF_BUDGET_MAX_CAMPAIGN_SEC', 'PERF_BUDGET_MAX_VISITS_PER_QUALIFIED', 'PERF_BUDGET_MIN_YIELD'],
    },
    {
      label: 'Extraction Quality',
      keys: ['QUALITY_MIN_EXTRACTION_RATE', 'QUALITY_MIN_EXTRACTION_SAMPLE'],
    },
    {
      label: 'Validation',
      keys: ['VALIDATION_ALLOW_TEMP_CLOSED'],
    },
    {
      label: 'Confidence Thresholds',
      keys: ['opp.confidence.high_threshold', 'opp.confidence.medium_threshold', 'opp.confidence.min_signals_high', 'opp.confidence.min_signals_medium'],
    },
    {
      label: 'Priority Thresholds',
      keys: ['opp.priority.high_threshold', 'opp.priority.medium_threshold'],
    },
    {
      label: 'Scoring Weights',
      keys: ['opp.score.no_website', 'opp.score.has_website', 'opp.score.review_high', 'opp.score.review_mid', 'opp.score.review_low', 'opp.score.rating_high', 'opp.score.rating_mid', 'opp.score.rating_low', 'opp.score.operational'],
    },
    {
      label: 'Review & Rating Thresholds',
      keys: ['opp.review.high_threshold', 'opp.review.mid_threshold', 'opp.rating.high_threshold', 'opp.rating.mid_threshold', 'opp.rating.low_threshold'],
    },
    {
      label: 'Value Multipliers',
      keys: ['opp.value.high_confidence_multiplier', 'opp.value.medium_confidence_multiplier', 'opp.value.low_confidence_multiplier'],
    },
  ];

  const renderSettings = () => {
    if (loadingSettings) return <LoadingSpinner label="Loading settings…" />;
    if (Object.keys(settingsData).length === 0) return <EmptyState icon={Settings} message="No settings loaded" sub="Settings will appear after the backend initializes." />;

    const allKnownKeys = SETTING_GROUPS.flatMap(g => g.keys);
    const otherKeys = Object.keys(settingsData).filter(k => !allKnownKeys.includes(k));

    const renderGroup = (label, keys) => {
      const available = keys.filter(k => settingsData[k]);
      if (available.length === 0) return null;
      return (
        <div key={label} className="panel">
          <h2 className="panel-title"><Settings size={15} color="var(--color-accent)" /> {label}</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {available.map(key => {
              const s = settingsData[key];
              const isDirty = editedSettings[key] !== s.value;
              const isSaving = savingKey === key;
              return (
                <div key={key} style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', gap: '0.5rem', alignItems: 'center' }}>
                  <div>
                    <div style={{ fontSize: '0.8rem', fontWeight: 500, color: 'var(--text-primary)', fontFamily: 'monospace' }}>{key}</div>
                    {s.description && <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: 1 }}>{s.description}</div>}
                  </div>
                  <input
                    type="text"
                    className="form-input"
                    style={{ width: 100, padding: '0.4rem 0.6rem', fontSize: '0.82rem', fontFamily: 'monospace', textAlign: 'right', borderColor: isDirty ? 'var(--color-accent)' : undefined }}
                    value={editedSettings[key] ?? s.value}
                    onChange={e => setEditedSettings(prev => ({ ...prev, [key]: e.target.value }))}
                  />
                  <button className="btn-secondary" style={{ fontSize: '0.75rem', padding: '0.4rem 0.65rem', opacity: isDirty ? 1 : 0.4 }}
                    disabled={!isDirty || isSaving} onClick={() => saveSetting(key)}>
                    {isSaving ? <RefreshCw size={12} style={{ animation: 'spin 1s linear infinite' }} /> : 'Save'}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      );
    };

    return (
      <div style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.25rem', maxWidth: 860 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
          <Info size={14} color="var(--text-muted)" />
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Changes apply to the next campaign. Numeric values only.</span>
        </div>
        {SETTING_GROUPS.map(({ label, keys }) => renderGroup(label, keys))}
        {otherKeys.length > 0 && renderGroup('Other', otherKeys)}

        {/* ── Danger Zone ── */}
        <div className="panel" style={{ borderColor: '#5c1a1a', background: 'rgba(92,26,26,0.12)' }}>
          <h2 className="panel-title" style={{ color: '#f87171' }}>
            <AlertTriangle size={15} color="#f87171" /> Danger Zone
          </h2>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1.5rem' }}>
            <div>
              <div style={{ fontWeight: 600, fontSize: '0.88rem', color: 'var(--text-primary)', marginBottom: '0.3rem' }}>
                Factory Reset LeadForge
              </div>
              <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', maxWidth: 520 }}>
                Permanently removes all campaigns, businesses, leads, opportunities, search history, analytics and
                exported Excel files. The database is immediately recreated using the default schema and settings.
              </div>
            </div>
            <button
              className="btn-secondary"
              style={{ flexShrink: 0, borderColor: '#f87171', color: '#f87171', whiteSpace: 'nowrap' }}
              onClick={() => { setResetDialogOpen(true); setResetConfirmText(''); }}
            >
              <AlertTriangle size={13} /> Factory Reset
            </button>
          </div>
          {resetSuccess && (
            <div style={{ marginTop: '0.75rem', fontSize: '0.8rem', color: '#4ade80', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <CheckCircle2 size={14} /> Factory reset completed. All data has been cleared and the database reinitialized.
            </div>
          )}
        </div>

        {/* ── Confirmation dialog ── */}
        {resetDialogOpen && (
          <div style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)', display: 'flex',
            alignItems: 'center', justifyContent: 'center', zIndex: 1000,
          }}>
            <div className="panel" style={{ width: 420, borderColor: '#5c1a1a', background: 'var(--bg-panel)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <h2 style={{ fontFamily: 'var(--display-font)', fontWeight: 700, fontSize: '1rem', color: '#f87171', margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <AlertTriangle size={16} color="#f87171" /> Confirm Factory Reset
                </h2>
                <button style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}
                  onClick={() => setResetDialogOpen(false)}><X size={18} /></button>
              </div>
              <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: '1.25rem', lineHeight: 1.55 }}>
                This will permanently delete all data and recreate the database. This action <strong style={{ color: 'var(--text-primary)' }}>cannot be undone</strong>.
                <br /><br />
                Type <strong style={{ color: '#f87171', fontFamily: 'monospace' }}>RESET</strong> to confirm.
              </p>
              <input
                type="text"
                className="form-input"
                placeholder="Type RESET to confirm"
                value={resetConfirmText}
                onChange={e => setResetConfirmText(e.target.value)}
                style={{ width: '100%', marginBottom: '1rem', borderColor: resetConfirmText === 'RESET' ? '#f87171' : undefined }}
                autoFocus
              />
              <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
                <button className="btn-secondary" onClick={() => setResetDialogOpen(false)} disabled={resetRunning}>
                  Cancel
                </button>
                <button
                  className="btn-secondary"
                  style={{ borderColor: '#f87171', color: '#f87171', opacity: resetConfirmText === 'RESET' ? 1 : 0.4 }}
                  disabled={resetConfirmText !== 'RESET' || resetRunning}
                  onClick={executeFactoryReset}
                >
                  {resetRunning
                    ? <><RefreshCw size={13} style={{ animation: 'spin 1s linear infinite' }} /> Resetting…</>
                    : <><AlertTriangle size={13} /> Factory Reset</>
                  }
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  };

  // ── TAB: Developer ─────────────────────────────────────────────────────────

  const renderDeveloper = () => (
    <div style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <div className="panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem' }}>
          <h2 style={{ fontFamily: 'var(--display-font)', fontWeight: 600, fontSize: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
            <TerminalIcon size={16} color="var(--color-accent)" /> Runtime Logs
          </h2>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{logs.length} lines</span>
            <button className="btn-secondary" style={{ fontSize: '0.8rem' }} onClick={fetchLogs}>
              <RefreshCw size={13} /> Refresh
            </button>
          </div>
        </div>
        <div className="console-monitor" ref={consoleRef} style={{ height: 'calc(100vh - 260px)', maxHeight: 800 }}>
          {logs.length === 0
            ? <div style={{ color: 'var(--text-muted)' }}>No logs yet. Start a campaign to generate log output.</div>
            : logs.map((log, i) => {
              let cls = 'console-line';
              if (log.includes('[ERROR]') || log.includes('Failed') || log.includes('failed')) cls += ' console-line-error';
              else if (log.includes('[WARNING]')) cls += ' console-line-warn';
              return <div key={i} className={cls}>{log}</div>;
            })
          }
        </div>
      </div>
    </div>
  );

  // ── Root render ────────────────────────────────────────────────────────────

  const tabs = [
    { id: 'campaign',        label: 'Campaign',          Icon: Play },
    { id: 'qualified-leads', label: 'Qualified Leads',   Icon: CheckCircle2 },
    { id: 'opportunities',   label: 'Opportunities',     Icon: TrendingUp },
    { id: 'businesses',      label: 'Business Registry', Icon: Building2 },
    { id: 'analytics',       label: 'Analytics',         Icon: BarChart3 },
    { id: 'settings',        label: 'Settings',          Icon: Settings },
    { id: 'developer',       label: 'Developer',         Icon: TerminalIcon },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      <header className="header">
        <div className="brand-container">
          <Database className="brand-icon" />
          <h1 className="brand-title">LeadForge</h1>
          <span className="brand-badge">V3.2</span>
        </div>
        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
          {status.is_running
            ? <span style={{ color: 'var(--color-accent)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span className="pulse-button" style={{ display: 'inline-block', width: 7, height: 7, background: 'var(--color-accent)', borderRadius: '50%' }} />
                Campaign Active
              </span>
            : <span style={{ color: 'var(--text-muted)' }}>System Idle</span>
          }
        </div>
      </header>

      <nav className="tab-bar">
        {tabs.map(({ id, label, Icon }) => (
          <button key={id} className={`tab ${activeTab === id ? 'tab-active' : ''}`}
            onClick={() => setActiveTab(id)}>
            <Icon size={14} />{label}
          </button>
        ))}
      </nav>

      <main style={{ flexGrow: 1 }}>
        {activeTab === 'campaign'        && renderCampaign()}
        {activeTab === 'qualified-leads' && renderQualifiedLeads()}
        {activeTab === 'opportunities'   && renderOpportunities()}
        {activeTab === 'businesses'      && renderBusinessRegistry()}
        {activeTab === 'analytics'       && renderAnalytics()}
        {activeTab === 'settings'        && renderSettings()}
        {activeTab === 'developer'       && renderDeveloper()}
      </main>
    </div>
  );
}
