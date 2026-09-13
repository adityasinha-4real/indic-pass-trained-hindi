import { CORE_CLAIM, CORE_CLAIM_SOURCE } from "@/lib/research-data";

const CAPABILITIES: Array<{ capability: string; conventional: boolean | "varies"; indicpass: boolean }> = [
  { capability: "Generic password patterns (digits, years, symbol runs, repeats)", conventional: true, indicpass: true },
  { capability: "Romanized-Indic dictionary awareness", conventional: false, indicpass: true },
  { capability: "Provenance-tiered vocabulary (human-romanized / curated / mined)", conventional: false, indicpass: true },
  { capability: "Transliteration-aware matching (Devanagari rendering of a hit)", conventional: false, indicpass: true },
  { capability: "Probabilistic grammar (PCFG) with a character model for unseen spellings", conventional: "varies", indicpass: true },
  { capability: "Out-of-lexicon (OOV) handling via a character-shape model", conventional: false, indicpass: true },
  { capability: "Scored against independent, bounded reference attacks", conventional: false, indicpass: true },
];

/**
 * "Why IndicPass?" — replaces the previous static ResearchNotes component.
 * Concise by design: this section states the project's own claim and points
 * at the sections below (Representative Cases, Independent Validation, OOV
 * / Generalization, Classifier Evaluation) where the evidence for it lives,
 * rather than repeating that evidence as unlinked prose.
 */
export function ResearchNotes() {
  return (
    <section className="space-y-5">
      <div className="rounded-xl border bg-surface p-5 sm:p-6">
        <h2 className="text-sm font-semibold">Why IndicPass?</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          Password meters built and measured on English miss Romanized-Indic vocabulary entirely — a
          generic wordlist has never seen <code className="font-mono text-foreground">bharat</code>,{" "}
          <code className="font-mono text-foreground">mera</code>, or{" "}
          <code className="font-mono text-foreground">krishna</code> as words, only as unstructured
          characters. IndicPass prices a password against a 297,747-entry Romanized-Hindi dictionary,
          split into four provenance tiers, ranked by measured corpus frequency where one is available.
          On top of that, a probabilistic grammar (PCFG) with a character-level model prices spellings
          the dictionary has never seen at all — the out-of-lexicon (OOV) case an English wordlist has
          no path to recognising.
        </p>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          None of this is asserted on its own. Every estimator here is also scored against{" "}
          <strong className="text-foreground">two independent, bounded reference attacks</strong> whose
          rank is observed by inversion rather than estimated — a wordlist-and-rules attack (M4) and a
          character-model attack that can reach unseen spellings (M5). See{" "}
          <span className="font-medium text-foreground">Independent Validation</span> below for what
          that comparison found.
        </p>
        <blockquote className="mt-4 rounded-lg border-l-4 border-accent bg-background px-4 py-3 text-sm italic leading-relaxed">
          &ldquo;{CORE_CLAIM}&rdquo;
        </blockquote>
        <p className="mt-1 text-xs text-muted">
          The project&rsquo;s own stated claim, quoted verbatim &mdash; <code className="font-mono">{CORE_CLAIM_SOURCE}</code>.
          Everything below is either evidence for it, a bound on it, or a statement of what it does not license.
        </p>
      </div>

      <div className="rounded-xl border bg-surface p-5 sm:p-6">
        <h2 className="text-sm font-semibold">Conventional estimators vs. IndicPass</h2>
        <p className="mt-1 text-xs text-muted">
          zxcvbn (bundled with this project as the baseline every result above is compared against) is
          not being criticised for failing at something it was not built for &mdash; it is the
          measurement of what a widely deployed generic meter does with Romanized-Indic input.
        </p>
        <div className="mt-4 overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[480px] border-collapse text-sm">
            <thead>
              <tr className="border-b bg-surface-muted text-left text-xs uppercase tracking-wide text-muted">
                <th className="px-3 py-2 font-medium">Capability</th>
                <th className="px-3 py-2 font-medium">Conventional estimator</th>
                <th className="px-3 py-2 font-medium">IndicPass</th>
              </tr>
            </thead>
            <tbody>
              {CAPABILITIES.map((row) => (
                <tr key={row.capability} className="border-b last:border-b-0">
                  <td className="px-3 py-2.5">{row.capability}</td>
                  <td className="px-3 py-2.5 text-center">{renderMark(row.conventional)}</td>
                  <td className="px-3 py-2.5 text-center">{renderMark(row.indicpass)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="rounded-xl border bg-surface p-5 sm:p-6">
        <h2 className="text-sm font-semibold">How this was evaluated</h2>
        <p className="mt-1 text-xs text-muted">
          A short map of the pipeline below, from a live password to the validation sections further
          down this page.
        </p>
        <MethodologyFlow />
      </div>
    </section>
  );
}

const FLOW_STEPS = [
  "Live password",
  "IndicPass / zxcvbn / PCFG estimate it",
  "Estimated strength (shown above)",
  "Independent reference attacks rank the same 1,400-sample benchmark (M4, M5)",
  "Ranking, error and calibration against those observed ranks",
  "Classification and attack-budget evaluation at a fixed guess budget",
];

function MethodologyFlow() {
  return (
    <ol className="mt-4 space-y-0 text-sm">
      {FLOW_STEPS.map((step, index) => (
        <li key={step} className="flex items-start gap-3">
          <div className="flex flex-col items-center">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border bg-background text-xs font-medium">
              {index + 1}
            </span>
            {index < FLOW_STEPS.length - 1 && <span className="h-6 w-px bg-border" />}
          </div>
          <span className="pb-4 pt-0.5 leading-snug">{step}</span>
        </li>
      ))}
    </ol>
  );
}

function renderMark(value: boolean | "varies") {
  if (value === true) return <span className="text-emerald-600 dark:text-emerald-400">&#10003;</span>;
  if (value === "varies") return <span className="text-muted">varies</span>;
  return <span className="text-muted">&mdash;</span>;
}
