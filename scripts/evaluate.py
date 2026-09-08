#!/usr/bin/env python
"""Score a trained transliterator on the HELD-OUT TEST split.

    python scripts/evaluate.py
    python scripts/evaluate.py --model models/final/indicpass-hin-v1 --languages hin
    python scripts/evaluate.py --limit 500 --no-report      # quick smoke run

Why this exists separately from training: the CER and exact-match numbers the
project has reported so far (CER 0.1048, EM 57.94%) come from the *validation*
split, and validation is what the best checkpoint was selected on. A number a
checkpoint was chosen by is a model-selection statistic, not a held-out result
-- reporting it as one overstates the model. This script measures the test
split, which nothing has ever selected on, and writes both numbers into the
report side by side so the distinction survives into whatever reads it.

Decoding is greedy and never teacher-forced, identical to ``Trainer.evaluate``,
so the two are directly comparable.

The report lands in ``results/reports/`` as JSON plus a Markdown twin, matching
what ``scripts/validate_dataset.py`` already writes there.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401  -- puts src/ on sys.path
from indicpass.cli import add_common_arguments, run_cli, startup
from indicpass.config import Config
from indicpass.metrics import evaluate_predictions
from indicpass.records import read_jsonl

SCRIPT = "evaluate"

#: Default model to score. A bundle directory, not a training checkpoint --
#: bundles load without executing a pickle and carry their own provenance.
DEFAULT_MODEL = "models/final/indicpass-hin-v1"

#: Split to report. Deliberately not a default that can silently become
#: "validation"; see the module docstring.
DEFAULT_SPLIT = "test"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evaluate.py",
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
        help=f"Bundle directory or .pt checkpoint to score (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--split",
        default=DEFAULT_SPLIT,
        metavar="NAME",
        help=(
            "Split to evaluate (default: test). Anything other than 'test' is "
            "labelled as a non-held-out measurement in the report."
        ),
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        metavar="DIR",
        help="Processed directory. Defaults to preprocessing.output_dir.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="Evaluate only the first N records. For smoke runs; marked in the report.",
    )
    parser.add_argument("--device", metavar="DEV", help="cuda, cpu or auto (default: auto).")
    parser.add_argument(
        "--batch-size", type=int, default=128, metavar="N", help="Words per forward pass."
    )
    parser.add_argument(
        "--max-length",
        type=int,
        default=64,
        metavar="N",
        help="Maximum characters generated per word (default: 64).",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=10,
        metavar="N",
        help="Worked examples to include in the report (default: 10).",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        metavar="FILE",
        help="Report path without suffix. Defaults to results/reports/test_eval_<lang>_<model>.",
    )
    parser.add_argument("--no-report", action="store_true", help="Print only; write no files.")
    return parser


def git_commit(root: Path) -> str:
    """Current HEAD, or ``"unknown"`` outside a working checkout."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def load_split(path: Path, *, limit: int | None = None) -> tuple[list[str], list[str]]:
    """Read a processed split as parallel source/target lists."""
    sources: list[str] = []
    targets: list[str] = []
    for row in read_jsonl(path):
        source = str(row.get("source_text") or "")
        target = str(row.get("target_text") or "")
        if not source or not target:
            continue
        sources.append(source)
        targets.append(target)
        if limit is not None and len(sources) >= limit:
            break

    if not sources:
        raise ValueError(f"{path} yielded no usable records.")
    return sources, targets


def _mean(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _length_stats(values: Sequence[int]) -> dict[str, float]:
    if not values:
        return {"min": 0, "max": 0, "mean": 0.0}
    return {"min": min(values), "max": max(values), "mean": round(sum(values) / len(values), 3)}


def selection_metrics(loaded: Any) -> dict[str, Any]:
    """The validation numbers the checkpoint was *selected* on, clearly labelled.

    Pulled from the model's own metadata rather than re-measured, because the
    point is to reproduce what was reported before, not to produce a second
    validation number that might differ.
    """
    metrics = (loaded.metadata.get("metrics") or {}) if loaded.metadata else {}
    best_cer = metrics.get("best_cer", loaded.metadata.get("best_cer"))
    return {
        "split": "validation",
        "cer": best_cer,
        "role": "model selection",
        "note": (
            "Validation CER is what the best checkpoint was chosen by. It is a "
            "model-selection statistic, NOT a held-out result, and must not be "
            "reported as the headline accuracy of this model."
        ),
    }


def build_report(
    *,
    config: Config,
    args: argparse.Namespace,
    loaded: Any,
    split_path: Path,
    sources: Sequence[str],
    targets: Sequence[str],
    predictions: Sequence[str],
    seconds: float,
    device: str,
) -> dict[str, Any]:
    result = evaluate_predictions(list(predictions), list(targets))
    count = len(targets)
    language_code = args.languages[0] if args.languages else "hin"

    samples = [
        {
            "source_text": source,
            "target_text": target,
            "prediction": prediction,
            "exact": prediction == target,
        }
        for source, target, prediction in list(
            zip(sources, targets, predictions, strict=True)
        )[: max(args.samples, 0)]
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project": f"{config.name} v{config.version}",
        "git_commit": git_commit(config.root),
        "evaluation": {
            "split": args.split,
            # The whole reason this script exists: say, in the artefact itself,
            # whether the number is held out.
            "held_out": args.split == "test",
            "records": count,
            "truncated": args.limit is not None and count >= args.limit,
            "limit": args.limit,
        },
        "metrics": {
            "cer": round(result.cer, 6),
            "exact_match": round(result.exact_match, 6),
            "count": result.count,
        },
        "selection_metrics": selection_metrics(loaded),
        "lengths": {
            "source": _length_stats([len(s) for s in sources]),
            "target": _length_stats([len(t) for t in targets]),
            "prediction": _length_stats([len(p) for p in predictions]),
            "average_source_length": _mean([len(s) for s in sources]),
            "average_target_length": _mean([len(t) for t in targets]),
        },
        "runtime": {
            "seconds": round(seconds, 3),
            "records_per_second": round(count / seconds, 2) if seconds > 0 else None,
            "device": device,
            "batch_size": args.batch_size,
            "max_decode_length": args.max_length,
            "decoding": "greedy",
        },
        "model": {
            "identifier": loaded.identifier,
            "kind": loaded.kind,
            "path": config.relative(loaded.path),
            "source_vocab_size": loaded.tokenizer.source_vocab_size,
            "target_vocab_size": loaded.tokenizer.target_vocab_size,
            "metadata": loaded.metadata,
        },
        "dataset": {
            "identifier": f"{config.default_source}/{language_code}",
            "file": config.relative(split_path),
            "source": config.default_source,
            "tokenizer_metadata": loaded.tokenizer.metadata,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "samples": samples,
    }


def render_markdown(report: dict[str, Any]) -> str:
    evaluation = report["evaluation"]
    metrics = report["metrics"]
    selection = report["selection_metrics"]
    runtime = report["runtime"]
    lengths = report["lengths"]

    held_out = "**held-out**" if evaluation["held_out"] else "**not held out**"
    lines = [
        f"# Transliteration evaluation -- {report['model']['identifier']}",
        "",
        f"- **Generated:** {report['generated_at']}",
        f"- **Git commit:** `{report['git_commit']}`",
        f"- **Model:** `{report['model']['path']}` ({report['model']['kind']})",
        f"- **Dataset:** `{report['dataset']['file']}`",
        f"- **Split:** `{evaluation['split']}` -- {held_out}",
        f"- **Records:** {evaluation['records']:,}",
        "",
        "## Headline result",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Test CER | {metrics['cer']:.4f} |",
        f"| Test exact match | {metrics['exact_match']:.4f} "
        f"({metrics['exact_match'] * 100:.2f}%) |",
        f"| Records | {metrics['count']:,} |",
        "",
        "## Validation numbers are not this result",
        "",
        selection["note"],
        "",
        "| Metric | Split | Value | Role |",
        "| --- | --- | ---: | --- |",
        f"| CER | {selection['split']} | "
        f"{selection['cer'] if selection['cer'] is not None else 'n/a'} | {selection['role']} |",
        f"| CER | {evaluation['split']} | {metrics['cer']:.4f} | held-out result |",
        "",
        "## Lengths",
        "",
        "| Series | min | mean | max |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name in ("source", "target", "prediction"):
        stats = lengths[name]
        lines.append(f"| {name} | {stats['min']} | {stats['mean']} | {stats['max']} |")

    lines += [
        "",
        "## Runtime",
        "",
        f"- {runtime['seconds']:.2f} s on {runtime['device']} "
        f"({runtime['records_per_second']} records/s)",
        f"- {runtime['decoding']} decoding, batch {runtime['batch_size']}, "
        f"max {runtime['max_decode_length']} characters",
        "",
        "## Samples",
        "",
        "| source | target | prediction | exact |",
        "| --- | --- | --- | :---: |",
    ]
    lines += [
        f"| `{s['source_text']}` | {s['target_text']} | {s['prediction']} "
        f"| {'yes' if s['exact'] else 'no'} |"
        for s in report["samples"]
    ]
    return "\n".join(lines) + "\n"


def print_console(report: dict[str, Any]) -> None:
    evaluation = report["evaluation"]
    metrics = report["metrics"]
    selection = report["selection_metrics"]

    print(f"\n{'=' * 74}")
    print(f"EVALUATION -- {report['model']['identifier']} on '{evaluation['split']}'")
    print(f"{'=' * 74}")
    print(f"  records            {evaluation['records']:,}")
    print(f"  CER                {metrics['cer']:.4f}")
    print(f"  exact match        {metrics['exact_match']:.4f}  "
          f"({metrics['exact_match'] * 100:.2f}%)")
    print(f"  held out           {'yes' if evaluation['held_out'] else 'NO'}")
    print(f"  runtime            {report['runtime']['seconds']:.2f}s on "
          f"{report['runtime']['device']}")
    selection_cer = selection["cer"]
    shown = f"{selection_cer:.4f}" if isinstance(selection_cer, (int, float)) else "n/a"
    print(f"\n  validation CER     {shown}   <- model selection only, not a held-out result")
    print()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config, logger = startup(args, SCRIPT)

    try:
        import torch  # noqa: F401
    except ImportError:
        print(
            "PyTorch is not installed. Evaluation needs it:\n"
            "  python -m pip install -r requirements/ml.txt",
            file=sys.stderr,
        )
        return 2

    languages = config.resolve_languages(args.languages)
    if len(languages) != 1:
        logger.error(
            "Evaluate one language at a time; got %s. Pass --languages hin.",
            ", ".join(language.code for language in languages),
        )
        return 2
    language = languages[0]

    source_name = args.source or config.default_source
    input_dir = config.resolve(
        args.input_dir or config.preprocessing.get("output_dir", "data/processed")
    )
    split_path = input_dir / source_name / language.code / f"{args.split}.jsonl"
    if not split_path.is_file():
        logger.error(
            "No %s split at %s. Run preprocessing first:\n"
            "    python scripts/preprocess_dataset.py --languages %s",
            args.split,
            config.relative(split_path),
            language.code,
        )
        return 1

    from indicpass.inference import load_bundle, transliterate
    from indicpass.seeding import describe_device

    model_path = config.resolve(args.model)
    logger.info("Loading %s", config.relative(model_path))
    loaded = load_bundle(model_path, device=args.device)
    device = describe_device(loaded.model.device)

    sources, targets = load_split(split_path, limit=args.limit)
    logger.info("Decoding %d records from %s", len(sources), config.relative(split_path))

    from indicpass.logging_utils import progress

    bar = progress(range(0, len(sources), args.batch_size), "evaluating")
    tracker = iter(bar)

    def tick(_done: int) -> None:
        next(tracker, None)

    started = time.perf_counter()
    predictions = transliterate(
        loaded,
        sources,
        max_length=args.max_length,
        batch_size=args.batch_size,
        progress=tick,
    )
    seconds = time.perf_counter() - started

    report = build_report(
        config=config,
        args=args,
        loaded=loaded,
        split_path=split_path,
        sources=sources,
        targets=targets,
        predictions=predictions,
        seconds=seconds,
        device=device,
    )

    print_console(report)

    if not args.no_report:
        if args.output is not None:
            base = config.resolve(args.output)
            base.parent.mkdir(parents=True, exist_ok=True)
        else:
            # e.g. test_eval_hin_v1 -- split, language and the model's version
            # suffix, so scoring a v2 model cannot overwrite the v1 report.
            version = loaded.identifier.rsplit("-", 1)[-1] or "v1"
            base = config.ensure_dir("reports") / f"{args.split}_eval_{language.code}_{version}"

        json_path = base.with_suffix(".json")
        json_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        md_path = base.with_suffix(".md")
        md_path.write_text(render_markdown(report), encoding="utf-8")
        logger.info("Report written to %s", config.relative(md_path))

    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
