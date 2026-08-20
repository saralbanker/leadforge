from leadforge.outreach.quality import EmailQualityEngine


def test_quality_clean_copy():
    """Verify that short, clean, human-like copy receives a 100 score."""
    body = (
        "I noticed your dental clinic listing has a solid 4.8 rating on Maps, but no booking widget.\n\n"
        "We build direct scheduling calendars for clinics. Would you be opposed to seeing a screenshot?"
    )
    result = EmailQualityEngine.score_draft(body)
    assert result["quality_score"] == 100
    assert result["passed"] is True
    assert len(result["issues"]) == 0


def test_quality_long_copy():
    """Verify long copy raises a length warning."""
    body = "word " * 120
    result = EmailQualityEngine.score_draft(body)
    assert result["quality_score"] < 100
    assert any("too long" in issue for issue in result["issues"])


def test_quality_spam_and_jargon():
    """Verify spam words and AI jargon reduce the quality score."""
    body = (
        "Hope this email finds you well. We guarantee risk-free sales growth for your business. "
        "We will elevate your conversions in this digital landscape."
    )
    result = EmailQualityEngine.score_draft(body)
    assert result["quality_score"] <= 60
    assert any("Spam indicators" in issue for issue in result["issues"])
    assert any("AI boilerplate" in issue for issue in result["issues"])


def test_quality_word_boundary_no_false_positive():
    """Regression: "buyers"/"growth" must not trip the "buy"/"grow" spam keywords
    (substring matching previously flagged legitimate B2B terms as spam)."""
    body = (
        "Procurement managers and buyers in Ahmedabad look for a technical catalog. "
        "Without one, buyers usually default to listed competitors."
    )
    result = EmailQualityEngine.score_draft(body)
    assert not any("Spam indicators" in issue for issue in result["issues"])
    assert result["quality_score"] == 100


def test_quality_links_and_images_banned():
    """Verify that including links or tracking elements reduces the score."""
    body = "Check out our site at https://orvion.com or contact us here."
    result = EmailQualityEngine.score_draft(body)
    assert result["quality_score"] < 100
    assert any("link or URL" in issue for issue in result["issues"])
