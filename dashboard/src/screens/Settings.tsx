import { useState } from "react";
import { useApp } from "../context/AppContext";
import { ApiError } from "../api/client";
import { Spinner } from "../components/ui";
import { IconCheck, IconX } from "../components/icons";

export function Settings() {
  const { settings, updateSettings, api, toast } = useApp();
  const [baseUrl, setBaseUrl] = useState(settings.baseUrl);
  const [agentId, setAgentId] = useState(settings.agentId);
  const [token, setToken] = useState(settings.token);
  const [topN, setTopN] = useState(settings.topN);
  const [showToken, setShowToken] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<"ok" | "fail" | null>(null);

  const dirty =
    baseUrl !== settings.baseUrl ||
    agentId !== settings.agentId ||
    token !== settings.token ||
    topN !== settings.topN;

  const save = () => {
    updateSettings({
      baseUrl: baseUrl.trim(),
      agentId: agentId.trim(),
      token: token.trim(),
      topN,
    });
    toast("success", "Settings saved");
    setTestResult(null);
  };

  const test = async () => {
    // Test against the values currently typed, not yet-saved ones.
    updateSettings({ baseUrl: baseUrl.trim(), agentId: agentId.trim(), token: token.trim() });
    setTesting(true);
    setTestResult(null);
    try {
      await api.health();
      setTestResult("ok");
      toast("success", "Connection healthy");
    } catch (err) {
      setTestResult("fail");
      toast("error", "Connection failed", err instanceof ApiError ? err.message : String(err));
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="animate-in max-w-[680px]">
      <div className="mb-5">
        <div className="eyebrow mb-1">Configuration</div>
        <h1 className="text-[24px] font-semibold tracking-tight" style={{ color: "var(--text-strong)" }}>
          Settings
        </h1>
        <p className="text-[13.5px] mt-1" style={{ color: "var(--muted)" }}>
          Point the console at an API endpoint and agent. Stored locally in this browser.
        </p>
      </div>

      <div className="panel px-5 py-5 flex flex-col gap-4">
        <div>
          <label className="label">API base URL</label>
          <input
            className="input mono"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="http://localhost:8000"
            spellCheck={false}
          />
          <p className="text-[12px] mt-1.5" style={{ color: "var(--faint)" }}>
            The polynomial-learnings API root. Requests go to <span className="mono">{"{base}"}/v1/agents/{"{agent_id}"}/…</span>
          </p>
        </div>

        <div>
          <label className="label">Agent id</label>
          <input
            className="input mono"
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            placeholder="demo-agent"
            spellCheck={false}
          />
        </div>

        <div>
          <label className="label">
            Authorization bearer token <span style={{ color: "var(--faint)" }}>(optional)</span>
          </label>
          <div className="flex gap-2">
            <input
              className="input mono"
              type={showToken ? "text" : "password"}
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="sent as: Authorization: Bearer …"
              spellCheck={false}
              autoComplete="off"
            />
            <button className="btn" onClick={() => setShowToken((s) => !s)} type="button">
              {showToken ? "Hide" : "Show"}
            </button>
          </div>
          <p className="text-[12px] mt-1.5" style={{ color: "var(--faint)" }}>
            Attached to every request when set. This is the API's own auth token — not any
            infrastructure secret. Never enter database URLs or provider keys here.
          </p>
        </div>

        <div style={{ maxWidth: 200 }}>
          <label className="label">Stats “most used” size (top_n)</label>
          <input
            className="input"
            type="number"
            min={0}
            max={50}
            value={topN}
            onChange={(e) => setTopN(Math.min(50, Math.max(0, Number(e.target.value) || 0)))}
          />
        </div>

        <div className="flex items-center gap-2 pt-2" style={{ borderTop: "1px solid var(--border)" }}>
          <button className="btn btn-primary" onClick={save} disabled={!dirty}>
            {dirty ? "Save settings" : "Saved"}
          </button>
          <button className="btn" onClick={test} disabled={testing || !baseUrl.trim()}>
            {testing ? <Spinner size={13} /> : testResult === "ok" ? <IconCheck size={14} /> : testResult === "fail" ? <IconX size={14} /> : null}
            Test connection
          </button>
          {testResult === "ok" && <span className="text-[12.5px]" style={{ color: "var(--ok)" }}>Reachable</span>}
          {testResult === "fail" && <span className="text-[12.5px]" style={{ color: "var(--danger)" }}>Unreachable</span>}
        </div>
      </div>

      <div className="panel px-5 py-4 mt-4" style={{ background: "var(--panel-2)" }}>
        <div className="eyebrow mb-2">About this console</div>
        <ul className="text-[12.5px] flex flex-col gap-1.5" style={{ color: "var(--muted)" }}>
          <li>• Internal operator tool for reviewing an agent's curated memory — not the agent runtime, and not shown to end users.</li>
          <li>• Personal learnings are privacy-sensitive; an entity_id is always entered explicitly and never inferred.</li>
          <li>• Deletes are soft — rows are marked rejected and retained for audit, never destroyed.</li>
        </ul>
      </div>
    </div>
  );
}
