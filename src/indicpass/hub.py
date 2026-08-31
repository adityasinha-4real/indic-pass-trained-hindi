"""Hugging Face Hub access: listing, size estimation and selective download.

Shared by ``scripts/download_datasets.py`` and ``scripts/inspect_dataset.py``
so that both agree on exactly which remote files belong to which language.

Every function here that talks to the network is read-only except
:func:`download_files`. Listing a repository transfers a few kilobytes of JSON
metadata, never dataset content -- which is what makes it safe to inspect
Aksharantar's 26M-pair corpus before deciding what to pull.
"""

from __future__ import annotations

import fnmatch
import json
import os
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

__all__ = [
    "HubError",
    "RemoteFile",
    "download_files",
    "extract_archives",
    "list_remote_files",
    "match_files",
    "repo_metadata",
    "write_manifest",
]


class HubError(RuntimeError):
    """Raised when the Hub cannot be reached or the repository is unusable."""


@dataclass(frozen=True)
class RemoteFile:
    """One file in a Hub repository, as reported by the metadata API."""

    path: str
    size: int | None = None
    lfs: bool = False

    @property
    def size_or_zero(self) -> int:
        return self.size or 0


def _require_hub() -> Any:
    try:
        import huggingface_hub
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise HubError(
            "huggingface_hub is not installed.\n"
            "  python -m pip install -r requirements/base.txt"
        ) from exc
    return huggingface_hub


def _token(explicit: str | None = None) -> str | None:
    """Resolve an access token: explicit, then HF_TOKEN, then the cached login."""
    return explicit or os.environ.get("HF_TOKEN") or None


def _wrap_hub_error(repo_id: str, exc: Exception) -> HubError:
    name = type(exc).__name__
    hint = ""
    if "Gated" in name or "gated" in str(exc).lower():
        hint = (
            f"\nThis repository is gated. Accept its terms at "
            f"https://huggingface.co/datasets/{repo_id} while signed in, then put a "
            "read token in .env as HF_TOKEN."
        )
    elif "RepositoryNotFound" in name or "401" in str(exc) or "404" in str(exc):
        hint = (
            f"\nCheck the repo id ({repo_id!r}) and, if it is private, that HF_TOKEN is set in .env."
        )
    elif "Connection" in name or "Timeout" in name:
        hint = "\nCould not reach huggingface.co -- check the network or a proxy setting."
    return HubError(f"{name}: {exc}{hint}")


def repo_metadata(
    repo_id: str,
    *,
    repo_type: str = "dataset",
    revision: str | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    """Fetch repository metadata (revision, tags, licence, gating). No data transfer."""
    hub = _require_hub()
    try:
        info = hub.HfApi().repo_info(
            repo_id=repo_id,
            repo_type=repo_type,
            revision=revision,
            token=_token(token),
        )
    except Exception as exc:  # noqa: BLE001 - hub raises a wide family of errors
        raise _wrap_hub_error(repo_id, exc) from exc

    card = getattr(info, "cardData", None) or {}
    return {
        "repo_id": repo_id,
        "repo_type": repo_type,
        "revision": getattr(info, "sha", None),
        "last_modified": str(getattr(info, "lastModified", "") or ""),
        "gated": getattr(info, "gated", False),
        "private": getattr(info, "private", False),
        "downloads": getattr(info, "downloads", None),
        "likes": getattr(info, "likes", None),
        "tags": list(getattr(info, "tags", []) or []),
        "license": card.get("license"),
        "configs": card.get("configs"),
        "card_languages": card.get("language"),
    }


def list_remote_files(
    repo_id: str,
    *,
    repo_type: str = "dataset",
    revision: str | None = None,
    token: str | None = None,
) -> list[RemoteFile]:
    """List every file in the repository with its size. Metadata only."""
    hub = _require_hub()
    api = hub.HfApi()
    auth = _token(token)

    try:
        entries = api.list_repo_tree(
            repo_id=repo_id,
            repo_type=repo_type,
            revision=revision,
            recursive=True,
            token=auth,
        )
        files = [
            RemoteFile(
                path=entry.path,
                size=getattr(entry, "size", None),
                lfs=getattr(entry, "lfs", None) is not None,
            )
            for entry in entries
            if type(entry).__name__ == "RepoFile"
        ]
        if files:
            return sorted(files, key=lambda f: f.path)
    except Exception as exc:  # noqa: BLE001
        # Older hub versions lack list_repo_tree; fall through to repo_info.
        if "list_repo_tree" not in str(exc) and not isinstance(exc, AttributeError):
            raise _wrap_hub_error(repo_id, exc) from exc

    try:
        info = api.repo_info(
            repo_id=repo_id,
            repo_type=repo_type,
            revision=revision,
            files_metadata=True,
            token=auth,
        )
    except Exception as exc:  # noqa: BLE001
        raise _wrap_hub_error(repo_id, exc) from exc

    return sorted(
        (
            RemoteFile(
                path=sibling.rfilename,
                size=getattr(sibling, "size", None),
                lfs=getattr(sibling, "lfs", None) is not None,
            )
            for sibling in (info.siblings or [])
        ),
        key=lambda f: f.path,
    )


def match_files(
    files: Iterable[RemoteFile],
    patterns: Sequence[str],
    code: str,
) -> list[RemoteFile]:
    """Select the files belonging to one language.

    Each pattern has ``{code}`` substituted then fnmatch'ed against the file's
    path. Patterns are intentionally permissive because the upstream layout is
    not guaranteed; the caller always prints the resulting list for review
    before downloading anything.
    """
    resolved = [pattern.format(code=code) for pattern in patterns]
    matched: dict[str, RemoteFile] = {}
    for entry in files:
        for pattern in resolved:
            if fnmatch.fnmatchcase(entry.path, pattern):
                matched[entry.path] = entry
                break
    return sorted(matched.values(), key=lambda f: f.path)


def download_files(
    repo_id: str,
    file_paths: Sequence[str],
    destination: Path,
    *,
    repo_type: str = "dataset",
    revision: str | None = None,
    token: str | None = None,
) -> Path:
    """Download exactly *file_paths* into *destination*.

    Uses ``allow_patterns`` with literal paths, so nothing outside the given
    list is ever fetched. Pinning *revision* makes the download reproducible.
    """
    if not file_paths:
        raise HubError("download_files() was given an empty file list.")

    hub = _require_hub()
    destination.mkdir(parents=True, exist_ok=True)
    try:
        local = hub.snapshot_download(
            repo_id=repo_id,
            repo_type=repo_type,
            revision=revision,
            allow_patterns=list(file_paths),
            local_dir=str(destination),
            token=_token(token),
        )
    except Exception as exc:  # noqa: BLE001
        raise _wrap_hub_error(repo_id, exc) from exc
    return Path(local)


def extract_archives(
    archives: Iterable[Path],
    destination: Path,
    *,
    force: bool = False,
) -> list[Path]:
    """Extract zip archives into ``destination/<archive stem>/``.

    Member paths are validated before extraction so a crafted archive cannot
    write outside *destination* (zip-slip). Already-extracted archives are
    skipped unless *force*.
    """
    extracted: list[Path] = []
    for archive in archives:
        target = destination / archive.stem
        if target.exists() and not force:
            extracted.append(target)
            continue

        target.mkdir(parents=True, exist_ok=True)
        resolved_root = target.resolve()
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.namelist():
                member_path = (target / member).resolve()
                if not member_path.is_relative_to(resolved_root):
                    raise HubError(
                        f"Refusing to extract {archive.name}: member {member!r} "
                        "would write outside the destination directory."
                    )
            bundle.extractall(target)
        extracted.append(target)
    return extracted


def write_manifest(path: Path, payload: dict[str, Any]) -> Path:
    """Record provenance for a download so the run can be reproduced exactly."""
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **payload,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
