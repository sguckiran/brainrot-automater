---
name: create-viral-video-concepts
description: Create distinct short-form AI video concepts and Flow-ready prompts. Use when generating, revising, queuing, or reviewing social-video ideas where every post must have a visibly different premise, setting, action, twist, visual style, and camera treatment from recent posts.
---

# Create Viral Video Concepts

Generate one concept at a time. Read [references/concept-rules.md](references/concept-rules.md) before producing batches or editing the automation's concept catalog.

## Workflow

1. Inspect recent job topics when available:
   `python -m social_video_factory.cli list-jobs`
2. Avoid reusing the same subject-action-setting combination.
3. Choose one item from each dimension:
   subject, setting, action, twist, visual treatment, camera language.
4. Make the first second visually understandable without dialogue.
5. Keep the concept suitable for an 8-second, vertical, looping clip.
6. Return a concise concept line, followed by an optional Flow-ready prompt.

## Output

Use this shape:

```text
Concept: <one sentence with subject, setting, action, and twist>
Visual treatment: <style, lighting, palette>
Camera: <movement and framing>
Loop: <how the final frame reconnects to the opening>
```

Never produce a near-duplicate by merely changing colors, props, or location names.
