import { useCallback, useEffect, useState } from "react";
import { useApp } from "../context/AppContext";
import { useAuth } from "../context/AuthContext";
import { authApi, AuthError } from "../api/auth";
import type { ApiKeyCreated, ApiKeySummary } from "../api/types";
import {
  CopyId,
  EmptyState,
  Modal,
  RefreshButton,
  Spinner,
} from "../components/ui";
import { Badge } from "../components/Badge";
import { IconAdd, IconCheck, IconCopy, IconKey, IconRefresh, IconTrash } from "../components/icons";
import { absoluteTime, relativeTime } from "../lib/format";

export function ApiKeys() {
  const { toast } = useApp();
  const { accessToken } = useAuth();
  const baseUrl = useApp().settings.baseUrl;

  const [keys, setKeys] = useState<ApiKeySummary[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rowBusy, setRowBusy] = useState<string | null>(null);

  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [createBusy, setCreateBusy] = useState(false);

  // Set right after create/regenerate — shown exactly once, then discarded.
  const [revealed, setRevealed] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      setKeys(await authApi.listApiKeys(baseUrl, accessToken));
    } catch (err) {
      setError(err instanceof AuthError ? err.message : String(err));
      setKeys(null);
    } finally {
      setLoading(false);
    }
  }, [baseUrl, accessToken]);

  useEffect(() => {
    load();
  }, [load]);

  const create = async () => {
    if (!accessToken || !newName.trim()) return;
    setCreateBusy(true);
    try {
      const created = await authApi.createApiKey(baseUrl, accessToken, newName.trim());
      setRevealed(created);
      setCreating(false);
      setNewName("");
      load();
    } catch (err) {
      toast("error", "Failed to create key", err instanceof AuthError ? err.message : String(err));
    } finally {
      setCreateBusy(false);
    }
  };

  const revoke = async (id: string) => {
    if (!accessToken) return;
    if (!window.confirm("Revoke this API key? Requests using it will start failing immediately.")) {
      return;
    }
    setRowBusy(id + "revoke");
    try {
      await authApi.revokeApiKey(baseUrl, accessToken, id);
      toast("success", "Key revoked");
      load();
    } catch (err) {
      toast("error", "Revoke failed", err instanceof AuthError ? err.message : String(err));
    } finally {
      setRowBusy(null);
    }
  };

  const regenerate = async (id: string) => {
    if (!accessToken) return;
    if (
      !window.confirm(
        "Regenerate this key? The old key is revoked immediately and a new one takes its place.",
      )
    ) {
      return;
    }
    setRowBusy(id + "regen");
    try {
      const created = await authApi.regenerateApiKey(baseUrl, accessToken, id);
      setRevealed(created);
      load();
    } catch (err) {
      toast("error", "Regenerate failed", err instanceof AuthError ? err.message : String(err));
    } finally {
      setRowBusy(null);
    }
  };

  return (
    <div className="animate-in max-w-[900px]">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 mb-5">
        <div>
          <div className="eyebrow mb-1">Access</div>
          <h1 className="text-[24px] font-semibold tracking-tight" style={{ color: "var(--text-strong)" }}>
            API keys
          </h1>
          <p className="text-[13.5px] mt-1" style={{ color: "var(--muted)" }}>
            Used by the <span className="mono">learnings</span> pip package to authenticate every
            request. Shown in full only once, at creation.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn btn-primary" onClick={() => setCreating(true)}>
            <IconAdd size={14} /> Create key
          </button>
          <RefreshButton onClick={load} loading={loading} />
        </div>
      </div>

      {error ? (
        <div
          className="panel px-4 py-3 flex items-center justify-between gap-4"
          style={{ borderColor: "var(--danger-border)", background: "var(--danger-bg)" }}
        >
          <div className="text-[13px]" style={{ color: "var(--danger)" }}>{error}</div>
          <RefreshButton onClick={load} loading={loading} label="Retry" />
        </div>
      ) : loading && !keys ? (
        <div className="panel grid place-items-center py-16">
          <Spinner size={22} />
        </div>
      ) : keys && keys.length === 0 ? (
        <div className="panel">
          <EmptyState
            icon={<IconKey size={20} />}
            title="No API keys yet"
            hint="Create one to start calling the API from the pip package."
            action={
              <button className="btn btn-primary" onClick={() => setCreating(true)}>
                <IconAdd size={14} /> Create key
              </button>
            }
          />
        </div>
      ) : keys ? (
        <div className="panel overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-[13px] border-collapse" style={{ minWidth: 720 }}>
              <thead>
                <tr style={{ color: "var(--faint)", borderBottom: "1px solid var(--border)" }}>
                  <th className="text-left eyebrow px-4 py-2.5">Name</th>
                  <th className="text-left eyebrow px-3 py-2.5">Key</th>
                  <th className="text-left eyebrow px-3 py-2.5 w-28">Status</th>
                  <th className="text-right eyebrow px-3 py-2.5 w-28">Last used</th>
                  <th className="text-right eyebrow px-3 py-2.5 w-28">Created</th>
                  <th className="text-right eyebrow px-4 py-2.5 w-[110px]">Actions</th>
                </tr>
              </thead>
              <tbody>
                {keys.map((k) => {
                  const revokedNow = k.revoked_at !== null;
                  return (
                    <tr key={k.id} style={{ borderBottom: "1px solid var(--border)" }}>
                      <td className="px-4 py-3 font-medium" style={{ color: "var(--text-strong)" }}>
                        {k.name}
                      </td>
                      <td className="px-3 py-3 mono" style={{ color: "var(--muted)" }}>
                        {k.key_prefix}…
                      </td>
                      <td className="px-3 py-3">
                        <Badge hue={revokedNow ? "danger" : "ok"}>{revokedNow ? "revoked" : "active"}</Badge>
                      </td>
                      <td className="px-3 py-3 text-right" style={{ color: "var(--muted)" }}>
                        {relativeTime(k.last_used_at)}
                      </td>
                      <td className="px-3 py-3 text-right" style={{ color: "var(--muted)" }} title={absoluteTime(k.created_at)}>
                        {relativeTime(k.created_at)}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            className="btn btn-sm btn-ghost"
                            title="Regenerate"
                            disabled={revokedNow || rowBusy === k.id + "regen"}
                            onClick={() => regenerate(k.id)}
                          >
                            {rowBusy === k.id + "regen" ? <Spinner size={12} /> : <IconRefresh size={13} />}
                          </button>
                          <button
                            className="btn btn-sm btn-ghost"
                            title="Revoke"
                            disabled={revokedNow || rowBusy === k.id + "revoke"}
                            onClick={() => revoke(k.id)}
                            style={{ color: "var(--danger)" }}
                          >
                            {rowBusy === k.id + "revoke" ? <Spinner size={12} /> : <IconTrash size={13} />}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {creating && (
        <Modal
          title="Create API key"
          subtitle="Name it after where it'll be used (e.g. “production”, “laptop”)."
          onClose={() => setCreating(false)}
          footer={
            <>
              <button className="btn" onClick={() => setCreating(false)}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={create} disabled={createBusy || !newName.trim()}>
                {createBusy && <Spinner size={13} />}
                Create
              </button>
            </>
          }
        >
          <label className="label">Name</label>
          <input
            className="input"
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="production"
            onKeyDown={(e) => e.key === "Enter" && create()}
          />
        </Modal>
      )}

      {revealed && (
        <Modal
          title="API key created"
          subtitle="Copy it now — it won't be shown again."
          onClose={() => setRevealed(null)}
          footer={
            <button className="btn btn-primary" onClick={() => setRevealed(null)}>
              Done
            </button>
          }
        >
          <div
            className="flex items-center justify-between gap-2 rounded-lg px-3 py-2.5 mono"
            style={{ background: "var(--bg)", border: "1px solid var(--border-strong)", fontSize: 12.5 }}
          >
            <span className="break-all">{revealed.raw_key}</span>
            <button
              className="btn-ghost rounded-md p-1.5 shrink-0"
              onClick={() => {
                navigator.clipboard?.writeText(revealed.raw_key);
                setCopied(true);
                setTimeout(() => setCopied(false), 1200);
              }}
              title="Copy"
            >
              {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
            </button>
          </div>
          <p className="text-[12px] mt-3" style={{ color: "var(--faint)" }}>
            Use it as an <span className="mono">Authorization: Bearer</span> header from the
            pip package. Key id: <CopyId id={revealed.id} />
          </p>
        </Modal>
      )}
    </div>
  );
}
