"""요청/응답 스키마."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import PayType, Role


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- 인증 ----------
class SignupIn(BaseModel):
    email: str
    password: str = Field(min_length=4)
    name: str
    role: Role = Role.CONSUMER


class LoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(ORM):
    id: int
    email: str
    name: str
    role: str
    preferences: dict


class PreferencesIn(BaseModel):
    spicy: int | None = Field(None, ge=0, le=5)
    sweet: int | None = Field(None, ge=0, le=5)
    dislikes: list[str] | None = None
    allergies: list[str] | None = None


# ---------- 가게 / 메뉴 ----------
class StoreIn(BaseModel):
    name: str
    description: str = ""
    category: str = ""
    address: str = ""
    region: str = ""
    supported_pay_types: list[PayType] | None = None
    point_rate: float = Field(0.03, ge=0, le=0.5)
    lat: float | None = None
    lng: float | None = None
    phone: str | None = None
    tagline: str | None = None
    image_url: str | None = None
    open_time: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    close_time: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    closed_weekdays: list[int] | None = None
    discount_rate: int | None = Field(None, ge=0, le=90)
    discount_title: str | None = None
    discount_until: datetime | None = None


class StoreUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    address: str | None = None
    region: str | None = None
    supported_pay_types: list[PayType] | None = None
    point_rate: float | None = Field(None, ge=0, le=0.5)
    lat: float | None = None
    lng: float | None = None
    phone: str | None = None
    tagline: str | None = None
    image_url: str | None = None
    open_time: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    close_time: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    closed_weekdays: list[int] | None = None
    discount_rate: int | None = Field(None, ge=0, le=90)
    discount_title: str | None = None
    discount_until: datetime | None = None


class StoreOut(ORM):
    id: int
    name: str
    description: str
    category: str
    address: str
    region: str
    supported_pay_types: list[str]
    point_rate: float
    lat: float | None
    lng: float | None
    phone: str
    tagline: str
    image_url: str
    open_time: str
    close_time: str
    closed_weekdays: list[int]
    discount_rate: int = 0
    discount_title: str = ""
    discount_until: datetime | None = None
    discount: dict | None = None


class MenuOptionIn(BaseModel):
    group: str
    name: str
    extra_price: int = 0


class MenuOptionOut(ORM):
    id: int
    group: str
    name: str
    extra_price: int


class MenuItemIn(BaseModel):
    name: str
    name_en: str = ""
    description: str = ""
    category: str = ""
    price: int = Field(ge=0)
    spicy_level: int = Field(0, ge=0, le=5)
    sweetness: int = Field(0, ge=0, le=5)
    tags: list[str] = []
    allergens: list[str] = []
    image_url: str = ""
    is_available: bool = True
    options: list[MenuOptionIn] = []


class MenuItemUpdate(BaseModel):
    name: str | None = None
    name_en: str | None = None
    description: str | None = None
    category: str | None = None
    price: int | None = Field(None, ge=0)
    spicy_level: int | None = Field(None, ge=0, le=5)
    sweetness: int | None = Field(None, ge=0, le=5)
    tags: list[str] | None = None
    allergens: list[str] | None = None
    image_url: str | None = None
    is_available: bool | None = None


class MenuItemOut(ORM):
    id: int
    store_id: int
    name: str
    name_en: str
    description: str
    category: str
    price: int
    spicy_level: int
    sweetness: int
    tags: list[str]
    allergens: list[str]
    image_url: str
    is_available: bool
    options: list[MenuOptionOut]


class KioskIn(BaseModel):
    name: str
    table_no: str | None = None


class KioskOut(ORM):
    id: int
    store_id: int
    name: str
    table_no: str | None
    api_key: str


# ---------- 주문 ----------
class OrderItemIn(BaseModel):
    menu_item_id: int
    quantity: int = Field(1, ge=1, le=99)
    option_ids: list[int] = []


class OrderIn(BaseModel):
    items: list[OrderItemIn] = Field(min_length=1)
    table_no: str | None = None
    order_type: str = Field("dine_in", pattern="^(dine_in|takeout)$", description="dine_in 매장 / takeout 포장")


class OrderItemOut(ORM):
    menu_item_id: int
    name: str
    unit_price: int
    quantity: int
    options: list[dict]


class OrderOut(ORM):
    id: int
    store_id: int
    user_id: int | None
    table_no: str | None
    order_type: str
    status: str
    total_amount: int
    discount_amount: int = 0
    created_at: datetime
    paid_at: datetime | None
    items: list[OrderItemOut]


class OrderStatusIn(BaseModel):
    status: str


# ---------- 결제 ----------
class PaymentMethodIn(BaseModel):
    pay_type: PayType
    display_name: str
    masked_number: str = ""
    billing_key: str = ""
    region: str = ""
    mock_balance: int | None = None
    priority: int | None = None


class PaymentMethodOut(ORM):
    id: int
    pay_type: str
    display_name: str
    masked_number: str
    region: str
    priority: int
    is_active: bool


class PriorityIn(BaseModel):
    method_ids: list[int] = Field(description="우선순위 순서대로 정렬된 결제수단 id 목록")


class QRTokenIn(BaseModel):
    method_id: int | None = Field(None, description="특정 카드로 결제할 때만 지정. 없으면 우선순위대로 결제")
    use_points: bool = Field(True, description="유니 포인트를 먼저 차감할지")


class QRTokenOut(BaseModel):
    token: str
    qr_payload: str
    expires_at: datetime
    method_id: int | None


class PairIn(BaseModel):
    qr_payload: str
    method_id: int | None = None
    use_points: bool = True


class QRPayIn(BaseModel):
    order_id: int
    qr_payload: str


class PaymentOut(ORM):
    id: int
    order_id: int
    pay_type: str
    amount: int
    status: str
    approval_no: str
    message: str
    created_at: datetime


class QRPayResult(BaseModel):
    success: bool
    order_id: int
    paid_amount: int
    points_used: int
    points_earned: int
    payments: list[PaymentOut]
    attempts: list[dict]
    message: str


class PointWalletOut(BaseModel):
    store_id: int
    store_name: str
    balance: int
    total_spent: int = 0
    last_earned: int = 0


# ---------- AI ----------
class ChatIn(BaseModel):
    session_id: str
    message: str
    customer_session: str | None = Field(None, description="/api/kiosk/identify 에서 받은 손님 세션 (개인화 추천)")


class ChatOut(BaseModel):
    reply: str
    recommended_menus: list[MenuItemOut]
    unmet_requests: list[str]
    actions: list[dict] = Field(default_factory=list,
                                description='말로 주문: {"type":"add_to_cart","menu_item_id","quantity"} / {"type":"checkout"}')
    ignored: bool = Field(False, description="음성: 주변 잡음·옆 사람 대화로 판단해 무시함 (화면에 안 보여주고 계속 듣기)")


class VoiceChatOut(ChatOut):
    transcript: str = Field(description="음성 인식된 손님 말")


class STTOut(BaseModel):
    text: str


class IdentifyIn(BaseModel):
    qr_payload: str


class IdentifyOut(BaseModel):
    user_id: int
    name: str
    greeting: str
    usual_items: list[dict]
    point_balance: int
    customer_session: str
    selected_method: dict | None = Field(None, description="앱에서 고른 결제카드. None 이면 '우선순위대로'")
    recommended_menus: list[MenuItemOut] = []
    memory: dict = Field(default_factory=dict, description="이 가게에서의 지난 대화·주문 요약")


class SessionIn(BaseModel):
    customer_session: str


class SessionPayIn(BaseModel):
    order_id: int
    customer_session: str
    method_id: int | None = Field(None, description="'결제 방식 바꾸기'로 고른 카드. 없으면 처음 QR에서 고른 카드")


class CardPayIn(BaseModel):
    order_id: int
    customer_session: str | None = Field(None, description="앱 손님이면 포인트 적립용")


TokenOut.model_rebuild()


class StoreAlertIn(BaseModel):
    on: bool
