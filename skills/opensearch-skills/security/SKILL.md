---
name: security
description: >
  Security engineering with OpenSearch. Use this skill when the user wants to
  work with OpenSearch Security Analytics: create or test Sigma detection
  rules, set up detectors, verify findings, or debug detections. Activate even
  if the user says SIEM, detection rule, threat detection, Sysmon, or
  detection engineering without mentioning OpenSearch.
compatibility: Requires a running OpenSearch cluster with the Security Analytics plugin.
metadata:
  author: StressTestor
  version: "1.0"
---

# Security

Category skill for security engineering with OpenSearch.

## Skills

| Skill | Description |
|---|---|
| [security-analytics-detection-engineering](security-analytics-detection-engineering/SKILL.md) | Create custom Sigma rules and detectors, then verify they fire with positive/negative fixture evidence |

## When to Use

| User Intent | Skill |
|---|---|
| Write, deploy, or test a Sigma rule; create a detector; verify findings | [security-analytics-detection-engineering](security-analytics-detection-engineering/SKILL.md) |
