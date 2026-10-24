"""소비자 앱: 결제수단 관리, 결제 QR, 포인트, 주문내역, 성향/추천."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Order, PaymentMethod, PaymentQRToken, PointTransaction, PointWallet, Store, User
from ..schemas import (
    StoreAlertIn,
    MenuItemOut,
    OrderOut,
    PaymentMethodIn,
    PaymentMethodOut,
    PointWalletOut,
    PriorityIn,
    QRTokenIn,
    QRTokenOut,
    PairIn,
)
from ..security import require_consumer
from ..services import ai_service, recommend
from ..services.payment_service import QR_PREFIX, issue_qr_token, ordered_methods

router = APIRouter(prefix="/api/me", tags=["소비자 앱"])


# ---------- 결제수단 ----------
@router.get("/payment-methods", response_model=list[PaymentMethodOut])
def list_methods(user: User = Depends(require_consumer), db: Session = Depends(get_db)):
    return ordered_methods(db, user.id)


@router.post("/payment-methods", response_model=PaymentMethodOut)
def add_method(data: PaymentMethodIn, user: User = Depends(require_consumer), db: Session = Depends(get_db)):
    existing = ordered_methods(db, user.id)
    priority = data.priority if data.priority is not None else (existing[-1].priority + 1 if existing else 1)
    m = PaymentMethod(user_id=user.id, pay_type=data.pay_type.value, display_name=data.display_name,
                      masked_number=data.masked_number, billing_key=data.billing_key, region=data.region,
                      mock_balance=data.mock_balance, priority=priority)
    db.add(m)
    db.commit()
    return m


@router.delete("/payment-methods/{method_id}")
def delete_method(method_id: int, user: User = Depends(require_consumer), db: Session = Depends(get_db)):
    m = db.get(PaymentMethod, method_id)
    if m is None or m.user_id != user.id:
        raise HTTPException(404, "결제수단을 찾을 수 없습니다.")
    m.is_active = False  # 결제 기록 보존을 위해 비활성화
    db.commit()
    return {"ok": True}


@router.put("/payment-methods/priority", response_model=list[PaymentMethodOut])
def set_priority(data: PriorityIn, user: User = Depends(require_consumer), db: Session = Depends(get_db)):
    """결제 우선순위 변경. method_ids 순서대로 1, 2, 3... 이 됩니다."""
    mine = {m.id: m for m in ordered_methods(db, user.id)}
    if set(data.method_ids) - set(mine):
        raise HTTPException(400, "내 결제수단이 아닌 id가 포함되어 있습니다.")
    for i, mid in enumerate(data.method_ids, start=1):
        mine[mid].priority = i
    rest = [m for mid, m in mine.items() if mid not in data.method_ids]
    for j, m in enumerate(rest, start=len(data.method_ids) + 1):
        m.priority = j
    db.commit()
    return ordered_methods(db, user.id)


# ---------- 결제 QR ----------
@router.post("/payment-qr", response_model=QRTokenOut)
def create_payment_qr(data: QRTokenIn, user: User = Depends(require_consumer), db: Session = Depends(get_db)):
    """앱을 열면 호출 → 응답의 qr_payload 를 QR 코드로 그려서 보여주면 됩니다.
    method_id 없이: 우선순위대로 결제 / method_id 지정: 카드를 넘겨 선택한 그 카드로 결제."""
    t = issue_qr_token(db, user, data.method_id, data.use_points)
    return QRTokenOut(token=t.token, qr_payload=QR_PREFIX + t.token, expires_at=t.expires_at, method_id=t.method_id)


@router.get("/payment-qr/{token}")
def payment_qr_status(token: str, user: User = Depends(require_consumer), db: Session = Depends(get_db)):
    """앱에서 QR 화면을 띄운 동안 폴링 → 키오스크에서 결제되면 결과 표시."""
    t = db.query(PaymentQRToken).filter_by(token=token, user_id=user.id).first()
    if t is None:
        raise HTTPException(404, "QR을 찾을 수 없습니다.")
    return {"used": t.used_at is not None, "order_id": t.order_id, "result": t.result, "expires_at": t.expires_at}


# ---------- 키오스크 QR 찍기 ----------
@router.post("/pair")
def pair_with_kiosk(data: PairIn, user: User = Depends(require_consumer), db: Session = Depends(get_db)):
    """키오스크 첫 화면의 QR을 앱 카메라로 찍으면 호출. 고른 결제카드가 이번 방문 결제까지 이어짐.
    응답의 token 으로 GET /api/me/payment-qr/{token} 을 폴링하면 키오스크 결제 결과를 받을 수 있어요."""
    from .kiosk import claim_pairing
    if data.method_id is not None:
        m = db.get(PaymentMethod, data.method_id)
        if m is None or m.user_id != user.id:
            raise HTTPException(404, "결제수단을 찾을 수 없습니다.")
    return claim_pairing(db, data.qr_payload, user, data.method_id, data.use_points)


# ---------- 포인트 ----------
@router.get("/points", response_model=list[PointWalletOut])
def my_points(user: User = Depends(require_consumer), db: Session = Depends(get_db)):
    """가게별 포인트 + 그 가게에서 쓴 돈 + 최근 적립."""
    rows = db.query(PointWallet, Store).join(Store, Store.id == PointWallet.store_id).filter(
        PointWallet.user_id == user.id).all()
    out = []
    for w, s in rows:
        spent = sum(o.total_amount for o in db.query(Order).filter(
            Order.user_id == user.id, Order.store_id == s.id, Order.status.in_(["paid", "served"])))
        last = (db.query(PointTransaction).filter_by(wallet_id=w.id, reason="earn")
                .order_by(PointTransaction.id.desc()).first())
        out.append(PointWalletOut(store_id=s.id, store_name=s.name, balance=w.balance, total_spent=spent,
                                  last_earned=last.amount if last else 0))
    return sorted(out, key=lambda x: -x.total_spent)


# ---------- 주문 내역 ----------
@router.get("/orders", response_model=list[OrderOut])
def my_orders(user: User = Depends(require_consumer), db: Session = Depends(get_db)):
    return db.query(Order).filter_by(user_id=user.id).order_by(Order.id.desc()).limit(50).all()


# ---------- AI 성향/추천 ----------
@router.get("/taste-profile")
def my_taste_profile(user: User = Depends(require_consumer), db: Session = Depends(get_db)):
    return ai_service.taste_profile(db, user)


@router.get("/behavior")
def my_behavior(user: User = Depends(require_consumer), db: Session = Depends(get_db)):
    """방문 시간대·요일·주기·자주 가는 가게 등 행동 패턴 요약."""
    return recommend.behavior_profile(db, user)


@router.get("/recommendations/stores")
def recommend_stores(limit: int = 5, lat: float | None = None, lng: float | None = None,
                     user: User = Depends(require_consumer), db: Session = Depends(get_db)):
    """행동 패턴(시간대·요일·단골·비슷한 손님) + 입맛 + 거리 기반 가게 추천.
    lat/lng 를 주면 거리도 반영합니다."""
    return recommend.recommend_stores(db, user, lat, lng, limit)


@router.get("/recommendations/stores/{store_id}")
def recommend_in_store(store_id: int, user: User = Depends(require_consumer), db: Session = Depends(get_db)):
    store = db.get(Store, store_id)
    if store is None:
        raise HTTPException(404, "가게를 찾을 수 없습니다.")
    profile = ai_service.taste_profile(db, user)
    return {
        "usual_items": ai_service.usual_items(db, user.id, store.id),
        "recommended_menus": [MenuItemOut.model_validate(m) for m in ai_service.recommend_menus(store, profile, 3)],
    }


# ---------- 가게 알림 (종 버튼) ----------
@router.get("/store-alerts")
def my_store_alerts(user: User = Depends(require_consumer), db: Session = Depends(get_db)):
    """알림을 켠 가게 목록 (할인·새 메뉴 소식을 받음)."""
    ids = (user.preferences or {}).get("store_alerts", [])
    return [{"store_id": s.id, "name": s.name, "discount": s.discount} for s in db.query(Store).filter(Store.id.in_(ids))]


@router.put("/store-alerts/{store_id}")
def set_store_alert(store_id: int, data: StoreAlertIn, user: User = Depends(require_consumer), db: Session = Depends(get_db)):
    if db.get(Store, store_id) is None:
        raise HTTPException(404, "가게를 찾을 수 없습니다.")
    prefs = dict(user.preferences or {})
    ids = [i for i in prefs.get("store_alerts", []) if i != store_id]
    if data.on:
        ids.append(store_id)
    prefs["store_alerts"] = ids
    user.preferences = prefs
    db.commit()
    return {"store_id": store_id, "on": data.on, "count": len(ids)}
