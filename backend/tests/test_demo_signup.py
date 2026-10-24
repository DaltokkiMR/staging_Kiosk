"""시연 흐름: 손님 없이 시작(reset_db --demo) → 앱에서 회원가입 → 입맛 설정 → 키오스크가 설정을 반영."""
import os

os.environ["SEED_HISTORY"] = "true"
import tempfile

os.environ.setdefault("DATABASE_URL", f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'd.db')}")
os.environ["ANTHROPIC_API_KEY"] = ""  # 규칙 기반 (키가 있으면 같은 흐름을 Claude가 처리)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Order, Role, Store, User  # noqa: E402
from app.seed import seed  # noqa: E402

K = {"X-Kiosk-Key": "rolling-kiosk-key"}  # 롤링파스타


def test_demo_reset_has_no_customers():
    old = settings.SEED_CUSTOMER, settings.SEED_HISTORY
    settings.SEED_CUSTOMER, settings.SEED_HISTORY = False, False
    try:
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as db:
            seed(db)
            assert db.query(User).filter_by(role=Role.CONSUMER.value).count() == 0
            assert db.query(User).filter_by(email="owner@demo.com").one()
            assert db.query(Store).filter_by(name="RollingPasta").one().menus
            assert db.query(Order).count() == 0
    finally:
        settings.SEED_CUSTOMER, settings.SEED_HISTORY = old


def test_signup_then_taste_then_kiosk():
    with TestClient(app) as c:
        r = c.post("/api/auth/signup", json={
            "email": "taste@demo.com", "password": "1234", "name": "이하늘", "role": "consumer",
            "birthdate": "2003-05-14", "gender": "여", "phone": "010-1234-5678"})
        assert r.status_code == 200, r.text
        assert r.json()["user"]["birthdate"] == "2003-05-14"
        U = {"Authorization": f"Bearer {r.json()['access_token']}"}
        # 데모 모드: 가입하자마자 결제수단이 있어 키오스크 결제까지 이어짐
        assert len(c.get("/api/me/payment-methods", headers=U).json()) == 4

        r = c.put("/api/auth/me/preferences", headers=U, json={
            "spicy": 1, "salty": 2, "sour": 0, "sweet": 4, "oily": 5,
            "allergies": ["갑각류"], "diet": [],
            "likes_text": "크림, 치즈", "dislikes_text": "토마토 싫어요", "notes": "우유 알레르기도 조금 있어요"})
        p = r.json()["preferences"]
        assert p["dislikes"] == ["토마토"] and p["likes"] == ["크림", "치즈"]
        assert "갑각류" in p["allergies"] and "우유" in p["allergies"]  # 특이사항 글에서도 알레르기를 찾음

        prof = c.get("/api/me/taste-profile", headers=U).json()
        assert prof["taste_tolerance"]["느끼한 맛"] == 5 and prof["notes"]
        assert "갑각류" in prof["summary"] or "우유" in prof["summary"]

        # 키오스크에서 앱 QR → 인사·추천에 설정이 반영 (토마토·갑각류·우유 메뉴 제외, 맵기 1 초과 제외)
        qr = c.post("/api/me/payment-qr", headers=U, json={}).json()
        s = c.post("/api/kiosk/session/start", headers=K, json={"qr_payload": qr["qr_payload"]}).json()
        assert "빼고" in s["greeting"] and s["recommended_menus"]
        menus = {m["id"]: m for m in c.get("/api/kiosk/menus", headers=K).json()}
        for m in s["recommended_menus"]:
            full = menus[m["id"]]
            assert "토마토" not in full["name"] and not {"갑각류", "우유"} & set(full["allergens"])
            assert full["spicy_level"] <= 1
