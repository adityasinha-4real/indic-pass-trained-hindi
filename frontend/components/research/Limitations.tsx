import { LIMITATIONS, EVAL_PROVENANCE } from "@/lib/research-data";
import { Section } from "../Section";

/**
 * "Limitations" — restated plainly from the project's own documentation.
 * The intent (per the project's own design doc) is that this increases
 * credibility rather than reading as an apology: every claim elsewhere on
 * this page is bounded by something in this list.
 */
export function Limitations() {
  return (
    <Section title="Limitations">
      <ul className="space-y-2.5 text-sm">
        {LIMITATIONS.map((item, index) => (
          <li key={index} className="flex gap-2.5">
            <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-muted" />
            <span className="leading-relaxed text-muted">{item}</span>
          </li>
        ))}
      </ul>
      <div className="mt-5 rounded-lg border bg-surface-muted px-3 py-2.5 text-xs leading-relaxed text-muted">
        <strong className="text-foreground">On the classifier-evaluation numbers specifically:</strong>{" "}
        {EVAL_PROVENANCE.note} (generated {EVAL_PROVENANCE.generatedAt} from commit{" "}
        <code className="font-mono">{EVAL_PROVENANCE.gitCommit}</code>).
      </div>
    </Section>
  );
}
