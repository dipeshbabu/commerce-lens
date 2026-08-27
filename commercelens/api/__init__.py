"""CommerceLens API package."""

from commercelens.api.domain import router as domain_router
from commercelens.api.main import app
from commercelens.api.portal_management import router as portal_management_router

if not getattr(app.state, "portal_management_installed", False):
    app.include_router(portal_management_router)
    app.state.portal_management_installed = True

if not getattr(app.state, "commerce_domain_installed", False):
    app.include_router(domain_router)
    app.state.commerce_domain_installed = True

__all__ = ["app"]
