import { useState, useEffect, useCallback } from 'react'
import { v4 as uuidv4 } from 'uuid'

export type Role = 'user' | 'agent' | 'error'

export interface Message {
  id: string
  role: Role
  content: string
  timestamp: string
}

export interface Session {
  id: string
  name: string
  messages: Message[]
  createdAt: string
}

const STORAGE_KEY = 'agent007_sessions'
const TIMEOUT_MS = 60_000

function loadSessions(): Session[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveSessions(sessions: Session[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions))
  } catch {
    // QuotaExceededError — silently skip persistence
  }
}

function makeSession(index: number): Session {
  return {
    id: uuidv4(),
    name: `Session ${index}`,
    messages: [],
    createdAt: new Date().toISOString(),
  }
}

export function useChat() {
  const [sessions, setSessions] = useState<Session[]>(() => {
    const stored = loadSessions()
    return stored.length > 0 ? stored : [makeSession(1)]
  })
  const [activeId, setActiveId] = useState<string>(() => {
    const stored = loadSessions()
    return stored.length > 0 ? stored[0].id : ''
  })
  const [userId, setUserId] = useState<string>('default')
  const [loading, setLoading] = useState(false)

  // Sync activeId when sessions first load
  useEffect(() => {
    if (!activeId && sessions.length > 0) {
      setActiveId(sessions[0].id)
    }
  }, [sessions, activeId])

  // Persist sessions to localStorage on every change
  useEffect(() => {
    saveSessions(sessions)
  }, [sessions])

  // Fetch user identity once on mount
  useEffect(() => {
    fetch('/me')
      .then(r => r.json())
      .then(data => { if (data.user_id) setUserId(data.user_id) })
      .catch(() => { /* keep default */ })
  }, [])

  const activeSession = sessions.find(s => s.id === activeId) ?? sessions[0]

  const appendMessage = useCallback((sessionId: string, msg: Omit<Message, 'id'>) => {
    setSessions(prev => prev.map(s =>
      s.id === sessionId
        ? { ...s, messages: [...s.messages, { ...msg, id: uuidv4() }] }
        : s
    ))
  }, [])

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || loading) return
    const sessionId = activeSession.id

    appendMessage(sessionId, { role: 'user', content: text, timestamp: new Date().toISOString() })
    setLoading(true)

    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS)

    try {
      const res = await fetch('/invocations', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-GreenNode-AgentBase-User-Id': userId,
          'X-GreenNode-AgentBase-Session-Id': sessionId,
        },
        body: JSON.stringify({ message: text }),
        signal: controller.signal,
      })

      const data = await res.json()

      if (data.status === 'error') {
        appendMessage(sessionId, { role: 'error', content: data.error ?? 'Unknown error', timestamp: new Date().toISOString() })
      } else {
        appendMessage(sessionId, { role: 'agent', content: data.response || '(no response)', timestamp: new Date().toISOString() })
      }
    } catch (err: unknown) {
      const msg = (err instanceof Error && err.name === 'AbortError')
        ? 'Request timed out after 60 seconds.'
        : 'Agent unreachable — is the server running?'
      appendMessage(sessionId, { role: 'error', content: msg, timestamp: new Date().toISOString() })
    } finally {
      clearTimeout(timeout)
      setLoading(false)
    }
  }, [activeSession, userId, loading, appendMessage])

  const newSession = useCallback(() => {
    const session = makeSession(sessions.length + 1)
    setSessions(prev => [...prev, session])
    setActiveId(session.id)
  }, [sessions.length])

  const switchSession = useCallback((id: string) => {
    setActiveId(id)
  }, [])

  return { sessions, activeSession, userId, loading, sendMessage, newSession, switchSession }
}
