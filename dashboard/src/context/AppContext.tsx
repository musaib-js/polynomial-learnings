import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiClient, type LogEntry } from "../api/client";
import {
  loadSettings,
  loadTheme,
  saveSettings,
  saveTheme,
  type Settings,
} from "../lib/settings";

export type Theme = "dark" | "light";
export type ToastKind = "success" | "error" | "info";

export interface Toast {
  id: string;
  kind: ToastKind;
  title: string;
  detail?: string;
}

interface AppContextValue {
  settings: Settings;
  updateSettings: (patch: Partial<Settings>) => void;
  api: ApiClient;
  log: LogEntry[];
  clearLog: () => void;
  theme: Theme;
  toggleTheme: () => void;
  toasts: Toast[];
  toast: (kind: ToastKind, title: string, detail?: string) => void;
  dismissToast: (id: string) => void;
  configured: boolean;
}

const Ctx = createContext<AppContextValue | null>(null);
const MAX_LOG = 200;

export function AppProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<Settings>(() => loadSettings());
  const [theme, setTheme] = useState<Theme>(() => loadTheme());
  const [log, setLog] = useState<LogEntry[]>([]);
  const [toasts, setToasts] = useState<Toast[]>([]);

  // One long-lived client; its config is updated in place so log subscribers
  // and in-flight screens keep the same instance.
  const apiRef = useRef<ApiClient>();
  if (!apiRef.current) apiRef.current = new ApiClient(settings);
  const api = apiRef.current;

  useEffect(() => {
    api.setConfig(settings);
    saveSettings(settings);
  }, [api, settings]);

  useEffect(() => {
    const off = api.onLog((entry) => {
      setLog((prev) => [entry, ...prev].slice(0, MAX_LOG));
    });
    return off;
  }, [api]);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    saveTheme(theme);
  }, [theme]);

  const updateSettings = useCallback((patch: Partial<Settings>) => {
    setSettings((prev) => ({ ...prev, ...patch }));
  }, []);

  const clearLog = useCallback(() => setLog([]), []);
  const toggleTheme = useCallback(
    () => setTheme((t) => (t === "dark" ? "light" : "dark")),
    [],
  );

  const dismissToast = useCallback(
    (id: string) => setToasts((prev) => prev.filter((t) => t.id !== id)),
    [],
  );

  const toast = useCallback(
    (kind: ToastKind, title: string, detail?: string) => {
      const id = Math.random().toString(36).slice(2);
      setToasts((prev) => [...prev, { id, kind, title, detail }]);
      const ttl = kind === "error" ? 7000 : 4000;
      window.setTimeout(() => dismissToast(id), ttl);
    },
    [dismissToast],
  );

  const value = useMemo<AppContextValue>(
    () => ({
      settings,
      updateSettings,
      api,
      log,
      clearLog,
      theme,
      toggleTheme,
      toasts,
      toast,
      dismissToast,
      configured: settings.baseUrl.trim() !== "" && settings.agentId.trim() !== "",
    }),
    [
      settings,
      updateSettings,
      api,
      log,
      clearLog,
      theme,
      toggleTheme,
      toasts,
      toast,
      dismissToast,
    ],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp must be used within AppProvider");
  return v;
}
