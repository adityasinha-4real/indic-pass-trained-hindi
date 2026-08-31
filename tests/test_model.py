"""Model shapes, numerical sanity, and the invariants that hide bugs.

The two that matter most and are easiest to get silently wrong:

* logits must align with ``target[:, 1:]`` -- an off-by-one here trains the
  model to predict the character it was just given, and still produces a
  falling loss curve;
* attention must not see padding -- a leak makes short words in a batch
  behave differently from short words alone, which is nearly invisible in
  aggregate metrics.
"""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch", reason="requires requirements/ml.txt")

from indicpass.data import TransliterationDataset, collate_batch  # noqa: E402
from indicpass.model import ModelConfig, Seq2SeqTransliterator  # noqa: E402
from indicpass.tokenizer import PAD_ID, TransliterationTokenizer  # noqa: E402

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
def model(tokenizer):
    torch.manual_seed(0)
    return Seq2SeqTransliterator(
        ModelConfig(
            source_vocab_size=tokenizer.source_vocab_size,
            target_vocab_size=tokenizer.target_vocab_size,
            embedding_dim=32,
            hidden_dim=48,
            encoder_layers=1,
            decoder_layers=1,
            dropout=0.0,
        )
    )


@pytest.fixture
def batch(tokenizer):
    dataset = TransliterationDataset(PAIRS, tokenizer)
    return collate_batch([dataset[i] for i in range(len(PAIRS))])


# -- forward pass ----------------------------------------------------------


def test_forward_returns_one_logit_row_per_predicted_character(model, batch, tokenizer):
    logits = model(batch.source, batch.source_lengths, batch.target)

    assert logits.shape == (
        len(batch),
        batch.target.size(1) - 1,  # aligned with target[:, 1:]
        tokenizer.target_vocab_size,
    )


def test_forward_output_aligns_with_the_shifted_target(model, batch):
    """The loss pairs logits[:, t] with target[:, t+1]. Guard that contract."""
    logits = model(batch.source, batch.source_lengths, batch.target)
    labels = batch.target[:, 1:]
    assert logits.shape[:2] == labels.shape


def test_forward_produces_no_nans_or_infs(model, batch):
    logits = model(batch.source, batch.source_lengths, batch.target)
    assert torch.isfinite(logits).all()


def test_a_single_example_batch_works(model, tokenizer):
    dataset = TransliterationDataset(PAIRS, tokenizer)
    single = collate_batch([dataset[0]])
    logits = model(single.source, single.source_lengths, single.target)
    assert logits.size(0) == 1 and torch.isfinite(logits).all()


def test_gradients_reach_both_encoder_and_decoder(model, batch):
    logits = model(batch.source, batch.source_lengths, batch.target)
    logits.sum().backward()

    assert model.encoder.embedding.weight.grad is not None
    assert model.decoder.embedding.weight.grad is not None
    assert torch.isfinite(model.encoder.embedding.weight.grad).all()


# -- padding and masking ---------------------------------------------------


def test_padding_does_not_change_a_sequence_s_own_output(model, tokenizer):
    """The mask test.

    "ho" is the shortest source. Encoding it alone and encoding it beside a
    long word must give the same logits -- otherwise padding is leaking into
    attention or the recurrence.
    """
    model.eval()
    dataset = TransliterationDataset(PAIRS, tokenizer)

    alone = collate_batch([dataset[2]])
    with torch.no_grad():
        solo = model(alone.source, alone.source_lengths, alone.target)

    padded = collate_batch([dataset[2], dataset[3]])  # "ho" + "dhanyavaad"
    with torch.no_grad():
        together = model(padded.source, padded.source_lengths, padded.target)

    steps = solo.size(1)
    assert torch.allclose(solo[0], together[0, :steps], atol=1e-5)


def test_attention_assigns_no_weight_to_padded_positions(model, tokenizer):
    model.eval()
    dataset = TransliterationDataset(PAIRS, tokenizer)
    batch = collate_batch([dataset[2], dataset[3]])  # short + long

    with torch.no_grad():
        encoder_outputs, state = model.encoder(batch.source, batch.source_lengths)
        mask = model._source_mask(batch.source, encoder_outputs.size(1))
        _, _, weights = model.decoder.step(
            batch.target[:, 0], state, encoder_outputs, mask
        )

    padded_weight = weights[0][~mask[0]]
    assert padded_weight.numel() > 0, "expected the short row to have padding"
    assert torch.allclose(padded_weight, torch.zeros_like(padded_weight))


def test_attention_weights_sum_to_one_over_real_positions(model, tokenizer):
    model.eval()
    dataset = TransliterationDataset(PAIRS, tokenizer)
    batch = collate_batch([dataset[i] for i in range(len(PAIRS))])

    with torch.no_grad():
        encoder_outputs, state = model.encoder(batch.source, batch.source_lengths)
        mask = model._source_mask(batch.source, encoder_outputs.size(1))
        _, _, weights = model.decoder.step(
            batch.target[:, 0], state, encoder_outputs, mask
        )

    assert torch.allclose(weights.sum(dim=-1), torch.ones(len(batch)), atol=1e-5)


# -- decoding --------------------------------------------------------------


def test_greedy_decode_returns_ids_within_the_target_vocabulary(model, batch, tokenizer):
    generated = model.greedy_decode(batch.source, batch.source_lengths, max_length=12)

    assert generated.size(0) == len(batch)
    assert generated.size(1) <= 12
    assert int(generated.max()) < tokenizer.target_vocab_size
    assert int(generated.min()) >= 0


def test_greedy_decode_output_decodes_to_a_string(model, batch, tokenizer):
    generated = model.greedy_decode(batch.source, batch.source_lengths, max_length=8)
    decoded = [tokenizer.decode_target(row) for row in generated.tolist()]

    assert len(decoded) == len(batch)
    assert all(isinstance(text, str) for text in decoded)


def test_greedy_decode_respects_max_length(model, batch):
    generated = model.greedy_decode(batch.source, batch.source_lengths, max_length=3)
    assert generated.size(1) <= 3


def test_finished_sequences_are_padded_not_left_rambling(model, tokenizer):
    """Once a row emits EOS it must emit PAD, so decode() sees a clean tail."""
    from indicpass.tokenizer import EOS_ID

    model.eval()
    dataset = TransliterationDataset(PAIRS, tokenizer)
    batch = collate_batch([dataset[i] for i in range(len(PAIRS))])
    generated = model.greedy_decode(batch.source, batch.source_lengths, max_length=40)

    for row in generated.tolist():
        if EOS_ID in row:
            tail = row[row.index(EOS_ID) + 1 :]
            assert all(token == PAD_ID for token in tail)


# -- configuration ---------------------------------------------------------


def test_model_config_survives_a_dict_round_trip():
    config = ModelConfig(source_vocab_size=10, target_vocab_size=20, hidden_dim=64)
    assert ModelConfig.from_dict(config.as_dict()) == config


def test_from_dict_ignores_unknown_keys():
    # Checkpoints written by a later version must still load.
    config = ModelConfig.from_dict(
        {"source_vocab_size": 8, "target_vocab_size": 9, "future_option": True}
    )
    assert config.source_vocab_size == 8


def test_encoder_and_decoder_depths_may_differ(tokenizer, batch):
    model = Seq2SeqTransliterator(
        ModelConfig(
            source_vocab_size=tokenizer.source_vocab_size,
            target_vocab_size=tokenizer.target_vocab_size,
            embedding_dim=16,
            hidden_dim=24,
            encoder_layers=2,
            decoder_layers=1,
            dropout=0.0,
        )
    )
    logits = model(batch.source, batch.source_lengths, batch.target)
    assert torch.isfinite(logits).all()


def test_parameter_count_is_reported(model):
    assert model.count_parameters() > 0
