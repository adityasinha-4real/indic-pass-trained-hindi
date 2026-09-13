import { ATTACK_BUDGET } from "@/lib/research-data";
import { Section } from "../Section";
import { ResearchFigure } from "./ResearchFigure";

/**
 * Translates abstract guess numbers into a practical question: at a given
 * offline-attack budget, what fraction of the benchmark did the two
 * reference attacks actually crack? Source: `results/evaluation/evaluation_report.md` §4.
 */
export function AttackBudgetSection() {
  return (
    <Section
      title="Attack-Budget Analysis"
      description="Observed (ground-truth) success rate of the two reference attacks at each budget — not a model's guess estimate, and not a live cracking run against the password you typed above."
    >
      <div className="mb-4 rounded-lg border bg-surface-muted px-3 py-2.5 text-xs leading-relaxed text-muted">
        <strong className="text-foreground">Estimated guesses</strong> (what IndicPass/PCFG/zxcvbn report
        for one password) is a model&rsquo;s own prediction of search cost.{" "}
        <strong className="text-foreground">Observed/reference attack outcomes</strong> (this table) are
        what the M4/M5 attacks actually achieved against the 1,400-sample benchmark within a stated
        candidate budget. The two are never averaged together.
      </div>

      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full min-w-[420px] border-collapse text-sm">
          <thead>
            <tr className="border-b bg-surface-muted text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-3 py-2 font-medium">Budget</th>
              <th className="px-3 py-2 font-medium text-right">M4 (wordlist) success</th>
              <th className="px-3 py-2 font-medium text-right">M5 (character model) success</th>
            </tr>
          </thead>
          <tbody>
            {ATTACK_BUDGET.map((row) => (
              <tr key={row.budgetLabel} className="border-b last:border-b-0">
                <td className="px-3 py-2 font-mono">{row.budgetLabel}</td>
                <td className="px-3 py-2 text-right font-mono">{row.m4SuccessPct.toFixed(1)}%</td>
                <td className="px-3 py-2 text-right font-mono">{row.m5SuccessPct.toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-xs text-muted">
        Success is measured against the whole 1,400-sample benchmark, not just the targets each attack
        can reach — an unreached password counts as a failure at every budget, never as a censored or
        substituted value.
      </p>

      <div className="mt-4">
        <ResearchFigure
          src="/research/evaluation-figures/attack_budget.svg"
          alt="Attack-budget success rate for M4 and M5, and estimated guess distributions overlaid"
          caption="Observed M4/M5 success rate by budget, with each estimator's own predicted crackable-share curve overlaid for comparison."
          source="results/evaluation/figures/attack_budget.svg"
        />
      </div>
    </Section>
  );
}
