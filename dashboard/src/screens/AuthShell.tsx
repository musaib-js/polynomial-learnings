import type { ReactNode } from "react";

// Shared centered-card layout for every unauthenticated screen (login,
// signup, forgot/reset password). Pulled out of Auth.tsx so ForgotPassword
// and ResetPassword can match it exactly without duplicating the logo/panel
// markup — the login/signup form logic itself is untouched.
export function AuthShell({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div
      className="h-full w-full flex items-center justify-center px-4"
      style={{ background: "var(--bg)" }}
    >
      <div className="w-full animate-in" style={{ maxWidth: 380 }}>
        <div className="flex flex-col items-center mb-6">
          <span
            className="grid place-items-center rounded-lg font-bold mb-3"
            style={{
              width: 40,
              height: 40,
              background: "var(--accent)",
              color: "var(--accent-fg)",
              fontSize: 20,
            }}
          >
            p
          </span>
          <div className="text-[16px] font-semibold" style={{ color: "var(--text-strong)" }}>
            polynomial
          </div>
          <div className="eyebrow mt-0.5">learnings · console</div>
        </div>

        <div className="panel px-5 py-5">
          <div className="mb-4">
            <h1 className="text-[17px] font-semibold" style={{ color: "var(--text-strong)" }}>
              {title}
            </h1>
            {subtitle && (
              <p className="text-[13px] mt-1" style={{ color: "var(--muted)" }}>
                {subtitle}
              </p>
            )}
          </div>
          {children}
        </div>

        {footer && (
          <div className="text-center mt-4 text-[13px]" style={{ color: "var(--muted)" }}>
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

export function AuthErrorBox({ message }: { message: string }) {
  return (
    <div
      className="text-[12.5px] rounded-md px-3 py-2"
      style={{
        color: "var(--danger)",
        background: "var(--danger-bg)",
        border: "1px solid var(--danger-border)",
      }}
    >
      {message}
    </div>
  );
}
