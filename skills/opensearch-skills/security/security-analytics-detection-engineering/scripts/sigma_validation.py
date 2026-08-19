"""Deterministic validation for the supported Sigma subset.

This module never talks to the network and never invents field mappings.
Callers supply the resolvable field universe (index mapping paths, explicit
Security Analytics aliases, explicitly declared synthetic fixture fields);
validation reports exactly which referenced fields resolve and which do not.

A rule cannot become SCHEMA_VALID while unresolved fields remain.

PyYAML (already a repository dev dependency) is imported lazily so the
Slice 1 commands keep working without it.
"""

import re

SUPPORTED_MODIFIERS = frozenset(
    {"contains", "all", "startswith", "endswith", "base64", "base64offset", "re"}
)
SUPPORTED_LEVELS = frozenset({"informational", "low", "medium", "high", "critical"})
REQUIRED_TOP_LEVEL = ("title", "logsource", "detection")
CONDITION_KEYWORDS = frozenset({"and", "or", "not", "of", "them", "all", "any"})
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
PLACEHOLDER_RE = re.compile(r"%[A-Za-z0-9_.]+%")

# High-precision secret patterns are blocking; generic assignments are warnings
# because detection content legitimately matches on words like "password".
SECRET_PATTERNS_BLOCKING = (
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bghp_[A-Za-z0-9]{36}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
)
SECRET_PATTERN_WARNING = re.compile(
    r"(?i)\b(password|passwd|api[_-]?key|secret|token)\s*[:=]\s*\S{12,}"
)


def load_sigma(sigma_text):
    """Parse Sigma YAML safely. Returns (doc, error_message)."""
    try:
        import yaml
    except ImportError:
        return None, (
            "PyYAML is required for rule validation. Run the CLI via "
            "`uv run scripts/security_analytics.py` (PyYAML is declared as a "
            "PEP 723 script dependency) or `pip install pyyaml`."
        )
    try:
        docs = list(yaml.safe_load_all(sigma_text))
    except yaml.YAMLError as e:
        return None, f"YAML parse error: {e}"
    if len(docs) != 1:
        return None, f"Expected exactly one YAML document, found {len(docs)}."
    doc = docs[0]
    if not isinstance(doc, dict):
        return None, "Sigma rule must be a YAML mapping at the top level."
    return doc, None


def _walk_values(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk_values(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            yield from _walk_values(v)
    elif node is not None:
        yield str(node)


def _selection_fields(selection):
    """Field names referenced by one selection block, with their modifiers."""
    refs = []
    if isinstance(selection, dict):
        items = selection.items()
    elif isinstance(selection, list):
        items = []
        for entry in selection:
            if isinstance(entry, dict):
                items.extend(entry.items())
            else:
                refs.append(("<keyword>", []))  # keyword list selection: no field
        items = tuple(items)
    else:
        return [("<keyword>", [])]
    for key, _ in items:
        parts = str(key).split("|")
        refs.append((parts[0], [m for m in parts[1:] if m]))
    return refs


def _condition_tokens(condition):
    return [t for t in re.split(r"[\s()]+", condition) if t]


def logsource_compatible(logsource, log_type):
    if not isinstance(logsource, dict):
        return False
    values = {
        str(logsource.get(k, "")).lower()
        for k in ("product", "category", "service")
    }
    return log_type.lower() in values


def validate_sigma(sigma_text, log_type, resolvable_fields, extra_fields=(),
                   existing_titles=(), existing_rule_id=None):
    """Validate one Sigma rule against the supported subset.

    resolvable_fields: iterable of field paths confirmed from the index mapping
        or explicit Security Analytics alias resolution.
    extra_fields: explicitly declared synthetic fixture fields.
    existing_titles: titles of custom rules already on the cluster (duplicate
        identity check); empty when offline.
    existing_rule_id: rule id already recorded for this run, if any.

    Returns a structured dict; `valid` is True only with zero blocking errors
    and zero unresolved fields.
    """
    errors = []
    warnings = []
    constructs = set()
    referenced = []
    resolved = []
    unresolved = []

    doc, parse_error = load_sigma(sigma_text)
    if parse_error:
        return _result(False, [parse_error], warnings, constructs,
                       referenced, resolved, unresolved,
                       next_action="Fix the YAML so it parses as a single mapping.")

    for key in REQUIRED_TOP_LEVEL:
        if key not in doc:
            errors.append(f"Missing required top-level key: {key!r}.")
    if "correlation" in doc or doc.get("action") == "correlation":
        errors.append("Correlation rules are not supported by this skill slice.")
    if errors:
        return _result(False, errors, warnings, constructs, referenced, resolved,
                       unresolved,
                       next_action="Add the missing required Sigma keys.")

    if not str(doc.get("title") or "").strip():
        errors.append("Rule title must be nonempty.")

    rule_id = doc.get("id")
    if rule_id is not None and not UUID_RE.match(str(rule_id)):
        errors.append(f"Rule id {rule_id!r} is not a well-formed UUID.")

    level = doc.get("level")
    if level is not None and str(level).lower() not in SUPPORTED_LEVELS:
        errors.append(
            f"Unsupported level {level!r}; supported: {sorted(SUPPORTED_LEVELS)}."
        )

    if not logsource_compatible(doc.get("logsource"), log_type):
        errors.append(
            f"logsource {doc.get('logsource')!r} does not match detector log type "
            f"{log_type!r} (product, category, or service must equal the log type)."
        )

    detection = doc.get("detection")
    if not isinstance(detection, dict):
        errors.append("detection must be a mapping of selections plus a condition.")
        return _result(False, errors, warnings, constructs, referenced, resolved,
                       unresolved, next_action="Rewrite the detection block.")

    condition = detection.get("condition")
    if not isinstance(condition, str) or not condition.strip():
        errors.append("detection.condition must be a nonempty string.")
        condition = ""
    if "|" in condition:
        errors.append(
            "Aggregation expressions in condition (count, near, pipe syntax) are "
            "not supported by this skill slice."
        )

    selections = {k: v for k, v in detection.items() if k != "condition"}
    if not selections:
        errors.append("detection defines no selections.")

    tokens = _condition_tokens(condition)
    numeric = re.compile(r"^\d+$")
    for token in tokens:
        low = token.lower()
        if low in CONDITION_KEYWORDS or numeric.match(token):
            continue
        if token in selections:
            continue
        if "*" in token:
            pattern = re.compile("^" + re.escape(token).replace(r"\*", ".*") + "$")
            if any(pattern.match(name) for name in selections):
                continue
        errors.append(f"condition references undefined selection {token!r}.")

    field_universe = set(resolvable_fields) | set(extra_fields)
    for name, selection in selections.items():
        for field, modifiers in _selection_fields(selection):
            if field == "<keyword>":
                constructs.add("keyword-selection")
                continue
            if field not in referenced:
                referenced.append(field)
            for mod in modifiers:
                if mod in SUPPORTED_MODIFIERS:
                    constructs.add(f"modifier:{mod}")
                else:
                    errors.append(
                        f"Unsupported field modifier {mod!r} on {field!r} in "
                        f"selection {name!r}; supported: {sorted(SUPPORTED_MODIFIERS)}."
                    )
    for field in referenced:
        (resolved if field in field_universe else unresolved).append(field)
    if unresolved:
        errors.append(
            "Unresolved fields (not in the index mapping, Security Analytics "
            f"aliases, or declared fixture fields): {unresolved}."
        )

    for value in _walk_values(doc):
        if PLACEHOLDER_RE.search(value):
            errors.append(
                f"Placeholder expansion {PLACEHOLDER_RE.search(value).group()!r} "
                "cannot be resolved deterministically and is not supported."
            )
        for label, pattern in SECRET_PATTERNS_BLOCKING:
            if pattern.search(value):
                errors.append(f"Rule contains an embedded secret ({label}).")
        if SECRET_PATTERN_WARNING.search(value):
            warnings.append(
                "A value looks like a credential assignment; confirm it is "
                "detection content, not an embedded secret."
            )

    title = str(doc.get("title") or "").strip()
    if title and title in set(existing_titles):
        errors.append(
            f"A custom rule titled {title!r} already exists on the cluster; "
            "duplicate rule identities are refused. Retitle or delete the old rule."
        )
    if existing_rule_id:
        errors.append(
            f"This run already created rule {existing_rule_id}; refusing a "
            "silently colliding second identity."
        )

    valid = not errors
    if valid:
        next_action = "Rule is SCHEMA_VALID. Submit with create-rule --apply."
    elif unresolved:
        next_action = ("Re-run inspect and rewrite the rule using only resolved "
                       "fields, or declare synthetic fixture fields explicitly.")
    else:
        next_action = "Fix the blocking errors listed and re-run validate-rule."
    return _result(valid, errors, warnings, constructs, referenced, resolved,
                   unresolved, next_action)


def _result(valid, errors, warnings, constructs, referenced, resolved,
            unresolved, next_action):
    return {
        "valid": valid,
        "evidence_state": "SCHEMA_VALID" if valid else "DRAFT",
        "supported_constructs_used": sorted(constructs),
        "referenced_fields": list(referenced),
        "resolved_fields": list(resolved),
        "unresolved_fields": list(unresolved),
        "warnings": list(warnings),
        "blocking_errors": list(errors),
        "next_action": next_action,
    }
