"""Train the Hindi transliteration baseline.

    python scripts/train.py --config config/training/hindi_debug.yaml
    python scripts/train.py --config config/training/hindi_baseline.yaml
    python scripts/train.py --config config/training/hindi_baseline.yaml \
        --max-train-records 10000

Everything the run produces lands under ``runs/<name>/``: checkpoints, the
tokenizer, the resolved config, and metrics.json. That directory is
git-ignored and is the only thing training writes -- the processed dataset is
read-only here.

Resume an interrupted run with ``--resume``, which picks up ``last.pt``
including optimizer, scheduler and RNG state.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

import _bootstrap  # noqa: F401  (sys.path side effect)
from indicpass.cli import run_cli, startup
from indicpass.config import Config, ConfigError
from indicpass.logging_utils import progress

SCRIPT = "train"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="train.py",
        description="Train a character-level transliteration model.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        required=True,
        metavar="FILE",
        help="Training config YAML, e.g. config/training/hindi_baseline.yaml",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Console verbosity. Overrides config/project.yaml.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Continue from the run's last.pt (optimizer, scheduler, RNG included).",
    )
    parser.add_argument(
        "--device",
        metavar="DEV",
        help="Override the device: cuda, cpu, cuda:1, auto.",
    )

    override = parser.add_argument_group("config overrides")
    override.add_argument(
        "--max-train-records",
        type=int,
        metavar="N",
        help="Train on the first N records only. This is how the scale-up "
        "stages are run -- no need to copy the config or the data.",
    )
    override.add_argument("--epochs", type=int, metavar="N")
    override.add_argument("--batch-size", type=int, metavar="N")
    override.add_argument("--learning-rate", type=float, metavar="LR")
    override.add_argument("--seed", type=int, metavar="N")
    override.add_argument(
        "--name", metavar="NAME", help="Run name; sets the runs/<name>/ directory."
    )
    return parser


def load_training_config(path: Path) -> dict[str, Any]:
    """Read a training YAML into a flat dict."""
    if not path.is_file():
        raise ConfigError(
            f"No training config at {path}.\n"
            "Shipped configs live in config/training/ -- try:\n"
            "  python scripts/train.py --config config/training/hindi_debug.yaml"
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level.")
    return data


def apply_overrides(data: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """Layer CLI flags over the file, so a stage needs no new config file."""
    mapping = {
        "max_train_records": args.max_train_records,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "seed": args.seed,
        "name": args.name,
        "device": args.device,
    }
    for key, value in mapping.items():
        if value is not None:
            data[key] = value
    return data


def split_path(config: Config, language: str, source: str, split: str) -> Path:
    """Locate a processed split, with an actionable error when it is absent."""
    path = config.path("data_processed", source, language, f"{split}.jsonl")
    if not path.is_file():
        raise ConfigError(
            f"Missing processed data: {config.relative(path)}\n"
            "Acquire and preprocess the dataset first:\n"
            f"  python scripts/download_datasets.py --languages {language}\n"
            f"  python scripts/preprocess_dataset.py --languages {language}\n"
            f"  python scripts/validate_dataset.py --languages {language}"
        )
    return path


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config, logger = startup(args, SCRIPT)

    settings = apply_overrides(load_training_config(config.resolve(args.config)), args)

    # Imported here, not at module scope: every other script in this directory
    # runs on requirements/base.txt alone, and importing torch at the top would
    # make `--help` fail on a machine that has not installed ml.txt.
    try:
        import torch
    except ImportError:
        print(
            "PyTorch is not installed. Training needs requirements/ml.txt:\n"
            "  python -m pip install -r requirements/ml.txt\n"
            "See the GPU notes in that file and in README.md.",
            file=sys.stderr,
        )
        return 2

    from indicpass.data import TransliterationDataset, build_dataloader
    from indicpass.model import Seq2SeqTransliterator
    from indicpass.seeding import describe_device, resolve_device, seed_everything
    from indicpass.tokenizer import TransliterationTokenizer
    from indicpass.trainer import Trainer, TrainingConfig

    training = TrainingConfig.from_dict(settings)
    seed_everything(training.seed, deterministic=training.deterministic)
    device = resolve_device(training.device)

    # Locate the data before creating anything: a run directory left behind by
    # a command that could never have worked is just litter to clean up.
    language, source = training.language, training.dataset_source
    train_file = split_path(config, language, source, "train")
    validation_file = split_path(config, language, source, "validation")

    run_dir = config.resolve(training.output_dir) / training.name
    run_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Run '%s' -> %s", training.name, config.relative(run_dir))
    logger.info("Device: %s | torch %s", describe_device(device), torch.__version__)
    if device.type == "cpu" and not training.max_train_records:
        logger.warning(
            "Training on CPU with no record limit. Fine for the debug config, "
            "impractically slow for the full 1.3M-record baseline."
        )

    # -- data --------------------------------------------------------------

    from indicpass.data import load_pairs

    train_pairs = load_pairs(train_file, limit=training.max_train_records)
    logger.info("Train: %s pairs from %s", f"{len(train_pairs):,}", config.relative(train_file))

    # -- tokenizer ---------------------------------------------------------
    # Fitted on the training pairs ONLY. A character first seen in validation
    # must arrive as <UNK>, exactly as it would in production.
    tokenizer = TransliterationTokenizer.fit(
        train_pairs,
        min_frequency=training.min_char_frequency,
        metadata={
            "language": language,
            "dataset_source": source,
            "fitted_on": "train",
            "train_file": config.relative(train_file),
        },
    )
    tokenizer_path = tokenizer.save(run_dir / "tokenizer" / "tokenizer.json")
    logger.info(
        "Vocabulary: %d source chars, %d target chars -> %s",
        tokenizer.source_vocab_size,
        tokenizer.target_vocab_size,
        config.relative(tokenizer_path),
    )

    train_dataset = TransliterationDataset(train_pairs, tokenizer)
    train_loader = build_dataloader(
        train_dataset,
        batch_size=training.batch_size,
        shuffle=True,
        num_workers=training.num_workers,
        seed=training.seed,
        pin_memory=device.type == "cuda",
    )

    # The debug config evaluates on its own training subset: the question it
    # asks is whether the model can memorise what it was shown.
    if settings.get("evaluate_on_train_subset"):
        eval_dataset = train_dataset
        logger.info("Evaluating on the TRAINING subset (overfit check).")
    else:
        eval_dataset = TransliterationDataset.from_jsonl(
            validation_file, tokenizer, limit=training.max_validation_records
        )
        logger.info(
            "Validation: %s pairs from %s",
            f"{len(eval_dataset):,}",
            config.relative(validation_file),
        )

    eval_loader = build_dataloader(
        eval_dataset,
        batch_size=training.eval_batch_size,
        shuffle=False,
        num_workers=training.num_workers,
        pin_memory=device.type == "cuda",
    )

    # -- model -------------------------------------------------------------
    model = Seq2SeqTransliterator(
        training.model_config(tokenizer.source_vocab_size, tokenizer.target_vocab_size)
    )
    logger.info("Model: %s trainable parameters", f"{model.count_parameters():,}")

    trainer = Trainer(model, tokenizer, training, device, run_dir, logger=logger)

    if args.resume:
        last = run_dir / "checkpoints" / "last.pt"
        trainer.load_checkpoint(last, resume=True)
        logger.info(
            "Resumed from %s at epoch %d (best CER %.4f)",
            config.relative(last),
            trainer.epoch,
            trainer.best_cer,
        )
        if trainer.epoch >= training.epochs:
            logger.warning(
                "Checkpoint is at epoch %d and the config asks for %d. "
                "Raise `epochs` or pass --epochs to continue.",
                trainer.epoch,
                training.epochs,
            )

    # Snapshot exactly what ran, resolved overrides included.
    (run_dir / "config.yaml").write_text(
        yaml.safe_dump(training.as_dict(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    def make_bar(loader: Any, label: str) -> Any:
        return progress(loader, description=label, total=len(loader))

    summary = trainer.fit(train_loader, eval_loader, progress_factory=make_bar)

    logger.info(
        "Done. %d epochs, best CER %s",
        summary["epochs_completed"],
        "n/a" if summary["best_cer"] is None else f"{summary['best_cer']:.4f}",
    )
    logger.info("Checkpoints: %s", config.relative(run_dir / "checkpoints"))
    print(json.dumps({"run": training.name, "best_cer": summary["best_cer"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
