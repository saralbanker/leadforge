# WhatsApp-Auto: Technical Specification & Implementation Blueprint

## 1. Scope & Objective
This specification defines the schema, module interfaces, data contracts, and implementation rules for **WhatsApp-Auto**. Any AI model or software engineer can implement, maintain, or extend this system from this specification.

---

## 2. SQLite Database Schema (`whatsapp_outreach.db`)

```sql
-- Contacts Table: Core prospect records
CREATE TABLE IF NOT EXISTS wa_contacts (
    id TEXT PRIMARY KEY,                       -- UUIDv7 identifier
    company_name TEXT NOT NULL,                -- Business name
    area TEXT NOT NULL DEFAULT 'Ahmedabad',    -- e.g. 'Vatva GIDC', 'Odhav'
    city TEXT NOT NULL DEFAULT 'Ahmedabad',    -- City anchor
    products TEXT NOT NULL,                    -- e.g. 'industrial valves'
    raw_phone TEXT NOT NULL,                   -- As originally scraped
    normalized_phone TEXT NOT NULL UNIQUE,     -- 10-digit clean mobile (e.g. '9825012345')
    source TEXT NOT NULL DEFAULT 'leadforge',   -- 'leadforge_db', 'indiamart', 'csv'
    status TEXT NOT NULL DEFAULT 'PENDING',    -- 'PENDING', 'SENT', 'REPLIED', 'NOT_ON_WA', 'OPT_OUT'
    notes TEXT,                                -- Optional operator observations
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Dispatch Log Table: History of all outbound messages and interactions
CREATE TABLE IF NOT EXISTS wa_dispatch_logs (
    id TEXT PRIMARY KEY,                       -- UUIDv7
    contact_id TEXT NOT NULL REFERENCES wa_contacts(id),
    template_name TEXT NOT NULL,               -- e.g. 'template_a_tally'
    message_text TEXT NOT NULL,                -- Exact text dispatched
    dispatched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    dispatch_status TEXT NOT NULL,             -- 'DISPATCHED', 'SKIPPED', 'FAILED'
    response_received INTEGER DEFAULT 0,       -- 1 if prospect replied
    response_notes TEXT,                       -- Notes on the prospect's reply
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_wa_contacts_status ON wa_contacts(status);
CREATE INDEX IF NOT EXISTS idx_wa_contacts_phone ON wa_contacts(normalized_phone);
CREATE INDEX IF NOT EXISTS idx_wa_dispatch_contact ON wa_dispatch_logs(contact_id);
```

---

## 3. Core Module Specifications

### Module 1: `foundation/phone_utils.py`
**Responsibility**: Validates and normalizes Indian mobile numbers with zero tolerance for landlines or junk digits.

```python
def normalize_indian_phone(raw_phone: str) -> Optional[str]:
    """Normalizes any raw input into a clean 10-digit Indian mobile number.
    
    Rules:
    1. Strip all spaces, dashes, parentheses, plus signs, dots.
    2. If starts with '91' and length is 12 -> take last 10 digits.
    3. If starts with '0' and length is 11 -> take last 10 digits.
    4. Must be exactly 10 digits.
    5. Valid Indian mobile numbers MUST begin with 6, 7, 8, or 9.
       (Numbers starting with 079, 022, 1, 2, 3, 4, 5 are landlines or invalid).
    
    Returns:
        10-digit string (e.g. '9825012345') or None if invalid.
    """
```

---

### Module 2: `foundation/templates.py`
**Responsibility**: Renders clean, professional, non-spammy messages tailored for Ahmedabad manufacturing owners.

```python
def render_template_a(company_name: str, products: str, area: str) -> str:
    """Renders the primary WhatsApp-to-Tally order entry hook.
    
    Variables:
        company_name: Clean business title (strips long legal suffixes like 'Pvt Ltd')
        products: Product category in lowercase (e.g. 'industrial valves')
        area: Ahmedabad industrial cluster (e.g. 'Vatva GIDC')
        
    Rules:
        - NEVER starts with 'Hi team'.
        - Professional salutation: 'Hello Sir,'
        - Plain vocabulary.
        - Under 65 words.
    """
```

---

### Module 3: `foundation/url_builder.py`
**Responsibility**: Generates standard, cross-platform WhatsApp deep links.

```python
def build_whatsapp_link(phone_10_digits: str, text: str, platform: str = "web") -> str:
    """Constructs a pre-filled WhatsApp deep-link.
    
    Formats:
        - 'web': 'https://web.whatsapp.com/send?phone=91{phone}&text={encoded_text}'
        - 'universal': 'https://wa.me/91{phone}?text={encoded_text}'
    
    Encoding:
        Uses urllib.parse.quote(text, safe='') so newlines and symbols encode cleanly.
    """
```

---

### Module 4: `foundation/queue_manager.py`
**Responsibility**: Loads uncontacted leads, iterates through the daily quota (default: 25), displays formatted prompts, and records status in SQLite.

```python
class WhatsAppQueueManager:
    def __init__(self, db_path: str):
        ...
        
    def import_from_leadforge_db(self, leadforge_db_path: str) -> int:
        """Imports uncontacted Ahmedabad businesses with phone numbers from leadforge.db."""
        ...

    def get_pending_queue(self, limit: int = 25) -> List[Dict[str, Any]]:
        """Fetches up to `limit` contacts with status 'PENDING'."""
        ...

    def mark_contact_status(self, contact_id: str, new_status: str, notes: str = None) -> None:
        """Updates contact status in wa_contacts and logs dispatch in wa_dispatch_logs."""
        ...
```

---

## 4. Integration with LeadForge Ecosystem
WhatsApp-Auto lives side-by-side with LeadForge:
- **Lead Ingestion**: Reads directly from `/mnt/data/rj/email_auto/leadforge/leadforge.db` (specifically `businesses` where `display_phone IS NOT NULL`).
- **Suppression Sync**: Checks `is_suppressed` in LeadForge before queueing to ensure no opted-out contacts are messaged.
- **Independence**: WhatsApp-Auto maintains its own isolated database (`whatsapp_outreach.db`) so email operations and WhatsApp operations never conflict.
