"""
API v1 module - Version 1 of the REST API.
"""

from fastapi import APIRouter

router = APIRouter()

# Import and include routers
# from .sources import router as sources_router
# from .jobs import router as jobs_router
# from .builds import router as builds_router
# from .tests import router as tests_router
# from .analytics import router as analytics_router

# router.include_router(sources_router, prefix="/sources", tags=["Sources"])
# router.include_router(jobs_router, prefix="/jobs", tags=["Jobs"])
# router.include_router(builds_router, prefix="/builds", tags=["Builds"])
# router.include_router(tests_router, prefix="/tests", tags=["Tests"])
# router.include_router(analytics_router, prefix="/analytics", tags=["Analytics"])
