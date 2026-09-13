import { DICTIONARY_SCALE, DICTIONARY_COVERAGE, ZXCVBN_CONTAMINATION } from "@/lib/research-data";
import { Section } from "../Section";

/**
 * "Dataset & Dictionary" — methodological transparency, not a performance
 * metric. Deliberately keeps three things visually separate: how big the
 * dictionary is, how much of a real-usage word bank it actually covers, and
 * a documented control/contamination finding about the baseline it's
 * compared against. Source: `results/reports/indicdict_coverage_hin.md`.
 */
export function DictionaryCoverage() {
  return (
    <Section
      title="Dataset & Dictionary"
      description="Dataset scale, coverage limitation, and a control/contamination finding — kept separate because conflating them would overstate or understate different things."
    >
      <h4 className="text-sm font-semibold">Dataset scale</h4>
      <div className="mt-2 overflow-x-auto rounded-lg border">
        <table className="w-full min-w-[480px] border-collapse text-sm">
          <thead>
            <tr className="border-b bg-surface-muted text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-3 py-2 font-medium">Provenance tier</th>
              <th className="px-3 py-2 font-medium text-right">Entries</th>
              <th className="px-3 py-2 font-medium text-right">Frequency-ranked</th>
              <th className="px-3 py-2 font-medium text-right">Fallback-priced</th>
            </tr>
          </thead>
          <tbody>
            {DICTIONARY_SCALE.tiers.map((tier) => (
              <tr key={tier.name} className="border-b last:border-b-0">
                <td className="px-3 py-2 font-mono">{tier.name}</td>
                <td className="px-3 py-2 text-right font-mono">{tier.entries.toLocaleString()}</td>
                <td className="px-3 py-2 text-right font-mono">{tier.ranked.toLocaleString()}</td>
                <td className="px-3 py-2 text-right font-mono">{tier.unranked.toLocaleString()}</td>
              </tr>
            ))}
            <tr className="bg-surface-muted font-medium">
              <td className="px-3 py-2">total</td>
              <td className="px-3 py-2 text-right font-mono">{DICTIONARY_SCALE.totalEntries.toLocaleString()}</td>
              <td className="px-3 py-2 text-right font-mono">{DICTIONARY_SCALE.frequencyRankedEntries.toLocaleString()}</td>
              <td className="px-3 py-2 text-right font-mono">
                {(DICTIONARY_SCALE.totalEntries - DICTIONARY_SCALE.frequencyRankedEntries).toLocaleString()}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-muted">
        {DICTIONARY_SCALE.frequencyCoveragePct}% of the dictionary has an observed corpus frequency (
        <code className="font-mono">{DICTIONARY_SCALE.frequencySource}</code>) and is priced by measured
        rank; the rest falls back to its provenance tier&rsquo;s offset.
      </p>

      <h4 className="mt-6 text-sm font-semibold">Coverage limitation</h4>
      <div className="mt-2 grid gap-3 sm:grid-cols-3">
        <CoverageStat label="Full probe bank (163 Hindi words)" pct={DICTIONARY_COVERAGE.fullBank.coveragePct} detail={`${DICTIONARY_COVERAGE.fullBank.present} present / ${DICTIONARY_COVERAGE.fullBank.absent} absent`} />
        <CoverageStat label="Core brief (15 words)" pct={DICTIONARY_COVERAGE.coreBrief.coveragePct} detail={`${DICTIONARY_COVERAGE.coreBrief.present} present / ${DICTIONARY_COVERAGE.coreBrief.absent} absent`} />
        <CoverageStat label="English controls (10 words)" pct={DICTIONARY_COVERAGE.englishControls.coveragePct} detail={`${DICTIONARY_COVERAGE.englishControls.present} present / ${DICTIONARY_COVERAGE.englishControls.absent} absent`} />
      </div>
      <p className="mt-3 text-xs leading-relaxed text-muted">
        Coverage is the ceiling on everything the guess model can do. Missing words include some of the
        most common in the language:{" "}
        {DICTIONARY_COVERAGE.missingCommonWords.map((w) => (
          <code key={w} className="mr-1 font-mono text-foreground">{w}</code>
        ))}
        . Any Indic-category result on this dashboard should be read against this table first.
      </p>

      <h4 className="mt-6 text-sm font-semibold">Control / contamination finding</h4>
      <p className="mt-2 text-xs leading-relaxed text-muted">{DICTIONARY_COVERAGE.contaminationNote}</p>
      <p className="mt-2 text-xs leading-relaxed text-muted">
        Separately, zxcvbn&rsquo;s own bundled English wordlists already resolve{" "}
        {ZXCVBN_CONTAMINATION.wordsZxcvbnAlreadyKnows.map((w, i) => (
          <span key={w}>
            <code className="font-mono text-foreground">{w}</code>
            {i < ZXCVBN_CONTAMINATION.wordsZxcvbnAlreadyKnows.length - 1 ? ", " : " "}
          </span>
        ))}
        as dictionary matches. &ldquo;Indic word&rdquo; does not mean &ldquo;invisible to zxcvbn&rdquo;.
      </p>
      <p className="mt-3 text-[11px] text-muted">
        Sources: <code className="font-mono">{DICTIONARY_SCALE.source}</code>,{" "}
        <code className="font-mono">{ZXCVBN_CONTAMINATION.source}</code>
      </p>
    </Section>
  );
}

function CoverageStat({ label, pct, detail }: { label: string; pct: number; detail: string }) {
  return (
    <div className="rounded-lg border bg-background p-3 text-center">
      <div className="font-mono text-2xl font-semibold">{pct.toFixed(1)}%</div>
      <div className="mt-1 text-xs font-medium">{label}</div>
      <div className="text-[11px] text-muted">{detail}</div>
    </div>
  );
}
