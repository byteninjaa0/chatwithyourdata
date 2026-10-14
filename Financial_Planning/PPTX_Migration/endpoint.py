"""POST /financial-plan/ppt-v2 -- the 49-slide Goal Based Planning deck.

Takes the workflow_state a prior Make plan run returned (the same body as the
existing /financial-plan/ppt) and returns the deck built by deck.build_deck.
The existing endpoint is untouched; both run side by side until the switch.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from .deck import DeckError, build_deck

PPTX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

router = APIRouter(tags=["financial-plan"])


class Advisor(BaseModel):
    name: str | None = None
    designation: str | None = None
    email: str | None = None


class PptV2Request(BaseModel):
    workflow_state: dict
    # "pptx" (default) or "pdf". PDF export needs PowerPoint on the server.
    format: str = "pptx"
    advisor: Advisor | None = None


@router.post("/financial-plan/ppt-v2")
def generate_ppt_v2(req: PptV2Request) -> Response:
    """Build the 49-slide deck from a prior Make plan workflow_state."""
    if not req.workflow_state:
        raise HTTPException(status_code=400, detail="workflow_state is required")
    fmt = req.format.lower()
    if fmt not in ("pptx", "pdf"):
        raise HTTPException(status_code=400, detail="format must be 'pptx' or 'pdf'")
    try:
        deck = build_deck(req.workflow_state, pdf=fmt == "pdf",
                          advisor=req.advisor.model_dump() if req.advisor else None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DeckError as exc:
        raise HTTPException(status_code=500, detail=f"Deck generation failed:\n{exc}") from exc

    if fmt == "pdf":
        if not deck.pdf:
            raise HTTPException(status_code=503, detail="PDF export is unavailable on this server")
        content, media, ext = deck.pdf, "application/pdf", "pdf"
    else:
        content, media, ext = deck.pptx, PPTX_MEDIA_TYPE, "pptx"
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{deck.name}_goal_based_plan.{ext}"'},
    )
