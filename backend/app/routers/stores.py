"""공개 가게/메뉴 조회 (소비자 앱·웹)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import MenuItem, Store
from ..schemas import MenuItemOut, StoreOut

router = APIRouter(prefix="/api/stores", tags=["가게(공개)"])


@router.get("", response_model=list[StoreOut])
def list_stores(q: str | None = None, category: str | None = None, db: Session = Depends(get_db)):
    query = db.query(Store)
    if q:
        query = query.filter(Store.name.contains(q))
    if category:
        query = query.filter(Store.category == category)
    return query.all()


@router.get("/{store_id}", response_model=StoreOut)
def get_store(store_id: int, db: Session = Depends(get_db)):
    store = db.get(Store, store_id)
    if store is None:
        raise HTTPException(404, "가게를 찾을 수 없습니다.")
    return store


@router.get("/{store_id}/menus", response_model=list[MenuItemOut])
def list_menus(store_id: int, db: Session = Depends(get_db)):
    return db.query(MenuItem).filter_by(store_id=store_id).order_by(MenuItem.category, MenuItem.id).all()
