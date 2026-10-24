"""비밀번호 해시, JWT, 인증 의존성."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import Kiosk, Role, Store, User

_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    salt, digest = stored.split("$", 1)
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return hmac.compare_digest(check, digest)


def create_access_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def create_customer_session(user_id: int, store_id: int, kiosk_id: int | None = None, method_id: int | None = None,
                            use_points: bool = True, qr: str | None = None) -> str:
    """키오스크 첫 화면에서 앱 QR을 찍은 손님의 방문 세션(30분).
    앱에서 고른 결제카드(method_id)가 결제까지 이어지고, AI 대화 개인화에도 쓰임."""
    payload = {"sub": str(user_id), "store": store_id, "kiosk": kiosk_id, "typ": "kiosk_customer",
               "method": method_id, "points": use_points, "qr": qr,
               "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def read_customer_session(token: str, store_id: int, kiosk_id: int | None = None) -> dict | None:
    """유효하면 {"user_id", "method_id", "use_points", "qr"} 반환. 다른 가게·다른 키오스크 세션은 거절."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "kiosk_customer" or payload.get("store") != store_id:
        return None
    if kiosk_id is not None and payload.get("kiosk") not in (None, kiosk_id):
        return None
    return {"user_id": int(payload["sub"]), "method_id": payload.get("method"),
            "use_points": payload.get("points", True), "qr": payload.get("qr")}


def _user_from_creds(creds: HTTPAuthorizationCredentials | None, db: Session) -> User | None:
    if creds is None:
        return None
    try:
        payload = jwt.decode(creds.credentials, settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "유효하지 않은 토큰입니다.")
    if payload.get("typ") == "kiosk_customer":  # 키오스크 손님 세션으로는 로그인 불가
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "유효하지 않은 토큰입니다.")
    return db.get(User, int(payload["sub"]))


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)
) -> User:
    user = _user_from_creds(creds, db)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "로그인이 필요합니다.")
    return user


def get_optional_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)
) -> User | None:
    return _user_from_creds(creds, db)


def require_owner(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.OWNER.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "사장님 계정만 사용할 수 있습니다.")
    return user


def require_consumer(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.CONSUMER.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "손님 계정만 사용할 수 있습니다.")
    return user


def get_owned_store(store_id: int, owner: User, db: Session) -> Store:
    store = db.get(Store, store_id)
    if store is None or store.owner_id != owner.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "가게를 찾을 수 없습니다.")
    return store


def get_kiosk(x_kiosk_key: str = Header(..., alias="X-Kiosk-Key"), db: Session = Depends(get_db)) -> Kiosk:
    kiosk = db.query(Kiosk).filter(Kiosk.api_key == x_kiosk_key).first()
    if kiosk is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "등록되지 않은 키오스크입니다.")
    return kiosk
