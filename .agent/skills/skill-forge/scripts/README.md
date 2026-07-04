# TTL Watcher — Skill Auto-Expiry Script

Automatically deletes custom skills that haven't been used within a configurable TTL (default: 30 days).

## How Usage is Tracked

Every time the AI activates a custom skill, it writes a timestamp to:

```
.agent/skills/.skill_usage.json
```

Format:
```json
{
  "my-custom-skill": "2026-03-15T10:30:00Z",
  "another-skill": "2026-02-28T14:00:00Z"
}
```

Timestamps are ISO-8601 UTC. Each key is a skill name matching its directory under `.agent/skills/`.

## Running the Watcher

### Manual Run

```bash
# From project root
python .agent/skills/skill-forge/scripts/ttl_watcher.py
```

### Dry Run (preview deletions without deleting)

```bash
python .agent/skills/skill-forge/scripts/ttl_watcher.py --dry-run
```

### Custom TTL (e.g., 14 days instead of 30)

```bash
python .agent/skills/skill-forge/scripts/ttl_watcher.py --ttl-days 14
```

### Combine Flags

```bash
python .agent/skills/skill-forge/scripts/ttl_watcher.py --dry-run --ttl-days 7
```

### Cron (Monthly Cleanup)

Add to your crontab (`crontab -e`):

```bash
0 9 1 * * cd /path/to/project && python .agent/skills/skill-forge/scripts/ttl_watcher.py >> .agent/skills/.ttl_log.txt 2>&1
```

This runs at 9:00 AM on the 1st of each month and logs output to `.ttl_log.txt`.

## Protected Skills

Protected skills are **never deleted**, regardless of their last-use timestamp.

The watcher checks for a protected list in this order:

1. **File-based**: `.agent/skills/.protected` — one skill name per line
2. **Hardcoded fallback**: If the file doesn't exist, these 14 core skills are protected:

```
task-planner
debugging-master
code-synthesizer
architecture-analyst
system-auditor
test-generator
security-auditor
performance-optimizer
refactoring-specialist
research-engine
dependency-analyzer
documentation-writer
frontend-design
skill-forge
```

### Adding a Skill to the Protected List

Create or edit `.agent/skills/.protected`:

```bash
echo "my-important-skill" >> .agent/skills/.protected
```

Each line is one skill name (no `@` prefix needed).

## Output Examples

```
Deleted: @unused-tool (unused 45 days)
Skipped: @task-planner (protected)
No custom skills to expire.

skill-forge TTL check: 1 deleted, 14 retained
```

Dry run:
```
Would delete: @unused-tool (unused 45 days)

[DRY RUN] skill-forge TTL check: 1 deleted, 14 retained
```
