"""Workflow final_state -> Goal Based Planning deck (PPTX, optionally PDF).

The one entry point for the new deck. It runs both halves in one call:

    final_state --adapter.adapt()--> values --populate_pptx.py--> PPTX / PDF

The values file exists only inside a temporary folder; nothing is written
anywhere else unless the caller asks for it.

    from Financial_Planning.PPTX_Migration.deck import build_deck
    deck = build_deck(final_state, pdf=True)
    deck.pptx, deck.pdf, deck.values, deck.report

From the command line, against a saved final_state (the API's
workflow_state, or a whole /financial-plan/run response):

    python -m Financial_Planning.PPTX_Migration.deck state.json -o out_dir [--no-pdf]

The PDF is exported by PowerPoint, so it needs Windows with PowerPoint
installed; pdf=False needs neither.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .adapter import adapt

PACKAGE = (Path(__file__).resolve().parents[2]
           / "FP-PPT-AI-NEW" / "placeholder_template_package")
POPULATOR = PACKAGE / "populate_pptx.py"


class DeckError(RuntimeError):
    """The deck could not be built; the message carries the populator's report."""


@dataclass
class Deck:
    name: str               # client name, file-safe
    pptx: bytes
    pdf: bytes | None
    values: dict            # what the adapter produced, for debugging
    report: str             # the populator's summary (slides kept / omitted)


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name).strip("_").lower() or "client"


def build_deck(final_state: dict, pdf: bool = True, advisor: dict | None = None,
               review_on=None) -> Deck:
    """Build the deck for one workflow run.

    Strict: a token left without a value is an error, never a [[token]] in a
    client deck. advisor is {name, designation, email} for the contact slide.
    """
    if not POPULATOR.is_file():
        raise DeckError(f"deck renderer not found: {POPULATOR}")
    values = adapt(final_state, review_on=review_on, advisor=advisor).to_values()
    name = _safe(str(final_state.get("client_data", {}).get("client_data", {}).get("name", "client")))

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        values_path = out / f"{name}.json"
        values_path.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
        command = [sys.executable, str(POPULATOR), str(values_path), "-o", str(out)]
        if not pdf:
            command.append("--no-pdf")
        result = subprocess.run(command, cwd=PACKAGE, capture_output=True, text=True,
                                encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        report = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            raise DeckError(report or f"renderer exited with {result.returncode}")
        pptx_path, pdf_path = out / f"{name}.pptx", out / f"{name}.pdf"
        if not pptx_path.is_file():
            raise DeckError(f"renderer wrote no deck\n{report}")
        return Deck(name=name, pptx=pptx_path.read_bytes(),
                    pdf=pdf_path.read_bytes() if pdf and pdf_path.is_file() else None,
                    values=values, report=report)


def _load_state(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    # Accept a whole /financial-plan/run response as well as its workflow_state.
    return data.get("workflow_state", data) if isinstance(data, dict) else data


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the Goal Based Planning deck from a workflow state.")
    parser.add_argument("state", type=Path, nargs="+", help="final_state JSON file(s)")
    parser.add_argument("-o", "--out", type=Path, default=Path("deck_out"))
    parser.add_argument("--no-pdf", action="store_true", help="write only the PPTX")
    args = parser.parse_args(argv)

    failed = 0
    for path in args.state:
        try:
            deck = build_deck(_load_state(path), pdf=not args.no_pdf)
        except Exception as exc:  # report and carry on with the next client
            failed += 1
            print(f"FAILED {path}: {exc}", file=sys.stderr)
            continue
        folder = args.out / deck.name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{deck.name}.pptx").write_bytes(deck.pptx)
        if deck.pdf:
            (folder / f"{deck.name}.pdf").write_bytes(deck.pdf)
        (folder / "values.json").write_text(json.dumps(deck.values, indent=2, ensure_ascii=False),
                                            encoding="utf-8")
        kept = next((l for l in deck.report.splitlines() if l.startswith("Populated")), "")
        print(f"{deck.name}: {kept.split(' -> ')[0]} -> {folder}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
