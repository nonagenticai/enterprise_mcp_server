from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from collections.abc import AsyncIterator, Callable
from concurrent.futures.thread import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, LiteralString, TypeVar

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing_extensions import ParamSpec
from uuid_v7.base import uuid7

P = ParamSpec("P")
R = TypeVar("R")

# Default database location
DEFAULT_DB_PATH = Path(__file__).parent / "tickets.sqlite"

# Initialize FastAPI app
app = FastAPI(
    title="Cleaning Request API",
    description="API for managing cleaning requests",
    version="1.0.0",
)

# Configure CORS
_cors_allowed_origins = [
    o.strip()
    for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Define the Pydantic model for cleaning requests
class CleaningRequestPayload(BaseModel):
    location: str = Field(..., description="Exact location of the incident")
    severity: int = Field(..., ge=1, le=5, description="Severity level (1-5 scale)")
    contact_email: str | None = Field(None, description="Optional contact email")


@app.post("/create-request", summary="Create a new cleaning request", status_code=201)
async def http_create_request(request: Request, payload: CleaningRequestPayload):
    """
    Creates a new cleaning request.
    Requires the 'location', 'severity', and optional 'contact_email'.
    """
    try:
        result = await create_request(payload)
        return JSONResponse(content=result, status_code=201)  # 201 Created
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Unexpected error in /create-request endpoint")
        raise HTTPException(
            status_code=500, detail="Internal server error during request creation."
        )


async def create_request(payload: CleaningRequestPayload):
    """Create a new cleaning request in the database and return its ID."""
    async with CleaningRequestDB.connect() as db:
        request_id = await db.add_request(payload)
        return {
            "status": "success",
            "message": "Cleaning request created successfully",
            "request_id": request_id,
        }


@app.get("/tickets", summary="List all cleaning requests")
async def list_tickets(request: Request):
    """
    Retrieves all cleaning requests from the database.
    Returns a list of all cleaning requests with their details.
    """
    try:
        result = await get_all_tickets()
        return JSONResponse(content=result, status_code=200)
    except Exception:
        logger.exception("Unexpected error in /tickets endpoint")
        raise HTTPException(
            status_code=500, detail="Internal server error while retrieving tickets."
        )


async def get_all_tickets():
    """Retrieve all cleaning requests from the database."""
    async with CleaningRequestDB.connect() as db:
        tickets = await db.get_all_requests()
        return {"status": "success", "tickets": tickets, "count": len(tickets)}


class CleaningRequestDB:
    """API for interacting with the cleaning request database."""

    def __init__(
        self,
        con: sqlite3.Connection,
        loop: asyncio.AbstractEventLoop,
        executor: ThreadPoolExecutor,
    ):
        self.con = con
        self._loop = loop
        self._executor = executor

    @classmethod
    @asynccontextmanager
    async def connect(
        cls, file: Path = DEFAULT_DB_PATH
    ) -> AsyncIterator[CleaningRequestDB]:
        """Create a new database connection with a dynamic path."""
        loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor(max_workers=1)
        con = await loop.run_in_executor(executor, cls._connect, file)
        slf = cls(con, loop, executor)
        try:
            yield slf
        finally:
            await slf._asyncify(con.close)

    @staticmethod
    def _connect(file: Path) -> sqlite3.Connection:
        """Connect to SQLite database and create cleaning_requests table if it doesn't exist."""
        con = sqlite3.connect(str(file))
        con.row_factory = sqlite3.Row  # Enable row factory for named access
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS cleaning_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                location TEXT NOT NULL,
                severity INTEGER NOT NULL,
                contact_email TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """
        )
        con.commit()
        return con

    async def add_request(self, payload: CleaningRequestPayload) -> str:
        """Add a new cleaning request to the database."""
        request_id = str(uuid7())
        now = datetime.utcnow().isoformat()

        await self._asyncify(
            self._execute,
            """
            INSERT INTO cleaning_requests 
            (request_id, location, severity, contact_email, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'pending', ?, ?)
            """,
            request_id,
            payload.location,
            payload.severity,
            payload.contact_email,
            now,
            now,
            commit=True,
        )

        logger.info(
            f"Created cleaning request {request_id} for location: {payload.location}"
        )
        return request_id

    async def get_request(self, request_id: str) -> dict[str, Any] | None:
        """Get a cleaning request by its ID."""
        cursor = await self._asyncify(
            self._execute,
            "SELECT * FROM cleaning_requests WHERE request_id = ?",
            request_id,
        )
        row = await self._asyncify(cursor.fetchone)
        if row:
            return dict(row)
        return None

    async def fetchall(self, sql: LiteralString, *args: Any) -> list[dict[str, Any]]:
        """Fetch all rows from the database."""
        cursor = await self._asyncify(self._execute, sql, *args)
        rows = await self._asyncify(cursor.fetchall)
        return [dict(row) for row in rows]

    def _execute(
        self, sql: LiteralString, *args: Any, commit: bool = False
    ) -> sqlite3.Cursor:
        """Execute a SQL query."""
        cur = self.con.cursor()
        cur.execute(sql, args)
        if commit:
            self.con.commit()
        return cur

    async def _asyncify(
        self, func: Callable[P, R], *args: P.args, **kwargs: P.kwargs
    ) -> R:
        """Run a synchronous function asynchronously in the executor."""
        return await self._loop.run_in_executor(
            self._executor,
            partial(func, **kwargs),
            *args,
        )

    async def get_all_requests(self) -> list[dict[str, Any]]:
        """Get all cleaning requests from the database."""
        return await self.fetchall(
            "SELECT * FROM cleaning_requests ORDER BY created_at DESC"
        )


# class CleaningRequest(BaseModel):
#     request_id: str = Field(..., description="Unique identifier for the request")
#     status: str = Field(..., description="Current status of the request")
#     created_at: str = Field(..., description="Timestamp of when the request was created")
#     updated_at: str = Field(..., description="Timestamp of when the request was last updated")

# class CleaningRequestResponse(BaseModel):
#     success: bool = Field(..., description="Whether the request was processed successfully")
#     message: Optional[str] = Field(None, description="Additional message about the request")

# class CleaningRequestList(BaseModel):
#     requests: List[CleaningRequest] = Field(..., description="List of cleaning requests")

# class CleaningRequestService:
#     def __init__(self):
#         self.requests = {}
#         self.request_id_counter = 0

#     async def create_request(self, payload: CleaningRequestPayload) -> CleaningRequest:
#         """Create a new cleaning request"""
#         request_id = str(uuid.uuid4())
#         created_at = datetime.now().isoformat()
#         updated_at = created_at

#         request = CleaningRequest(
#             request_id=request_id,
#             status="pending",
#             created_at=created_at,
#             updated_at=updated_at
#         )

# Add this at the end of the file
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8769)
