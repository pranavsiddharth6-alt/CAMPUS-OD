from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.api.v1.router import api_router
from app.database.session import check_db_connection

app = FastAPI(
    title=settings.PROJECT_NAME,
    description=f"{settings.TAGLINE} for {settings.INSTITUTION}",
    version=settings.VERSION,
    debug=settings.DEBUG,
)

# Configure Development CORS for Vite Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global institutional exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "error": "InternalServerError",
            "message": str(exc) if settings.DEBUG else "An unexpected institutional server error occurred.",
            "path": str(request.url),
        },
    )

# Root Health Check Endpoint
@app.get("/", tags=["Health"])
def root_health_check():
    """Root health check endpoint reporting service and live PostgreSQL connection state."""
    db_health = check_db_connection()
    return {
        "status": "healthy" if db_health["connected"] else "degraded",
        "project": settings.PROJECT_NAME,
        "tagline": settings.TAGLINE,
        "institution": settings.INSTITUTION,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "database": db_health,
        "message": f"Welcome to {settings.PROJECT_NAME} API ({settings.INSTITUTION})",
    }

# Include API v1 Router
app.include_router(api_router, prefix="/api/v1")
