-- ============================================================================
-- LeadForge Migration (019_local_llm_settings.sql)
-- Seeds configurable Local LM (Ollama / Local LLM) Control Settings & Prompts.
-- ============================================================================

INSERT OR IGNORE INTO settings (id, key, value, description) VALUES
    ('01932a00-3000-7001-8000-000000000001',
     'llm.enabled',
     'true',
     'Enable or disable local LLM (Ollama) inference for outreach copy and hook generation'),

    ('01932a00-3000-7001-8000-000000000002',
     'llm.api_url',
     'http://localhost:11434',
     'Base URL endpoint for Ollama or OpenAI-compatible local LM server'),

    ('01932a00-3000-7001-8000-000000000003',
     'llm.model_name',
     'llama3.2:3b',
     'Target local model tag in Ollama (e.g. llama3.2:3b, qwen2.5:3b, mistral, deepseek-r1:1.5b)'),

    ('01932a00-3000-7001-8000-000000000004',
     'llm.temperature',
     '0.2',
     'Sampling temperature for local LM inference (0.0 = deterministic, 1.0 = highly creative)'),

    ('01932a00-3000-7001-8000-000000000005',
     'llm.max_tokens',
     '150',
     'Maximum token generation limit (num_predict) per hook/draft generation call'),

    ('01932a00-3000-7001-8000-000000000006',
     'llm.system_prompt',
     'You are an expert B2B outreach copywriter specialized in industrial, manufacturing, and local business growth. Write a concise, highly tailored observation hook for the target business based on their gathered operational details.

Writing Rules:
1. Write like a real business development professional sending a quick, relevant inquiry.
2. Ground the observation specifically in their real industry, city/industrial zone, and digital infrastructure (e.g. absence of digital spec catalog or online procurement).
3. Do NOT use generic pleasantries, greetings, or "hope you are well". Keep it under 25 words.
4. Output strictly raw JSON: {"observation_hook": "Your single observation sentence here."}',
     'System prompt controlling the personality, rules, and output schema of the local LM'),

    ('01932a00-3000-7001-8000-000000000007',
     'llm.user_prompt_template',
     'Business Name: {business_name}
Category: {category}
City: {city}
Area / Industrial Zone: {area}
Has Website: {has_website}
Website Domain / Scraped Snippet: {scraped_text}
Google Rating: {rating}
Google Review Count: {review_count}

Output the single observation hook in raw JSON.',
     'Dynamic prompt template with variable interpolation ({business_name}, {city}, {category}, {area}, {scraped_text}, {rating}, {review_count}, {has_website})');
