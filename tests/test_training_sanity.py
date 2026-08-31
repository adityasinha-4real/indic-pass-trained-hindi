"""The overfit test: can this model memorise a tiny dataset?

This is the single most valuable test in the suite. A seq2seq with a mis-shifted
target, a broken mask, or a loss that ignores the wrong index will still show a
falling training loss -- it learns *something*, just not the task. The one thing
such a model cannot do is drive CER on a handful of examples to near zero.

So: 64 pairs, no dropout, a few dozen epochs, and an assertion that the model
reproduces them. If this fails, full training is pointless and the cause is in
the model, the collate function, or the loss -- not the data.

Checkpoint resumption is tested alongside it, because a training run that
cannot resume is not usable on a laptop that sleeps.
"""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch", reason="requires requirements/ml.txt")

from indicpass.data import (  # noqa: E402
    TransliterationDataset,
    build_dataloader,
)
from indicpass.metrics import evaluate_predictions  # noqa: E402
from indicpass.model import Seq2SeqTransliterator  # noqa: E402
from indicpass.seeding import seed_everything  # noqa: E402
from indicpass.tokenizer import TransliterationTokenizer  # noqa: E402
from indicpass.trainer import (  # noqa: E402
    Trainer,
    TrainingConfig,
    build_model_from_checkpoint,
    load_checkpoint,
)

# Real Hindi transliteration pairs, written by hand. Small enough to memorise,
# varied enough that memorising them requires actually learning to align
# source characters with target ones.
TINY_CORPUS: list[tuple[str, str]] = [
    ("namaste", "नमस्ते"),
    ("kaise", "कैसे"),
    ("ho", "हो"),
    ("aap", "आप"),
    ("mera", "मेरा"),
    ("naam", "नाम"),
    ("hai", "है"),
    ("kya", "क्या"),
    ("nahi", "नहीं"),
    ("haan", "हाँ"),
    ("dhanyavaad", "धन्यवाद"),
    ("shukriya", "शुक्रिया"),
    ("accha", "अच्छा"),
    ("bura", "बुरा"),
    ("bada", "बड़ा"),
    ("chota", "छोटा"),
    ("paani", "पानी"),
    ("khana", "खाना"),
    ("ghar", "घर"),
    ("school", "स्कूल"),
    ("kitab", "किताब"),
    ("dost", "दोस्त"),
    ("bhai", "भाई"),
    ("behen", "बहन"),
    ("maa", "माँ"),
    ("pita", "पिता"),
    ("subah", "सुबह"),
    ("shaam", "शाम"),
    ("raat", "रात"),
    ("din", "दिन"),
    ("saal", "साल"),
    ("mahina", "महीना"),
    ("aaj", "आज"),
    ("kal", "कल"),
    ("abhi", "अभी"),
    ("jaldi", "जल्दी"),
    ("dheere", "धीरे"),
    ("yahan", "यहाँ"),
    ("wahan", "वहाँ"),
    ("kahan", "कहाँ"),
    ("kaun", "कौन"),
    ("kyun", "क्यों"),
    ("kaam", "काम"),
    ("samay", "समय"),
    ("logon", "लोगों"),
    ("desh", "देश"),
    ("shahar", "शहर"),
    ("gaon", "गाँव"),
    ("rasta", "रास्ता"),
    ("gaadi", "गाड़ी"),
    ("safar", "सफ़र"),
    ("khushi", "खुशी"),
    ("pyaar", "प्यार"),
    ("zindagi", "ज़िंदगी"),
    ("duniya", "दुनिया"),
    ("sapna", "सपना"),
    ("umeed", "उम्मीद"),
    ("mushkil", "मुश्किल"),
    ("aasaan", "आसान"),
    ("sach", "सच"),
    ("jhooth", "झूठ"),
    ("baat", "बात"),
    ("sawaal", "सवाल"),
    ("jawab", "जवाब"),
]


def _train_tiny(epochs: int = 60, seed: int = 42):
    """Train a small model on TINY_CORPUS and return (trainer, loader)."""
    seed_everything(seed)
    tokenizer = TransliterationTokenizer.fit(TINY_CORPUS)

    config = TrainingConfig(
        name="pytest_overfit",
        epochs=epochs,
        batch_size=16,
        eval_batch_size=32,
        learning_rate=3e-3,
        embedding_dim=64,
        hidden_dim=128,
        encoder_layers=1,
        decoder_layers=1,
        dropout=0.0,  # overfitting is the goal; regularisation would fight it
        lr_scheduler="none",
        max_decode_length=32,
    )

    dataset = TransliterationDataset(TINY_CORPUS, tokenizer)
    loader = build_dataloader(dataset, batch_size=config.batch_size, shuffle=True, seed=seed)
    model = Seq2SeqTransliterator(
        config.model_config(tokenizer.source_vocab_size, tokenizer.target_vocab_size)
    )
    return model, tokenizer, config, loader


@pytest.fixture(scope="module")
def overfit_run(tmp_path_factory):
    """Train once; several tests read the result."""
    run_dir = tmp_path_factory.mktemp("overfit_run")
    model, tokenizer, config, loader = _train_tiny()
    trainer = Trainer(
        model, tokenizer, config, torch.device("cpu"), run_dir, logger=_QuietLogger()
    )

    first_loss = trainer.train_epoch(loader)
    for _ in range(config.epochs - 1):
        last_loss = trainer.train_epoch(loader)
    trainer.epoch = config.epochs

    metrics = trainer.evaluate(loader)
    return {
        "trainer": trainer,
        "loader": loader,
        "first_loss": first_loss,
        "last_loss": last_loss,
        "metrics": metrics,
        "run_dir": run_dir,
    }


class _QuietLogger:
    def info(self, *args, **kwargs) -> None:  # pragma: no cover - noise control
        pass

    warning = error = debug = info


# -- the overfit test ------------------------------------------------------


def test_training_loss_falls_substantially(overfit_run):
    first, last = overfit_run["first_loss"], overfit_run["last_loss"]
    assert last < first * 0.2, f"loss barely moved: {first:.4f} -> {last:.4f}"


def test_the_model_memorises_the_tiny_corpus(overfit_run):
    """The gate. Near-zero CER on data the model has seen many times.

    A failure here means the pipeline is broken, not undertrained -- 64 pairs
    and 60 epochs is far past what memorisation needs.
    """
    cer = overfit_run["metrics"].cer
    assert cer < 0.05, f"CER {cer:.4f} on training data -- the model is not learning"


def test_most_predictions_are_exactly_right(overfit_run):
    exact = overfit_run["metrics"].exact_match
    assert exact > 0.85, f"only {exact:.1%} exact on memorised data"


def test_greedy_decoding_reproduces_specific_pairs(overfit_run):
    """Spot-check actual strings, not just the aggregate."""
    trainer = overfit_run["trainer"]
    predictions: list[str] = []
    targets: list[str] = []

    for batch in overfit_run["loader"]:
        generated = trainer.model.greedy_decode(
            batch.source, batch.source_lengths, max_length=32
        )
        predictions.extend(
            trainer.tokenizer.decode_target(row) for row in generated.tolist()
        )
        targets.extend(batch.target_texts)

    result = evaluate_predictions(predictions, targets)
    assert result.count == len(TINY_CORPUS)
    assert result.cer < 0.05


# -- checkpointing ---------------------------------------------------------


def test_checkpoint_round_trip_preserves_predictions(overfit_run, tmp_path):
    """A reloaded checkpoint must predict identically -- or it is not the model."""
    trainer = overfit_run["trainer"]
    path = trainer.save_checkpoint(tmp_path / "best.pt")

    batch = next(iter(overfit_run["loader"]))
    trainer.model.eval()
    with torch.no_grad():
        before = trainer.model.greedy_decode(
            batch.source, batch.source_lengths, max_length=32
        )

    reloaded, tokenizer = build_model_from_checkpoint(load_checkpoint(path))
    reloaded.eval()
    with torch.no_grad():
        after = reloaded.greedy_decode(batch.source, batch.source_lengths, max_length=32)

    assert torch.equal(before, after)
    assert tokenizer.source.itos == trainer.tokenizer.source.itos


def test_checkpoint_carries_everything_needed_to_resume(overfit_run, tmp_path):
    path = overfit_run["trainer"].save_checkpoint(tmp_path / "last.pt")
    payload = load_checkpoint(path)

    for key in (
        "model_state",
        "model_config",
        "optimizer_state",
        "training_config",
        "tokenizer",
        "epoch",
        "history",
        "rng_state",
    ):
        assert key in payload, f"checkpoint is missing {key}"


def test_the_tokenizer_is_embedded_not_merely_referenced(overfit_run, tmp_path):
    # A checkpoint that needs a sibling file is one careless copy from useless.
    payload = load_checkpoint(overfit_run["trainer"].save_checkpoint(tmp_path / "c.pt"))
    assert payload["tokenizer"]["target_vocab"][:4] == ["<PAD>", "<BOS>", "<EOS>", "<UNK>"]


def test_resuming_restores_epoch_and_best_cer(overfit_run, tmp_path):
    trainer = overfit_run["trainer"]
    trainer.best_cer = 0.1234
    path = trainer.save_checkpoint(tmp_path / "last.pt")

    model, tokenizer, config, _ = _train_tiny(epochs=1)
    fresh = Trainer(
        model, tokenizer, config, torch.device("cpu"), tmp_path, logger=_QuietLogger()
    )
    fresh.load_checkpoint(path, resume=True)

    assert fresh.epoch == trainer.epoch
    assert fresh.best_cer == pytest.approx(0.1234)


def test_a_missing_checkpoint_says_where_checkpoints_come_from(tmp_path):
    with pytest.raises(FileNotFoundError, match="runs/"):
        load_checkpoint(tmp_path / "absent.pt")


def test_metrics_json_is_written(overfit_run):
    trainer = overfit_run["trainer"]
    trainer.history.append({"epoch": 1, "train_loss": 1.0})
    path = trainer.write_metrics()
    assert path.is_file() and "history" in path.read_text(encoding="utf-8")


# -- config ----------------------------------------------------------------


def test_training_config_round_trips_through_a_dict():
    config = TrainingConfig(name="x", epochs=3, batch_size=8)
    assert TrainingConfig.from_dict(config.as_dict()).epochs == 3


def test_unknown_config_keys_are_kept_in_extras():
    # hindi_debug.yaml carries evaluate_on_train_subset, which the dataclass
    # does not model but train.py reads.
    config = TrainingConfig.from_dict({"name": "x", "evaluate_on_train_subset": True})
    assert config.extras["evaluate_on_train_subset"] is True
    assert config.as_dict()["evaluate_on_train_subset"] is True
