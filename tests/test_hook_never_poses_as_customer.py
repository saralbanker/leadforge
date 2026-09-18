"""The sender is a vendor, not a buyer.

A real generated hook read: "K. Rudra Textiles has no clear product details on
its website for potential buyers like me." The sender sells web development.
Implying he is a prospective customer to win attention is deceptive, and deceptive
content is exactly what CAN-SPAM prohibits in commercial email.
"""

import pytest

from leadforge.outreach.quality import EmailQualityEngine


POSING = [
    "K. Rudra Textiles has no clear product details for potential buyers like me.",
    "Acme Steel does not list prices for customers like us.",
    "As a potential buyer I could not find your catalogue.",
    "I am a customer looking for CPVC pipe prices.",
]

HONEST = [
    "Noble Brothers exports H.D.P.E tarpaulins to several countries.",
    "Bhagvat Pipe makes CPVC and UPVC pipes for construction projects.",
    "Cutis Hospital lists reconstructive and aesthetic surgery services.",
]


@pytest.mark.parametrize("hook", POSING)
def test_hooks_posing_as_a_customer_are_rejected(hook):
    valid, issues = EmailQualityEngine.validate_hook(hook, has_site_text=True)
    assert valid is False
    assert any("customer" in i.lower() or "banned" in i.lower() for i in issues), issues


@pytest.mark.parametrize("hook", HONEST)
def test_straightforward_observations_still_pass(hook):
    valid, issues = EmailQualityEngine.validate_hook(hook, has_site_text=True)
    assert valid is True, issues


def test_the_exact_hook_that_shipped_is_now_caught():
    """Regression: this one reached an APPROVED draft."""
    shipped = (
        "K. Rudra Textiles has no clear product details on its website "
        "for potential buyers like me."
    )
    valid, issues = EmailQualityEngine.validate_hook(shipped, has_site_text=True)
    assert valid is False
    assert any("Poses the sender as a customer" in i for i in issues), issues
