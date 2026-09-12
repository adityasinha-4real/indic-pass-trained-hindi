"use client";

import { useState } from "react";
import { analyzePassword, ApiError } from "@/lib/api";
import type { AnalyzeResponse } from "@/lib/types";
import { PasswordForm } from "./PasswordForm";
import { ResultPanel } from "./ResultPanel";

/** "idle" covers both the true empty state and "typed but not yet analyzed". */
type Status = "idle" | "loading" | "error" | "done";

export function AnalyzerSection() {
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const [revealTokens, setRevealTokens] = useState(false);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalyzeResponse | null>(null);

  async function handleSubmit() {
    if (password.length === 0) return;
    setStatus("loading");
    setError(null);
    try {
      const analysis = await analyzePassword(password, revealTokens);
      setResult(analysis);
      setStatus("done");
    } catch (err) {
      setResult(null);
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      setStatus("error");
    }
  }

  function handleClear() {
    setPassword("");
    setResult(null);
    setError(null);
    setStatus("idle");
  }

  return (
    <div className="space-y-5">
      <PasswordForm
        password={password}
        onPasswordChange={(value) => {
          setPassword(value);
          if (status !== "loading") {
            setResult(null);
            setError(null);
            setStatus("idle");
          }
        }}
        visible={visible}
        onToggleVisible={() => setVisible((v) => !v)}
        revealTokens={revealTokens}
        onToggleRevealTokens={() => setRevealTokens((v) => !v)}
        loading={status === "loading"}
        onSubmit={handleSubmit}
        onClear={handleClear}
        hasResult={result !== null}
      />

      <div aria-live="polite">
        {status === "loading" && <LoadingState />}
        {status === "error" && error && <ErrorState message={error} />}
        {status === "done" && result && <ResultPanel result={result} />}
        {status === "idle" && !result && <EmptyState />}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted">
      Enter a password above and select Analyze to see IndicPass&rsquo;s estimate,
      alongside the generic baseline and the PCFG, for that exact password.
    </div>
  );
}

function LoadingState() {
  return (
    <div className="rounded-xl border bg-surface p-8 text-center text-sm text-muted">
      Scoring against the dictionary and every attached estimator&hellip;
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="rounded-xl border border-red-300 bg-red-50 p-5 text-sm text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
    >
      <p className="font-medium">Analysis failed</p>
      <p className="mt-1">{message}</p>
    </div>
  );
}
