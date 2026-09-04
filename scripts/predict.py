"""Transliterate Romanized text with a trained checkpoint.

    python scripts/predict.py --checkpoint runs/hindi_baseline_v1/checkpoints/best.pt \
        --text "namaste"
    -> नमस्ते

    python scripts/predict.py -k runs/hindi_baseline_v1/checkpoints/best.pt \
        --text "namaste" "kaise" "ho"

    type words.txt | python scripts/predict.py -k .../best.pt

Greedy decoding, one word at a time. The model is word-level, so a multi-word
line is split on whitespace and each word transliterated independently; that
is a real limitation of the training data, not of this script.

The checkpoint carries its own tokenizer, so nothing else is needed to run it.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import _bootstrap  # noqa: F401  (sys.path side effect)
from indicpass.cli import run_cli
from indicpass.config import load_config

SCRIPT = "predict"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="predict.py",
        description="Transliterate Romanized text using a trained checkpoint.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--checkpoint",
        "-k",
        type=Path,
        required=True,
        metavar="FILE",
        help="Checkpoint to load, e.g. runs/hindi_baseline_v1/checkpoints/best.pt",
    )
    parser.add_argument(
        "--text",
        "-t",
        nargs="+",
        metavar="TEXT",
        help="Text to transliterate. Reads stdin when omitted.",
    )
    parser.add_argument(
        "--device",
        metavar="DEV",
        help="cuda, cpu or auto (default: auto).",
    )
    parser.add_argument(
        "--max-length",
        type=int,
        default=64,
        metavar="N",
        help="Maximum characters to generate per word (default: 64).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        metavar="N",
        help="Words decoded per forward pass (default: 64).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON lines instead of plain text.",
    )
    return parser


def read_inputs(args: argparse.Namespace) -> list[str]:
    """Collect input lines from --text or stdin."""
    if args.text:
        return list(args.text)
    if sys.stdin.isatty():
        raise SystemExit(
            "Nothing to transliterate. Pass --text WORD, or pipe input on stdin."
        )
    return [line.strip() for line in sys.stdin if line.strip()]


def transliterate(
    model,
    tokenizer,
    words: Sequence[str],
    *,
    device,
    max_length: int,
    batch_size: int,
) -> list[str]:
    """Greedy-decode *words*, preserving order."""
    import torch
    from torch.nn.utils.rnn import pad_sequence

    from indicpass.tokenizer import PAD_ID

    outputs: list[str] = []
    for start in range(0, len(words), batch_size):
        chunk = words[start : start + batch_size]
        encoded = [
            torch.tensor(tokenizer.encode_source(word), dtype=torch.long)
            for word in chunk
        ]
        source = pad_sequence(encoded, batch_first=True, padding_value=PAD_ID).to(device)
        lengths = torch.tensor([len(ids) for ids in encoded], dtype=torch.long)

        generated = model.greedy_decode(source, lengths, max_length=max_length)
        outputs.extend(tokenizer.decode_target(row) for row in generated.tolist())
    return outputs


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config()

    try:
        import torch  # noqa: F401
    except ImportError:
        print(
            "PyTorch is not installed. Inference needs it:\n"
            "  python -m pip install -r requirements/ml.txt",
            file=sys.stderr,
        )
        return 2

    from indicpass.seeding import resolve_device
    from indicpass.trainer import build_model_from_checkpoint, load_checkpoint

    checkpoint_path = config.resolve(args.checkpoint)
    if checkpoint_path.is_dir():
        from indicpass.model import ModelConfig, Seq2SeqTransliterator
        from indicpass.tokenizer import CharVocab, TransliterationTokenizer
        import safetensors.torch

        config_data = json.loads((checkpoint_path / "config.json").read_text(encoding="utf-8"))
        model = Seq2SeqTransliterator(ModelConfig.from_dict(config_data))
        state_dict = safetensors.torch.load_file(checkpoint_path / "model.safetensors")
        model.load_state_dict(state_dict)

        tok_data = json.loads((checkpoint_path / "tokenizer.json").read_text(encoding="utf-8"))
        tokenizer = TransliterationTokenizer(
            CharVocab(tok_data["source_vocab"]),
            CharVocab(tok_data["target_vocab"]),
            metadata=tok_data.get("metadata") or {},
        )
    else:
        payload = load_checkpoint(checkpoint_path)
        model, tokenizer = build_model_from_checkpoint(payload)

    device = resolve_device(args.device)
    model = model.to(device).eval()

    lines = read_inputs(args)
    for line in lines:
        # Word-level model: split the line, transliterate each word, rejoin.
        words = line.split()
        if not words:
            continue
        predictions = transliterate(
            model,
            tokenizer,
            words,
            device=device,
            max_length=args.max_length,
            batch_size=args.batch_size,
        )
        result = " ".join(predictions)
        if args.json:
            print(json.dumps({"source": line, "prediction": result}, ensure_ascii=False))
        else:
            print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
