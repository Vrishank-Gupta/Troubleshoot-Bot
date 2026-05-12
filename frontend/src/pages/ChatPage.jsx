import React, { useState, useRef, useEffect, useCallback } from 'react'
import ChatBubble from '../components/ChatBubble'
import QuickReplies from '../components/QuickReplies'
import DebugPanel from '../components/DebugPanel'
import { sendMessage } from '../services/api'

const isDev = import.meta.env.DEV

const containerStyle = {
  display: 'flex',
  flexDirection: 'column',
  height: '100vh',
  maxWidth: 680,
  margin: '0 auto',
  background: '#fff',
  boxShadow: '0 0 40px rgba(0,0,0,0.08)',
}

const headerStyle = {
  padding: '16px 20px',
  background: '#1a73e8',
  color: '#fff',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  flexShrink: 0,
}

const messagesStyle = {
  flex: 1,
  overflowY: 'auto',
  padding: '16px 16px 8px',
  background: '#f0f2f5',
}

const inputAreaStyle = {
  borderTop: '1px solid #e0e0e0',
  background: '#fff',
  flexShrink: 0,
}

const inputRowStyle = {
  display: 'flex',
  padding: '10px 12px',
  gap: 8,
}

const inputStyle = {
  flex: 1,
  padding: '10px 14px',
  borderRadius: 24,
  border: '1.5px solid #ddd',
  fontSize: 15,
  outline: 'none',
  background: '#fafafa',
}

const sendBtnStyle = (disabled) => ({
  padding: '10px 20px',
  borderRadius: 24,
  border: 'none',
  background: disabled ? '#ccc' : '#1a73e8',
  color: '#fff',
  fontWeight: 600,
  fontSize: 15,
  cursor: disabled ? 'not-allowed' : 'pointer',
})

const CUSTOMER_ID = `web_${Math.random().toString(36).slice(2, 10)}`

export default function ChatPage() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [conversationId, setConversationId] = useState(null)
  const [state, setState] = useState('NEW')
  const [debug, setDebug] = useState(null)
  const [activeButtons, setActiveButtons] = useState([])
  const bottomRef = useRef(null)

  const scrollToBottom = () => bottomRef.current?.scrollIntoView({ behavior: 'smooth' })

  useEffect(() => { scrollToBottom() }, [messages])

  // Auto-start greeting
  useEffect(() => {
    handleSend('', true)
  }, [])

  const appendBotMessages = (botMsgs) => {
    const uiMsgs = botMsgs.map((m) => ({ ...m, from: 'bot' }))
    setMessages((prev) => [...prev, ...uiMsgs])
    const lastWithButtons = [...botMsgs].reverse().find((m) => m.type === 'buttons')
    setActiveButtons(lastWithButtons?.buttons || [])
  }

  const handleSend = useCallback(async (text, silent = false) => {
    const msg = text || input
    if (!msg.trim() && !silent) return
    if (loading) return

    if (!silent) {
      setMessages((prev) => [...prev, { type: 'text', text: msg, from: 'user' }])
      setInput('')
      setActiveButtons([])
    }

    setLoading(true)
    try {
      const res = await sendMessage({
        conversation_id: conversationId || undefined,
        customer_id: CUSTOMER_ID,
        channel: 'web',
        message: msg || '__init__',
      })
      const data = res.data
      setConversationId(data.conversation_id)
      setState(data.state)
      if (data.debug) setDebug(data.debug)
      appendBotMessages(data.messages || [])
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { type: 'text', text: 'Sorry, something went wrong. Please try again.', from: 'bot' },
      ])
    } finally {
      setLoading(false)
    }
  }, [conversationId, input, loading])

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleReset = () => {
    setMessages([])
    setConversationId(null)
    setState('NEW')
    setDebug(null)
    setActiveButtons([])
    setTimeout(() => handleSend('restart', true), 100)
  }

  const isTerminal = ['RESOLVED', 'ESCALATED'].includes(state)

  return (
    <div style={containerStyle}>
      {/* Header */}
      <div style={headerStyle}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 18 }}>Support</div>
          <div style={{ fontSize: 12, opacity: 0.85 }}>
            {loading ? 'Typing...' : `Status: ${state}`}
          </div>
        </div>
        <button
          onClick={handleReset}
          style={{ background: 'rgba(255,255,255,0.2)', border: 'none', color: '#fff', borderRadius: 8, padding: '6px 14px', cursor: 'pointer', fontSize: 13 }}
        >
          New Chat
        </button>
      </div>

      {/* Messages */}
      <div style={messagesStyle}>
        {messages.map((msg, i) => (
          <ChatBubble key={i} message={msg} isBot={msg.from === 'bot'} />
        ))}
        {loading && (
          <ChatBubble message={{ type: 'text', text: '...' }} isBot />
        )}
        <div ref={bottomRef} />
      </div>

      {/* Quick Replies */}
      <QuickReplies
        buttons={activeButtons}
        onSelect={(btn) => handleSend(btn)}
        disabled={loading || isTerminal}
      />

      {/* Input */}
      <div style={inputAreaStyle}>
        <div style={inputRowStyle}>
          <input
            style={inputStyle}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={isTerminal ? 'Type "restart" to start over…' : 'Type your message…'}
            disabled={loading}
          />
          <button
            style={sendBtnStyle(loading || !input.trim())}
            onClick={() => handleSend()}
            disabled={loading || !input.trim()}
          >
            Send
          </button>
        </div>
      </div>

      {isDev && <DebugPanel debug={debug} conversationId={conversationId} />}
    </div>
  )
}
