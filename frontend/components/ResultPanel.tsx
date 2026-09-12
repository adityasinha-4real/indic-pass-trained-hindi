import type { AnalyzeResponse } from "@/lib/types";
import { formatGuesses } from "@/lib/format";
import { StrengthMeter } from "./StrengthMeter";
import { EstimatorTable } from "./EstimatorTable";
import { MatchList } from "./MatchList";
import { PcfgPanel } from "./PcfgPanel";
import { DictionaryPanel } from "./DictionaryPanel";
import { Section } from "./Section";

export function ResultPanel({ result }: { result: AnalyzeResponse }) {
  return (
    <div className="space-y-5">
      <Section title="Strength">
        <StrengthMeter score={result.strength_score} label={result.strength_label} />
        <div className="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-3">
          <Stat label="Length" value={`${result.password_length} characters`} />
          <Stat label="Estimated guesses" value={formatGuesses(result.guess_number)} />
          <Stat label="log10 guesses" value={result.log10_guesses.toFixed(2)} />
        </div>
      </Section>

      <Section
        title="Attack analysis"
        description="Every estimator this run has configured, scored on this password in one call."
      >
        <EstimatorTable result={result} />
      </Section>

      <Section
        title="Structural findings"
        description="What the winning segmentation found in this password."
      >
        <MatchList matches={result.matched_patterns} />
      </Section>

      {result.warnings.length > 0 && (
        <Section title="Findings">
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
            {result.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </Section>
      )}

      {result.pcfg && (
        <Section
          title="PCFG derivation (Milestone 3)"
          description="A probability model over password structure, reported alongside the estimator above — it does not replace it."
        >
          <PcfgPanel pcfg={result.pcfg} />
        </Section>
      )}

      <Section
        title="Dictionaries used"
        description="Provenance for the numbers above: which IndicDict build produced them."
      >
        <DictionaryPanel dictionaries={result.dictionaries} />
      </Section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-muted">{label}</div>
      <div className="font-mono text-sm">{value}</div>
    </div>
  );
}
