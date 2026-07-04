import React, { useState, useEffect, useRef } from 'react';
import { 
  Play, 
  Download, 
  Terminal as TerminalIcon, 
  Database, 
  CheckCircle2, 
  AlertTriangle,
  History,
  FileSpreadsheet,
  Clock,
  Search,
  MapPin,
  Tag
} from 'lucide-react';

const API_BASE = 'http://localhost:8000/api';

export default function App() {
  // Scraper inputs
  const [city, setCity] = useState('Ahmedabad');
  const [category, setCategory] = useState('Manufacturers');
  const [limit, setLimit] = useState(10);
  
  // App state
  const [status, setStatus] = useState({
    is_running: false,
    current_task: null,
    last_result: null,
    error: null
  });
  const [logs, setLogs] = useState([]);
  const [history, setHistory] = useState([]);
  const [leads, setLeads] = useState([]);
  const [selectedFile, setSelectedFile] = useState('');
  const [tableSearch, setTableSearch] = useState('');
  
  const consoleRef = useRef(null);

  // Poll status and logs when scraper is running
  useEffect(() => {
    fetchHistory();
    fetchStatus();
    fetchLogs();
    
    const interval = setInterval(() => {
      fetchStatus();
      fetchLogs();
    }, 2000);
    
    return () => clearInterval(interval);
  }, []);

  // Update leads when a run completes
  useEffect(() => {
    if (status.last_result && status.last_result.file_name) {
      if (selectedFile !== status.last_result.file_name) {
        setSelectedFile(status.last_result.file_name);
        fetchLeads(status.last_result.file_name);
        fetchHistory();
      }
    }
  }, [status.last_result]);

  // Scroll terminal logs to bottom
  useEffect(() => {
    if (consoleRef.current) {
      consoleRef.current.scrollTop = consoleRef.current.scrollHeight;
    }
  }, [logs]);

  const fetchStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/status`);
      const data = await res.json();
      setStatus(data);
    } catch (err) {
      console.error('Error fetching status:', err);
    }
  };

  const fetchLogs = async () => {
    try {
      const res = await fetch(`${API_BASE}/logs?lines=50`);
      const data = await res.json();
      if (data.logs) {
        setLogs(data.logs);
      }
    } catch (err) {
      console.error('Error fetching logs:', err);
    }
  };

  const fetchHistory = async () => {
    try {
      const res = await fetch(`${API_BASE}/history`);
      const data = await res.json();
      setHistory(data);
    } catch (err) {
      console.error('Error fetching history:', err);
    }
  };

  const fetchLeads = async (filename) => {
    try {
      const res = await fetch(`${API_BASE}/leads/${filename}`);
      if (res.ok) {
        const data = await res.json();
        setLeads(data);
      } else {
        setLeads([]);
      }
    } catch (err) {
      console.error('Error fetching leads:', err);
      setLeads([]);
    }
  };

  const handleStartScrape = async (e) => {
    e.preventDefault();
    if (status.is_running) return;

    try {
      const res = await fetch(`${API_BASE}/scrape`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ city, category, limit: Number(limit) })
      });
      if (res.ok) {
        setLeads([]);
        setSelectedFile('');
        fetchStatus();
      } else {
        const data = await res.json();
        alert(`Failed to start: ${data.detail}`);
      }
    } catch (err) {
      alert(`API Error: Make sure your local server is running on port 8000.`);
    }
  };

  const loadHistoryFile = (filename) => {
    setSelectedFile(filename);
    fetchLeads(filename);
  };

  const formatSize = (bytes) => {
    if (!bytes) return '0 B';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  };

  const formatDate = (timestamp) => {
    return new Date(timestamp * 1000).toLocaleString();
  };

  // Filter leads based on user query
  const filteredLeads = leads.filter(lead => {
    const query = tableSearch.toLowerCase();
    return (
      lead.name?.toLowerCase().includes(query) ||
      lead.phone?.toLowerCase().includes(query) ||
      lead.website?.toLowerCase().includes(query) ||
      lead.area?.toLowerCase().includes(query)
    );
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      {/* Header */}
      <header className="header">
        <div className="brand-container">
          <Database className="brand-icon" />
          <h1 className="brand-title">LeadForge</h1>
          <span className="brand-badge">MVP V1.0</span>
        </div>
        <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
          {status.is_running ? (
            <span style={{ color: 'var(--color-accent)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span className="pulse-button" style={{ display: 'inline-block', width: '8px', height: '8px', background: 'var(--color-accent)', borderRadius: '50%' }}></span>
              Scraper Active
            </span>
          ) : (
            <span style={{ color: 'var(--text-muted)' }}>System Idle</span>
          )}
        </div>
      </header>

      {/* Main Dashboard Grid */}
      <main className="dashboard-grid">
        {/* Left column: Setup & Logs */}
        <section style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          {/* Controls Panel */}
          <div className="panel">
            <h2 className="panel-title">
              <Play size={18} color="var(--color-accent)" />
              Discovery Parameters
            </h2>
            <form onSubmit={handleStartScrape}>
              <div className="form-group">
                <label className="form-label">City</label>
                <input 
                  type="text" 
                  className="form-input" 
                  value={city} 
                  onChange={(e) => setCity(e.target.value)} 
                  disabled={status.is_running}
                  required
                />
              </div>
              <div className="form-group">
                <label className="form-label">Business Category</label>
                <input 
                  type="text" 
                  className="form-input" 
                  value={category} 
                  onChange={(e) => setCategory(e.target.value)} 
                  disabled={status.is_running}
                  required
                />
              </div>
              <div className="form-group">
                <label className="form-label">Target Lead Count</label>
                <input 
                  type="number" 
                  className="form-input" 
                  value={limit} 
                  onChange={(e) => setLimit(e.target.value)} 
                  disabled={status.is_running}
                  min="1"
                  max="300"
                  required
                />
              </div>
              <button 
                type="submit" 
                className={`btn-primary ${status.is_running ? '' : 'pulse-button'}`}
                disabled={status.is_running}
              >
                {status.is_running ? 'Scraping...' : 'Launch LeadForge'}
              </button>
            </form>
          </div>

          {/* Real-time Terminal Log */}
          <div className="panel" style={{ flexGrow: 1, display: 'flex', flexDirection: 'column' }}>
            <h2 className="panel-title">
              <TerminalIcon size={18} color="var(--color-accent)" />
              Terminal Feed
            </h2>
            <div className="console-monitor" ref={consoleRef} style={{ flexGrow: 1 }}>
              {logs.length === 0 ? (
                <div style={{ color: 'var(--text-muted)' }}>Waiting for process run...</div>
              ) : (
                logs.map((log, index) => {
                  let logClass = "console-line";
                  if (log.includes("[ERROR]") || log.includes("failed")) {
                    logClass += " console-line-error";
                  } else if (log.includes("[WARNING]")) {
                    logClass += " console-line-warn";
                  }
                  return (
                    <div key={index} className={logClass}>
                      {log}
                    </div>
                  );
                })
              )}
            </div>
            {status.is_running && (
              <div style={{ marginTop: '0.75rem', fontSize: '0.85rem', color: 'var(--color-accent)' }}>
                Current: {status.current_task}
              </div>
            )}
            {status.error && (
              <div style={{ marginTop: '0.75rem', color: '#f87171', display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.85rem' }}>
                <AlertTriangle size={16} />
                Failed: {status.error}
              </div>
            )}
          </div>
        </section>

        {/* Right column: Results & Export history */}
        <section style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          {/* Metrics section */}
          <div className="metrics-row">
            <div className="metric-card">
              <div className="metric-icon-wrapper">
                <Search size={20} />
              </div>
              <div className="metric-info">
                <div className="metric-value">{status.last_result?.searched_count || 0}</div>
                <div className="metric-label">Businesses Checked</div>
              </div>
            </div>
            <div className="metric-card">
              <div className="metric-icon-wrapper">
                <Database size={20} />
              </div>
              <div className="metric-info">
                <div className="metric-value">{status.last_result?.found_count || 0}</div>
                <div className="metric-label">Raw Listings</div>
              </div>
            </div>
            <div className="metric-card">
              <div className="metric-icon-wrapper">
                <CheckCircle2 size={20} />
              </div>
              <div className="metric-info">
                <div className="metric-value">{status.last_result?.exported_count || leads.length}</div>
                <div className="metric-label">Qualified Leads</div>
              </div>
            </div>
            <div className="metric-card">
              <div className="metric-icon-wrapper">
                <Clock size={20} />
              </div>
              <div className="metric-info">
                <div className="metric-value">
                  {status.last_result?.duration_sec ? `${status.last_result.duration_sec.toFixed(1)}s` : '0s'}
                </div>
                <div className="metric-label">Time Elapsed</div>
              </div>
            </div>
          </div>

          {/* Main Leads Table */}
          <div className="panel" style={{ display: 'flex', flexDirection: 'column', flexGrow: 1 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem', marginBottom: '1rem', flexWrap: 'wrap', gap: '1rem' }}>
              <h2 style={{ fontSize: '1.15rem', display: 'flex', alignItems: 'center', gap: '0.5rem', fontFamily: "'Space Grotesk', sans-serif", fontWeight: 600 }}>
                <FileSpreadsheet size={18} color="var(--color-accent)" />
                {selectedFile ? `Leads: ${selectedFile}` : 'Leads Database'}
              </h2>
              {selectedFile && (
                <a 
                  href={`${API_BASE}/download/${selectedFile}`}
                  className="btn-secondary"
                  style={{ textDecoration: 'none' }}
                >
                  <Download size={15} />
                  Download Excel
                </a>
              )}
            </div>

            {/* Filter controls */}
            {leads.length > 0 && (
              <div style={{ position: 'relative', marginBottom: '1rem' }}>
                <input
                  type="text"
                  placeholder="Filter leads by name, phone, website or area..."
                  className="form-input"
                  style={{ paddingLeft: '2.5rem' }}
                  value={tableSearch}
                  onChange={(e) => setTableSearch(e.target.value)}
                />
                <Search size={16} style={{ position: 'absolute', left: '1rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              </div>
            )}

            {/* Leads list */}
            {leads.length === 0 ? (
              <div style={{ flexGrow: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '300px', flexDirection: 'column', gap: '0.75rem', color: 'var(--text-muted)' }}>
                <Database size={48} style={{ opacity: 0.3 }} />
                <div>No leads loaded. Select a past file or run a search.</div>
              </div>
            ) : (
              <div className="leads-table-container">
                <table className="leads-table">
                  <thead>
                    <tr>
                      <th>Business Name</th>
                      <th>Category</th>
                      <th>Phone</th>
                      <th>Website</th>
                      <th>Area</th>
                      <th>Priority</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredLeads.map((lead, idx) => (
                      <tr key={idx}>
                        <td style={{ fontWeight: 500, color: 'var(--text-primary)' }}>{lead.name}</td>
                        <td style={{ color: 'var(--text-secondary)' }}>{lead.category}</td>
                        <td style={{ fontFamily: 'monospace', fontSize: '0.85rem' }}>{lead.phone || 'N/A'}</td>
                        <td>
                          {lead.website ? (
                            <a href={lead.website} target="_blank" rel="noreferrer" style={{ color: 'var(--color-accent)', textDecoration: 'none' }}>
                              Visit Link
                            </a>
                          ) : (
                            <span style={{ color: 'var(--text-muted)' }}>None</span>
                          )}
                        </td>
                        <td style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', borderBottom: 'none' }}>
                          <MapPin size={13} style={{ color: 'var(--text-muted)' }} />
                          {lead.area || 'Unknown'}
                        </td>
                        <td>
                          <span className={`badge ${lead.priority === 'High' ? 'badge-high' : 'badge-medium'}`}>
                            <Tag size={12} />
                            {lead.priority}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Past exports panel */}
          <div className="panel">
            <h2 className="panel-title">
              <History size={18} color="var(--color-accent)" />
              Export Directory History
            </h2>
            <div style={{ maxHeight: '180px', overflowY: 'auto' }}>
              {history.length === 0 ? (
                <div style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>No past export files found in the output directory.</div>
              ) : (
                history.map((file, idx) => (
                  <div 
                    key={idx} 
                    className="history-item"
                    style={{ 
                      borderColor: selectedFile === file.filename ? 'var(--color-accent)' : 'var(--border-color)',
                      cursor: 'pointer'
                    }}
                    onClick={() => loadHistoryFile(file.filename)}
                  >
                    <div className="history-details">
                      <div className="history-name">{file.filename}</div>
                      <div className="history-meta">
                        {formatSize(file.size_bytes)} • {formatDate(file.created_at)}
                      </div>
                    </div>
                    <button 
                      onClick={(e) => {
                        e.stopPropagation();
                        window.open(`${API_BASE}/download/${file.filename}`);
                      }}
                      className="btn-secondary"
                      style={{ padding: '0.35rem 0.65rem' }}
                    >
                      <Download size={14} />
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
