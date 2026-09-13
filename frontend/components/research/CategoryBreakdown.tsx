import {
  CATEGORY_BREAKDOWN,
  OOV_PARTITION_BREAKDOWN,
  CATEGORY_SPEARMAN_M4,
  ZXCVBN_CATEGORY_SPEARMAN_M4,
  type CategoryRow,
} from "@/lib/research-data";
import { Section } from "../Section";
import { ResearchFigure } from "./ResearchFigure";

function BreakdownTable({ rows }: { rows: CategoryRow[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full min-w-[560px] border-collapse text-sm">
        <thead>
          <tr className="border-b bg-surface-muted text-left text-xs uppercase tracking-wide text-muted">
            <th className="px-3 py-2 font-medium">Category</th>
            <th className="px-3 py-2 font-medium text-right">n</th>
            <th className="px-3 py-2 font-medium text-right">Accuracy</th>
            <th className="px-3 py-2 font-medium text-right">F1</th>
            <th className="px-3 py-2 font-medium text-right">ROC-AUC</th>
            <th className="px-3 py-2 font-medium text-right">M4 coverage</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.name} className="border-b last:border-b-0">
              <td className="px-3 py-2 font-mono">{row.name}</td>
              <td className="px-3 py-2 text-right font-mono">{row.n}</td>
              <td className="px-3 py-2 text-right font-mono">{row.accuracy.toFixed(3)}</td>
              <td className="px-3 py-2 text-right font-mono">{row.f1 !== undefined ? row.f1.toFixed(3) : "—"}</td>
              <td className="px-3 py-2 text-right font-mono">{row.rocAuc !== undefined ? row.rocAuc.toFixed(3) : "—"}</td>
              <td className="px-3 py-2 text-right font-mono">{row.m4CoveragePct.toFixed(1)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * "Category/OOV Performance" — where IndicPass performs well and where it
 * does not, preserving the actual nuance of the research rather than a
 * single aggregate "IndicPass beats zxcvbn" headline, which the underlying
 * results do not support. Source:
 * `results/evaluation/evaluation_report.md` §8, `category_metrics.csv`, and
 * `results/reports/reference_attack_hin.md` §3.1 for the per-category
 * Spearman comparison against zxcvbn.
 */
export function CategoryBreakdown() {
  const categoryNames = Object.keys(CATEGORY_SPEARMAN_M4);

  return (
    <Section
      title="Category / OOV Performance"
      description="Accuracy/F1/ROC-AUC are classification metrics at the default budget (M4 ground truth); '—' marks a category where the underlying statistic is undefined (e.g. too few positives)."
    >
      <div className="rounded-lg border bg-surface-muted px-3 py-2.5 text-xs leading-relaxed text-muted">
        This project does <strong className="text-foreground">not</strong> claim IndicPass beats zxcvbn
        everywhere. zxcvbn performs strongly on English (it carries a purpose-built common-password
        wordlist IndicPass does not). Its ordering of bare Romanized Hindi words is weak (Spearman{" "}
        {ZXCVBN_CATEGORY_SPEARMAN_M4.indic_word}). Mixed/Hinglish results are nuanced rather than a clean
        win either way. The out-of-lexicon results are where the character model provides its clearest
        supporting evidence.
      </div>

      <h4 className="mt-4 text-sm font-semibold">By benchmark category</h4>
      <div className="mt-2">
        <BreakdownTable rows={CATEGORY_BREAKDOWN} />
      </div>

      <h4 className="mt-5 text-sm font-semibold">Rank correlation (Spearman &rho;) vs. M4, IndicPass vs. zxcvbn</h4>
      <div className="mt-2 overflow-x-auto rounded-lg border">
        <table className="w-full min-w-[480px] border-collapse text-sm">
          <thead>
            <tr className="border-b bg-surface-muted text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-3 py-2 font-medium">Category</th>
              <th className="px-3 py-2 font-medium text-right">IndicPass (M2)</th>
              <th className="px-3 py-2 font-medium text-right">zxcvbn 4.5.0</th>
            </tr>
          </thead>
          <tbody>
            {categoryNames.map((name) => (
              <tr key={name} className="border-b last:border-b-0">
                <td className="px-3 py-2 font-mono">{name}</td>
                <td className="px-3 py-2 text-right font-mono">{CATEGORY_SPEARMAN_M4[name].toFixed(3)}</td>
                <td className="px-3 py-2 text-right font-mono">{ZXCVBN_CATEGORY_SPEARMAN_M4[name].toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h4 className="mt-5 text-sm font-semibold">By out-of-lexicon partition (dictionary-membership rules, not model-derived)</h4>
      <div className="mt-2">
        <BreakdownTable rows={OOV_PARTITION_BREAKDOWN} />
      </div>

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <ResearchFigure
          src="/research/evaluation-figures/category_comparison.svg"
          alt="F1 by benchmark category, M4 ground truth"
          caption="F1 score at the default budget, by benchmark category, M4 ground truth."
          source="results/evaluation/figures/category_comparison.svg"
        />
        <ResearchFigure
          src="/research/figures/per_category.svg"
          alt="Rank correlation per benchmark partition, M5 attack"
          caption="Spearman rho per partition under the M5 attack. Populations are not comparable with each other — each is conditional on its own coverage and n."
          source="results/figures/per_category.svg"
        />
      </div>
    </Section>
  );
}
