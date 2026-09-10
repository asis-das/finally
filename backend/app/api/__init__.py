"""REST routers for the FinAlly backend."""

from .health import router as health_router
from .portfolio import router as portfolio_router
from .watchlist import router as watchlist_router

__all__ = ["health_router", "portfolio_router", "watchlist_router"]
