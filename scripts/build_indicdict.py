#!/usr/bin/env python
"""Build IndicDict offline, using the trained transliterator.

    python scripts/build_indicdict.py --languages hin
    python scripts/build_indicdict.py --languages hin --model models/final/indicpass-hin-v1

This is the *only* place the transliteration model touches the password engine.
It runs here, once, over a vocabulary; the meter then reads the file it writes.
Scoring a password never invokes the model -- for runtime, and more importantly
so a benchmark result rests on a fixed artefact rather than on whatever the
model happened to decode that day. The dictionary is too large to commit, so
what is committed is its ``.meta.json`` sidecar: the tier sizes every guess
estimate depends on, plus the model, commit and filters that produced them.
Rebuilding from the same inputs gives the same file.

The pipeline
------------
    Romanized Hindi vocabulary   (all splits -- see below)
              |
              v
    trained transliterator       (greedy decode, batched)
              |
              v
    native Hindi candidate
              |
              v
    validation / filtering       (script check, agreement with the corpus)
              |
              v
    IndicDict

Why all splits, not just train: this builds a *wordlist*, not a model. Nothing
is fitted here, and nothing is later evaluated against the transliteration
splits, so the usual reason to hold data back does not apply -- while the cost
of holding it back is real. The 1%% validation and test splits are where
``bharat`` and ``krishna`` happen to live, and a Hindi password dictionary
missing those two would be a worse instrument for no gain. The transliteration
test evaluation in ``results/reports/`` was run before this and is unaffected.

Corpus coverage is uneven
-------------------------
Aksharantar is a transliteration corpus, not a Hindi lexicon, and its Hindi
vocabulary has real holes. ``namaste``, ``sharma``, ``namaskar`` and
``dhanyavaad`` are absent outright, while inflected neighbours -- ``namasteji``,
``sharmane``, ``dhanyavad`` -- are present. Words are not added by hand to
close that gap: a dictionary hand-tuned to recognise the demo examples would
tell us nothing about whether Indic awareness helps in general. The gap is
measured and reported instead; see ``docs/password_strength_design.md``.

Frequency
---------
Aksharantar supplies none, and none is invented from it: its only numeric field
is a mining log-likelihood present on one subsource, and the subsource called
``AK-Freq`` is not frequency-ordered. What frequency the dictionary carries is
imported here from an external, versioned table (``wordfreq``) and joined
through the **native** form -- the transliterator's prediction first, the
corpus's attested spellings second. The result is baked into the file so that
scoring stays a lookup and a benchmark does not depend on which version of
wordfreq happens to be installed at scoring time.

Coverage is partial by construction: the shipped Hindi list holds ~27k words
against ~298k spellings here. Entries it does not cover keep ``frequency:
null`` and ``rank: null`` and are priced by their provenance tier. Nothing is
substituted for them. See ``docs/password_strength_design.md``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401  -- puts src/ on sys.path
from indicpass.cli import add_common_arguments, run_cli, startup
from indicpass.config import Language
from indicpass.logging_utils import progress
from indicpass.password.dictionary import IndicDict, IndicDictEntry
from indicpass.password.frequency import load_frequency_lookup
from indicpass.records import read_jsonl
from indicpass.script_utils import script_ratio

SCRIPT = "build_indicdict"

DEFAULT_MODEL = "models/final/indicpass-hin-v1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_indicdict.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common_arguments(parser)
    parser.add_argument(
        "--model",
        "-m",
        type=Path,
        default=Path(DEFAULT_MODEL),
        metavar="PATH",
        help=f"Transliteration bundle or checkpoint (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--splits",
        nargs="+",
        default=["train", "validation", "test"],
        metavar="NAME",
        help=(
            "Processed splits the vocabulary is drawn from (default: all three). "
            "A wordlist is not a trained model -- see the module docstring."
        ),
    )
    parser.add_argument(
        "--input-dir", type=Path, metavar="DIR", help="Processed directory to read."
    )
    parser.add_argument(
        "--output", "-o", type=Path, metavar="FILE", help="Dictionary path. Default from config."
    )
    parser.add_argument("--device", metavar="DEV", help="cuda, cpu or auto (default: auto).")
    parser.add_argument("--batch-size", type=int, default=256, metavar="N")
    parser.add_argument(
        "--no-model",
        action="store_true",
        help=(
            "Skip transliteration and use the corpus's attested native form. "
            "For rebuilding the dictionary where torch is not installed; the "
            "entries are then marked model_verified=false."
        ),
    )
    parser.add_argument(
        "--no-frequency",
        action="store_true",
        help=(
            "Build without the external frequency table, pricing every entry by "
            "its provenance tier. This is the Milestone 1 artefact and exists so "
            "the effect of adding frequency can be measured; a report produced "
            "from it must say so."
        ),
    )
    parser.add_argument(
        "--reuse-native-forms",
        type=Path,
        metavar="FILE",
        help=(
            "Take native forms from an existing dictionary instead of re-running "
            "the model. Only spellings present in that file are kept, so this "
            "re-annotates a previous build rather than producing a new one."
        ),
    )
    return parser


def git_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _read_previous(path: Path) -> Iterator[IndicDictEntry]:
    """Stream a previously built dictionary file.

    Read directly rather than through ``IndicDict.load`` so that re-annotating
    does not first have to satisfy the current tier configuration -- the point
    of the reuse path is to keep the model's output while everything around it
    changes.
    """
    if not path.is_file():
        raise FileNotFoundError(f"No dictionary to reuse native forms from at {path}.")
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if text:
                yield IndicDictEntry.from_dict(json.loads(text))


def tier_index(tiers: Sequence[dict[str, Any]]) -> dict[str, str]:
    """Map each Aksharantar subsource to its configured tier name."""
    index: dict[str, str] = {}
    for tier in tiers:
        for subsource in tier.get("subsources") or []:
            index[str(subsource)] = str(tier["name"])
    return index


def collect_vocabulary(
    paths: Sequence[Path],
    *,
    subsource_to_tier: dict[str, str],
    min_length: int,
    max_length: int,
) -> dict[str, dict[str, Any]]:
    """Read splits into ``romanized -> {tier, source, attested forms}``.

    Only lower-case ASCII letters are kept. A spelling containing a digit or a
    hyphen is a corpus artefact rather than a word, and the model's source
    vocabulary is 26 letters anyway -- anything else would decode from <UNK>.

    A spelling seen in several subsources is filed under its BEST tier: that is
    where an attacker's wordlist would reach it first, and guessing cost is a
    minimum over the attacker's options.
    """
    tier_rank = {
        name: index for index, name in enumerate(dict.fromkeys(subsource_to_tier.values()))
    }
    vocabulary: dict[str, dict[str, Any]] = {}

    for path in paths:
        for row in progress(read_jsonl(path), f"reading {path.stem}"):
            word = str(row.get("source_text") or "")
            native = str(row.get("target_text") or "")
            if not word or not native:
                continue
            if not (min_length <= len(word) <= max_length):
                continue
            if not (word.isascii() and word.isalpha() and word.islower()):
                continue

            tier = subsource_to_tier.get(str(row.get("subsource") or ""))
            if tier is None:
                continue  # a subsource nobody put in a tier is not dictionary material

            existing = vocabulary.get(word)
            if existing is None:
                vocabulary[word] = {
                    "tier": tier,
                    "source": str(row.get("subsource") or ""),
                    "attested": {native},
                }
                continue

            existing["attested"].add(native)
            if tier_rank[tier] < tier_rank[existing["tier"]]:
                existing["tier"] = tier
                existing["source"] = str(row.get("subsource") or "")

    return vocabulary


def apply_tier_caps(
    vocabulary: dict[str, dict[str, Any]],
    caps: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """Trim each tier to its configured cap, deterministically.

    Selection within a tier is by ``(length, spelling)``: shorter first, then
    alphabetical. Short spellings are the password-plausible ones, and both
    keys are properties of the string, so the same corpus always yields the
    same dictionary. This is a *selection* rule, not a ranking -- nothing
    downstream reads the order back.
    """
    by_tier: dict[str, list[str]] = defaultdict(list)
    for word, info in vocabulary.items():
        by_tier[str(info["tier"])].append(word)

    kept: dict[str, dict[str, Any]] = {}
    dropped: dict[str, int] = {}
    for tier, words in by_tier.items():
        cap = caps.get(tier)
        words.sort(key=lambda w: (len(w), w))
        if cap is not None and len(words) > int(cap):
            dropped[tier] = len(words) - int(cap)
            words = words[: int(cap)]
        for word in words:
            kept[word] = vocabulary[word]
    return kept, dropped


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config, logger = startup(args, SCRIPT)

    languages = config.resolve_languages(args.languages)
    if len(languages) != 1:
        logger.error("Build one language at a time. Pass --languages hin.")
        return 2
    language: Language = languages[0]

    dictionary_config = config.password_section("dictionary")
    tiers = list(dictionary_config.get("tiers") or [])
    tier_order = [str(tier["name"]) for tier in tiers]
    subsource_to_tier = tier_index(tiers)

    source_name = args.source or config.default_source
    input_dir = config.resolve(
        args.input_dir or config.preprocessing.get("output_dir", "data/processed")
    )
    split_paths = [
        input_dir / source_name / language.code / f"{name}.jsonl" for name in args.splits
    ]
    missing = [path for path in split_paths if not path.is_file()]
    if missing:
        logger.error(
            "Missing processed split(s): %s",
            ", ".join(config.relative(path) for path in missing),
        )
        return 1

    logger.info(
        "Collecting vocabulary from %s", ", ".join(config.relative(p) for p in split_paths)
    )
    vocabulary = collect_vocabulary(
        split_paths,
        subsource_to_tier=subsource_to_tier,
        min_length=int(dictionary_config.get("min_token_length", 3)),
        max_length=int(dictionary_config.get("max_token_length", 16)),
    )
    logger.info("  %d distinct Romanized spellings in scope", len(vocabulary))

    vocabulary, dropped = apply_tier_caps(
        vocabulary, dict(dictionary_config.get("max_entries_per_tier") or {})
    )
    for tier, count in sorted(dropped.items()):
        logger.info("  tier %s: capped, %d spellings dropped", tier, count)
    logger.info("  %d spellings after tier caps", len(vocabulary))

    words = sorted(vocabulary)
    predictions: list[str] = []
    model_info: dict[str, Any] = {"used": False}

    if args.reuse_native_forms is not None:
        source_path = config.resolve(args.reuse_native_forms)
        logger.info("Reusing native forms from %s", config.relative(source_path))
        previous = {
            entry.romanized_form: entry
            for entry in _read_previous(source_path)
        }
        # Drop anything the previous build did not contain rather than filling
        # the gap from the corpus: mixing two provenances inside one file would
        # make model_verified mean two different things.
        words = [word for word in words if word in previous]
        predictions = [previous[word].native_form for word in words]
        # Carry the earlier build's model block forward. Without it the chain
        # from a dictionary back to the checkpoint that produced its native
        # forms is broken after one re-annotation, and the file stops being
        # able to say where it came from.
        previous_meta = source_path.with_suffix(".meta.json")
        inherited = (
            json.loads(previous_meta.read_text(encoding="utf-8")).get("model")
            if previous_meta.is_file()
            else None
        )
        model_info = {
            "used": False,
            "reused_from": config.relative(source_path),
            "inherited_model": inherited,
            "note": (
                "Native forms copied from a previous build; the model did not run here. "
                "inherited_model records the build that did produce them."
            ),
        }
        if inherited is None:
            logger.warning(
                "No .meta.json beside %s, so the model that produced these native forms "
                "cannot be recorded. The dictionary will not be self-describing.",
                config.relative(source_path),
            )
        verified_override = {word: previous[word].model_verified for word in words}
    elif args.no_model:
        logger.warning(
            "--no-model: using the corpus's attested form instead of a model prediction. "
            "Entries will be marked model_verified=false."
        )
        predictions = [sorted(vocabulary[word]["attested"])[0] for word in words]
        verified_override = {}
    else:
        verified_override = {}
        try:
            import torch  # noqa: F401
        except ImportError:
            logger.error(
                "PyTorch is not installed, so the model cannot run.\n"
                "  python -m pip install -r requirements/ml.txt\n"
                "Or pass --no-model to build from the corpus's attested forms alone."
            )
            return 2

        from indicpass.inference import load_bundle, transliterate
        from indicpass.seeding import describe_device

        model_path = config.resolve(args.model)
        logger.info("Loading %s", config.relative(model_path))
        loaded = load_bundle(model_path, device=args.device)
        logger.info(
            "Transliterating %d spellings on %s",
            len(words),
            describe_device(loaded.model.device),
        )

        bar = iter(progress(range(0, len(words), args.batch_size), "transliterating"))
        started = time.perf_counter()
        predictions = transliterate(
            loaded,
            words,
            batch_size=args.batch_size,
            progress=lambda _done: next(bar, None),
        )
        model_info = {
            "used": True,
            "identifier": loaded.identifier,
            "kind": loaded.kind,
            "path": config.relative(loaded.path),
            "seconds": round(time.perf_counter() - started, 2),
            "metadata": loaded.metadata,
        }

    # -- frequency ---------------------------------------------------------
    frequency_config = config.password_section("frequency")
    lookup = None
    if not args.no_frequency and bool(frequency_config.get("enabled", True)):
        provider_code = (frequency_config.get("languages") or {}).get(language.code)
        if provider_code is None:
            logger.error(
                "config/password.yaml frequency.languages has no entry for %r, so the "
                "frequency table cannot be joined. Add one, or pass --no-frequency.",
                language.code,
            )
            return 2
        lookup = load_frequency_lookup(
            str(provider_code),
            provider=str(frequency_config.get("provider", "wordfreq")),
            wordlist=str(frequency_config.get("wordlist", "small")),
            use_attested_forms=bool(frequency_config.get("use_attested_forms", True)),
        )
        logger.info(
            "Frequency source %s (%d words)", lookup.source.identifier, len(lookup)
        )
    else:
        logger.warning(
            "Building WITHOUT a frequency source. Every entry will be priced by its "
            "provenance tier, and any report from this dictionary must say so."
        )

    # -- validation / filtering -------------------------------------------
    entries: list[IndicDictEntry] = []
    rejected = {"empty_prediction": 0, "wrong_script": 0}
    verified = 0
    frequency_hits = {"native_form": 0, "attested_form": 0}

    for word, prediction in zip(words, predictions, strict=True):
        info = vocabulary[word]
        attested = sorted(info["attested"])

        if not prediction:
            rejected["empty_prediction"] += 1
            continue
        ratio = script_ratio(
            prediction,
            language.unicode_ranges,
            neutral_codepoints=config.neutral_codepoints,
            neutral_categories=config.neutral_categories,
        )
        if ratio < float(config.preprocessing.get("min_target_script_ratio", 0.9)):
            # The model emitted something that is not the target script. Rare,
            # but it must not reach the dictionary as a "native form".
            rejected["wrong_script"] += 1
            continue

        agrees = verified_override.get(word, prediction in info["attested"])
        verified += agrees

        reading = lookup.lookup(prediction, attested) if lookup else None
        if reading is not None and reading.matched_via:
            frequency_hits[reading.matched_via] += 1

        entries.append(
            IndicDictEntry(
                romanized_form=word,
                native_form=prediction,
                language=language.code,
                tier=str(info["tier"]),
                source=str(info["source"]),
                attested_forms=tuple(attested),
                model_verified=bool(agrees),
                variant_count=len(attested),
                # Observed or explicitly absent. Rank is assigned by
                # IndicDict.from_entries once the whole set is known.
                frequency=reading.value if reading else None,
                rank=None,
                frequency_source=(
                    lookup.source.identifier if reading and reading.observed else None
                ),
                frequency_matched_via=reading.matched_via if reading else None,
            )
        )

    dictionary = IndicDict.from_entries(
        entries,
        language=language.code,
        tier_order=tier_order,
        frequency_source=lookup.source.to_dict() if lookup else None,
    )

    output = args.output or (config.password_section("dictionary").get("files") or {}).get(
        language.code
    )
    if output is None:
        logger.error("No output path for %s in config/password.yaml.", language.code)
        return 2
    path = config.resolve(output)

    dictionary.save(
        path,
        metadata={
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "git_commit": git_commit(config.root),
            "dataset": {
                "source": source_name,
                "splits": list(args.splits),
                "files": [config.relative(path) for path in split_paths],
            },
            "model": model_info,
            "filters": {
                "min_token_length": int(dictionary_config.get("min_token_length", 3)),
                "max_token_length": int(dictionary_config.get("max_token_length", 16)),
                "charset": "ascii lowercase letters only",
                "max_entries_per_tier": dict(
                    dictionary_config.get("max_entries_per_tier") or {}
                ),
            },
            "rejected": rejected,
            "model_verified_entries": verified,
            "model_verified_ratio": (
                round(verified / len(entries), 6) if entries else 0.0
            ),
            "frequency_matched_via": frequency_hits,
        },
    )

    total = len(dictionary)
    print(f"\n{'=' * 70}\nINDICDICT -- {language.code}\n{'=' * 70}")
    print(f"  entries              {total:,}")
    print(f"  model verified       {verified:,} "
          f"({verified / len(entries) * 100 if entries else 0:.1f}%)")
    print(f"  rejected             {rejected}")
    if lookup is not None:
        print(f"  frequency source     {lookup.source.identifier} ({len(lookup):,} words)")
        print(f"  ranked entries       {dictionary.ranked_total:,} "
              f"({dictionary.frequency_coverage * 100:.1f}% of the dictionary)")
        print(f"    via native form    {frequency_hits['native_form']:,}")
        print(f"    via attested form  {frequency_hits['attested_form']:,}")
    else:
        print("  frequency source     none -- every entry priced by its tier")
    print(f"  {'tier':<18} {'size':>9} {'ranked':>9} {'unranked':>9} {'offset':>9}")
    for tier in sorted(dictionary.tiers.values(), key=lambda t: t.index):
        print(f"    {tier.name:<16} {tier.size:>9,} {tier.ranked_size:>9,} "
              f"{tier.unranked_size:>9,} {tier.offset:>9,}")
    print(f"\n  written to {config.relative(path)}\n")

    logger.info("Dictionary written to %s", config.relative(path))
    return 0


if __name__ == "__main__":
    sys.exit(run_cli(main))
