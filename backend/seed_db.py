"""
seed_db.py — Aacharya AI Database Seeder
===========================================
Populates the 5-node Chikkaballapur regional cluster: AshaCenter records,
one ASHA worker per center, and tiered initial stock for MED_PARA_500 and
VAC_BCG_001. Center IDs here are hardcoded to match inventory_routing.py
exactly — these are not arbitrary; the distance matrix is keyed on these
exact strings, so a typo here silently breaks routing rather than failing
loudly.

Run directly: python seed_db.py
Safe to re-run: existing rows are left untouched (checked by primary key /
username before insert), so this will not duplicate or reset data on a
second run.
"""

import logging

from sqlmodel import Session, select

from models import (
    Worker,
    AshaCenter,
    CenterInventory,
    CenterType,
    create_db_and_tables,
    engine,
)
from auth import get_password_hash  # reuses the same bcrypt hashing as the live server

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Center IDs — MUST match inventory_routing.py's CENTER_IDS exactly.
# --------------------------------------------------------------------------
HUB = "PHC_CKB_HUB"
SC_MANCHE = "SC_CKB_MANCHE"
SC_NAGA = "SC_CKB_NAGA"
SC_DIBBUR = "SC_CKB_DIBBUR"
SC_MELUR = "SC_CKB_MELUR"

CENTERS = [
    {"id": HUB, "name": "Chikkaballapur District PHC", "center_type": CenterType.DISTRICT_HUB},
    {"id": SC_MANCHE, "name": "Manchenahalli Sub-Centre", "center_type": CenterType.VILLAGE_SUB_CENTRE},
    {"id": SC_NAGA, "name": "Nagamangala Sub-Centre", "center_type": CenterType.VILLAGE_SUB_CENTRE},
    {"id": SC_DIBBUR, "name": "Dibburahalli Sub-Centre", "center_type": CenterType.VILLAGE_SUB_CENTRE},
    {"id": SC_MELUR, "name": "Melur Sub-Centre", "center_type": CenterType.VILLAGE_SUB_CENTRE},
]

# One worker per center. Default password is identical across all seed
# accounts for local dev/demo convenience ONLY — flagged clearly so this
# never quietly ships to a real deployment unchanged.
DEFAULT_SEED_PASSWORD = "securepass"

WORKERS = [
    {"username": "hubworker", "center_id": HUB},
    {"username": "mancheworker", "center_id": SC_MANCHE},
    {"username": "nagaworker", "center_id": SC_NAGA},
    {"username": "dibburworker", "center_id": SC_DIBBUR},
    {"username": "melurworker", "center_id": SC_MELUR},
]

# Tiered stock, deliberately chosen to exercise the routing engine:
#   - Hub is heavily stocked (the "always has it" fallback of last resort).
#   - Manchenahalli is OUT of Paracetamol, to force fallback routing.
#   - Melur has exactly 1 unit of Paracetamol, to exercise the
#     reserve_stock() atomic race-condition path under concurrent requests.
#   - BCG is vaccine-tier, stocked more conservatively and unevenly,
#     since cold-chain vaccines realistically don't sit at every sub-centre.
INVENTORY_SEED = [
    # MED_PARA_500
    {"center_id": HUB, "item_id": "MED_PARA_500", "item_name": "Paracetamol 500mg", "quantity": 240},
    {"center_id": SC_MANCHE, "item_id": "MED_PARA_500", "item_name": "Paracetamol 500mg", "quantity": 0},
    {"center_id": SC_NAGA, "item_id": "MED_PARA_500", "item_name": "Paracetamol 500mg", "quantity": 18},
    {"center_id": SC_DIBBUR, "item_id": "MED_PARA_500", "item_name": "Paracetamol 500mg", "quantity": 6},
    {"center_id": SC_MELUR, "item_id": "MED_PARA_500", "item_name": "Paracetamol 500mg", "quantity": 1},
    # VAC_BCG_001
    {"center_id": HUB, "item_id": "VAC_BCG_001", "item_name": "BCG Vaccine", "quantity": 50},
    {"center_id": SC_MANCHE, "item_id": "VAC_BCG_001", "item_name": "BCG Vaccine", "quantity": 4},
    {"center_id": SC_NAGA, "item_id": "VAC_BCG_001", "item_name": "BCG Vaccine", "quantity": 0},
    {"center_id": SC_DIBBUR, "item_id": "VAC_BCG_001", "item_name": "BCG Vaccine", "quantity": 0},
    {"center_id": SC_MELUR, "item_id": "VAC_BCG_001", "item_name": "BCG Vaccine", "quantity": 2},
]


def seed_centers(session: Session) -> None:
    for center_data in CENTERS:
        existing = session.get(AshaCenter, center_data["id"])
        if existing:
            logger.info(f"AshaCenter '{center_data['id']}' already exists, skipping.")
            continue
        session.add(AshaCenter(**center_data))
        logger.info(f"Seeded AshaCenter: {center_data['id']} ({center_data['name']})")
    session.commit()


def seed_workers(session: Session) -> None:
    for worker_data in WORKERS:
        existing = session.exec(
            select(Worker).where(Worker.username == worker_data["username"])
        ).first()
        if existing:
            logger.info(f"Worker '{worker_data['username']}' already exists, skipping.")
            continue
        session.add(
            Worker(
                username=worker_data["username"],
                hashed_password=get_password_hash(DEFAULT_SEED_PASSWORD),
                center_id=worker_data["center_id"],
            )
        )
        logger.info(f"Seeded Worker: {worker_data['username']} -> {worker_data['center_id']}")
    session.commit()


def seed_inventory(session: Session) -> None:
    for item in INVENTORY_SEED:
        existing = session.exec(
            select(CenterInventory).where(
                CenterInventory.center_id == item["center_id"],
                CenterInventory.item_id == item["item_id"],
            )
        ).first()
        if existing:
            logger.info(
                f"CenterInventory row for {item['item_id']} at {item['center_id']} "
                f"already exists, skipping."
            )
            continue
        session.add(CenterInventory(**item))
        logger.info(
            f"Seeded inventory: {item['item_id']} @ {item['center_id']} = {item['quantity']} units"
        )
    session.commit()


def run_seed() -> None:
    logger.info("Initializing database tables...")
    create_db_and_tables()

    with Session(engine) as session:
        logger.info("Seeding ASHA centers...")
        seed_centers(session)

        logger.info("Seeding ASHA workers...")
        seed_workers(session)

        logger.info("Seeding center inventory...")
        seed_inventory(session)

    logger.info("Seeding complete.")
    logger.info(
        f"All seed worker accounts use the password: '{DEFAULT_SEED_PASSWORD}' "
        f"— change this before any non-local deployment."
    )


if __name__ == "__main__":
    run_seed()