import { useChat } from './hooks/useChat'
import { Sidebar } from './components/Sidebar'
import { ChatWindow } from './components/ChatWindow'
import { InputBar } from './components/InputBar'

export default function App() {
  const { sessions, activeSession, loading, sendMessage, newSession, switchSession } = useChat()

  return (
    <div className="flex h-screen bg-gray-950 text-white overflow-hidden">
      <Sidebar
        sessions={sessions}
        activeId={activeSession?.id ?? ''}
        onNew={newSession}
        onSwitch={switchSession}
      />

      <main className="flex flex-col flex-1 min-w-0">
        <header className="px-6 py-3 border-b border-gray-700 bg-gray-900 shrink-0">
          <h2 className="text-sm font-medium text-gray-300">{activeSession?.name ?? 'agent007'}</h2>
        </header>

        {activeSession && (
          <>
            <ChatWindow session={activeSession} loading={loading} />
            <InputBar onSend={sendMessage} disabled={loading} />
          </>
        )}
      </main>
    </div>
  )
}
