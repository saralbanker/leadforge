"""Tests for foundation/phone_utils.py."""

import pytest
from foundation.phone_utils import format_display_phone, normalize_indian_phone


class TestNormalizeIndianPhone:
    """Test suite for Indian mobile phone number normalization."""

    def test_clean_10_digit_valid(self):
        """Standard 10-digit valid Indian mobile numbers (starting with 6, 7, 8, 9)."""
        assert normalize_indian_phone("9825012345") == "9825012345"
        assert normalize_indian_phone("8765432109") == "8765432109"
        assert normalize_indian_phone("7817971213") == "7817971213"
        assert normalize_indian_phone("6353476796") == "6353476796"

    def test_with_country_code_plus_91(self):
        """+91 prefix with various spacings and dashes."""
        assert normalize_indian_phone("+91 98250 12345") == "9825012345"
        assert normalize_indian_phone("+91-98250-12345") == "9825012345"
        assert normalize_indian_phone("+919825012345") == "9825012345"

    def test_with_country_code_91_no_plus(self):
        """91 prefix (12 digits total)."""
        assert normalize_indian_phone("919825012345") == "9825012345"

    def test_with_trunk_prefix_zero(self):
        """0 prefix (11 digits total)."""
        assert normalize_indian_phone("09825012345") == "9825012345"
        assert normalize_indian_phone("06353476796") == "6353476796"

    def test_invalid_lengths(self):
        """Rejects numbers that do not have 10 digits."""
        assert normalize_indian_phone("982501234") is None  # 9 digits
        assert normalize_indian_phone("98250123456") is None  # 11 digits not starting with 0
        assert normalize_indian_phone("") is None
        assert normalize_indian_phone(None) is None
        assert normalize_indian_phone("abc") is None

    def test_invalid_start_digits(self):
        """Rejects numbers starting with 0, 1, 2, 3, 4, 5 (landlines or unallocated)."""
        assert normalize_indian_phone("1234567890") is None
        assert normalize_indian_phone("2345678901") is None
        assert normalize_indian_phone("3456789012") is None
        assert normalize_indian_phone("4567890123") is None
        assert normalize_indian_phone("5678901234") is None

    def test_landline_rejection_as_documented(self):
        """Verify documented claim: 'Ahmedabad landline 079-25831234 is rejected'."""
        # The docstring explicitly claims:
        # '(e.g., Ahmedabad landline 079-25831234 is rejected).'
        result = normalize_indian_phone("079-25831234")
        assert result is None, f"Expected 079-25831234 to be rejected as landline, but got: {result}"

    def test_landline_with_various_delimiters(self):
        """Verify that various 079 landline formats are properly rejected."""
        assert normalize_indian_phone("07922743495") is None
        assert normalize_indian_phone("+91-79-26402695") is None
        assert normalize_indian_phone("079 40070099") is None


class TestFormatDisplayPhone:
    """Test suite for phone formatting for operator reading."""

    def test_format_display_phone(self):
        assert format_display_phone("9825012345") == "+91 98250 12345"

    def test_format_display_phone_invalid(self):
        assert format_display_phone("123") == "123"
        assert format_display_phone("") == ""
