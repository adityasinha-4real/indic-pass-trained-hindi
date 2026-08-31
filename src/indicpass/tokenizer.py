"""Character-level vocabularies for Romanized -> native transliteration.

Transliteration is a character-rewriting task, so characters are the right
unit. A subword tokenizer would have to be trained, would fragment rare
spellings unpredictably, and would add a dependency for no accuracy -- Hindi
needs roughly 40 Roman symbols and 130 Devanagari ones, which is a vocabulary
small enough to read in full.

Source and target get **separate** vocabularies. They share no characters, and
keeping them apart means the decoder's softmax covers ~130 classes instead of
~170, none of which it could ever legally emit.

Special tokens occupy fixed low ids in every vocabulary ever built:

    0  <PAD>   never contributes to the loss; see IGNORE_INDEX
    1  <BOS>   decoder start symbol
    2  <EOS>   generation stops here
    3  <UNK>   character not seen during fitting

PAD is deliberately id 0 so that a zero-filled tensor is already a padded
batch, and so ``padding_idx=0`` in an embedding needs no explanation.

Vocabularies are built from the TRAINING SPLIT ALONE. A character that appears
only in validation or test must arrive at evaluation time as <UNK>, exactly as
an unseen character would in production. Fitting on all splits would leak, and
would quietly flatter every metric.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

__all__ = [
    "BOS",
    "BOS_ID",
    "EOS",
    "EOS_ID",
    "IGNORE_INDEX",
    "PAD",
    "PAD_ID",
    "SPECIAL_TOKENS",
    "UNK",
    "UNK_ID",
    "CharVocab",
    "TransliterationTokenizer",
]

PAD, BOS, EOS, UNK = "<PAD>", "<BOS>", "<EOS>", "<UNK>"
SPECIAL_TOKENS: tuple[str, ...] = (PAD, BOS, EOS, UNK)
PAD_ID, BOS_ID, EOS_ID, UNK_ID = 0, 1, 2, 3

#: Value handed to ``nn.CrossEntropyLoss(ignore_index=...)``. Same as PAD_ID,
#: named separately because the two mean different things at the call site.
IGNORE_INDEX = PAD_ID

_FORMAT_VERSION = 1


class CharVocab:
    """A bidirectional character <-> id map with the four special tokens."""

    def __init__(self, tokens: Iterable[str]) -> None:
        ordered = list(tokens)
        if ordered[: len(SPECIAL_TOKENS)] != list(SPECIAL_TOKENS):
            raise ValueError(
                f"A vocabulary must begin with {SPECIAL_TOKENS}; got {ordered[:4]}."
            )
        duplicates = [t for t, n in Counter(ordered).items() if n > 1]
        if duplicates:
            raise ValueError(f"Duplicate vocabulary entries: {duplicates!r}")

        self.itos: tuple[str, ...] = tuple(ordered)
        self.stoi: dict[str, int] = {token: index for index, token in enumerate(self.itos)}

    # -- construction ------------------------------------------------------

    @classmethod
    def fit(cls, texts: Iterable[str], *, min_frequency: int = 1) -> CharVocab:
        """Build a vocabulary from *texts*.

        Ordering is by descending frequency, ties broken by codepoint. Both
        keys are deterministic, so the same corpus always yields the same ids
        -- which is what makes a checkpoint's embedding matrix meaningful on
        another machine. Never iterate a set to build this.
        """
        counts = Counter(char for text in texts for char in text)
        kept = [char for char, n in counts.items() if n >= min_frequency]
        kept.sort(key=lambda char: (-counts[char], char))
        return cls([*SPECIAL_TOKENS, *kept])

    # -- lookup ------------------------------------------------------------

    def __len__(self) -> int:
        return len(self.itos)

    def __contains__(self, char: object) -> bool:
        return char in self.stoi

    def encode(self, text: str, *, add_bos: bool = False, add_eos: bool = False) -> list[int]:
        """Characters -> ids. Unknown characters become ``UNK_ID``."""
        ids = [self.stoi.get(char, UNK_ID) for char in text]
        if add_bos:
            ids.insert(0, BOS_ID)
        if add_eos:
            ids.append(EOS_ID)
        return ids

    def decode(self, ids: Iterable[int], *, strip_specials: bool = True) -> str:
        """Ids -> characters, stopping at the first EOS.

        Out-of-range ids decode to <UNK> rather than raising: a freshly
        initialised model emits nonsense, and debugging it should not require
        catching exceptions.
        """
        out: list[str] = []
        for value in ids:
            index = int(value)
            if index == EOS_ID:
                break
            if strip_specials and index in (PAD_ID, BOS_ID):
                continue
            token = self.itos[index] if 0 <= index < len(self.itos) else UNK
            if strip_specials and token in SPECIAL_TOKENS and token != UNK:
                continue
            out.append(token)
        return "".join(out)

    def to_list(self) -> list[str]:
        return list(self.itos)


class TransliterationTokenizer:
    """The source and target vocabularies for one language, as one object.

    Saved next to a checkpoint so that inference can reconstruct exactly the
    id mapping the model was trained with. A checkpoint without its tokenizer
    is unusable, which is why :meth:`save` writes both vocabularies into a
    single file.
    """

    def __init__(
        self,
        source: CharVocab,
        target: CharVocab,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.source = source
        self.target = target
        self.metadata: dict[str, Any] = dict(metadata or {})

    # -- construction ------------------------------------------------------

    @classmethod
    def fit(
        cls,
        pairs: Iterable[tuple[str, str]],
        *,
        min_frequency: int = 1,
        metadata: Mapping[str, Any] | None = None,
    ) -> TransliterationTokenizer:
        """Fit both vocabularies from ``(source_text, target_text)`` pairs.

        *pairs* must come from the training split only.
        """
        source_texts: list[str] = []
        target_texts: list[str] = []
        for source_text, target_text in pairs:
            source_texts.append(source_text)
            target_texts.append(target_text)

        if not source_texts:
            raise ValueError("Cannot fit a tokenizer on zero pairs.")

        return cls(
            CharVocab.fit(source_texts, min_frequency=min_frequency),
            CharVocab.fit(target_texts, min_frequency=min_frequency),
            metadata={
                "fitted_on_pairs": len(source_texts),
                "min_frequency": min_frequency,
                **dict(metadata or {}),
            },
        )

    # -- use ---------------------------------------------------------------

    @property
    def source_vocab_size(self) -> int:
        return len(self.source)

    @property
    def target_vocab_size(self) -> int:
        return len(self.target)

    def encode_source(self, text: str) -> list[int]:
        """Source ids, EOS-terminated so the encoder sees where input ends."""
        return self.source.encode(text, add_eos=True)

    def encode_target(self, text: str) -> list[int]:
        """Target ids wrapped in BOS/EOS, ready to be shifted for teacher forcing."""
        return self.target.encode(text, add_bos=True, add_eos=True)

    def decode_target(self, ids: Iterable[int]) -> str:
        return self.target.decode(ids)

    # -- persistence -------------------------------------------------------

    def save(self, path: Path) -> Path:
        """Write both vocabularies to one JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format_version": _FORMAT_VERSION,
            "special_tokens": list(SPECIAL_TOKENS),
            "source_vocab": self.source.to_list(),
            "target_vocab": self.target.to_list(),
            "metadata": self.metadata,
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return path

    @classmethod
    def load(cls, path: Path) -> TransliterationTokenizer:
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(
                f"No tokenizer at {path}. It is written beside the checkpoint at "
                "training time; a checkpoint cannot be used without it."
            )
        payload = json.loads(path.read_text(encoding="utf-8"))

        version = int(payload.get("format_version", 0))
        if version != _FORMAT_VERSION:
            raise ValueError(
                f"{path} is tokenizer format v{version}, this build reads "
                f"v{_FORMAT_VERSION}."
            )
        return cls(
            CharVocab(payload["source_vocab"]),
            CharVocab(payload["target_vocab"]),
            metadata=payload.get("metadata") or {},
        )

    def __repr__(self) -> str:  # pragma: no cover - display only
        return (
            f"<TransliterationTokenizer source={self.source_vocab_size} "
            f"target={self.target_vocab_size}>"
        )
