import type { DictionaryInfo } from "@/lib/types";
import { formatPercent } from "@/lib/format";

export function DictionaryPanel({ dictionaries }: { dictionaries: DictionaryInfo[] }) {
  if (dictionaries.length === 0) return null;

  return (
    <ul className="space-y-1.5 text-sm">
      {dictionaries.map((dict) => (
        <li key={dict.language} className="rounded-lg border bg-background px-3 py-2">
          <span className="font-medium uppercase">{dict.language}</span>{" "}
          <span className="text-muted">
            {dict.entries.toLocaleString()} entries &middot;{" "}
            {dict.ranked_entries.toLocaleString()} priced by measured rank (
            {formatPercent(dict.frequency_coverage)})
            {dict.frequency_source ? ` · source: ${dict.frequency_source.identifier}` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}
