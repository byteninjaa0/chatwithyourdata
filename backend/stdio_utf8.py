"""
Force UTF-8 on stdout/stderr (Windows consoles often use cp1252).
Armstrong workflow prints and raises messages containing ₹ (U+20B9).

On Windows under uvicorn, reopening stdout via fileno() can raise
OSError: [Errno 22] Invalid argument — prefer TextIOWrapper.reconfigure().
"""

from __future__ import annotations

import os
import sys

_done = False


def _encoding_ok(stream) -> bool:
    enc = getattr(stream, "encoding", None)
    return bool(enc and enc.lower().replace("-", "") in ("utf8", "utf_8"))


def _reconfigure_stream(stream):
    if stream is None:
        return False
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
            return _encoding_ok(stream)
        except Exception:
            return False
    return False


def _reopen_via_fileno(original, assign):
    """Reopen fd as UTF-8 text stream. Not used on Windows (Errno 22 risk)."""
    if original is None or not hasattr(original, "fileno"):
        return False
    try:
        assign(
            open(  # noqa: SIM115 — intentional reopen of fd
                original.fileno(),
                mode="w",
                encoding="utf-8",
                errors="replace",
                buffering=1,
                closefd=False,
            )
        )
        return True
    except OSError:
        return False


def force_utf8_stdio() -> None:
    """Ensure process stdout/stderr accept Unicode (₹, etc.). Idempotent."""
    global _done
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    if _done and _encoding_ok(sys.stdout) and _encoding_ok(sys.stderr):
        return

    out_orig = getattr(sys, "__stdout__", None) or sys.stdout
    err_orig = getattr(sys, "__stderr__", None) or sys.stderr

    out_ok = _reconfigure_stream(sys.stdout) or _reconfigure_stream(out_orig)
    err_ok = _reconfigure_stream(sys.stderr) or _reconfigure_stream(err_orig)

    # fileno reopen: Unix fallback only — causes Errno 22 on some Windows consoles
    if sys.platform != "win32":
        if not out_ok:
            out_ok = _reopen_via_fileno(out_orig, lambda s: setattr(sys, "stdout", s))
        if not err_ok:
            err_ok = _reopen_via_fileno(err_orig, lambda s: setattr(sys, "stderr", s))

    _done = bool(out_ok or err_ok or sys.platform == "win32")
