"""Seeding and device selection for reproducible training runs.

What "reproducible" means here, precisely: the same command on the same
machine with the same seed produces the same numbers. That is the useful
guarantee -- it makes an experiment comparable with the one before it.

Bit-exact reproducibility *across* machines is not offered, and chasing it is
usually a bad trade. cuDNN picks convolution and RNN algorithms by
benchmarking the local GPU, and forcing deterministic kernels
(``torch.use_deterministic_algorithms``) makes LSTM training substantially
slower for a guarantee that breaks anyway on different hardware. Pass
``deterministic=True`` when a run must be exactly repeatable and you are
willing to pay for it; leave it off for normal training.
"""

from __future__ import annotations

import os
import random
from contextlib import suppress
from typing import Any

__all__ = ["capture_rng_state", "resolve_device", "restore_rng_state", "seed_everything"]


def seed_everything(seed: int, *, deterministic: bool = False) -> int:
    """Seed Python, NumPy and PyTorch (CPU and CUDA). Returns *seed*."""
    seed = int(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)

    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:  # pragma: no cover - numpy ships with torch
        pass

    import torch

    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

    if deterministic:
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
        # cuBLAS needs this to be reproducible for matmuls on CUDA >= 10.2.
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    else:
        # Let cuDNN benchmark; input shapes vary by batch, but not wildly.
        torch.backends.cudnn.benchmark = True

    return seed


def resolve_device(requested: str | None = None) -> Any:
    """Pick a device. ``None`` or ``"auto"`` means CUDA when present, else CPU."""
    import torch

    if requested and requested != "auto":
        return torch.device(requested)
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def describe_device(device: Any) -> str:
    """One human-readable line about *device*, for the startup banner."""
    import torch

    if device.type != "cuda":
        return "CPU"
    index = device.index or 0
    name = torch.cuda.get_device_name(index)
    total = torch.cuda.get_device_properties(index).total_memory / (1024**3)
    return f"{name} ({total:.1f} GiB, CUDA {torch.version.cuda})"


def capture_rng_state() -> dict[str, Any]:
    """Snapshot RNG state so a resumed run continues the same stream."""
    import torch

    state: dict[str, Any] = {
        "python": random.getstate(),
        "torch": torch.get_rng_state(),
    }
    try:
        import numpy as np

        state["numpy"] = np.random.get_state()
    except ImportError:  # pragma: no cover
        pass
    if torch.cuda.is_available():
        state["cuda"] = torch.cuda.get_rng_state_all()
    return state


def restore_rng_state(state: dict[str, Any] | None) -> None:
    """Restore a snapshot from :func:`capture_rng_state`, tolerating gaps.

    A checkpoint moved between machines can carry CUDA state that does not
    apply here. Restore what fits and carry on rather than refusing to resume.
    """
    if not state:
        return
    import torch

    if "python" in state:
        random.setstate(state["python"])
    if "torch" in state:
        torch.set_rng_state(_as_byte_tensor(state["torch"]))
    if "numpy" in state:
        with suppress(ImportError, ValueError, TypeError):  # pragma: no cover
            import numpy as np

            np.random.set_state(state["numpy"])
    if "cuda" in state and torch.cuda.is_available():
        # A checkpoint from a machine with a different GPU count restores
        # nothing here; that is not worth failing a resume over.
        with suppress(RuntimeError, ValueError, TypeError):  # pragma: no cover
            torch.cuda.set_rng_state_all([_as_byte_tensor(s) for s in state["cuda"]])


def _as_byte_tensor(value: Any) -> Any:
    """RNG state must be a CPU ByteTensor; a reloaded checkpoint may not be."""
    import torch

    tensor = value if isinstance(value, torch.Tensor) else torch.tensor(value)
    return tensor.cpu().to(torch.uint8)
