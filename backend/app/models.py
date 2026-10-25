"""DB 모델."""
from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def now() -> datetime:
    return datetime.now()


class Role(str, Enum):
    OWNER = "owner"
    CONSUMER = "consumer"


class PayType(str, Enum):
    CREDIT_CARD = "credit_card"        # 신용카드
    CHECK_CARD = "check_card"          # 체크카드
    SAMSUNG_PAY = "samsung_pay"        # 삼성페이
    NAVER_PAY = "naver_pay"            # 네이버페이
    KAKAO_PAY = "kakao_pay"            # 카카오페이
    LOCAL_CURRENCY = "local_currency"  # 지역화폐
    ONNURI = "onnuri"                  # 온누리상품권
    DODO_POINT = "dodo_point"          # 가게 전용 포인트


PAY_TYPE_LABELS = {
    PayType.CREDIT_CARD: "신용카드",
    PayType.CHECK_CARD: "체크카드",
    PayType.SAMSUNG_PAY: "삼성페이",
    PayType.NAVER_PAY: "네이버페이",
    PayType.KAKAO_PAY: "카카오페이",
    PayType.LOCAL_CURRENCY: "지역화폐",
    PayType.ONNURI: "온누리상품권",
    PayType.DODO_POINT: "포인트",
}


class OrderStatus(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    SERVED = "served"
    CANCELLED = "cancelled"


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), default=Role.CONSUMER.value)
    birthdate: Mapped[str | None] = mapped_column(String(10), nullable=True)  # YYYY-MM-DD
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 소비자 입맛 설정 (선택)
    # 얼마나 잘 먹는지 0~5: spicy, salty, sour, sweet, oily / 직접 쓴 글: likes_text, dislikes_text, notes
    # 고른 것: allergies, diet / 글에서 뽑은 재료: likes, dislikes
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Store(Base):
    __tablename__ = "stores"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(50), default="")
    address: Mapped[str] = mapped_column(String(255), default="")
    region: Mapped[str] = mapped_column(String(50), default="")  # 지역화폐 사용 가능 지역 판단용
    supported_pay_types: Mapped[list] = mapped_column(JSON, default=lambda: [p.value for p in PayType])
    point_rate: Mapped[float] = mapped_column(Float, default=0.03)  # 결제금액 대비 포인트 적립률
    # 지도 표시용
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    phone: Mapped[str] = mapped_column(String(30), default="")
    tagline: Mapped[str] = mapped_column(String(100), default="")  # 지도 핀에 보일 한 줄 소개
    # 매장 안내: 유아 의자·앞접시·주차·와이파이 등. 키오스크 AI 직원이 손님 질문에 답할 때 참고
    notice: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str] = mapped_column(String(500), default="")
    open_time: Mapped[str] = mapped_column(String(5), default="10:00")   # "HH:MM"
    close_time: Mapped[str] = mapped_column(String(5), default="21:00")  # 자정 넘기면 "02:00" 처럼
    closed_weekdays: Mapped[list] = mapped_column(JSON, default=list)    # 0=월 ... 6=일
    # 할인 행사 (사장님이 설정). 기간 안이면 주문 합계에서 rate% 할인
    discount_rate: Mapped[int] = mapped_column(Integer, default=0)
    discount_title: Mapped[str] = mapped_column(String(60), default="")
    discount_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    @property
    def discount(self) -> dict | None:
        """지금 진행 중인 할인 (없으면 None)."""
        if self.discount_rate > 0 and self.discount_until and self.discount_until > now():
            return {"rate": self.discount_rate, "title": self.discount_title or f"{self.discount_rate}% 할인",
                    "until": self.discount_until.isoformat(),
                    "seconds_left": int((self.discount_until - now()).total_seconds())}
        return None

    menus: Mapped[list["MenuItem"]] = relationship(back_populates="store", cascade="all, delete-orphan")
    kiosks: Mapped[list["Kiosk"]] = relationship(back_populates="store", cascade="all, delete-orphan")


class Kiosk(Base):
    """키오스크/테이블오더 기기. X-Kiosk-Key 헤더로 인증."""
    __tablename__ = "kiosks"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    name: Mapped[str] = mapped_column(String(100))
    table_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
    api_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    store: Mapped[Store] = relationship(back_populates="kiosks")


class MenuItem(Base):
    __tablename__ = "menu_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    name_en: Mapped[str] = mapped_column(String(100), default="")  # 키오스크 English 모드
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(50), default="")
    price: Mapped[int] = mapped_column(Integer)
    spicy_level: Mapped[int] = mapped_column(Integer, default=0)  # 0(안매움)~5(아주매움)
    sweetness: Mapped[int] = mapped_column(Integer, default=0)    # 0~5
    tags: Mapped[list] = mapped_column(JSON, default=list)
    allergens: Mapped[list] = mapped_column(JSON, default=list)
    image_url: Mapped[str] = mapped_column(String(500), default="")
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)

    store: Mapped[Store] = relationship(back_populates="menus")
    options: Mapped[list["MenuOption"]] = relationship(back_populates="menu_item", cascade="all, delete-orphan")


class MenuOption(Base):
    """예: group='맵기', name='덜 맵게', extra_price=0"""
    __tablename__ = "menu_options"
    id: Mapped[int] = mapped_column(primary_key=True)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"), index=True)
    group: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(50))
    extra_price: Mapped[int] = mapped_column(Integer, default=0)
    menu_item: Mapped[MenuItem] = relationship(back_populates="options")


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    kiosk_id: Mapped[int | None] = mapped_column(ForeignKey("kiosks.id"), nullable=True)
    table_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
    order_type: Mapped[str] = mapped_column(String(20), default="dine_in")  # dine_in(매장) / takeout(포장)
    status: Mapped[str] = mapped_column(String(20), default=OrderStatus.PENDING.value)
    total_amount: Mapped[int] = mapped_column(Integer, default=0)
    discount_amount: Mapped[int] = mapped_column(Integer, default=0)  # 할인 행사로 빠진 금액 (total_amount는 할인 후)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    payments: Mapped[list["Payment"]] = relationship(back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"))
    name: Mapped[str] = mapped_column(String(100))
    unit_price: Mapped[int] = mapped_column(Integer)  # 옵션 추가금 포함
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    options: Mapped[list] = mapped_column(JSON, default=list)  # [{"group","name","extra_price"}]
    order: Mapped[Order] = relationship(back_populates="items")


class PaymentMethod(Base):
    """소비자가 앱에 등록한 결제수단. priority 가 낮을수록 먼저 시도."""
    __tablename__ = "payment_methods"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    pay_type: Mapped[str] = mapped_column(String(30))
    display_name: Mapped[str] = mapped_column(String(100))
    masked_number: Mapped[str] = mapped_column(String(30), default="")
    # 실제 서비스에서는 PG사 빌링키 등 토큰만 저장 (카드번호 원문 저장 금지)
    billing_key: Mapped[str] = mapped_column(String(255), default="")
    region: Mapped[str] = mapped_column(String(50), default="")  # 지역화폐 발행 지역
    mock_balance: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 데모용 잔액(상품권/페이머니)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class PaymentQRToken(Base):
    """소비자 앱이 띄우는 결제 QR. 짧은 유효시간 + 1회용."""
    __tablename__ = "payment_qr_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    method_id: Mapped[int | None] = mapped_column(ForeignKey("payment_methods.id"), nullable=True)
    use_points: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 앱에서 결제 결과 확인용


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    method_id: Mapped[int | None] = mapped_column(ForeignKey("payment_methods.id"), nullable=True)
    pay_type: Mapped[str] = mapped_column(String(30))
    amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))  # approved / failed / cancelled
    approval_no: Mapped[str] = mapped_column(String(64), default="")
    message: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    order: Mapped[Order] = relationship(back_populates="payments")


class PointWallet(Base):
    """포인트: 가게별로 따로 적립되고 그 가게에서만 사용 가능."""
    __tablename__ = "point_wallets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)


class PointTransaction(Base):
    __tablename__ = "point_transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("point_wallets.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    amount: Mapped[int] = mapped_column(Integer)  # +적립 / -사용
    reason: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ChatLog(Base):
    """키오스크 AI 대화 기록. 사장님 인사이트 분석의 원천 데이터."""
    __tablename__ = "chat_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    # 손님이 원했지만 가게에 없는 것 (예: "맵기 조절") — AI가 추출
    unmet_requests: Mapped[list] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)  # assistant: 추천한 메뉴 id 등 ("그걸로 주세요" 처리용)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class KioskPairing(Base):
    """키오스크 화면에 띄운 QR을 손님 앱이 찍어서 연결 (카메라 없는 테이블오더용)."""
    __tablename__ = "kiosk_pairings"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kiosk_id: Mapped[int] = mapped_column(ForeignKey("kiosks.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    method_id: Mapped[int | None] = mapped_column(ForeignKey("payment_methods.id"), nullable=True)
    use_points: Mapped[bool] = mapped_column(Boolean, default=True)
    qr_token: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 앱이 결제 결과를 받아볼 토큰
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
