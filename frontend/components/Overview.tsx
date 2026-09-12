export function Overview() {
  return (
    <section className="rounded-xl border bg-surface p-5 sm:p-6">
      <h2 className="text-sm font-semibold">What IndicPass does</h2>
      <p className="mt-2 text-sm leading-relaxed text-muted">
        Most password-strength meters were built and measured on English. IndicPass
        asks what a meter misses when a password is built from Romanized Indic
        words instead &mdash; <code className="font-mono text-foreground">namaste</code>,{" "}
        <code className="font-mono text-foreground">bharat2024</code>,{" "}
        <code className="font-mono text-foreground">sharma@123</code> &mdash; spellings
        a generic English wordlist has never seen but an attacker who knows the
        threat model absolutely would try.
      </p>
      <p className="mt-2 text-sm leading-relaxed text-muted">
        The engine matches Romanized-Hindi substrings against a 297,747-entry
        dictionary built offline from a trained transliteration model, prices each
        hit by its measured position in an attacker&rsquo;s wordlist, and combines
        that with a probabilistic grammar (PCFG) over password structure &mdash; all
        scored against a generic baseline (zxcvbn) in the same call, so every result
        below is a direct comparison rather than a claim taken on faith.
      </p>
      <p className="mt-3 text-xs text-muted">
        This page is a live interface over that research implementation &mdash; not a
        reimplementation. Every number came from{" "}
        <code className="font-mono">src/indicpass/password/</code> running against the
        committed dictionary and PCFG artefacts; nothing is computed in the browser.
      </p>
    </section>
  );
}
