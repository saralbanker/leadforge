import React, { useState, useEffect } from 'react';
import {
  Cpu, Sparkles, RefreshCw, CheckCircle2, AlertTriangle, Play,
  RotateCcw, Sliders, Check, Copy, Info, Terminal as TerminalIcon,
  ShieldCheck, Globe, Zap, Layers, ArrowRight,
} from 'lucide-react';

const DEFAULT_SYSTEM_PROMPT = `You are writing the OPENING LINE of a cold email to a busy small business owner. They will read this on their phone in about 3 seconds between tasks. If it does not grab them instantly, they delete it.

Rules:
1. Write ONE sentence, maximum 15 words.
2. Use simple, everyday words. Never use exclamation marks or em-dashes.
3. Banned phrases, never use these or anything similar: "online presence", "digital footprint", "digital age", "solutions", "leverage", "optimize", "streamline", or any of:
{banned_vocabulary}
4. Stay strictly EVIDENCE-BOUND. Only state facts directly provided in the input: business name, city, category, Google rating, review count, or verified website details. If the input does not establish how they take orders or bookings, or if Operational Premise is UNCONFIRMED, you MUST NOT invent or assume their workflow. Instead, make a true observation from the verified data or ask a question rather than asserting.
5. Do not greet them. Do not introduce yourself. Do not pitch anything, and never mention a website, portal, app, or any product by name. Just the one observation sentence.
6. Write like a real person quickly typing an email, not a marketing department.

Good examples (evidence-bound, simple, no invented claims):
- Business "ATX Family Dental" in "Austin", Category: Dentist, Rating: 4.9, Reviews: 128, Premise: UNCONFIRMED -> {"observation_hook": "I saw ATX Family Dental has 128 reviews with a 4.9 rating in Austin."}
- Business "Sydney Roof Masters" in "Sydney", Category: Roofing Contractor, Has Website: No -> {"observation_hook": "Sydney Roof Masters does not have a website listed for customers in Sydney."}
- Business "Apex Law Group" in "Denver", Category: Law Firm, Website snippet mentions commercial litigation -> {"observation_hook": "I noticed Apex Law Group handles commercial litigation for businesses in Denver."}
- Business "Oak & Iron Fabrication" in "Chicago", Category: Metal Fabrication, Premise: UNCONFIRMED -> {"observation_hook": "Do new fabrication inquiries for Oak & Iron mostly come through phone calls?"}

Bad examples (invented claims or jargon, do NOT write like this):
- "ATX Family Dental's phone-based scheduling means new patients get lost in calls." (INVENTED - scheduling method was never verified)
- "Sydney Roof Masters currently lacks an online presence." (JARGON - violates banned vocabulary)

Output strictly raw JSON: {"observation_hook": "your one sentence here"}`;

const DEFAULT_USER_PROMPT_TEMPLATE = `Business Name: {business_name}
Category: {category}
City: {city}
Area: {area}
Has Website: {has_website}
Website Domain / Scraped Snippet: {scraped_text}
Google Rating: {rating}
Google Review Count: {review_count}
Operational Premise: {operational_premise}

Output the single observation hook in raw JSON.`;

const PROMPT_VARIABLES = [
  { key: '{business_name}', label: 'Business Name', desc: 'e.g. ATX Family Dental' },
  { key: '{category}', label: 'Category', desc: 'e.g. Dentist' },
  { key: '{city}', label: 'City', desc: 'e.g. Austin' },
  { key: '{area}', label: 'Area', desc: 'e.g. Downtown' },
  { key: '{has_website}', label: 'Has Website', desc: 'Yes or No' },
  { key: '{scraped_text}', label: 'Scraped Text / Domain', desc: 'Extracted content or domain' },
  { key: '{rating}', label: 'Google Rating', desc: 'e.g. 4.9' },
  { key: '{review_count}', label: 'Google Reviews', desc: 'e.g. 128' },
  { key: '{operational_premise}', label: 'Operational Premise', desc: 'CONFIRMED or UNCONFIRMED' },
];

export default function LocalLMControl({
  settingsData,
  editedSettings,
  setEditedSettings,
  saveSetting,
  savingKey,
  apiBase,
}) {
  const [llmStatus, setLlmStatus] = useState(null);
  const [testingConnection, setTestingConnection] = useState(false);
  const [testPromptInput, setTestPromptInput] = useState(
    'Business Name: ATX Family Dental\nCategory: Dentist\nCity: Austin\nArea: Downtown\nHas Website: Yes\nScraped Snippet: Family and cosmetic dentistry\nGoogle Rating: 4.9\nGoogle Review Count: 128\nOperational Premise: UNCONFIRMED'
  );
  const [testOutput, setTestOutput] = useState(null);
  const [runningTest, setRunningTest] = useState(false);
  const [copiedKey, setCopiedKey] = useState(null);
  // Canonical defaults come from the backend, never from the constant below.
  // That constant drifts: it once lagged behind the migrations that added the
  // evidence-binding rules, so "Reset to Default" silently reverted the prompt
  // to a version that allowed the model to invent facts about a business.
  const [apiDefaults, setApiDefaults] = useState(null);

  // Load live LLM status on mount
  const checkLlmStatus = async () => {
    setTestingConnection(true);
    try {
      const res = await fetch(`${apiBase}/llm/status`);
      if (res.ok) {
        const data = await res.json();
        setLlmStatus(data);
      }
    } catch {
      setLlmStatus({ connection: { connected: false, error: 'Cannot connect to LeadForge backend' } });
    } finally {
      setTestingConnection(false);
    }
  };

  const loadDefaults = async () => {
    try {
      const res = await fetch(`${apiBase}/settings/defaults`);
      if (res.ok) setApiDefaults(await res.json());
    } catch {
      setApiDefaults(null); // fall back to the bundled constant
    }
  };

  useEffect(() => {
    checkLlmStatus();
    loadDefaults();
  }, [apiBase]);

  const canonicalSystemPrompt = () =>
    apiDefaults?.['llm.system_prompt'] || DEFAULT_SYSTEM_PROMPT;

  // Execute interactive test inference
  const handleRunTest = async () => {
    setRunningTest(true);
    setTestOutput(null);
    try {
      const res = await fetch(`${apiBase}/llm/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          api_url: editedSettings['llm.api_url'] || settingsData['llm.api_url']?.value || 'http://localhost:11434',
          model_name: editedSettings['llm.model_name'] || settingsData['llm.model_name']?.value || 'llama3.1:8b',
          system_prompt: editedSettings['llm.system_prompt'] || settingsData['llm.system_prompt']?.value || canonicalSystemPrompt(),
          prompt: testPromptInput,
          temperature: parseFloat(editedSettings['llm.temperature'] ?? settingsData['llm.temperature']?.value ?? '0.2'),
          max_tokens: parseInt(editedSettings['llm.max_tokens'] ?? settingsData['llm.max_tokens']?.value ?? '150', 10),
        }),
      });
      const data = await res.json();
      setTestOutput(data);
    } catch (err) {
      setTestOutput({ success: false, error: String(err) });
    } finally {
      setRunningTest(false);
    }
  };

  const handleCopy = (text, key) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  const insertVariable = (variableKey) => {
    const current = editedSettings['llm.user_prompt_template'] ?? settingsData['llm.user_prompt_template']?.value ?? DEFAULT_USER_PROMPT_TEMPLATE;
    setEditedSettings(prev => ({
      ...prev,
      ['llm.user_prompt_template']: current + `\n${variableKey}`,
    }));
  };

  const isLlmConnected = llmStatus?.connection?.connected;
  const isEnabled = (editedSettings['llm.enabled'] ?? settingsData['llm.enabled']?.value ?? 'true').toLowerCase() === 'true';

  return (
    <div className="panel" style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', borderColor: 'var(--color-accent)' }}>
      {/* ── Header ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div style={{
            background: 'var(--color-accent-glow)',
            color: 'var(--color-accent)',
            padding: '0.6rem',
            borderRadius: '8px',
            border: '1px solid rgba(20, 184, 166, 0.3)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}>
            <Cpu size={22} />
          </div>
          <div>
            <h2 className="panel-title" style={{ margin: 0, fontSize: '1.1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              Local LM Control (Ollama / Local AI)
              <Sparkles size={16} color="var(--color-accent)" />
            </h2>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
              Full access to local model parameters, system prompts, dynamic templates, and real-time generation testing.
            </div>
          </div>
        </div>

        {/* ── Status & Connection Test ── */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div style={{
            padding: '0.35rem 0.75rem',
            borderRadius: '20px',
            fontSize: '0.75rem',
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            gap: '0.4rem',
            background: isLlmConnected ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
            color: isLlmConnected ? '#10b981' : '#f87171',
            border: `1px solid ${isLlmConnected ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
          }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: isLlmConnected ? '#10b981' : '#f87171', display: 'inline-block' }} />
            {isLlmConnected ? `Ollama Online (${llmStatus.connection.latency_ms}ms)` : 'Ollama Offline'}
          </div>

          <button
            className="btn-secondary"
            style={{ fontSize: '0.75rem', padding: '0.4rem 0.75rem', display: 'flex', alignItems: 'center', gap: '0.35rem' }}
            disabled={testingConnection}
            onClick={checkLlmStatus}
          >
            <RefreshCw size={12} style={{ animation: testingConnection ? 'spin 1s linear infinite' : 'none' }} />
            {testingConnection ? 'Checking…' : 'Check Status'}
          </button>
        </div>
      </div>

      {/* ── Pipeline Architecture Confirmation Banner ── */}
      <div style={{
        background: 'linear-gradient(135deg, rgba(20, 184, 166, 0.08), rgba(26, 34, 52, 0.4))',
        border: '1px solid rgba(20, 184, 166, 0.2)',
        borderRadius: '8px',
        padding: '0.9rem 1.1rem',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.4rem' }}>
          <Zap size={15} color="var(--color-accent)" />
          <span style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--text-primary)' }}>
            Pipeline Confirmation: How Gathered Data Feeds the Local LM
          </span>
        </div>
        <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', lineHeight: 1.5, margin: 0 }}>
          <strong>Yes, absolutely:</strong> Once the scraper gathers business data (name, category, city, GIDC/MIDC industrial area, contact email, website presence/scraped snippets), it immediately interpolates those variables into your <strong>User Prompt Template</strong> and invokes the <strong>Local Model (Ollama)</strong> using your custom <strong>System Prompt</strong> below. The model generates a hyper-targeted observation hook, which is then assembled into a personalized B2B outreach email draft ready for approval and sending!
        </p>
      </div>

      {/* ── Core Configuration Grid ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>
        {/* Toggle Enable */}
        <div style={{ background: 'rgba(0,0,0,0.2)', padding: '0.85rem', borderRadius: '6px', border: '1px solid var(--border-color)' }}>
          <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '0.4rem' }}>
            Local LM Inference
          </label>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: '0.82rem', color: isEnabled ? '#10b981' : 'var(--text-muted)', fontWeight: 500 }}>
              {isEnabled ? 'Enabled (Active)' : 'Disabled (Fallback mode)'}
            </span>
            <button
              className="btn-secondary"
              style={{
                fontSize: '0.72rem',
                padding: '0.25rem 0.6rem',
                background: isEnabled ? 'rgba(16, 185, 129, 0.2)' : 'rgba(255,255,255,0.05)',
                color: isEnabled ? '#10b981' : 'var(--text-muted)',
              }}
              onClick={() => {
                const nextVal = isEnabled ? 'false' : 'true';
                setEditedSettings(prev => ({ ...prev, ['llm.enabled']: nextVal }));
                saveSetting('llm.enabled', nextVal);
              }}
            >
              Toggle
            </button>
          </div>
        </div>

        {/* Endpoint URL */}
        <div style={{ background: 'rgba(0,0,0,0.2)', padding: '0.85rem', borderRadius: '6px', border: '1px solid var(--border-color)' }}>
          <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '0.4rem' }}>
            Ollama Endpoint URL
          </label>
          <div style={{ display: 'flex', gap: '0.4rem' }}>
            <input
              type="text"
              className="form-input"
              style={{ width: '100%', padding: '0.4rem 0.6rem', fontSize: '0.8rem', fontFamily: 'monospace' }}
              value={editedSettings['llm.api_url'] ?? settingsData['llm.api_url']?.value ?? 'http://localhost:11434'}
              onChange={e => setEditedSettings(prev => ({ ...prev, ['llm.api_url']: e.target.value }))}
            />
            {editedSettings['llm.api_url'] && editedSettings['llm.api_url'] !== settingsData['llm.api_url']?.value && (
              <button className="btn-primary" style={{ fontSize: '0.72rem', padding: '0.35rem 0.6rem' }} onClick={() => saveSetting('llm.api_url')}>
                Save
              </button>
            )}
          </div>
        </div>

        {/* Model Selection */}
        <div style={{ background: 'rgba(0,0,0,0.2)', padding: '0.85rem', borderRadius: '6px', border: '1px solid var(--border-color)' }}>
          <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '0.4rem' }}>
            Model Tag / Name
          </label>
          <div style={{ display: 'flex', gap: '0.4rem' }}>
            <input
              type="text"
              className="form-input"
              placeholder="e.g. llama3.1:8b, mistral, qwen2.5:3b"
              style={{ width: '100%', padding: '0.4rem 0.6rem', fontSize: '0.8rem', fontFamily: 'monospace' }}
              value={editedSettings['llm.model_name'] ?? settingsData['llm.model_name']?.value ?? 'llama3.1:8b'}
              onChange={e => setEditedSettings(prev => ({ ...prev, ['llm.model_name']: e.target.value }))}
            />
            {editedSettings['llm.model_name'] && editedSettings['llm.model_name'] !== settingsData['llm.model_name']?.value && (
              <button className="btn-primary" style={{ fontSize: '0.72rem', padding: '0.35rem 0.6rem' }} onClick={() => saveSetting('llm.model_name')}>
                Save
              </button>
            )}
          </div>
          {llmStatus?.connection?.models?.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem', marginTop: '0.4rem' }}>
              <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>Installed:</span>
              {llmStatus.connection.models.map(m => (
                <button
                  key={m}
                  type="button"
                  style={{
                    fontSize: '0.68rem',
                    background: 'rgba(20, 184, 166, 0.1)',
                    border: '1px solid rgba(20, 184, 166, 0.3)',
                    color: 'var(--color-accent)',
                    borderRadius: '4px',
                    padding: '0.1rem 0.4rem',
                    cursor: 'pointer',
                  }}
                  onClick={() => {
                    setEditedSettings(prev => ({ ...prev, ['llm.model_name']: m }));
                    saveSetting('llm.model_name');
                  }}
                >
                  {m}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Temperature & Max Tokens */}
        <div style={{ background: 'rgba(0,0,0,0.2)', padding: '0.85rem', borderRadius: '6px', border: '1px solid var(--border-color)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.3rem' }}>
            <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
              Temperature: {editedSettings['llm.temperature'] ?? settingsData['llm.temperature']?.value ?? '0.2'}
            </label>
            <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>
              {parseFloat(editedSettings['llm.temperature'] ?? '0.2') <= 0.3 ? 'Deterministic' : 'Creative'}
            </span>
          </div>
          <input
            type="range"
            min="0.0"
            max="1.0"
            step="0.05"
            style={{ width: '100%', accentColor: 'var(--color-accent)' }}
            value={editedSettings['llm.temperature'] ?? settingsData['llm.temperature']?.value ?? '0.2'}
            onChange={e => setEditedSettings(prev => ({ ...prev, ['llm.temperature']: e.target.value }))}
            onMouseUp={() => saveSetting('llm.temperature')}
          />
        </div>
      </div>

      {/* ── System Prompt Editor (Entire Access) ── */}
      <div style={{ background: 'rgba(0,0,0,0.25)', padding: '1.25rem', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.6rem', flexWrap: 'wrap', gap: '0.5rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <TerminalIcon size={16} color="var(--color-accent)" />
              <label style={{ fontSize: '0.88rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                System Prompt (Persona & Output Guidelines)
              </label>
            </div>
            <div style={{ fontSize: '0.73rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
              Instructs the local LM on personality, tone, constraints, and JSON response schema.
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <button
              className="btn-secondary"
              style={{ fontSize: '0.72rem', padding: '0.35rem 0.65rem', display: 'flex', alignItems: 'center', gap: '0.3rem' }}
              onClick={() => {
                setEditedSettings(prev => ({ ...prev, ['llm.system_prompt']: canonicalSystemPrompt() }));
                saveSetting('llm.system_prompt');
              }}
            >
              <RotateCcw size={12} /> Reset to Default
            </button>
            <button
              className="btn-primary"
              style={{ fontSize: '0.75rem', padding: '0.4rem 0.85rem' }}
              disabled={savingKey === 'llm.system_prompt'}
              onClick={() => saveSetting('llm.system_prompt')}
            >
              {savingKey === 'llm.system_prompt' ? 'Saving…' : 'Save System Prompt'}
            </button>
          </div>
        </div>

        <textarea
          className="form-input"
          rows={7}
          style={{
            width: '100%',
            fontFamily: 'monospace',
            fontSize: '0.82rem',
            lineHeight: '1.45',
            padding: '0.75rem',
            background: '#070a11',
            borderRadius: '6px',
            color: '#e2e8f0',
            resize: 'vertical',
          }}
          value={editedSettings['llm.system_prompt'] ?? settingsData['llm.system_prompt']?.value ?? canonicalSystemPrompt()}
          onChange={e => setEditedSettings(prev => ({ ...prev, ['llm.system_prompt']: e.target.value }))}
        />
      </div>

      {/* ── User Prompt Template Editor & Variable Injector ── */}
      <div style={{ background: 'rgba(0,0,0,0.25)', padding: '1.25rem', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.6rem', flexWrap: 'wrap', gap: '0.5rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <Layers size={16} color="var(--color-accent)" />
              <label style={{ fontSize: '0.88rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                User Prompt Template (Dynamic Scraped Data Injection)
              </label>
            </div>
            <div style={{ fontSize: '0.73rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
              Scraped business fields are dynamically interpolated into these variables at runtime.
            </div>
          </div>

          <button
            className="btn-primary"
            style={{ fontSize: '0.75rem', padding: '0.4rem 0.85rem' }}
            disabled={savingKey === 'llm.user_prompt_template'}
            onClick={() => saveSetting('llm.user_prompt_template')}
          >
            {savingKey === 'llm.user_prompt_template' ? 'Saving…' : 'Save Template'}
          </button>
        </div>

        {/* Dynamic Variable Chips */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', marginBottom: '0.6rem' }}>
          <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', alignSelf: 'center', marginRight: '0.2rem' }}>Click to insert:</span>
          {PROMPT_VARIABLES.map(v => (
            <button
              key={v.key}
              type="button"
              className="badge"
              style={{
                fontSize: '0.7rem',
                fontFamily: 'monospace',
                cursor: 'pointer',
                background: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid rgba(255, 255, 255, 0.15)',
                color: 'var(--text-primary)',
                padding: '0.2rem 0.5rem',
                borderRadius: '4px',
              }}
              title={v.desc}
              onClick={() => insertVariable(v.key)}
            >
              + {v.key}
            </button>
          ))}
        </div>

        <textarea
          className="form-input"
          rows={6}
          style={{
            width: '100%',
            fontFamily: 'monospace',
            fontSize: '0.82rem',
            lineHeight: '1.45',
            padding: '0.75rem',
            background: '#070a11',
            borderRadius: '6px',
            color: '#e2e8f0',
            resize: 'vertical',
          }}
          value={editedSettings['llm.user_prompt_template'] ?? settingsData['llm.user_prompt_template']?.value ?? DEFAULT_USER_PROMPT_TEMPLATE}
          onChange={e => setEditedSettings(prev => ({ ...prev, ['llm.user_prompt_template']: e.target.value }))}
        />
      </div>

      {/* ── Interactive LM Test Sandbox ── */}
      <div style={{
        background: 'rgba(0,0,0,0.3)',
        padding: '1.25rem',
        borderRadius: '8px',
        border: '1px solid rgba(255,255,255,0.08)',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.6rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <Play size={16} color="var(--color-accent)" />
            <span style={{ fontWeight: 600, fontSize: '0.88rem', color: 'var(--text-primary)' }}>
              Interactive Local LM Playground
            </span>
          </div>
          <button
            className="btn-primary"
            style={{ fontSize: '0.75rem', padding: '0.4rem 0.9rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}
            disabled={runningTest}
            onClick={handleRunTest}
          >
            {runningTest ? <RefreshCw size={13} style={{ animation: 'spin 1s linear infinite' }} /> : <Play size={13} />}
            {runningTest ? 'Running Inference…' : 'Test Generation Now'}
          </button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
          <div>
            <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.3rem' }}>
              Sample Scraped Business Context:
            </label>
            <textarea
              className="form-input"
              rows={4}
              style={{ width: '100%', fontFamily: 'monospace', fontSize: '0.75rem', background: '#090d16', color: '#cbd5e1' }}
              value={testPromptInput}
              onChange={e => setTestPromptInput(e.target.value)}
            />
          </div>

          <div>
            <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.3rem' }}>
              Live LM Response & Generated Hook:
            </label>
            <div style={{
              background: '#090d16',
              border: '1px solid var(--border-color)',
              borderRadius: '6px',
              padding: '0.6rem 0.8rem',
              minHeight: '82px',
              fontFamily: 'monospace',
              fontSize: '0.75rem',
              color: testOutput?.success ? '#4ade80' : testOutput ? '#f87171' : 'var(--text-muted)',
              overflowY: 'auto',
              maxHeight: '130px',
            }}>
              {runningTest && <span style={{ color: 'var(--color-accent)' }}>Running local model inference…</span>}
              {!runningTest && !testOutput && <span>Click "Test Generation Now" to test your local LM configuration live.</span>}
              {!runningTest && testOutput && (
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.3rem', fontSize: '0.68rem', color: 'var(--text-muted)' }}>
                    <span>Model: {testOutput.model}</span>
                    <span>Latency: {testOutput.latency_ms}ms</span>
                  </div>
                  {testOutput.success ? (
                    <pre style={{ margin: 0, whiteSpace: 'pre-wrap', color: '#38bdf8' }}>{testOutput.raw_response}</pre>
                  ) : (
                    <div style={{ color: '#f87171' }}>Error: {testOutput.error}</div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
