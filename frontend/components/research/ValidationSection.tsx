import {
  M4_ATTACK,
  M4_VALIDATION,
  M5_ATTACK,
  M5_VALIDATION_ALL,
  M5_M3_VS_M2_TRADEOFF,
  ZXCVBN_INDIC_WORD_SPEARMAN,
} from "@/lib/research-data";
import { Section } from "../Section";
import { ResearchFigure } from "./ResearchFigure";
import { ValidationTable } from "./ValidationTable";

/**
 * "Independent Validation" — scores every estimator against two bounded,
 * fully specified reference attacks (M4, M5) whose rank is OBSERVED by
 * inversion, rather than treating one estimator as ground truth for
 * another. All numbers here are transcribed from
 * `results/reports/reference_attack_hin.md` and
 * `results/reports/milestone5_oov_attack.md`; the embedded figures are
 * static copies of that report's own rendered SVGs.
 */
export function ValidationSection() {
  return (
    <Section
      title="Independent Validation"
      description="Estimated guesses vs. an observed attack rank — a different kind of evidence from the Live Estimator Comparison above, which only compares models with each other."
    >
      <div className="mb-4 rounded-lg border bg-surface-muted px-3 py-2.5 text-xs leading-relaxed text-muted">
        These evaluations compare the estimators against independent, bounded attack procedures rather
        than treating another password-strength estimator as ground truth. Neither attack uses real
        leaked passwords — both are fully specified, reproducible procedures defined by this project.
      </div>

      <h4 className="text-sm font-semibold">M4 &mdash; wordlist &times; rules attack</h4>
      <p className="mt-1 text-xs text-muted">
        Universe: 10^{M4_ATTACK.universeLog10} candidates ({M4_ATTACK.universeExact}). Reaches{" "}
        {M4_ATTACK.coveragePct}% of the 1,400-sample benchmark ({M4_ATTACK.coveredOfTotal}) &mdash; by
        construction it cannot reach any of the 872 out-of-lexicon targets (0/872), because its universe
        is a wordlist.
      </p>
      <div className="mt-3">
        <ValidationTable rows={M4_VALIDATION} />
      </div>
      <p className="mt-2 text-xs text-muted">
        zxcvbn&rsquo;s rank correlation restricted to the <code className="font-mono">indic_word</code>{" "}
        category alone is <strong className="text-foreground">{ZXCVBN_INDIC_WORD_SPEARMAN}</strong> &mdash;
        essentially no ordering information on bare Romanized Hindi words. Source:{" "}
        <code className="font-mono">{M4_ATTACK.source}</code>.
      </p>

      <h4 className="mt-6 text-sm font-semibold">M5 &mdash; character-model attack (reaches unseen spellings)</h4>
      <p className="mt-1 text-xs text-muted">
        Universe: ~10^{M5_ATTACK.universeStemsLog10} stems, counted without enumeration. Reaches{" "}
        {M5_ATTACK.coveragePct}% overall ({M5_ATTACK.coveredOfTotal}) and{" "}
        <strong className="text-foreground">{M5_ATTACK.oovIndicCoveragePct}%</strong> of the 468
        out-of-lexicon Indic targets ({M5_ATTACK.oovIndicCoveredOf}) &mdash; the population M4 cannot
        reach at all.
      </p>
      <div className="mt-3">
        <ValidationTable rows={M5_VALIDATION_ALL} />
      </div>

      <div className="mt-4 rounded-lg border bg-background p-4 text-sm">
        <p className="font-medium">
          On the 468 out-of-lexicon Indic targets specifically ({M5_M3_VS_M2_TRADEOFF.population}):
        </p>
        <ul className="mt-2 space-y-1 text-xs text-muted">
          <li>
            Ordering (Spearman &rho;): IndicPass {M5_M3_VS_M2_TRADEOFF.rhoM2.toFixed(3)} vs. PCFG{" "}
            {M5_M3_VS_M2_TRADEOFF.rhoM3.toFixed(3)} &mdash; paired difference [{M5_M3_VS_M2_TRADEOFF.rhoDiffLow.toFixed(3)},{" "}
            {M5_M3_VS_M2_TRADEOFF.rhoDiffHigh.toFixed(3)}] excludes zero: <strong>IndicPass orders better</strong>.
          </li>
          <li>
            Calibration (MAE): IndicPass {M5_M3_VS_M2_TRADEOFF.maeM2.toFixed(3)} vs. PCFG{" "}
            {M5_M3_VS_M2_TRADEOFF.maeM3.toFixed(3)} &mdash; paired difference [{M5_M3_VS_M2_TRADEOFF.maeDiffLow.toFixed(3)},{" "}
            {M5_M3_VS_M2_TRADEOFF.maeDiffHigh.toFixed(3)}] excludes zero: <strong>PCFG is closer in magnitude</strong>.
          </li>
        </ul>
        <p className="mt-2 text-xs text-muted">
          Both hold at once, on the same targets, under a paired 2,000-resample bootstrap (95% CI). This
          is the project&rsquo;s central trade-off, not a contradiction: a 0&ndash;4 band needs ordering
          (IndicPass wins), a magnitude estimate needs calibration (PCFG wins) &mdash; which is why the
          shipped score is M2&rsquo;s alone and PCFG is reported alongside it, never substituted in.
        </p>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <ResearchFigure
          src="/research/figures/rank_correlation.svg"
          alt="Rank correlation with the observed M5 attack order, by population"
          caption="Spearman rho between predicted log10 guesses and the observed M5 attack rank, reachable targets only."
          source="results/figures/rank_correlation.svg"
        />
        <ResearchFigure
          src="/research/figures/mean_absolute_error.svg"
          alt="Mean absolute error against the observed M5 attack order"
          caption="|predicted log10 guesses - observed log10 attack rank|, in orders of magnitude. Lower is better."
          source="results/figures/mean_absolute_error.svg"
        />
        <ResearchFigure
          src="/research/figures/calibration.svg"
          alt="Calibration against the observed M5 attack order"
          caption="OLS slope of observed log10 rank on predicted log10 guesses. 1.0 is perfect; below 1 compresses the scale."
          source="results/figures/calibration.svg"
        />
        <ResearchFigure
          src="/research/figures/coverage_m4_vs_m5.svg"
          alt="Benchmark coverage: M4 wordlist attack vs M5 character attack"
          caption="Share of the 1,400-sample benchmark each attack can reach and therefore rank, by population."
          source="results/figures/coverage_m4_vs_m5.svg"
        />
        <ResearchFigure
          src="/research/figures/confidence_intervals_spearman.svg"
          alt="M3 minus M2 rank correlation, with 95% bootstrap intervals"
          caption="Paired percentile bootstrap, 2,000 resamples. Positive favours the PCFG."
          source="results/figures/confidence_intervals_spearman.svg"
        />
        <ResearchFigure
          src="/research/figures/confidence_intervals_mae.svg"
          alt="M3 minus M2 mean absolute error, with 95% bootstrap intervals"
          caption="Same paired bootstrap. Negative favours the PCFG here, because a lower error is better."
          source="results/figures/confidence_intervals_mae.svg"
        />
      </div>
    </Section>
  );
}
