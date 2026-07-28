import { useState, type FormEvent } from "react";
import { useApp } from "../context/AppContext";
import { authApi, AuthError } from "../api/auth";
import { Spinner } from "../components/ui";
import { AuthErrorBox, AuthShell } from "./AuthShell";
import { IconCheck } from "../components/icons";

export function ForgotPassword({ onBack }: { onBack: () => void }) {
  const { settings } = useApp();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await authApi.forgotPassword(settings.baseUrl, email.trim());
      setSent(true);
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell
      title="Reset your password"
      subtitle="Enter the email on your account and we'll generate a reset link."
      footer={
        <button className="font-medium" style={{ color: "var(--accent)" }} onClick={onBack} type="button">
          Back to log in
        </button>
      }
    >
      {sent ? (
        <div className="flex flex-col items-center text-center py-2">
          <div
            className="grid place-items-center rounded-full mb-3"
            style={{ width: 40, height: 40, background: "var(--ok-bg)", color: "var(--ok)" }}
          >
            <IconCheck size={18} />
          </div>
          <div className="text-[13.5px] font-medium" style={{ color: "var(--text-strong)" }}>
            Check your email
          </div>
          <p className="text-[13px] mt-1.5" style={{ color: "var(--muted)" }}>
            If an account exists for <span className="mono">{email}</span>, a password reset
            link has been generated. Follow it to set a new password.
          </p>
        </div>
      ) : (
        <form className="flex flex-col gap-3.5" onSubmit={submit}>
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
              autoFocus
            />
          </div>

          {error && <AuthErrorBox message={error} />}

          <button type="submit" className="btn btn-primary mt-1" style={{ width: "100%", height: 36 }} disabled={busy}>
            {busy && <Spinner size={13} />}
            Send reset link
          </button>
        </form>
      )}
    </AuthShell>
  );
}
