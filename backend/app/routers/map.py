"""손님 지도: 주변 가맹점 핀(간단 정보) + 가게 상세(메뉴·추천).

로그인 없이도 쓸 수 있고, 손님 토큰을 함께 보내면 추천/단골/포인트 정보가 추가됩니다.
지도 SDK(카카오맵·네이버지도 등)는 프론트에서 붙이고, 여기서는 좌표와 데이터만 줍니다.
"""
from collections import Counter
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import PAY_TYPE_LABELS, Order, OrderItem, PayType, Store, User
from ..schemas import MenuItemOut
from ..security import get_optional_user
from ..services import ai_service, recommend
from ..services.geo import hours_text, is_open, store_distance, walk_minutes
from ..services.payment_service import get_wallet

router = APIRouter(prefix="/api/map", tags=["지도"])


def _popular_menus(db: Session, store_id: int, limit: int = 3) -> list[dict]:
    since = datetime.now() - timedelta(days=30)
    rows = (db.query(OrderItem.menu_item_id, OrderItem.name, OrderItem.quantity)
            .join(Order, Order.id == OrderItem.order_id)
            .filter(Order.store_id == store_id, Order.status.in_(recommend.DONE), Order.paid_at >= since).all())
    qty, names = Counter(), {}
    for mid, name, q in rows:
        qty[mid] += q
        names[mid] = name
    return [{"menu_item_id": mid, "name": names[mid], "sold_30d": q} for mid, q in qty.most_common(limit)]


def _menu_reason(m, p: dict, popular_ids: list[int]) -> str:
    if any(a in m.allergens for a in p.get("allergies", [])):
        return "알레르기 성분이 있어요, 주의하세요"
    bits = []
    if m.name in p.get("favorite_menus", []):
        bits.append("자주 드신 메뉴")
    sp, sw = p.get("spicy_preference"), p.get("sweet_preference")
    if sp is not None and abs(m.spicy_level - sp) <= 1.5:
        bits.append("매운 걸 좋아하는 입맛에 딱" if sp >= 3 else "순한 맛 좋아하시는 입맛에 딱" if sp < 1 else "딱 좋은 맵기")
    if sw is not None and abs(m.sweetness - sw) <= 1 and len(bits) < 2:
        bits.append("부담 없는 단맛")
    if m.id in popular_ids:
        bits.append(f"이 가게 인기 {popular_ids.index(m.id) + 1}위")
    return " · ".join(bits[:2]) or "새로운 메뉴에 도전해보세요"


@router.get("/stores")
def map_stores(
    lat: float | None = Query(None, description="내 위치 위도"),
    lng: float | None = Query(None, description="내 위치 경도"),
    radius_m: int | None = Query(None, description="lat/lng 기준 반경(m). 없으면 전체"),
    sw_lat: float | None = None, sw_lng: float | None = None, ne_lat: float | None = None, ne_lng: float | None = None,
    category: str | None = None, q: str | None = None, open_now: bool = False,
    user: User | None = Depends(get_optional_user), db: Session = Depends(get_db),
):
    """지도 핀용 가맹점 목록. 지도 화면 영역(sw/ne) 또는 내 위치 반경으로 거를 수 있어요."""
    stores = db.query(Store).filter(Store.lat.isnot(None)).all()
    if category:
        stores = [s for s in stores if s.category == category]
    if q:
        stores = [s for s in stores if q in s.name or any(q in m.name for m in s.menus)]
    if None not in (sw_lat, sw_lng, ne_lat, ne_lng):
        stores = [s for s in stores if sw_lat <= s.lat <= ne_lat and sw_lng <= s.lng <= ne_lng]

    recos = {}
    if user:
        ranked = recommend.recommend_stores(db, user, lat, lng, limit=len(stores) or 1, with_ai_comment=False)
        for rank, r in enumerate(ranked, 1):
            recos[r["store_id"]] = {**r, "rank": rank}

    out = []
    for s in stores:
        dist = store_distance(s, lat, lng)
        if radius_m and dist is not None and dist > radius_m:
            continue
        open_ = is_open(s)
        if open_now and not open_:
            continue
        menus = [m for m in s.menus if m.is_available]
        pop = _popular_menus(db, s.id, 1)
        item = {
            "id": s.id, "name": s.name, "category": s.category, "tagline": s.tagline, "image_url": s.image_url,
            "lat": s.lat, "lng": s.lng, "is_open": open_, "hours": hours_text(s),
            "distance_m": round(dist) if dist is not None else None,
            "walk_min": walk_minutes(dist) if dist is not None else None,
            "price_range": [min(m.price for m in menus), max(m.price for m in menus)] if menus else None,
            "signature_menu": pop[0]["name"] if pop else (menus[0].name if menus else None),
            "discount": s.discount,
        }
        if user and s.id in recos:
            r = recos[s.id]
            item["recommend"] = {"rank": r["rank"], "tag": r["tag"], "reason": r["reason"], "score": r["score"],
                                 "highlight": r["rank"] <= 3}
            item["visits"] = r["visits"]
        out.append(item)
    out.sort(key=lambda x: (x.get("recommend", {}).get("rank", 999), x["distance_m"] or 0))
    return out


@router.get("/stores/{store_id}")
def map_store_detail(store_id: int, lat: float | None = None, lng: float | None = None,
                     user: User | None = Depends(get_optional_user), db: Session = Depends(get_db)):
    """핀을 눌러 들어갔을 때: 가게 상세 + 메뉴 + (로그인 시) 나에게 맞는 추천."""
    s = db.get(Store, store_id)
    if s is None:
        raise HTTPException(404, "가게를 찾을 수 없습니다.")
    dist = store_distance(s, lat, lng)
    menus = [m for m in s.menus if m.is_available]
    grouped: dict[str, list] = {}
    for m in menus:
        grouped.setdefault(m.category or "기타", []).append(MenuItemOut.model_validate(m))

    detail = {
        "id": s.id, "name": s.name, "category": s.category, "tagline": s.tagline, "description": s.description,
        "image_url": s.image_url, "address": s.address, "phone": s.phone, "lat": s.lat, "lng": s.lng,
        "is_open": is_open(s), "hours": hours_text(s),
        "distance_m": round(dist) if dist is not None else None,
        "walk_min": walk_minutes(dist) if dist is not None else None,
        "pay_types": [PAY_TYPE_LABELS[PayType(p)] for p in s.supported_pay_types if p in PayType._value2member_map_],
        "point_rate": s.point_rate,
        "discount": s.discount,
        "popular_menus": _popular_menus(db, s.id, 3),
        "menus": [{"category": c, "items": items} for c, items in grouped.items()],
    }
    if user:
        prof = ai_service.taste_profile(db, user)
        recs = ai_service.recommend_menus(s, prof, 3)
        popular_ids = [x["menu_item_id"] for x in detail["popular_menus"]]
        wallet = get_wallet(db, user.id, s.id, create=False)
        mine = recommend.recommend_stores(db, user, lat, lng, limit=100, with_ai_comment=False)
        me = next((r for r in mine if r["store_id"] == s.id), None)
        detail["for_me"] = {
            "usual_items": ai_service.usual_items(db, user.id, s.id),
            "recommended_menus": [{"menu": MenuItemOut.model_validate(m), "reason": _menu_reason(m, prof, popular_ids)} for m in recs],
            "point_balance": wallet.balance if wallet else 0,
            "visits": me["visits"] if me else 0,
            "why_this_store": me["reasons"] if me else [],
            "alert_on": s.id in (user.preferences or {}).get("store_alerts", []),
        }
    return detail
