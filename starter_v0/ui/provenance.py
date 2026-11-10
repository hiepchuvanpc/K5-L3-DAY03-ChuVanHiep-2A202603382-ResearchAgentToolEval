"""Recover the exact system_prompt.md / tools.yaml a run used, from its sha256 in the run JSON.

Candidates are the working tree and every git commit that touched the file. Teammates on Windows
hash CRLF files, so each candidate is compared as raw, LF and CRLF bytes.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def hash_variants(data: bytes) -> dict[str, str]:
    lf = data.replace(b"\r\n", b"\n")
    return {
        "raw": hashlib.sha256(data).hexdigest(),
        "lf": hashlib.sha256(lf).hexdigest(),
        "crlf": hashlib.sha256(lf.replace(b"\n", b"\r\n")).hexdigest(),
    }


def matches(data: bytes, target: str) -> bool:
    target = (target or "").lower()
    return bool(target) and any(h == target or (len(target) >= 8 and h.startswith(target)) for h in hash_variants(data).values())


def _candidates(rel_path: str, root: Path):
    path = root / rel_path
    if path.exists():
        yield "working tree", path.read_bytes()
    try:
        log = subprocess.run(
            ["git", "-C", str(root), "log", "--all", "--format=%h %s", "--", rel_path],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return
    for line in log.splitlines():
        sha, _, subject = line.partition(" ")
        blob = subprocess.run(["git", "-C", str(root), "show", f"{sha}:./{rel_path}"], capture_output=True, timeout=10)
        if blob.returncode == 0:
            yield f"git {sha} · {subject}", blob.stdout


def resolve(rel_path: str, target_hash: str, root: Path = ROOT) -> tuple[str, str] | None:
    """Return (text, source) of the artifact content whose hash matches, or None."""
    for source, data in _candidates(rel_path, root):
        if matches(data, target_hash):
            return data.decode("utf-8", errors="replace").replace("\r\n", "\n"), source
    return None
