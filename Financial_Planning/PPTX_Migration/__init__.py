"""Workflow state -> the 49-slide Goal Based Planning deck.

adapter.py maps a workflow_state to deck values, deck.py renders them with
FP-PPT-AI-NEW, endpoint.py serves POST /financial-plan/ppt-v2. This replaced
the old python-pptx pipeline (git tag `legacy-ppt-pipeline`).
"""
