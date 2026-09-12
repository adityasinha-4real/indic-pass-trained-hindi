import type { Match } from "@/lib/types";
import { patternLabel } from "@/lib/labels";
import { formatGuesses } from "@/lib/format";

export function MatchList({ matches }: { matches: Match[] }) {
  if (matches.length === 0) {
    return <p className="text-sm text-muted">No structure was recognised in this password.</p>;
  }

  const indic = matches.filter((m) => m.pattern === "indic_word");
  const other = matches.filter((m) => m.pattern !== "indic_word");

  return (
    <div className="space-y-4">
      {indic.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-xs font-medium uppercase tracking-wide text-muted">
            Indic dictionary matches
          </h4>
          {indic.map((match, index) => (
            <IndicMatchCard key={`${match.start}-${match.end}-${index}`} match={match} />
          ))}
        </div>
      )}

      {other.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-xs font-medium uppercase tracking-wide text-muted">
            Other components
          </h4>
          <ul className="space-y-1.5">
            {other.map((match, index) => (
              <li
                key={`${match.start}-${match.end}-${index}`}
                className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 rounded-lg border bg-background px-3 py-2 text-sm"
              >
                <span>
                  <span className="font-medium">{patternLabel(match.pattern)}</span>{" "}
                  <span className="text-muted">
                    chars {match.start}&ndash;{match.end} ({match.length} chars)
                    {match.token ? <> &mdash; <code className="font-mono">{match.token}</code></> : null}
                  </span>
                </span>
                <span className="font-mono text-xs text-muted">
                  {formatGuesses(match.guesses)} guesses
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function IndicMatchCard({ match }: { match: Match }) {
  const kind = match.is_named_entity ? "name" : "word";
  const verified = match.model_verified ? "model-verified" : "unverified";
  const observedRank = match.rank_policy === "observed_rank";

  return (
    <div className="rounded-lg border bg-background px-3 py-2.5 text-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <span>
          <span className="font-medium">Hindi dictionary {kind}</span>{" "}
          <span className="text-muted">
            chars {match.start}&ndash;{match.end} ({match.length} chars)
          </span>
        </span>
        <span className="font-mono text-xs text-muted">
          {formatGuesses(match.guesses)} guesses
        </span>
      </div>

      {(match.token || match.native_form) && (
        <p className="mt-1 font-mono text-sm">
          {match.token}
          {match.native_form ? (
            <>
              {" "}
              <span className="text-muted">renders as</span> {match.native_form}
            </>
          ) : null}
        </p>
      )}

      <p className="mt-1 text-xs text-muted">
        {match.match_class} &middot; {match.tier} tier &middot; {verified}
        {match.case_transformation && match.case_transformation !== "lowercase"
          ? ` · case: ${match.case_transformation}`
          : null}
      </p>

      <p className="mt-1 text-xs text-muted">
        {observedRank && match.rank ? (
          <>
            Wordlist rank {match.rank.toLocaleString()}
            {typeof match.frequency === "number"
              ? ` (corpus frequency ${match.frequency}, ${match.frequency_source ?? "measured"})`
              : null}
          </>
        ) : (
          <>
            No observed corpus frequency &mdash; priced by the {match.tier} tier fallback
            {typeof match.wordlist_position === "number"
              ? ` at position ${Math.round(match.wordlist_position).toLocaleString()}`
              : null}
          </>
        )}
      </p>
    </div>
  );
}
