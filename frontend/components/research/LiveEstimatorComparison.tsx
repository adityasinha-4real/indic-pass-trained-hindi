import type { AnalyzeResponse } from "@/lib/types";
import { getBaselineBlock } from "@/lib/api";
import { formatGuesses, formatLog10 } from "@/lib/format";

/**
 * A horizontal bar visualization of the SAME numbers `EstimatorTable`
 * already prints — `result.indicpass` / the baseline block / `result.pcfg`
 * from this one `/api/analyze` response. No new computation: this is a
 * presentation of existing per-request data, hand-rolled the same way
 * `StrengthMeter` already renders a bar with plain divs, so no charting
 * dependency is introduced.
 *
 * This is a LIVE, per-password comparison between three estimators — it is
 * not a claim that any one of them is ground truth, and it is a different
 * kind of evidence from the "Independent Validation" section below, which
 * scores estimators against two bounded reference attacks instead of
 * against each other.
 */
export function LiveEstimatorComparison({ result }: { result: AnalyzeResponse }) {
  const baseline = getBaselineBlock(result);

  const bars: Array<{ name: string; log10: number; guesses: number; color: string }> = [
    { name: "IndicPass (M2)", log10: result.indicpass.log10_guesses, guesses: result.indicpass.guesses, color: "#1e3a5f" },
  ];
  if (baseline && result.estimators.baseline) {
    bars.push({ name: result.estimators.baseline, log10: baseline.log10_guesses, guesses: baseline.guesses, color: "#6b7280" });
  }
  if (result.pcfg) {
    bars.push({ name: "PCFG (M3)", log10: result.pcfg.log10_guesses, guesses: result.pcfg.guesses, color: "#7c3aed" });
  }

  const finiteValues = bars.map((b) => b.log10).filter((v) => Number.isFinite(v));
  const maxLog10 = Math.max(1, ...finiteValues);

  return (
    <div className="space-y-2.5">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">
        Live Estimator Comparison
      </p>
      {bars.map((bar) => {
        const widthPct = Number.isFinite(bar.log10)
          ? Math.max(2, Math.min(100, (bar.log10 / maxLog10) * 100))
          : 100;
        return (
          <div key={bar.name} className="flex items-center gap-3 text-sm">
            <div className="w-28 shrink-0 truncate font-medium" title={bar.name}>
              {bar.name}
            </div>
            <div className="relative h-6 flex-1 overflow-hidden rounded bg-surface-muted">
              <div
                className="h-full rounded"
                style={{ width: `${widthPct}%`, backgroundColor: bar.color }}
              />
            </div>
            <div className="w-40 shrink-0 text-right font-mono text-xs text-muted">
              {formatGuesses(bar.guesses)} ({formatLog10(bar.log10)} log10)
            </div>
          </div>
        );
      })}
      <p className="text-xs text-muted">
        Bars scale to log&#8321;&#8320; guesses for this one password. A longer bar means an attacker
        modeled by that estimator must try more candidates before reaching it — it is not a claim
        that any of these three is the correct answer, only what each model reports.
      </p>
    </div>
  );
}
