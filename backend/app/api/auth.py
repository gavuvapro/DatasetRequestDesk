"""Authentication endpoints: issue and inspect JWTs."""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.core.security import create_access_token, verify_password
from app.database import get_db
from app.models import User
from app.schemas.user import LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _issue_token_response(user: User) -> TokenResponse:
    token = create_access_token(str(user.id), {"role": user.role.value})
    return TokenResponse(
        access_token=token,
        user=UserOut(
            id=user.id,
            email=user.email,
            role=user.role,
            name=user.name,
            organisation=user.organisation,
            is_active=user.is_active,
            created_at=user.created_at,
        ),
    )


def _authenticate(db: Session, email: str, password: str) -> User:
    user = db.query(User).filter(User.email == email.strip().lower()).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account is deactivated")
    return user


@router.post("/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """OAuth2 password flow (form-encoded: username + password)."""
    user = _authenticate(db, form.username, form.password)
    return _issue_token_response(user)


@router.post("/login-json", response_model=TokenResponse)
def login_json(body: LoginRequest, db: Session = Depends(get_db)):
    """JSON variant of login for programmatic clients."""
    user = _authenticate(db, body.email, body.password)
    return _issue_token_response(user)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    return current_user
