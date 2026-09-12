import type { ReactNode } from "react";

const CAPABILITIES: Array<{ capability: string; conventional: boolean | "varies"; indicpass: boolean }> = [
  { capability: "Generic password patterns (digits, years, symbol runs, repeats)", conventional: true, indicpass: true },
  { capability: "Romanized-Indic dictionary awareness", conventional: false, indicpass: true },
  { capability: "Transliteration-aware matching (Devanagari rendering of a hit)", conventional: false, indicpass: true },
  { capability: "Probabilistic grammar (PCFG) over password structure", conventional: "varies", indicpass: true },
  { capability: "Scored against an independent, bounded reference attack", conventional: false, indicpass: true },
];

export function ResearchNotes() {
  return (
    <section className="space-y-5">
      <div className="rounded-xl border bg-surface p-5 sm:p-6">
        <h2 className="text-sm font-semibold">Conventional estimators vs. IndicPass</h2>
        <p className="mt-1 text-xs text-muted">
          zxcvbn (bundled with this project as the baseline every result above is
          compared against) is not being criticised for failing at something it was
          not built for &mdash; it is the measurement of what a widely deployed
          generic meter does with Romanized-Indic input.
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
        <h2 className="text-sm font-semibold">What the project&rsquo;s own evaluation found</h2>
        <p className="mt-1 text-xs text-muted">
          Measured on this project&rsquo;s benchmark corpus and two independent bounded
          reference attacks &mdash; not recomputed for the password above. Full detail:{" "}
          <code className="font-mono">docs/password_strength_design.md</code> and{" "}
          <code className="font-mono">results/reports/</code>.
        </p>
        <ul className="mt-4 space-y-3 text-sm">
          <Finding>
            Against a bounded wordlist attack whose rank is observed rather than
            estimated, IndicPass&rsquo;s guess number correlates with the actual attack
            order at Spearman <strong>0.900</strong>, vs. <strong>0.592</strong> for
            zxcvbn &mdash; and zxcvbn&rsquo;s correlation on bare Romanized Hindi words
            alone is <strong>0.005</strong>, essentially no information.{" "}
            <span className="text-muted">(Milestone 4, reference_attack_hin.md)</span>
          </Finding>
          <Finding>
            A character-model attack that can reach spellings the dictionary has
            never seen reaches an unseen Hindi word <strong>6.49 orders of
            magnitude</strong> earlier than a random string of the same length &mdash;
            confirming the PCFG&rsquo;s out-of-lexicon mechanism independently.{" "}
            <span className="text-muted">(Milestone 5, milestone5_oov_attack.md)</span>
          </Finding>
          <Finding>
            The Indic lexicon alone lowers IndicPass&rsquo;s estimate on Indic-category
            passwords by <strong>0.79 to 0.93 log10</strong> guesses while leaving
            random controls unchanged (0.00 log10) &mdash; the effect is specific to
            Indic content, not a general loosening of the model.{" "}
            <span className="text-muted">(password_benchmark_hin.md)</span>
          </Finding>
          <Finding>
            IndicPass alone does not beat zxcvbn on English passwords, because it
            carries no common-password wordlist. The deployable object is{" "}
            <code className="font-mono">min(IndicPass, zxcvbn)</code> &mdash; the
            &ldquo;against every model above&rdquo; figure shown for the password you
            analyze.
          </Finding>
        </ul>
        <p className="mt-4 text-xs text-muted">
          The benchmark corpus is synthetic &mdash; 1,400 generated passwords, not
          observed ones &mdash; and these are two fully specified reference attacks,
          not a real cracking run against leaked data. No claim here is validated
          against real-world password distributions.
        </p>
      </div>
    </section>
  );
}

function Finding({ children }: { children: ReactNode }) {
  return (
    <li className="rounded-lg border bg-background px-3 py-2.5 leading-relaxed">{children}</li>
  );
}

function renderMark(value: boolean | "varies") {
  if (value === true) return <span className="text-emerald-600 dark:text-emerald-400">&#10003;</span>;
  if (value === "varies") return <span className="text-muted">varies</span>;
  return <span className="text-muted">&mdash;</span>;
}
