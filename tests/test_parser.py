from leadforge.parser import parse_business_details


def test_parse_business_details_no_website():
    raw_name = " Ahmedabad Manufacturers Co.  "
    raw_phone = "phone:tel:+91 98765 43210"
    raw_website = ""
    raw_address = (
        "Address: 12, GIDC Industrial Estate, Vatva, Ahmedabad, Gujarat 382445"
    )
    raw_category = "Manufacturers"
    raw_url = "https://google.com/maps/place/test"

    parsed = parse_business_details(
        name=raw_name,
        phone_data=raw_phone,
        website=raw_website,
        address=raw_address,
        category=raw_category,
        source_url=raw_url,
        city="Ahmedabad",
    )

    assert parsed["name"] == "Ahmedabad Manufacturers Co."
    assert parsed["phone"] == "+919876543210"
    assert parsed["website"] == ""
    assert (
        parsed["address"]
        == "12, GIDC Industrial Estate, Vatva, Ahmedabad, Gujarat 382445"
    )
    assert parsed["area"] == "Vatva"
    assert parsed["category"] == "Manufacturers"
    assert parsed["postal_code"] == "382445"


def test_parse_business_details_with_website_and_redirect():
    raw_name = "Hospital Care"
    raw_phone = ""
    # Redirection url format
    raw_website = (
        "https://www.google.com/url?q=https://hospitalcare.in/&sa=D&source=editors"
    )
    raw_address = "Address: Navrangpura, Ahmedabad"
    raw_category = "Hospitals"
    raw_url = "https://google.com/maps/place/test2"

    parsed = parse_business_details(
        name=raw_name,
        phone_data=raw_phone,
        website=raw_website,
        address=raw_address,
        category=raw_category,
        source_url=raw_url,
    )

    assert parsed["name"] == "Hospital Care"
    assert parsed["website"] == "https://hospitalcare.in/"
    assert parsed["area"] == "Navrangpura"
    assert parsed["postal_code"] == ""


def test_extract_postal_code():
    from leadforge.parser import extract_postal_code

    # PIN at the end of a normal address
    assert extract_postal_code("12, GIDC, Vatva, Ahmedabad, Gujarat 382445") == "382445"
    # Last standalone 6-digit group wins (PIN follows the street number)
    assert extract_postal_code("380001 Building, Ahmedabad 380015") == "380015"
    # No embedded match inside longer digit runs (phone numbers)
    assert extract_postal_code("Call 9876543210, Ahmedabad") == ""
    # PINs never start with 0
    assert extract_postal_code("Sector 098765, Ahmedabad") == ""
    assert extract_postal_code("") == ""
