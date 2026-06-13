import { useEffect, useRef } from 'react'
import { MessageBubble } from './MessageBubble'
import type { Session } from '../hooks/useChat'

interface Props {
  session: Session
  loading: boolean
}

export function ChatWindow({ session, loading }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [session.messages, loading])

  return (
    <div className="flex-1 overflow-y-auto p-6">
      {session.messages.length === 0 && !loading && (
        <div className="flex items-center justify-center h-full">
          <div className="text-center text-gray-500">
            <p className="text-lg font-medium">Start a conversation</p>
            <p className="text-sm mt-1">Ask about your Jira tasks, Notion todos, or Confluence pages.</p>
          </div>
        </div>
      )}

      {session.messages.map(msg => (
        <MessageBubble key={msg.id} message={msg} />
      ))}

      {loading && (
        <div className="flex justify-start mb-4">
          <div className="px-4 py-3 rounded-2xl rounded-tl-sm bg-gray-800">
            <div className="flex gap-1 items-center">
              <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:-0.3s]" />
              <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:-0.15s]" />
              <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" />
            </div>
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}
