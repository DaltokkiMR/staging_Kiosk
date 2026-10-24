"""전체 흐름 테스트: pytest -q"""
import os

os.environ["SEED_HISTORY"] = "true"  # 테스트는 데모 기록이 있는 상태에서
import tempfile

_db = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db}"
os.environ["ANTHROPIC_API_KEY"] = ""  # 규칙 기반 AI로 테스트

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

K = {"X-Kiosk-Key": "demo-kiosk-key"}


def login(c, email):
    r = c.post("/api/auth/login", json={"email": email, "password": "1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_full_flow():
    with TestClient(app) as c:
        user = login(c, "user@demo.com")
        owner = login(c, "owner@demo.com")

        menus = c.get("/api/kiosk/menus", headers=K).json()
        kimchi = next(m for m in menus if m["name"] == "김치찌개")
        jeyuk = next(m for m in menus if m["name"] == "제육볶음")

        # 단골 인식
        qr = c.post("/api/me/payment-qr", headers=user, json={}).json()
        ident = c.post("/api/kiosk/identify", headers=K, json={"qr_payload": qr["qr_payload"]}).json()
        assert "김치찌개" in ident["greeting"]
        assert ident["point_balance"] > 0

        # AI 대화 + 없는 옵션 감지
        chat = c.post("/api/kiosk/ai/chat", headers=K,
                      json={"session_id": "t1", "message": "김치찌개 매워요? 맵기 조절 되나요?"}).json()
        assert chat["reply"]
        assert "맵기 조절" in chat["unmet_requests"]
        chat2 = c.post("/api/kiosk/ai/chat", headers=K, json={"session_id": "t1", "message": "안 매운 거 추천해줘"}).json()
        assert all(m["spicy_level"] <= 1 for m in chat2["recommended_menus"])

        # 주문 (제육 곱빼기 + 김치찌개) = 13000 + 9000 = 22000
        opt = jeyuk["options"][0]["id"]
        order = c.post("/api/kiosk/orders", headers=K, json={"items": [
            {"menu_item_id": jeyuk["id"], "option_ids": [opt]}, {"menu_item_id": kimchi["id"]}]}).json()
        assert order["total_amount"] == 22000

        # 우선순위 결제: 포인트 먼저 → 카카오페이(잔액 5000 부족) 실패 → 마포 지역화폐 성공
        qr = c.post("/api/me/payment-qr", headers=user, json={}).json()  # 단골 확인에 쓴 QR은 소진됨
        pay = c.post("/api/kiosk/payments/qr", headers=K,
                     json={"order_id": order["id"], "qr_payload": qr["qr_payload"]}).json()
        assert pay["success"], pay
        assert pay["points_used"] > 0
        assert pay["attempts"][1]["success"] is False and pay["attempts"][2]["success"] is True
        assert pay["points_earned"] > 0

        # 같은 QR 재사용 불가
        order2 = c.post("/api/kiosk/orders", headers=K, json={"items": [{"menu_item_id": kimchi["id"]}]}).json()
        r = c.post("/api/kiosk/payments/qr", headers=K, json={"order_id": order2["id"], "qr_payload": qr["qr_payload"]})
        assert r.status_code == 400

        # 앱 폴링으로 결과 확인
        st = c.get(f"/api/me/payment-qr/{qr['token']}", headers=user).json()
        assert st["used"] and st["result"]["success"]

        # 카드 지정 결제 (신용카드)
        methods = c.get("/api/me/payment-methods", headers=user).json()
        card = next(m for m in methods if m["pay_type"] == "credit_card")
        qr2 = c.post("/api/me/payment-qr", headers=user, json={"method_id": card["id"]}).json()
        pay2 = c.post("/api/kiosk/payments/qr", headers=K,
                      json={"order_id": order2["id"], "qr_payload": qr2["qr_payload"]}).json()
        assert pay2["success"] and pay2["payments"][0]["pay_type"] == "credit_card"

        # 우선순위 변경
        new_order = [card["id"]] + [m["id"] for m in methods if m["id"] != card["id"]]
        pr = c.put("/api/me/payment-methods/priority", headers=user, json={"method_ids": new_order}).json()
        assert pr[0]["id"] == card["id"]

        # 소비자 성향/추천
        prof = c.get("/api/me/taste-profile", headers=user).json()
        assert "김치찌개" in prof["favorite_menus"]
        assert c.get("/api/me/recommendations/stores", headers=user).json()
        assert c.get("/api/me/points", headers=user).json()[0]["balance"] >= 0

        # 사장님: 매출, 인사이트, 옵션 추가
        sales = c.get("/api/owner/stores/1/sales", headers=owner).json()
        assert sales["total_revenue"] > 0 and sales["by_payment_type"]
        ins = c.get("/api/owner/stores/1/insights", headers=owner).json()
        assert ins["unmet_requests"][0]["request"] == "맵기 조절"
        assert ins["suggestions"]
        r = c.post(f"/api/owner/menus/{kimchi['id']}/options", headers=owner,
                   json={"group": "맵기", "name": "덜 맵게", "extra_price": 0})
        assert r.status_code == 200
        chat3 = c.post("/api/kiosk/ai/chat", headers=K, json={"session_id": "t2", "message": "맵기 조절 되나요?"}).json()
        assert "맵기 조절" not in chat3["unmet_requests"]

        # 지도: 비로그인 / 로그인
        pins = c.get("/api/map/stores", params={"lat": 37.5555, "lng": 126.91}).json()
        assert len(pins) >= 9 and all("recommend" not in p for p in pins)
        assert pins[0]["distance_m"] is not None and pins[0]["price_range"]
        near = c.get("/api/map/stores", params={"lat": 37.5555, "lng": 126.91, "radius_m": 200}).json()
        assert 0 < len(near) < len(pins)
        mine = c.get("/api/map/stores", headers=user, params={"lat": 37.5555, "lng": 126.91}).json()
        assert mine[0]["recommend"]["rank"] == 1
        detail = c.get("/api/map/stores/1", headers=user).json()
        assert detail["menus"] and detail["popular_menus"] and detail["for_me"]["usual_items"]
        assert detail["for_me"]["recommended_menus"][0]["reason"]

        # 행동 패턴 + 추천
        beh = c.get("/api/me/behavior", headers=user).json()
        assert beh["visit_count"] >= 8 and beh["slots"] and beh["summary"]
        recs = c.get("/api/me/recommendations/stores", headers=user, params={"lat": 37.5555, "lng": 126.91}).json()
        assert recs and recs[0]["reasons"]
        from datetime import datetime
        from app.database import SessionLocal
        from app.models import User as U
        from app.services.recommend import recommend_stores
        with SessionLocal() as db:
            me = db.query(U).filter_by(email="user@demo.com").first()
            names = lambda dt: [r["name"] for r in recommend_stores(db, me, limit=3, now=dt, with_ai_comment=False)]
            lunch = names(datetime(2026, 10, 21, 12, 30))   # 수요일 점심
            evening = names(datetime(2026, 10, 21, 19, 0))  # 수요일 저녁
            weekend = names(datetime(2026, 10, 24, 15, 0))  # 토요일 오후
            print("lunch", lunch, "evening", evening, "weekend", weekend)
            assert lunch[0] == "도도식당"
            assert "도도분식" in evening[:2]
            assert "카페 소담" in weekend[:2]
            all_ = recommend_stores(db, me, limit=20, now=datetime(2026, 10, 21, 12, 30), with_ai_comment=False)
            assert any("비슷한 손님" in " ".join(r["reasons"]) for r in all_)

        # 권한 체크
        assert c.get("/api/owner/stores", headers=user).status_code == 403
        assert c.get("/api/kiosk/menus", headers={"X-Kiosk-Key": "nope"}).status_code == 401
