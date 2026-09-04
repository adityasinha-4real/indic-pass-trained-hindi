"""Package a trained PyTorch checkpoint into a portable deployment bundle.

    python scripts/export_bundle.py \
        --checkpoint runs/hindi_baseline_v1/checkpoints/best.pt \
        --name indicpass-hin-v1

The resulting bundle directory (e.g. ``models/final/indicpass-hin-v1/``) contains:
- ``model.safetensors``         Weights in safe tensor format (no pickle execution)
- ``config.json``               Model architecture configuration
- ``tokenizer.json``            Source and target character vocabularies
- ``tokenizer_config.json``     Tokenizer parameters and special token definitions
- ``special_tokens_map.json``   Special tokens mapping
- ``inference_metadata.json``   Provenance (git commit, dataset revision, metrics, framework versions)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import _bootstrap  # noqa: F401
from indicpass.cli import run_cli, startup
from indicpass.config import Config, load_config
from indicpass.trainer import build_model_from_checkpoint, load_checkpoint

SCRIPT = "export_bundle"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="export_bundle.py",
        description="Package a checkpoint into a portable inference bundle under models/final/.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--checkpoint",
        "-k",
        type=Path,
        required=True,
        metavar="FILE",
        help="Path to checkpoint file, e.g. runs/hindi_baseline_v1/checkpoints/best.pt",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        metavar="DIR",
        help="Output directory for the bundle (default: models/final/<name>)",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="indicpass-hin-v1",
        metavar="NAME",
        help="Model bundle name (default: indicpass-hin-v1)",
    )
    return parser


def get_git_commit(project_root: Path) -> str:
    """Fetch the current git commit SHA, returning 'unknown' on failure."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "unknown"


def get_dataset_manifest_info(config: Config, source: str) -> dict[str, Any]:
    """Retrieve revision and record counts from raw/processed manifests if available."""
    info: dict[str, Any] = {"source": source, "revision": "unknown", "train_records": 0}
    
    raw_manifest = config.resolve(config.path("data_raw_aksharantar")) / "download_manifest.json"
    if raw_manifest.is_file():
        try:
            data = json.loads(raw_manifest.read_text(encoding="utf-8"))
            info["revision"] = data.get("revision") or "unknown"
        except Exception:
            pass

    proc_manifest = config.resolve(config.path("data_processed")) / "preprocess_manifest.json"
    if proc_manifest.is_file():
        try:
            data = json.loads(proc_manifest.read_text(encoding="utf-8"))
            languages = data.get("languages", {})
            hin_data = languages.get("hin", {})
            info["train_records"] = hin_data.get("per_split", {}).get("train", 0)
        except Exception:
            pass

    return info


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config, logger = startup(args, SCRIPT)

    checkpoint_path = config.resolve(args.checkpoint)
    payload = load_checkpoint(checkpoint_path)
    model, tokenizer = build_model_from_checkpoint(payload)

    try:
        import torch
        import safetensors.torch
    except ImportError:
        logger.error("safetensors is required to export bundles: pip install safetensors")
        return 1

    bundle_name = args.name
    if args.output_dir:
        bundle_dir = config.resolve(args.output_dir)
    else:
        bundle_dir = config.resolve(config.path("model_final")) / bundle_name

    bundle_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Exporting bundle '%s' to %s", bundle_name, config.relative(bundle_dir))

    # 1. model.safetensors
    weights_path = bundle_dir / "model.safetensors"
    safetensors.torch.save_file(model.state_dict(), weights_path)
    logger.info("  Saved weights -> %s", config.relative(weights_path))

    # 2. config.json
    config_path = bundle_dir / "config.json"
    config_payload = model.config.as_dict()
    config_path.write_text(json.dumps(config_payload, indent=2) + "\n", encoding="utf-8")
    logger.info("  Saved model config -> %s", config.relative(config_path))

    # 3. tokenizer.json
    tok_path = bundle_dir / "tokenizer.json"
    tok_payload = {
        "source_vocab": tokenizer.source.to_list(),
        "target_vocab": tokenizer.target.to_list(),
        "metadata": tokenizer.metadata,
    }
    tok_path.write_text(json.dumps(tok_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("  Saved tokenizer -> %s", config.relative(tok_path))

    # 4. tokenizer_config.json
    tok_cfg_path = bundle_dir / "tokenizer_config.json"
    tok_cfg_payload = {
        "source_vocab_size": tokenizer.source_vocab_size,
        "target_vocab_size": tokenizer.target_vocab_size,
        "pad_token": "<PAD>",
        "bos_token": "<BOS>",
        "eos_token": "<EOS>",
        "unk_token": "<UNK>",
    }
    tok_cfg_path.write_text(json.dumps(tok_cfg_payload, indent=2) + "\n", encoding="utf-8")
    logger.info("  Saved tokenizer config -> %s", config.relative(tok_cfg_path))

    # 5. special_tokens_map.json
    special_path = bundle_dir / "special_tokens_map.json"
    special_payload = {
        "pad_token": "<PAD>",
        "bos_token": "<BOS>",
        "eos_token": "<EOS>",
        "unk_token": "<UNK>",
    }
    special_path.write_text(json.dumps(special_payload, indent=2) + "\n", encoding="utf-8")
    logger.info("  Saved special tokens map -> %s", config.relative(special_path))

    # 6. inference_metadata.json
    git_commit = get_git_commit(config.root)
    dataset_info = get_dataset_manifest_info(
        config, payload.get("training_config", {}).get("dataset_source", "aksharantar")
    )
    meta_path = bundle_dir / "inference_metadata.json"
    meta_payload = {
        "model_name": bundle_name,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "languages": [payload.get("training_config", {}).get("language", "hin")],
        "direction": "roman_to_native",
        "max_input_length": payload.get("training_config", {}).get("max_decode_length", 64),
        "max_output_length": payload.get("training_config", {}).get("max_decode_length", 64),
        "git_commit": git_commit,
        "dataset": dataset_info,
        "metrics": {
            "best_cer": payload.get("best_cer"),
        },
        "framework": {
            "torch": torch.__version__,
            "safetensors": getattr(safetensors, "__version__", "unknown"),
        },
    }
    meta_path.write_text(json.dumps(meta_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("  Saved inference metadata -> %s", config.relative(meta_path))

    logger.info("Bundle successfully exported to %s", config.relative(bundle_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
