# Workspace Rules for LeadForge & Automation Workspaces

## Documentation & Planning Output Policy (CLI Mode)

- Whenever writing an audit, plan, architecture review, technical specification, or any analytical/planning output that exceeds **3,000 characters**, DO NOT dump the full verbose content directly into the chat/terminal response.
- **Always write the full content into a Markdown (`.md`) file** inside an appropriately named folder under `docs/` (e.g., `docs/<task_topic>/<DOCUMENT_NAME>.md`).
- In the conversation output, provide:
  1. A clickable GitHub-style file link to the generated Markdown file.
  2. A concise, executive-level summary highlighting key findings, blockers, and next actions.
- This rule applies specifically when operating in CLI mode.
