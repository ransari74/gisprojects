"""Static invariants of the Alembic revision files.

No database needed: these read the migration sources directly, so they catch a
branched history or an empty downgrade in CI even where Postgres is not
available.
"""

from __future__ import annotations

import re
from pathlib import Path

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _revisions() -> dict[str, dict]:
    revisions: dict[str, dict] = {}
    for path in VERSIONS_DIR.glob("*.py"):
        source = path.read_text()
        rev = re.search(r'^revision: str = "([^"]+)"', source, re.M)
        down = re.search(r'^down_revision: str \| None = (?:"([^"]+)"|None)', source, re.M)
        assert rev, f"{path.name} has no revision id"
        assert down, f"{path.name} has no down_revision"
        revisions[rev.group(1)] = {
            "down": down.group(1),
            "path": path,
            "source": source,
        }
    return revisions


def test_migration_chain_is_linear_with_one_head():
    """A branched history would make `upgrade head` ambiguous."""
    revisions = _revisions()
    assert revisions, "no migrations found"

    downs = [meta["down"] for meta in revisions.values()]
    bases = [rev for rev, meta in revisions.items() if meta["down"] is None]
    heads = [rev for rev in revisions if rev not in downs]

    assert len(bases) == 1, f"expected exactly one base revision, found {bases}"
    assert len(heads) == 1, f"expected exactly one head revision, found {heads}"
    # No revision may be the parent of two others.
    assert len(downs) == len(set(downs)), "the revision history branches"


def test_every_migration_has_a_real_downgrade():
    """A downgrade that silently passes is worse than none -- it looks reversible."""
    for rev, meta in _revisions().items():
        body = meta["source"].split("def downgrade() -> None:", 1)
        assert len(body) == 2, f"revision {rev} has no downgrade()"
        statements = [
            line.strip()
            for line in body[1].splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        assert statements and statements != ["pass"], (
            f"revision {rev} ({meta['path'].name}) has an empty downgrade"
        )


def test_no_duplicate_revision_ids():
    ids = []
    for path in VERSIONS_DIR.glob("*.py"):
        match = re.search(r'^revision: str = "([^"]+)"', path.read_text(), re.M)
        if match:
            ids.append(match.group(1))
    assert len(ids) == len(set(ids)), "two migrations share a revision id"


