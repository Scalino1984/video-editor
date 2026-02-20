### Coding-Agent Report

**PR:** #1 – FastAPI backend audit: canonical API registry with 110 endpoints, models, and issues
**Status:** MERGED
**URL:** https://github.com/Scalino1984/video-editor/pull/1
**Author:** app/copilot-swe-agent
**Base → Head:** master → copilot/full-backend-inventory-fastapi
**Created/Updated:** 2026-02-19T11:15:06Z / 2026-02-19T14:43:09Z
**Files/Lines:** 2 files, +353/-1
**Assignees:** Scalino1984, Copilot

### Summary

Full inventory of the FastAPI backend — endpoints, schemas, dependencies, middleware, security, and cross-file references — materialized as `.intern/api-registry.json`.

### Registry contents

- **110 endpoints** across 4 routers (`/api`, `/api/ai`, `/api/library|render|media`, `/api/editor`)
- **All Pydantic models** — centralized (`models.py`) and scattered (10+ models defined inline in route files)
- **Dependencies** — BackgroundTasks, undo system, segment CRUD helpers, chat DB
- **Middleware/lifespan** — CORS config, startup/shutdown hooks, static mounts

### Issues identified

| Issue | Type |
|-------|------|
| `GET /api/jobs/{job_id}/download-zip` registered twice (line 267 + 602) | Bug |
| 6 unused models: `SegmentInfo`, `WordInfoSchema`, `MediaInfo`, `MediaTagsUpdate`, `LyricsTemplateInfo`, `RetranscribeSegment` | Dead code |
| `RetranscribeSegment` imported in `routes.py` but never referenced | Dead import |
| ~40 endpoints return ad-hoc dicts without `response_model` | OpenAPI gaps |
| `update_media_tags` accepts raw `dict` instead of existing `MediaTagsUpdate` | Schema mismatch |
| `POST /api/ai/segments/{job_id}/merge` is a segment mutation living in AI routes | Misplacement |
| Pydantic models scattered across `ai/routes.py`, `db/routes.py` | Organization |
| No auth, open CORS (`*` + credentials), no rate limiting | Security (by-design for local use) |

### `.gitignore` change

```
-.intern/
+.intern/*
+!.intern/api-registry.json
```

Allows the registry to be committed while keeping other `.intern/` development docs ignored.

<!-- START COPILOT CODING AGENT TIPS -->
---

💡 You can make Copilot smarter by setting up custom instructions, customizing its development environment and configuring Model Context Protocol (MCP) servers. Learn more [Copilot coding agent tips](https://gh.io/copilot-coding-agent-tips) in the docs.

### Changed files

| File | Add | Del |
|---|---:|---:|
| .gitignore | 2 | 1 |
| .intern/api-registry.json | 351 | 0 |

### Commits

-  
-  

### Checks

_No checks reported._

