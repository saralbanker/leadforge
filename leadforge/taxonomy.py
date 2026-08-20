"""Hierarchical Industry Taxonomy and Categorical Library for LeadForge.

Provides a rich, high-density categorical tree across Manufacturing,
Construction, Healthcare, Automotive, IT, Professional Services, and Wholesale,
with specialized sub-categories and query expansion keywords.
"""

from typing import Dict, List, Any, Optional

TAXONOMY: Dict[str, Dict[str, Any]] = {
    "Manufacturing": {
        "description": "Industrial production, fabrication, and chemical processing units",
        "subcategories": {
            "Plastics & Polymers": {
                "keywords": [
                    "Plastic Injection Moulding",
                    "Plastic Blow Moulding",
                    "Polymer Packaging",
                    "PVC Pipes Manufacturer",
                    "HDPE Pipe Manufacturer",
                    "Plastic Extrusion Plant",
                    "Plastic Masterbatch Manufacturer",
                    "Rubber & Elastomer Products",
                    "Rigid Packaging Containers",
                ],
                "default_services": ["Website Design & Development", "B2B Catalog Portal", "SEO & Export Lead Gen"],
            },
            "Boilers, Tanks & Pressure Vessels": {
                "keywords": [
                    "Industrial Boiler Manufacturer",
                    "Steam Boiler Manufacturers",
                    "Pressure Vessel Manufacturer",
                    "Heat Exchanger Manufacturers",
                    "Storage Tank Fabrication",
                    "Thermic Fluid Heater",
                    "Steam Turbines & Piping",
                    "IBR Boiler Fabricator",
                ],
                "default_services": ["Custom Engineering Website", "Digital Product Catalog", "B2B Lead Generation"],
            },
            "CNC Machining & Precision Tooling": {
                "keywords": [
                    "CNC Machining Works",
                    "VMC 4-Axis Machining",
                    "Precision Lathe Works",
                    "Tool and Die Makers",
                    "Laser Cutting Job Works",
                    "Sheet Metal Fabrication",
                    "Press Tools & Moulds",
                    "Custom Engineering Components",
                ],
                "default_services": ["Industrial Website Development", "Technical Spec Sheets", "Google Search Ads"],
            },
            "Chemicals, Dyes & Pigments": {
                "keywords": [
                    "Reactive Dyes Manufacturer",
                    "Acid Dyes & Pigments",
                    "Industrial Chemicals Manufacturer",
                    "Specialty Chemical Plant",
                    "Chemical Solvents & Resins",
                    "Bulk Drug Intermediates",
                    "Textile Auxiliaries & Chemicals",
                    "Agrochemicals & Fertilizers",
                ],
                "default_services": ["Export B2B Web Portal", "Compliance & Safety Page Design", "International SEO"],
            },
            "Electrical, Transformers & Switchgears": {
                "keywords": [
                    "Distribution Transformer Manufacturer",
                    "HT Control Panel Manufacturer",
                    "LT Switchgear Manufacturer",
                    "Industrial Electric Motors",
                    "Power Distribution Panels",
                    "Servo Voltage Stabilizer",
                    "Cable Tray & Conduit Manufacturer",
                    "Diesel Generator Manufacturer",
                ],
                "default_services": ["B2B Industrial Catalog", "Corporate Web Branding", "Inquiry Form Optimization"],
            },
            "Metals, Forging & Foundry": {
                "keywords": [
                    "Steel Fabrication Works",
                    "Cast Iron Foundry",
                    "Aluminum Die Casting",
                    "Drop Forging Units",
                    "Stainless Steel Fasteners",
                    "Structural Steel Fabricator",
                    "Flanges & Pipe Fittings Manufacturer",
                    "Wire Mesh & Spring Manufacturer",
                ],
                "default_services": ["B2B Supplier Web Portal", "Product Portfolio Design", "Local SEO & Outreach"],
            },
            "Textiles, Spinning & Garments": {
                "keywords": [
                    "Cotton Spinning Mill",
                    "Weaving Mills & Grey Fabric",
                    "Denim Fabric Manufacturer",
                    "Technical Textiles Plant",
                    "Garment Exporters & Manufacturers",
                    "Knitting & Hosiery Unit",
                    "Yarn Dyeing & Processing",
                    "Non-Woven Fabric Manufacturer",
                ],
                "default_services": ["Export Catalog Website", "B2B Brand Showroom", "Global Sourcing SEO"],
            },
            "Pharmaceuticals & Medical Devices": {
                "keywords": [
                    "Bulk Drugs API Manufacturer",
                    "Pharma Formulation Unit",
                    "Ayurvedic & Herbal Medicine Plant",
                    "Nutraceuticals Manufacturer",
                    "Blister & Vial Packaging Machines",
                    "Surgical Equipment Manufacturer",
                    "Hospital Furniture Manufacturer",
                    "Cleanroom Equipment Manufacturer",
                ],
                "default_services": ["GMP Compliant Website", "Product Certification Showcase", "B2B Distributor Portal"],
            },
            "Food Processing & Agro Industries": {
                "keywords": [
                    "Roller Flour Mill",
                    "Edible Oil Refinery Plant",
                    "Dairy Processing Machinery",
                    "Solvent Extraction Plant",
                    "Spices Processing & Export",
                    "Rice & Dal Mill Manufacturer",
                    "Cold Chain & Refrigeration Plant",
                    "Commercial Food Packaging Machines",
                ],
                "default_services": ["Modern FMCG Website", "FSSAI / ISO Showcase", "Distributor Onboarding Funnels"],
            },
            "Packaging & Commercial Printing": {
                "keywords": [
                    "Corrugated Box Manufacturer",
                    "Flexible Packaging & Pouches",
                    "Commercial Offset Printing Press",
                    "Labels & Shrink Sleeves Manufacturer",
                    "Carton Box & Duplex Board Packaging",
                    "Wooden Pallets & Industrial Packing",
                ],
                "default_services": ["B2B Packaging Portfolio", "Online Quote Request System", "Client Case Studies"],
            },
        },
    },
    "Construction & Infrastructure": {
        "description": "Building materials, civil contracting, architecture, and interior infrastructure",
        "subcategories": {
            "Building Materials & RMC": {
                "keywords": [
                    "Ready Mix Concrete RMC Plant",
                    "Cement & AAC Block Manufacturer",
                    "Ceramic Tiles & Sanitaryware",
                    "Plywood & Laminates Manufacturer",
                    "Ready Mix Mortar & Plaster",
                    "Stone & Granite Processing",
                ],
                "default_services": ["Product Visualizer Website", "Dealer Locator Integration", "Local Search Optimization"],
            },
            "Civil & Structural Contractors": {
                "keywords": [
                    "Civil Construction Company",
                    "Industrial PEB Shed Contractor",
                    "Earthmoving & Piling Contractors",
                    "Road & Highway Contractors",
                    "Waterproofing Contractors",
                ],
                "default_services": ["Project Portfolio Website", "Tender & Credential Showcase", "Lead Generation Funnel"],
            },
            "Architects & Interior Designers": {
                "keywords": [
                    "Commercial Interior Designers",
                    "Architectural Design Firms",
                    "Turnkey Office Fitout Contractors",
                    "Modular Furniture & Kitchens",
                ],
                "default_services": ["High-End Portfolio Website", "3D Render Showcases", "Instagram & Social Lead Gen"],
            },
        },
    },
    "Healthcare & Medical": {
        "description": "Clinics, specialty hospitals, diagnostic centers, and wellness facilities",
        "subcategories": {
            "Specialty Hospitals & Clinics": {
                "keywords": [
                    "Multi-specialty Hospital",
                    "Dental Implant Clinic",
                    "Eye Care & Ophthalmology Clinic",
                    "IVF & Fertility Centre",
                    "Orthopedic & Joint Replacement Centre",
                    "Cosmetic & Dermatology Clinic",
                ],
                "default_services": ["Online Appointment Booking", "Google Maps Local Pack Ranking", "Doctor Profile Pages"],
            },
            "Diagnostic & Pathology Labs": {
                "keywords": [
                    "Pathology Diagnostic Centre",
                    "MRI & CT Scan Centre",
                    "Ultrasound & Digital X-Ray Lab",
                    "Preventive Health Checkup Centre",
                ],
                "default_services": ["Report Download Portal", "Home Collection Booking", "Local Area SEO"],
            },
        },
    },
    "Automotive & Logistics": {
        "description": "Auto parts, commercial body building, fleet operations, and freight logistics",
        "subcategories": {
            "Auto Components & Body Building": {
                "keywords": [
                    "Auto Components Manufacturer",
                    "Commercial Vehicle Body Builders",
                    "Tractor & Agricultural Spares",
                    "Hydraulic Tipper & Trailer Manufacturer",
                    "Automotive Springs & Suspension",
                ],
                "default_services": ["B2B OEM Catalog", "Digital Inquiries Form", "Search Advertising"],
            },
            "Freight & Logistics Operators": {
                "keywords": [
                    "Fleet Owners & Truck Transport",
                    "Cold Storage & Logistics Warehousing",
                    "Customs Clearing & Freight Forwarders",
                    "Industrial Heavy Haulage Transport",
                ],
                "default_services": ["Consignment Tracking System", "Fleet Showcase Website", "Corporate Logistics Pitch"],
            },
        },
    },
    "Information Technology & Digital": {
        "description": "Software, web design, cloud infrastructure, and IT support services",
        "subcategories": {
            "Software & Web Agencies": {
                "keywords": [
                    "Custom Software Development Company",
                    "Mobile App Development Agency",
                    "Web Design & Development Agency",
                    "Ecommerce Development Services",
                    "UI/UX Design Studio",
                ],
                "default_services": ["Modern Tech Portfolio", "Case Studies & Whitepapers", "International SEO"],
            },
            "Cloud & IT Infrastructure": {
                "keywords": [
                    "Cloud Hosting & DevOps Services",
                    "Cybersecurity & Network Auditing",
                    "CCTV & Biometric Security Systems",
                    "IT Hardware & Server AMC Services",
                ],
                "default_services": ["Corporate AMC Contract Portal", "Security Audit Landing Pages", "B2B Lead Gen"],
            },
        },
    },
    "Professional & Business Services": {
        "description": "Corporate compliance, accounting, legal, and industrial consultancy",
        "subcategories": {
            "Accounting & Corporate Law": {
                "keywords": [
                    "Chartered Accountants CA Firm",
                    "Corporate Law & Legal Consultants",
                    "GST & Income Tax Consultants",
                    "Trademark & Patent Registration",
                ],
                "default_services": ["Professional Advisory Website", "Client Onboarding Forms", "Knowledge Hub / Blog"],
            },
            "Industrial & Environmental Consultants": {
                "keywords": [
                    "Pollution Control & ETP Consultants",
                    "ISO Certification Consultants",
                    "Industrial Safety & Energy Auditors",
                    "Labour Law & Factory Act Consultants",
                ],
                "default_services": ["Corporate Credential Portal", "Audit Request Forms", "B2B Inbound Strategy"],
            },
        },
    },
    "Wholesale, Distribution & Retail": {
        "description": "Bulk trading, distributor networks, and commercial retail supplies",
        "subcategories": {
            "Industrial Wholesale & Trading": {
                "keywords": [
                    "Industrial Hardware Wholesalers",
                    "Electrical Switchgear Distributors",
                    "Industrial Chemical Traders",
                    "Building Materials Distributors",
                    "Pumps & Valves Stockists",
                ],
                "default_services": ["B2B Wholesale Ordering Portal", "Product Price Lists", "WhatsApp Commerce Hook"],
            },
        },
    },
}


def get_taxonomy_tree() -> Dict[str, Any]:
    """Returns the complete hierarchical taxonomy tree."""
    return TAXONOMY


def get_all_sectors() -> List[str]:
    """Returns a list of all primary industry sectors."""
    return list(TAXONOMY.keys())


def get_subcategories(sector: str) -> List[str]:
    """Returns a list of sub-category names for a given sector."""
    if sector not in TAXONOMY:
        return []
    return list(TAXONOMY[sector].get("subcategories", {}).keys())


def get_keywords_for_subcategory(sector: str, subcategory: str) -> List[str]:
    """Returns search expansion keywords for a specific sector + subcategory."""
    if sector not in TAXONOMY:
        return []
    sub = TAXONOMY[sector].get("subcategories", {}).get(subcategory, {})
    return sub.get("keywords", [])


def get_default_services_for_category(sector: str, subcategory: Optional[str] = None) -> List[str]:
    """Returns recommended services based on the sector and subcategory."""
    if sector in TAXONOMY:
        if subcategory and subcategory in TAXONOMY[sector].get("subcategories", {}):
            return TAXONOMY[sector]["subcategories"][subcategory].get(
                "default_services", ["Website Design & Development", "B2B Lead Generation"]
            )
    return ["Website Design & Development", "SEO & Local Marketing"]


def resolve_search_query(city: str, sector: str, subcategory: Optional[str] = None) -> str:
    """Constructs a targeted search query from sector, subcategory, and city."""
    if subcategory:
        return f"{subcategory} in {city}"
    return f"{sector} in {city}"


# Aliases for flexible import conventions
INDUSTRY_TAXONOMY = TAXONOMY
get_subcategories_for_sector = get_subcategories
build_specialized_search_query = lambda sector, subcategory, city: resolve_search_query(city, sector, subcategory)
get_service_offerings_for_niche = lambda sector, subcategory: get_default_services_for_category(sector, subcategory)
