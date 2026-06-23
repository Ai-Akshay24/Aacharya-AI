"""
seed_db.py — Aacharya AI Database Seeder
==========================================
Populates the 5-node Chikkaballapur regional cluster: AshaCenter records,
one ASHA worker per center, and tiered initial stock for all 8 medicines
in knowledge_base.json. Center IDs are hardcoded to match
inventory_routing.py's CENTER_IDS exactly — the distance matrix is keyed
on these strings, so a mismatch here breaks routing silently.

Run: python seed_db.py
Safe to re-run: existing rows are skipped (checked before insert),
so this will not duplicate or reset live data.
"""

import logging
import random

from sqlmodel import Session, select

from models import (
    Worker,
    AshaCenter,
    CenterInventory,
    CenterType,
    create_db_and_tables,
    engine,
)
from auth import get_password_hash

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Center IDs — must match inventory_routing.py CENTER_IDS exactly.
# --------------------------------------------------------------------------
HUB      = "PHC_CKB_HUB"
SC_MANCHE = "SC_CKB_MANCHE"
SC_NAGA   = "SC_CKB_NAGA"
SC_DIBBUR = "SC_CKB_DIBBUR"
SC_MELUR  = "SC_CKB_MELUR"

CENTERS = [
    {"id": HUB,       "name": "Chikkaballapur District PHC", "center_type": CenterType.DISTRICT_HUB},
    {"id": SC_MANCHE, "name": "Manchenahalli Sub-Centre",    "center_type": CenterType.VILLAGE_SUB_CENTRE},
    {"id": SC_NAGA,   "name": "Nagamangala Sub-Centre",      "center_type": CenterType.VILLAGE_SUB_CENTRE},
    {"id": SC_DIBBUR, "name": "Dibburahalli Sub-Centre",     "center_type": CenterType.VILLAGE_SUB_CENTRE},
    {"id": SC_MELUR,  "name": "Melur Sub-Centre",            "center_type": CenterType.VILLAGE_SUB_CENTRE},
]

# Default password for all seed accounts — change before any non-local deployment.
DEFAULT_SEED_PASSWORD = "securepass"

WORKERS = [
    {"username": "hubworker",    "center_id": HUB},
    {"username": "mancheworker", "center_id": SC_MANCHE},
    {"username": "nagaworker",   "center_id": SC_NAGA},
    {"username": "dibburworker", "center_id": SC_DIBBUR},
    {"username": "melurworker",  "center_id": SC_MELUR},
]

# --------------------------------------------------------------------------
# Medicine catalogue — item_id keys must match knowledge_base.json exactly.
# --------------------------------------------------------------------------
MEDICINES = [
    {"item_id": "MED_PARA_500", "item_name": "Paracetamol 500mg"},
    {"item_id": "MED_DICY_10",  "item_name": "Dicyclomine 10mg"},
    {"item_id": "MED_ORS_001",  "item_name": "ORS Packet"},
    {"item_id": "MED_AMOX_250", "item_name": "Amoxicillin 250mg"},
    {"item_id": "MED_IRON_FA",  "item_name": "Iron & Folic Acid Tablet"},
    {"item_id": "MED_CETI_10",  "item_name": "Cetirizine 10mg"},
    {"item_id": "MED_ACID_001", "item_name": "Antacid Tablet"},
    {"item_id": "VAC_BCG_001",  "item_name": "BCG Vaccine"},
]

# Deliberate exceptions to the random baseline — these specific
# (center, item) pairs exercise the routing and concurrency logic:
#   • SC_MANCHE Paracetamol = 0  → forces fallback routing away from Manchenahalli.
#   • SC_MELUR  Paracetamol = 1  → single unit; tests atomic race-condition path.
#   • Hub always heavily stocked → district-level safety net for all items.
STOCK_OVERRIDES = {
    (HUB,       "MED_PARA_500"): 240,
    (SC_MANCHE, "MED_PARA_500"): 0,
    (SC_MELUR,  "MED_PARA_500"): 1,
    (HUB,       "VAC_BCG_001"):  50,
    (SC_NAGA,   "VAC_BCG_001"):  0,
    (SC_DIBBUR, "VAC_BCG_001"):  0,
}

# Random stock range for all (center, item) pairs not in STOCK_OVERRIDES.
RANDOM_STOCK_MIN = 10
RANDOM_STOCK_MAX = 100


def _stock_quantity(center_id: str, item_id: str) -> int:
    return STOCK_OVERRIDES.get(
        (center_id, item_id),
        random.randint(RANDOM_STOCK_MIN, RANDOM_STOCK_MAX),
    )


# --------------------------------------------------------------------------
# Seeder functions — each is idempotent (skip-if-exists).
# --------------------------------------------------------------------------

def seed_centers(session: Session) -> None:
    for c in CENTERS:
        if session.get(AshaCenter, c["id"]):
            logger.info(f"  AshaCenter '{c['id']}' already exists, skipping.")
            continue
        session.add(AshaCenter(**c))
        logger.info(f"  Seeded AshaCenter: {c['id']} ({c['name']})")
    session.commit()


def seed_workers(session: Session) -> None:
    for w in WORKERS:
        existing = session.exec(
            select(Worker).where(Worker.username == w["username"])
        ).first()
        if existing:
            logger.info(f"  Worker '{w['username']}' already exists, skipping.")
            continue
        session.add(Worker(
            username=w["username"],
            hashed_password=get_password_hash(DEFAULT_SEED_PASSWORD),
            center_id=w["center_id"],
        ))
        logger.info(f"  Seeded Worker: {w['username']} -> {w['center_id']}")
    session.commit()


def seed_inventory(session: Session) -> None:
    for center in CENTERS:
        for med in MEDICINES:
            existing = session.exec(
                select(CenterInventory).where(
                    CenterInventory.center_id == center["id"],
                    CenterInventory.item_id   == med["item_id"],
                )
            ).first()
            if existing:
                logger.info(
                    f"  Inventory row {med['item_id']}@{center['id']} "
                    f"already exists ({existing.quantity} units), skipping."
                )
                continue
            qty = _stock_quantity(center["id"], med["item_id"])
            session.add(CenterInventory(
                center_id=center["id"],
                item_id=med["item_id"],
                item_name=med["item_name"],
                quantity=qty,
            ))
            logger.info(
                f"  Seeded inventory: {med['item_id']:15s} @ "
                f"{center['id']:15s} = {qty:>4d} units"
            )
    session.commit()


def run_seed() -> None:
    logger.info("Initializing database tables...")
    create_db_and_tables()

    with Session(engine) as session:
        logger.info("--- Seeding ASHA centers ---")
        seed_centers(session)

        logger.info("--- Seeding ASHA workers ---")
        seed_workers(session)

        logger.info("--- Seeding center inventory (8 items x 5 centers = 40 rows) ---")
        seed_inventory(session)

    logger.info("Seeding complete.")
    logger.info(
        f"All seed accounts use password: '{DEFAULT_SEED_PASSWORD}' "
        f"— change this before any non-local deployment."
    )


if __name__ == "__main__":
    run_seed()