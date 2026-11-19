from fastapi import APIRouter, Depends, HTTPException, status
from app.api.v1.admin_academics import router as admin_academics_router
from app.api.v1.admin_provisioning import admin_provisioning_router
from app.api.v1.auth import auth_router
from app.api.v1.od_applications import od_router
from app.database.session import check_db_connection
from app.schemas.health import DatabaseHealthResponse

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(admin_provisioning_router)
api_router.include_router(admin_academics_router)
api_router.include_router(od_router)


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
