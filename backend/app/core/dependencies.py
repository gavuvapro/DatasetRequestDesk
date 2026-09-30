"""FastAPI dependencies: current user resolution and role-based access control.

All authorization is enforced here, server-side. The frontend hiding buttons is
a convenience, never the security boundary.
"""
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.database import get_db
from app.models import User
from app.models.user import UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)] = None,
    db: Session = Depends(get_db),
) -> User:
    """Resolve the JWT Bearer token to an active user, or 401."""
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(token)
    if payload is None or "sub" not in payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account is deactivated")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


class RoleChecker:
    """Dependency that gates an endpoint to the given roles.

    Usage: `current_user: CurrentUser = Depends(RoleChecker(UserRole.OPERATOR, UserRole.ADMIN))`
    """

    def __init__(self, *allowed: UserRole) -> None:
        self.allowed = set(allowed)

    def __call__(self, user: CurrentUser) -> User:
        if user.role not in self.allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {' or '.join(r.value for r in self.allowed)}",
            )
        return user


# Shared instances.
require_operator = RoleChecker(UserRole.OPERATOR, UserRole.ADMIN)
require_admin = RoleChecker(UserRole.ADMIN)
