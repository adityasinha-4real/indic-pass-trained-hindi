"""FastAPI adapter over the existing IndicPass password-strength engine.

Boundary
--------
This module contains no password-scoring logic. Every number a response
carries is produced by :class:`indicpass.password.meter.IndicPassMeter` --
built once, at process startup, the same way ``scripts/check_password.py``
builds it -- and serialised with the same
:meth:`~indicpass.password.result.PasswordStrengthResult.to_dict` the CLI's
``--json`` mode already uses (see :func:`_serialize`). See
``docs/frontend.md`` for the full picture and ``api/tests/test_api.py`` for
the test that this adapter and a direct call to the meter agree exactly on
the same password.

Security
--------
A password arrives as a POST JSON body -- never a URL or query string -- is
held only as a local variable for the duration of one request, and is never
written to a file, a log line, or a response cache. The one thing logged on
a failure is the exception, via ``logger.exception``, which reports the
*meter's* internal state, never the request body.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

# Mirrors scripts/_bootstrap.py: make src/ importable without requiring
# `pip install -e .`. A no-op once the package is installed. Runs before the
# indicpass import below, same as every script in scripts/ does.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Optional api/.env, for INDICPASS_API_CORS_ORIGINS. Mirrors
# indicpass.cli.load_env's own tolerance for a missing file or a missing
# python-dotenv install -- this is convenience, never a hard requirement.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
except ImportError:  # pragma: no cover - depends on the install
    pass

from fastapi import FastAPI, HTTPException, Response  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from indicpass.config import ConfigError, load_config  # noqa: E402
from indicpass.password.meter import (  # noqa: E402
    IndicPassMeter,
    describe_dictionaries,
    describe_pcfg,
)

logger = logging.getLogger("indicpass.api")

#: The meter itself imposes no length limit -- but with the baseline enabled
#: (the shipped default; see config/password.yaml's baseline.enabled), every
#: call also runs zxcvbn, which hard-codes a 72-character cap and raises
#: ValueError above it (zxcvbn/__init__.py). Rejecting an over-length request
#: here with a clear 400 is strictly better than the 500 that same input
#: would otherwise produce two calls deeper -- this bound describes an
#: existing limit of the composed system, not a new one.
MAX_PASSWORD_LENGTH = 72

_DEFAULT_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"


class _MeterState:
    """Holds the one IndicPassMeter this process builds, or why it could not.

    Built once here rather than per-request: ``IndicPassMeter.from_config``
    loads the ~298k-entry dictionary and refits the PCFG's character n-gram
    from it, which is tens of seconds of work (see ``docs/frontend.md``).
    Doing that once at startup is what makes a request a dictionary lookup,
    matching the meter's own design intent -- see ``meter.py``'s module
    docstring.
    """

    def __init__(self) -> None:
        self.meter: IndicPassMeter | None = None
        self.error: str | None = None

    def load(self) -> None:
        try:
            config = load_config()
            self.meter = IndicPassMeter.from_config(config)
        except ConfigError as exc:
            logger.error("IndicPass meter failed to load: %s", exc)
            self.error = (
                "The IndicPass analysis backend could not load its configuration "
                "or artefacts. See the server log for detail."
            )
        except Exception:  # pragma: no cover - depends on local artefacts
            logger.exception("IndicPass meter failed to load.")
            self.error = (
                "The IndicPass analysis backend failed to start. See the server "
                "log for detail."
            )

    def require(self) -> IndicPassMeter:
        if self.meter is None:
            raise HTTPException(
                status_code=503,
                detail=self.error or "The IndicPass analysis backend is not ready.",
            )
        return self.meter


_state = _MeterState()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _state.load()
    yield


app = FastAPI(
    title="IndicPass API",
    description=(
        "Thin adapter over the existing IndicPass password-strength engine. "
        "See docs/frontend.md for the architecture and security notes."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

_origins = [
    origin.strip()
    for origin in os.environ.get("INDICPASS_API_CORS_ORIGINS", _DEFAULT_ORIGINS).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    allow_credentials=False,
)


class AnalyzeRequest(BaseModel):
    password: str = Field(
        ...,
        description="Password to analyze. Never logged or written to disk.",
    )
    reveal_tokens: bool = Field(
        False,
        description=(
            "Include the matched substrings and their native-script rendering in "
            "the response, mirroring check_password.py's --show-tokens. Off by "
            "default, same as the CLI's plain --json output."
        ),
    )


def _serialize(result: Any, meter: IndicPassMeter, *, include_tokens: bool) -> str:
    """The exact payload ``scripts/check_password.py`` writes under ``--json``.

    Not a new schema: same dict, built by the same two calls the CLI makes
    (``result.to_dict`` and the meter's own ``describe_*`` helpers), so the
    API and the CLI cannot silently drift apart.

    ``json.dumps`` rather than FastAPI's default ``JSONResponse`` for the
    same reason the CLI uses it: Python's ``json`` module allows the bare
    ``Infinity`` token that ``PasswordStrengthResult.guess_number`` can
    genuinely be (see ``guesses_from_log10`` in ``result.py``, for a guess
    count that overflows a float), and a stricter encoder raises on exactly
    the passwords this meter is proudest of scoring correctly.
    """
    payload = result.to_dict(include_tokens=include_tokens)
    payload["dictionaries"] = describe_dictionaries(meter)
    payload["estimators"] = {
        "indicpass": True,
        "baseline": meter.baseline.name if meter.baseline else None,
        "pcfg": describe_pcfg(meter) is not None,
    }
    return json.dumps(payload, ensure_ascii=False)


@app.get("/api/health")
def health() -> Response:
    if _state.meter is not None:
        body = json.dumps({"status": "ok", "ready": True})
        return Response(content=body, media_type="application/json")
    body = json.dumps(
        {
            "status": "unavailable",
            "ready": False,
            "detail": _state.error or "The IndicPass analysis backend is not ready.",
        }
    )
    return Response(content=body, media_type="application/json", status_code=503)


@app.post("/api/analyze")
def analyze(payload: AnalyzeRequest) -> Response:
    meter = _state.require()

    password = payload.password
    if not password:
        raise HTTPException(status_code=400, detail="Password must not be empty.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Password exceeds the maximum length of {MAX_PASSWORD_LENGTH} characters.",
        )

    try:
        result = meter.score(password)
    except Exception:
        # Never the password, never a traceback, never a path in the response
        # -- logger.exception writes the stack trace to the server's own log
        # only, and that trace is over the meter's internals, not the input.
        logger.exception("Password analysis raised.")
        raise HTTPException(status_code=500, detail="Analysis failed.") from None

    body = _serialize(result, meter, include_tokens=payload.reveal_tokens)
    return Response(content=body, media_type="application/json")
