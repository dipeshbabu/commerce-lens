"""Customer portal onboarding and monitor management routes."""

from fastapi import APIRouter

from commercelens.api.portal_management_actions import router as actions_router
from commercelens.api.portal_management_pages import router as pages_router

router = APIRouter()
router.include_router(pages_router)
router.include_router(actions_router)
