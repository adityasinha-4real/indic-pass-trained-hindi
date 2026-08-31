"""Character-level seq2seq with attention: the Hindi transliteration baseline.

    source ids
        -> embedding
        -> bidirectional LSTM encoder        (packed; padding never seen)
        -> Bahdanau attention over encoder states, masked at PAD
        -> LSTM decoder, teacher-forced during training
        -> linear projection to the target character vocabulary

Attention is the part that is not optional. Transliteration is close to
monotonic character alignment -- ``janamdivas`` -> ``जन्मदिवस`` consumes the
source left to right -- and a fixed-size context vector forces a 30-character
word through one bottleneck. Attention lets the decoder look straight at the
source position it is currently rewriting, which is why this converges in far
fewer epochs than a plain encoder-decoder.

Sized for a laptop GPU: at the default 256/512 configuration the model is
17.2M parameters, roughly 66 MB of fp32 weights (measured, not estimated --
`Seq2SeqTransliterator.count_parameters()` reports it at startup).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence

from indicpass.tokenizer import BOS_ID, EOS_ID, PAD_ID

__all__ = ["ModelConfig", "Seq2SeqTransliterator"]


@dataclass(frozen=True)
class ModelConfig:
    """Architecture hyper-parameters. Stored in every checkpoint."""

    source_vocab_size: int
    target_vocab_size: int
    embedding_dim: int = 256
    hidden_dim: int = 512
    encoder_layers: int = 2
    decoder_layers: int = 2
    dropout: float = 0.2

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ModelConfig:
        known = {field for field in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


class BahdanauAttention(nn.Module):
    """Additive attention scoring decoder state against every encoder state."""

    def __init__(self, encoder_dim: int, decoder_dim: int, attention_dim: int) -> None:
        super().__init__()
        self.encoder_projection = nn.Linear(encoder_dim, attention_dim, bias=False)
        self.decoder_projection = nn.Linear(decoder_dim, attention_dim, bias=False)
        self.score = nn.Linear(attention_dim, 1, bias=False)

    def forward(
        self,
        decoder_state: torch.Tensor,  # (batch, decoder_dim)
        encoder_outputs: torch.Tensor,  # (batch, src_len, encoder_dim)
        source_mask: torch.Tensor,  # (batch, src_len) True where real
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Return ``(context, weights)``: ``(batch, encoder_dim)``, ``(batch, src_len)``."""
        projected = self.encoder_projection(encoder_outputs)
        query = self.decoder_projection(decoder_state).unsqueeze(1)
        scores = self.score(torch.tanh(projected + query)).squeeze(-1)

        # Padding must not receive attention mass. -inf survives the softmax as
        # exactly zero weight, whereas a small penalty would leak.
        scores = scores.masked_fill(~source_mask, float("-inf"))
        weights = F.softmax(scores, dim=-1)
        context = torch.bmm(weights.unsqueeze(1), encoder_outputs).squeeze(1)
        return context, weights


class Encoder(nn.Module):
    """Bidirectional LSTM over the source characters."""

    def __init__(self, config: ModelConfig) -> None:
        super().__init__()
        self.embedding = nn.Embedding(
            config.source_vocab_size, config.embedding_dim, padding_idx=PAD_ID
        )
        self.rnn = nn.LSTM(
            config.embedding_dim,
            config.hidden_dim,
            num_layers=config.encoder_layers,
            bidirectional=True,
            batch_first=True,
            dropout=config.dropout if config.encoder_layers > 1 else 0.0,
        )
        self.dropout = nn.Dropout(config.dropout)
        # Fuse the two directions back to hidden_dim so the decoder, which is
        # unidirectional, can be initialised from them.
        self.bridge_hidden = nn.Linear(config.hidden_dim * 2, config.hidden_dim)
        self.bridge_cell = nn.Linear(config.hidden_dim * 2, config.hidden_dim)
        self.decoder_layers = config.decoder_layers

    def forward(
        self, source: torch.Tensor, source_lengths: torch.Tensor
    ) -> tuple[torch.Tensor, tuple[torch.Tensor, torch.Tensor]]:
        embedded = self.dropout(self.embedding(source))

        # Packing is what keeps padding out of the recurrence entirely, rather
        # than relying on the mask alone to clean up afterwards.
        packed = pack_padded_sequence(
            embedded, source_lengths.cpu(), batch_first=True, enforce_sorted=False
        )
        packed_output, (hidden, cell) = self.rnn(packed)
        outputs, _ = pad_packed_sequence(
            packed_output, batch_first=True, padding_value=0.0
        )

        return outputs, self._bridge(hidden, cell)

    def _bridge(
        self, hidden: torch.Tensor, cell: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Turn ``(layers*2, batch, hidden)`` encoder state into decoder state."""
        batch = hidden.size(1)
        # (layers, 2, batch, hidden) -> concatenate the two directions
        hidden = hidden.view(-1, 2, batch, hidden.size(-1))
        cell = cell.view(-1, 2, batch, cell.size(-1))
        merged_hidden = torch.tanh(
            self.bridge_hidden(torch.cat((hidden[:, 0], hidden[:, 1]), dim=-1))
        )
        merged_cell = torch.tanh(
            self.bridge_cell(torch.cat((cell[:, 0], cell[:, 1]), dim=-1))
        )

        # Encoder and decoder depth need not match; take the topmost encoder
        # layers, repeating if the decoder is deeper.
        merged_hidden = self._fit_layers(merged_hidden, self.decoder_layers)
        merged_cell = self._fit_layers(merged_cell, self.decoder_layers)
        return merged_hidden.contiguous(), merged_cell.contiguous()

    @staticmethod
    def _fit_layers(state: torch.Tensor, layers: int) -> torch.Tensor:
        available = state.size(0)
        if available == layers:
            return state
        if available > layers:
            return state[-layers:]
        # Decoder is deeper than the encoder: repeat the topmost layer's state.
        padding = state[-1:].expand(layers - available, -1, -1)
        return torch.cat([state, padding], dim=0)


class Decoder(nn.Module):
    """LSTM decoder that attends over the encoder outputs at every step."""

    def __init__(self, config: ModelConfig) -> None:
        super().__init__()
        encoder_dim = config.hidden_dim * 2
        self.embedding = nn.Embedding(
            config.target_vocab_size, config.embedding_dim, padding_idx=PAD_ID
        )
        self.attention = BahdanauAttention(
            encoder_dim, config.hidden_dim, config.hidden_dim
        )
        # Input-feeding: the previous character embedding and the attention
        # context are concatenated, so the decoder conditions on where it just
        # looked as well as what it just emitted.
        self.rnn = nn.LSTM(
            config.embedding_dim + encoder_dim,
            config.hidden_dim,
            num_layers=config.decoder_layers,
            batch_first=True,
            dropout=config.dropout if config.decoder_layers > 1 else 0.0,
        )
        self.dropout = nn.Dropout(config.dropout)
        self.output = nn.Linear(config.hidden_dim + encoder_dim, config.target_vocab_size)

    def step(
        self,
        token: torch.Tensor,  # (batch,)
        state: tuple[torch.Tensor, torch.Tensor],
        encoder_outputs: torch.Tensor,
        source_mask: torch.Tensor,
    ) -> tuple[torch.Tensor, tuple[torch.Tensor, torch.Tensor], torch.Tensor]:
        """One decoding step -> ``(logits, new_state, attention_weights)``."""
        embedded = self.dropout(self.embedding(token)).unsqueeze(1)

        # Attend using the top layer's hidden state from the previous step.
        context, weights = self.attention(state[0][-1], encoder_outputs, source_mask)
        rnn_input = torch.cat((embedded, context.unsqueeze(1)), dim=-1)
        output, new_state = self.rnn(rnn_input, state)

        output = output.squeeze(1)
        logits = self.output(self.dropout(torch.cat((output, context), dim=-1)))
        return logits, new_state, weights


class Seq2SeqTransliterator(nn.Module):
    """The full model. See the module docstring for the data flow."""

    def __init__(self, config: ModelConfig) -> None:
        super().__init__()
        self.config = config
        self.encoder = Encoder(config)
        self.decoder = Decoder(config)

    # -- helpers -----------------------------------------------------------

    @property
    def device(self) -> torch.device:
        return next(self.parameters()).device

    def count_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)

    @staticmethod
    def _source_mask(source: torch.Tensor, encoder_len: int) -> torch.Tensor:
        """True at real source positions.

        Built from the padded ids and then trimmed: ``pad_packed_sequence``
        returns only as many timesteps as the longest sequence in the batch,
        which can be shorter than the padded input tensor.
        """
        return (source != PAD_ID)[:, :encoder_len]

    # -- training ----------------------------------------------------------

    def forward(
        self,
        source: torch.Tensor,
        source_lengths: torch.Tensor,
        target: torch.Tensor,
        *,
        teacher_forcing_ratio: float = 1.0,
    ) -> torch.Tensor:
        """Teacher-forced decode.

        *target* is the full ``<BOS> ... <EOS>`` sequence. Returns logits of
        shape ``(batch, target_len - 1, target_vocab)``, aligned with
        ``target[:, 1:]`` -- the caller supplies the shift, so there is exactly
        one place where the off-by-one can live.

        ``teacher_forcing_ratio`` below 1.0 feeds the model's own prediction
        instead of the gold character, per step, which narrows the gap between
        training and greedy inference.
        """
        encoder_outputs, state = self.encoder(source, source_lengths)
        mask = self._source_mask(source, encoder_outputs.size(1))

        steps = target.size(1) - 1
        token = target[:, 0]  # <BOS>
        collected: list[torch.Tensor] = []

        for position in range(steps):
            logits, state, _ = self.decoder.step(token, state, encoder_outputs, mask)
            collected.append(logits)

            if teacher_forcing_ratio >= 1.0:
                token = target[:, position + 1]
            else:
                use_gold = torch.rand(1).item() < teacher_forcing_ratio
                token = target[:, position + 1] if use_gold else logits.argmax(dim=-1)

        return torch.stack(collected, dim=1)

    # -- inference ---------------------------------------------------------

    @torch.no_grad()
    def greedy_decode(
        self,
        source: torch.Tensor,
        source_lengths: torch.Tensor,
        *,
        max_length: int = 64,
    ) -> torch.Tensor:
        """Greedy decode -> ``(batch, <= max_length)`` of generated ids.

        Stops early once every sequence in the batch has emitted EOS. Finished
        sequences are padded rather than left to ramble, so the returned
        tensor decodes cleanly.
        """
        self.eval()
        encoder_outputs, state = self.encoder(source, source_lengths)
        mask = self._source_mask(source, encoder_outputs.size(1))

        batch = source.size(0)
        token = torch.full((batch,), BOS_ID, dtype=torch.long, device=source.device)
        finished = torch.zeros(batch, dtype=torch.bool, device=source.device)
        generated: list[torch.Tensor] = []

        for _ in range(max_length):
            logits, state, _ = self.decoder.step(token, state, encoder_outputs, mask)
            token = logits.argmax(dim=-1)
            token = token.masked_fill(finished, PAD_ID)
            generated.append(token)

            finished = finished | (token == EOS_ID)
            if bool(finished.all()):
                break

        return torch.stack(generated, dim=1)
