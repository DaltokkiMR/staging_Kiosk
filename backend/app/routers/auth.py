from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Role, User
from ..schemas import LoginIn, PreferencesIn, SignupIn, TokenOut, UserOut
from ..security import create_access_token, get_current_user, hash_password, verify_password
from ..seed import add_demo_wallet
from ..services.ai_service import extract_taste_keywords

router = APIRouter(prefix="/api/auth", tags=["인증"])


@router.post("/signup", response_model=TokenOut)
def signup(data: SignupIn, db: Session = Depends(get_db)):
    if db.query(User).filter_by(email=data.email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 가입된 이메일입니다.")
    user = User(email=data.email, password_hash=hash_password(data.password), name=data.name,
                role=data.role.value, birthdate=data.birthdate, gender=data.gender, phone=data.phone, preferences={})
    db.add(user)
    db.flush()
    if settings.DEMO_MODE and user.role == Role.CONSUMER.value:
        add_demo_wallet(db, user)  # 시연: 가입하자마자 키오스크 결제까지 이어지게 데모 결제수단을 넣어둠
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
    new = data.model_dump(exclude_none=True)
    prefs.update(new)
    if {"likes_text", "dislikes_text", "notes"} & new.keys():
        kw = extract_taste_keywords(prefs.get("likes_text", ""), prefs.get("dislikes_text", ""), prefs.get("notes", ""))
        prefs["likes"] = kw["likes"]
        if "dislikes" not in new:
            prefs["dislikes"] = kw["dislikes"]
        prefs["allergies"] = list(dict.fromkeys((prefs.get("allergies") or []) + kw["allergies"]))
    user.preferences = prefs
    db.commit()
    return user
