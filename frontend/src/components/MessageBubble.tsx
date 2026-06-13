import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Message } from '../hooks/useChat'

export function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'
  const isError = message.role === 'error'

  if (isUser) {
    return (
      <div className="flex justify-end mb-4">
        <div className="max-w-[75%] px-4 py-2.5 rounded-2xl rounded-tr-sm bg-blue-600 text-white text-sm">
          {message.content}
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex justify-start mb-4">
        <div className="max-w-[75%] px-4 py-2.5 rounded-2xl rounded-tl-sm bg-red-900/50 border border-red-700 text-red-300 text-sm">
          {message.content}
        </div>
      </div>
    )
  }

  return (
    <div className="flex justify-start mb-4">
      <div className="max-w-[75%] px-4 py-2.5 rounded-2xl rounded-tl-sm bg-gray-800 text-gray-100 text-sm prose prose-invert prose-sm max-w-none">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {message.content}
        </ReactMarkdown>
      </div>
    </div>
  )
}
