import { OOV_SEPARATION, PCFG_GENERALIZATION } from "@/lib/research-data";
import { Section } from "../Section";
import { ResearchFigure } from "./ResearchFigure";

/**
 * "OOV / Generalization" — does the character model carry real information
 * about Romanized-Hindi shape, or is it just a lookup table? Both numbers
 * here are transcribed from `results/reports/milestone5_oov_attack.md` §8.1
 * and `results/reports/pcfg_benchmark_hin.md`'s character-model section.
 */
export function OovGeneralization() {
  return (
    <Section
      title="OOV / Generalization"
      description="OOV = out-of-lexicon: a password whose spelling the 297,747-entry dictionary does not contain. These results test behaviour beyond direct dictionary membership — not proof that every unseen password is correctly understood."
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg border bg-background p-4">
          <p className="text-3xl font-semibold" style={{ color: "#1e3a5f" }}>
            {OOV_SEPARATION.separationOrdersOfMagnitude}
          </p>
          <p className="text-sm font-medium">orders of magnitude separation</p>
          <p className="mt-2 text-xs leading-relaxed text-muted">
            Median log10 attack rank: {OOV_SEPARATION.medianLog10RankOovIndic} for out-of-lexicon Hindi
            words vs. {OOV_SEPARATION.medianLog10RankRandomControl} for random control strings, under the
            M5 character-model attack (which, unlike M4, can reach a random lower-case string at all — so
            the control here is &ldquo;how much later&rdquo;, not &ldquo;does it reach it&rdquo;). A gap
            near zero would mean the character model is matching noise; a large one means it carries real
            information about Romanized-Hindi shape.
          </p>
          <p className="mt-2 text-[11px] text-muted">Source: {OOV_SEPARATION.source}</p>
        </div>

        <div className="rounded-lg border bg-background p-4">
          <p className="text-sm font-medium">PCFG character-model generalisation</p>
          <div className="mt-2 grid grid-cols-3 gap-2 text-center">
            <Stat label="in-dictionary" value={PCFG_GENERALIZATION.inDictLog10PerChar.toFixed(3)} sub={`n=${PCFG_GENERALIZATION.inDictN}`} />
            <Stat label="out-of-lexicon" value={PCFG_GENERALIZATION.oovLog10PerChar.toFixed(3)} sub={`n=${PCFG_GENERALIZATION.oovN}`} />
            <Stat label="random control" value={PCFG_GENERALIZATION.randomControlLog10PerChar.toFixed(3)} sub="log10/char" />
          </div>
          <p className="mt-3 text-xs leading-relaxed text-muted">
            Cost per character is nearly identical for words the model trained on (
            {PCFG_GENERALIZATION.inDictLog10PerChar}) and words it never saw (
            {PCFG_GENERALIZATION.oovLog10PerChar}) — consistent with the character model having learned
            the shape of Romanized Hindi rather than memorising a list of spellings. Random strings cost
            far more ({PCFG_GENERALIZATION.randomControlLog10PerChar}/char), so the discrimination is
            real. This does not mean the finding is large in absolute terms: only{" "}
            {PCFG_GENERALIZATION.marginOverFloor} log10/char of that signal can ever reach a reported
            estimate, because it competes against a brute-force floor of{" "}
            {PCFG_GENERALIZATION.floorLog10PerChar}/char.
          </p>
          <p className="mt-2 text-[11px] text-muted">Source: {PCFG_GENERALIZATION.source}</p>
        </div>
      </div>

      <div className="mt-4">
        <ResearchFigure
          src="/research/figures/oov_vs_random_separation.svg"
          alt="Median log10 attack rank: in-lexicon vs out-of-lexicon Hindi vs random controls"
          caption="How deep the M5 character attack has to go before reaching each population."
          source="results/figures/oov_vs_random_separation.svg"
        />
      </div>
    </Section>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-md border bg-surface-muted px-2 py-2">
      <div className="font-mono text-lg font-semibold">{value}</div>
      <div className="text-[11px] text-muted">{label}</div>
      <div className="text-[10px] text-muted/70">{sub}</div>
    </div>
  );
}
