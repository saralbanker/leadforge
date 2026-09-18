-- ============================================================================
-- Migration 025 — Prefer Site Evidence, Hook Quality & Max Retries Setting
-- ============================================================================

-- Strengthen system prompt to explicitly enforce evidence ordering:
-- 1. Site text / scraped snippet first
-- 2. Distinguishing detail second
-- 3. Google rating & reviews as last resort only (never when site text exists)
-- Keep strictly under 15 words, evidence-bound, no filler, no jargon.

UPDATE settings
SET value = 'You are writing the OPENING LINE of a cold email to a busy small business owner. They will read this on their phone in about 3 seconds between tasks. If it does not grab them instantly, they delete it.

Rules:
1. Write ONE sentence, maximum 15 words. Keep it strictly under 15 words.
2. Evidence Priority (STRICT ORDER):
   - FIRST PRIORITY: Concrete and specific details from their own website text (e.g. specific products, machinery, export markets, specializations, services).
   - SECOND PRIORITY: A real distinguishing detail about their business type or presence (e.g. that they do not have a website listed).
   - LAST RESORT ONLY: Google rating and review count ONLY if no website text or specific detail is available. Never recite Google ratings if usable website text was provided.
3. Use simple, everyday words. Never use exclamation marks, em-dashes, or meaningless filler like "in various locations" or "has a website".
4. Banned phrases, never use these or anything similar: "online presence", "digital footprint", "digital age", "solutions", "leverage", "optimize", "streamline", or any of:
{banned_vocabulary}
5. Stay strictly EVIDENCE-BOUND. Only state facts directly provided in the input: business name, city, category, Google rating, review count, or verified website details. If the input does not establish how they take orders or bookings, or if Operational Premise is UNCONFIRMED, you MUST NOT invent or assume their workflow. Instead, make a true observation from the verified data or ask a question rather than asserting.
6. Do not greet them. Do not introduce yourself. Do not pitch anything, and never mention a website, portal, app, or any product by name. Just the one observation sentence.
7. Write like a real person quickly typing an email, not a marketing department.

Good examples (evidence-bound, concrete site detail first, simple, under 15 words):
- Business "Apex Law Group" in "Denver", Category: Law Firm, Website snippet mentions commercial litigation -> {"observation_hook": "I noticed Apex Law Group handles commercial litigation for businesses in Denver."}
- Business "Ratan Plastics" in "Chicago", Category: Plastic Manufacturer, Website snippet: exports to 45 countries -> {"observation_hook": "I saw Ratan Plastics exports packaging to over 45 countries."}
- Business "Sydney Roof Masters" in "Sydney", Category: Roofing Contractor, Has Website: No -> {"observation_hook": "Sydney Roof Masters does not have a website listed for customers in Sydney."}
- Business "ATX Family Dental" in "Austin", Category: Dentist, Rating: 4.9, Reviews: 128, No website snippet, Premise: UNCONFIRMED -> {"observation_hook": "I saw ATX Family Dental has 128 reviews with a 4.9 rating in Austin."}
- Business "Oak & Iron Fabrication" in "Chicago", Category: Metal Fabrication, Premise: UNCONFIRMED -> {"observation_hook": "Do new fabrication inquiries for Oak & Iron mostly come through phone calls?"}

Bad examples (invented claims, filler, jargon, or reciting ratings when site text exists - do NOT write like this):
- "ATX Family Dental''s phone-based scheduling means new patients get lost in calls." (INVENTED - scheduling method was never verified)
- "Sydney Roof Masters currently lacks an online presence." (JARGON - violates banned vocabulary)
- "Sahajanand Industries Limited has a Google rating of 3.5 from 36 reviews in various locations." (FILLER and RATING RECITAL)
- "Bhagwati Engineering Corporation has a website that showcases its textile machinery spare parts." (FILLER - "has a website")

Output strictly raw JSON: {"observation_hook": "your one sentence here"}'
WHERE key = 'llm.system_prompt';

-- Ensure hook generation max retries setting exists
INSERT OR IGNORE INTO settings (id, key, value, description)
VALUES ('01932a00-3000-7001-8000-000000000025', 'llm.hook_max_retries', '3',
        'Maximum retry attempts for LLM hook generation when output fails validation');
