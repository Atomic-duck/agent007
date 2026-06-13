import type { Session } from '../hooks/useChat'

interface Props {
  sessions: Session[]
  activeId: string
  onNew: () => void
  onSwitch: (id: string) => void
}

export function Sidebar({ sessions, activeId, onNew, onSwitch }: Props) {
  return (
    <aside className="w-64 shrink-0 flex flex-col bg-gray-900 border-r border-gray-700 h-screen">
      <div className="p-4 border-b border-gray-700">
        <h1 className="text-white font-semibold text-lg">agent007</h1>
        <p className="text-gray-400 text-xs mt-0.5">Work management agent</p>
      </div>

      <nav className="flex-1 overflow-y-auto p-2 space-y-1">
        {sessions.map(session => (
          <button
            key={session.id}
            onClick={() => onSwitch(session.id)}
            className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
              session.id === activeId
                ? 'bg-gray-700 text-white'
                : 'text-gray-400 hover:bg-gray-800 hover:text-white'
            }`}
          >
            {session.name}
            <span className="block text-xs text-gray-500 mt-0.5">
              {session.messages.length} message{session.messages.length !== 1 ? 's' : ''}
            </span>
          </button>
        ))}
      </nav>

      <div className="p-3 border-t border-gray-700">
        <button
          onClick={onNew}
          className="w-full px-3 py-2 rounded-lg text-sm text-gray-300 border border-gray-600 hover:bg-gray-800 hover:text-white transition-colors"
        >
          + New Session
        </button>
      </div>
    </aside>
  )
}
