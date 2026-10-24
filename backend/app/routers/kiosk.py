"""키오스크/테이블오더 기기용 API. 모든 요청에 X-Kiosk-Key 헤더 필요."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
import secrets
from datetime import datetime, timedelta

from ..config import settings
from ..models import PAY_TYPE_LABELS, Kiosk, KioskPairing, MenuItem, Order, PaymentMethod, PaymentQRToken, PayType, User
from ..schemas import (
    ChatIn,
    ChatOut,
    IdentifyIn,
    CardPayIn,
    IdentifyOut,
    SessionIn,
    SessionPayIn,
    MenuItemOut,
    OrderIn,
    OrderOut,
    QRPayIn,
    QRPayResult,
    StoreOut,
    STTOut,
    VoiceChatOut,
)
from ..security import create_customer_session, get_kiosk, read_customer_session
from ..services import ai_service, stt
from ..services.order_service import create_order
from ..services.payment_service import (
    get_wallet, issue_qr_token, ordered_methods, pay_order, pay_order_with_card, pay_order_with_qr, resolve_qr,
)

router = APIRouter(prefix="/api/kiosk", tags=["키오스크"])


def _own_order(db: Session, kiosk: Kiosk, order_id: int) -> Order:
    order = db.get(Order, order_id)
    if order is None or order.store_id != kiosk.store_id:
        raise HTTPException(404, "주문을 찾을 수 없습니다.")
    return order


@router.get("/store", response_model=StoreOut)
def kiosk_store(kiosk: Kiosk = Depends(get_kiosk)):
    return kiosk.store


@router.get("/menus", response_model=list[MenuItemOut])
def kiosk_menus(kiosk: Kiosk = Depends(get_kiosk), db: Session = Depends(get_db)):
    return db.query(MenuItem).filter_by(store_id=kiosk.store_id, is_available=True).all()


@router.post("/orders", response_model=OrderOut)
def kiosk_create_order(data: OrderIn, kiosk: Kiosk = Depends(get_kiosk), db: Session = Depends(get_db)):
    return create_order(db, kiosk.store_id, data, kiosk_id=kiosk.id, table_no=kiosk.table_no)


@router.get("/orders/{order_id}", response_model=OrderOut)
def kiosk_get_order(order_id: int, kiosk: Kiosk = Depends(get_kiosk), db: Session = Depends(get_db)):
    return _own_order(db, kiosk, order_id)


@router.post("/payments/qr", response_model=QRPayResult)
def kiosk_pay_with_qr(data: QRPayIn, kiosk: Kiosk = Depends(get_kiosk), db: Session = Depends(get_db)):
    """'앱으로 결제하기' → 키오스크가 손님 앱 QR을 스캔하면 호출.
    서버가 손님의 등록 결제수단을 우선순위대로(또는 지정 카드로) 직접 결제합니다."""
    order = _own_order(db, kiosk, data.order_id)
    return pay_order_with_qr(db, order, kiosk.store, data.qr_payload)


def _session(kiosk: Kiosk, token: str | None) -> dict | None:
    if not token:
        return None
    return read_customer_session(token, kiosk.store_id, kiosk.id)


def _method_info(m: PaymentMethod | None) -> dict | None:
    if m is None:
        return None
    return {"id": m.id, "pay_type": m.pay_type, "label": PAY_TYPE_LABELS.get(PayType(m.pay_type), m.pay_type),
            "display_name": m.display_name, "masked_number": m.masked_number}


def _start_session(db: Session, kiosk: Kiosk, user: User, token: PaymentQRToken) -> IdentifyOut:
    """손님 확인 → 방문 세션(고른 결제카드 유지) + 이 가게 대화 기억으로 인사·추천."""
    store = kiosk.store
    method = db.get(PaymentMethod, token.method_id) if token.method_id else None
    mem = ai_service.customer_memory(db, user, store)
    prof = ai_service.apply_memory(ai_service.taste_profile(db, user), mem)
    recs = ai_service.recommend_menus(store, prof, 3)
    wallet = get_wallet(db, user.id, store.id, create=False)
    greeting = ai_service.welcome_message(user, store, mem, recs, method.display_name if method else "등록한 결제수단 우선순위")
    token.used_at = token.used_at or datetime.now()
    token.result = {"type": "identified", "store": store.name, "kiosk": kiosk.name,
                    "method": method.display_name if method else None}
    db.commit()
    return IdentifyOut(
        user_id=user.id, name=user.name, greeting=greeting, usual_items=mem["usual_items"],
        point_balance=wallet.balance if wallet else 0,
        customer_session=create_customer_session(user.id, store.id, kiosk.id, token.method_id, token.use_points,
                                                 token.token),
        selected_method=_method_info(method), recommended_menus=recs, memory=mem,
    )


@router.post("/session/start", response_model=IdentifyOut)
def kiosk_session_start(data: IdentifyIn, kiosk: Kiosk = Depends(get_kiosk), db: Session = Depends(get_db)):
    """[키오스크에 카메라가 있을 때] 손님 앱 QR을 키오스크가 찍어서 방문 시작."""
    token = resolve_qr(db, data.qr_payload)
    return _start_session(db, kiosk, db.get(User, token.user_id), token)


# ---------- 키오스크 화면 QR ← 손님 앱이 찍기 (카메라 없는 태블릿) ----------
PAIR_PREFIX = "UNIORDER:PAIR:"
PAIR_TTL = 180  # 초


@router.post("/pair")
def kiosk_pair_create(kiosk: Kiosk = Depends(get_kiosk), db: Session = Depends(get_db)):
    """첫 화면에 띄울 연결 QR 발급 (3분마다 새로). 손님이 UNIORDER 앱으로 찍으면 연결돼요."""
    p = KioskPairing(code=secrets.token_urlsafe(18), kiosk_id=kiosk.id,
                     expires_at=datetime.now() + timedelta(seconds=PAIR_TTL))
    db.add(p)
    db.commit()
    return {"code": p.code, "qr_payload": PAIR_PREFIX + p.code, "expires_in": PAIR_TTL}


@router.get("/pair/{code}")
def kiosk_pair_status(code: str, kiosk: Kiosk = Depends(get_kiosk), db: Session = Depends(get_db)):
    """키오스크가 폴링. 손님이 찍었으면 방문 세션을 돌려줌 (한 번만)."""
    p = db.query(KioskPairing).filter_by(code=code, kiosk_id=kiosk.id).first()
    if p is None:
        raise HTTPException(404, "QR을 찾을 수 없어요.")
    if p.claimed_at is None:
        return {"status": "expired" if p.expires_at < datetime.now() else "waiting"}
    if p.consumed_at is not None:
        return {"status": "used"}
    p.consumed_at = datetime.now()
    token = db.query(PaymentQRToken).filter_by(token=p.qr_token).first()
    session = _start_session(db, kiosk, db.get(User, p.user_id), token)
    return {"status": "linked", "session": session}


@router.post("/pair/{code}/demo")
def kiosk_pair_demo(code: str, kiosk: Kiosk = Depends(get_kiosk), db: Session = Depends(get_db)):
    """[데모] 폰 없이 시연: 데모 손님이 이 QR을 찍은 것처럼 처리."""
    if not settings.DEMO_MODE:
        raise HTTPException(404)
    user = db.query(User).filter_by(email="user@demo.com").first()
    return claim_pairing(db, PAIR_PREFIX + code, user, None, True)


def claim_pairing(db: Session, qr_payload: str, user: User, method_id: int | None, use_points: bool) -> dict:
    code = qr_payload.strip()
    if code.startswith(PAIR_PREFIX):
        code = code[len(PAIR_PREFIX):]
    p = db.query(KioskPairing).filter_by(code=code).first()
    if p is None:
        raise HTTPException(400, "UNIORDER 키오스크 QR이 아니에요.")
    if p.expires_at < datetime.now():
        raise HTTPException(400, "QR 유효시간이 지났어요. 키오스크 화면의 새 QR을 찍어주세요.")
    if p.claimed_at is not None:
        raise HTTPException(400, "이미 다른 손님과 연결된 QR이에요.")
    token = issue_qr_token(db, user, method_id, use_points)  # 결제 결과를 앱에 전달할 통로
    p.user_id, p.method_id, p.use_points, p.qr_token, p.claimed_at = user.id, method_id, use_points, token.token, datetime.now()
    db.commit()
    kiosk = db.get(Kiosk, p.kiosk_id)
    return {"store": kiosk.store.name, "kiosk": kiosk.name, "token": token.token,
            "method": db.get(PaymentMethod, method_id).display_name if method_id else None}


# 예전 이름 호환
router.add_api_route("/identify", kiosk_session_start, methods=["POST"], response_model=IdentifyOut,
                     include_in_schema=False)


@router.post("/session/methods")
def kiosk_session_methods(data: SessionIn, kiosk: Kiosk = Depends(get_kiosk), db: Session = Depends(get_db)):
    """'결제 방식 바꾸기': 손님이 앱에 등록한 결제수단 (마스킹) 목록."""
    sess = _session(kiosk, data.customer_session)
    if not sess:
        raise HTTPException(401, "손님 확인이 만료됐어요. 앱 QR을 다시 찍어주세요.")
    supported = set(kiosk.store.supported_pay_types or [])
    return [{**_method_info(m), "supported": m.pay_type in supported, "selected": m.id == sess["method_id"]}
            for m in ordered_methods(db, sess["user_id"]) if m.pay_type != PayType.DODO_POINT.value]


@router.post("/payments/session", response_model=QRPayResult)
def kiosk_pay_with_session(data: SessionPayIn, kiosk: Kiosk = Depends(get_kiosk), db: Session = Depends(get_db)):
    """'결제 계속하기' (처음 QR에서 고른 카드) 또는 '결제 방식 바꾸기'로 고른 카드로 결제."""
    sess = _session(kiosk, data.customer_session)
    if not sess:
        raise HTTPException(401, "손님 확인이 만료됐어요. 앱 QR을 다시 찍어주세요.")
    order = _own_order(db, kiosk, data.order_id)
    method_id = data.method_id if data.method_id is not None else sess["method_id"]
    token = db.query(PaymentQRToken).filter_by(token=sess["qr"]).first() if sess.get("qr") else None
    use_points = sess["use_points"] and data.method_id is None
    return pay_order(db, order, kiosk.store, sess["user_id"], method_id, use_points, token)


@router.post("/payments/card", response_model=QRPayResult)
def kiosk_pay_with_card(data: CardPayIn, kiosk: Kiosk = Depends(get_kiosk), db: Session = Depends(get_db)):
    """'카드결제': 키오스크 카드 단말기 (데모는 바로 승인). 앱 손님이면 포인트 적립."""
    order = _own_order(db, kiosk, data.order_id)
    sess = _session(kiosk, data.customer_session)
    return pay_order_with_card(db, order, kiosk.store, sess["user_id"] if sess else None)


@router.post("/ai/chat", response_model=ChatOut)
def kiosk_ai_chat(data: ChatIn, kiosk: Kiosk = Depends(get_kiosk), db: Session = Depends(get_db)):
    """손님과 AI 대화: '이거 매워요?', '덜 단 거 없어요?', '추천해 주세요' 등."""
    user = None
    if data.customer_session:
        sess = _session(kiosk, data.customer_session)
        user = db.get(User, sess["user_id"]) if sess else None
    return ai_service.kiosk_chat(db, kiosk.store, data.session_id, data.message, user)


# ---------- 음성 (Whisper) ----------
def _menu_hint(kiosk: Kiosk) -> str:
    """메뉴 이름을 힌트로 줘서 인식률을 높임."""
    names = [m.name for m in kiosk.store.menus if m.is_available]
    return f"{kiosk.store.name} 메뉴: " + ", ".join(names) + ". 맵기, 덜 맵게, 곱빼기, 포장, 추천해 주세요."


async def _transcribe(kiosk: Kiosk, audio: UploadFile, allow_empty: bool = False) -> str:
    data = await audio.read()
    try:
        return stt.transcribe(data, audio.filename or "audio.webm", _menu_hint(kiosk))
    except stt.NoSpeech:
        if allow_empty:
            return ""
        raise HTTPException(400, "잘 못 알아들었어요. 다시 한 번 말씀해 주세요.")
    except stt.STTError as e:
        raise HTTPException(400, str(e))


@router.post("/stt", response_model=STTOut)
async def kiosk_stt(audio: UploadFile = File(..., description="녹음 파일 (webm/ogg/wav/mp3/m4a)"),
                    kiosk: Kiosk = Depends(get_kiosk)):
    """음성 → 글자만. (검색창·주문 입력 등에 받아쓰기로 쓰고 싶을 때)"""
    return STTOut(text=await _transcribe(kiosk, audio))


@router.post("/ai/voice", response_model=VoiceChatOut)
async def kiosk_ai_voice(audio: UploadFile = File(...), session_id: str = Form(...),
                         customer_session: str | None = Form(None),
                         kiosk: Kiosk = Depends(get_kiosk), db: Session = Depends(get_db)):
    """음성으로 AI 직원에게 물어보기: 음성 인식 → /ai/chat 과 같은 대화 처리.
    글자로 묻고 싶으면 기존 /ai/chat 을 그대로 쓰면 되고, 같은 session_id 를 쓰면 대화가 이어집니다."""
    text = await _transcribe(kiosk, audio, allow_empty=True)
    if not text:  # 잡음만 들어옴 → 조용히 무시하고 계속 듣기
        return VoiceChatOut(transcript="", reply="", recommended_menus=[], unmet_requests=[], ignored=True)
    user = None
    if customer_session:
        sess = _session(kiosk, customer_session)
        user = db.get(User, sess["user_id"]) if sess else None
    result = ai_service.kiosk_chat(db, kiosk.store, session_id, text, user, spoken=True)
    return VoiceChatOut(transcript=text, **result)
