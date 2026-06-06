"""Sidecar SQLite settlement-aware claim search index.

Folded from chimera-graphsource into chimera-memory for the public package.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from chimera_memory_types.knowledge import Claim


class ClaimIndex:
    def __init__(self, path: str | Path, *, force_like: bool = False) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path))
        self.connection.row_factory = sqlite3.Row
        self.fts_enabled = False if force_like else self._probe_fts5()
        self._init_schema()

    def _probe_fts5(self) -> bool:
        try:
            self.connection.execute("CREATE VIRTUAL TABLE temp._fts_probe USING fts5(value)")
            self.connection.execute("DROP TABLE temp._fts_probe")
            return True
        except sqlite3.Error:
            return False

    def _init_schema(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS claims (
                claim_id TEXT PRIMARY KEY,
                claim_type TEXT NOT NULL,
                claim_status TEXT NOT NULL,
                entity_id TEXT,
                polarity TEXT,
                settled INTEGER NOT NULL,
                wealth REAL NOT NULL,
                text TEXT NOT NULL,
                claim_json TEXT NOT NULL
            )
            """
        )
        if self.fts_enabled:
            self.connection.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(claim_id UNINDEXED, text)"
            )
        self.connection.commit()

    def index(self, claim: Claim) -> None:
        text = _claim_text(claim)
        settled = _is_settled(claim)
        wealth = _wealth(claim)
        entity_id = _metadata_string(claim, "entity_id")
        polarity = _metadata_string(claim, "polarity")
        payload = (
            claim.claim_id,
            claim.claim_type.value,
            claim.claim_status.value,
            entity_id,
            polarity,
            int(settled),
            wealth,
            text,
            json.dumps(claim.model_dump(mode="json"), sort_keys=True),
        )
        self.connection.execute(
            """
            INSERT INTO claims (
                claim_id, claim_type, claim_status, entity_id, polarity,
                settled, wealth, text, claim_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(claim_id) DO UPDATE SET
                claim_type=excluded.claim_type,
                claim_status=excluded.claim_status,
                entity_id=excluded.entity_id,
                polarity=excluded.polarity,
                settled=excluded.settled,
                wealth=excluded.wealth,
                text=excluded.text,
                claim_json=excluded.claim_json
            """,
            payload,
        )
        if self.fts_enabled:
            self.connection.execute("DELETE FROM claims_fts WHERE claim_id = ?", (claim.claim_id,))
            self.connection.execute(
                "INSERT INTO claims_fts (claim_id, text) VALUES (?, ?)",
                (claim.claim_id, text),
            )
        self.connection.commit()

    def search(
        self,
        query: str,
        *,
        settled_only: bool = False,
        min_wealth: float | None = None,
        claim_type: str | None = None,
    ) -> list[Claim]:
        where: list[str] = []
        params: list[Any] = []
        if settled_only:
            where.append("claims.settled = 1")
        if min_wealth is not None:
            where.append("claims.wealth >= ?")
            params.append(float(min_wealth))
        if claim_type is not None:
            where.append("claims.claim_type = ?")
            params.append(str(claim_type))

        if self.fts_enabled:
            sql = "SELECT claims.claim_json FROM claims JOIN claims_fts USING (claim_id)"
            where.append("claims_fts.text MATCH ?")
            params.append(query)
        else:
            sql = "SELECT claims.claim_json FROM claims"
            where.append("LOWER(claims.text) LIKE ?")
            params.append(f"%{query.lower()}%")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY claims.wealth DESC, claims.claim_id ASC"
        rows = self.connection.execute(sql, params).fetchall()
        return [Claim.model_validate(json.loads(row["claim_json"])) for row in rows]

    def find_contradictions(self, claim_id: str) -> list[Claim]:
        row = self.connection.execute(
            "SELECT entity_id, polarity FROM claims WHERE claim_id = ? AND settled = 1",
            (claim_id,),
        ).fetchone()
        if row is None or row["entity_id"] is None or row["polarity"] is None:
            return []
        opposite = _opposite_polarity(row["polarity"])
        if opposite is None:
            return []
        rows = self.connection.execute(
            """
            SELECT claim_json FROM claims
            WHERE settled = 1
              AND claim_id != ?
              AND entity_id = ?
              AND polarity = ?
            ORDER BY wealth DESC, claim_id ASC
            """,
            (claim_id, row["entity_id"], opposite),
        ).fetchall()
        return [Claim.model_validate(json.loads(result["claim_json"])) for result in rows]


def _claim_text(claim: Claim) -> str:
    parts = [
        claim.claim_id,
        claim.claim_type.value,
        claim.claim_status.value,
        claim.title,
        claim.summary,
        claim.formal_statement or "",
        str(claim.metadata.get("entity_id", "")),
        str(claim.metadata.get("polarity", "")),
    ]
    if claim.settlement is not None:
        parts.extend(
            [
                claim.settlement.status.value,
                str(claim.settlement.proper_score or ""),
                str(claim.settlement.wealth.wealth),
            ]
        )
    return " ".join(part for part in parts if part)


def _is_settled(claim: Claim) -> bool:
    return bool(claim.settlement is not None and claim.settlement.events)


def _wealth(claim: Claim) -> float:
    if claim.settlement is None:
        return 0.0
    return claim.settlement.wealth.wealth


def _metadata_string(claim: Claim, key: str) -> str | None:
    value = claim.metadata.get(key)
    if value is None:
        return None
    return str(value)


def _opposite_polarity(polarity: str) -> str | None:
    pairs = {
        "positive": "negative",
        "negative": "positive",
        "true": "false",
        "false": "true",
        "support": "oppose",
        "oppose": "support",
    }
    return pairs.get(polarity.lower())
