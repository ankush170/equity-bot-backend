from fastapi import APIRouter
from app.api.v1.endpoints import api, auth

api_router = APIRouter()

# Include the auth router
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])

# Include the API router (for threads and other endpoints)
api_router.include_router(api.router, tags=["api"])

# Include any other routers
# If you have other endpoint routers, include them here 