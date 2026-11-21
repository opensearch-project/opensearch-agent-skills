"""Make the unclosed skill's scripts importable by its tests.

The skill ships as plain files copied into this repository, so its modules are
imported as scripts rather than as a package -- the same reason the other test
files here insert skills/opensearch-skills/scripts onto sys.path themselves.
Done once here instead of twelve times there; the test files stay byte-identical
to the skill's development repository, where the same suite runs against the
same layout.
"""

import sys
from pathlib import Path

_UNCLOSED_SCRIPTS = (Path(__file__).resolve().parent.parent / "skills" / "opensearch-skills"
                     / "observability" / "unclosed" / "scripts")
sys.path.insert(0, str(_UNCLOSED_SCRIPTS))
