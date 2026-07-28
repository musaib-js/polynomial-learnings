import { useState } from "react";
import { useApp } from "../context/AppContext";
import { IconBolt, IconCheck, IconCopy, IconKey, IconLearnings, IconSandbox } from "../components/icons";
import type { Route } from "../components/Sidebar";

function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="relative">
      <pre
        className="mono overflow-x-auto rounded-lg px-4 py-3 leading-relaxed"
        style={{ background: "var(--bg)", border: "1px solid var(--border)", color: "var(--text)" }}
      >
        {code}
      </pre>
      <button
        className="btn-ghost absolute top-2 right-2 rounded-md p-1.5"
        style={{ color: "var(--faint)" }}
        title="Copy"
        onClick={() => {
          navigator.clipboard?.writeText(code);
          setCopied(true);
          setTimeout(() => setCopied(false), 1200);
        }}
      >
        {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
      </button>
    </div>
  );
}

function StepCard({
  step,
  title,
  children,
}: {
  step: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="panel px-5 py-4">
      <div className="flex items-center gap-2.5 mb-3">
        <span
          className="grid place-items-center rounded-full font-semibold shrink-0"
          style={{
            width: 22,
            height: 22,
            fontSize: 11.5,
            background: "var(--panel-2)",
            border: "1px solid var(--border-strong)",
            color: "var(--text-strong)",
          }}
        >
          {step}
        </span>
        <h3 className="text-[14px] font-semibold" style={{ color: "var(--text-strong)" }}>
          {title}
        </h3>
      </div>
      {children}
    </div>
  );
}

export function Landing({ onNavigate }: { onNavigate: (r: Route) => void }) {
  const { settings } = useApp();
  const agentId = settings.agentId || "your-agent-id";

  return (
    <div className="animate-in max-w-[880px]">
      <div className="mb-6">
        <div className="eyebrow mb-1">Welcome</div>
        <h1 className="text-[26px] font-semibold tracking-tight" style={{ color: "var(--text-strong)" }}>
          polynomial learnings
        </h1>
        <p className="text-[13.5px] mt-1.5 max-w-[620px]" style={{ color: "var(--muted)" }}>
          A hosted, long-term memory layer for AI agents. Your agent retrieves relevant
          past learnings before it answers, and durable lessons get curated and stored
          automatically — with per-user isolation, human review, and usage analytics
          built in.
        </p>
      </div>

      {/* What problem it solves */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
        <div className="panel px-4 py-4">
          <IconLearnings size={17} />
          <div className="mt-2.5 text-[13.5px] font-semibold" style={{ color: "var(--text-strong)" }}>
            Durable memory
          </div>
          <p className="text-[12.5px] mt-1" style={{ color: "var(--muted)" }}>
            Agents forget between sessions. We persist the lessons worth keeping and
            retrieve them on the next relevant conversation.
          </p>
        </div>
        <div className="panel px-4 py-4">
          <IconKey size={17} />
          <div className="mt-2.5 text-[13.5px] font-semibold" style={{ color: "var(--text-strong)" }}>
            Isolated per user
          </div>
          <p className="text-[12.5px] mt-1" style={{ color: "var(--muted)" }}>
            Personal learnings never leak across entities. Global learnings are
            explicit and agent-wide — never inferred.
          </p>
        </div>
        <div className="panel px-4 py-4">
          <IconBolt size={17} />
          <div className="mt-2.5 text-[13.5px] font-semibold" style={{ color: "var(--text-strong)" }}>
            Reviewed &amp; measured
          </div>
          <p className="text-[12.5px] mt-1" style={{ color: "var(--muted)" }}>
            Approve, edit, or reject anything the model stores, and see exactly what's
            being retrieved and how often.
          </p>
        </div>
      </div>

      {/* Quick start */}
      <div className="mb-3">
        <div className="eyebrow mb-1">Quick start</div>
        <h2 className="text-[16px] font-semibold" style={{ color: "var(--text-strong)" }}>
          Get an API key, then start persisting learnings
        </h2>
      </div>

      <div className="grid grid-cols-1 gap-3 mb-6">
        <StepCard step={1} title="Install the client">
          <CodeBlock code="pip install polynomial-learnings" />
        </StepCard>

        <StepCard step={2} title="Create an API key">
          <p className="text-[13px] mb-3" style={{ color: "var(--muted)" }}>
            Every request from the pip package needs one. Keys are shown in full only
            once, right after creation.
          </p>
          <button className="btn btn-primary" onClick={() => onNavigate("apikeys")}>
            Go to API Keys
          </button>
        </StepCard>

        <StepCard step={3} title="Retrieve and persist learnings">
          <CodeBlock
            code={`from learnings.client import LearningClient

client = LearningClient(
    agent_id="${agentId}",
    base_url="${settings.baseUrl || "https://your-api-host"}",
    headers={"Authorization": "Bearer sk_live_..."},
)

learnings = client.retrieve(
    messages=[{"role": "user", "content": "how do I get revenue by region?"}],
    entity_id="user-123",
)

result = client.persist(
    messages=[{"role": "user", "content": "always report revenue in USD"}],
    entity_id="user-123",
)`}
          />
        </StepCard>
      </div>

      {/* Where to go next */}
      <div className="panel px-5 py-4 mb-4">
        <div className="eyebrow mb-2">Where to go next</div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          <button className="btn" style={{ justifyContent: "flex-start" }} onClick={() => onNavigate("overview")}>
            <IconLearnings size={14} /> View your agents
          </button>
          <button className="btn" style={{ justifyContent: "flex-start" }} onClick={() => onNavigate("analytics")}>
            <IconBolt size={14} /> Analytics
          </button>
          <button className="btn" style={{ justifyContent: "flex-start" }} onClick={() => onNavigate("sandbox")}>
            <IconSandbox size={14} /> Try the Sandbox
          </button>
        </div>
      </div>

      <div className="panel px-5 py-4" style={{ background: "var(--panel-2)" }}>
        <div className="eyebrow mb-2">Documentation</div>
        <ul className="text-[12.5px] flex flex-col gap-1.5" style={{ color: "var(--muted)" }}>
          <li>
            • <span className="mono">README.md</span> in the package repo — full library
            reference, isolation model, and adapter usage.
          </li>
          <li>
            • <span className="mono">{"{baseUrl}"}/docs</span> — live, interactive API
            reference (Swagger UI) for every endpoint this console calls.
          </li>
          <li>
            • Settings → Advanced, for direct API/agent targeting during development.
          </li>
        </ul>
      </div>
    </div>
  );
}
