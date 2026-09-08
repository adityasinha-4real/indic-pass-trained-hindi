"""Load a trained transliterator and run it over text.

Three callers now need the same two things -- get a model and tokenizer out of
storage, then greedy-decode a list of words with them: ``scripts/predict.py``,
``scripts/evaluate.py`` and the offline dictionary builder. This module is
where that lives so the three cannot drift apart and start reporting different
numbers for the same checkpoint.

Two storage layouts are supported and :func:`load_bundle` tells them apart by
looking at the path:

* a **bundle directory** (``models/final/indicpass-hin-v1/``) holding
  ``model.safetensors`` + ``config.json`` + ``tokenizer.json``. No pickle is
  executed, and this is what should be used for anything whose result gets
  reported.
* a **training checkpoint** (``runs/.../best.pt``), which is a torch pickle.
  Kept because it is what training writes and what export reads.

``torch`` is imported inside the functions, not at module scope. The password
engine imports :mod:`indicpass.password` on machines that never installed
``requirements/ml.txt``, and a top-level torch import here would make that fail.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "LoadedModel",
    "load_bundle",
    "transliterate",
]


@dataclass
class LoadedModel:
    """A model, its tokenizer, and where the two came from."""

    model: Any
    tokenizer: Any
    #: ``"bundle"`` or ``"checkpoint"`` -- which of the two layouts was read.
    kind: str
    #: Absolute path that was loaded.
    path: Path
    #: ``inference_metadata.json`` for a bundle; the checkpoint's own metadata
    #: otherwise. Provenance for the report, never used for computation.
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def identifier(self) -> str:
        """A short name for this model, for report headers."""
        return str(self.metadata.get("model_name") or self.path.name)


def _load_bundle_dir(path: Path) -> LoadedModel:
    import safetensors.torch

    from indicpass.model import ModelConfig, Seq2SeqTransliterator
    from indicpass.tokenizer import CharVocab, TransliterationTokenizer

    required = ("config.json", "model.safetensors", "tokenizer.json")
    missing = [name for name in required if not (path / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"{path} does not look like an inference bundle; missing "
            f"{', '.join(missing)}.\nExport one with:\n"
            "    python scripts/export_bundle.py --checkpoint runs/.../best.pt"
        )

    model_config = json.loads((path / "config.json").read_text(encoding="utf-8"))
    model = Seq2SeqTransliterator(ModelConfig.from_dict(model_config))
    model.load_state_dict(safetensors.torch.load_file(path / "model.safetensors"))

    tokenizer_data = json.loads((path / "tokenizer.json").read_text(encoding="utf-8"))
    tokenizer = TransliterationTokenizer(
        CharVocab(tokenizer_data["source_vocab"]),
        CharVocab(tokenizer_data["target_vocab"]),
        metadata=tokenizer_data.get("metadata") or {},
    )

    metadata: dict[str, Any] = {}
    meta_file = path / "inference_metadata.json"
    if meta_file.is_file():
        metadata = json.loads(meta_file.read_text(encoding="utf-8"))

    return LoadedModel(
        model=model, tokenizer=tokenizer, kind="bundle", path=path, metadata=metadata
    )


def _load_checkpoint_file(path: Path) -> LoadedModel:
    from indicpass.trainer import build_model_from_checkpoint, load_checkpoint

    payload = load_checkpoint(path)
    model, tokenizer = build_model_from_checkpoint(payload)
    # Everything except the weights: a checkpoint's tensors are megabytes and
    # have no business in a JSON report.
    metadata = {
        key: value
        for key, value in payload.items()
        if key not in {"model_state", "optimizer_state", "scheduler_state", "tokenizer"}
    }
    return LoadedModel(
        model=model, tokenizer=tokenizer, kind="checkpoint", path=path, metadata=metadata
    )


def load_bundle(path: Path, *, device: str | None = None) -> LoadedModel:
    """Load a safetensors bundle directory or a ``.pt`` checkpoint from *path*.

    The returned model is already on *device* and in eval mode, so a caller
    that forgets ``.eval()`` cannot accidentally measure dropout.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No model at {path}.")

    loaded = _load_bundle_dir(path) if path.is_dir() else _load_checkpoint_file(path)

    from indicpass.seeding import resolve_device

    resolved = resolve_device(device)
    loaded.model = loaded.model.to(resolved).eval()
    return loaded


def transliterate(
    loaded: LoadedModel,
    words: Sequence[str],
    *,
    max_length: int = 64,
    batch_size: int = 64,
    progress: Any = None,
) -> list[str]:
    """Greedy-decode *words* into native script, preserving input order.

    One word per element: the model is word-level, and splitting a phrase is
    the caller's job (``scripts/predict.py`` does it on whitespace).

    *progress* is an optional callable invoked with the number of words
    finished after each batch -- the dictionary build runs this over tens of
    thousands of words and needs to show something.
    """
    import torch
    from torch.nn.utils.rnn import pad_sequence

    from indicpass.tokenizer import PAD_ID

    if not words:
        return []

    device = loaded.model.device
    outputs: list[str] = []
    for start in range(0, len(words), batch_size):
        chunk = list(words[start : start + batch_size])
        encoded = [
            torch.tensor(loaded.tokenizer.encode_source(word), dtype=torch.long)
            for word in chunk
        ]
        source = pad_sequence(encoded, batch_first=True, padding_value=PAD_ID).to(device)
        lengths = torch.tensor([len(ids) for ids in encoded], dtype=torch.long)

        generated = loaded.model.greedy_decode(source, lengths, max_length=max_length)
        outputs.extend(loaded.tokenizer.decode_target(row) for row in generated.tolist())

        if progress is not None:
            progress(len(outputs))

    return outputs
