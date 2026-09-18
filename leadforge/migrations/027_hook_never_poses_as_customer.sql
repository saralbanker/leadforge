-- ============================================================================
-- Migration 027 - Hook must never pose the sender as a customer
-- ============================================================================
-- A generated hook shipped as: "K. Rudra Textiles has no clear product details
-- on its website for potential buyers like me." The sender sells web development
-- and is not a buyer. Implying otherwise to win attention is deceptive, and
-- deceptive content in commercial email is what CAN-SPAM prohibits.
-- The validator in outreach/quality.py enforces this; the prompt should also
-- stop producing it in the first place.

UPDATE settings
SET value = replace(
        value,
        '7. Write like a real person quickly typing an email, not a marketing department.',
        '7. Write like a real person quickly typing an email, not a marketing department.
8. NEVER write as though you are their customer or a prospective buyer. You are not shopping. Phrases like "for buyers like me", "as a potential customer", or "I was looking to buy" are forbidden. You are a person who looked at their business, nothing more.'
    ),
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE key = 'llm.system_prompt'
  AND value LIKE '%7. Write like a real person quickly typing an email%'
  AND value NOT LIKE '%NEVER write as though you are their customer%';
