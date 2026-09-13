import {
  CLASSIFICATION_M4,
  CLASSIFICATION_M5,
  CONFUSION_MATRIX_M4_INDICPASS,
  BASELINE_DELTA,
  CLASSIFICATION_BOOTSTRAP,
  EVAL_DEFAULT_BUDGET,
  EVAL_SOURCE,
} from "@/lib/research-data";
import { Section } from "../Section";
import { ResearchFigure } from "./ResearchFigure";

function ClassificationTable({ rows }: { rows: typeof CLASSIFICATION_M4 }) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full min-w-[720px] border-collapse text-sm">
        <thead>
          <tr className="border-b bg-surface-muted text-left text-xs uppercase tracking-wide text-muted">
            <th className="px-3 py-2 font-medium">Estimator</th>
            <th className="px-3 py-2 font-medium text-right">Accuracy</th>
            <th className="px-3 py-2 font-medium text-right">Precision</th>
            <th className="px-3 py-2 font-medium text-right">Recall</th>
            <th className="px-3 py-2 font-medium text-right">F1</th>
            <th className="px-3 py-2 font-medium text-right">Bal. acc.</th>
            <th className="px-3 py-2 font-medium text-right">MCC</th>
            <th className="px-3 py-2 font-medium text-right">ROC-AUC</th>
            <th className="px-3 py-2 font-medium text-right">PR-AUC</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.estimator} className="border-b last:border-b-0">
              <td className="px-3 py-2 font-medium">{row.estimator}</td>
              <td className="px-3 py-2 text-right font-mono">{row.accuracy.toFixed(3)}</td>
              <td className="px-3 py-2 text-right font-mono">{row.precision.toFixed(3)}</td>
              <td className="px-3 py-2 text-right font-mono">{row.recall.toFixed(3)}</td>
              <td className="px-3 py-2 text-right font-mono">{row.f1.toFixed(3)}</td>
              <td className="px-3 py-2 text-right font-mono">{row.balancedAccuracy.toFixed(3)}</td>
              <td className="px-3 py-2 text-right font-mono">{row.mcc.toFixed(3)}</td>
              <td className="px-3 py-2 text-right font-mono">{row.rocAuc.toFixed(3)}</td>
              <td className="px-3 py-2 text-right font-mono">{row.prAuc.toFixed(3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * "Classifier Evaluation" — treats "crackable within a fixed guess budget"
 * as a binary label and reports the standard classifier vocabulary a
 * reviewer will expect (accuracy/F1/ROC-AUC/confusion matrix). Every number
 * here comes from `results/evaluation/metrics.json` /
 * `evaluation_report.md`, produced by the (functionally complete, not yet
 * committed — see the Provenance note at the foot of the dashboard)
 * evaluation layer on top of M2-M5's own unchanged outputs. No metric here
 * is recomputed with a different methodology, and none is invented.
 */
export function ClassifierEvaluation() {
  return (
    <Section
      title="Classifier Evaluation"
      description={`"Crackable within a fixed guess budget" treated as a binary label, at the default budget of ${EVAL_DEFAULT_BUDGET} — one of config/password.yaml's own pre-existing strength thresholds, not tuned on this data.`}
    >
      <h4 className="text-sm font-semibold">Ground truth: M4 (wordlist attack)</h4>
      <div className="mt-2">
        <ClassificationTable rows={CLASSIFICATION_M4} />
      </div>

      <h4 className="mt-5 text-sm font-semibold">Ground truth: M5 (character-model attack)</h4>
      <div className="mt-2">
        <ClassificationTable rows={CLASSIFICATION_M5} />
      </div>

      <div className="mt-5 rounded-lg border bg-background p-4 text-sm">
        <p className="font-medium">IndicPass confusion matrix, ground truth M4, budget {EVAL_DEFAULT_BUDGET}</p>
        <div className="mt-2 grid grid-cols-2 gap-2 text-center text-xs sm:w-80">
          <div className="rounded border bg-surface-muted px-2 py-3">
            <div className="font-mono text-lg font-semibold">{CONFUSION_MATRIX_M4_INDICPASS.truePositive}</div>
            <div className="text-muted">true positive</div>
          </div>
          <div className="rounded border bg-surface-muted px-2 py-3">
            <div className="font-mono text-lg font-semibold">{CONFUSION_MATRIX_M4_INDICPASS.falseNegative}</div>
            <div className="text-muted">false negative</div>
          </div>
          <div className="rounded border bg-surface-muted px-2 py-3">
            <div className="font-mono text-lg font-semibold">{CONFUSION_MATRIX_M4_INDICPASS.falsePositive}</div>
            <div className="text-muted">false positive</div>
          </div>
          <div className="rounded border bg-surface-muted px-2 py-3">
            <div className="font-mono text-lg font-semibold">{CONFUSION_MATRIX_M4_INDICPASS.trueNegative}</div>
            <div className="text-muted">true negative</div>
          </div>
        </div>
        <p className="mt-2 text-xs text-muted">
          &ldquo;Positive&rdquo; = IndicPass estimates &le; {EVAL_DEFAULT_BUDGET}; &ldquo;actual
          crackable&rdquo; = M4 reached it within that budget. n = {CONFUSION_MATRIX_M4_INDICPASS.n}.
          IndicPass never misses a password M4 actually cracked at this budget (0 false negatives) — the
          cost is a high false-positive rate, i.e. it calls many passwords crackable that this particular
          bounded attack does not reach.
        </p>
      </div>

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <ResearchFigure
          src="/research/evaluation-figures/roc.svg"
          alt="ROC curve, crackable within budget, M4 ground truth"
          caption="IndicPass vs. PCFG vs. zxcvbn, M4 ground truth, default budget."
          source="results/evaluation/figures/roc.svg"
        />
        <ResearchFigure
          src="/research/evaluation-figures/precision_recall.svg"
          alt="Precision-recall curve, crackable within budget, M4 ground truth"
          caption="Same comparison, precision-recall space — more informative than ROC when positives (crackable passwords) are the minority class."
          source="results/evaluation/figures/precision_recall.svg"
        />
        <ResearchFigure
          src="/research/evaluation-figures/confusion_matrix.svg"
          alt="IndicPass confusion matrix, M4 ground truth"
          caption="The same four counts tabulated above, rendered as a grid."
          source="results/evaluation/figures/confusion_matrix.svg"
        />
        <ResearchFigure
          src="/research/evaluation-figures/baseline_comparison.svg"
          alt="IndicPass / PCFG / zxcvbn accuracy and related metrics compared"
          caption="Same records, same attacker (M4), same budget, across estimators."
          source="results/evaluation/figures/baseline_comparison.svg"
        />
      </div>

      <div className="mt-5 rounded-lg border bg-background p-4 text-sm">
        <p className="font-medium">IndicPass &minus; zxcvbn, same records, same attacker (M4), same budget</p>
        <div className="mt-2 grid grid-cols-3 gap-2 text-xs sm:grid-cols-6">
          <Delta label="accuracy" value={BASELINE_DELTA.accuracy} />
          <Delta label="precision" value={BASELINE_DELTA.precision} />
          <Delta label="recall" value={BASELINE_DELTA.recall} />
          <Delta label="F1" value={BASELINE_DELTA.f1} />
          <Delta label="ROC-AUC" value={BASELINE_DELTA.rocAuc} />
          <Delta label="PR-AUC" value={BASELINE_DELTA.prAuc} />
        </div>
        <p className="mt-3 text-xs text-muted">Source: {BASELINE_DELTA.source}</p>
      </div>

      <div className="mt-5">
        <p className="text-sm font-medium">Paired bootstrap on the differences above</p>
        <p className="mt-1 text-xs text-muted">
          1,000-resample percentile bootstrap, 95% CI, ground truth M4, default budget. An interval
          excluding zero is reported as such — it is not a significance test.
        </p>
        <div className="mt-2 overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[520px] border-collapse text-sm">
            <thead>
              <tr className="border-b bg-surface-muted text-left text-xs uppercase tracking-wide text-muted">
                <th className="px-3 py-2 font-medium">Comparison</th>
                <th className="px-3 py-2 font-medium">Statistic</th>
                <th className="px-3 py-2 font-medium text-right">Value</th>
                <th className="px-3 py-2 font-medium text-right">95% CI</th>
                <th className="px-3 py-2 font-medium text-right">Excludes 0</th>
              </tr>
            </thead>
            <tbody>
              {CLASSIFICATION_BOOTSTRAP.map((row, i) => (
                <tr key={`${row.comparison}-${row.statistic}-${i}`} className="border-b last:border-b-0">
                  <td className="px-3 py-2">{row.comparison}</td>
                  <td className="px-3 py-2">{row.statistic}</td>
                  <td className="px-3 py-2 text-right font-mono">{row.value >= 0 ? "+" : ""}{row.value.toFixed(3)}</td>
                  <td className="px-3 py-2 text-right font-mono">[{row.ciLow.toFixed(3)}, {row.ciHigh.toFixed(3)}]</td>
                  <td className="px-3 py-2 text-right">{row.excludesZero ? "yes" : "no"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <p className="mt-4 text-xs text-muted">Source: {EVAL_SOURCE}</p>
    </Section>
  );
}

function Delta({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border bg-surface-muted px-2 py-2 text-center">
      <div className="font-mono text-sm font-semibold text-emerald-700 dark:text-emerald-400">
        {value >= 0 ? "+" : ""}
        {value.toFixed(3)}
      </div>
      <div className="text-[11px] text-muted">{label}</div>
    </div>
  );
}
