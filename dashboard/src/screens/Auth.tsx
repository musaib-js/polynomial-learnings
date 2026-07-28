import { useState, type FormEvent } from "react";
import { useAuth } from "../context/AuthContext";
import { AuthError } from "../api/auth";
import { Spinner } from "../components/ui";
import { AuthErrorBox, AuthShell } from "./AuthShell";

type Mode = "login" | "signup";

export function Auth({ onForgotPassword }: { onForgotPassword: () => void }) {
  const { login, signup } = useAuth();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") await login(email.trim(), password);
      else await signup(email.trim(), password, name.trim() || undefined);
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell
      title={mode === "login" ? "Log in" : "Create an account"}
      subtitle={
        mode === "login"
          ? "Sign in to manage your agents, API keys, and learnings."
          : "Get an API key and start persisting learnings in minutes."
      }
      footer={
        mode === "login" ? (
          <>
            Don&rsquo;t have an account?{" "}
            <button
              className="font-medium"
              style={{ color: "var(--accent)" }}
              onClick={() => {
                setError(null);
                setMode("signup");
              }}
              type="button"
            >
              Sign up
            </button>
          </>
        ) : (
          <>
            Already have an account?{" "}
            <button
              className="font-medium"
              style={{ color: "var(--accent)" }}
              onClick={() => {
                setError(null);
                setMode("login");
              }}
              type="button"
            >
              Log in
            </button>
          </>
        )
      }
    >
      <form className="flex flex-col gap-3.5" onSubmit={submit}>
        {mode === "signup" && (
          <div>
            <label className="label">
              Name <span style={{ color: "var(--faint)" }}>(optional)</span>
            </label>
            <input
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ada Lovelace"
              autoComplete="name"
            />
          </div>
        )}

        <div>
          <label className="label">Email</label>
          <input
            className="input"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@company.com"
            autoComplete="email"
          />
        </div>

        <div>
          <div className="flex items-center justify-between">
            <label className="label mb-0">Password</label>
            {mode === "login" && (
              <button
                type="button"
                className="text-[12px] font-medium mb-1.5"
                style={{ color: "var(--accent)" }}
                onClick={onForgotPassword}
              >
                Forgot password?
              </button>
            )}
          </div>
          <input
            className="input"
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={mode === "signup" ? "At least 8 characters" : "••••••••"}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
          />
        </div>

        {error && <AuthErrorBox message={error} />}

        <button
          type="submit"
          className="btn btn-primary mt-1"
          style={{ width: "100%", height: 36 }}
          disabled={busy}
        >
          {busy && <Spinner size={13} />}
          {mode === "login" ? "Log in" : "Sign up"}
        </button>
      </form>
    </AuthShell>
  );
}
