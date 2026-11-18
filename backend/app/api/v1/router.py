from fastapi import APIRouter, Depends, HTTPException, status
from app.database.session import check_db_connection
from app.schemas.health import DatabaseHealthResponse

api_router = APIRouter()


@api_router.get("/status", tags=["Status"])
async def get_v1_status():
    """Version 1 API status endpoint."""
    return {
        "status": "operational",
        "version": "v1",
        "phase": "Phase 2 - Database Architecture & Backend Foundation",
    }


@api_router.get(
    "/health/db",
    response_model=DatabaseHealthResponse,
    tags=["Health"],
    summary="Check PostgreSQL Database Connectivity",
)
def get_db_health():
    """Live database connectivity probe.
    
    Returns the real PostgreSQL connection status, version and latency.
    """
    health = check_db_connection()
    return health
