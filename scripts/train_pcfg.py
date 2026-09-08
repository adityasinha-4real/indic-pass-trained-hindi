#!/usr/bin/env python
"""Fit the Indic PCFG and write its artefact.

    python scripts/train_pcfg.py --languages hin
    python scripts/train_pcfg.py --languages hin --samples 20000 --no-write   # smoke run

Two things happen here, and only one of them is stochastic.

**Fitting the grammar** is deterministic. The word distribution is a function of
the dictionary's ``frequency`` and ``tier`` fields; the character n-gram is a
function of its keys. Both depend on the *set* of entries, not their order, so
the same dictionary always produces the same grammar. That is why the artefact
does not store either of them: it stores a fingerprint over
``(spelling, frequency, tier)`` and refits at load time, and a mismatch is a
hard error rather than a silently wrong number.

**Building the guess curve** draws ``estimator.samples`` derivations from the
grammar, seeded by ``estimator.sample_seed``. That seed is the only randomness
anywhere in the pipeline and it is recorded in the artefact and in every report.

Nothing sampled is ever assembled into a password. The Monte-Carlo estimator
needs the *probabilities* of the drawn derivations and nothing else, so the
sampler returns numbers; a file of sampled passwords would be a cracking
wordlist, and there is no point in this pipeline at which one exists.
"""

from __future__ import annotations

import argparse
import dataclasses
import subprocess
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

import _bootstrap  # noqa: F401  -- puts src/ on sys.path
from indicpass.cli import add_common_arguments, run_cli, startup
from indicpass.password.dictionary import IndicDict
from indicpass.password.pcfg.artifact import dictionary_fingerprint, save_estimator
from indicpass.password.pcfg.estimator import EstimatorSettings, PcfgEstimator
from indicpass.password.pcfg.grammar import GrammarSettings, PcfgGrammar
from indicpass.password.scoring import StrengthScale

SCRIPT = "train_pcfg"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="train_pcfg.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common_arguments(parser)
    parser.add_argument(
        "--dictionary", type=Path, metavar="FILE", help="Dictionary to fit. Default from config."
    )
    parser.add_argument(
        "--samples", type=int, metavar="N", help="Curve samples. Default from config."
    )
    parser.add_argument(
        "--sample-seed", type=int, metavar="N", help="Sampler seed. Default from config."
    )
    parser.add_argument(
        "--ngram-order", type=int, metavar="N", help="Character-model order. Default from config."
    )
    parser.add_argument("--output", type=Path, metavar="FILE", help="Where the artefact lands.")
    parser.add_argument("--no-write", action="store_true", help="Fit and report; write nothing.")
    return parser


def git_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config, logger = startup(args, SCRIPT)

    languages = config.resolve_languages(args.languages)
    if len(languages) != 1:
        logger.error(
            "The PCFG is a single-language model: its character n-gram and its word "
            "distribution are both fitted to one lexicon. Pass --languages hin."
        )
        return 2
    language = languages[0]

    dictionary_config = config.password_section("dictionary")
    scoring = config.password_section("scoring")
    pcfg_config = config.password_section("pcfg")
    tier_order = [str(tier["name"]) for tier in (dictionary_config.get("tiers") or [])]

    path = config.resolve(
        args.dictionary or (dictionary_config.get("files") or {})[language.code]
    )
    logger.info("Loading %s", config.relative(path))
    dictionary = IndicDict.load(path, language=language.code, tier_order=tier_order)
    logger.info(
        "  %d entries, %d with an observed frequency (%.1f%%)",
        len(dictionary),
        dictionary.ranked_total,
        dictionary.frequency_coverage * 100,
    )

    grammar_settings = GrammarSettings.from_config(pcfg_config, scoring)
    if args.ngram_order:
        grammar_settings = _replace(grammar_settings, ngram_order=args.ngram_order)

    estimator_settings = EstimatorSettings.from_config(pcfg_config, scoring)
    if args.samples:
        estimator_settings = _replace(estimator_settings, samples=args.samples)
    if args.sample_seed is not None:
        estimator_settings = _replace(estimator_settings, sample_seed=args.sample_seed)

    started = time.perf_counter()
    grammar = PcfgGrammar.train(dictionary, grammar_settings)
    fitted = time.perf_counter() - started
    logger.info(
        "Grammar fitted in %.1fs: order-%d n-gram over %s contexts, %s training spellings",
        fitted,
        grammar.settings.ngram_order,
        f"{len(grammar.ngram.counts):,}",
        f"{grammar.ngram.training_words:,}",
    )

    words = grammar.words
    logger.info(
        "  word distribution: %s observed, %s priced by the %s policy",
        f"{words.observed_entries:,}",
        f"{words.unobserved_entries:,}",
        words.policy,
    )
    for name, weight in sorted(words.tier_weights.items()):
        logger.info("    tier weight %-18s %.4f", name, weight)

    started = time.perf_counter()
    estimator = PcfgEstimator.train(
        grammar,
        settings=estimator_settings,
        scale=StrengthScale.from_config(config.password_section("strength")),
    )
    sampled = time.perf_counter() - started
    curve = estimator.curve
    logger.info(
        "Guess curve built in %.1fs: %s samples, %d stored points, tail slope %.3f",
        sampled,
        f"{curve.samples:,}",
        len(curve.log10_probabilities),
        curve.tail_slope,
    )
    logger.info(
        "  log10 P spans %.2f (most likely) to %.2f (least); log10 G spans %.2f to %.2f",
        curve.log10_probabilities[0],
        curve.log10_probabilities[-1],
        curve.log10_guesses[0],
        curve.log10_guesses[-1],
    )
    logger.info("  segments drawn: %s", dict(curve.segment_histogram))

    print_summary(estimator, dictionary)

    if args.no_write:
        logger.info("--no-write: nothing written.")
        return 0

    output = config.resolve(args.output) if args.output else config.resolve(
        (pcfg_config.get("files") or {})[language.code]
    )
    save_estimator(
        estimator,
        output,
        language=language.code,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "git_commit": git_commit(config.root),
            "project": f"{config.name} v{config.version}",
            "dictionary_path": config.relative(path),
            "fit_seconds": round(fitted, 2),
            "sample_seconds": round(sampled, 2),
        },
    )
    logger.info("Artefact written to %s", config.relative(output))
    logger.info(
        "  %.1f KiB -- the curve and the hyper-parameters, not the grammar",
        output.stat().st_size / 1024,
    )
    return 0


def _replace(settings, **changes):
    return dataclasses.replace(settings, **changes)


def print_summary(estimator: PcfgEstimator, dictionary: IndicDict) -> None:
    """A short console read-out. Prints no password and no dictionary entry."""
    grammar = estimator.grammar
    print(f"\n{'=' * 78}")
    print("PCFG TRAINED")
    print(f"{'=' * 78}")
    print(f"  dictionary        {len(dictionary):,} entries "
          f"({dictionary.ranked_total:,} with observed frequency)")
    print(f"  fingerprint       {dictionary_fingerprint(dictionary)[:23]}...")
    print(f"  n-gram            order {grammar.settings.ngram_order}, "
          f"{len(grammar.ngram.counts):,} contexts, Witten-Bell")
    print(f"  structure prior   geometric(q={grammar.settings.segment_continuation}), "
          f"truncated at {grammar.settings.max_segments}   [ASSUMPTION: not learned]")
    prior = "uniform (maximum entropy)" if not grammar.settings.category_prior else "configured"
    print(f"  category prior    {prior}   [ASSUMPTION: not learned]")
    print(f"  guess curve       {estimator.curve.samples:,} sampled derivations, "
          f"seed {estimator.curve.seed}")
    print()
    print("  Structure probabilities are NOT learned: that needs a corpus of real")
    print("  passwords, this repository has none, and fitting them to the synthetic")
    print("  benchmark would measure the generator. See docs/password_strength_design.md")
    print("  section 14.4.")
    print()


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
