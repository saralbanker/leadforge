import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Play, Download, Terminal as TerminalIcon, Database, CheckCircle2,
  AlertTriangle, History, FileSpreadsheet, Clock, Search, MapPin,
  Tag, Building2, TrendingUp, Star, ChevronUp, ChevronDown,
  ChevronRight, X, RefreshCw, BarChart3, Zap, Globe, Phone,
  Mail, Award, Target, Filter
} from 'lucide-react';

const API_BASE = 'http://localhost:8000/api';

// ── Helpers ────────────────────────────────────────────────────────────────────

const priorityClass = (p) => {
  const s = (p || '').toUpperCase();
  if (s === 'HIGH' || s === 'High') return 'badge-high';
  if (s === 'LOW' || s === 'Low') return 'badge-low';
  return 'badge-medium';
};

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

const formatDate = (ts) => {
  if (!ts) return '—';
  try {
    if (typeof ts === 'number') return new Date(ts * 1000).toLocaleString();
    return new Date(ts).toLocaleString();
  } catch { return ts; }
};

const formatSize = (bytes) => {
  if (!bytes) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
};

const Stars = ({ rating }) => {
  if (rating == null) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  const r = parseFloat(rating).toFixed(1);
  return (
    <span style={{ color: '#f59e0b', fontSize: '0.8rem' }}>
      <Star size={11} style={{ display: 'inline', verticalAlign: 'middle', marginRight: 2 }} />
      {r}
    </span>
  );
};

const GradeBadge = ({ grade }) => {
  if (!grade) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  return (
    <span style={{
      display: 'inline-block',
      background: `${gradeColor(grade)}22`,
      border: `1px solid ${gradeColor(grade)}55`,
      color: gradeColor(grade),
      borderRadius: 4,
      padding: '1px 6px',
      fontWeight: 700,
      fontSize: '0.75rem',
    }}>{grade}</span>
  );
};

const ScoreBadge = ({ score, priority }) => {
  const p = (priority || '').toUpperCase();
  const color = p === 'HIGH' ? 'var(--priority-high)' : p === 'LOW' ? '#6b7280' : 'var(--priority-medium)';
  const bg    = p === 'HIGH' ? 'var(--priority-high-bg)' : p === 'LOW' ? 'rgba(107,114,128,0.1)' : 'var(--priority-medium-bg)';
  const border = p === 'HIGH' ? 'var(--priority-high-border)' : p === 'LOW' ? 'rgba(107,114,128,0.2)' : 'var(--priority-medium-border)';
  return (
    <span style={{
      display: 'inline-block',
      background: bg,
      border: `1px solid ${border}`,
      color,
      borderRadius: 4,
      padding: '2px 6px',
      fontWeight: 700,
      fontSize: '0.75rem',
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
    <th
      onClick={() => onSort(col)}
      style={{ cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap' }}
    >
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


// ── App ─���──────────────────────────────────────────────────────────────────────

export default function App() {
  // Navigation
  const [activeTab, setActiveTab] = useState('discover');

  // ── Discover tab
  const [city, setCity] = useState('Ahmedabad');
  const [category, setCategory] = useState('Manufacturers');
  const [limit, setLimit] = useState(10);
  const [noWebsiteOnly, setNoWebsiteOnly] = useState(false);
  const [status, setStatus] = useState({ is_running: false, current_task: null, last_result: null, error: null });
  const [logs, setLogs] = useState([]);
  const consoleRef = useRef(null);

  // ── Leads tab
  const [history, setHistory] = useState([]);
  const [leads, setLeads] = useState([]);
  const [selectedCampaign, setSelectedCampaign] = useState('');
  const [leadsSearch, setLeadsSearch] = useState('');
  const [leadsSort, setLeadsSort] = useState({ col: 'score', dir: 'desc' });
  const [loadingLeads, setLoadingLeads] = useState(false);
  const [errorLeads, setErrorLeads] = useState(null);

  // ── Opportunities tab
  const [opps, setOpps] = useState([]);
  const [oppsSearch, setOppsSearch] = useState('');
  const [oppsPriorityFilter, setOppsPriorityFilter] = useState('');
  const [loadingOpps, setLoadingOpps] = useState(false);
  const [errorOpps, setErrorOpps] = useState(null);
  const [expandedOpp, setExpandedOpp] = useState(null);
  const [oppDetail, setOppDetail] = useState({});  // id → detail

  // ── Businesses tab
  const [businesses, setBusinesses] = useState([]);
  const [bizSearch, setBizSearch] = useState('');
  const [bizGrade, setBizGrade] = useState('');
  const [bizSort, setBizSort] = useState({ col: 'score', dir: 'desc' });
  const [loadingBiz, setLoadingBiz] = useState(false);
  const [errorBiz, setErrorBiz] = useState(null);
  const [selectedBiz, setSelectedBiz] = useState(null);
  const [bizDetail, setBizDetail] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // ── Data fetching ──────────────────────────────────────────────────────────

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/status`);
      setStatus(await res.json());
    } catch { /* ignore */ }
  }, []);

  const fetchLogs = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/logs?lines=60`);
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
      const res = await fetch(`${API_BASE}/opportunities?limit=300`);
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
      if (bizGrade) params.set('maturity_grade', bizGrade);
      const res = await fetch(`${API_BASE}/businesses?${params}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setBusinesses(await res.json());
    } catch (e) {
      setErrorBiz(e.message);
    } finally {
      setLoadingBiz(false);
    }
  }, [bizSearch, bizGrade, bizSort]);

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

  const fetchOppDetail = useCallback(async (id) => {
    if (oppDetail[id]) return;
    try {
      const res = await fetch(`${API_BASE}/opportunities/${id}`);
      if (!res.ok) return;
      const data = await res.json();
      setOppDetail(prev => ({ ...prev, [id]: data }));
    } catch { /* ignore */ }
  }, [oppDetail]);

  // ── Lifecycle ──────────────────────────────────────────────────────────────

  useEffect(() => {
    fetchHistory();
    fetchStatus();
    fetchLogs();
    const iv = setInterval(() => { fetchStatus(); fetchLogs(); }, 2000);
    return () => clearInterval(iv);
  }, [fetchHistory, fetchStatus, fetchLogs]);

  useEffect(() => {
    if (status.last_result?.file_name && selectedCampaign !== status.last_result.file_name) {
      const fn = status.last_result.file_name;
      setSelectedCampaign(fn);
      fetchLeads(fn);
      fetchHistory();
    }
  }, [status.last_result]);

  useEffect(() => {
    if (consoleRef.current) consoleRef.current.scrollTop = consoleRef.current.scrollHeight;
  }, [logs]);

  useEffect(() => {
    if (activeTab === 'opportunities') fetchOpps();
    if (activeTab === 'businesses') fetchBiz();
  }, [activeTab]);

  // ── Sorted/filtered derived lists ─────────────────────────────────────────

  const filteredLeads = leads
    .filter(l => {
      const q = leadsSearch.toLowerCase();
      return !q || [l.name, l.phone, l.website, l.area, l.category]
        .some(v => (v || '').toLowerCase().includes(q));
    })
    .sort((a, b) => {
      const { col, dir } = leadsSort;
      const va = a[col] ?? (col === 'score' ? 0 : '');
      const vb = b[col] ?? (col === 'score' ? 0 : '');
      const cmp = typeof va === 'number' ? va - vb : String(va).localeCompare(String(vb));
      return dir === 'asc' ? cmp : -cmp;
    });

  const filteredOpps = opps.filter(o => {
    const q = oppsSearch.toLowerCase();
    const matchText = !q || (o.business_name || '').toLowerCase().includes(q)
      || (o.title || '').toLowerCase().includes(q);
    const matchPriority = !oppsPriorityFilter || (o.priority || '') === oppsPriorityFilter;
    return matchText && matchPriority;
  });

  const toggleLeadsSort = (col) => {
    setLeadsSort(prev => ({ col, dir: prev.col === col && prev.dir === 'desc' ? 'asc' : 'desc' }));
  };

  const toggleBizSort = (col) => {
    setBizSort(prev => ({ col, dir: prev.col === col && prev.dir === 'desc' ? 'asc' : 'desc' }));
    fetchBiz();
  };

  const toggleOpp = (id) => {
    if (expandedOpp === id) { setExpandedOpp(null); return; }
    setExpandedOpp(id);
    fetchOppDetail(id);
  };

  const openBizDetail = (biz) => {
    setSelectedBiz(biz);
    setBizDetail(null);
    fetchBizDetail(biz.id);
  };

  // ── Scraper ────────────────────────────────────────────────────────────────

  const handleStartScrape = async (e) => {
    e.preventDefault();
    if (status.is_running) return;
    try {
      const res = await fetch(`${API_BASE}/scrape`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ city, category, limit: Number(limit), no_website_only: noWebsiteOnly }),
      });
      if (res.ok) {
        setLeads([]); setSelectedCampaign(''); fetchStatus();
      } else {
        const d = await res.json();
        alert(`Failed to start: ${d.detail}`);
      }
    } catch {
      alert('API Error: make sure the server is running on port 8000.');
    }
  };

  // ── Export helper ──────────────────────────────────────────────────────────

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


  // ── Render: Tab bar ────��───────────────────────────────────────────────────

  const tabs = [
    { id: 'discover',      label: 'Discover',      Icon: Play },
    { id: 'leads',         label: 'Leads',          Icon: FileSpreadsheet },
    { id: 'opportunities', label: 'Opportunities',  Icon: TrendingUp },
    { id: 'businesses',    label: 'Businesses',     Icon: Building2 },
  ];

  // ── Render: Discover tab ────���──────────────────────────────────────────────

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

  const renderDiscover = () => (
    <div className="dashboard-grid">
      {/* Left: form + terminal */}
      <section style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        <div className="panel">
          <h2 className="panel-title"><Play size={18} color="var(--color-accent)" /> Discovery Parameters</h2>
          <form onSubmit={handleStartScrape}>
            <div className="form-group">
              <label className="form-label">City</label>
              <input type="text" className="form-input" value={city} onChange={e => setCity(e.target.value)} disabled={status.is_running} required />
            </div>
            <div className="form-group">
              <label className="form-label">Business Category</label>
              <input
                type="text"
                className="form-input"
                list="category-list"
                value={category}
                onChange={e => setCategory(e.target.value)}
                disabled={status.is_running}
                placeholder="Type or select…"
                required
              />
              <datalist id="category-list">
                {CATEGORIES.map(c => <option key={c} value={c} />)}
              </datalist>
            </div>
            <div className="form-group">
              <label className="form-label">Target Lead Count</label>
              <input type="number" className="form-input" value={limit} onChange={e => setLimit(e.target.value)} disabled={status.is_running} min="1" max="300" required />
            </div>

            {/* No-website toggle */}
            <div className="form-group" style={{ marginBottom: '1.25rem' }}>
              <div
                onClick={() => !status.is_running && setNoWebsiteOnly(v => !v)}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '0.75rem 1rem',
                  background: noWebsiteOnly ? 'rgba(20,184,166,0.08)' : 'rgba(19,25,38,0.4)',
                  border: `1px solid ${noWebsiteOnly ? 'rgba(20,184,166,0.35)' : 'var(--border-color)'}`,
                  borderRadius: 8,
                  cursor: status.is_running ? 'not-allowed' : 'pointer',
                  transition: 'all 0.2s',
                  opacity: status.is_running ? 0.5 : 1,
                }}
              >
                <div>
                  <div style={{ fontSize: '0.875rem', fontWeight: 600, color: noWebsiteOnly ? 'var(--color-accent)' : 'var(--text-primary)' }}>
                    No-Website Leads Only
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 2 }}>
                    {noWebsiteOnly
                      ? `Will fetch up to ${limit * 3} raw, keep first ${limit} without a website`
                      : 'Include all businesses regardless of website status'}
                  </div>
                </div>
                <div style={{
                  width: 40, height: 22, borderRadius: 11, position: 'relative',
                  background: noWebsiteOnly ? 'var(--color-accent)' : 'rgba(255,255,255,0.1)',
                  border: `1px solid ${noWebsiteOnly ? 'var(--color-accent)' : 'var(--border-color)'}`,
                  transition: 'background 0.2s',
                  flexShrink: 0,
                }}>
                  <div style={{
                    position: 'absolute', top: 2, left: noWebsiteOnly ? 20 : 2,
                    width: 16, height: 16, borderRadius: '50%',
                    background: noWebsiteOnly ? '#fff' : 'var(--text-muted)',
                    transition: 'left 0.2s',
                  }} />
                </div>
              </div>
            </div>

            <button type="submit" className={`btn-primary ${status.is_running ? '' : 'pulse-button'}`} disabled={status.is_running}>
              {status.is_running ? 'Scraping…' : 'Launch LeadForge'}
            </button>
          </form>
        </div>

        <div className="panel" style={{ flexGrow: 1, display: 'flex', flexDirection: 'column' }}>
          <h2 className="panel-title"><TerminalIcon size={18} color="var(--color-accent)" /> Terminal Feed</h2>
          <div className="console-monitor" ref={consoleRef} style={{ flexGrow: 1 }}>
            {logs.length === 0
              ? <div style={{ color: 'var(--text-muted)' }}>Waiting for process run…</div>
              : logs.map((log, i) => {
                  let cls = 'console-line';
                  if (log.includes('[ERROR]') || log.includes('failed')) cls += ' console-line-error';
                  else if (log.includes('[WARNING]')) cls += ' console-line-warn';
                  return <div key={i} className={cls}>{log}</div>;
                })
            }
          </div>
          {status.is_running && (
            <div style={{ marginTop: '0.75rem', fontSize: '0.85rem', color: 'var(--color-accent)' }}>
              Current: {status.current_task}
            </div>
          )}
          {status.error && (
            <div style={{ marginTop: '0.75rem', color: '#f87171', display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.85rem' }}>
              <AlertTriangle size={16} /> {status.error}
            </div>
          )}
        </div>
      </section>

      {/* Right: metrics + last run summary */}
      <section style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        <div className="metrics-row">
          {[
            { Icon: Search,       val: status.last_result?.searched_count || 0,    label: 'Businesses Checked' },
            { Icon: Database,     val: status.last_result?.found_count    || 0,    label: 'Raw Listings' },
            { Icon: CheckCircle2, val: status.last_result?.new_count      || 0,    label: 'New Leads' },
            { Icon: Clock,        val: status.last_result?.duration_sec   ? `${status.last_result.duration_sec.toFixed(1)}s` : '0s', label: 'Time Elapsed' },
          ].map(({ Icon, val, label }) => (
            <div key={label} className="metric-card">
              <div className="metric-icon-wrapper"><Icon size={20} /></div>
              <div className="metric-info">
                <div className="metric-value">{val}</div>
                <div className="metric-label">{label}</div>
              </div>
            </div>
          ))}
        </div>

        {/* Search history */}
        <div className="panel">
          <h2 className="panel-title"><History size={18} color="var(--color-accent)" /> Search History</h2>
          <div style={{ maxHeight: '240px', overflowY: 'auto' }}>
            {history.length === 0
              ? <div style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>No past searches found.</div>
              : history.map((run, i) => (
                <div key={i} className="history-item"
                  style={{ borderColor: selectedCampaign === run.filename ? 'var(--color-accent)' : 'var(--border-color)', cursor: 'pointer' }}
                  onClick={() => { setSelectedCampaign(run.filename); fetchLeads(run.filename); setActiveTab('leads'); }}
                >
                  <div className="history-details">
                    <div className="history-name">{run.city} — {run.category}</div>
                    <div className="history-meta">
                      {run.status} • {formatSize(run.size_bytes)} • {formatDate(run.created_at)}
                    </div>
                  </div>
                  <button className="btn-secondary" style={{ padding: '0.35rem 0.65rem' }}
                    onClick={e => { e.stopPropagation(); window.open(`${API_BASE}/download/${run.filename}`); }}>
                    <Download size={14} />
                  </button>
                </div>
              ))
            }
          </div>
        </div>

        {/* Quick links to other tabs */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
          <button className="btn-secondary" style={{ padding: '1rem', flexDirection: 'column', gap: '0.35rem' }}
            onClick={() => { fetchOpps(); setActiveTab('opportunities'); }}>
            <TrendingUp size={20} color="var(--color-accent)" />
            <span>View Opportunities</span>
          </button>
          <button className="btn-secondary" style={{ padding: '1rem', flexDirection: 'column', gap: '0.35rem' }}
            onClick={() => { fetchBiz(); setActiveTab('businesses'); }}>
            <Building2 size={20} color="var(--color-accent)" />
            <span>Browse Businesses</span>
          </button>
        </div>
      </section>
    </div>
  );

  // ── Render: Leads tab ──────────────────────────────────────────────────────

  const renderLeads = () => (
    <div style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Campaign selector */}
      <div className="panel" style={{ padding: '1rem 1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '1rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
            <FileSpreadsheet size={18} color="var(--color-accent)" />
            <span style={{ fontWeight: 600 }}>{selectedCampaign || 'No campaign loaded'}</span>
            {selectedCampaign && (
              <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{leads.length} leads</span>
            )}
          </div>
          <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
            {selectedCampaign && (
              <>
                <a href={`${API_BASE}/download/${selectedCampaign}`} className="btn-secondary" style={{ textDecoration: 'none' }}>
                  <Download size={14} /> Raw Export
                </a>
                <button className="btn-secondary" onClick={() => handleExport('campaign', selectedCampaign)}>
                  <BarChart3 size={14} /> Intelligence Export
                </button>
              </>
            )}
            <button className="btn-secondary" onClick={() => handleExport('high_priority', null)}>
              <Zap size={14} /> Export High Priority
            </button>
          </div>
        </div>
      </div>

      {/* History quick-select */}
      {history.length > 0 && (
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          {history.slice(0, 8).map((run, i) => (
            <button key={i} className="btn-secondary"
              style={{ fontSize: '0.8rem', borderColor: selectedCampaign === run.filename ? 'var(--color-accent)' : 'var(--border-color)', color: selectedCampaign === run.filename ? 'var(--color-accent)' : undefined }}
              onClick={() => { setSelectedCampaign(run.filename); fetchLeads(run.filename); }}>
              {run.city} / {run.category}
            </button>
          ))}
        </div>
      )}

      {/* Leads table */}
      <div className="panel" style={{ flexGrow: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
          <div style={{ position: 'relative', flexGrow: 1, minWidth: 200 }}>
            <input type="text" className="form-input" placeholder="Filter by name, phone, website, area…"
              style={{ paddingLeft: '2.25rem' }} value={leadsSearch} onChange={e => setLeadsSearch(e.target.value)} />
            <Search size={14} style={{ position: 'absolute', left: '0.75rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
          </div>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
            {filteredLeads.length} of {leads.length}
          </span>
        </div>

        {loadingLeads && <LoadingSpinner label="Loading leads…" />}
        {!loadingLeads && errorLeads && <ErrorState message={errorLeads} onRetry={() => fetchLeads(selectedCampaign)} />}
        {!loadingLeads && !errorLeads && leads.length === 0 && (
          <EmptyState icon={Database} message="No leads loaded" sub="Select a past campaign or run a new search." />
        )}
        {!loadingLeads && !errorLeads && leads.length > 0 && (
          <div className="leads-table-container">
            <table className="leads-table">
              <thead>
                <tr>
                  <SortHeader label="Business Name" col="name"          sortState={leadsSort} onSort={toggleLeadsSort} />
                  <SortHeader label="Category"      col="category"      sortState={leadsSort} onSort={toggleLeadsSort} />
                  <SortHeader label="Area"          col="area"          sortState={leadsSort} onSort={toggleLeadsSort} />
                  <th>Phone</th>
                  <th>Website</th>
                  <SortHeader label="Rating"        col="rating"        sortState={leadsSort} onSort={toggleLeadsSort} />
                  <SortHeader label="Reviews"       col="review_count"  sortState={leadsSort} onSort={toggleLeadsSort} />
                  <SortHeader label="Maturity"      col="maturity_grade" sortState={leadsSort} onSort={toggleLeadsSort} />
                  <SortHeader label="Score"         col="score"         sortState={leadsSort} onSort={toggleLeadsSort} />
                  <th>Priority</th>
                </tr>
              </thead>
              <tbody>
                {filteredLeads.map((lead, idx) => (
                  <tr key={idx}>
                    <td style={{ fontWeight: 500 }}>{lead.name}</td>
                    <td style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>{lead.category}</td>
                    <td style={{ fontSize: '0.85rem' }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                        <MapPin size={11} style={{ color: 'var(--text-muted)' }} />{lead.area || '—'}
                      </span>
                    </td>
                    <td style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>{lead.phone || '—'}</td>
                    <td>
                      {lead.website
                        ? <a href={lead.website} target="_blank" rel="noreferrer" style={{ color: 'var(--color-accent)', textDecoration: 'none', fontSize: '0.8rem' }}>
                            <Globe size={11} style={{ marginRight: 3 }} />Visit
                          </a>
                        : <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>None</span>
                      }
                    </td>
                    <td><Stars rating={lead.rating} /></td>
                    <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{lead.review_count ?? '—'}</td>
                    <td><GradeBadge grade={lead.maturity_grade} /></td>
                    <td><ScoreBadge score={lead.score} priority={lead.priority} /></td>
                    <td>
                      <span className={`badge ${priorityClass(lead.priority)}`}>
                        <Tag size={11} />{lead.priority}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );

  // ── Render: Opportunities tab ──────────────────────────────────────────────

  const renderOpportunities = () => (
    <div style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', flexGrow: 1, minWidth: 200 }}>
          <input type="text" className="form-input" placeholder="Filter by business or service…"
            style={{ paddingLeft: '2.25rem' }} value={oppsSearch} onChange={e => setOppsSearch(e.target.value)} />
          <Search size={14} style={{ position: 'absolute', left: '0.75rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          {['', 'HIGH', 'MEDIUM', 'LOW'].map(p => (
            <button key={p} className="btn-secondary"
              style={{ fontSize: '0.8rem', borderColor: oppsPriorityFilter === p ? 'var(--color-accent)' : 'var(--border-color)', color: oppsPriorityFilter === p ? 'var(--color-accent)' : undefined }}
              onClick={() => setOppsPriorityFilter(p)}>
              {p || 'All'}
            </button>
          ))}
        </div>
        <button className="btn-secondary" onClick={fetchOpps}><RefreshCw size={14} /></button>
        <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{filteredOpps.length} of {opps.length}</span>
      </div>

      {loadingOpps && <LoadingSpinner label="Loading opportunities…" />}
      {!loadingOpps && errorOpps && <ErrorState message={errorOpps} onRetry={fetchOpps} />}
      {!loadingOpps && !errorOpps && opps.length === 0 && (
        <EmptyState icon={TrendingUp} message="No opportunities yet" sub="Run a search to generate intelligence." />
      )}

      {!loadingOpps && !errorOpps && filteredOpps.map(opp => {
        const expanded = expandedOpp === opp.id;
        const detail = oppDetail[opp.id];
        return (
          <div key={opp.id} className="panel" style={{ padding: '1rem 1.25rem', cursor: 'pointer' }}
            onClick={() => toggleOpp(opp.id)}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
              <div style={{ flexGrow: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                  <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>{opp.title}</span>
                </div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: 3 }}>
                  {opp.business_category} • {opp.pipeline_stage}
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexShrink: 0 }}>
                <ScoreBadge score={opp.score} priority={opp.priority} />
                <GradeBadge grade={opp.maturity_grade} />
                <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                  {(opp.close_probability * 100).toFixed(0)}% close
                </span>
                <span style={{ fontSize: '0.8rem', color: 'var(--color-accent)', fontWeight: 600 }}>
                  ₹{Number(opp.estimated_value).toLocaleString()}
                </span>
                {expanded ? <ChevronUp size={16} /> : <ChevronRight size={16} />}
              </div>
            </div>

            {expanded && (
              <div style={{ marginTop: '1rem', borderTop: '1px solid var(--border-color)', paddingTop: '1rem' }}
                onClick={e => e.stopPropagation()}>
                {!detail
                  ? <LoadingSpinner label="Loading signals…" />
                  : (
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '0.75rem' }}>
                      {(detail.signals || []).map((sig, i) => (
                        <div key={i} style={{
                          background: sig.score_delta > 0 ? 'rgba(16,185,129,0.06)' : 'rgba(239,68,68,0.06)',
                          border: `1px solid ${sig.score_delta > 0 ? 'rgba(16,185,129,0.2)' : 'rgba(239,68,68,0.2)'}`,
                          borderRadius: 6, padding: '0.6rem 0.75rem',
                        }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                            <span style={{ fontWeight: 600, fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{sig.rule_name}</span>
                            <span style={{ fontWeight: 700, fontSize: '0.8rem', color: sig.score_delta > 0 ? '#10b981' : '#ef4444' }}>
                              {sig.score_delta > 0 ? '+' : ''}{sig.score_delta.toFixed(1)}
                            </span>
                          </div>
                          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', lineHeight: 1.4 }}>{sig.reason}</div>
                        </div>
                      ))}
                      {(!detail.signals || detail.signals.length === 0) && (
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>No signals recorded.</div>
                      )}
                    </div>
                  )
                }
              </div>
            )}
          </div>
        );
      })}
    </div>
  );

  // ── Render: Businesses tab ────���────────────────────────────────────────────

  const renderBusinesses = () => (
    <div style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.5rem', position: 'relative' }}>
      {/* Toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', flexGrow: 1, minWidth: 200 }}>
          <input type="text" className="form-input" placeholder="Search businesses…"
            style={{ paddingLeft: '2.25rem' }} value={bizSearch}
            onChange={e => { setBizSearch(e.target.value); }}
            onKeyDown={e => { if (e.key === 'Enter') fetchBiz(); }} />
          <Search size={14} style={{ position: 'absolute', left: '0.75rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          {['', 'A', 'B', 'C', 'D', 'F'].map(g => (
            <button key={g} className="btn-secondary"
              style={{ fontSize: '0.8rem', minWidth: 32, borderColor: bizGrade === g ? (g ? gradeColor(g) : 'var(--color-accent)') : 'var(--border-color)', color: bizGrade === g ? (g ? gradeColor(g) : 'var(--color-accent)') : undefined }}
              onClick={() => { setBizGrade(g); }}>
              {g || 'All'}
            </button>
          ))}
        </div>
        <button className="btn-secondary" onClick={fetchBiz}><RefreshCw size={14} /></button>
        <button className="btn-secondary" onClick={() => handleExport('all', null)}>
          <Download size={14} /> Export All
        </button>
        <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{businesses.length} businesses</span>
      </div>

      {loadingBiz && <LoadingSpinner label="Loading businesses…" />}
      {!loadingBiz && errorBiz && <ErrorState message={errorBiz} onRetry={fetchBiz} />}
      {!loadingBiz && !errorBiz && businesses.length === 0 && (
        <EmptyState icon={Building2} message="No businesses found" sub="Run a search to discover businesses." />
      )}

      {!loadingBiz && !errorBiz && businesses.length > 0 && (
        <div className="panel">
          <div className="leads-table-container">
            <table className="leads-table">
              <thead>
                <tr>
                  <SortHeader label="Business" col="name"          sortState={bizSort} onSort={toggleBizSort} />
                  <th>Category</th>
                  <th>Area</th>
                  <th>Phone</th>
                  <SortHeader label="Rating"   col="rating"        sortState={bizSort} onSort={toggleBizSort} />
                  <SortHeader label="Reviews"  col="review_count"  sortState={bizSort} onSort={toggleBizSort} />
                  <SortHeader label="Maturity" col="maturity_score" sortState={bizSort} onSort={toggleBizSort} />
                  <SortHeader label="Score"    col="score"         sortState={bizSort} onSort={toggleBizSort} />
                  <th>Top Opportunity</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {businesses.map((biz, idx) => (
                  <tr key={idx} style={{ cursor: 'pointer' }} onClick={() => openBizDetail(biz)}>
                    <td style={{ fontWeight: 500 }}>{biz.name}</td>
                    <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{biz.category}</td>
                    <td style={{ fontSize: '0.8rem' }}>{biz.area || '—'}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: '0.78rem' }}>{biz.phone || '—'}</td>
                    <td><Stars rating={biz.rating} /></td>
                    <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{biz.review_count ?? '—'}</td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                        <GradeBadge grade={biz.maturity_grade} />
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{biz.maturity_score}</span>
                      </div>
                    </td>
                    <td><ScoreBadge score={biz.top_score} priority={biz.priority} /></td>
                    <td style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {biz.top_opportunity ? biz.top_opportunity.split(' — ')[0] : '—'}
                    </td>
                    <td><ChevronRight size={14} style={{ color: 'var(--text-muted)' }} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Business Detail Drawer */}
      {selectedBiz && (
        <div className="detail-drawer">
          <div className="detail-drawer-overlay" onClick={() => setSelectedBiz(null)} />
          <div className="detail-drawer-panel">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.5rem' }}>
              <div>
                <h2 style={{ fontFamily: 'var(--display-font)', fontWeight: 700, fontSize: '1.2rem' }}>{selectedBiz.name}</h2>
                <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginTop: 2 }}>{selectedBiz.category} • {selectedBiz.area}</div>
              </div>
              <button className="btn-secondary" style={{ padding: '0.4rem' }} onClick={() => setSelectedBiz(null)}><X size={16} /></button>
            </div>

            {loadingDetail && <LoadingSpinner label="Loading detail…" />}
            {!loadingDetail && !bizDetail && <div style={{ color: 'var(--text-muted)' }}>Could not load detail.</div>}
            {!loadingDetail && bizDetail && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', overflowY: 'auto', maxHeight: 'calc(100vh - 180px)', paddingRight: 4 }}>
                {/* Contact */}
                <div>
                  <div className="detail-section-title">Contact</div>
                  <div className="detail-row"><Phone size={13} />{bizDetail.phone || '—'}</div>
                  {bizDetail.contact_email && <div className="detail-row"><Mail size={13} />{bizDetail.contact_email}</div>}
                  {bizDetail.website && <div className="detail-row"><Globe size={13} /><a href={bizDetail.website} target="_blank" rel="noreferrer" style={{ color: 'var(--color-accent)' }}>{bizDetail.website}</a></div>}
                  {bizDetail.address && <div className="detail-row"><MapPin size={13} />{bizDetail.address}{bizDetail.city ? `, ${bizDetail.city}` : ''}</div>}
                  <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.5rem', flexWrap: 'wrap' }}>
                    <Stars rating={bizDetail.rating} />
                    {bizDetail.review_count != null && <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{bizDetail.review_count} reviews</span>}
                    {bizDetail.business_status && <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', background: 'rgba(255,255,255,0.05)', borderRadius: 4, padding: '1px 6px' }}>{bizDetail.business_status}</span>}
                  </div>
                </div>

                {/* Digital Maturity */}
                {bizDetail.maturity && (
                  <div>
                    <div className="detail-section-title">Digital Maturity</div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.75rem' }}>
                      <GradeBadge grade={bizDetail.maturity.grade} />
                      <div style={{ flexGrow: 1, background: 'var(--border-color)', borderRadius: 4, height: 6, overflow: 'hidden' }}>
                        <div style={{ width: `${bizDetail.maturity.score}%`, height: '100%', background: gradeColor(bizDetail.maturity.grade), borderRadius: 4 }} />
                      </div>
                      <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>{(bizDetail.maturity.score || 0).toFixed(0)}/100</span>
                    </div>
                    {bizDetail.maturity.dimensions?.map((dim, i) => (
                      <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.35rem 0', borderBottom: '1px solid var(--border-color)', fontSize: '0.8rem' }}>
                        <span style={{ color: dim.gap ? '#f97316' : '#10b981' }}>
                          {dim.gap ? '✗' : '✓'} {dim.name}
                        </span>
                        <span style={{ color: 'var(--text-muted)' }}>{dim.score?.toFixed(0)}/{dim.max_score?.toFixed(0)}</span>
                      </div>
                    ))}
                    {bizDetail.maturity.gaps?.length > 0 && (
                      <div style={{ marginTop: '0.5rem' }}>
                        <div style={{ fontSize: '0.75rem', color: '#f97316', fontWeight: 600, marginBottom: 2 }}>Gaps:</div>
                        {bizDetail.maturity.gaps.map((g, i) => <div key={i} style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', paddingLeft: 8 }}>• {g}</div>)}
                      </div>
                    )}
                  </div>
                )}

                {/* Opportunities */}
                {bizDetail.opportunities?.length > 0 && (
                  <div>
                    <div className="detail-section-title">Opportunities ({bizDetail.opportunities.length})</div>
                    {bizDetail.opportunities.map((opp, i) => (
                      <div key={i} style={{ background: 'rgba(19,25,38,0.4)', border: '1px solid var(--border-color)', borderRadius: 8, padding: '0.75rem', marginBottom: '0.75rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                          <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>{opp.title?.split(' — ')[0]}</span>
                          <ScoreBadge score={opp.score} priority={opp.score >= 60 ? 'HIGH' : opp.score >= 28 ? 'MEDIUM' : 'LOW'} />
                        </div>
                        <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', display: 'flex', gap: '1rem' }}>
                          <span>{(opp.close_probability * 100).toFixed(0)}% close prob.</span>
                          <span>₹{Number(opp.estimated_value).toLocaleString()} est.</span>
                        </div>
                        {opp.signals?.length > 0 && (
                          <div style={{ marginTop: '0.5rem', display: 'flex', flexDirection: 'column', gap: 3 }}>
                            {opp.signals.slice(0, 5).map((sig, j) => (
                              <div key={j} style={{ fontSize: '0.75rem', display: 'flex', justifyContent: 'space-between' }}>
                                <span style={{ color: 'var(--text-secondary)' }}>{sig.rule_name}</span>
                                <span style={{ color: sig.score_delta > 0 ? '#10b981' : '#ef4444', fontWeight: 600 }}>
                                  {sig.score_delta > 0 ? '+' : ''}{sig.score_delta.toFixed(1)}
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', paddingTop: '0.5rem', borderTop: '1px solid var(--border-color)' }}>
                  First seen: {formatDate(bizDetail.first_discovered_at)} &nbsp;·&nbsp; Last scraped: {formatDate(bizDetail.last_scraped_at)}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );

  // ── Root render ────────────────────────────────────────────────────────────

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      <header className="header">
        <div className="brand-container">
          <Database className="brand-icon" />
          <h1 className="brand-title">LeadForge</h1>
          <span className="brand-badge">MVP V1.0</span>
        </div>
        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
          {status.is_running
            ? <span style={{ color: 'var(--color-accent)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span className="pulse-button" style={{ display: 'inline-block', width: 8, height: 8, background: 'var(--color-accent)', borderRadius: '50%' }} />
                Scraper Active
              </span>
            : <span style={{ color: 'var(--text-muted)' }}>System Idle</span>
          }
        </div>
      </header>

      <nav className="tab-bar">
        {tabs.map(({ id, label, Icon }) => (
          <button key={id} className={`tab ${activeTab === id ? 'tab-active' : ''}`}
            onClick={() => setActiveTab(id)}>
            <Icon size={15} />{label}
          </button>
        ))}
      </nav>

      <main style={{ flexGrow: 1 }}>
        {activeTab === 'discover'      && renderDiscover()}
        {activeTab === 'leads'         && renderLeads()}
        {activeTab === 'opportunities' && renderOpportunities()}
        {activeTab === 'businesses'    && renderBusinesses()}
      </main>
    </div>
  );
}
