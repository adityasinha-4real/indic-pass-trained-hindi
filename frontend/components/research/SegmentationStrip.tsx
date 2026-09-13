import type { Match } from "@/lib/types";
import { patternLabel, patternColor } from "@/lib/labels";

/**
 * A visual strip of the winning segmentation IndicPass found for this
 * password — the same `matched_patterns[]` array `MatchList` already
 * renders as text, laid out left-to-right in character order instead.
 *
 * Answers "what did IndicPass actually see inside this password?" without
 * introducing any new classifier: every span and its label come from the
 * matcher/segmentation search that already ran for `EstimatorTable` /
 * `MatchList` above.
 *
 * Privacy: identical to the rest of the app. When `reveal_tokens` was off,
 * `match.token` is absent, so this renders the pattern kind and length only
 * — never a guessed-at reconstruction of the characters.
 */
export function SegmentationStrip({ matches, passwordLength }: { matches: Match[]; passwordLength: number }) {
  if (matches.length === 0) return null;

  const ordered = [...matches].sort((a, b) => a.start - b.start);

  return (
    <div className="space-y-2">
      <div className="flex w-full overflow-hidden rounded-lg border" style={{ minHeight: "2.75rem" }}>
        {ordered.map((match, index) => {
          const widthPct = (match.length / Math.max(1, passwordLength)) * 100;
          const kind =
            match.pattern === "indic_word" && match.is_named_entity ? "Name" : patternLabel(match.pattern);
          return (
            <div
              key={`${match.start}-${match.end}-${index}`}
              className="flex flex-col items-center justify-center border-r px-1 py-1.5 text-center last:border-r-0"
              style={{ width: `${widthPct}%`, backgroundColor: `${patternColor(match.pattern)}1a` }}
              title={`${kind}, characters ${match.start}–${match.end}`}
            >
              {match.token ? (
                <span className="truncate font-mono text-xs font-medium">{match.token}</span>
              ) : (
                <span className="truncate text-[10px] font-medium" style={{ color: patternColor(match.pattern) }}>
                  {kind}
                </span>
              )}
              <span className="truncate text-[10px] text-muted">{match.length}ch</span>
            </div>
          );
        })}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
        {Array.from(new Set(ordered.map((m) => m.pattern))).map((pattern) => (
          <span key={pattern} className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ backgroundColor: patternColor(pattern) }}
            />
            {patternLabel(pattern)}
          </span>
        ))}
      </div>
    </div>
  );
}
