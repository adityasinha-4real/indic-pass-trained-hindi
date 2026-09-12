import type { PcfgBlock } from "@/lib/types";
import { pcfgCategoryLabel } from "@/lib/labels";
import { formatLog10 } from "@/lib/format";

export function PcfgPanel({ pcfg }: { pcfg: PcfgBlock }) {
  return (
    <div className="space-y-3">
      {!pcfg.supported && (
        <p className="rounded-lg border bg-surface-muted px-3 py-2 text-sm text-muted">
          No derivation covers this password &mdash; the grammar has nothing to say
          about it, so the brute-force floor was used instead.
        </p>
      )}

      {pcfg.segments.length > 0 && (
        <ul className="space-y-1.5">
          {pcfg.segments.map((segment, index) => (
            <li
              key={`${segment.start}-${segment.end}-${index}`}
              className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 rounded-lg border bg-background px-3 py-2 text-sm"
            >
              <span>
                <span className="font-medium">{pcfgCategoryLabel(segment.category)}</span>{" "}
                <span className="text-muted">
                  chars {segment.start}&ndash;{segment.end}
                  {segment.category === "word" && segment.rank
                    ? ` · rank ${segment.rank.toLocaleString()}`
                    : segment.category === "word"
                      ? ` · ${segment.tier ?? "unranked"} tier`
                      : null}
                </span>
              </span>
              <span className="font-mono text-xs text-muted">
                log&#8321;&#8320; P {segment.log10_probability.toFixed(2)}
              </span>
            </li>
          ))}
        </ul>
      )}

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-4">
        <Stat label="log10 P(password)" value={formatLog10(pcfg.log10_probability)} />
        <Stat label="grammar guesses" value={`${formatLog10(pcfg.grammar_log10_guesses)} log10`} />
        <Stat
          label="brute force"
          value={`${formatLog10(pcfg.bruteforce_log10_guesses)} log10`}
        />
        <Stat
          label="reported"
          value={`${formatLog10(pcfg.log10_guesses)} log10${pcfg.floor_applied ? " (floor)" : ""}`}
        />
      </dl>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="font-mono">{value}</dd>
    </div>
  );
}
