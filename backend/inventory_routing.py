"""
inventory_routing.py — Aacharya AI Supply Chain Routing Engine
================================================================
Bridges matcher.py (intent layer) and models.py (data layer). Resolves
"where can this user get item X" using a static 5x5 proximity matrix for
the Chikkaballapur regional cluster, with atomic stock reservation to
prevent two concurrent edge-network users from being promised the same
last unit.

Two distinct operations are deliberately kept separate:
    find_nearest_stock() — READ-ONLY. Safe to call repeatedly (e.g. to
                            render a dropdown or status check). Never
                            mutates the database.
    reserve_stock()      — WRITE. Atomically decrements quantity via a
                            single conditional UPDATE statement. This is
                            the only function in the system permitted to
                            change stock counts for a fulfilled request.

Checking stock in Python and saving later (read-then-write) is exactly
the pattern that causes double-booking under concurrent requests. Every
mutation here is a single round-trip conditional UPDATE; there is no
window between "check" and "write" for a second request to interleave.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import update
from sqlmodel import Session, select

from models import AshaCenter, CenterInventory

# --------------------------------------------------------------------------
# Static 5x5 Proximity Matrix (Chikkaballapur Regional Cluster)
# --------------------------------------------------------------------------
# Distances in km, hand-entered from approximate road distance, not
# straight-line. Symmetric by construction (A->B == B->A). This is a fixed
# 5-node cluster; if the cluster grows, this matrix needs deliberate
# re-authoring, not a generated/interpolated update — distances here are
# meant to be auditable, not computed.

HUB = "PHC_CKB_HUB"
SC_MANCHE = "SC_CKB_MANCHE"
SC_NAGA = "SC_CKB_NAGA"
SC_DIBBUR = "SC_CKB_DIBBUR"
SC_MELUR = "SC_CKB_MELUR"

CENTER_IDS = [HUB, SC_MANCHE, SC_NAGA, SC_DIBBUR, SC_MELUR]

# Upper-triangle pairwise distances; matrix below is built symmetrically
# from this so each pair is authored exactly once (avoids accidental
# asymmetry from a copy-paste error in a fully duplicated 5x5 table).
_RAW_DISTANCES_KM = {
    (HUB, SC_MANCHE): 6.2,
    (HUB, SC_NAGA): 8.9,
    (HUB, SC_DIBBUR): 11.4,
    (HUB, SC_MELUR): 7.8,
    (SC_MANCHE, SC_NAGA): 9.5,
    (SC_MANCHE, SC_DIBBUR): 14.0,
    (SC_MANCHE, SC_MELUR): 5.3,
    (SC_NAGA, SC_DIBBUR): 6.7,
    (SC_NAGA, SC_MELUR): 10.1,
    (SC_DIBBUR, SC_MELUR): 9.0,
}


def _build_distance_matrix() -> dict[str, dict[str, float]]:
    """Expands the upper-triangle distance table into a full symmetric matrix."""
    matrix: dict[str, dict[str, float]] = {cid: {} for cid in CENTER_IDS}
    for cid in CENTER_IDS:
        matrix[cid][cid] = 0.0
    for (a, b), dist in _RAW_DISTANCES_KM.items():
        matrix[a][b] = dist
        matrix[b][a] = dist
    return matrix


DISTANCE_MATRIX = _build_distance_matrix()


def get_sorted_neighbors(center_id: str) -> list[tuple[str, float]]:
    """
    Returns [(neighbor_center_id, distance_km), ...] sorted ascending by
    distance, excluding the center itself. Works relative to ANY of the
    5 nodes (the hub is not treated as special in this function — it's
    just another node in the matrix).
    """
    if center_id not in DISTANCE_MATRIX:
        raise ValueError(f"Unknown center_id: {center_id}")

    neighbors = [
        (other_id, dist)
        for other_id, dist in DISTANCE_MATRIX[center_id].items()
        if other_id != center_id
    ]
    neighbors.sort(key=lambda pair: pair[1])
    return neighbors


# --------------------------------------------------------------------------
# Read-only stock lookup
# --------------------------------------------------------------------------

def _get_stock_row(session: Session, center_id: str, item_id: str) -> Optional[CenterInventory]:
    statement = select(CenterInventory).where(
        CenterInventory.center_id == center_id,
        CenterInventory.item_id == item_id,
    )
    return session.exec(statement).first()


def _center_name(session: Session, center_id: str) -> Optional[str]:
    center = session.get(AshaCenter, center_id)
    return center.name if center else None


def find_nearest_stock(
    session: Session,
    current_center_id: str,
    item_id: str,
    min_quantity: int = 1,
) -> dict:
    """
    READ-ONLY proximity check. Does not reserve or mutate stock.

    1. If current_center_id has >= min_quantity in stock, returns it
       immediately (no need to search further).
    2. Otherwise walks the proximity-sorted neighbor list and returns the
       first center with sufficient stock.
    3. If nothing in the cluster has stock, returns a structured
       out-of-stock payload (global_out_of_stock=True) so the API layer
       can trigger a restock alert.

    Return shape (always present): {
        "found": bool,
        "center_id": str | None,
        "center_name": str | None,
        "distance_km": float,          # 0.0 if same center as requested
        "quantity_available": int,
        "is_fallback": bool,           # True if not the originally requested center
        "global_out_of_stock": bool,
    }
    """
    if current_center_id not in DISTANCE_MATRIX:
        raise ValueError(f"Unknown center_id: {current_center_id}")

    # Step 1 — check the requested center first.
    primary_row = _get_stock_row(session, current_center_id, item_id)
    if primary_row and primary_row.quantity >= min_quantity:
        return {
            "found": True,
            "center_id": current_center_id,
            "center_name": _center_name(session, current_center_id),
            "distance_km": 0.0,
            "quantity_available": primary_row.quantity,
            "is_fallback": False,
            "global_out_of_stock": False,
        }

    # Step 2 — walk neighbors in proximity order.
    for neighbor_id, distance_km in get_sorted_neighbors(current_center_id):
        row = _get_stock_row(session, neighbor_id, item_id)
        if row and row.quantity >= min_quantity:
            return {
                "found": True,
                "center_id": neighbor_id,
                "center_name": _center_name(session, neighbor_id),
                "distance_km": distance_km,
                "quantity_available": row.quantity,
                "is_fallback": True,
                "global_out_of_stock": False,
            }

    # Step 3 — nothing in the cluster is stocked.
    return {
        "found": False,
        "center_id": None,
        "center_name": None,
        "distance_km": None,
        "quantity_available": 0,
        "is_fallback": False,
        "global_out_of_stock": True,
    }


# --------------------------------------------------------------------------
# Atomic stock reservation
# --------------------------------------------------------------------------

def reserve_stock(
    session: Session,
    center_id: str,
    item_id: str,
    amount: int = 1,
) -> bool:
    """
    WRITE. Atomically decrements quantity for (center_id, item_id) in a
    single conditional UPDATE — `WHERE quantity >= amount` is evaluated
    by SQLite itself as part of the same statement that performs the
    decrement, so there is no read-then-write gap a second concurrent
    request could land in.

    Returns True if the row was updated (reservation succeeded), False if
    zero rows matched (either insufficient stock or the row doesn't
    exist) — in which case NO partial state is written; the caller should
    fall back to the next nearest center.
    """
    statement = (
        update(CenterInventory)
        .where(
            CenterInventory.center_id == center_id,
            CenterInventory.item_id == item_id,
            CenterInventory.quantity >= amount,
        )
        .values(quantity=CenterInventory.quantity - amount)
    )
    result = session.exec(statement)
    session.commit()

    # rowcount is 0 if no row matched all three WHERE conditions —
    # i.e. either no inventory row exists for this center+item, or
    # quantity was already below `amount` (someone else got there first,
    # or it was genuinely out of stock).
    return result.rowcount > 0


def reserve_with_fallback(
    session: Session,
    current_center_id: str,
    item_id: str,
    amount: int = 1,
) -> dict:
    """
    Combines proximity routing with atomic reservation: attempts to
    reserve `amount` units at current_center_id first; on failure (race
    lost, or simply out of stock), walks the proximity-sorted neighbor
    list and attempts an atomic reservation at each in turn, stopping at
    the first success.

    This re-checks stock live at each hop via the atomic UPDATE itself
    (not a prior read), so it stays correct even if another request
    depletes a neighbor's stock in between this function's own hops.

    Return shape: {
        "reserved": bool,
        "center_id": str | None,
        "center_name": str | None,
        "distance_km": float | None,
        "is_fallback": bool,
        "global_out_of_stock": bool,
    }
    """
    if current_center_id not in DISTANCE_MATRIX:
        raise ValueError(f"Unknown center_id: {current_center_id}")

    # Attempt 1 — the requested center, via atomic UPDATE (not a prior read).
    if reserve_stock(session, current_center_id, item_id, amount):
        return {
            "reserved": True,
            "center_id": current_center_id,
            "center_name": _center_name(session, current_center_id),
            "distance_km": 0.0,
            "is_fallback": False,
            "global_out_of_stock": False,
        }

    # Attempt 2+ — proximity-ordered fallback, each hop re-checked live.
    for neighbor_id, distance_km in get_sorted_neighbors(current_center_id):
        if reserve_stock(session, neighbor_id, item_id, amount):
            return {
                "reserved": True,
                "center_id": neighbor_id,
                "center_name": _center_name(session, neighbor_id),
                "distance_km": distance_km,
                "is_fallback": True,
                "global_out_of_stock": False,
            }

    # No center in the cluster could fulfill the reservation.
    return {
        "reserved": False,
        "center_id": None,
        "center_name": None,
        "distance_km": None,
        "is_fallback": False,
        "global_out_of_stock": True,
    }


# --------------------------------------------------------------------------
# Self-test (run directly: `python inventory_routing.py`)
# --------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    from models import create_db_and_tables, engine, CenterType

    db_file = "health_chatbot.db"
    if os.path.exists(db_file):
        os.remove(db_file)

    create_db_and_tables()

    with Session(engine) as setup_session:
        setup_session.add_all([
            AshaCenter(id=HUB, name="Chikkaballapur District PHC", center_type=CenterType.DISTRICT_HUB),
            AshaCenter(id=SC_MANCHE, name="Manchenahalli Sub-Centre", center_type=CenterType.VILLAGE_SUB_CENTRE),
            AshaCenter(id=SC_NAGA, name="Nagamangala Sub-Centre", center_type=CenterType.VILLAGE_SUB_CENTRE),
            AshaCenter(id=SC_DIBBUR, name="Dibburahalli Sub-Centre", center_type=CenterType.VILLAGE_SUB_CENTRE),
            AshaCenter(id=SC_MELUR, name="Melur Sub-Centre", center_type=CenterType.VILLAGE_SUB_CENTRE),
        ])
        # SC_MANCHE has 0 stock; SC_MELUR (its nearest neighbor) has 1 unit only.
        setup_session.add_all([
            CenterInventory(center_id=HUB, item_id="MED_PARA_500", item_name="Paracetamol 500mg", quantity=240),
            CenterInventory(center_id=SC_MANCHE, item_id="MED_PARA_500", item_name="Paracetamol 500mg", quantity=0),
            CenterInventory(center_id=SC_NAGA, item_id="MED_PARA_500", item_name="Paracetamol 500mg", quantity=18),
            CenterInventory(center_id=SC_MELUR, item_id="MED_PARA_500", item_name="Paracetamol 500mg", quantity=1),
        ])
        setup_session.commit()

    print("--- get_sorted_neighbors(SC_CKB_MANCHE) ---")
    for cid, dist in get_sorted_neighbors(SC_MANCHE):
        print(f"  {cid}: {dist} km")

    print("\n--- find_nearest_stock: SC_MANCHE out of stock -> should route to SC_MELUR (5.3km, nearest with stock) ---")
    with Session(engine) as s:
        result = find_nearest_stock(s, SC_MANCHE, "MED_PARA_500")
        print(" ", result)

    print("\n--- Simulating two concurrent users both requesting the last unit at SC_MELUR ---")
    with Session(engine) as s1, Session(engine) as s2:
        r1 = reserve_with_fallback(s1, SC_MANCHE, "MED_PARA_500", amount=1)
        print("  User 1 reservation:", r1)
        r2 = reserve_with_fallback(s2, SC_MANCHE, "MED_PARA_500", amount=1)
        print("  User 2 reservation (should fall back past depleted SC_MELUR to SC_NAGA):", r2)

    print("\n--- Final stock state ---")
    with Session(engine) as s:
        rows = s.exec(select(CenterInventory).where(CenterInventory.item_id == "MED_PARA_500")).all()
        for row in rows:
            print(f"  {row.center_id}: {row.quantity}")

    print("\n--- Draining global stock entirely, then checking graceful failure ---")
    with Session(engine) as s:
        for cid in CENTER_IDS:
            row = _get_stock_row(s, cid, "MED_PARA_500")
            if row:
                row.quantity = 0
                s.add(row)
        s.commit()
    with Session(engine) as s:
        result = find_nearest_stock(s, SC_MANCHE, "MED_PARA_500")
        print(" ", result)
        reserve_result = reserve_with_fallback(s, SC_MANCHE, "MED_PARA_500")
        print(" ", reserve_result)

    os.remove(db_file)
