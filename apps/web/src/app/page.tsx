import { HealthStatus } from "./health-status";

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-8 bg-zinc-50 px-6 font-sans dark:bg-black">
      <h1 className="text-4xl font-semibold tracking-tight text-black dark:text-zinc-50">
        Personal AI OS
      </h1>
      <HealthStatus />
    </div>
  );
}
