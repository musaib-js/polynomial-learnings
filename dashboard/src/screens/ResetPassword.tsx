import { useState, type FormEvent } from "react";
import { useApp } from "../context/AppContext";
import { authApi, AuthError } from "../api/auth";
import { Spinner } from "../components/ui";
import { AuthErrorBox, AuthShell } from "./AuthShell";
import { IconCheck } from "../components/icons";

// The backend's forgot-password flow doesn't wire up email delivery yet (see
// learnings/api/auth_routes.py::forgot_password) — it logs the raw reset
// token server-side. Until that's connected, the token is pasted in here
// manually (or arrives via a `?reset_token=` link, once email sending
// exists) rather than assumed to come from an email click-through.
export function ResetPassword({
  initialToken,
  onBack,
}: {
  initialToken?: string;
  onBack: () => void;
}) {
  const { settings } = useApp();
  const [token, setToken] = useState(initialToken ?? "");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await authApi.resetPassword(settings.baseUrl, token.trim(), password);
      setDone(true);
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell
      title="Set a new password"
      subtitle="Paste the reset token you received, then choose a new password."
      footer={
        <button className="font-medium" style={{ color: "var(--accent)" }} onClick={onBack} type="button">
          Back to log in
        </button>
      }
    >
      {done ? (
        <div className="flex flex-col items-center text-center py-2">
          <div
            className="grid place-items-center rounded-full mb-3"
            style={{ width: 40, height: 40, background: "var(--ok-bg)", color: "var(--ok)" }}
          >
            <IconCheck size={18} />
          </div>
          <div className="text-[13.5px] font-medium" style={{ color: "var(--text-strong)" }}>
            Password updated
          </div>
          <p className="text-[13px] mt-1.5 mb-4" style={{ color: "var(--muted)" }}>
            You can now log in with your new password.
          </p>
          <button className="btn btn-primary" onClick={onBack} type="button">
            Back to log in
          </button>
        </div>
      ) : (
        <form className="flex flex-col gap-3.5" onSubmit={submit}>
          <div>
            <label className="label">Reset token</label>
            <input
              className="input mono"
              required
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="paste the token here"
              spellCheck={false}
              autoFocus={!initialToken}
            />
          </div>

          <div>
            <label className="label">New password</label>
            <input
              className="input"
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 8 characters"
              autoComplete="new-password"
              autoFocus={!!initialToken}
            />
          </div>

          {error && <AuthErrorBox message={error} />}

          <button type="submit" className="btn btn-primary mt-1" style={{ width: "100%", height: 36 }} disabled={busy}>
            {busy && <Spinner size={13} />}
            Update password
          </button>
        </form>
      )}
    </AuthShell>
  );
}
