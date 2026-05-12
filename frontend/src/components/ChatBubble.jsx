import React from 'react'

const styles = {
  row: (isBot) => ({
    display: 'flex',
    justifyContent: isBot ? 'flex-start' : 'flex-end',
    marginBottom: 8,
  }),
  bubble: (isBot) => ({
    maxWidth: '75%',
    padding: '10px 14px',
    borderRadius: isBot ? '4px 16px 16px 16px' : '16px 4px 16px 16px',
    background: isBot ? '#fff' : '#1a73e8',
    color: isBot ? '#222' : '#fff',
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
    fontSize: 15,
    lineHeight: 1.5,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  }),
  info: {
    maxWidth: '75%',
    padding: '8px 12px',
    borderRadius: 8,
    background: '#fff3cd',
    color: '#856404',
    border: '1px solid #ffc107',
    fontSize: 13,
    marginBottom: 4,
  },
  label: {
    fontSize: 11,
    color: '#888',
    marginBottom: 2,
    marginLeft: 2,
  },
}

export default function ChatBubble({ message, isBot = false }) {
  if (message.type === 'info') {
    return (
      <div style={{ display: 'flex', justifyContent: 'flex-start', marginBottom: 6 }}>
        <div style={styles.info}>{message.text}</div>
      </div>
    )
  }

  return (
    <div style={styles.row(isBot)}>
      <div>
        {isBot && <div style={styles.label}>Support Bot</div>}
        <div style={styles.bubble(isBot)}>{message.text}</div>
      </div>
    </div>
  )
}
