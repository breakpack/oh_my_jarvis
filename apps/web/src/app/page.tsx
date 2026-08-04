import { ChatView } from "./chat-view";
import { HealthStatus } from "./health-status";

export default function Home() {
  return (
    <div className="flex h-screen flex-col bg-zinc-50 dark:bg-black">
      <header className="flex items-center justify-between border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
        <h1 className="text-xl font-semibold tracking-tight text-black dark:text-zinc-50">
          Personal AI OS
        </h1>
        <HealthStatus compact />
      </header>
      <ChatView />
    </div>
  );
}
