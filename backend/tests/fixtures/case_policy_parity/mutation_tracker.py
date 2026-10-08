"""Mutation tracker shared by canary fixture tools during parity invoke."""

from __future__ import annotations

mutated = False


def reset() -> None:
    global mutated
    mutated = False


def mark_mutated() -> None:
    global mutated
    mutated = True
