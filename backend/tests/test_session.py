"""첫 화면 'UNIORDER 앱 있나요?' → QR 찍기 → 고른 카드로 계속 결제 / 카드 바꾸기 / 카드결제 + 가게별 대화 기억."""
import os

os.environ["SEED_HISTORY"] = "true"  # 테스트는 데모 기록이 있는 상태에서
import tempfile

os.environ.setdefault("DATABASE_URL", f"sqlite:///{os.path.join(tempfile.mkdtemp(), 's.db')}")
os.environ["ANTHROPIC_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

K1 = {"X-Kiosk-Key": "demo-kiosk-key"}      # 도도식당
K2 = {"X-Kiosk-Key": "demo-kiosk-key-2"}    # 도도분식


def test_session_flow():
    with TestClient(app) as c:
        tok = c.post("/api/auth/login", json={"email": "user@demo.com", "password": "1234"}).json()["access_token"]
        U = {"Authorization": f"Bearer {tok}"}
        methods = c.get("/api/me/payment-methods", headers=U).json()
        card = next(m for m in methods if m["pay_type"] == "credit_card")

        # 1) 앱에서 신한카드를 골라 QR → 키오스크 첫 화면에서 찍음
        qr = c.post("/api/me/payment-qr", headers=U, json={"method_id": card["id"]}).json()
        s = c.post("/api/kiosk/session/start", headers=K1, json={"qr_payload": qr["qr_payload"]}).json()
        assert s["selected_method"]["display_name"] == "신한카드"
        # 이 가게 기억: 덜 맵게 원함 + 땅콩 → 인사·추천에 반영
        assert s["memory"]["wants_less_spicy"] and "땅콩" in s["memory"]["mentioned_allergies"]
        assert "김치찌개" in s["greeting"] and "덜 맵게" in s["greeting"]
        assert all(m["spicy_level"] <= 2 for m in s["recommended_menus"])
        # QR은 소진 → 앱은 '연결됨' 표시
        st = c.get(f"/api/me/payment-qr/{qr['token']}", headers=U).json()
        assert st["used"] and st["result"]["type"] == "identified"
        assert c.post("/api/kiosk/session/start", headers=K1, json={"qr_payload": qr["qr_payload"]}).status_code == 400

        sess = s["customer_session"]
        # 2) 대화에도 기억 반영 (지난번 땅콩 언급 → 이번엔 말 안 해도 제외)
        chat = c.post("/api/kiosk/ai/chat", headers=K1,
                      json={"session_id": "k1", "message": "추천해 주세요", "customer_session": sess}).json()
        assert "땅콩" in chat["reply"]

        # 3) '결제 계속하기' → 처음 고른 신한카드로
        menus = c.get("/api/kiosk/menus", headers=K1).json()
        kimchi = next(m for m in menus if m["name"] == "김치찌개")
        o1 = c.post("/api/kiosk/orders", headers=K1, json={"items": [{"menu_item_id": kimchi["id"]}]}).json()
        p1 = c.post("/api/kiosk/payments/session", headers=K1, json={"order_id": o1["id"], "customer_session": sess}).json()
        assert p1["success"] and p1["payments"][-1]["pay_type"] == "credit_card" and p1["points_used"] == 0
        st = c.get(f"/api/me/payment-qr/{qr['token']}", headers=U).json()
        assert st["result"]["type"] == "paid" and st["result"]["success"]  # 앱에도 결제 결과

        # 4) '결제카드 바꾸기' → 목록에서 지역화폐 선택
        lst = c.post("/api/kiosk/session/methods", headers=K1, json={"customer_session": sess}).json()
        assert any(m["selected"] for m in lst) and all("****" in m["masked_number"] or not m["masked_number"] for m in lst)
        local = next(m for m in lst if m["pay_type"] == "local_currency")
        o2 = c.post("/api/kiosk/orders", headers=K1, json={"items": [{"menu_item_id": kimchi["id"]}]}).json()
        p2 = c.post("/api/kiosk/payments/session", headers=K1,
                    json={"order_id": o2["id"], "customer_session": sess, "method_id": local["id"]}).json()
        assert p2["success"] and p2["payments"][-1]["pay_type"] == "local_currency"

        # 5) '카드결제' (단말기) + 앱 손님이라 포인트 적립
        o3 = c.post("/api/kiosk/orders", headers=K1, json={"items": [{"menu_item_id": kimchi["id"]}]}).json()
        p3 = c.post("/api/kiosk/payments/card", headers=K1, json={"order_id": o3["id"], "customer_session": sess}).json()
        assert p3["success"] and p3["points_earned"] > 0
        # 비회원 카드결제
        o4 = c.post("/api/kiosk/orders", headers=K1, json={"items": [{"menu_item_id": kimchi["id"]}]}).json()
        p4 = c.post("/api/kiosk/payments/card", headers=K1, json={"order_id": o4["id"]}).json()
        assert p4["success"] and p4["points_earned"] == 0

        # 6) 다른 가게 키오스크에서는 이 세션 사용 불가 + 기억도 가게별
        o5 = c.post("/api/kiosk/orders", headers=K2, json={"items": [{"menu_item_id": c.get("/api/kiosk/menus", headers=K2).json()[0]["id"]}]}).json()
        assert c.post("/api/kiosk/payments/session", headers=K2, json={"order_id": o5["id"], "customer_session": sess}).status_code == 401
        qr2 = c.post("/api/me/payment-qr", headers=U, json={}).json()
        s2 = c.post("/api/kiosk/session/start", headers=K2, json={"qr_payload": qr2["qr_payload"]}).json()
        assert s2["selected_method"] is None  # 우선순위대로
        assert "로제떡볶이" in " ".join(s2["memory"]["past_questions"])
        assert not any("김치찌개" in q for q in s2["memory"]["past_questions"])


def test_pairing_kiosk_shows_qr():
    """카메라 없는 키오스크: 키오스크가 QR을 띄우고 → 손님 앱이 찍고 → 키오스크가 연결 확인."""
    with TestClient(app) as c:
        tok = c.post("/api/auth/login", json={"email": "user@demo.com", "password": "1234"}).json()["access_token"]
        U = {"Authorization": f"Bearer {tok}"}
        card = next(m for m in c.get("/api/me/payment-methods", headers=U).json() if m["pay_type"] == "credit_card")
        p = c.post("/api/kiosk/pair", headers=K1).json()
        assert p["qr_payload"].startswith("UNIORDER:PAIR:")
        assert c.get(f"/api/kiosk/pair/{p['code']}", headers=K1).json()["status"] == "waiting"
        # 다른 가게 키오스크로는 상태 조회 불가
        assert c.get(f"/api/kiosk/pair/{p['code']}", headers=K2).status_code == 404
        r = c.post("/api/me/pair", headers=U, json={"qr_payload": p["qr_payload"], "method_id": card["id"]}).json()
        assert r["method"] == "신한카드" and r["token"]
        # 두 번째 손님은 같은 QR 사용 불가
        assert c.post("/api/me/pair", headers=U, json={"qr_payload": p["qr_payload"]}).status_code == 400
        st = c.get(f"/api/kiosk/pair/{p['code']}", headers=K1).json()
        assert st["status"] == "linked" and st["session"]["selected_method"]["display_name"] == "신한카드"
        assert c.get(f"/api/kiosk/pair/{p['code']}", headers=K1).json()["status"] == "used"
        # 앱은 '연결됨' → 키오스크에서 결제 계속하기 → 앱에 결제 결과
        assert c.get(f"/api/me/payment-qr/{r['token']}", headers=U).json()["result"]["type"] == "identified"
        menu = c.get("/api/kiosk/menus", headers=K1).json()[0]
        o = c.post("/api/kiosk/orders", headers=K1, json={"items": [{"menu_item_id": menu["id"]}], "order_type": "takeout"}).json()
        assert o["order_type"] == "takeout"
        pay = c.post("/api/kiosk/payments/session", headers=K1, json={"order_id": o["id"], "customer_session": st["session"]["customer_session"]}).json()
        assert pay["success"]
        assert c.get(f"/api/me/payment-qr/{r['token']}", headers=U).json()["result"]["type"] == "paid"
        # 데모 버튼 / 만료
        p2 = c.post("/api/kiosk/pair", headers=K1).json()
        assert c.post(f"/api/kiosk/pair/{p2['code']}/demo", headers=K1).status_code == 200
        assert c.get(f"/api/kiosk/pair/{p2['code']}", headers=K1).json()["status"] == "linked"
        assert c.post("/api/me/pair", headers=U, json={"qr_payload": "UNIORDER:PAIR:nope"}).status_code == 400


def test_discount_and_store_alert():
    with TestClient(app) as c:
        KR = {"X-Kiosk-Key": "rolling-kiosk-key"}
        store = c.get("/api/kiosk/store", headers=KR).json()
        assert store["discount"]["rate"] == 10 and store["discount"]["seconds_left"] > 0
        menu = c.get("/api/kiosk/menus", headers=KR).json()[0]
        o = c.post("/api/kiosk/orders", headers=KR, json={"items": [{"menu_item_id": menu["id"], "quantity": 2}]}).json()
        full = menu["price"] * 2
        assert o["discount_amount"] == (full * 10 // 100) // 10 * 10 and o["total_amount"] == full - o["discount_amount"]
        # 지도에도 할인 표시
        pins = c.get("/api/map/stores").json()
        assert next(p for p in pins if p["id"] == store["id"])["discount"]["rate"] == 10

        tok = c.post("/api/auth/login", json={"email": "user@demo.com", "password": "1234"}).json()["access_token"]
        U = {"Authorization": f"Bearer {tok}"}
        assert c.put(f"/api/me/store-alerts/{store['id']}", headers=U, json={"on": True}).json()["on"]
        assert c.get(f"/api/map/stores/{store['id']}", headers=U).json()["for_me"]["alert_on"]
        assert [a["store_id"] for a in c.get("/api/me/store-alerts", headers=U).json()] == [store["id"]]
        c.put(f"/api/me/store-alerts/{store['id']}", headers=U, json={"on": False})
        assert c.get("/api/me/store-alerts", headers=U).json() == []
        # 사장님이 할인 종료
        otok = c.post("/api/auth/login", json={"email": "owner@demo.com", "password": "1234"}).json()["access_token"]
        r = c.patch(f"/api/owner/stores/{store['id']}", headers={"Authorization": f"Bearer {otok}"}, json={"discount_rate": 0})
        assert r.status_code == 200 and r.json()["discount"] is None


def test_reset_db_starts_empty(monkeypatch, tmp_path):
    """reset_db: 기록 0건, 기본 데이터만."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app import config, seed as seed_mod
    from app.database import Base
    from app.models import ChatLog, Kiosk, MenuItem, Order, PointWallet, Store, User
    eng = create_engine(f"sqlite:///{tmp_path / 'e.db'}")
    Base.metadata.create_all(eng)
    monkeypatch.setattr(config.settings, "SEED_HISTORY", False)
    with sessionmaker(bind=eng)() as db:
        seed_mod.seed(db)
        assert db.query(Order).count() == 0 and db.query(ChatLog).count() == 0 and db.query(PointWallet).count() == 0
        assert db.query(Store).count() >= 3 and db.query(MenuItem).count() > 10 and db.query(Kiosk).count() == 3
        assert db.query(User).filter_by(email="user@demo.com").first() is not None
