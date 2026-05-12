import React, { useState } from 'react'

const panelStyle = {
  position: 'fixed',
  bottom: 16,
  right: 16,
  width: 320,
  background: '#1e1e1e',
  color: '#d4d4d4',
  borderRadius: 10,
  fontFamily: 'monospace',
  fontSize: 12,
  zIndex: 1000,
  boxShadow: '0 4px 20px rgba(0,0,0,0.4)',
}

const headerStyle = {
  padding: '8px 12px',
  background: '#333',
  borderRadius: '10px 10px 0 0',
  cursor: 'pointer',
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  color: '#ccc',
  userSelect: 'none',
}

const bodyStyle = {
  padding: '10px 12px',
  maxHeight: 280,
  overflowY: 'auto',
}

const rowStyle = {
  display: 'flex',
  justifyContent: 'space-between',
  marginBottom: 4,
  borderBottom: '1px solid #333',
  paddingBottom: 3,
}

const keyStyle = { color: '#9cdcfe' }
const valStyle = { color: '#ce9178', maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }

export default function DebugPanel({ debug, conversationId }) {
  const [open, setOpen] = useState(false)
  if (!debug) return null

  return (
    <div style={panelStyle}>
      <div style={headerStyle} onClick={() => setOpen(!open)}>
        <span>🐛 Debug Panel</span>
        <span>{open ? '▲' : '▼'}</span>
      </div>
      {open && (
        <div style={bodyStyle}>
          <div style={rowStyle}><span style={keyStyle}>conversation_id</span><span style={valStyle}>{conversationId || '—'}</span></div>
          {Object.entries(debug).map(([k, v]) => (
            <div key={k} style={rowStyle}>
              <span style={keyStyle}>{k}</span>
              <span style={valStyle}>{v === null || v === undefined ? '—' : String(v)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
