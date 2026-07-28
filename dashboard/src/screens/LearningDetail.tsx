import { useState } from "react";
import type { Learning, LearningPatch, Outcome } from "../api/types";
import { useApp } from "../context/AppContext";
import { ApiError } from "../api/client";
import { Modal, Spinner, CopyId, Tag } from "../components/ui";
import { OutcomeBadge, ScopeBadge, StatusBadge } from "../components/Badge";
import { absoluteTime, num, relativeTime } from "../lib/format";
import { IconCheck, IconX, IconTrash, IconEdit, IconLink } from "../components/icons";

const OUTCOMES: Outcome[] = ["positive", "neutral", "negative"];

// Read-only metadata row.
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[120px_1fr] gap-3 py-2 items-start border-t" style={{ borderColor: "var(--border)" }}>
      <div className="eyebrow pt-0.5">{label}</div>
      <div className="text-[13px]" style={{ color: "var(--text)" }}>{children}</div>
    </div>
  );
}

export function LearningDetail({
  learning,
  onClose,
  onChanged,
}: {
  learning: Learning;
  onClose: () => void;
  onChanged: (l: Learning) => void;
}) {
  const { api, toast } = useApp();
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Editable draft (only the six allowed fields).
  const [ctx, setCtx] = useState(learning.context);
  const [content, setContent] = useState(learning.content);
  const [category, setCategory] = useState(learning.category ?? "");
  const [tagsStr, setTagsStr] = useState(learning.tags.join(", "));
  const [reason, setReason] = useState(learning.reason ?? "");
  const [outcome, setOutcome] = useState<Outcome>(learning.outcome);

  const run = async (
    label: string,
    fn: () => Promise<Learning>,
    successMsg: string,
  ) => {
    setBusy(label);
    try {
      const updated = await fn();
      onChanged(updated);
      toast("success", successMsg);
      return updated;
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err);
      toast("error", `${label} failed`, msg);
      throw err;
    } finally {
      setBusy(null);
    }
  };

  const saveEdits = async () => {
    const patch: LearningPatch = {
      context: ctx,
      content,
      category: category.trim() === "" ? null : category.trim(),
      tags: tagsStr
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean),
      reason: reason.trim() === "" ? null : reason.trim(),
      outcome,
    };
    try {
      await run("Save", () => api.update(learning.id, patch), "Changes saved");
      setEditing(false);
    } catch {
      /* toast already shown */
    }
  };

  const footer = editing ? (
    <>
      <button className="btn" onClick={() => setEditing(false)} disabled={!!busy}>
        Cancel
      </button>
      <button className="btn btn-primary" onClick={saveEdits} disabled={!!busy}>
        {busy === "Save" ? <Spinner size={13} /> : <IconCheck size={14} />}
        Save changes
      </button>
    </>
  ) : (
    <>
      <button
        className="btn"
        onClick={() => run("Approve", () => api.approve(learning.id), "Marked active")}
        disabled={!!busy || learning.status === "active"}
        title={learning.status === "active" ? "Already active" : "Mark active"}
      >
        {busy === "Approve" ? <Spinner size={13} /> : <IconCheck size={14} />}
        Approve
      </button>
      <button
        className="btn"
        onClick={() => run("Disapprove", () => api.disapprove(learning.id), "Marked rejected")}
        disabled={!!busy || learning.status === "rejected"}
      >
        {busy === "Disapprove" ? <Spinner size={13} /> : <IconX size={14} />}
        Disapprove
      </button>
      <button className="btn" onClick={() => setEditing(true)} disabled={!!busy}>
        <IconEdit size={14} />
        Edit
      </button>
      <button className="btn btn-danger" onClick={() => setConfirmDelete(true)} disabled={!!busy}>
        <IconTrash size={14} />
        Delete
      </button>
    </>
  );

  return (
    <Modal
      title={editing ? "Edit learning" : "Learning"}
      subtitle={
        <span className="flex items-center gap-2 flex-wrap">
          <StatusBadge value={learning.status} />
          <ScopeBadge value={learning.scope} />
          <OutcomeBadge value={learning.outcome} />
        </span>
      }
      onClose={onClose}
      wide
      footer={footer}
    >
      {editing ? (
        <div className="flex flex-col gap-3.5">
          <div>
            <label className="label">Context</label>
            <textarea className="textarea" value={ctx} onChange={(e) => setCtx(e.target.value)} rows={2} />
          </div>
          <div>
            <label className="label">Content (the lesson)</label>
            <textarea className="textarea" value={content} onChange={(e) => setContent(e.target.value)} rows={3} />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
            <div>
              <label className="label">Category</label>
              <input className="input" value={category} onChange={(e) => setCategory(e.target.value)} placeholder="none" />
            </div>
            <div>
              <label className="label">Outcome</label>
              <select className="select" value={outcome} onChange={(e) => setOutcome(e.target.value as Outcome)}>
                {OUTCOMES.map((o) => (
                  <option key={o} value={o}>{o}</option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <label className="label">Tags <span style={{ color: "var(--faint)" }}>(comma-separated)</span></label>
            <input className="input" value={tagsStr} onChange={(e) => setTagsStr(e.target.value)} placeholder="e.g. scheduling, preferences" />
          </div>
          <div>
            <label className="label">Reason</label>
            <textarea className="textarea" value={reason} onChange={(e) => setReason(e.target.value)} rows={2} placeholder="Why this lesson was recorded" />
          </div>
          <p className="text-[12px]" style={{ color: "var(--faint)" }}>
            Only these six fields are editable. Editing context or content re-embeds the
            learning on the server. All other fields are managed by the system.
          </p>
        </div>
      ) : (
        <div>
          <div className="mb-1 eyebrow">Context</div>
          <div className="text-[13px] mb-3" style={{ color: "var(--muted)" }}>{learning.context}</div>
          <div className="mb-1 eyebrow">Content</div>
          <div className="text-[14px] leading-relaxed" style={{ color: "var(--text-strong)" }}>
            {learning.content}
          </div>

          {(learning.original_output || learning.corrected_output) && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4">
              {learning.original_output && (
                <div className="panel px-3 py-2.5" style={{ background: "var(--panel-2)" }}>
                  <div className="eyebrow mb-1" style={{ color: "var(--danger)" }}>Original output</div>
                  <div className="text-[12.5px]" style={{ color: "var(--muted)" }}>{learning.original_output}</div>
                </div>
              )}
              {learning.corrected_output && (
                <div className="panel px-3 py-2.5" style={{ background: "var(--panel-2)" }}>
                  <div className="eyebrow mb-1" style={{ color: "var(--ok)" }}>Corrected output</div>
                  <div className="text-[12.5px]" style={{ color: "var(--muted)" }}>{learning.corrected_output}</div>
                </div>
              )}
            </div>
          )}

          <div className="mt-4">
            {learning.reason && <Field label="Reason">{learning.reason}</Field>}
            <Field label="Category">
              {learning.category ?? <span style={{ color: "var(--faint)" }}>none</span>}
            </Field>
            <Field label="Tags">
              {learning.tags.length ? (
                <span className="flex flex-wrap gap-1.5">
                  {learning.tags.map((t) => <Tag key={t}>{t}</Tag>)}
                </span>
              ) : (
                <span style={{ color: "var(--faint)" }}>none</span>
              )}
            </Field>
            <Field label="Hits">
              <span className="tabular-nums">{num(learning.hits)}</span>
            </Field>
            <Field label="Entity">
              {learning.entity_id ? <CopyId id={learning.entity_id} label="entity_id" head={24} /> : <span style={{ color: "var(--faint)" }}>global (all users)</span>}
            </Field>
            <Field label="Created">
              <span title={absoluteTime(learning.created_at)}>{absoluteTime(learning.created_at)}</span>
            </Field>
            <Field label="Last used">
              <span title={absoluteTime(learning.last_used_at)}>{relativeTime(learning.last_used_at)}</span>
            </Field>
            {learning.supersedes && (
              <Field label="Supersedes">
                <span className="inline-flex items-center gap-1.5" style={{ color: "var(--warn)" }}>
                  <IconLink size={13} />
                  <CopyId id={learning.supersedes} label="superseded id" head={24} />
                </span>
                <div className="text-[12px] mt-1" style={{ color: "var(--faint)" }}>
                  This learning replaced an earlier, contradicting one.
                </div>
              </Field>
            )}
            <Field label="Learning id">
              <CopyId id={learning.id} label="learning id" head={36} />
            </Field>
          </div>
        </div>
      )}

      {confirmDelete && (
        <Modal
          title="Soft-delete this learning?"
          onClose={() => setConfirmDelete(false)}
          footer={
            <>
              <button className="btn" onClick={() => setConfirmDelete(false)} disabled={!!busy}>
                Cancel
              </button>
              <button
                className="btn btn-danger"
                disabled={!!busy}
                onClick={async () => {
                  try {
                    await run("Delete", () => api.softDelete(learning.id), "Learning soft-deleted");
                    setConfirmDelete(false);
                  } catch {
                    /* toast shown */
                  }
                }}
              >
                {busy === "Delete" ? <Spinner size={13} /> : <IconTrash size={14} />}
                Soft-delete
              </button>
            </>
          }
        >
          <p className="text-[13px]" style={{ color: "var(--text)" }}>
            This marks the learning <strong>rejected</strong> so the agent stops
            retrieving it. It is <strong>not</strong> permanently destroyed — the row is
            retained for audit and can be approved again later.
          </p>
        </Modal>
      )}
    </Modal>
  );
}
