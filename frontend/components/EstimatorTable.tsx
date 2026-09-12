import type { AnalyzeResponse } from "@/lib/types";
import { getBaselineBlock } from "@/lib/api";
import { formatGuesses, formatLog10 } from "@/lib/format";

interface Row {
  name: string;
  note: string;
  guesses: number;
  log10: number;
  score?: number;
  label?: string;
  highlight?: boolean;
}

export function EstimatorTable({ result }: { result: AnalyzeResponse }) {
  const rows: Row[] = [
    {
      name: "IndicPass (M2)",
      note: "the primary estimator — Indic-aware dictionary + structural guess model",
      guesses: result.indicpass.guesses,
      log10: result.indicpass.log10_guesses,
      score: result.indicpass.score,
      label: result.indicpass.label,
      highlight: true,
    },
  ];

  const baseline = getBaselineBlock(result);
  if (baseline && result.estimators.baseline) {
    rows.push({
      name: result.estimators.baseline,
      note: "generic estimator, no Indic-language awareness — the comparison point",
      guesses: baseline.guesses,
      log10: baseline.log10_guesses,
      score: baseline.score,
    });
  }

  if (result.pcfg) {
    rows.push({
      name: "PCFG (M3)",
      note: "probabilistic grammar over password structure — reported alongside, not instead of",
      guesses: result.pcfg.guesses,
      log10: result.pcfg.log10_guesses,
      score: result.pcfg.score,
      label: result.pcfg.label,
    });
  }

  return (
    <div>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full min-w-[520px] border-collapse text-sm">
          <thead>
            <tr className="border-b bg-surface-muted text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-3 py-2 font-medium">Estimator</th>
              <th className="px-3 py-2 font-medium">Guesses</th>
              <th className="px-3 py-2 font-medium">log&#8321;&#8320; guesses</th>
              <th className="px-3 py-2 font-medium">0&ndash;4 score</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.name} className="border-b last:border-b-0">
                <td className="px-3 py-2.5 align-top">
                  <div className="font-medium">{row.name}</div>
                  <div className="text-xs text-muted">{row.note}</div>
                </td>
                <td className="px-3 py-2.5 align-top font-mono">{formatGuesses(row.guesses)}</td>
                <td className="px-3 py-2.5 align-top font-mono">{formatLog10(row.log10)}</td>
                <td className="px-3 py-2.5 align-top">
                  {row.score !== undefined ? `${row.score} / 4${row.label ? ` (${row.label})` : ""}` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {result.combined_log10_guesses !== undefined && (
        <p className="mt-3 text-sm text-muted">
          <span className="font-medium text-foreground">
            Against an attacker holding every model above:
          </span>{" "}
          {formatLog10(result.combined_log10_guesses)} log&#8321;&#8320; guesses (
          {formatGuesses(10 ** result.combined_log10_guesses)}). Guessing cost is a
          minimum over the attacker&rsquo;s options, so this — not any single row — is
          the number that describes the password.
        </p>
      )}
    </div>
  );
}
