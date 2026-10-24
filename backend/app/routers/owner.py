"""사장님 앱/웹: 가게·메뉴 관리, 키오스크 등록, 주문 관리, 매출, AI 인사이트."""
import secrets
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Kiosk, MenuItem, MenuOption, Order, OrderStatus, PayType, Store, User
from ..schemas import (
    KioskIn,
    KioskOut,
    MenuItemIn,
    MenuItemOut,
    MenuItemUpdate,
    MenuOptionIn,
    MenuOptionOut,
    OrderOut,
    OrderStatusIn,
    StoreIn,
    StoreOut,
    StoreUpdate,
)
from ..security import get_owned_store, require_owner
from ..services import ai_service
from ..services.analytics import sales_summary

router = APIRouter(prefix="/api/owner", tags=["사장님"])


# ---------- 가게 ----------
@router.get("/stores", response_model=list[StoreOut])
def my_stores(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return db.query(Store).filter_by(owner_id=owner.id).all()


@router.post("/stores", response_model=StoreOut)
def create_store(data: StoreIn, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    values = data.model_dump(exclude_none=True)
    values["supported_pay_types"] = [p.value for p in (data.supported_pay_types or list(PayType))]
    store = Store(owner_id=owner.id, **values)
    db.add(store)
    db.commit()
    return store


@router.patch("/stores/{store_id}", response_model=StoreOut)
def update_store(store_id: int, data: StoreUpdate, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    """지원 결제수단(supported_pay_types), 포인트 적립률 등 설정."""
    store = get_owned_store(store_id, owner, db)
    values = data.model_dump(exclude_none=True)
    if "supported_pay_types" in values:
        values["supported_pay_types"] = [p.value for p in data.supported_pay_types]
    for k, v in values.items():
        setattr(store, k, v)
    db.commit()
    return store


# ---------- 메뉴 ----------
@router.get("/stores/{store_id}/menus", response_model=list[MenuItemOut])
def list_menus(store_id: int, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return get_owned_store(store_id, owner, db).menus


@router.post("/stores/{store_id}/menus", response_model=MenuItemOut)
def create_menu(store_id: int, data: MenuItemIn, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    get_owned_store(store_id, owner, db)
    values = data.model_dump(exclude={"options"})
    menu = MenuItem(store_id=store_id, **values)
    menu.options = [MenuOption(**o.model_dump()) for o in data.options]
    db.add(menu)
    db.commit()
    return menu


def _owned_menu(menu_id: int, owner: User, db: Session) -> MenuItem:
    menu = db.get(MenuItem, menu_id)
    if menu is None:
        raise HTTPException(404, "메뉴를 찾을 수 없습니다.")
    get_owned_store(menu.store_id, owner, db)
    return menu


@router.patch("/menus/{menu_id}", response_model=MenuItemOut)
def update_menu(menu_id: int, data: MenuItemUpdate, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    """가격 변경, 품절 처리(is_available=false), 맵기/당도 정보 수정 등."""
    menu = _owned_menu(menu_id, owner, db)
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(menu, k, v)
    db.commit()
    return menu


@router.delete("/menus/{menu_id}")
def delete_menu(menu_id: int, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    menu = _owned_menu(menu_id, owner, db)
    menu.is_available = False  # 주문 이력 보존을 위해 숨김 처리
    db.commit()
    return {"ok": True}


@router.post("/menus/{menu_id}/options", response_model=MenuOptionOut)
def add_option(menu_id: int, data: MenuOptionIn, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    """예: AI 인사이트에서 '맵기 조절' 요청이 많다고 하면 → group='맵기', name='덜 맵게' 추가."""
    menu = _owned_menu(menu_id, owner, db)
    opt = MenuOption(menu_item_id=menu.id, **data.model_dump())
    db.add(opt)
    db.commit()
    return opt


@router.delete("/options/{option_id}")
def delete_option(option_id: int, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    opt = db.get(MenuOption, option_id)
    if opt is None:
        raise HTTPException(404, "옵션을 찾을 수 없습니다.")
    _owned_menu(opt.menu_item_id, owner, db)
    db.delete(opt)
    db.commit()
    return {"ok": True}


# ---------- 키오스크 기기 ----------
@router.get("/stores/{store_id}/kiosks", response_model=list[KioskOut])
def list_kiosks(store_id: int, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return get_owned_store(store_id, owner, db).kiosks


@router.post("/stores/{store_id}/kiosks", response_model=KioskOut)
def register_kiosk(store_id: int, data: KioskIn, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    """키오스크/테이블 태블릿 등록 → 발급된 api_key 를 기기에 설정."""
    get_owned_store(store_id, owner, db)
    k = Kiosk(store_id=store_id, name=data.name, table_no=data.table_no, api_key=secrets.token_hex(24))
    db.add(k)
    db.commit()
    return k


# ---------- 주문 ----------
@router.get("/stores/{store_id}/orders", response_model=list[OrderOut])
def list_orders(store_id: int, status: str | None = None, owner: User = Depends(require_owner),
                db: Session = Depends(get_db)):
    get_owned_store(store_id, owner, db)
    q = db.query(Order).filter_by(store_id=store_id)
    if status:
        q = q.filter_by(status=status)
    return q.order_by(Order.id.desc()).limit(100).all()


@router.patch("/orders/{order_id}/status", response_model=OrderOut)
def change_order_status(order_id: int, data: OrderStatusIn, owner: User = Depends(require_owner),
                        db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "주문을 찾을 수 없습니다.")
    get_owned_store(order.store_id, owner, db)
    if data.status not in {s.value for s in OrderStatus}:
        raise HTTPException(400, "잘못된 상태값입니다.")
    order.status = data.status
    db.commit()
    return order


# ---------- 매출 / AI 인사이트 ----------
@router.get("/stores/{store_id}/sales")
def sales(store_id: int, start: date | None = None, end: date | None = None,
          owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    store = get_owned_store(store_id, owner, db)
    end = end or date.today()
    start = start or end - timedelta(days=6)
    return sales_summary(db, store, start, end)


@router.get("/stores/{store_id}/insights")
def insights(store_id: int, days: int = 30, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    """키오스크 대화 분석: 손님들이 많이 찾았지만 없는 옵션, 자주 묻는 주제, 개선 제안."""
    store = get_owned_store(store_id, owner, db)
    return ai_service.owner_insights(db, store, days)
