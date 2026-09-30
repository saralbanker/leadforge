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


def test_validate_subject_length_and_quality():
    """Verify that validate_subject enforces the 50-character ceiling and checks quality."""
    # 1. Valid subject under 50 characters
    valid_sub = "quick note: servo voltage stabilizers at ProtekG"
    assert len(valid_sub) <= 50
    is_valid, issues = EmailQualityEngine.validate_subject(valid_sub)
    assert is_valid is True
    assert issues == []

    # 2. Over-length subject (> 50 chars) rejected
    long_sub = "a thought on sheet metal components inquiries at Khyati Industries Sheet Metal Parts manufacturer"
    assert len(long_sub) > 50
    is_valid, issues = EmailQualityEngine.validate_subject(long_sub)
    assert is_valid is False
    assert any("exceeds 50 characters" in issue for issue in issues)

    # 3. Exactly 50 characters passes
    exact_50 = "a" * 50
    is_valid, issues = EmailQualityEngine.validate_subject(exact_50)
    assert is_valid is True
    assert issues == []

    # 4. 51 characters fails
    over_by_one = "a" * 51
    is_valid, issues = EmailQualityEngine.validate_subject(over_by_one)
    assert is_valid is False
    assert any("exceeds 50 characters" in issue for issue in issues)

    # 5. Empty subject rejected
    is_valid, issues = EmailQualityEngine.validate_subject("")
    assert is_valid is False
    assert any("empty" in issue.lower() for issue in issues)

    # 6. Subject with spam keywords / AI jargon rejected
    spam_sub = "guarantee risk-free sales growth"
    is_valid, issues = EmailQualityEngine.validate_subject(spam_sub)
    assert is_valid is False
    assert any("banned phrase" in issue.lower() for issue in issues)


# ============================================================================
# Body Validator Rule Tests
# ============================================================================

def test_validate_body_clean_pass():
    """Verify that a compliant body strictly within the 40-60 word budget passes."""
    clean_body = (
        "ProtekG Power Electronics manufactures oil-cooled servo voltage stabilizers in Ahmedabad.\n\n"
        "I came across your site while looking at local industrial suppliers. I'm Saral Banker from Orvion. "
        "We build simple dealer portals so repeat purchase orders don't need re-typing from chat.\n\n"
        "Would a brief 5-minute call this Thursday work, or could I send a quick overview on WhatsApp?"
    )
    is_valid, issues = EmailQualityEngine.validate_body(clean_body, city="Ahmedabad")
    assert is_valid is True
    assert issues == []


def test_validate_body_too_long():
    """Verify that a body exceeding the word count ceiling is rejected."""
    long_body = "word " * 75
    is_valid, issues = EmailQualityEngine.validate_body(long_body)
    assert is_valid is False
    assert any("exceeds 65 words" in issue for issue in issues)


def test_validate_body_diagnosis_language_flagged():
    """Verify universal-claim diagnosis language is rejected."""
    unverified_body = (
        "I noticed your unit in Ahmedabad.\n\n"
        "Most plants with lean office teams lose orders because incoming inquiries get buried on WhatsApp "
        "or forgotten before staff follow up. We make sure zero orders slip through.\n\n"
        "Could I send a quick overview on WhatsApp?"
    )
    is_valid, issues = EmailQualityEngine.validate_body(unverified_body)
    assert is_valid is False
    assert any("unverified diagnosis claim" in issue for issue in issues)


def test_validate_body_location_duplication():
    """Verify mechanical collision duplicating location in opening paragraphs is flagged."""
    duplicated_body = (
        "ProtekG manufactures servo voltage stabilizers in Ahmedabad.\n\n"
        "I am Saral Banker from Orvion, a custom software developer based here in Ahmedabad. "
        "We build simple portals for engineering units.\n\n"
        "Would a brief call work?"
    )
    is_valid, issues = EmailQualityEngine.validate_body(duplicated_body, city="Ahmedabad")
    assert is_valid is False
    assert any("Location duplication" in issue for issue in issues)


def test_validate_body_banned_phrases():
    """Verify AI jargon and spam keywords in body copy are flagged."""
    jargon_body = (
        "I noticed your business in Ahmedabad.\n\n"
        "We help streamline and leverage your digital footprint in this digital age.\n\n"
        "Would you like to see a sample?"
    )
    is_valid, issues = EmailQualityEngine.validate_body(jargon_body)
    assert is_valid is False
    assert any("banned phrase" in issue for issue in issues)


def test_validate_body_links_and_images():
    """Verify links and images are rejected in body copy."""
    link_body = (
        "I saw your manufacturing catalog in Ahmedabad.\n\n"
        "Check our work at https://orvion.com to see examples.\n\n"
        "Would tomorrow work for a call?"
    )
    is_valid, issues = EmailQualityEngine.validate_body(link_body)
    assert is_valid is False
    assert any("Contains link or URL" in issue for issue in issues)


def test_validate_body_posing_as_customer():
    """Verify posing as a buyer/customer is flagged."""
    posing_body = (
        "I noticed your textile unit in Ahmedabad.\n\n"
        "I was looking to buy from you as a customer and found your catalog.\n\n"
        "Can I send a message on WhatsApp?"
    )
    is_valid, issues = EmailQualityEngine.validate_body(posing_body)
    assert is_valid is False
    assert any("Poses the sender as a customer" in issue for issue in issues)


def test_validate_body_empty():
    """Verify empty body is rejected."""
    is_valid, issues = EmailQualityEngine.validate_body("")
    assert is_valid is False
    assert any("empty" in issue.lower() for issue in issues)


# ============================================================================
# Bridge Validator Rule Tests
# ============================================================================

def test_validate_bridge_clean_pass():
    """Verify that a compliant grounded bridge passes."""
    bridge = "I noticed your power conditioning catalog while reviewing regional suppliers."
    is_valid, issues = EmailQualityEngine.validate_bridge(bridge, is_usable=True, has_website=True)
    assert is_valid is True
    assert issues == []


def test_validate_bridge_length_bounds():
    """Verify bridge length restrictions (5 to 18 words)."""
    too_short = "I noticed you."
    is_valid, issues = EmailQualityEngine.validate_bridge(too_short)
    assert is_valid is False
    assert any("too short" in issue.lower() for issue in issues)

    too_long = "I noticed your power conditioning catalog while researching regional equipment suppliers and reviewing various manufacturing units in the surrounding areas of Gujarat."
    is_valid, issues = EmailQualityEngine.validate_bridge(too_long)
    assert is_valid is False
    assert any("exceeds 18 words" in issue.lower() for issue in issues)


def test_validate_bridge_prior_contact_fabrication():
    """Verify fabricated prior contact in bridge is flagged."""
    fab_bridge = "Following up on our conversation regarding your product catalog."
    is_valid, issues = EmailQualityEngine.validate_bridge(fab_bridge)
    assert is_valid is False
    assert any("prior contact" in issue.lower() for issue in issues)


def test_validate_bridge_offline_interaction_fabrication():
    """Verify fabricated offline interactions in bridge are flagged."""
    fab_bridge = "I called your office yesterday while looking at local industrial suppliers."
    is_valid, issues = EmailQualityEngine.validate_bridge(fab_bridge)
    assert is_valid is False
    assert any("offline interaction" in issue.lower() for issue in issues)


def test_validate_bridge_customer_posing():
    """Verify customer/buyer posing in bridge is flagged."""
    posing_bridge = "I was looking to buy as a customer from your equipment catalog."
    is_valid, issues = EmailQualityEngine.validate_bridge(posing_bridge)
    assert is_valid is False
    assert any("poses the sender as a customer" in issue.lower() for issue in issues)


def test_validate_bridge_unusable_site_fabrication():
    """Verify claiming website browsing when site is unusable or missing is flagged."""
    fake_site_bridge = "I noticed your product catalog on your website while reviewing local suppliers."
    is_valid, issues = EmailQualityEngine.validate_bridge(fake_site_bridge, is_usable=False, has_website=False)
    assert is_valid is False
    assert any("no usable website exists" in issue.lower() for issue in issues)


def test_validate_bridge_unusable_site_honest_fallback_pass():
    """Verify honest directory/registry fallback passes for unusable or missing websites."""
    honest_bridge = "I came across Shivam Hydraulic while reviewing regional industrial directory listings."
    is_valid, issues = EmailQualityEngine.validate_bridge(honest_bridge, is_usable=False, has_website=False)
    assert is_valid is True
    assert issues == []


def test_validate_bridge_banned_vocabulary():
    """Verify AI jargon and spam terms are rejected in bridge."""
    jargon_bridge = "We help streamline your product catalog while reviewing regional suppliers."
    is_valid, issues = EmailQualityEngine.validate_bridge(jargon_bridge)
    assert is_valid is False
    assert any("banned phrase" in issue.lower() for issue in issues)


def test_validate_bridge_diagnosis_language():
    """Verify universal diagnosis claims are rejected in bridge."""
    diag_bridge = "I noticed plants lose orders while reviewing regional industrial suppliers."
    is_valid, issues = EmailQualityEngine.validate_bridge(diag_bridge)
    assert is_valid is False
    assert any("diagnosis claim" in issue.lower() for issue in issues)


def test_validate_bridge_location_duplication():
    """Verify repeating city from hook in bridge is flagged."""
    hook = "ProtekG Power Electronics manufactures in Ahmedabad."
    bridge = "I noticed your equipment catalog while reviewing suppliers in Ahmedabad."
    is_valid, issues = EmailQualityEngine.validate_bridge(
        bridge, observation_hook=hook, city="Ahmedabad"
    )
    assert is_valid is False
    assert any("location duplication" in issue.lower() for issue in issues)





# --- P0-3/P0-4 (2026-09-24): envelope, social proof, and hook_source gating ---


def test_validate_envelope_requires_greeting_signoff_footer():
    """A body with no greeting, no sign-off, and no footer must fail validate_envelope.

    This is exactly the shape of the drafts sent on 2026-09-24 before the fix.
    """
    bare_body = (
        "Rajsagar Steel manufactures carbon steel pipes in Ahmedabad.\n\n"
        "I came across Rajsagar Steel while reviewing regional industrial directory listings. "
        "I'm Saral Banker from Orvion. We build simple tools that log inquiries.\n\n"
        "How do you currently keep track of inquiries from IndiaMART, your website, and WhatsApp?"
    )
    is_valid, issues = EmailQualityEngine.validate_envelope(bare_body)
    assert is_valid is False
    assert any("greeting" in i.lower() for i in issues)
    assert any("sign-off" in i.lower() for i in issues)
    assert any("footer" in i.lower() for i in issues)


def test_validate_envelope_passes_with_full_wrapper():
    """A body with greeting, sign-off, and compliance footer passes validate_envelope."""
    full_body = (
        "Hi Rajsagar Steel team,\n\n"
        "Rajsagar Steel manufactures carbon steel pipes in Ahmedabad.\n\n"
        "I came across Rajsagar Steel while reviewing regional industrial directory listings. "
        "I'm Saral Banker from Orvion. We build simple tools that log inquiries.\n\n"
        "How do you currently keep track of inquiries from IndiaMART, your website, and WhatsApp?\n\n"
        "Best,\nSaral Banker, Orvion"
        "\n\n---\nOrvion\n402 Silicon Square, SG Highway, Ahmedabad, Gujarat 380054, India\n"
        "Reply STOP to unsubscribe."
    )
    is_valid, issues = EmailQualityEngine.validate_envelope(full_body)
    assert is_valid is True
    assert issues == []


def test_compose_full_body_produces_valid_envelope():
    """compose_full_body() must produce a body that passes validate_envelope
    and stays within the core word budget used by the content circuit breaker."""
    from leadforge.outreach.generator import compose_full_body

    class FakeSettings:
        def get_str(self, key, default=""):
            values = {
                "outreach.footer_company_name": "Orvion",
                "outreach.footer_website": "",
                "outreach.footer_opt_out_text": "Reply STOP to unsubscribe.",
                "outreach.footer_postal_address": "402 Silicon Square, SG Highway, Ahmedabad, Gujarat 380054, India",
            }
            return values.get(key, default)

    core = (
        "Rajsagar Steel manufactures carbon steel pipes in Ahmedabad.\n\n"
        "I came across Rajsagar Steel while reviewing regional industrial directory listings. "
        "I'm Saral Banker from Orvion. We build simple tools that log inquiries from IndiaMART, "
        "your website, and WhatsApp in one place.\n\n"
        "How do you currently keep track of inquiries from IndiaMART, your website, and WhatsApp?"
    )
    body = compose_full_body(core, "Rajsagar Steel", FakeSettings())

    is_valid, issues = EmailQualityEngine.validate_envelope(body)
    assert is_valid is True, issues
    # The website line must be omitted entirely when the setting is empty -
    # never a fabricated URL (P1-1).
    assert "acmegrowth" not in body.lower()
    assert "Orvion\n402 Silicon Square" in body or "Orvion\n\n402 Silicon Square" in body


def test_validate_body_flags_social_proof():
    """No implied clients or social proof - the sender has no case studies."""
    body = (
        "I noticed your plant in Ahmedabad.\n\n"
        "I came across your listing while reviewing regional suppliers. We help other manufacturers "
        "track incoming inquiries the same way.\n\n"
        "Would this be useful for your team?"
    )
    is_valid, issues = EmailQualityEngine.validate_body(body, city="Ahmedabad")
    assert is_valid is False
    assert any("social proof" in i.lower() for i in issues)


def test_score_draft_flags_social_proof():
    body = (
        "I noticed your plant in Ahmedabad.\n\n"
        "I came across your listing while reviewing regional suppliers. We've helped other manufacturers "
        "track incoming inquiries.\n\n"
        "Would this be useful for your team?"
    )
    result = EmailQualityEngine.score_draft(body)
    assert any("social proof" in i.lower() for i in result["issues"])
    assert result["quality_score"] < 100
    # validate_body is the hard gate actually used to block approval/sending -
    # score_draft alone is a soft numeric signal (see server.py: body_valid
    # from validate_body forces quality["passed"] = False).
    body_valid, _ = EmailQualityEngine.validate_body(body)
    assert body_valid is False


def test_bulk_approve_blocks_draft_missing_envelope(tmp_path, monkeypatch):
    """A PENDING_APPROVAL draft with a perfect quality score but no envelope
    (greeting/sign-off/footer) must be held back at bulk-approve time, not sent."""
    from leadforge.outreach.circuit_breaker import validate_draft_content

    bare_body = (
        "Rajsagar Steel manufactures carbon steel pipes in Ahmedabad.\n\n"
        "I came across Rajsagar Steel while reviewing regional industrial directory listings. "
        "I'm Saral Banker from Orvion. We build simple tools that log inquiries from IndiaMART, "
        "your website, and WhatsApp in one place.\n\n"
        "How do you currently keep track of inquiries from IndiaMART, your website, and WhatsApp?"
    )
    valid, issues = validate_draft_content(
        body=bare_body,
        subject="inquiry tracking for Rajsagar Steel",
        city="Ahmedabad",
        has_website=True,
    )
    assert valid is False
    assert any("greeting" in i.lower() or "sign-off" in i.lower() or "footer" in i.lower() for i in issues)


def test_validate_body_rejects_repeated_paragraph_opener():
    body = (
        "I noticed Allied Valves manufactures knife edge gate valves.\n\n"
        "I noticed your industrial valve catalog while researching suppliers. "
        "I'm Saral Banker from Orvion.\n\n"
        "Do most of your new inquiries come in through IndiaMART, WhatsApp, or your website?"
    )
    valid, issues = EmailQualityEngine.validate_body(body, city="Ahmedabad")
    assert valid is False
    assert any("repeat the same opener" in i for i in issues)
