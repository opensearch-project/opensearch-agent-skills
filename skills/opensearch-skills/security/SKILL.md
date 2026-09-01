---
name: security
description: >
  Design, troubleshoot, and validate least-privilege OpenSearch access. Use
  when a user is debugging 403 or MISSING_PRIVILEGES errors, replacing broad
  roles, reviewing Security plugin permissions, or validating that forbidden
  operations remain denied.
compatibility: Requires Python 3.11+ and a test identity on an OpenSearch cluster.
metadata:
  author: opensearch-project
  version: "1.0"
---

# Security

Category skill for evidence-backed OpenSearch access-control workflows.

## Skills

| Skill | Description |
|---|---|
| [permission-compiler](permission-compiler/SKILL.md) | Compile representative workflows into observed-minimum Security role candidates |

## When to use

| User intent | Skill |
|---|---|
| Debug a 403 or `MISSING_PRIVILEGES` response | [permission-compiler](permission-compiler/SKILL.md) |
| Replace `all_access` with a narrower role | [permission-compiler](permission-compiler/SKILL.md) |
| Prove required actions work while destructive actions stay denied | [permission-compiler](permission-compiler/SKILL.md) |
