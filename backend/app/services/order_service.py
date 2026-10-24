from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import MenuItem, MenuOption, Order, OrderItem, Store
from ..schemas import OrderIn


def create_order(db: Session, store_id: int, data: OrderIn, user_id: int | None = None,
                 kiosk_id: int | None = None, table_no: str | None = None) -> Order:
    order = Order(store_id=store_id, user_id=user_id, kiosk_id=kiosk_id, table_no=data.table_no or table_no,
                  order_type=data.order_type)
    total = 0
    for it in data.items:
        menu = db.get(MenuItem, it.menu_item_id)
        if menu is None or menu.store_id != store_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"메뉴 {it.menu_item_id} 를 찾을 수 없습니다.")
        if not menu.is_available:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"'{menu.name}'은(는) 지금 주문할 수 없습니다.")
        opts = []
        for oid in it.option_ids:
            opt = db.get(MenuOption, oid)
            if opt is None or opt.menu_item_id != menu.id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"'{menu.name}'에 없는 옵션입니다: {oid}")
            opts.append({"id": opt.id, "group": opt.group, "name": opt.name, "extra_price": opt.extra_price})
        unit = menu.price + sum(o["extra_price"] for o in opts)
        total += unit * it.quantity
        order.items.append(OrderItem(menu_item_id=menu.id, name=menu.name, unit_price=unit,
                                     quantity=it.quantity, options=opts))
    # 진행 중인 할인 행사 적용 (10원 단위 내림)
    store = db.get(Store, store_id)
    disc = store.discount if store else None
    off = (total * disc["rate"] // 100) // 10 * 10 if disc else 0
    order.discount_amount = off
    order.total_amount = total - off
    db.add(order)
    db.commit()
    db.refresh(order)
    return order
