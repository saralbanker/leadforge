"""Outbound copy must not make claims it cannot support.

The whole system is built so the opening line only states what the data actually
establishes. That discipline is worthless if the paragraph underneath it promises
a doubling of inquiries. An unverifiable number is the fastest way to lose a
reader who knows their own business better than we do.
"""

import re
from pathlib import Path

import yaml

import pytest

ROUTING = Path(__file__).resolve().parent.parent / "campaign_routing.yaml"

# Quantified outcomes and absolutes we have no evidence for.
UNSUPPORTABLE = [
    r"\bdouble\b", r"\btriple\b", r"\b\d+\s*%", r"\b\d+x\b",
    r"\bguarantee(d|s)?\b", r"\bproven\b", r"\bbest[- ]in[- ]class\b",
    r"\bnumber one\b", r"\b#1\b",
]

BANNED_VOCAB = [
    "online presence", "digital footprint", "digital age",
    "solutions", "leverage", "optimize", "streamline",
]


def _all_copy() -> list[tuple[str, str]]:
    """Every rendered copy string in the routing config, tagged by campaign."""
    data = yaml.safe_load(ROUTING.read_text())
    out: list[tuple[str, str]] = []

    def walk(node, campaign):
        if isinstance(node, str):
            out.append((campaign, node))
        elif isinstance(node, list):
            for item in node:
                walk(item, campaign)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value, campaign)

    for campaign in data["campaigns"]:
        walk(campaign.get("copy_template", {}), campaign["name"])
    return out


@pytest.mark.parametrize("pattern", UNSUPPORTABLE)
def test_no_unsupportable_claims(pattern):
    offenders = [
        f"{camp}: {text[:90]}"
        for camp, text in _all_copy()
        if re.search(pattern, text, re.IGNORECASE)
    ]
    assert not offenders, f"unsupportable claim matching {pattern}: {offenders}"


@pytest.mark.parametrize("term", BANNED_VOCAB)
def test_banned_vocabulary_absent(term):
    offenders = [
        f"{camp}: {text[:90]}" for camp, text in _all_copy() if term in text.lower()
    ]
    assert not offenders, f"banned term {term!r}: {offenders}"


def test_no_em_dashes_or_exclamations():
    offenders = [
        f"{camp}: {text[:90]}"
        for camp, text in _all_copy()
        if "—" in text or "!" in text
    ]
    assert not offenders, offenders
