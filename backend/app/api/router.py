"""Aggregates all module routers under the configured API prefix."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.modules.assets.router import router as assets_router
from app.modules.closure.router import router as closure_router
from app.modules.complaints.router import router as complaints_router
from app.modules.demo.router import router as demo_router
from app.modules.intake.router import router as intake_router
from app.modules.notify.router import router as notify_router
from app.modules.review.router import router as review_router

api_router = APIRouter()
api_router.include_router(intake_router)
api_router.include_router(complaints_router)
api_router.include_router(closure_router)
api_router.include_router(review_router)
api_router.include_router(notify_router)
api_router.include_router(assets_router)

if get_settings().demo_reset_enabled:
    api_router.include_router(demo_router)