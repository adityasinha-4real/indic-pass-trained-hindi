import { REPRODUCIBILITY } from "@/lib/research-data";
import { Section } from "../Section";

/** "Reproducibility" — a compact research-rigor card. Source: results/reports/reproducibility.md */
export function Reproducibility() {
  return (
    <Section title="Reproducibility">
      <div className="flex flex-col items-start gap-4 sm:flex-row sm:items-center">
        <div className="shrink-0 rounded-lg border bg-background px-5 py-4 text-center">
          <div className="font-mono text-3xl font-semibold text-emerald-600 dark:text-emerald-400">
            {REPRODUCIBILITY.identicalReports}/{REPRODUCIBILITY.totalReports}
          </div>
          <div className="text-xs text-muted">byte-identical reports</div>
        </div>
        <p className="text-sm leading-relaxed text-muted">
          {REPRODUCIBILITY.method} All experiments use a fixed seed ({REPRODUCIBILITY.seed}). Reproduce
          with <code className="font-mono">python scripts/verify_reproducibility.py --languages hin</code>.
        </p>
      </div>
      <div className="mt-4 overflow-x-auto rounded-lg border">
        <table className="w-full min-w-[360px] border-collapse text-sm">
          <thead>
            <tr className="border-b bg-surface-muted text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-3 py-2 font-medium">Experiment</th>
              <th className="px-3 py-2 font-medium text-right">Wall clock (two runs)</th>
            </tr>
          </thead>
          <tbody>
            {REPRODUCIBILITY.experiments.map((exp) => (
              <tr key={exp.name} className="border-b last:border-b-0">
                <td className="px-3 py-2 font-mono">{exp.name}</td>
                <td className="px-3 py-2 text-right font-mono">{exp.wallClockSeconds}s</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-muted">
        Source: <code className="font-mono">{REPRODUCIBILITY.source}</code>
      </p>
    </Section>
  );
}
