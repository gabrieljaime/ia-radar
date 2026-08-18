from fastapi import APIRouter

from app.web import overview, radar, runs, sources

router = APIRouter()
router.include_router(overview.router)
router.include_router(radar.router)
router.include_router(sources.router)
router.include_router(runs.router)
