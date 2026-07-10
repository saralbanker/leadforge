"""Phase 4 — Digital Maturity Assessor Unit Tests.

Covers:
- All 4 dimension assessments
- Grade thresholds (A/B/C/D/F)
- Data completeness calculation
- Gap detection
- Strength detection
- Explanation structure
- Determinism
"""

import os
import tempfile
from pathlib import Path

import pytest

import leadforge.database

_temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_temp_db_path = Path(_temp_db.name)
_temp_db.close()
leadforge.database.DB_PATH = _temp_db_path

from leadforge.database import initialize_database  # noqa: E402
from leadforge.digital_maturity import DigitalMaturityAssessor  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def db_setup():
    initialize_database()
    yield
    if _temp_db_path.exists():
        try:
            os.remove(_temp_db_path)
        except Exception:
            pass


def _biz(**kwargs):
    base = {
        "name": "Test Business",
        "website": "",
        "phone": "",
        "contact_email": "",
        "rating": None,
        "review_count": None,
        "business_status": "OPERATIONAL",
        "categories": "",
    }
    base.update(kwargs)
    return base


class TestDigitalMaturityDimensions:
    def assessor(self):
        return DigitalMaturityAssessor()

    def test_no_website_scores_zero_web_dimension(self):
        a = self.assessor()
        profile = a.assess(_biz(website=""))
        web_dim = next(d for d in profile.dimensions if d.name == "WEB_PRESENCE")
        assert web_dim.score == 0.0
        assert web_dim.gap is True

    def test_has_website_scores_max_web_dimension(self):
        a = self.assessor()
        profile = a.assess(_biz(website="https://example.com"))
        web_dim = next(d for d in profile.dimensions if d.name == "WEB_PRESENCE")
        assert web_dim.score == 25.0
        assert web_dim.gap is False

    def test_zero_reviews_scores_zero_search_dimension(self):
        a = self.assessor()
        profile = a.assess(_biz(review_count=0))
        search_dim = next(d for d in profile.dimensions if d.name == "SEARCH_SIGNAL")
        assert search_dim.score == 0.0
        assert search_dim.gap is True

    def test_high_reviews_scores_max_search_dimension(self):
        a = self.assessor()
        profile = a.assess(_biz(review_count=150))
        search_dim = next(d for d in profile.dimensions if d.name == "SEARCH_SIGNAL")
        assert search_dim.score == 25.0
        assert search_dim.gap is False

    def test_no_rating_gets_partial_reputation_score(self):
        """Unknown rating is treated as partial — not a full gap."""
        a = self.assessor()
        profile = a.assess(_biz(rating=None))
        rep_dim = next(d for d in profile.dimensions if d.name == "REPUTATION")
        assert rep_dim.score > 0.0

    def test_excellent_rating_scores_max_reputation(self):
        a = self.assessor()
        profile = a.assess(_biz(rating=4.8))
        rep_dim = next(d for d in profile.dimensions if d.name == "REPUTATION")
        assert rep_dim.score == 25.0
        assert rep_dim.gap is False

    def test_poor_rating_scores_zero_reputation(self):
        a = self.assessor()
        profile = a.assess(_biz(rating=2.5))
        rep_dim = next(d for d in profile.dimensions if d.name == "REPUTATION")
        assert rep_dim.score == 0.0
        assert rep_dim.gap is True

    def test_email_only_scores_partial_contact_reach(self):
        a = self.assessor()
        profile = a.assess(_biz(contact_email="a@b.com", phone=""))
        contact_dim = next(d for d in profile.dimensions if d.name == "CONTACT_REACH")
        assert 0 < contact_dim.score < 25.0

    def test_email_and_phone_scores_max_contact_reach(self):
        a = self.assessor()
        profile = a.assess(_biz(contact_email="a@b.com", phone="+91999"))
        contact_dim = next(d for d in profile.dimensions if d.name == "CONTACT_REACH")
        assert contact_dim.score == 25.0
        assert contact_dim.gap is False

    def test_no_contact_scores_zero_contact_reach(self):
        a = self.assessor()
        profile = a.assess(_biz(contact_email="", phone=""))
        contact_dim = next(d for d in profile.dimensions if d.name == "CONTACT_REACH")
        assert contact_dim.score == 0.0
        assert contact_dim.gap is True


class TestDigitalMaturityGrades:
    def assessor(self):
        return DigitalMaturityAssessor()

    def test_all_perfect_scores_grade_a(self):
        a = self.assessor()
        profile = a.assess(
            _biz(
                website="https://example.com",
                rating=4.9,
                review_count=500,
                contact_email="owner@example.com",
                phone="+91999",
            )
        )
        assert profile.grade == "A"
        assert profile.score >= 80.0

    def test_all_empty_scores_grade_f(self):
        a = self.assessor()
        profile = a.assess(_biz())  # empty — only partial reputation
        assert profile.grade in ("F", "D")  # partial reputation pulls it just above 0

    def test_grade_is_valid_enum(self):
        a = self.assessor()
        for biz in [
            _biz(),
            _biz(website="https://x.com"),
            _biz(rating=4.5, review_count=200),
        ]:
            profile = a.assess(biz)
            assert profile.grade in ("A", "B", "C", "D", "F")

    def test_score_is_within_0_100(self):
        a = self.assessor()
        profile = a.assess(
            _biz(
                website="https://x.com",
                rating=4.0,
                review_count=30,
                contact_email="e@x.com",
                phone="+91000",
            )
        )
        assert 0.0 <= profile.score <= 100.0


class TestDigitalMaturityDataCompleteness:
    def assessor(self):
        return DigitalMaturityAssessor()

    def test_fully_populated_is_1(self):
        a = self.assessor()
        profile = a.assess(
            _biz(
                name="Full Biz",
                website="https://x.com",
                phone="+9199",
                contact_email="a@b.com",
                rating=4.0,
                review_count=50,
                business_status="OPERATIONAL",
                categories="[Traders]",
            )
        )
        assert profile.data_completeness == 1.0

    def test_empty_business_has_low_completeness(self):
        a = self.assessor()
        profile = a.assess(
            {
                "name": "Sparse",
                "website": "",
                "phone": "",
                "contact_email": "",
                "rating": None,
                "review_count": None,
                "business_status": "",
                "categories": "",
            }
        )
        # Only "name" is present → 1/8
        assert profile.data_completeness <= 0.2

    def test_completeness_between_0_and_1(self):
        a = self.assessor()
        profile = a.assess(_biz(website="https://x.com", phone="+91999"))
        assert 0.0 <= profile.data_completeness <= 1.0


class TestDigitalMaturityGapStrengths:
    def assessor(self):
        return DigitalMaturityAssessor()

    def test_no_website_appears_in_gaps(self):
        a = self.assessor()
        profile = a.assess(_biz(website=""))
        assert any("website" in g.lower() or "web" in g.lower() for g in profile.gaps)

    def test_has_website_appears_in_strengths(self):
        a = self.assessor()
        profile = a.assess(_biz(website="https://example.com"))
        assert any(
            "website" in s.lower() or "web" in s.lower() for s in profile.strengths
        )

    def test_gaps_and_strengths_are_non_overlapping(self):
        """Every dimension either contributes a gap OR a strength, not both."""
        a = self.assessor()
        profile = a.assess(_biz(website="https://x.com", rating=4.5, review_count=200))
        assert len(set(profile.gaps) & set(profile.strengths)) == 0


class TestDigitalMaturityExplanation:
    def assessor(self):
        return DigitalMaturityAssessor()

    def test_explanation_contains_business_name(self):
        a = self.assessor()
        # Merge with explicit name winning over _biz() default
        profile2 = a.assess({**_biz(), "name": "My Named Biz"})
        assert "My Named Biz" in profile2.explanation

        assert "My Named Biz" in profile2.explanation

    def test_explanation_contains_grade(self):
        a = self.assessor()
        profile = a.assess(_biz())
        assert profile.grade in profile.explanation

    def test_explanation_contains_dimension_names(self):
        a = self.assessor()
        profile = a.assess(_biz(website="https://x.com", rating=4.0, review_count=50))
        for dim in profile.dimensions:
            assert dim.name in profile.explanation


class TestDigitalMaturityDeterminism:
    def assessor(self):
        return DigitalMaturityAssessor()

    def test_same_input_produces_same_output(self):
        a = self.assessor()
        biz = _biz(
            website="https://x.com",
            rating=4.2,
            review_count=60,
            contact_email="a@b.com",
            phone="+91999",
        )
        r1 = a.assess(biz)
        r2 = a.assess(biz)
        assert r1.score == r2.score
        assert r1.grade == r2.grade
        assert r1.data_completeness == r2.data_completeness
        assert len(r1.gaps) == len(r2.gaps)
        assert len(r1.strengths) == len(r2.strengths)
