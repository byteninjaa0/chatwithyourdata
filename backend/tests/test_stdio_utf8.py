"""stdio_utf8 must not raise OSError on Windows (uvicorn / Make plan)."""

import io
import sys

import stdio_utf8


def test_force_utf8_stdio_on_wrapped_stdout(monkeypatch):
    """Simulate pipe/capture stdout — must not raise Errno 22."""
    real_out = sys.__stdout__
    real_err = sys.__stderr__
    monkeypatch.setattr(stdio_utf8, "_done", False)
    sys.stdout = io.TextIOWrapper(
        io.BufferedWriter(open(real_out.fileno(), "wb", closefd=False)),
        encoding="cp1252",
        errors="replace",
    )
    sys.stderr = io.TextIOWrapper(
        io.BufferedWriter(open(real_err.fileno(), "wb", closefd=False)),
        encoding="cp1252",
        errors="replace",
    )
    stdio_utf8.force_utf8_stdio()
    print("\u20b9100000")
    stdio_utf8.force_utf8_stdio()  # idempotent second call
