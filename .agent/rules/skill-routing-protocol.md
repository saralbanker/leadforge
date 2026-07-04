---
name: skill-routing-protocol
description: Routing protocol for deciding which skill to activate. Includes fallback to skill-forge for unknown domains.
---

# Skill Routing Protocol

When a user request arrives, follow this routing sequence in order:

1. **Explicit activation**: If the user wrote `@skill-name`, activate that skill directly. No routing needed.

2. **Semantic match**: Scan installed skill descriptions for the closest match to the request. If a match is found with high confidence, activate it.

3. **Multi-step planning**: For requests with 3+ distinct steps, activate `@task-planner` first to decompose before activating specialist skills.

4. **Unknown domain fallback**: If no existing skill covers the task AND the task is complex or will likely recur → activate `@skill-forge` to create a new skill, then immediately activate the new skill to complete the original request.

5. **Concurrency limit**: Never load more than 2 skills simultaneously. Context window is a shared resource.

6. **Context handoff**: Pass only `context_delta` between skills — new information only, not full conversation history.

7. **Completion protocol**: After a skill completes its task, output a one-sentence summary of what was done before returning control to the user.

## Routing Decision Tree

```
[REQUEST]
  → explicit @skill-name? → YES → activate directly
                          → NO  → semantic match found? → YES → activate matched skill
                                                         → NO  → complex/recurring? → YES → @skill-forge
                                                                                    → NO  → solve free-form
```
