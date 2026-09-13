import { CASE_STUDIES, CASE_STUDY_SOURCE } from "@/lib/research-data";
import { Section } from "../Section";

/**
 * Concrete worked examples, transcribed from the project's own documented
 * examples (docs/password_strength_design.md §5.3, §4.3) rather than
 * re-computed for this dashboard — these are fixed illustrations of how the
 * live analyzer above already prices exactly these passwords, not a new
 * evaluation.
 */
export function CaseStudies() {
  return (
    <Section
      title="Representative cases"
      description="Worked examples from the project's own documentation — try any of these in the analyzer above to see the live numbers for yourself."
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {CASE_STUDIES.map((study) => (
          <article key={study.password} className="rounded-lg border bg-background p-4 text-sm">
            <div className="flex items-baseline justify-between gap-2">
              <code className="font-mono text-base font-semibold">{study.password}</code>
              <span className="shrink-0 rounded bg-surface-muted px-2 py-0.5 text-xs font-medium">
                score {study.score}/4
              </span>
            </div>
            <p className="mt-1.5 text-xs text-muted">{study.structure}</p>
            <p className="mt-2 font-mono text-sm">
              IndicPass: {study.indicpassGuesses} guesses ({study.indicpassLog10.toFixed(2)} log10)
            </p>
            {study.zxcvbnNote && <p className="mt-0.5 font-mono text-xs text-muted">{study.zxcvbnNote}</p>}
            <p className="mt-2 text-xs leading-relaxed text-muted">{study.significance}</p>
          </article>
        ))}
      </div>
      <p className="mt-4 text-xs text-muted">
        Source: <code className="font-mono">{CASE_STUDY_SOURCE}</code>
      </p>
    </Section>
  );
}
