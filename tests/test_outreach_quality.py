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


# ============================================================================
# Hook Validator Rule Tests (Task E)
# ============================================================================

def test_validate_hook_too_long():
    """Hook exceeding 15 words must be flagged as invalid."""
    long_hook = (
        "Sakar Plastic Industries has a website with over 50 years of experience "
        "as an eco-friendly packaging provider."
    )
    is_valid, issues = EmailQualityEngine.validate_hook(long_hook, has_site_text=True)
    assert is_valid is False
    assert any("exceeds 15 words" in issue for issue in issues)


def test_validate_hook_banned_vocabulary():
    """Hook containing banned vocabulary (e.g. 'solutions', 'streamline') must be invalid."""
    banned_hook = "We build custom packaging solutions for manufacturers in Denver."
    is_valid, issues = EmailQualityEngine.validate_hook(banned_hook, has_site_text=True)
    assert is_valid is False
    assert any("banned phrase" in issue.lower() for issue in issues)


def test_validate_hook_filler_locations():
    """Meaningless filler like 'in various locations' must be flagged as invalid."""
    filler_hook = "Sahajanand Industries Limited has 36 reviews in various locations."
    is_valid, issues = EmailQualityEngine.validate_hook(filler_hook, has_site_text=False)
    assert is_valid is False
    assert any("filler" in issue.lower() for issue in issues)


def test_validate_hook_filler_has_website():
    """Trivial observation 'has a website' must be flagged as filler."""
    filler_hook = "Bhagwati Engineering Corporation has a website that showcases textile machinery parts."
    is_valid, issues = EmailQualityEngine.validate_hook(filler_hook, has_site_text=True)
    assert is_valid is False
    assert any("filler" in issue.lower() for issue in issues)


def test_validate_hook_negative_website_is_not_filler():
    """Observing that a business has NO website listed is legitimate and NOT filler."""
    no_web_hook = "Sydney Roof Masters does not have a website listed for customers in Sydney."
    is_valid, issues = EmailQualityEngine.validate_hook(no_web_hook, has_site_text=False)
    assert is_valid is True
    assert issues == []


def test_validate_hook_rating_recital_with_site_text_rejected():
    """Bare rating/review recital WHEN usable site text was supplied must be REJECTED."""
    rating_hook = "Bombay Hosiery House has a Google rating of 3.5 based on 14 reviews from customers."
    is_valid, issues = EmailQualityEngine.validate_hook(rating_hook, has_site_text=True)
    assert is_valid is False
    assert any("Rating recital" in issue for issue in issues)


def test_validate_hook_rating_recital_without_site_text_accepted():
    """Bare rating/review recital WITHOUT usable site text is the acceptable last resort and must be ACCEPTED."""
    rating_hook = "I saw ATX Family Dental has 128 reviews with a 4.9 rating in Austin."
    is_valid, issues = EmailQualityEngine.validate_hook(rating_hook, has_site_text=False)
    assert is_valid is True
    assert issues == []


def test_validate_hook_valid_site_evidence():
    """Specific concrete observation from site text under 15 words must pass cleanly."""
    clean_hook = "I saw Ratan Plastics exports packaging to over 45 countries."
    is_valid, issues = EmailQualityEngine.validate_hook(clean_hook, has_site_text=True)
    assert is_valid is True
    assert issues == []

