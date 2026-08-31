"""PyTorch dataset and batching for the processed JSONL splits.

Loading strategy: the whole split is read into memory as ``(source, target)``
string pairs, and nothing else.

That is a deliberate choice rather than a shortcut. Hindi's train split is
1,299,143 records / 270 MB on disk, but almost all of that is JSON syntax and
the five fields training does not use. Keeping only the two text fields costs
roughly 150 MB of Python strings -- affordable on any machine that can hold a
model -- and buys random access, which is what shuffling needs. Memory-mapped
line indexing would save a hundred megabytes and cost a JSON parse per item on
every epoch, in the dataloader's hot path.

If a future split genuinely does not fit, the place to change is
:class:`TransliterationDataset`: swap the eager list for an offset index and
keep the same interface.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import torch
from torch.nn.utils.rnn import pad_sequence
from torch.utils.data import DataLoader, Dataset

from indicpass.records import read_jsonl
from indicpass.tokenizer import PAD_ID, TransliterationTokenizer

__all__ = [
    "Batch",
    "TransliterationDataset",
    "build_dataloader",
    "collate_batch",
    "load_pairs",
]


def load_pairs(path: Path, *, limit: int | None = None) -> list[tuple[str, str]]:
    """Read a processed JSONL split as ``(source_text, target_text)`` pairs.

    *limit* truncates deterministically -- the first N lines of a file whose
    order is itself deterministic -- so a subset run is reproducible without
    materialising a separate subset file on disk.
    """
    path = Path(path)
    pairs: list[tuple[str, str]] = []
    for row in read_jsonl(path):
        source = row.get("source_text") or ""
        target = row.get("target_text") or ""
        if not source or not target:
            continue
        pairs.append((source, target))
        if limit is not None and len(pairs) >= limit:
            break

    if not pairs:
        raise ValueError(
            f"{path} yielded no usable pairs. Has preprocessing been run?\n"
            "  python scripts/preprocess_dataset.py --languages hin"
        )
    return pairs


class TransliterationDataset(Dataset):
    """Encoded ``(source, target)`` pairs for one split.

    Encoding happens per item rather than up front. It is a dict lookup per
    character, far cheaper than holding 1.3M pairs of int lists, and it keeps
    the dataset usable with ``num_workers > 0`` without pickling a large
    tensor cache into every worker.
    """

    def __init__(
        self,
        pairs: Sequence[tuple[str, str]],
        tokenizer: TransliterationTokenizer,
    ) -> None:
        if not pairs:
            raise ValueError("TransliterationDataset needs at least one pair.")
        self.pairs = list(pairs)
        self.tokenizer = tokenizer

    @classmethod
    def from_jsonl(
        cls,
        path: Path,
        tokenizer: TransliterationTokenizer,
        *,
        limit: int | None = None,
    ) -> TransliterationDataset:
        return cls(load_pairs(path, limit=limit), tokenizer)

    def __len__(self) -> int:
        return len(self.pairs)

    def __getitem__(self, index: int) -> dict[str, Any]:
        source_text, target_text = self.pairs[index]
        return {
            "source": torch.tensor(
                self.tokenizer.encode_source(source_text), dtype=torch.long
            ),
            # <BOS> ... <EOS>; the trainer shifts this into input and label.
            "target": torch.tensor(
                self.tokenizer.encode_target(target_text), dtype=torch.long
            ),
            "source_text": source_text,
            "target_text": target_text,
        }


class Batch:
    """One padded, batch-first batch.

    Attributes
    ----------
    source, target:
        ``(batch, time)`` id tensors padded with ``PAD_ID``.
    source_lengths:
        ``(batch,)`` true lengths, on CPU. ``pack_padded_sequence`` requires
        CPU lengths, so they are deliberately never moved to the device.
    source_texts, target_texts:
        The original strings, kept for computing CER against exactly what the
        record said rather than against a decode of the ids.
    """

    __slots__ = ("source", "source_lengths", "source_texts", "target", "target_texts")

    def __init__(
        self,
        source: torch.Tensor,
        source_lengths: torch.Tensor,
        target: torch.Tensor,
        source_texts: list[str],
        target_texts: list[str],
    ) -> None:
        self.source = source
        self.source_lengths = source_lengths
        self.target = target
        self.source_texts = source_texts
        self.target_texts = target_texts

    def __len__(self) -> int:
        return self.source.size(0)

    def to(self, device: torch.device | str) -> Batch:
        """Move the id tensors to *device*, leaving lengths on the CPU."""
        return Batch(
            self.source.to(device),
            self.source_lengths,
            self.target.to(device),
            self.source_texts,
            self.target_texts,
        )


def collate_batch(items: Iterable[dict[str, Any]]) -> Batch:
    """Pad a list of dataset items into a :class:`Batch`.

    Padding uses ``PAD_ID`` (0) on both sides. The loss ignores it via
    ``ignore_index``; the encoder ignores it via packed sequences. Nothing
    downstream should ever have to strip it by hand.
    """
    rows = list(items)
    if not rows:
        raise ValueError("collate_batch() received an empty batch.")

    sources = [row["source"] for row in rows]
    targets = [row["target"] for row in rows]

    return Batch(
        source=pad_sequence(sources, batch_first=True, padding_value=PAD_ID),
        # Lengths describe the unpadded input and must stay on the CPU.
        source_lengths=torch.tensor([len(s) for s in sources], dtype=torch.long),
        target=pad_sequence(targets, batch_first=True, padding_value=PAD_ID),
        source_texts=[row["source_text"] for row in rows],
        target_texts=[row["target_text"] for row in rows],
    )


def build_dataloader(
    dataset: TransliterationDataset,
    *,
    batch_size: int,
    shuffle: bool,
    num_workers: int = 0,
    seed: int | None = None,
    pin_memory: bool = False,
) -> DataLoader:
    """Wrap *dataset* in a DataLoader with IndicPass's collate function.

    A seeded generator is attached when shuffling so that two runs with the
    same seed visit examples in the same order.
    """
    generator = None
    if shuffle and seed is not None:
        generator = torch.Generator()
        generator.manual_seed(int(seed))

    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=num_workers,
        collate_fn=collate_batch,
        generator=generator,
        pin_memory=pin_memory,
        # Workers are expensive to respawn each epoch on Windows.
        persistent_workers=num_workers > 0,
        drop_last=False,
    )
