"""Dataset loading and batching.

Skipped wholesale when torch is absent: the dataset pipeline runs on
requirements/base.txt, and a development machine that never trains should
still get a green suite.
"""

from __future__ import annotations

import json

import pytest

torch = pytest.importorskip("torch", reason="requires requirements/ml.txt")

from indicpass.data import (  # noqa: E402
    TransliterationDataset,
    build_dataloader,
    collate_batch,
    load_pairs,
)
from indicpass.tokenizer import (  # noqa: E402
    BOS_ID,
    EOS_ID,
    PAD_ID,
    TransliterationTokenizer,
)

PAIRS = [
    ("namaste", "नमस्ते"),
    ("kaise", "कैसे"),
    ("ho", "हो"),
    ("dhanyavaad", "धन्यवाद"),
]


@pytest.fixture
def tokenizer():
    return TransliterationTokenizer.fit(PAIRS)


@pytest.fixture
def jsonl_file(tmp_path):
    """A processed split in the real record schema."""
    path = tmp_path / "train.jsonl"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for index, (source, target) in enumerate(PAIRS):
            handle.write(
                json.dumps(
                    {
                        "record_id": f"{index:016x}",
                        "language": "hin",
                        "script": "Deva",
                        "source_text": source,
                        "target_text": target,
                        "dataset_source": "aksharantar",
                        "subsource": "Dakshina",
                        "split": "train",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return path


# -- JSONL loading ---------------------------------------------------------


def test_load_pairs_extracts_source_and_target(jsonl_file):
    assert load_pairs(jsonl_file) == PAIRS


def test_load_pairs_honours_a_limit(jsonl_file):
    assert load_pairs(jsonl_file, limit=2) == PAIRS[:2]


def test_limit_is_deterministic(jsonl_file):
    # This is what makes --max-train-records a stable subset rather than a
    # different sample on every run.
    assert load_pairs(jsonl_file, limit=3) == load_pairs(jsonl_file, limit=3)


def test_records_missing_text_are_skipped(tmp_path):
    path = tmp_path / "train.jsonl"
    path.write_text(
        json.dumps({"source_text": "", "target_text": "क"})
        + "\n"
        + json.dumps({"source_text": "ok", "target_text": "ठीक"})
        + "\n",
        encoding="utf-8",
    )
    assert load_pairs(path) == [("ok", "ठीक")]


def test_an_empty_split_says_to_run_preprocessing(tmp_path):
    path = tmp_path / "train.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="preprocess_dataset"):
        load_pairs(path)


# -- dataset ---------------------------------------------------------------


def test_dataset_returns_tensors_and_the_original_strings(tokenizer):
    item = TransliterationDataset(PAIRS, tokenizer)[0]

    assert item["source"].dtype == torch.long
    assert item["target"].dtype == torch.long
    assert item["source_text"] == "namaste"
    assert item["target_text"] == "नमस्ते"


def test_dataset_target_carries_bos_and_eos(tokenizer):
    target = TransliterationDataset(PAIRS, tokenizer)[0]["target"]
    assert int(target[0]) == BOS_ID
    assert int(target[-1]) == EOS_ID


def test_dataset_length_matches_the_pairs(tokenizer):
    assert len(TransliterationDataset(PAIRS, tokenizer)) == len(PAIRS)


def test_from_jsonl_builds_the_same_dataset(jsonl_file, tokenizer):
    assert len(TransliterationDataset.from_jsonl(jsonl_file, tokenizer)) == len(PAIRS)


def test_an_empty_dataset_is_rejected(tokenizer):
    with pytest.raises(ValueError, match="at least one pair"):
        TransliterationDataset([], tokenizer)


# -- collate ---------------------------------------------------------------


def test_batch_is_batch_first_and_rectangular(tokenizer):
    dataset = TransliterationDataset(PAIRS, tokenizer)
    batch = collate_batch([dataset[i] for i in range(len(PAIRS))])

    assert batch.source.dim() == 2
    assert batch.source.size(0) == len(PAIRS)
    assert batch.target.size(0) == len(PAIRS)


def test_padding_uses_pad_id_and_only_after_real_content(tokenizer):
    dataset = TransliterationDataset(PAIRS, tokenizer)
    # "ho" is the shortest source, so its row must be padded.
    batch = collate_batch([dataset[2], dataset[3]])

    short = batch.source[0]
    true_length = int(batch.source_lengths[0])
    assert (short[true_length:] == PAD_ID).all()
    assert (short[:true_length] != PAD_ID).all()


def test_source_lengths_are_the_unpadded_lengths(tokenizer):
    dataset = TransliterationDataset(PAIRS, tokenizer)
    items = [dataset[i] for i in range(len(PAIRS))]
    batch = collate_batch(items)

    expected = torch.tensor([len(item["source"]) for item in items])
    assert torch.equal(batch.source_lengths, expected)


def test_lengths_stay_on_cpu_for_pack_padded_sequence(tokenizer):
    # pack_padded_sequence requires CPU lengths; moving them to a device is a
    # runtime error that only shows up on the GPU machine.
    dataset = TransliterationDataset(PAIRS, tokenizer)
    batch = collate_batch([dataset[0], dataset[1]]).to("cpu")
    assert batch.source_lengths.device.type == "cpu"


def test_batch_width_is_the_longest_member_not_a_fixed_size(tokenizer):
    dataset = TransliterationDataset(PAIRS, tokenizer)
    batch = collate_batch([dataset[2]])  # "ho" alone
    assert batch.source.size(1) == len(dataset[2]["source"])


def test_original_texts_survive_collation_in_order(tokenizer):
    dataset = TransliterationDataset(PAIRS, tokenizer)
    batch = collate_batch([dataset[i] for i in range(len(PAIRS))])
    assert batch.target_texts == [target for _, target in PAIRS]


def test_collating_nothing_is_an_error():
    with pytest.raises(ValueError, match="empty batch"):
        collate_batch([])


# -- dataloader ------------------------------------------------------------


def test_dataloader_yields_batches(tokenizer):
    loader = build_dataloader(
        TransliterationDataset(PAIRS, tokenizer), batch_size=2, shuffle=False
    )
    batches = list(loader)
    assert len(batches) == 2
    assert all(len(b) == 2 for b in batches)


def test_shuffling_with_a_seed_is_reproducible(tokenizer):
    dataset = TransliterationDataset(PAIRS, tokenizer)

    def order(seed: int) -> list[str]:
        loader = build_dataloader(dataset, batch_size=1, shuffle=True, seed=seed)
        return [batch.source_texts[0] for batch in loader]

    assert order(42) == order(42)
