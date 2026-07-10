from leadforge.scorer import process_and_score_leads


def test_process_and_score_leads():
    raw_leads = [
        {
            "name": "Alpha Traders",
            "phone": "+91 9999988888",
            "website": "https://alphatraders.com",
            "address": "Kalupur, Ahmedabad",
            "category": "Traders",
        },
        # Duplicate Alpha Traders (should be removed)
        {
            "name": "Alpha Traders",
            "phone": "+919999988888",
            "website": "https://alphatraders.com",
            "address": "Kalupur, Ahmedabad",
            "category": "Traders",
        },
        # High Priority lead (no website)
        {
            "name": "Beta Industries",
            "phone": "+91 8888877777",
            "website": "",
            "address": "Naroda, Ahmedabad",
            "category": "Traders",
        },
    ]

    processed = process_and_score_leads(raw_leads)

    # Verify deduplication
    assert len(processed) == 2

    # Verify sorting (High priority/score 60 first)
    assert processed[0]["name"] == "Beta Industries"
    assert processed[0]["priority"] == "High"
    assert processed[0]["score"] == 60

    assert processed[1]["name"] == "Alpha Traders"
    assert processed[1]["priority"] == "Medium"
    assert processed[1]["score"] == 0
