"""Character vocabularies: special tokens, determinism, round-tripping.

The rule these tests exist to protect: vocabularies are fitted on training
data alone, and ids are stable across processes. A checkpoint's embedding
matrix is meaningless if either breaks.
"""

from __future__ import annotations

import pytest

from indicpass.tokenizer import (
    BOS_ID,
    EOS_ID,
    PAD_ID,
    SPECIAL_TOKENS,
    UNK,
    UNK_ID,
    CharVocab,
    TransliterationTokenizer,
)

PAIRS = [
    ("namaste", "नमस्ते"),
    ("kaise", "कैसे"),
    ("ho", "हो"),
    ("dhanyavaad", "धन्यवाद"),
]


# -- special tokens --------------------------------------------------------


def test_special_tokens_occupy_the_documented_ids():
    vocab = CharVocab.fit(["abc"])
    assert (PAD_ID, BOS_ID, EOS_ID, UNK_ID) == (0, 1, 2, 3)
    assert vocab.itos[:4] == SPECIAL_TOKENS
    for index, token in enumerate(SPECIAL_TOKENS):
        assert vocab.stoi[token] == index


def test_pad_is_zero_so_a_zero_tensor_is_already_padded():
    # nn.Embedding(padding_idx=0) and CrossEntropyLoss(ignore_index=0) both
    # depend on this; it is not merely a convention.
    assert PAD_ID == 0


def test_a_vocab_without_the_special_prefix_is_rejected():
    with pytest.raises(ValueError, match="must begin with"):
        CharVocab(["a", "b", "c"])


def test_duplicate_entries_are_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        CharVocab([*SPECIAL_TOKENS, "a", "a"])


# -- determinism -----------------------------------------------------------


def test_vocabulary_order_is_deterministic_across_calls():
    texts = ["banana", "apple", "cherry", "date"]
    assert CharVocab.fit(texts).itos == CharVocab.fit(texts).itos


def test_vocabulary_order_does_not_depend_on_input_order():
    forward = CharVocab.fit(["abc", "bcd", "cde"])
    backward = CharVocab.fit(["cde", "bcd", "abc"])
    assert forward.itos == backward.itos


def test_ties_are_broken_by_codepoint_not_insertion():
    # 'z' and 'a' both appear once; 'a' must come first, whichever was seen first.
    vocab = CharVocab.fit(["za"])
    assert vocab.itos.index("a") < vocab.itos.index("z")


def test_more_frequent_characters_get_lower_ids():
    vocab = CharVocab.fit(["aaaab"])
    assert vocab.stoi["a"] < vocab.stoi["b"]


# -- encode / decode -------------------------------------------------------


def test_encode_decode_round_trips():
    vocab = CharVocab.fit(["namaste"])
    assert vocab.decode(vocab.encode("namaste")) == "namaste"


def test_encode_adds_requested_boundary_tokens():
    vocab = CharVocab.fit(["ab"])
    assert vocab.encode("ab", add_bos=True, add_eos=True)[0] == BOS_ID
    assert vocab.encode("ab", add_bos=True, add_eos=True)[-1] == EOS_ID


def test_unknown_characters_become_unk_rather_than_raising():
    vocab = CharVocab.fit(["abc"])
    assert vocab.encode("axc") == [vocab.stoi["a"], UNK_ID, vocab.stoi["c"]]
    assert vocab.decode(vocab.encode("axc")) == f"a{UNK}c"


def test_decode_stops_at_eos_and_ignores_padding_after_it():
    vocab = CharVocab.fit(["ab"])
    ids = [vocab.stoi["a"], EOS_ID, vocab.stoi["b"], PAD_ID]
    assert vocab.decode(ids) == "a"


def test_decode_tolerates_out_of_range_ids():
    # A freshly initialised model emits garbage; debugging it should not
    # require catching IndexError.
    vocab = CharVocab.fit(["ab"])
    assert vocab.decode([999]) == UNK


def test_min_frequency_prunes_rare_characters():
    vocab = CharVocab.fit(["aaab"], min_frequency=2)
    assert "a" in vocab
    assert "b" not in vocab


# -- the paired tokenizer --------------------------------------------------


def test_source_and_target_vocabularies_are_separate():
    tokenizer = TransliterationTokenizer.fit(PAIRS)
    assert "n" in tokenizer.source
    assert "न" not in tokenizer.source
    assert "न" in tokenizer.target
    assert "n" not in tokenizer.target


def test_target_encoding_is_bos_wrapped_and_eos_terminated():
    tokenizer = TransliterationTokenizer.fit(PAIRS)
    ids = tokenizer.encode_target("नमस्ते")
    assert ids[0] == BOS_ID and ids[-1] == EOS_ID
    assert tokenizer.decode_target(ids) == "नमस्ते"


def test_source_encoding_is_eos_terminated_without_bos():
    tokenizer = TransliterationTokenizer.fit(PAIRS)
    ids = tokenizer.encode_source("namaste")
    assert ids[-1] == EOS_ID
    assert BOS_ID not in ids


def test_fitting_on_zero_pairs_is_an_error():
    with pytest.raises(ValueError, match="zero pairs"):
        TransliterationTokenizer.fit([])


# -- the leakage rule ------------------------------------------------------


def test_characters_only_in_held_out_data_are_absent_from_the_vocabulary():
    """The rule: fit on train, and let evaluation meet <UNK> honestly."""
    train = [("namaste", "नमस्ते")]
    tokenizer = TransliterationTokenizer.fit(train)

    # 'ज़' (nukta) appears only in this held-out record.
    held_out_target = "ज़रूरी"
    assert "ज़" not in tokenizer.target

    encoded = tokenizer.encode_target(held_out_target)
    assert UNK_ID in encoded, "an unseen character must encode as <UNK>"


# -- persistence -----------------------------------------------------------


def test_save_and_load_preserves_every_id(tmp_path):
    tokenizer = TransliterationTokenizer.fit(PAIRS, metadata={"language": "hin"})
    path = tokenizer.save(tmp_path / "tokenizer.json")

    reloaded = TransliterationTokenizer.load(path)
    assert reloaded.source.itos == tokenizer.source.itos
    assert reloaded.target.itos == tokenizer.target.itos
    assert reloaded.metadata["language"] == "hin"
    assert reloaded.encode_source("namaste") == tokenizer.encode_source("namaste")


def test_saved_tokenizer_is_readable_utf8_json(tmp_path):
    # Native script must be legible in the file itself -- it is the artifact
    # someone opens when a model produces nonsense.
    path = TransliterationTokenizer.fit(PAIRS).save(tmp_path / "tokenizer.json")
    assert "नमस्ते"[0] in path.read_text(encoding="utf-8")


def test_loading_a_missing_tokenizer_explains_where_it_comes_from(tmp_path):
    with pytest.raises(FileNotFoundError, match="beside the checkpoint"):
        TransliterationTokenizer.load(tmp_path / "absent.json")
