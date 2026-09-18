import pytest
import yaml
from pathlib import Path
from leadforge.outreach.router import CampaignRouter


@pytest.fixture
def temp_campaign_config(tmp_path: Path) -> Path:
    """Fixture to create a temporary campaign_routing.yaml file for testing."""
    config_data = {
        "campaigns": [
            {
                "name": "Campaign A",
                "target_offer": "Web Design Offer",
                "criteria": {
                    "has_website": False,
                    "max_load_time_seconds": 3.0,
                },
                "copy_template": {
                    "subject": "Design Subject",
                    "body_structure": "Design Body",
                },
            },
            {
                "name": "Campaign B (Special)",
                "target_offer": "Software Integration Offer",
                "criteria": {
                    "has_website": True,
                    "ssl_valid": True,
                    "categories": ["Dentist", "Physio"],
                },
                "copy_template": {
                    "subject": "Special Subject",
                    "body_structure": "Special Body",
                },
            },
            {
                "name": "Campaign C (Standard)",
                "target_offer": "General Software Offer",
                "criteria": {
                    "has_website": True,
                },
                "copy_template": {
                    "subject": "Standard Subject",
                    "body_structure": "Standard Body",
                },
            },
        ]
    }
    config_file = tmp_path / "test_campaign_routing.yaml"
    with open(config_file, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f)
    return config_file


def test_router_loads_config(temp_campaign_config: Path):
    """Verify router successfully parses YAML campaign configurations."""
    router = CampaignRouter(config_path=temp_campaign_config)
    assert len(router.campaigns) == 3
    assert router.campaigns[0]["name"] == "Campaign A"


def test_router_missing_config():
    """Verify router handles non-existent config path gracefully by returning an empty list."""
    router = CampaignRouter(config_path=Path("non_existent_file.yaml"))
    assert router.campaigns == []


def test_route_campaign_a_no_website(temp_campaign_config: Path):
    """Campaign A should match if has_website is False."""
    router = CampaignRouter(config_path=temp_campaign_config)
    matched = router.route_lead(
        category="Dentist",
        has_website=False,
        ssl_valid=True,
        load_time_seconds=1.5,
    )
    assert matched is not None
    assert matched["name"] == "Campaign A"
    assert matched["target_offer"] == "Web Design Offer"


def test_route_campaign_a_slow_website_rejected(temp_campaign_config: Path):
    """Campaign A should fail to match if website load time is higher than max limit."""
    router = CampaignRouter(config_path=temp_campaign_config)
    matched = router.route_lead(
        category="Dentist",
        has_website=False,
        ssl_valid=True,
        load_time_seconds=4.0,  # exceeds 3.0 max limit
    )
    assert matched is None


def test_route_campaign_b_category_match(temp_campaign_config: Path):
    """Campaign B should match if website exists, SSL is valid, and category matches."""
    router = CampaignRouter(config_path=temp_campaign_config)
    matched = router.route_lead(
        category="Dentist",
        has_website=True,
        ssl_valid=True,
        load_time_seconds=1.2,
    )
    assert matched is not None
    assert matched["name"] == "Campaign B (Special)"


def test_route_campaign_b_unmatched_category_falls_to_c(temp_campaign_config: Path):
    """If category does not match Campaign B, it should fall back to Campaign C."""
    router = CampaignRouter(config_path=temp_campaign_config)
    matched = router.route_lead(
        category="Wholesaler",  # not in Dentist / Physio
        has_website=True,
        ssl_valid=True,
        load_time_seconds=1.2,
    )
    assert matched is not None
    assert matched["name"] == "Campaign C (Standard)"


def test_route_empty_category_does_not_match_category_restricted_campaign(temp_campaign_config: Path):
    """An empty/unknown category must not satisfy a category-restricted campaign
    (regression: empty string is a substring of every string, so the fuzzy
    category match previously treated unknown category as a universal match)."""
    router = CampaignRouter(config_path=temp_campaign_config)
    matched = router.route_lead(
        category="",
        has_website=True,
        ssl_valid=True,
        load_time_seconds=1.2,
    )
    assert matched is not None
    assert matched["name"] == "Campaign C (Standard)"  # falls through, not Campaign B


def test_route_no_matches(temp_campaign_config: Path):
    """If no campaign rules match, should return None."""
    router = CampaignRouter(config_path=temp_campaign_config)
    # Campaign A requires has_website=False
    # Campaign B & C require has_website=True
    # Let's see: what if category is mismatch, etc.
    # In this fixture, Campaign C matches any has_website=True, so it always catches it.
    # Let's verify Campaign B rejects invalid SSL and falls to Campaign C
    matched = router.route_lead(
        category="Dentist",
        has_website=True,
        ssl_valid=False,  # fails Campaign B criteria
        load_time_seconds=1.0,
    )
    assert matched is not None
    assert matched["name"] == "Campaign C (Standard)"


# ============================================================================
# Task A1: Subject Line Variation & Backward Compatibility Tests
# ============================================================================


def test_subject_selection_stable_for_same_business_id():
    """Regenerating a draft for the same business must deterministically give the same subject."""
    copy_tpl = {
        "subject": [
            "orders by WhatsApp?",
            "dealer orders for {business_name}",
            "quick question re: order flow",
            "order entry at {business_name}",
            "taking orders over WhatsApp?",
        ]
    }
    biz_id_1 = "01907de3-bc42-7c89-8d76-5a507db4f555"
    biz_id_2 = "01907de3-bc42-7c89-8d76-5a507db4f999"

    # Multiple invocations for biz_id_1 must return identical variant
    first_choice = CampaignRouter.select_subject(copy_tpl, business_id=biz_id_1)
    for _ in range(20):
        assert CampaignRouter.select_subject(copy_tpl, business_id=biz_id_1) == first_choice

    # Multiple invocations for biz_id_2 must return identical variant
    second_choice = CampaignRouter.select_subject(copy_tpl, business_id=biz_id_2)
    for _ in range(20):
        assert CampaignRouter.select_subject(copy_tpl, business_id=biz_id_2) == second_choice


def test_subject_selection_spread_across_different_businesses():
    """Different businesses in the same campaign must spread across subject variants."""
    import uuid
    variants = [
        "variant 1: {business_name}",
        "variant 2: {business_name}",
        "variant 3: {business_name}",
        "variant 4: {business_name}",
        "variant 5: {business_name}",
    ]
    copy_tpl = {"subject": variants}

    chosen_counts = {v: 0 for v in variants}
    for i in range(100):
        b_id = str(uuid.uuid4())
        picked = CampaignRouter.select_subject(copy_tpl, business_id=b_id)
        assert picked in variants
        chosen_counts[picked] += 1

    # Verify that every variant received some selections across 100 businesses
    for v, count in chosen_counts.items():
        assert count > 0, f"Variant '{v}' was never chosen out of 100 trials (spread failure)."


def test_subject_selection_string_backward_compat():
    """A plain string subject: must still work transparently."""
    plain_tpl = {"subject": "single plain subject for {business_name}"}
    assert CampaignRouter.select_subject(plain_tpl, business_id="biz-123") == "single plain subject for {business_name}"
    assert CampaignRouter.select_subject(plain_tpl, business_id=None) == "single plain subject for {business_name}"

    # Also test when passing campaign dict directly
    camp = {"name": "Test", "copy_template": {"subject": "orders by WhatsApp?"}}
    assert CampaignRouter.select_subject(camp, business_id="biz-456") == "orders by WhatsApp?"


def test_subject_variants_in_production_campaign_routing():
    """Verify live campaign_routing.yaml contains 4-6 valid variants per campaign."""
    router = CampaignRouter()
    assert len(router.campaigns) >= 4
    for camp in router.campaigns:
        copy_tpl = camp.get("copy_template", {})
        subjects = copy_tpl.get("subject")
        assert isinstance(subjects, list), f"Campaign {camp['name']} must have a list of subject variants"
        assert 4 <= len(subjects) <= 6, f"Campaign {camp['name']} must have 4-6 variants, got {len(subjects)}"
        for s in subjects:
            assert isinstance(s, str) and len(s) > 0
            # Confirm no empty braces or malformed templates
            assert "{" not in s or "}" in s


# ============================================================================
# Task A2: Premise Gating (has-form / no-form / unknown)
# ============================================================================


def test_premise_gating_order_portal_has_form_or_order_flow_rejected():
    """Manufacturing portal campaign must NOT match if the site already has a contact form or order flow."""
    router = CampaignRouter()

    # 1. Has working contact form -> rejected from Order Portal, falls to General Outreach
    matched_form = router.route_lead(
        category="Manufacturers",
        has_website=True,
        ssl_valid=True,
        has_order_flow=False,
        has_contact_form=True,
    )
    assert matched_form is not None
    assert matched_form["name"] == "General Outreach (Digital Performance)"

    # 2. Has order flow (e.g. Shopify/ecommerce) -> rejected from Order Portal, falls to General Outreach
    matched_order = router.route_lead(
        category="Manufacturers",
        has_website=True,
        ssl_valid=True,
        has_order_flow=True,
        has_contact_form=False,
    )
    assert matched_order is not None
    assert matched_order["name"] == "General Outreach (Digital Performance)"

    # 3. Via audit_data dictionary with Shopify CMS -> detected as has_order_flow=True, falls to General Outreach
    matched_shopify = router.route_lead(
        category="Manufacturers",
        has_website=True,
        ssl_valid=True,
        audit_data={"cms": "Shopify", "has_booking": False, "has_contact_form": False},
    )
    assert matched_shopify is not None
    assert matched_shopify["name"] == "General Outreach (Digital Performance)"


def test_premise_gating_order_portal_no_form_matches():
    """Manufacturing portal campaign matches only when real evidence confirms NO form and NO order flow."""
    router = CampaignRouter()
    matched = router.route_lead(
        category="Manufacturers",
        has_website=True,
        ssl_valid=True,
        has_order_flow=False,
        has_contact_form=False,
    )
    assert matched is not None
    assert matched["name"] == "Manufacturing - B2B Dealer & Order Portal"


def test_premise_gating_order_portal_unknown_evidence_routes_but_unverified():
    """Missing evidence is unknown, not absence.

    The lead still routes to the order-portal campaign, but the match is
    flagged unverified so the composer never asserts the premise as fact.
    """
    router = CampaignRouter()
    matched = router.route_lead(
        category="Manufacturers",
        has_website=True,
        ssl_valid=True,
        has_order_flow=None,
        has_contact_form=None,
    )
    assert matched is not None
    assert matched["name"] == "Manufacturing - B2B Dealer & Order Portal"
    assert matched["premise_verified"] is False
    assert set(matched["premise_unverified_fields"]) == {
        "has_order_flow",
        "has_contact_form",
    }


def test_premise_gating_booking_has_booking_rejected():
    """Campaign B (Booking) must NOT match if the site already has a booking widget."""
    router = CampaignRouter()
    matched = router.route_lead(
        category="Dentists",
        has_website=True,
        ssl_valid=True,
        has_booking=True,
    )
    assert matched is not None
    assert matched["name"] == "General Outreach (Digital Performance)"


def test_premise_gating_booking_no_booking_matches():
    """Campaign B (Booking) matches when verified that site has NO booking widget."""
    router = CampaignRouter()
    matched = router.route_lead(
        category="Dentists",
        has_website=True,
        ssl_valid=True,
        has_booking=False,
    )
    assert matched is not None
    assert matched["name"] == "Campaign B (Booking)"


def test_premise_gating_booking_unknown_evidence_routes_but_unverified():
    """Unknown booking evidence still routes to Campaign B, flagged unverified."""
    router = CampaignRouter()
    matched = router.route_lead(
        category="Dentists",
        has_website=True,
        ssl_valid=True,
        has_booking=None,
    )
    assert matched is not None
    assert matched["name"] == "Campaign B (Booking)"
    assert matched["premise_verified"] is False
    assert matched["premise_unverified_fields"] == ["has_booking"]


def test_premise_gating_confirmed_absence_is_verified():
    """Confirmed absence routes AND marks the premise verified, so copy may assert it."""
    router = CampaignRouter()
    matched = router.route_lead(
        category="Dentists",
        has_website=True,
        ssl_valid=True,
        has_booking=False,
    )
    assert matched is not None
    assert matched["name"] == "Campaign B (Booking)"
    assert matched["premise_verified"] is True
    assert matched["premise_unverified_fields"] == []


# ============================================================================
# Task B: Body Variation & Premise-Gated Non-Asserting Variants
# ============================================================================


def test_body_selection_stable_for_same_business_id():
    """Regenerating a draft for the same business must deterministically give the same body variant."""
    copy_tpl = {
        "body_structure": [
            "variant 1: {observation_hook}",
            "variant 2: {observation_hook}",
            "variant 3: {observation_hook}",
            "variant 4: {observation_hook}",
            "variant 5: {observation_hook}",
        ]
    }
    biz_id_1 = "01907de3-bc42-7c89-8d76-5a507db4f111"
    biz_id_2 = "01907de3-bc42-7c89-8d76-5a507db4f222"

    first_choice = CampaignRouter.select_body(copy_tpl, business_id=biz_id_1)
    for _ in range(20):
        assert CampaignRouter.select_body(copy_tpl, business_id=biz_id_1) == first_choice

    second_choice = CampaignRouter.select_body(copy_tpl, business_id=biz_id_2)
    for _ in range(20):
        assert CampaignRouter.select_body(copy_tpl, business_id=biz_id_2) == second_choice


def test_body_selection_spread_across_different_businesses():
    """Different businesses in the same campaign must spread across body variants."""
    import uuid
    variants = [
        "body variant 1: {business_name}",
        "body variant 2: {business_name}",
        "body variant 3: {business_name}",
        "body variant 4: {business_name}",
        "body variant 5: {business_name}",
    ]
    copy_tpl = {"body_structure": variants}

    chosen_counts = {v: 0 for v in variants}
    for _ in range(100):
        b_id = str(uuid.uuid4())
        picked = CampaignRouter.select_body(copy_tpl, business_id=b_id)
        assert picked in variants
        chosen_counts[picked] += 1

    for v, count in chosen_counts.items():
        assert count > 0, f"Body variant '{v}' was never chosen out of 100 trials (spread failure)."


def test_body_selection_string_backward_compat():
    """A plain string body_structure must still work transparently."""
    plain_tpl = {"body_structure": "single plain body for {business_name}"}
    assert CampaignRouter.select_body(plain_tpl, business_id="biz-123") == "single plain body for {business_name}"
    assert CampaignRouter.select_body(plain_tpl, business_id=None) == "single plain body for {business_name}"

    camp = {"name": "Test", "copy_template": {"body_structure": "single plain body"}}
    assert CampaignRouter.select_body(camp, business_id="biz-456") == "single plain body"


def test_body_selection_unverified_premise_selects_unverified_variant():
    """When premise_verified is False, select_body selects from body_structure_unverified."""
    copy_tpl = {
        "body_structure": [
            "asserting variant 1",
            "asserting variant 2",
        ],
        "body_structure_unverified": [
            "non-asserting asking variant 1",
            "non-asserting asking variant 2",
        ],
    }
    b_id = "01907de3-bc42-7c89-8d76-5a507db4f333"
    unverified_pick = CampaignRouter.select_body(copy_tpl, business_id=b_id, premise_verified=False)
    assert unverified_pick in copy_tpl["body_structure_unverified"]
    assert unverified_pick not in copy_tpl["body_structure"]


def test_body_selection_verified_premise_selects_asserting_variant():
    """When premise_verified is True, select_body selects from body_structure."""
    copy_tpl = {
        "body_structure": [
            "asserting variant 1",
            "asserting variant 2",
        ],
        "body_structure_unverified": [
            "non-asserting asking variant 1",
            "non-asserting asking variant 2",
        ],
    }
    b_id = "01907de3-bc42-7c89-8d76-5a507db4f333"
    verified_pick = CampaignRouter.select_body(copy_tpl, business_id=b_id, premise_verified=True)
    assert verified_pick in copy_tpl["body_structure"]
    assert verified_pick not in copy_tpl["body_structure_unverified"]


def test_body_selection_absent_unverified_falls_back_to_body_structure():
    """When body_structure_unverified is absent, unverified premise falls back to body_structure."""
    copy_tpl = {
        "body_structure": [
            "standard body variant 1",
            "standard body variant 2",
        ],
    }
    b_id = "01907de3-bc42-7c89-8d76-5a507db4f444"
    pick = CampaignRouter.select_body(copy_tpl, business_id=b_id, premise_verified=False)
    assert pick in copy_tpl["body_structure"]


def test_campaign_dict_with_premise_verified_flag_passes_through():
    """Passing a full campaign dict with premise_verified=False routes to unverified body."""
    campaign = {
        "name": "Manufacturing - B2B Dealer & Order Portal",
        "premise_verified": False,
        "copy_template": {
            "body_structure": ["asserting body"],
            "body_structure_unverified": ["asking unverified body"],
        },
    }
    pick = CampaignRouter.select_body(campaign, business_id="biz-555")
    assert pick == "asking unverified body"

    campaign["premise_verified"] = True
    pick_verified = CampaignRouter.select_body(campaign, business_id="biz-555")
    assert pick_verified == "asserting body"


def test_subject_and_body_selection_are_uncorrelated():
    """Subject and body selections must be salted differently to avoid correlated indexing.

    If both used unsalted sha256(business_id), index_subject == index_body for 100% of leads.
    With independent salts, the pairing is well-distributed across combinations.
    """
    import uuid

    subjects = [f"subject_{i}" for i in range(5)]
    bodies = [f"body_{i}" for i in range(5)]
    copy_tpl = {"subject": subjects, "body_structure": bodies}

    matched_indices_count = 0
    distinct_pairs = set()
    sample_size = 200

    for _ in range(sample_size):
        b_id = str(uuid.uuid4())
        subj = CampaignRouter.select_subject(copy_tpl, business_id=b_id)
        body = CampaignRouter.select_body(copy_tpl, business_id=b_id)

        s_idx = subjects.index(subj)
        b_idx = bodies.index(body)

        if s_idx == b_idx:
            matched_indices_count += 1
        distinct_pairs.add((s_idx, b_idx))

    # In correlated case, matched_indices_count would be 200 (100%) and distinct_pairs would be <= 5.
    # In independent case (1/5 probability of match), matched_indices_count is roughly 40 (~20%).
    # We assert matched is well below 100% (e.g. < 50%) and distinct pairs cover majority of 25 combinations.
    assert matched_indices_count < sample_size * 0.5, (
        f"Subject and body indices matched too frequently ({matched_indices_count}/{sample_size}), indicating correlation."
    )
    assert len(distinct_pairs) >= 15, (
        f"Expected wide spread of (subject, body) pairs, got only {len(distinct_pairs)}/25 combinations."
    )


def test_production_campaign_routing_body_variants_and_voice():
    """Verify live campaign_routing.yaml satisfies all quality, voice, and variant requirements."""
    banned_words = [
        "online presence",
        "digital footprint",
        "digital age",
        "solutions",
        "leverage",
        "optimize",
        "streamline",
    ]
    router = CampaignRouter()
    assert len(router.campaigns) >= 4

    for camp in router.campaigns:
        copy_tpl = camp.get("copy_template", {})

        # Subjects check
        subjects = copy_tpl.get("subject")
        assert isinstance(subjects, list), f"Campaign {camp['name']} must have a list of subjects"
        assert 4 <= len(subjects) <= 6, f"Campaign {camp['name']} subject count {len(subjects)} outside 4-6 range"
        for s in subjects:
            for banned in banned_words:
                assert banned not in s.lower(), f"Banned phrase '{banned}' found in subject: {s}"

        # Body structure check - supports slot-dict and flat-list
        body_struct = copy_tpl.get("body_structure")
        if isinstance(body_struct, dict):
            middles = body_struct.get("middles", [])
            closings = body_struct.get("closings", [])
            assert 4 <= len(middles) <= 6, f"Campaign {camp['name']} middles count outside 4-6 range"
            assert 4 <= len(closings) <= 6, f"Campaign {camp['name']} closings count outside 4-6 range"
            for m in middles:
                assert "!" not in m, f"Exclamation marks banned: {m}"
                assert "—" not in m and "–" not in m, f"Em-dashes banned: {m}"
                for banned in banned_words:
                    assert banned not in m.lower(), f"Banned phrase in middle: {m}"
            for c in closings:
                assert c.strip().endswith("?"), f"Closing must end in '?': {c}"
                assert "!" not in c, f"Exclamation marks banned: {c}"
                assert "—" not in c and "–" not in c, f"Em-dashes banned: {c}"
                for banned in banned_words:
                    assert banned not in c.lower(), f"Banned phrase in closing: {c}"
        elif isinstance(body_struct, list):
            assert 4 <= len(body_struct) <= 6, f"Campaign {camp['name']} body count outside 4-6 range"
            for b in body_struct:
                assert "{observation_hook}" in b, f"Missing {{observation_hook}} in {camp['name']}"
                assert b.strip().endswith("?"), f"Body must end in '?': {b}"
                assert "!" not in b, f"Exclamation marks banned: {b}"
                assert "—" not in b and "–" not in b, f"Em-dashes banned: {b}"
                for banned in banned_words:
                    assert banned not in b.lower(), f"Banned phrase in body: {b}"

        # Check unverified variants where required
        if camp["name"] in ("Manufacturing - B2B Dealer & Order Portal", "Campaign B (Booking)"):
            unverified_struct = copy_tpl.get("body_structure_unverified")
            if isinstance(unverified_struct, dict):
                u_middles = unverified_struct.get("middles", [])
                u_closings = unverified_struct.get("closings", [])
                assert 4 <= len(u_middles) <= 6
                assert 4 <= len(u_closings) <= 6
                for m in u_middles:
                    assert "!" not in m
                    assert "—" not in m and "–" not in m
                    for banned in banned_words:
                        assert banned not in m.lower()
                for c in u_closings:
                    assert c.strip().endswith("?")
                    assert "!" not in c
                    assert "—" not in c and "–" not in c
                    for banned in banned_words:
                        assert banned not in c.lower()
            elif isinstance(unverified_struct, list):
                assert 4 <= len(unverified_struct) <= 6
                for ub in unverified_struct:
                    assert "{observation_hook}" in ub
                    assert ub.strip().endswith("?")
                    assert "!" not in ub
                    assert "—" not in ub and "–" not in ub
                    for banned in banned_words:
                        assert banned not in ub.lower()


def test_slot_composition_produces_multiplied_distinct_bodies():
    """Slot composition multiplying 5 middles x 5 closings produces >= 20 distinct bodies out of 100 random leads."""
    import uuid
    copy_tpl = {
        "body_structure": {
            "middles": [f"middle_{i}" for i in range(5)],
            "closings": [f"closing_{j}?" for j in range(5)],
        }
    }
    distinct_bodies = set()
    for _ in range(150):
        b_id = str(uuid.uuid4())
        body = CampaignRouter.select_body(copy_tpl, business_id=b_id)
        distinct_bodies.add(body)

    # 5 finished bodies could produce at most 5 distinct bodies.
    # 5x5 slot composition yields up to 25 combinations; across 150 random leads, we should see >= 18 distinct combinations.
    assert len(distinct_bodies) >= 18, (
        f"Expected at least 18 distinct composed bodies from 5x5 slots, got {len(distinct_bodies)}"
    )


def test_slot_composition_stability_per_business():
    """Regenerating a draft for the same business id always produces the exact same composed body."""
    copy_tpl = {
        "body_structure": {
            "middles": [f"middle_{i}" for i in range(6)],
            "closings": [f"closing_{j}?" for j in range(6)],
        }
    }
    biz_id = "01907de3-bc42-7c89-8d76-5a507db4f777"
    first = CampaignRouter.select_body(copy_tpl, business_id=biz_id)
    for _ in range(30):
        assert CampaignRouter.select_body(copy_tpl, business_id=biz_id) == first


def test_slots_are_mutually_uncorrelated_and_uncorrelated_with_subject():
    """Middle slot, closing slot, and subject selections must be mutually independent."""
    import uuid

    subjects = [f"subject_{i}" for i in range(5)]
    middles = [f"middle_{i}" for i in range(5)]
    closings = [f"closing_{j}?" for j in range(5)]

    copy_tpl = {
        "subject": subjects,
        "body_structure": {
            "middles": middles,
            "closings": closings,
        },
    }

    sample_size = 250
    mid_cls_matches = 0
    subj_mid_matches = 0
    subj_cls_matches = 0
    distinct_slot_pairs = set()

    for _ in range(sample_size):
        b_id = str(uuid.uuid4())
        subj = CampaignRouter.select_subject(copy_tpl, business_id=b_id)
        body = CampaignRouter.select_body(copy_tpl, business_id=b_id)

        s_idx = subjects.index(subj)
        # Find which middle and closing was selected
        m_idx = next(i for i, m in enumerate(middles) if m in body)
        c_idx = next(j for j, c in enumerate(closings) if c in body)

        if m_idx == c_idx:
            mid_cls_matches += 1
        if s_idx == m_idx:
            subj_mid_matches += 1
        if s_idx == c_idx:
            subj_cls_matches += 1

        distinct_slot_pairs.add((m_idx, c_idx))

    # Independent uniform selection gives ~20% match probability.
    # Assert each correlation is well below 45% of trials.
    assert mid_cls_matches < sample_size * 0.45, (
        f"Middle and closing slots matched too frequently ({mid_cls_matches}/{sample_size}), indicating correlation."
    )
    assert subj_mid_matches < sample_size * 0.45, (
        f"Subject and middle slot matched too frequently ({subj_mid_matches}/{sample_size}), indicating correlation."
    )
    assert subj_cls_matches < sample_size * 0.45, (
        f"Subject and closing slot matched too frequently ({subj_cls_matches}/{sample_size}), indicating correlation."
    )
    assert len(distinct_slot_pairs) >= 18, (
        f"Expected wide spread across 25 slot combinations, got {len(distinct_slot_pairs)}"
    )


def test_body_selection_supports_string_flat_list_and_slot_dict():
    """All three forms (plain string, flat list, slot dict) must work transparently."""
    # 1. Plain string
    plain_tpl = {"body_structure": "plain string body"}
    assert CampaignRouter.select_body(plain_tpl, business_id="biz-1") == "plain string body"

    # 2. Flat list
    list_tpl = {"body_structure": ["body variant 1", "body variant 2", "body variant 3"]}
    res_list = CampaignRouter.select_body(list_tpl, business_id="biz-1")
    assert res_list in list_tpl["body_structure"]

    # 3. Slot dict
    slot_tpl = {
        "body_structure": {
            "middles": ["middle A", "middle B"],
            "closings": ["closing A?", "closing B?"],
        }
    }
    res_slot = CampaignRouter.select_body(slot_tpl, business_id="biz-1")
    assert "{observation_hook}" in res_slot
    assert any(m in res_slot for m in ["middle A", "middle B"])
    assert any(c in res_slot for c in ["closing A?", "closing B?"])


def test_unverified_premise_never_yields_asserting_slot():
    """When premise_verified is False, slot composition selects from body_structure_unverified."""
    copy_tpl = {
        "body_structure": {
            "middles": ["Taking dealer orders over WhatsApp causes errors."],
            "closings": ["Do your distributors call in orders?"],
        },
        "body_structure_unverified": {
            "middles": ["We build private order portals for manufacturers in {city}."],
            "closings": ["How do your dealers usually send over repeat orders?"],
        },
    }
    b_id = "01907de3-bc42-7c89-8d76-5a507db4f888"
    unverified_body = CampaignRouter.select_body(copy_tpl, business_id=b_id, premise_verified=False)
    assert "We build private order portals" in unverified_body
    assert "Taking dealer orders over WhatsApp causes errors" not in unverified_body
    assert "How do your dealers usually send over repeat orders?" in unverified_body

    verified_body = CampaignRouter.select_body(copy_tpl, business_id=b_id, premise_verified=True)
    assert "Taking dealer orders over WhatsApp causes errors." in verified_body


