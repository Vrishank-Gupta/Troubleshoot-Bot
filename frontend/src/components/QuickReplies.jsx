import React from 'react'

const btnStyle = (hovered) => ({
  padding: '8px 16px',
  borderRadius: 20,
  border: '1.5px solid #1a73e8',
  background: hovered ? '#1a73e8' : '#fff',
  color: hovered ? '#fff' : '#1a73e8',
  cursor: 'pointer',
  fontSize: 14,
  fontWeight: 500,
  transition: 'all 0.15s',
  marginRight: 6,
  marginBottom: 6,
})

function QuickReplyBtn({ label, onClick }) {
  const [hovered, setHovered] = React.useState(false)
  return (
    <button
      style={btnStyle(hovered)}
      onClick={() => onClick(label)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {label}
    </button>
  )
}

export default function QuickReplies({ buttons, onSelect, disabled = false }) {
  if (!buttons || buttons.length === 0) return null
  return (
    <div style={{ padding: '6px 12px 4px', display: 'flex', flexWrap: 'wrap', opacity: disabled ? 0.4 : 1 }}>
      {buttons.map((btn) => (
        <QuickReplyBtn key={btn} label={btn} onClick={disabled ? () => {} : onSelect} />
      ))}
    </div>
  )
}
