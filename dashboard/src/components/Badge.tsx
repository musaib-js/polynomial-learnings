import type { CSSProperties, ReactNode } from "react";
import type { Outcome, Scope, Status, Verdict } from "../api/types";

// A single accessible color system shared by status / scope / outcome / verdict.
type Hue = "ok" | "warn" | "danger" | "info" | "violet" | "neutral" | "accent";

function hueStyle(hue: Hue): CSSProperties {
  if (hue === "accent") {
    return {
      color: "var(--accent)",
      background: "color-mix(in srgb, var(--accent) 12%, transparent)",
      borderColor: "color-mix(in srgb, var(--accent) 30%, transparent)",
    };
  }
  return {
    color: `var(--${hue})`,
    background: `var(--${hue}-bg)`,
    borderColor: `var(--${hue}-border)`,
  };
}

export function Badge({
  hue,
  children,
  dot = true,
  title,
}: {
  hue: Hue;
  children: ReactNode;
  dot?: boolean;
  title?: string;
}) {
  return (
    <span className="badge" style={hueStyle(hue)} title={title}>
      {dot && <span className="dot" />}
      {children}
    </span>
  );
}

const STATUS_HUE: Record<Status, Hue> = {
  active: "ok",
  superseded: "warn",
  rejected: "danger",
};

const OUTCOME_HUE: Record<Outcome, Hue> = {
  positive: "ok",
  negative: "danger",
  neutral: "neutral",
};

const SCOPE_HUE: Record<Scope, Hue> = {
  global: "accent",
  personal: "violet",
};

// The five verdicts must read as visually distinct at a glance.
const VERDICT_HUE: Record<Verdict, Hue> = {
  new: "ok",
  same: "neutral",
  refine: "info",
  contradict: "warn",
  reject: "danger",
};

export const StatusBadge = ({ value }: { value: Status }) => (
  <Badge hue={STATUS_HUE[value] ?? "neutral"}>{value}</Badge>
);

export const OutcomeBadge = ({ value }: { value: Outcome }) => (
  <Badge hue={OUTCOME_HUE[value] ?? "neutral"} dot={value !== "neutral"}>
    {value}
  </Badge>
);

export const ScopeBadge = ({ value }: { value: Scope }) => (
  <Badge hue={SCOPE_HUE[value] ?? "neutral"}>{value}</Badge>
);

export const VerdictBadge = ({ value }: { value: Verdict }) => (
  <Badge hue={VERDICT_HUE[value] ?? "neutral"}>{value}</Badge>
);

export function verdictHue(v: Verdict): Hue {
  return VERDICT_HUE[v] ?? "neutral";
}
