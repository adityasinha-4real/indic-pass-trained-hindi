"use client";

import { useId } from "react";

/**
 * Matches api/main.py's MAX_PASSWORD_LENGTH. Not an arbitrary UI limit: with
 * the zxcvbn baseline attached (the shipped default), the composed backend
 * rejects anything longer with a clear 400 rather than a 500 -- see the
 * comment on that constant for why 72.
 */
const MAX_PASSWORD_LENGTH = 72;

interface PasswordFormProps {
  password: string;
  onPasswordChange: (value: string) => void;
  visible: boolean;
  onToggleVisible: () => void;
  revealTokens: boolean;
  onToggleRevealTokens: () => void;
  loading: boolean;
  onSubmit: () => void;
  onClear: () => void;
  hasResult: boolean;
}

export function PasswordForm({
  password,
  onPasswordChange,
  visible,
  onToggleVisible,
  revealTokens,
  onToggleRevealTokens,
  loading,
  onSubmit,
  onClear,
  hasResult,
}: PasswordFormProps) {
  const inputId = useId();
  const revealId = useId();

  return (
    <form
      className="rounded-xl border bg-surface p-5 sm:p-6"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <label htmlFor={inputId} className="mb-2 block text-sm font-medium">
        Password
      </label>
      <div className="flex flex-col gap-3 sm:flex-row">
        <div className="relative flex-1">
          <input
            id={inputId}
            name="password"
            type={visible ? "text" : "password"}
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            value={password}
            onChange={(event) => onPasswordChange(event.target.value)}
            maxLength={MAX_PASSWORD_LENGTH}
            placeholder="Type a password to analyze"
            className="w-full rounded-lg border bg-background px-3.5 py-2.5 pr-11 font-mono text-sm outline-none focus:ring-2 focus:ring-accent/40"
          />
          <button
            type="button"
            onClick={onToggleVisible}
            aria-pressed={visible}
            aria-label={visible ? "Hide password" : "Show password"}
            className="absolute inset-y-0 right-2 flex items-center px-1.5 text-muted hover:text-foreground"
          >
            {visible ? <EyeOffIcon /> : <EyeIcon />}
          </button>
        </div>

        <div className="flex gap-2">
          <button
            type="submit"
            disabled={loading || password.length === 0}
            className="inline-flex items-center justify-center rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-accent-foreground transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? <Spinner /> : "Analyze"}
          </button>
          <button
            type="button"
            onClick={onClear}
            disabled={loading || (password.length === 0 && !hasResult)}
            className="inline-flex items-center justify-center rounded-lg border px-4 py-2.5 text-sm font-medium hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50"
          >
            Clear
          </button>
        </div>
      </div>

      <div className="mt-3 flex items-start gap-2">
        <input
          id={revealId}
          type="checkbox"
          checked={revealTokens}
          onChange={onToggleRevealTokens}
          className="mt-0.5 h-4 w-4 rounded border-border accent-accent"
        />
        <label htmlFor={revealId} className="text-xs leading-snug text-muted">
          Show what was matched — the substrings IndicPass recognised and their
          Devanagari rendering. Off by default; only sent when you turn it on, and
          only for the password you just submitted.
        </label>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
        <p>Never logged, never written to disk, never sent anywhere but this analysis.</p>
        <span className="font-mono">
          {password.length} / {MAX_PASSWORD_LENGTH}
        </span>
      </div>
    </form>
  );
}

function EyeIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}

function EyeOffIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M3 3l18 18M10.6 10.6a3 3 0 0 0 4.2 4.2M9.4 5.3A10.5 10.5 0 0 1 12 5c6.4 0 10 7 10 7a13.5 13.5 0 0 1-3.2 4.1M6.3 6.9C4 8.5 2 12 2 12a13.6 13.6 0 0 0 5.2 5.6"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

function Spinner() {
  return (
    <svg
      className="h-4 w-4 animate-spin"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeWidth="3"
        opacity="0.25"
      />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}
