"""통합 결제 로직: 결제 QR 발급 → 키오스크 스캔 → 우선순위대로 결제 시도."""
import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    PAY_TYPE_LABELS,
    Order,
    OrderStatus,
    Payment,
    PaymentMethod,
    PaymentQRToken,
    PayType,
    PointTransaction,
    PointWallet,
    Store,
    User,
)
from .payment_gateways import get_gateway

QR_PREFIX = "STGPAY:"  # QR 문자열 형식: "STGPAY:<token>"


# ---------- 결제수단 ----------
def ordered_methods(db: Session, user_id: int) -> list[PaymentMethod]:
    return (
        db.query(PaymentMethod)
        .filter(PaymentMethod.user_id == user_id, PaymentMethod.is_active.is_(True))
        .order_by(PaymentMethod.priority, PaymentMethod.id)
        .all()
    )


# ---------- 유니 포인트 ----------
def get_wallet(db: Session, user_id: int, store_id: int, create: bool = True) -> PointWallet | None:
    wallet = db.query(PointWallet).filter_by(user_id=user_id, store_id=store_id).first()
    if wallet is None and create:
        wallet = PointWallet(user_id=user_id, store_id=store_id, balance=0)
        db.add(wallet)
        db.flush()
    return wallet


def change_points(db: Session, wallet: PointWallet, amount: int, reason: str, order_id: int | None) -> None:
    wallet.balance += amount
    db.add(PointTransaction(wallet_id=wallet.id, order_id=order_id, amount=amount, reason=reason))


# ---------- QR ----------
def issue_qr_token(db: Session, user: User, method_id: int | None, use_points: bool) -> PaymentQRToken:
    if method_id is not None:
        m = db.get(PaymentMethod, method_id)
        if m is None or m.user_id != user.id or not m.is_active:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "결제수단을 찾을 수 없습니다.")
    token = PaymentQRToken(
        token=secrets.token_urlsafe(24),
        user_id=user.id,
        method_id=method_id,
        use_points=use_points,
        expires_at=datetime.now() + timedelta(seconds=settings.PAYMENT_QR_TTL_SECONDS),
    )
    db.add(token)
    db.commit()
    return token


def resolve_qr(db: Session, qr_payload: str) -> PaymentQRToken:
    raw = qr_payload.strip()
    if raw.startswith(QR_PREFIX):
        raw = raw[len(QR_PREFIX):]
    token = db.query(PaymentQRToken).filter_by(token=raw).first()
    if token is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "인식할 수 없는 QR 코드입니다.")
    if token.used_at is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "이미 사용된 QR 코드입니다. 앱에서 새로 열어주세요.")
    if token.expires_at < datetime.now():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "QR 코드 유효시간이 지났습니다. 앱에서 새로 열어주세요.")
    return token


# ---------- 결제 실행 ----------
def _check_pending(order: Order) -> None:
    if order.status != OrderStatus.PENDING.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "결제 대기 중인 주문이 아닙니다.")


def pay_order(db: Session, order: Order, store: Store, user_id: int, method_id: int | None,
              use_points: bool = True, token: PaymentQRToken | None = None) -> dict:
    """손님의 등록 결제수단으로 결제. method_id 가 있으면 그 카드만, 없으면 우선순위대로.
    token 이 있으면 손님 앱이 결과를 볼 수 있게 token.result 에 기록."""
    _check_pending(order)
    order.user_id = order.user_id or user_id
    if token is not None:
        token.order_id = order.id

    remaining = order.total_amount
    attempts: list[dict] = []
    approved: list[Payment] = []
    points_used = 0
    supported = set(store.supported_pay_types or [])

    # 1) 유니 포인트 우선 차감 (가게 전용 포인트)
    wallet = get_wallet(db, user_id, store.id)
    if use_points and method_id is None and PayType.DODO_POINT.value in supported and wallet.balance > 0:
        points_used = min(wallet.balance, remaining)
        remaining -= points_used
        attempts.append({"pay_type": PayType.DODO_POINT.value, "label": "유니 포인트", "amount": points_used,
                         "success": True, "message": f"{points_used:,}P 사용"})

    # 2) 남은 금액은 (지정 카드 또는) 우선순위 순서대로 시도
    if method_id is not None:
        m = db.get(PaymentMethod, method_id)
        if m is None or m.user_id != user_id or not m.is_active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "사용할 수 없는 결제수단입니다.")
        candidates = [m]
    else:
        candidates = ordered_methods(db, user_id)

    if remaining > 0:
        for method in candidates:
            label = f"{method.display_name}({PAY_TYPE_LABELS.get(PayType(method.pay_type), method.pay_type)})"
            if method.pay_type == PayType.DODO_POINT.value:
                continue  # 포인트는 결제수단 목록이 아닌 지갑에서 처리
            if method.pay_type not in supported:
                attempts.append({"method_id": method.id, "pay_type": method.pay_type, "label": label,
                                 "amount": remaining, "success": False, "message": "이 가게에서 지원하지 않는 결제수단"})
                continue
            result = get_gateway(method.pay_type).charge(method, remaining, store, order.id)
            payment = Payment(order_id=order.id, user_id=user_id, method_id=method.id, pay_type=method.pay_type,
                              amount=remaining, status="approved" if result.success else "failed",
                              approval_no=result.approval_no, message=result.message)
            db.add(payment)
            attempts.append({"method_id": method.id, "pay_type": method.pay_type, "label": label,
                             "amount": remaining, "success": result.success, "message": result.message})
            if result.success:
                approved.append(payment)
                remaining = 0
                break

    if remaining > 0:
        # 실패: 포인트 차감은 반영하지 않음. 실패 기록만 커밋.
        if token is not None:
            token.result = {"type": "paid", "success": False, "attempts": attempts}
        db.commit()
        return {"success": False, "order_id": order.id, "paid_amount": 0, "points_used": 0, "points_earned": 0,
                "payments": [], "attempts": attempts,
                "message": "이 결제수단으로 결제하지 못했어요. 결제카드를 바꾸거나 카드결제를 이용해주세요."}

    # 3) 성공 처리: 포인트 차감 기록, 주문 완료, 포인트 적립
    if points_used:
        change_points(db, wallet, -points_used, "use", order.id)
        p = Payment(order_id=order.id, user_id=user_id, method_id=None, pay_type=PayType.DODO_POINT.value,
                    amount=points_used, status="approved", approval_no=f"PT-{secrets.token_hex(5).upper()}",
                    message="유니 포인트 사용")
        db.add(p)
        approved.insert(0, p)

    earned = _earn(db, wallet, store, order, order.total_amount - points_used)
    _mark_paid(order)
    if token is not None:
        token.result = {"type": "paid", "success": True, "paid_amount": order.total_amount, "points_used": points_used,
                        "points_earned": earned, "attempts": attempts}
    db.commit()
    return {"success": True, "order_id": order.id, "paid_amount": order.total_amount, "points_used": points_used,
            "points_earned": earned, "payments": approved, "attempts": attempts,
            "message": f"결제 완료! 유니 포인트 {earned:,}P 적립"}


def _earn(db: Session, wallet: PointWallet | None, store: Store, order: Order, cash_paid: int) -> int:
    earned = int(cash_paid * (store.point_rate or 0))
    if earned and wallet is not None:
        change_points(db, wallet, earned, "earn", order.id)
    return earned if wallet is not None else 0


def _mark_paid(order: Order) -> None:
    order.status = OrderStatus.PAID.value
    order.paid_at = datetime.now()


def pay_order_with_qr(db: Session, order: Order, store: Store, qr_payload: str) -> dict:
    """결제 단계에서 QR을 새로 찍은 경우 (앱에서 고른 카드 그대로)."""
    _check_pending(order)
    token = resolve_qr(db, qr_payload)
    token.used_at = datetime.now()  # 1회용: 성공/실패와 관계없이 소진
    return pay_order(db, order, store, token.user_id, token.method_id, token.use_points, token)


def pay_order_with_card(db: Session, order: Order, store: Store, user_id: int | None = None) -> dict:
    """[데모] 키오스크 카드 단말기(IC/삼성페이) 결제. 실제로는 VAN/PG 단말 연동.
    앱으로 손님 확인이 된 상태면 포인트는 적립해 줌."""
    _check_pending(order)
    if user_id:
        order.user_id = order.user_id or user_id
    p = Payment(order_id=order.id, user_id=user_id, method_id=None, pay_type=PayType.CREDIT_CARD.value,
                amount=order.total_amount, status="approved", approval_no=f"IC-{secrets.token_hex(5).upper()}",
                message="카드 단말기 결제")
    db.add(p)
    wallet = get_wallet(db, user_id, store.id) if user_id else None
    earned = _earn(db, wallet, store, order, order.total_amount)
    _mark_paid(order)
    db.commit()
    attempts = [{"pay_type": PayType.CREDIT_CARD.value, "label": "카드 단말기", "amount": order.total_amount,
                 "success": True, "message": "승인"}]
    return {"success": True, "order_id": order.id, "paid_amount": order.total_amount, "points_used": 0,
            "points_earned": earned, "payments": [p], "attempts": attempts,
            "message": "결제 완료!" + (f" 유니 포인트 {earned:,}P 적립" if earned else "")}
