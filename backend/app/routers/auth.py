from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import LoginIn, PreferencesIn, SignupIn, TokenOut, UserOut
from ..security import create_access_token, get_current_user, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["인증"])


@router.post("/signup", response_model=TokenOut)
def signup(data: SignupIn, db: Session = Depends(get_db)):
    if db.query(User).filter_by(email=data.email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 가입된 이메일입니다.")
    user = User(email=data.email, password_hash=hash_password(data.password), name=data.name,
                role=data.role.value, preferences={})
    db.add(user)
    db.commit()
    return TokenOut(access_token=create_access_token(user), user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=data.email).first()
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "이메일 또는 비밀번호가 올바르지 않습니다.")
    return TokenOut(access_token=create_access_token(user), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.put("/me/preferences", response_model=UserOut)
def update_preferences(data: PreferencesIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    prefs = dict(user.preferences or {})
    prefs.update(data.model_dump(exclude_none=True))
    user.preferences = prefs
    db.commit()
    return user
