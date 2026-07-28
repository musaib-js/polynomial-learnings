import { useState } from "react";
import { Sidebar, type Route } from "./components/Sidebar";
import { HealthIndicator } from "./components/HealthIndicator";
import { Spinner, Toaster } from "./components/ui";
import { IconMenu, IconMoon, IconSun } from "./components/icons";
import { useApp } from "./context/AppContext";
import { useAuth } from "./context/AuthContext";
import { Auth } from "./screens/Auth";
import { ForgotPassword } from "./screens/ForgotPassword";
import { ResetPassword } from "./screens/ResetPassword";
import { Landing } from "./screens/Landing";
import { Overview } from "./screens/Overview";
import { Learnings } from "./screens/Learnings";
import { Analytics } from "./screens/Analytics";
import { ApiKeys } from "./screens/ApiKeys";
import { Sandbox } from "./screens/Sandbox";
import { Activity } from "./screens/Activity";
import { Settings } from "./screens/Settings";

type UnauthView = "login" | "forgot" | "reset";

function initialUnauthView(): { view: UnauthView; resetToken?: string } {
  const token = new URLSearchParams(window.location.search).get("reset_token");
  return token ? { view: "reset", resetToken: token } : { view: "login" };
}

export function App() {
  const { status } = useAuth();
  const [unauth] = useState(initialUnauthView);
  const [unauthView, setUnauthView] = useState<UnauthView>(unauth.view);

  if (status === "checking") {
    return (
      <div className="h-full w-full flex items-center justify-center">
        <Spinner size={20} />
      </div>
    );
  }

  if (status === "anon") {
    if (unauthView === "forgot") {
      return <ForgotPassword onBack={() => setUnauthView("login")} />;
    }
    if (unauthView === "reset") {
      return (
        <ResetPassword initialToken={unauth.resetToken} onBack={() => setUnauthView("login")} />
      );
    }
    return <Auth onForgotPassword={() => setUnauthView("forgot")} />;
  }

  return <Dashboard />;
}

function Dashboard() {
  const { settings, theme, toggleTheme } = useApp();
  const { user, logout } = useAuth();
  const [route, setRoute] = useState<Route>("home");
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
            {user && (
              <button
                className="btn btn-sm hidden sm:inline-flex"
                onClick={logout}
                title={user.email}
              >
                Log out
              </button>
            )}
          </div>
        </header>

        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1240px] px-4 sm:px-6 py-6">
            {route === "home" && <Landing onNavigate={setRoute} />}
            {route === "overview" && <Overview onNavigate={setRoute} />}
            {route === "learnings" && <Learnings />}
            {route === "analytics" && <Analytics />}
            {route === "apikeys" && <ApiKeys />}
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
