"""The training loop, checkpointing and evaluation for the Hindi baseline.

Kept deliberately small: one class, an explicit epoch loop, and checkpoints
that are plain ``torch.save`` dictionaries. There is no experiment framework
because at this stage the failure modes worth catching -- a mis-shifted target,
a mask that leaks padding, a checkpoint that cannot be resumed -- are all
easier to see in a loop you can read end to end.

Best-checkpoint selection uses validation **CER**, never exact match. With
13.33% of the corpus's Romanized spellings mapping to multiple valid targets,
exact match penalises correct-but-different output and would pick the wrong
checkpoint.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from indicpass.metrics import MetricResult, evaluate_predictions
from indicpass.model import ModelConfig, Seq2SeqTransliterator
from indicpass.seeding import capture_rng_state, restore_rng_state
from indicpass.tokenizer import IGNORE_INDEX, TransliterationTokenizer

__all__ = ["Trainer", "TrainingConfig", "load_checkpoint"]

CHECKPOINT_VERSION = 1


@dataclass
class TrainingConfig:
    """Everything the loop needs, loaded from a YAML file in config/training/."""

    # -- identity
    name: str = "hindi_baseline_v1"
    language: str = "hin"
    dataset_source: str = "aksharantar"
    seed: int = 42
    device: str = "auto"
    deterministic: bool = False

    # -- data
    max_train_records: int | None = None
    max_validation_records: int | None = None
    batch_size: int = 128
    eval_batch_size: int = 256
    num_workers: int = 0
    min_char_frequency: int = 1

    # -- model
    embedding_dim: int = 256
    hidden_dim: int = 512
    encoder_layers: int = 2
    decoder_layers: int = 2
    dropout: float = 0.2

    # -- optimisation
    epochs: int = 10
    learning_rate: float = 1e-3
    weight_decay: float = 0.0
    gradient_clip: float = 1.0
    teacher_forcing_ratio: float = 1.0
    lr_scheduler: str = "plateau"  # "plateau" | "none"
    lr_patience: int = 1
    lr_factor: float = 0.5

    # -- evaluation / output
    max_decode_length: int = 64
    eval_max_batches: int | None = None
    output_dir: str = "runs"
    log_interval: int = 50
    early_stopping_patience: int | None = None

    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TrainingConfig:
        """Build from a flat mapping, keeping unknown keys in ``extras``."""
        known = set(cls.__dataclass_fields__) - {"extras"}
        kwargs = {k: v for k, v in data.items() if k in known}
        extras = {k: v for k, v in data.items() if k not in known}
        return cls(**kwargs, extras=extras)

    def as_dict(self) -> dict[str, Any]:
        payload = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "extras"
        }
        payload.update(self.extras)
        return payload

    def model_config(self, source_vocab: int, target_vocab: int) -> ModelConfig:
        return ModelConfig(
            source_vocab_size=source_vocab,
            target_vocab_size=target_vocab,
            embedding_dim=self.embedding_dim,
            hidden_dim=self.hidden_dim,
            encoder_layers=self.encoder_layers,
            decoder_layers=self.decoder_layers,
            dropout=self.dropout,
        )


class Trainer:
    """Owns the model, the optimiser and the run directory."""

    def __init__(
        self,
        model: Seq2SeqTransliterator,
        tokenizer: TransliterationTokenizer,
        config: TrainingConfig,
        device: torch.device,
        run_dir: Path,
        logger: Any = None,
    ) -> None:
        self.model = model.to(device)
        self.tokenizer = tokenizer
        self.config = config
        self.device = device
        self.run_dir = Path(run_dir)
        self.logger = logger

        self.checkpoint_dir = self.run_dir / "checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        self.criterion = nn.CrossEntropyLoss(ignore_index=IGNORE_INDEX)
        self.optimizer = torch.optim.AdamW(
            self.model.parameters(),
            lr=config.learning_rate,
            weight_decay=config.weight_decay,
        )
        self.scheduler = self._build_scheduler()

        self.epoch = 0
        self.best_cer = math.inf
        self.history: list[dict[str, Any]] = []

    def _build_scheduler(self) -> Any:
        if self.config.lr_scheduler != "plateau":
            return None
        return torch.optim.lr_scheduler.ReduceLROnPlateau(
            self.optimizer,
            mode="min",  # tracking CER
            factor=self.config.lr_factor,
            patience=self.config.lr_patience,
        )

    def _log(self, message: str) -> None:
        if self.logger is not None:
            self.logger.info(message)
        else:  # pragma: no cover - only when used as a library
            print(message)

    # -- one epoch ---------------------------------------------------------

    def train_epoch(self, loader: DataLoader, *, progress: Any = None) -> float:
        """One pass over *loader*. Returns mean token-level loss."""
        self.model.train()
        total_loss = 0.0
        total_batches = 0

        iterator = progress if progress is not None else loader
        for step, batch in enumerate(iterator, start=1):
            batch = batch.to(self.device)

            logits = self.model(
                batch.source,
                batch.source_lengths,
                batch.target,
                teacher_forcing_ratio=self.config.teacher_forcing_ratio,
            )
            # logits align with target[:, 1:] -- the model returns one step per
            # position after <BOS>, and the label is the character to predict.
            loss = self.criterion(
                logits.reshape(-1, logits.size(-1)),
                batch.target[:, 1:].reshape(-1),
            )

            self.optimizer.zero_grad(set_to_none=True)
            loss.backward()
            if self.config.gradient_clip > 0:
                nn.utils.clip_grad_norm_(
                    self.model.parameters(), self.config.gradient_clip
                )
            self.optimizer.step()

            total_loss += loss.item()
            total_batches += 1

            if progress is not None and hasattr(progress, "set_postfix"):
                progress.set_postfix(loss=f"{total_loss / total_batches:.4f}")
            elif step % max(self.config.log_interval, 1) == 0:
                self._log(
                    f"  step {step}/{len(loader)} | loss {total_loss / total_batches:.4f}"
                )

        return total_loss / max(total_batches, 1)

    @torch.no_grad()
    def evaluate(self, loader: DataLoader, *, max_batches: int | None = None) -> MetricResult:
        """Greedy-decode *loader* and score it. Never teacher-forced.

        Decoding without the gold prefix is the only honest measurement: a
        teacher-forced CER would be reported against inputs the model will not
        have at inference time.
        """
        self.model.eval()
        predictions: list[str] = []
        targets: list[str] = []

        for index, batch in enumerate(loader):
            if max_batches is not None and index >= max_batches:
                break
            batch = batch.to(self.device)
            generated = self.model.greedy_decode(
                batch.source,
                batch.source_lengths,
                max_length=self.config.max_decode_length,
            )
            predictions.extend(
                self.tokenizer.decode_target(row) for row in generated.tolist()
            )
            # Score against the record's own text, not a re-decode of its ids.
            targets.extend(batch.target_texts)

        return evaluate_predictions(predictions, targets)

    # -- the run -----------------------------------------------------------

    def fit(
        self,
        train_loader: DataLoader,
        validation_loader: DataLoader | None,
        *,
        progress_factory: Any = None,
    ) -> dict[str, Any]:
        """Train for ``config.epochs``, checkpointing best and last."""
        start_epoch = self.epoch
        epochs_without_improvement = 0

        for epoch in range(start_epoch + 1, self.config.epochs + 1):
            self.epoch = epoch
            started = time.perf_counter()

            bar = None
            if progress_factory is not None:
                bar = progress_factory(train_loader, f"epoch {epoch}/{self.config.epochs}")
            train_loss = self.train_epoch(train_loader, progress=bar)

            record: dict[str, Any] = {
                "epoch": epoch,
                "train_loss": round(train_loss, 6),
                "learning_rate": self.optimizer.param_groups[0]["lr"],
            }

            improved = False
            if validation_loader is not None:
                metrics = self.evaluate(
                    validation_loader, max_batches=self.config.eval_max_batches
                )
                record.update(
                    val_cer=round(metrics.cer, 6),
                    val_exact_match=round(metrics.exact_match, 6),
                    val_count=metrics.count,
                )
                if self.scheduler is not None:
                    self.scheduler.step(metrics.cer)
                improved = metrics.cer < self.best_cer
                if improved:
                    self.best_cer = metrics.cer

            record["seconds"] = round(time.perf_counter() - started, 2)
            record["best_cer"] = None if self.best_cer == math.inf else round(self.best_cer, 6)
            self.history.append(record)

            summary = f"epoch {epoch}/{self.config.epochs} | loss {train_loss:.4f}"
            if "val_cer" in record:
                summary += (
                    f" | val CER {record['val_cer']:.4f}"
                    f" | val exact {record['val_exact_match']:.4f}"
                )
                if improved:
                    summary += "  <- best"
            summary += f" | {record['seconds']:.1f}s"
            self._log(summary)

            self.save_checkpoint(self.checkpoint_dir / "last.pt")
            if improved:
                self.save_checkpoint(self.checkpoint_dir / "best.pt")
                epochs_without_improvement = 0
            else:
                epochs_without_improvement += 1

            self.write_metrics()

            patience = self.config.early_stopping_patience
            if patience and epochs_without_improvement >= patience:
                self._log(
                    f"No validation improvement for {patience} epochs; stopping early."
                )
                break

        return {
            "epochs_completed": self.epoch,
            "best_cer": None if self.best_cer == math.inf else self.best_cer,
            "history": self.history,
        }

    # -- persistence -------------------------------------------------------

    def save_checkpoint(self, path: Path) -> Path:
        """Write a checkpoint containing everything needed to resume or infer.

        The tokenizer vocabularies are embedded, not merely referenced by path.
        A checkpoint that depends on a sibling file is one careless copy away
        from being unusable, and the vocabularies are a few kilobytes.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "checkpoint_version": CHECKPOINT_VERSION,
            "epoch": self.epoch,
            "best_cer": None if self.best_cer == math.inf else self.best_cer,
            "model_state": self.model.state_dict(),
            "model_config": self.model.config.as_dict(),
            "optimizer_state": self.optimizer.state_dict(),
            "scheduler_state": (
                self.scheduler.state_dict() if self.scheduler is not None else None
            ),
            "training_config": self.config.as_dict(),
            "tokenizer": {
                "source_vocab": self.tokenizer.source.to_list(),
                "target_vocab": self.tokenizer.target.to_list(),
                "metadata": self.tokenizer.metadata,
            },
            "tokenizer_path": "tokenizer/tokenizer.json",
            "history": self.history,
            "rng_state": capture_rng_state(),
        }
        torch.save(payload, path)
        return path

    def load_checkpoint(self, path: Path, *, resume: bool = True) -> dict[str, Any]:
        """Restore from *path*. ``resume=False`` loads weights only."""
        payload = load_checkpoint(path)
        self.model.load_state_dict(payload["model_state"])
        if not resume:
            return payload

        self.optimizer.load_state_dict(payload["optimizer_state"])
        if self.scheduler is not None and payload.get("scheduler_state"):
            self.scheduler.load_state_dict(payload["scheduler_state"])
        self.epoch = int(payload.get("epoch", 0))
        best = payload.get("best_cer")
        self.best_cer = math.inf if best is None else float(best)
        self.history = list(payload.get("history") or [])
        restore_rng_state(payload.get("rng_state"))
        return payload

    def write_metrics(self) -> Path:
        """Write ``metrics.json`` after every epoch, so a crash keeps the record."""
        path = self.run_dir / "metrics.json"
        payload = {
            "run": self.config.name,
            "language": self.config.language,
            "epochs_completed": self.epoch,
            "best_cer": None if self.best_cer == math.inf else self.best_cer,
            "history": self.history,
        }
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return path


def load_checkpoint(path: Path) -> dict[str, Any]:
    """Load a checkpoint file with a useful error when it is missing.

    ``weights_only=False`` is required because the payload holds RNG state and
    config dictionaries, not just tensors. These are files this project wrote;
    never point this at a checkpoint from an untrusted source.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(
            f"No checkpoint at {path}.\n"
            "Checkpoints are written to runs/<name>/checkpoints/ during training."
        )
    payload = torch.load(path, map_location="cpu", weights_only=False)

    version = int(payload.get("checkpoint_version", 0))
    if version != CHECKPOINT_VERSION:
        raise ValueError(
            f"{path} is checkpoint v{version}, this build reads v{CHECKPOINT_VERSION}."
        )
    return payload


def build_model_from_checkpoint(
    payload: Mapping[str, Any],
) -> tuple[Seq2SeqTransliterator, TransliterationTokenizer]:
    """Reconstruct model and tokenizer from a loaded checkpoint payload."""
    from indicpass.tokenizer import CharVocab

    model = Seq2SeqTransliterator(ModelConfig.from_dict(payload["model_config"]))
    model.load_state_dict(payload["model_state"])

    tokenizer_payload = payload["tokenizer"]
    tokenizer = TransliterationTokenizer(
        CharVocab(tokenizer_payload["source_vocab"]),
        CharVocab(tokenizer_payload["target_vocab"]),
        metadata=tokenizer_payload.get("metadata") or {},
    )
    return model, tokenizer
