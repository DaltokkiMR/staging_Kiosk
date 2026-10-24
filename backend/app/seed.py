"""데모 데이터. 서버 시작 시 DB가 비어 있으면 자동으로 넣습니다.

  사장님 : owner@demo.com / 1234   (도도식당, 도도분식)
  손님   : user@demo.com  / 1234   (김민지 — 평일 점심 한식, 저녁 분식, 주말 카페 패턴)
  키오스크 X-Kiosk-Key : demo-kiosk-key

지도 데모 위치: 서울 마포구 망원동 일대 (중심 37.5555, 126.9100)
"""
import random
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .config import settings
from .models import (
    ChatLog, Kiosk, MenuItem, MenuOption, Order, OrderItem, OrderStatus, Payment,
    PaymentMethod, PayType, PointTransaction, PointWallet, Role, Store, User,
)
from .security import hash_password

MAP_CENTER = (37.5555, 126.9100)
ALL_PAY = [p.value for p in PayType]

# (이름, 분류, 위도, 경도, 영업시작, 영업끝, 휴무요일, 한줄소개, 적립률, 메뉴들)
# 메뉴: (이름, 가격, 분류, 맵기, 단맛, 설명, 태그, 알레르기)
EXTRA_STORES = [
    ("망원 스시하루", "일식", 37.5571, 126.9068, "11:30", "21:30", [0], "숙성회로 만드는 동네 초밥집", 0.03, [
        ("모둠초밥", 15000, "초밥", 0, 1, "제철 생선 12피스", ["인기"], ["생선"]),
        ("연어덮밥", 12000, "덮밥", 0, 1, "생연어와 간장 소스", [], ["생선", "대두"]),
        ("매운 참치비빔", 13000, "덮밥", 3, 1, "참치와 고추장 소스", [], ["생선", "대두"]),
    ]),
    ("홍춘루", "중식", 37.5538, 126.9131, "11:00", "21:00", [], "40년 된 동네 중국집", 0.02, [
        ("짜장면", 7000, "면", 0, 3, "춘장 듬뿍 옛날 짜장", ["인기"], ["밀", "대두"]),
        ("짬뽕", 9000, "면", 4, 0, "불맛 나는 해물 짬뽕", [], ["밀", "갑각류"]),
        ("탕수육", 18000, "요리", 0, 4, "바삭한 찹쌀 탕수육", [], ["밀", "돼지고기"]),
    ]),
    ("카페 소담", "카페", 37.5562, 126.9125, "09:00", "22:00", [], "창가 자리가 예쁜 디저트 카페", 0.05, [
        ("아메리카노", 4500, "커피", 0, 0, "고소한 블렌드", [], []),
        ("바닐라라떼", 5500, "커피", 0, 4, "직접 만든 바닐라 시럽", [], ["우유"]),
        ("말차 케이크", 6500, "디저트", 0, 3, "진한 말차 생크림", ["인기"], ["밀", "우유", "계란"]),
    ]),
    ("그린볼", "샐러드", 37.5544, 126.9080, "10:00", "20:00", [6], "든든한 한 끼 샐러드", 0.04, [
        ("닭가슴살 샐러드", 9500, "샐러드", 0, 1, "수비드 닭가슴살", ["건강"], []),
        ("두부 포케", 9000, "포케", 1, 1, "구운 두부와 현미밥", ["채식", "비건"], ["대두"]),
    ]),
    ("화덕 파스타", "양식", 37.5580, 126.9110, "11:30", "22:00", [], "화덕 피자와 생면 파스타", 0.03, [
        ("마르게리타 피자", 16000, "피자", 0, 1, "토마토·모짜렐라·바질", ["인기"], ["밀", "우유"]),
        ("까르보나라", 14000, "파스타", 0, 1, "관찰레와 페코리노", [], ["밀", "계란", "우유", "돼지고기"]),
        ("아라비아따", 13000, "파스타", 3, 0, "매콤한 토마토 파스타", [], ["밀"]),
    ]),
    ("망원 고깃집", "고기", 37.5528, 126.9100, "16:00", "23:00", [], "숯불에 굽는 삼겹살", 0.03, [
        ("삼겹살", 16000, "고기", 0, 0, "1인분 180g", ["인기"], ["돼지고기"]),
        ("양념갈비", 18000, "고기", 1, 3, "달콤 간장 양념", [], ["돼지고기", "대두"]),
        ("김치찌개", 8000, "식사", 3, 0, "고기 넣은 김치찌개", [], ["돼지고기"]),
    ]),
    ("심야포차 달", "주점", 37.5551, 126.9142, "18:00", "02:00", [0], "새벽까지 하는 동네 포차", 0.03, [
        ("닭발", 17000, "안주", 5, 1, "불맛 무뼈 닭발", [], []),
        ("계란찜", 6000, "안주", 0, 0, "폭탄 계란찜", [], ["계란"]),
        ("어묵탕", 13000, "안주", 1, 0, "따끈한 국물", [], ["생선", "밀"]),
    ]),
]


def _menu(db, store, name, price, cat, spicy, sweet, desc="", tags=(), allergens=(), options=(), name_en="", image=""):
    m = MenuItem(store_id=store.id, name=name, name_en=name_en, image_url=image, price=price, category=cat,
                 spicy_level=spicy, sweetness=sweet, description=desc, tags=list(tags), allergens=list(allergens))
    m.options = [MenuOption(group=g, name=n, extra_price=p) for g, n, p in options]
    db.add(m)
    return m


IMG = "/kiosk/img/menu/"
# 피그마 시안의 RollingPasta 메뉴판 (이름, 영문, 가격, 맵기, 단맛, 설명, 태그, 알레르기, 이미지)
ROLLING_PASTA = [
    ("버터 갈릭 파스타", "Butter Garlic Pasta", 10000, 0, 1, "버터와 마늘의 고소한 풍미를 그대로! 한 번 맛보면 자꾸 생각나는 매력적인 파스타", [], ["밀", "우유"], "butter_garlic"),
    ("치즈 듬뿍 오븐 파스타", "Oven-baked Pasta", 12000, 1, 1, "진한 비프 토마토 소스에 고소한 치즈를 듬뿍 올려 오븐에 구워낸 겉바속촉 오븐파스타", [], ["밀", "우유", "소고기"], "oven_baked"),
    ("씨푸드 오일 파스타", "Seafood Oil Pasta", 11000, 1, 0, "새우, 오징어, 바지락 등 다양한 해물에 비법 소스를 넣어 감칠맛을 더한 오일 파스타", [], ["밀", "갑각류", "조개"], "seafood_oil"),
    ("토마토 미트 파스타", "Tomato Meat Pasta", 9900, 1, 2, "깊은 감칠맛의 토마토소스와 다진 소고기가 어우러진 클래식 미트 파스타", [], ["밀", "소고기"], "tomato_meat"),
    ("매운 우삼겹 오일 파스타", "Spicy Usamgyeop Oil Pasta", 12000, 4, 0, "매콤한 오일 소스에 우삼겹의 고소한 풍미를 더한 파스타", ["매콤"], ["밀", "소고기"], "spicy_usamgyeop_oil"),
    ("알리오 올리오", "Aglio E Olio", 9000, 3, 0, "올리브유에 마늘의 풍부한 향을 더하고 고추로 느끼함을 잡은 파스타", ["매콤"], ["밀"], "aglio_olio"),
    ("토마토 파스타", "Tomato Pasta", 9000, 0, 2, "그라나파다노 치즈를 듬뿍 갈아 올린 베이직 토마토 파스타", [], ["밀", "우유"], "tomato"),
    ("스테이크 크림 파스타", "Steak Cream Pasta", 13000, 3, 1, "데미소스가 뿌려진 고소한 크림 파스타에 큐브 스테이크를 올린 파스타", ["매콤"], ["밀", "우유", "소고기"], "steak_cream"),
    ("해물 크림 파스타", "Seafood Cream Pasta", 10000, 0, 1, "새우, 오징어, 바지락 등의 해물을 넣어 크림 소스에 깊은 맛을 더한 파스타", [], ["밀", "우유", "갑각류", "조개"], "seafood_cream"),
    ("매운 크림 파스타", "Spicy Cream Pasta", 11000, 3, 1, "매운크림에 우삼겹의 진한 육즙이 어우러져 더욱 풍부한 맛의 파스타", ["매콤"], ["밀", "우유", "소고기"], "spicy_cream"),
    ("로제 크림 쉬림프 파스타", "Rose Cream Shrimp Pasta", 12000, 1, 2, "부드러운 로제 크림에 새우를 넣어 풍미가 일품인 파스타", ["BEST", "인기"], ["밀", "우유", "갑각류"], "rose_shrimp"),
    ("까르보나라", "Carbonara", 11000, 0, 1, "고소하고 부드러운 크림에 베이컨으로 풍미를 살린 크림 파스타", [], ["밀", "우유", "계란", "돼지고기"], "carbonara"),
]
ROLLING_SIDES = [  # (분류, 이름, 영문, 가격, 맵기, 단맛, 설명, 알레르기, 이미지)
    ("에피타이저", "갈릭 브레드", "Garlic Bread", 4000, 0, 1, "버터와 마늘을 발라 구운 바게트", ["밀", "우유"], "/kiosk/img/cat-appetizer.png"),
    ("에피타이저", "시저 샐러드", "Caesar Salad", 7000, 0, 1, "로메인과 파마산, 크루통", ["밀", "우유", "계란"], "/kiosk/img/cat-appetizer.png"),
    ("음료", "아이스티", "Iced Tea", 3000, 0, 4, "복숭아 아이스티", [], "/kiosk/img/iced-tea.png"),
    ("음료", "콜라", "Coke", 2500, 0, 4, "", [], "/kiosk/img/cat-drink.png"),
    ("음료", "레몬에이드", "Lemonade", 4500, 0, 3, "생레몬 에이드", [], "/kiosk/img/cat-drink.png"),
    ("디저트", "딸기 케이크", "Strawberry Cake", 6500, 0, 4, "생딸기 생크림 케이크", ["밀", "우유", "계란"], "/kiosk/img/cat-dessert.png"),
    ("디저트", "티라미수", "Tiramisu", 6000, 0, 3, "마스카포네 티라미수", ["밀", "우유", "계란"], "/kiosk/img/cat-dessert.png"),
]


def _order(db, store, menus_qty, t, user=None, pay=PayType.CREDIT_CARD, status=OrderStatus.SERVED):
    o = Order(store_id=store.id, user_id=user.id if user else None, status=status.value, created_at=t, paid_at=t)
    o.items = [OrderItem(menu_item_id=m.id, name=m.name, unit_price=m.price, quantity=q, options=[]) for m, q in menus_qty]
    o.total_amount = sum(m.price * q for m, q in menus_qty)
    db.add(o)
    db.flush()
    db.add(Payment(order_id=o.id, user_id=user.id if user else None, pay_type=pay.value, amount=o.total_amount,
                   status="approved", approval_no=f"SEED-{o.id}", created_at=t))
    if user:
        w = db.query(PointWallet).filter_by(user_id=user.id, store_id=store.id).first()
        if w is None:
            w = PointWallet(user_id=user.id, store_id=store.id, balance=0)
            db.add(w)
            db.flush()
        earned = int(o.total_amount * store.point_rate)
        w.balance += earned
        db.add(PointTransaction(wallet_id=w.id, order_id=o.id, amount=earned, reason="earn", created_at=t))
    return o


def _at(days_ago: int, hour: int, minute: int = 0) -> datetime:
    return (datetime.now() - timedelta(days=days_ago)).replace(hour=hour, minute=minute, second=0, microsecond=0)


def _last(weekday_set: set[int], n: int, start: int = 1) -> list[int]:
    """오늘 기준 과거 날짜 중 원하는 요일(0=월)에 해당하는 days_ago n개."""
    out, d = [], start
    while len(out) < n and d < 60:
        if (datetime.now() - timedelta(days=d)).weekday() in weekday_set:
            out.append(d)
        d += 1
    return out


def add_demo_wallet(db: Session, user: User) -> None:
    """데모 결제수단: 카카오페이(잔액 5,000) → 마포사랑상품권 → 신한카드 → 온누리 순서.
    22,000원 주문 시 카카오페이 잔액부족 → 지역화폐로 넘어가는 흐름을 보여줄 수 있음."""
    db.add_all([
        PaymentMethod(user_id=user.id, pay_type=PayType.KAKAO_PAY.value, display_name="카카오페이머니", mock_balance=5000, priority=1),
        PaymentMethod(user_id=user.id, pay_type=PayType.LOCAL_CURRENCY.value, display_name="마포사랑상품권",
                      region="서울 마포구", mock_balance=30000, priority=2),
        PaymentMethod(user_id=user.id, pay_type=PayType.CREDIT_CARD.value, display_name="신한카드",
                      masked_number="****-1234", billing_key="demo-billing-key", priority=3),
        PaymentMethod(user_id=user.id, pay_type=PayType.ONNURI.value, display_name="모바일 온누리", mock_balance=20000, priority=4),
    ])


def seed(db: Session) -> None:
    if db.query(User).first():
        return
    rng = random.Random(42)
    pw = hash_password("1234")

    owner = User(email="owner@demo.com", password_hash=pw, name="김사장", role=Role.OWNER.value, preferences={})
    owner2 = User(email="owner2@demo.com", password_hash=pw, name="박사장", role=Role.OWNER.value, preferences={})
    db.add_all([owner, owner2])
    user = None
    if settings.SEED_CUSTOMER:
        user = User(email="user@demo.com", password_hash=pw, name="김민지", role=Role.CONSUMER.value,
                    preferences={"allergies": ["땅콩"]})
        db.add(user)
    db.flush()

    # ---------- 가게 ----------
    store = Store(owner_id=owner.id, name="도도식당", category="한식", region="서울 마포구",
                  address="서울 마포구 망원로 12", phone="02-321-0001", tagline="엄마 손맛 찌개 백반",
                  description="엄마 손맛 한식 백반집. 찌개와 볶음 요리가 대표 메뉴.",
                  lat=37.5556, lng=126.9095, open_time="10:30", close_time="21:00", closed_weekdays=[6],
                  supported_pay_types=ALL_PAY, point_rate=0.05)
    store2 = Store(owner_id=owner.id, name="도도분식", category="분식", region="서울 마포구",
                   address="서울 마포구 망원로 20", phone="02-321-0002", tagline="매콤달콤 즉석 떡볶이",
                   description="떡볶이·김밥 전문 분식집", lat=37.5549, lng=126.9112, open_time="11:00", close_time="22:00",
                   supported_pay_types=[p for p in ALL_PAY if p != PayType.ONNURI.value], point_rate=0.03,
                   discount_rate=15, discount_title="떡볶이 타임세일 15%", discount_until=datetime.now() + timedelta(hours=26))
    db.add_all([store, store2])
    db.flush()

    kimchi = _menu(db, store, "김치찌개", 9000, "찌개", 3, 0, "묵은지와 돼지고기를 넣은 얼큰한 찌개", ["국물", "돼지고기"], ["돼지고기"])
    _menu(db, store, "된장찌개", 8500, "찌개", 1, 0, "구수한 집된장 찌개", ["국물"], ["대두"])
    jeyuk = _menu(db, store, "제육볶음", 10000, "볶음", 3, 2, "고추장 양념 돼지고기 볶음", ["밥도둑", "돼지고기"],
                  ["돼지고기", "대두"], [("양", "곱빼기", 3000)])
    _menu(db, store, "불고기 정식", 12000, "정식", 0, 3, "달달한 간장 불고기", ["소고기"], ["소고기", "대두"])
    _menu(db, store, "계란말이", 6000, "사이드", 0, 1, "부드러운 계란말이", ["사이드"], ["계란"])
    _menu(db, store, "비빔밥", 9000, "밥", 2, 1, "제철 나물 비빔밥", ["채식"], ["대두"], [("재료", "고추장 빼기", 0)])
    tteok = _menu(db, store2, "떡볶이", 5000, "분식", 4, 3, "매콤달콤 국물 떡볶이", ["인기"], ["밀"])
    _menu(db, store2, "로제떡볶이", 6500, "분식", 2, 3, "크림 로제 떡볶이", ["인기"], ["밀", "우유"])
    gimbap = _menu(db, store2, "참치김밥", 4000, "김밥", 0, 0, "참치마요 김밥", [], ["생선", "계란"])

    extra: dict[str, Store] = {}
    for name, cat, lat, lng, o, c, closed, tag, rate, menus in EXTRA_STORES:
        s = Store(owner_id=owner2.id, name=name, category=cat, region="서울 마포구", address=f"서울 마포구 망원동 {rng.randint(100, 499)}",
                  phone=f"02-33{rng.randint(0, 9)}-{rng.randint(1000, 9999)}", tagline=tag, description=tag,
                  lat=lat, lng=lng, open_time=o, close_time=c, closed_weekdays=closed,
                  supported_pay_types=ALL_PAY, point_rate=rate)
        db.add(s)
        db.flush()
        for mn in menus:
            _menu(db, s, *mn)
        extra[name] = s
    db.flush()

    # ---------- 롤링파스타 (피그마 시연 매장) ----------
    rolling = Store(owner_id=owner.id, name="RollingPasta", category="양식", region="서울 마포구",
                    address="서울 마포구 망원로 30", phone="02-321-0030", tagline="매일 생면으로 만드는 파스타",
                    description="롤링파스타. 오일·토마토·크림 파스타 전문점. 매콤 메뉴와 로제 크림 쉬림프가 인기.",
                    lat=37.5561, lng=126.9104, open_time="11:00", close_time="22:00",
                    supported_pay_types=ALL_PAY, point_rate=0.05,
                    discount_rate=10, discount_title="오픈 기념 전 메뉴 10% 할인",
                    discount_until=(datetime.now() + timedelta(days=2)).replace(hour=22, minute=0, second=0, microsecond=0))
    db.add(rolling)
    db.flush()
    rp = {}
    for name, en, price, sp, sw, desc, tags, alg, img in ROLLING_PASTA:
        rp[name] = _menu(db, rolling, name, price, "메뉴", sp, sw, desc, tags, alg, [("추가", "면 추가", 2000)],
                         name_en=en, image=IMG + img + ".png")
    for cat, name, en, price, sp, sw, desc, alg, img in ROLLING_SIDES:
        rp[name] = _menu(db, rolling, name, price, cat, sp, sw, desc, [], alg, name_en=en, image=img)
    db.add(Kiosk(store_id=rolling.id, name="롤링파스타 3번 테이블", table_no="3", api_key="rolling-kiosk-key"))
    db.flush()

    db.add(Kiosk(store_id=store.id, name="1번 테이블", table_no="1", api_key="demo-kiosk-key"))
    db.add(Kiosk(store_id=store2.id, name="분식 키오스크", api_key="demo-kiosk-key-2"))

    if user:
        add_demo_wallet(db, user)

    if not settings.SEED_HISTORY or user is None:
        # 기록 없이 시작: 매출·주문·대화·포인트가 하나도 없는 상태
        db.commit()
        return

    # ---------- 데모 손님(김민지) 행동 패턴 ----------
    # 평일 점심: 도도식당 김치찌개 단골 → "늘 드시던 김치찌개로 드릴까요?"
    for i, d in enumerate(_last({0, 1, 2, 3, 4}, 4, start=2)):
        _order(db, store, [(kimchi, 1)] + ([(jeyuk, 1)] if i == 1 else []), _at(d, 12, 20), user)
    # 평일 저녁: 도도분식
    for d in _last({1, 3}, 2, start=1):
        _order(db, store2, [(tteok, 1), (gimbap, 1)], _at(d, 19, 10), user, PayType.KAKAO_PAY)
    # 주말 오후: 카페 소담
    cafe = extra["카페 소담"]
    for d in _last({5, 6}, 2, start=1):
        _order(db, cafe, [(cafe.menus[1], 1), (cafe.menus[2], 1)], _at(d, 15, 30), user, PayType.NAVER_PAY)

    # 김민지가 가게별로 키오스크 AI와 나눴던 대화 (가게마다 따로 기억)
    for d, sid, st, q in [(9, "m1", store, "김치찌개 좀 덜 맵게 되나요?"), (9, "m1", store, "땅콩 들어간 메뉴 있어요?"),
                          (4, "m2", store2, "로제떡볶이 많이 달아요?")]:
        db.add(ChatLog(store_id=st.id, user_id=user.id, session_id=f"seed-{sid}", role="user", content=q,
                       unmet_requests=["맵기 조절"] if "덜 맵게" in q else [], created_at=_at(d, 12, 15)))

    # 김민지의 롤링파스타 기록: 주말 점심 2번 + "덜 맵게" 물어봤던 대화 (가게별 기억)
    for d, items in zip(_last({5, 6}, 2, start=6), [[(rp["토마토 미트 파스타"], 1), (rp["아이스티"], 1)],
                                                   [(rp["토마토 미트 파스타"], 1), (rp["로제 크림 쉬림프 파스타"], 1)]]):
        _order(db, rolling, items, _at(d, 12, 40), user, PayType.CREDIT_CARD)
    for q in ["알리오 올리오 많이 매워요?", "덜 맵게 해주실 수 있어요?"]:
        db.add(ChatLog(store_id=rolling.id, user_id=user.id, session_id="seed-rp-m", role="user", content=q,
                       unmet_requests=["맵기 조절"] if "덜 맵게" in q else [], created_at=_at(_last({5, 6}, 1, start=6)[0], 12, 35)))

    # ---------- 다른 손님들 (비슷한 손님 추천용) ----------
    # 도도식당 단골들은 스시하루·고깃집도 자주 감 → 김민지에게 "비슷한 손님들이 자주 가는 곳"
    others = []
    for i, nm in enumerate(["이서준", "박지우", "최예린", "정하준", "강수아", "윤도윤"]):
        u = User(email=f"guest{i + 1}@demo.com", password_hash=pw, name=nm, role=Role.CONSUMER.value, preferences={})
        db.add(u)
        others.append(u)
    db.flush()
    pattern = {0: ["도도식당", "망원 스시하루", "망원 고깃집"], 1: ["도도식당", "망원 스시하루"],
               2: ["도도식당", "망원 고깃집", "심야포차 달"], 3: ["도도분식", "카페 소담", "화덕 파스타"],
               4: ["그린볼", "카페 소담"], 5: ["홍춘루", "도도분식"]}
    by_name = {"도도식당": store, "도도분식": store2, "RollingPasta": rolling, **extra}
    for i, u in enumerate(others):
        for sname in pattern[i]:
            s = by_name[sname]
            for _ in range(rng.randint(2, 4)):
                hour = {"도도식당": 12, "망원 고깃집": 19, "심야포차 달": 22, "카페 소담": 15}.get(sname, rng.choice([12, 18]))
                _order(db, s, [(rng.choice(s.menus), 1)], _at(rng.randint(1, 25), hour, rng.randint(0, 59)), u,
                       rng.choice([PayType.CREDIT_CARD, PayType.KAKAO_PAY, PayType.LOCAL_CURRENCY]))

    # ---------- 최근 2주 비회원 매출 (사장님 대시보드·인기도) ----------
    pay_mix = [PayType.CREDIT_CARD, PayType.CHECK_CARD, PayType.KAKAO_PAY, PayType.NAVER_PAY,
               PayType.SAMSUNG_PAY, PayType.LOCAL_CURRENCY, PayType.ONNURI]
    volume = {"RollingPasta": (8, 16), "도도식당": (6, 14), "도도분식": (3, 8), "망원 스시하루": (4, 9), "홍춘루": (3, 7), "카페 소담": (8, 15),
              "그린볼": (2, 5), "화덕 파스타": (3, 7), "망원 고깃집": (4, 8), "심야포차 달": (2, 6)}
    for sname, s in by_name.items():
        a, b = volume[sname]
        open_h, close_h = int(s.open_time[:2]), int(s.close_time[:2]) or 24
        if close_h <= open_h:
            close_h += 24
        hours = list(range(open_h, close_h))
        for day in range(14):
            for _ in range(rng.randint(a, b)):
                t = _at(day, rng.choice(hours) % 24, rng.randint(0, 59))
                if t > datetime.now() or t.weekday() in (s.closed_weekdays or []):
                    continue
                picks = rng.sample(s.menus, k=min(len(s.menus), rng.randint(1, 3)))
                _order(db, s, [(m, rng.randint(1, 2)) for m in picks], t, None, rng.choice(pay_mix))

    # ---------- 키오스크 대화 기록 (사장님 AI 인사이트) ----------
    for i, q in enumerate(["알리오 올리오 덜 맵게 되나요?", "매운 크림 파스타 맵기 조절 돼요?", "포장 되나요?",
                           "면 추가는 얼마예요?", "아이가 먹을 안 매운 파스타 있어요?", "스테이크 크림 덜 맵게 가능해요?"]):
        db.add(ChatLog(store_id=rolling.id, session_id=f"seed-rp-{i}", role="user", content=q,
                       unmet_requests=[r for r, k in [("맵기 조절", "맵"), ("포장", "포장"), ("아이용 메뉴", "아이")] if k in q],
                       created_at=datetime.now() - timedelta(days=i)))
    for i, q in enumerate(["김치찌개 맵기 조절 되나요?", "덜 맵게 해주실 수 있어요?", "아이가 먹을 건데 김치찌개 안 맵게 가능해요?",
                           "제육 덜 맵게 되나요?", "포장 되나요?", "땅콩 들어간 메뉴 있어요?"]):
        db.add(ChatLog(store_id=store.id, session_id=f"seed-{i}", role="user", content=q,
                       unmet_requests=[r for r, k in [("맵기 조절", "맵"), ("포장", "포장"), ("아이용 메뉴", "아이")] if k in q],
                       created_at=datetime.now() - timedelta(days=i)))
    db.commit()
