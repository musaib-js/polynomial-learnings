import { useState } from "react";
import { Sidebar, type Route } from "./components/Sidebar";
import { HealthIndicator } from "./components/HealthIndicator";
import { Toaster } from "./components/ui";
import { IconMenu, IconMoon, IconSun } from "./components/icons";
import { useApp } from "./context/AppContext";
import { Overview } from "./screens/Overview";
import { Learnings } from "./screens/Learnings";
import { Sandbox } from "./screens/Sandbox";
import { Activity } from "./screens/Activity";
import { Settings } from "./screens/Settings";

export function App() {
  const { settings, theme, toggleTheme } = useApp();
  const [route, setRoute] = useState<Route>("overview");
  const [navOpen, setNavOpen] = useState(false);

  return (
    <div className="h-full flex" style={{ color: "var(--text)" }}>
      {/* Desktop sidebar */}
      <div className="hidden md:flex">
        <Sidebar route={route} onNavigate={setRoute} />
      </div>

      {/* Mobile sidebar drawer */}
      {navOpen && (
        <div className="md:hidden fixed inset-0 z-40 flex">
          <div
            className="absolute inset-0"
            style={{ background: "rgba(0,0,0,0.5)" }}
            onClick={() => setNavOpen(false)}
          />
          <div className="relative z-10">
            <Sidebar
              route={route}
              onNavigate={(r) => {
                setRoute(r);
                setNavOpen(false);
              }}
            />
          </div>
        </div>
      )}

      <div className="flex-1 flex flex-col min-w-0">
        <header
          className="flex items-center justify-between gap-3 px-4 sm:px-6 h-14 shrink-0"
          style={{ borderBottom: "1px solid var(--border)", background: "var(--bg)" }}
        >
          <div className="flex items-center gap-3 min-w-0">
            <button
              className="btn-ghost md:hidden rounded-md p-1.5"
              onClick={() => setNavOpen(true)}
              aria-label="Open navigation"
            >
              <IconMenu size={18} />
            </button>
            <span className="eyebrow hidden sm:inline">Agent</span>
            <span
              className="mono truncate"
              style={{ color: "var(--text-strong)", fontSize: 13 }}
              title={settings.agentId}
            >
              {settings.agentId || "no agent"}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <HealthIndicator />
            <button
              className="btn-ghost rounded-md p-2"
              onClick={toggleTheme}
              aria-label="Toggle theme"
              title={theme === "dark" ? "Switch to light" : "Switch to dark"}
              style={{ border: "1px solid var(--border)", color: "var(--muted)" }}
            >
              {theme === "dark" ? <IconSun size={16} /> : <IconMoon size={16} />}
            </button>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1240px] px-4 sm:px-6 py-6">
            {route === "overview" && <Overview onNavigate={setRoute} />}
            {route === "learnings" && <Learnings />}
            {route === "sandbox" && <Sandbox />}
            {route === "activity" && <Activity />}
            {route === "settings" && <Settings />}
          </div>
        </main>
      </div>

      <Toaster />
    </div>
  );
}
