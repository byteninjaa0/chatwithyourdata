"""Typed contract for the 49-slide Goal Based Planning deck.

This is the boundary that makes the migration safe. final_state carries bare
dicts whose inner shapes nothing validates, so a renamed key inside (say)
funded_from would silently produce an empty slide. Everything the deck needs
is declared here instead, and the adapter must satisfy it -- a mapping that
stops working fails loudly, at a named field, rather than rendering a deck
with a figure quietly missing.

Row models mirror the template's list families (pptx_template_tokens.json).
Field names match the token suffixes exactly: an IaRow's `asset` fills
ia_<n>_asset. Renaming a field here breaks the deck, so don't.

Scalars are Optional by design. A slide that is not yet wired leaves its
fields None, populate_pptx.py renders them as [[token]] under --allow-missing,
and the draft stays buildable while the migration is in progress. Strict mode
(no --allow-missing) is what enforces completeness at the end.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Row(BaseModel):
    """Rows reject unknown fields: a typo becomes an error, not a blank cell."""

    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------- list rows

class SummaryGoalRow(_Row):
    """slide 2 -- the three headline goals."""

    name: str
    years: str


class RoadmapRow(_Row):
    """slide 11 -- one milestone on the goals road-map.

    `horizon` is filled by pptx_derive.py from the review year when omitted.
    """

    year: str
    label: str
    amount: str = ""
    horizon: str | None = None


class IaRow(_Row):
    """slide 12 -- one financial asset and the goals it funds."""

    asset: str
    current: str
    allocated: str
    monthly: str
    goals: str


class SipRow(_Row):
    """slide 13 -- one monthly SIP commitment."""

    label: str
    amount: str


class FreedRow(_Row):
    """slide 14 -- an instalment that frees up and is redirected."""

    year: str
    event: str
    amount: str


class LoanRow(_Row):
    """slides 8, 9, 22-25 -- one liability. Extra loans clone the slide."""

    name: str
    type: str | None = None
    outstanding: str
    emi: str
    rate: str
    closing_year: str | None = None
    new_closing_year: str | None = None
    prepay_amount: str | None = None
    interest_outstanding: str | None = None
    interest_saved: str | None = None
    years_saved: str | None = None
    emi_topup: str | None = None
    comment: str | None = None


class FdRow(_Row):
    """slide 20 -- one fixed deposit. Overflows to a (cont.) page."""

    issuer: str
    amount: str
    rate: str
    maturity: str
    remarks: str = ""


class PolicyRow(_Row):
    """slide 16 -- one insurance policy. Overflows to a (cont.) page."""

    name: str
    premium: str
    start: str | None = None
    maturity: str | None = None
    payout: str | None = None
    remarks: str = ""


class LabelValueRow(_Row):
    """slides 39, 41 -- corpus breakdown rows (fold mode)."""

    label: str
    value: str


class EduRow(_Row):
    """slides 30, 31 -- one child's undergraduate or postgraduate panel.

    Sources are numbered: UG draws two rows, PG four. Rows a child does not
    use are left out and pptx_derive.py blanks them.
    """

    child: str
    year: str
    target: str
    basis: str = ""
    corpus: str = ""
    note: str | None = None
    src1_label: str | None = None
    src1_value: str | None = None
    src2_label: str | None = None
    src2_value: str | None = None
    src3_label: str | None = None
    src3_value: str | None = None
    src4_label: str | None = None
    src4_value: str | None = None


class ActionRow(_Row):
    """slide 44 -- one step of the action plan. Overflows to a (cont.) page."""

    title: str
    desc: str


class GoalSourceRow(_Row):
    """slide 27 -- one funding source for a goal."""

    label: str
    terms: str = ""
    value: str


class GoalRow(_Row):
    """slide 27 -- one goal, repeated as its own slide.

    Only the goals with no dedicated slide of their own appear here; a
    vacation or a plot purchase, not retirement or a child's education.
    """

    name: str
    year: str
    cost_label: str = "Cost today"
    cost_today: str | None = None
    inflation_label: str = "Inflation assumed"
    inflation: str | None = None
    years_left: str | None = None
    future_cost: str | None = None
    intro: str | None = None
    corpus: str | None = None
    margin: str | None = None
    redirect_label: str | None = None
    redirect_to: str | None = None
    comment: str | None = None
    sources: list[GoalSourceRow] = Field(default_factory=list)


class AssetEntry(_Row):
    """slides 4, 5, 6 -- one asset class's holding.

    `to_include: False` keeps a figure on record while excluding it from the
    slide and from every total and percentage on it, exactly as a zero would.
    The class key is free text: pptx_derive.py names the nine the design drew
    and falls back to the key for anything else, so a client's own asset
    classes reach the deck instead of being dropped from the total.
    """

    amount: float
    to_include: bool = True


# ---------------------------------------------------------------- include

class Include(BaseModel):
    """Section gates. False drops the section's slides from the deck.

    Names and slide numbers come from SECTIONS in populate_pptx.py. Every
    gate defaults False: a section appears only when the adapter finds the
    data behind it, the way the existing builder deletes a slide it has
    nothing to put on.
    """

    model_config = ConfigDict(extra="forbid")

    home_loan: bool = False
    home_loan_detail: bool = False
    other_loan: bool = False
    protection_detail: bool = False
    cover_classification: bool = False
    cover_suggestions: bool = False
    education: bool = False
    marriage: bool = False
    ssy: bool = False
    pf: bool = False
    ppf: bool = False
    direct_equity: bool = False
    nps: bool = False
    legacy: bool = False
    executive_summary: bool = False


# ------------------------------------------------------------ the payload

# Every token the template carries. A scalar the adapter sets must be one of
# these, so a misspelt key fails here instead of silently filling nothing.
MANIFEST = (Path(__file__).resolve().parents[2] / "FP-PPT-AI-NEW"
            / "placeholder_template_package" / "pptx_template_tokens.json")


# Values read only by a chart, not printed as text (GRAPHIC_INPUTS in
# populate_pptx.py).
GRAPHIC_INPUTS = frozenset({"health_score", "corpus_with_plan"})


@lru_cache(maxsize=1)
def template_tokens() -> frozenset[str]:
    return frozenset(json.loads(MANIFEST.read_text(encoding="utf-8"))["tokens"])


class PlanValues(BaseModel):
    """Everything the deck needs, as populate_pptx.py wants it.

    Lists are declared with typed rows. Scalars are the template's own token
    names; rather than mirror all six hundred here, any extra key is accepted
    only if it is a token in pptx_template_tokens.json and its value a string.
    """

    model_config = ConfigDict(extra="allow")

    include: Include = Field(default_factory=Include)

    summary_goal: list[SummaryGoalRow] = Field(default_factory=list)
    assets: dict[str, AssetEntry] = Field(default_factory=dict)
    loan: list[LoanRow] = Field(default_factory=list)
    roadmap: list[RoadmapRow] = Field(default_factory=list)
    ia: list[IaRow] = Field(default_factory=list)
    sip: list[SipRow] = Field(default_factory=list)
    freed: list[FreedRow] = Field(default_factory=list)
    policy: list[PolicyRow] = Field(default_factory=list)
    fd: list[FdRow] = Field(default_factory=list)
    goals: list[GoalRow] = Field(default_factory=list)
    ug: list[EduRow] = Field(default_factory=list)
    pg: list[EduRow] = Field(default_factory=list)
    corpus_now: list[LabelValueRow] = Field(default_factory=list)
    corpus_later: list[LabelValueRow] = Field(default_factory=list)
    corpus_breakup: list[LabelValueRow] = Field(default_factory=list)
    action: list[ActionRow] = Field(default_factory=list)

    @model_validator(mode="after")
    def _scalars_are_tokens(self):
        known = template_tokens() | GRAPHIC_INPUTS
        for key, value in (self.model_extra or {}).items():
            if key not in known:
                raise ValueError(f"'{key}' is not a token in {MANIFEST.name}")
            if not isinstance(value, str):
                raise ValueError(f"'{key}' must be a string, got {type(value).__name__}")
        return self

    def to_values(self) -> dict:
        """Render as the plain dict populate_pptx.py reads.

        None is dropped rather than emitted: an absent token renders as
        [[token]] in a draft, whereas an empty string would silently look
        like a real, blank value. Empty lists are kept -- an empty list is how
        populate_pptx.py is told to drop a table's slide (no loans, no FDs, no
        child at PG stage).
        """
        return self.model_dump(exclude_none=True)
