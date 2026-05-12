import React, { useState, useEffect, useCallback } from 'react'
import {
  listSops, publishSop, unpublishSop, deleteSop,
  uploadSop, searchSops, listEscalations, getAnalytics,
  listConversations, getParsedSop,
} from '../services/api'

const sidebarStyle = {
  width: 200, background: '#1e293b', color: '#cbd5e1',
  display: 'flex', flexDirection: 'column', padding: '20px 0', flexShrink: 0,
}
const navBtnStyle = (active) => ({
  padding: '12px 20px', cursor: 'pointer', background: active ? '#334155' : 'transparent',
  color: active ? '#fff' : '#94a3b8', border: 'none', textAlign: 'left',
  fontSize: 14, fontWeight: active ? 600 : 400, width: '100%',
})
const mainStyle = { flex: 1, padding: 24, overflowY: 'auto', background: '#f8fafc' }
const cardStyle = { background: '#fff', borderRadius: 10, padding: 20, marginBottom: 16, boxShadow: '0 1px 4px rgba(0,0,0,0.06)' }
const tableStyle = { width: '100%', borderCollapse: 'collapse', fontSize: 13 }
const thStyle = { padding: '8px 10px', background: '#f1f5f9', textAlign: 'left', borderBottom: '2px solid #e2e8f0', fontWeight: 600 }
const tdStyle = { padding: '8px 10px', borderBottom: '1px solid #f1f5f9' }
const btnStyle = (color) => ({
  padding: '4px 12px', borderRadius: 6, border: 'none',
  background: color || '#1a73e8', color: '#fff', cursor: 'pointer', fontSize: 12, marginRight: 4,
})

function SopManager() {
  const [sops, setSops] = useState([])
  const [loading, setLoading] = useState(false)
  const [uploadFile, setUploadFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadMsg, setUploadMsg] = useState('')
  const [selectedSop, setSelectedSop] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try { const r = await listSops(); setSops(r.data) } catch { }
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  const handleUpload = async () => {
    if (!uploadFile) return
    setUploading(true); setUploadMsg('')
    try {
      const r = await uploadSop(uploadFile, false)
      setUploadMsg(`✅ Ingested: ${r.data.title}`)
      load()
    } catch (e) {
      setUploadMsg(`❌ Error: ${e.response?.data?.detail || e.message}`)
    }
    setUploading(false)
  }

  const handlePublish = async (id) => {
    await publishSop(id); load()
  }
  const handleUnpublish = async (id) => {
    await unpublishSop(id); load()
  }
  const handleDelete = async (id) => {
    if (!window.confirm('Delete this SOP?')) return
    await deleteSop(id); load()
  }
  const handleView = async (id) => {
    const r = await getParsedSop(id)
    setSelectedSop(r.data)
  }

  const statusColor = { published: '#16a34a', draft: '#d97706', reviewed: '#2563eb', archived: '#6b7280' }

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>SOP Management</h2>
      <div style={cardStyle}>
        <h3 style={{ marginBottom: 12 }}>Upload New SOP</h3>
        <input type="file" accept=".pdf,.docx,.doc" onChange={(e) => setUploadFile(e.target.files[0])} />
        <button style={btnStyle()} onClick={handleUpload} disabled={!uploadFile || uploading}>
          {uploading ? 'Ingesting…' : 'Upload & Parse'}
        </button>
        {uploadMsg && <div style={{ marginTop: 8, fontSize: 13 }}>{uploadMsg}</div>}
      </div>

      <div style={cardStyle}>
        <h3 style={{ marginBottom: 12 }}>SOP List {loading ? '(loading…)' : `(${sops.length})`}</h3>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>Title</th>
              <th style={thStyle}>Product</th>
              <th style={thStyle}>Issue</th>
              <th style={thStyle}>Status</th>
              <th style={thStyle}>Version</th>
              <th style={thStyle}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {sops.map((s) => (
              <tr key={s.id}>
                <td style={tdStyle}>{s.title}</td>
                <td style={tdStyle}>{s.product || '—'}</td>
                <td style={tdStyle}>{s.issue || '—'}</td>
                <td style={tdStyle}>
                  <span style={{ color: statusColor[s.status] || '#333', fontWeight: 600 }}>{s.status}</span>
                </td>
                <td style={tdStyle}>v{s.version}</td>
                <td style={tdStyle}>
                  <button style={btnStyle('#1a73e8')} onClick={() => handleView(s.id)}>View JSON</button>
                  {s.status !== 'published' && <button style={btnStyle('#16a34a')} onClick={() => handlePublish(s.id)}>Publish</button>}
                  {s.status === 'published' && <button style={btnStyle('#d97706')} onClick={() => handleUnpublish(s.id)}>Unpublish</button>}
                  <button style={btnStyle('#ef4444')} onClick={() => handleDelete(s.id)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selectedSop && (
        <div style={cardStyle}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
            <h3>Parsed SOP JSON</h3>
            <button style={btnStyle('#6b7280')} onClick={() => setSelectedSop(null)}>Close</button>
          </div>
          <pre style={{ background: '#1e293b', color: '#a5f3fc', padding: 16, borderRadius: 8, overflowX: 'auto', fontSize: 11, maxHeight: 480 }}>
            {JSON.stringify(selectedSop, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

function SearchTest() {
  const [query, setQuery] = useState({ product_text: '', issue_text: '', customer_message: '' })
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)

  const handleSearch = async () => {
    setLoading(true)
    try { const r = await searchSops(query); setResults(r.data) } catch { }
    setLoading(false)
  }

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Search Test</h2>
      <div style={cardStyle}>
        {['product_text', 'issue_text', 'customer_message'].map((k) => (
          <div key={k} style={{ marginBottom: 10 }}>
            <label style={{ fontSize: 13, display: 'block', marginBottom: 4 }}>{k}</label>
            <input
              style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid #ddd', fontSize: 14 }}
              value={query[k]}
              onChange={(e) => setQuery({ ...query, [k]: e.target.value })}
              placeholder={`Enter ${k.replace('_', ' ')}…`}
            />
          </div>
        ))}
        <button style={btnStyle()} onClick={handleSearch} disabled={loading}>
          {loading ? 'Searching…' : 'Search'}
        </button>
      </div>
      {results && (
        <div style={cardStyle}>
          <h3 style={{ marginBottom: 12 }}>Results — Needs Clarification: {results.needs_clarification ? 'Yes' : 'No'}</h3>
          {results.clarification_question && <p style={{ marginBottom: 12 }}>❓ {results.clarification_question}</p>}
          {results.candidates.map((c, i) => (
            <div key={i} style={{ padding: '10px 0', borderBottom: '1px solid #f0f0f0' }}>
              <strong>{c.title}</strong> — {c.product} / {c.issue}
              <br /><span style={{ fontSize: 12, color: '#666' }}>Score: {c.score} | Reasons: {c.match_reasons.join(', ')}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function EscalationsList() {
  const [items, setItems] = useState([])
  useEffect(() => {
    listEscalations().then((r) => setItems(r.data)).catch(() => {})
  }, [])

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Escalations ({items.length})</h2>
      <div style={cardStyle}>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>Customer</th>
              <th style={thStyle}>Product</th>
              <th style={thStyle}>Issue</th>
              <th style={thStyle}>Status</th>
              <th style={thStyle}>Summary</th>
              <th style={thStyle}>Date</th>
            </tr>
          </thead>
          <tbody>
            {items.map((e) => (
              <tr key={e.id}>
                <td style={tdStyle}>{e.customer_id}</td>
                <td style={tdStyle}>{e.product_name || '—'}</td>
                <td style={tdStyle}>{e.issue_name || '—'}</td>
                <td style={tdStyle}>{e.status}</td>
                <td style={tdStyle}><span title={e.summary}>{(e.summary || '').slice(0, 60)}…</span></td>
                <td style={tdStyle}>{e.created_at ? new Date(e.created_at).toLocaleDateString() : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Analytics() {
  const [data, setData] = useState(null)
  useEffect(() => {
    getAnalytics().then((r) => setData(r.data)).catch(() => {})
  }, [])

  if (!data) return <div>Loading analytics…</div>

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Analytics</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
        {[
          { label: 'Total', value: data.total_conversations },
          { label: 'Resolved', value: data.resolved_count },
          { label: 'Escalated', value: data.escalated_count },
          { label: 'Abandoned', value: data.abandoned_count },
        ].map((m) => (
          <div key={m.label} style={{ ...cardStyle, textAlign: 'center', marginBottom: 0 }}>
            <div style={{ fontSize: 28, fontWeight: 700 }}>{m.value}</div>
            <div style={{ fontSize: 13, color: '#666' }}>{m.label}</div>
          </div>
        ))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div style={cardStyle}>
          <h3 style={{ marginBottom: 8 }}>Top Products</h3>
          {(data.top_products || []).map((p, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '3px 0' }}>
              <span>{p.product}</span><span>{p.count}</span>
            </div>
          ))}
        </div>
        <div style={cardStyle}>
          <h3 style={{ marginBottom: 8 }}>Top Issues</h3>
          {(data.top_issues || []).map((p, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '3px 0' }}>
              <span>{p.issue}</span><span>{p.count}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function Conversations() {
  const [items, setItems] = useState([])
  useEffect(() => {
    listConversations({ limit: 50 }).then((r) => setItems(r.data)).catch(() => {})
  }, [])
  const statusColor = { RESOLVED: '#16a34a', ESCALATED: '#ef4444', ABANDONED: '#6b7280', NEW: '#2563eb' }
  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Conversations</h2>
      <div style={cardStyle}>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>ID</th>
              <th style={thStyle}>Customer</th>
              <th style={thStyle}>Status</th>
              <th style={thStyle}>Current Step</th>
              <th style={thStyle}>Created</th>
            </tr>
          </thead>
          <tbody>
            {items.map((c) => (
              <tr key={c.id}>
                <td style={tdStyle}><code style={{ fontSize: 11 }}>{c.id.slice(0, 8)}</code></td>
                <td style={tdStyle}>{c.customer_id}</td>
                <td style={tdStyle}>
                  <span style={{ color: statusColor[c.status] || '#333', fontWeight: 600 }}>{c.status}</span>
                </td>
                <td style={tdStyle}>{c.current_step_id || '—'}</td>
                <td style={tdStyle}>{c.created_at ? new Date(c.created_at).toLocaleString() : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const TABS = [
  { id: 'sops', label: '📋 SOPs' },
  { id: 'search', label: '🔍 Search Test' },
  { id: 'convs', label: '💬 Conversations' },
  { id: 'escalations', label: '🚨 Escalations' },
  { id: 'analytics', label: '📊 Analytics' },
]

export default function AdminPage() {
  const [tab, setTab] = useState('sops')

  const renderContent = () => {
    switch (tab) {
      case 'sops': return <SopManager />
      case 'search': return <SearchTest />
      case 'convs': return <Conversations />
      case 'escalations': return <EscalationsList />
      case 'analytics': return <Analytics />
      default: return null
    }
  }

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      <div style={sidebarStyle}>
        <div style={{ padding: '16px 20px 20px', fontSize: 16, fontWeight: 700, color: '#fff', borderBottom: '1px solid #334155' }}>
          Admin Panel
        </div>
        {TABS.map((t) => (
          <button key={t.id} style={navBtnStyle(tab === t.id)} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
        <div style={{ marginTop: 'auto', padding: '12px 20px' }}>
          <a href="/" style={{ color: '#94a3b8', fontSize: 13, textDecoration: 'none' }}>← Back to Chat</a>
        </div>
      </div>
      <div style={mainStyle}>
        {renderContent()}
      </div>
    </div>
  )
}
