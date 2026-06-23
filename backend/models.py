"""
models.py — Aacharya AI Database Schema (Decentralized Multi-Center)
======================================================================
SQLModel definitions replacing the old flat, globally-unique inventory
table with a hub-and-spoke ASHA center network. Each medicine can now
exist independently across multiple centers, keyed by (center_id, item_id).

Tables:
    Worker          — ASHA worker accounts, scoped to a home center.
    AshaCenter      — The 5-node regional cluster (1 hub + 4 sub-centres).
    CenterInventory — Per-center stock ledger (composite-unique, not global).
    Alert           — Broadcast alerts, location-prefixed by the caller.
"""

import enum
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlmodel import SQLModel, Field, create_engine, Session, UniqueConstraint

# --------------------------------------------------------------------------
# Engine setup
# --------------------------------------------------------------------------

ROOT_DIR = Path(__file__).parent
DATABASE_URL = f"sqlite:///{ROOT_DIR}/health_chatbot.db"

engine = create_engine(DATABASE_URL, echo=False)


# --------------------------------------------------------------------------
# Center type constraint
# --------------------------------------------------------------------------
# SQLite has no native ENUM type. Using a str Enum here (rather than
# typing.Literal) so SQLModel/SQLAlchemy can map it to a real CHECK
# constraint-backed column, enforced at both the Python and DB layers —
# not just validated at the Pydantic boundary.
class CenterType(str, enum.Enum):
    DISTRICT_HUB = "district_hub"
    VILLAGE_SUB_CENTRE = "village_sub_centre"


# --------------------------------------------------------------------------
# Worker
# --------------------------------------------------------------------------

class Worker(SQLModel, table=True):
    """
    ASHA worker account. `center_id` scopes which center's inventory and
    alerts this worker is authorized to manage. Optional at the schema
    level (existing/legacy accounts may be unassigned), but the API layer
    should treat an unassigned worker as having no inventory-write scope.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    hashed_password: str
    center_id: Optional[str] = Field(default=None, foreign_key="ashacenter.id", index=True)


# --------------------------------------------------------------------------
# AshaCenter
# --------------------------------------------------------------------------

class AshaCenter(SQLModel, table=True):
    """
    A single node in the regional cluster — either the district hub (PHC)
    or one of the surrounding village sub-centres. `id` is a human-readable
    string key (e.g. "SC_CKB_NANDI") rather than an autoincrement int, so
    it can be referenced directly in the static distance matrix and in
    frontend dropdown values without an extra lookup join.
    """
    id: str = Field(primary_key=True)
    name: str
    center_type: CenterType = Field(index=True)


# --------------------------------------------------------------------------
# CenterInventory
# --------------------------------------------------------------------------

class CenterInventory(SQLModel, table=True):
    """
    Per-center stock ledger. Replaces the old globally-unique Inventory
    table. The same item_id (e.g. "MED_PARA_500", matching knowledge_base.json
    concept IDs) can have independent rows per center_id, each with its own
    quantity. Uniqueness is enforced on (center_id, item_id) together —
    NOT on item_id alone — so stock can't fragment into duplicate rows for
    the same item at the same center.
    """
    __table_args__ = (
        UniqueConstraint("center_id", "item_id", name="uq_center_item"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    center_id: str = Field(foreign_key="ashacenter.id", index=True)
    item_id: str = Field(index=True)
    item_name: str
    quantity: int = Field(default=0)


# --------------------------------------------------------------------------
# Alert
# --------------------------------------------------------------------------

class Alert(SQLModel, table=True):
    """
    Broadcast alert. `message` is expected to already carry the location
    prefix (e.g. "Nandi Hills: Dengue Alert") composed at the API layer
    from the broadcasting worker's center_id — kept as a single text field
    here rather than a separate center_id FK, since alerts are append-only
    broadcast records, not queryable-by-center in the current design.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    message: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --------------------------------------------------------------------------
# Table creation & session dependency
# --------------------------------------------------------------------------

def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
