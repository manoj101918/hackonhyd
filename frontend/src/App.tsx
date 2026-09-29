import { DemoBar, MemoryBanner, TopBar } from './components/Chrome'
import { Compare } from './components/Compare'
import { DeployCheck } from './components/DeployCheck'
import { IncidentChannel } from './components/IncidentChannel'
import { Learning } from './components/Learning'
import { MemoryPanel } from './components/MemoryPanel'
import { AppProvider, useApp } from './state'

function Main() {
  const { tab } = useApp()
  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <TopBar />
      <MemoryBanner />
      <DemoBar />
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_380px] grid-rows-1 overflow-hidden">
        <main className="min-h-0 overflow-hidden">
          {tab === 'channel' && <IncidentChannel />}
          {tab === 'compare' && <Compare />}
          {tab === 'deploy' && <DeployCheck />}
          {tab === 'learning' && <Learning />}
        </main>
        <MemoryPanel />
      </div>
    </div>
  )
}

export default function App() {
  return (
    <AppProvider>
      <Main />
    </AppProvider>
  )
}
