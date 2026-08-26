"""CommerceLens API package."""

from commercelens.api.main import app
from commercelens.api.portal_management import router as portal_management_router

if not getattr(app.state, "portal_management_installed", False):
    app.include_router(portal_management_router)
    app.state.portal_management_installed = True

__all__ = ["app"]
