"""The compliance footer carries the legally required sender identity.

US CAN-SPAM and Canadian CASL both require a valid physical postal address in
commercial email. Presenting the mail as a casual personal note does not exempt
it - what matters is that its purpose is commercial.
"""

from leadforge.outreach.generator import compile_compliance_footer


class FakeSettings:
    def __init__(self, **vals):
        self.vals = vals

    def get_str(self, key, default=""):
        return self.vals.get(key, default)


def _footer(**vals) -> str:
    base = {
        "outreach.footer_company_name": "Orvion",
        "outreach.footer_website": "https://example.test/",
        "outreach.footer_opt_out_text": "Reply STOP to unsubscribe.",
    }
    base.update(vals)
    return compile_compliance_footer(FakeSettings(**base))


def test_postal_address_appears_when_configured():
    out = _footer(**{"outreach.footer_postal_address": "12 Example Road, Austin TX 78701"})
    assert "12 Example Road, Austin TX 78701" in out


def test_footer_still_builds_without_an_address():
    """Absence must not crash the composer - the send-time guard is what blocks
    delivery, so that the reason surfaces as one clear message rather than an
    exception buried in draft generation."""
    out = _footer()
    assert "Orvion" in out
    assert "Reply STOP to unsubscribe." in out


def test_address_sits_between_identity_and_opt_out():
    out = _footer(**{"outreach.footer_postal_address": "12 Example Road"})
    assert out.index("Orvion") < out.index("12 Example Road") < out.index("Reply STOP")


def test_opt_out_instruction_is_always_present():
    """A working opt-out is required in every market currently enabled."""
    assert "unsubscribe" in _footer().lower()
