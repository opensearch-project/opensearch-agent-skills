import re
from typing import Any, Dict

class Redactor:
    """Redacts secrets and sensitive fields from raw telemetry."""
    
    PATTERNS = [
        (re.compile(r'(?i)(password|secret|token|api_key|auth)["\':\s=]+([a-zA-Z0-9_\-\.\+]+)'), r'\1="[REDACTED]"'),
        (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b'), '[REDACTED]'), # email
    ]

    # Matches dict keys whose *value* should be redacted outright, even when the
    # key name itself doesn't appear inside the value string (e.g. a structured
    # {"api_key": "sk-live-..."} field, as opposed to free text like 'api_key=sk-live-...').
    SENSITIVE_KEY_PATTERN = re.compile(r'(?i)^(password|secret|token|api_key|auth)$')

    @classmethod
    def redact_string(cls, text: str) -> str:
        for pattern, replacement in cls.PATTERNS:
            # Replace the match (or captured secret group, if any) with [REDACTED]
            text = pattern.sub(replacement, text)
        return text

    @classmethod
    def redact_value(cls, value: Any) -> Any:
        if isinstance(value, str):
            return cls.redact_string(value)
        if isinstance(value, dict):
            return cls.redact_dict(value)
        if isinstance(value, list):
            return [cls.redact_value(i) for i in value]
        return value

    @classmethod
    def redact_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        result = {}
        for k, v in data.items():
            if isinstance(v, str) and cls.SENSITIVE_KEY_PATTERN.match(k):
                result[k] = '"[REDACTED]"'
            else:
                result[k] = cls.redact_value(v)
        return result
