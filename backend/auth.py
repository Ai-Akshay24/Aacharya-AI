"""
auth.py — Aacharya AI Server Entrypoint
==========================================
FastAPI gateway wiring the local deterministic engines (matcher.py,
inventory_routing.py) to the multi-center database (models.py). No
external LLM, no LangChain, no vector store, no network dependency for
the chat path — resolution is entirely local and deterministic.

To run: uvicorn auth:app --reload
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import FastAPI, APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from passlib.context import CryptContext
from jose import JWTError, jwt
from sqlmodel import Session, select

from models import (
    Worker,
    AshaCenter,
    CenterInventory,
    Alert,
    create_db_and_tables,
    get_session,
)
import matcher
import inventory_routing

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Authentication setup
# --------------------------------------------------------------------------
# NOTE: SECRET_KEY should come from the environment in production
# (see backend/.env). Hardcoding a fallback here only to preserve local
# dev ergonomics if .env is missing; this should be tightened before
# deployment so a missing .env fails loudly instead of silently using a
# known default.
import os
from dotenv import load_dotenv

load_dotenv()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.getenv("SECRET_KEY", "your_strong_secret_key_here_a9f8d6e5")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
security = HTTPBearer()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_worker(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: Session = Depends(get_session),
) -> Worker:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    worker = session.exec(select(Worker).where(Worker.username == username)).first()
    if worker is None:
        raise credentials_exception
    return worker


# --------------------------------------------------------------------------
# Lifespan — local engine only, no RAG/LLM setup
# --------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up application (local deterministic engine, no external LLM)...")
    create_db_and_tables()
    logger.info("Database tables ready.")
    yield
    logger.info("Shutting down application...")


# --------------------------------------------------------------------------
# App setup
# --------------------------------------------------------------------------

app = FastAPI(lifespan=lifespan)
api_router = APIRouter(prefix="/api")

# --------------------------------------------------------------------------
# Request / Response models
# --------------------------------------------------------------------------

class ChatRequest(BaseModel):
    query: str
    language: str = "en"


class ChatResponse(BaseModel):
    response: str
    intent: str
    requires_location: bool = False
    item_id: Optional[str] = None
    escalation_flag: bool = False
    escalation_action: Optional[str] = None


class AlertResponse(BaseModel):
    id: int
    message: str
    timestamp: datetime


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class BroadcastAlertRequest(BaseModel):
    message: str


class InventoryResponse(BaseModel):
    id: int
    center_id: str
    item_id: str
    item_name: str
    quantity: int


class UpdateInventoryRequest(BaseModel):
    item_id: str
    item_name: str
    quantity: int


class StatusResponse(BaseModel):
    status: str


# --------------------------------------------------------------------------
# Public Endpoints
# --------------------------------------------------------------------------

@api_router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Fully local, deterministic chat resolution. No network calls, no
    external LLM. Input is defensively normalized before being handed to
    the matcher pipeline; the matcher itself does its own Stage 0
    normalization, but trimming/lowercasing here keeps logging and any
    future caching layer consistent with what the pipeline actually sees.
    """
    cleaned_query = request.query.strip().lower()
    if not cleaned_query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    result = matcher.resolve_query(cleaned_query, request.language)

    # Critical path: emergency intents return immediately with escalation
    # metadata, bypassing any further branching.
    if result.intent == "emergency":
        return ChatResponse(
            response=result.response_text,
            intent=result.intent,
            requires_location=False,
            escalation_flag=result.escalation_flag,
            escalation_action=result.escalation_action,
        )

    # Medicine / location-dependent intents: signal the frontend to open
    # the ASHA center selection dropdown rather than answering directly.
    if result.intent == "medicine" or result.requires_location:
        return ChatResponse(
            response=result.response_text,
            intent=result.intent,
            requires_location=True,
            item_id=result.concept_id,
            escalation_flag=result.escalation_flag,
            escalation_action=result.escalation_action,
        )

    # Standard informational symptoms, diseases, vaccines, or unmatched
    # fallback — return the resolved (or fallback) text as-is.
    return ChatResponse(
        response=result.response_text,
        intent=result.intent,
        requires_location=False,
        escalation_flag=result.escalation_flag,
        escalation_action=result.escalation_action,
    )


@api_router.get("/get-alerts", response_model=List[AlertResponse])
async def get_alerts(session: Session = Depends(get_session)):
    alerts = session.exec(select(Alert).order_by(Alert.timestamp.desc())).all()
    return alerts


@api_router.get("/inventory/nearest-stock")
async def nearest_stock(
    center_id: str,
    item_id: str,
    session: Session = Depends(get_session),
):
    """
    Public read-only endpoint backing the frontend's location dropdown.
    Returns proximity-ranked stock availability without reserving
    anything — safe to call on dropdown open/change.
    """
    try:
        return inventory_routing.find_nearest_stock(session, center_id, item_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --------------------------------------------------------------------------
# Worker Endpoints (Protected)
# --------------------------------------------------------------------------

@api_router.post("/worker/login", response_model=LoginResponse)
async def worker_login(request: LoginRequest, session: Session = Depends(get_session)):
    worker = session.exec(select(Worker).where(Worker.username == request.username)).first()

    if not worker or not verify_password(request.password, worker.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    access_token = create_access_token(data={"sub": worker.username})
    return LoginResponse(access_token=access_token)


@api_router.post("/worker/broadcast-alert", response_model=StatusResponse)
async def broadcast_alert(
    request: BroadcastAlertRequest,
    session: Session = Depends(get_session),
    current_worker: Worker = Depends(get_current_worker),
):
    """
    Broadcasts an alert, automatically prefixing it with the worker's
    home center name (e.g. "Nagamangala Sub-Centre: Dengue Alert") so
    every broadcast is location-attributable without the worker having
    to type it themselves.
    """
    location_prefix = "Unassigned Center"
    if current_worker.center_id:
        center = session.get(AshaCenter, current_worker.center_id)
        if center:
            location_prefix = center.name
        else:
            logger.warning(
                f"Worker {current_worker.username} has center_id="
                f"{current_worker.center_id} which does not exist in AshaCenter."
            )

    prefixed_message = f"{location_prefix}: {request.message}"

    new_alert = Alert(message=prefixed_message)
    session.add(new_alert)
    session.commit()
    return StatusResponse(status="success")


@api_router.get("/worker/get-inventory", response_model=List[InventoryResponse])
async def get_inventory(
    session: Session = Depends(get_session),
    current_worker: Worker = Depends(get_current_worker),
):
    """
    Scoped to the logged-in worker's home center only. A worker has no
    visibility into other centers' stock through this endpoint — that's
    intentionally what /api/inventory/nearest-stock is for (read-only,
    public, cross-center routing view).
    """
    if not current_worker.center_id:
        raise HTTPException(
            status_code=400,
            detail="This worker is not assigned to a center.",
        )

    inventory = session.exec(
        select(CenterInventory).where(CenterInventory.center_id == current_worker.center_id)
    ).all()
    return inventory


@api_router.post("/worker/update-inventory", response_model=StatusResponse)
async def update_inventory(
    request: UpdateInventoryRequest,
    session: Session = Depends(get_session),
    current_worker: Worker = Depends(get_current_worker),
):
    """
    Writes are scoped entirely to current_worker.center_id — a worker
    cannot inject a row into another center's ledger through this
    endpoint, regardless of what center_id they might try to pass (note
    the request body has no center_id field at all; it's derived solely
    from the authenticated worker's own assignment).
    """
    if not current_worker.center_id:
        raise HTTPException(
            status_code=400,
            detail="This worker is not assigned to a center and cannot update inventory.",
        )

    existing_row = session.exec(
        select(CenterInventory).where(
            CenterInventory.center_id == current_worker.center_id,
            CenterInventory.item_id == request.item_id,
        )
    ).first()

    if existing_row:
        existing_row.quantity = request.quantity
        existing_row.item_name = request.item_name
        session.add(existing_row)
    else:
        new_row = CenterInventory(
            center_id=current_worker.center_id,
            item_id=request.item_id,
            item_name=request.item_name,
            quantity=request.quantity,
        )
        session.add(new_row)

    session.commit()
    return StatusResponse(status="success")


# --------------------------------------------------------------------------
# Final App Setup
# --------------------------------------------------------------------------

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# To run this file, use: uvicorn auth:app --reload