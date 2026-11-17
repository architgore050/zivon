"""Deterministic tests for the separate assessment-content pipeline (P2).

Key-free, offline, no model: the seed generator is tracked data, and every
check here fails for one named reason. Run from the repo root:

    python -m unittest discover -s testing/content_factory/assessment -t .
"""
