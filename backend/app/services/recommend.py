"""손님 행동 패턴 분석 + 가게 추천.

추천 점수 = 여러 신호의 가중합 (각 신호는 0~1)
  taste       입맛 적합도   : 가게 메뉴의 맵기/단맛/카테고리가 손님 취향과 얼마나 맞는지
  loyalty     단골도        : 이 가게 방문 횟수 (최근일수록 가중)
  time_fit    시간대 패턴   : 지금 시간대(점심/저녁…)에 손님이 주로 먹는 종류인지
  day_fit     요일 패턴     : 평일/주말에 주로 가는 종류인지
  co_visit    비슷한 손님   : 나와 같은 가게를 다니는 손님들이 자주 가는 곳인지
  popularity  인기          : 최근 30일 주문 수
  distance    거리          : 현재 위치에서 가까운지 (위치 줄 때만)
  novelty     새로운 발견   : 좋아하는 종류인데 아직 안 가본 곳 (보너스)
"""
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import Order, OrderStatus, Store, User
from . import llm
from .ai_service import recommend_menus, score_menu, taste_profile
from .geo import is_open, store_distance, walk_minutes

DONE = [OrderStatus.PAID.value, OrderStatus.SERVED.value]
SLOTS = [("아침", 5, 10), ("점심", 10, 15), ("오후", 15, 17), ("저녁", 17, 21), ("야식", 21, 29)]
WEIGHTS = {"taste": 0.22, "loyalty": 0.18, "time_fit": 0.15, "day_fit": 0.05,
           "co_visit": 0.12, "popularity": 0.10, "distance": 0.18}


def slot_of(dt: datetime) -> str:
    h = dt.hour if dt.hour >= 5 else dt.hour + 24
    for name, a, b in SLOTS:
        if a <= h < b:
            return name
    return "야식"


def day_type(dt: datetime) -> str:
    return "주말" if dt.weekday() >= 5 else "평일"


def _user_orders(db: Session, user_id: int) -> list[Order]:
    return (db.query(Order).filter(Order.user_id == user_id, Order.status.in_(DONE))
            .order_by(Order.paid_at).all())


# ---------------- 행동 패턴 ----------------
def behavior_profile(db: Session, user: User) -> dict:
    orders = _user_orders(db, user.id)
    stores = {s.id: s for s in db.query(Store).all()}
    now = datetime.now()
    if not orders:
        return {"visit_count": 0, "summary": "아직 방문 기록이 없어요. 몇 번 이용하면 생활 패턴에 맞춰 추천해드릴게요!",
                "slots": [], "day_types": {}, "top_stores": [], "top_categories": [], "total_spent": 0,
                "avg_order_value": 0, "avg_days_between_visits": None, "last_visit_days_ago": None,
                "slot_categories": {}}

    slots = Counter(slot_of(o.paid_at) for o in orders)
    days = Counter(day_type(o.paid_at) for o in orders)
    store_visits = Counter(o.store_id for o in orders)
    cats = Counter(stores[o.store_id].category for o in orders if o.store_id in stores)
    slot_cats: dict[str, Counter] = defaultdict(Counter)
    for o in orders:
        if o.store_id in stores:
            slot_cats[slot_of(o.paid_at)][stores[o.store_id].category] += 1

    dates = sorted({o.paid_at.date() for o in orders})
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    total = sum(o.total_amount for o in orders)
    prof = {
        "visit_count": len(orders),
        "total_spent": total,
        "avg_order_value": round(total / len(orders)),
        "avg_days_between_visits": round(sum(gaps) / len(gaps), 1) if gaps else None,
        "last_visit_days_ago": (now.date() - orders[-1].paid_at.date()).days,
        "slots": [{"slot": s, "count": c} for s, c in slots.most_common()],
        "day_types": dict(days),
        "top_stores": [{"store_id": sid, "name": stores[sid].name, "visits": c}
                       for sid, c in store_visits.most_common(5) if sid in stores],
        "top_categories": [c for c, _ in cats.most_common(3)],
        "slot_categories": {s: dict(c.most_common(3)) for s, c in slot_cats.items()},
    }
    prof["summary"] = _behavior_summary(prof)
    return prof


def _behavior_summary(p: dict) -> str:
    ai = llm.complete(
        "너는 손님의 외식 패턴을 분석하는 앱 도우미야. 데이터를 보고 친근한 한국어 2문장으로 생활 패턴을 요약해. 숫자는 꼭 필요한 것만.",
        [{"role": "user", "content": json.dumps(p, ensure_ascii=False)}], max_tokens=200)
    if ai:
        return ai.strip()
    parts = []
    if p["slots"]:
        top = p["slots"][0]["slot"]
        cat = next(iter(p["slot_categories"].get(top, {})), None)
        parts.append(f"주로 {top}에 {cat + ' ' if cat else ''}드시는 편이에요.")
    if p["top_stores"]:
        parts.append(f"가장 자주 가는 곳은 {p['top_stores'][0]['name']}({p['top_stores'][0]['visits']}번)이에요.")
    if p["avg_days_between_visits"]:
        parts.append(f"평균 {p['avg_days_between_visits']}일마다 외식하세요.")
    return " ".join(parts)


# ---------------- 가게 추천 ----------------
def _co_visit_scores(db: Session, user_id: int, my_stores: set[int]) -> dict[int, float]:
    """나와 같은 가게를 다니는 손님들이 다른 어디를 가는지 (간단한 협업 필터링)."""
    if not my_stores:
        return {}
    rows = db.query(Order.user_id, Order.store_id).filter(
        Order.user_id.isnot(None), Order.user_id != user_id, Order.status.in_(DONE)).distinct().all()
    by_user: dict[int, set[int]] = defaultdict(set)
    for uid, sid in rows:
        by_user[uid].add(sid)
    score: Counter = Counter()
    for stores in by_user.values():
        overlap = len(stores & my_stores)
        if overlap:
            for sid in stores - my_stores:  # 이미 가본 곳은 단골도로 반영하므로 제외
                score[sid] += overlap
    mx = max(score.values(), default=0)
    return {sid: v / mx for sid, v in score.items()} if mx else {}


def _popularity(db: Session) -> dict[int, tuple[float, int]]:
    since = datetime.now() - timedelta(days=30)
    cnt = Counter(sid for (sid,) in db.query(Order.store_id).filter(Order.status.in_(DONE), Order.paid_at >= since))
    mx = max(cnt.values(), default=0)
    return {sid: (c / mx if mx else 0, c) for sid, c in cnt.items()}


def recommend_stores(db: Session, user: User | None, lat: float | None = None, lng: float | None = None,
                     limit: int = 5, now: datetime | None = None, with_ai_comment: bool = True) -> list[dict]:
    now = now or datetime.now()
    stores = [s for s in db.query(Store).all() if any(m.is_available for m in s.menus)]
    pop = _popularity(db)
    cur_slot, cur_day = slot_of(now), day_type(now)

    if user:
        tprof = taste_profile(db, user)
        orders = _user_orders(db, user.id)
    else:
        tprof, orders = None, []
    store_cat = {s.id: s.category for s in stores}
    has_history = bool(orders)

    # 단골도: 방문마다 최근성 가중 (30일 반감)
    loyalty_raw: dict[int, float] = defaultdict(float)
    visits = Counter()
    for o in orders:
        loyalty_raw[o.store_id] += math.exp(-(now - o.paid_at).days / 30)
        visits[o.store_id] += 1
    lmax = max(loyalty_raw.values(), default=0)

    slot_cat = Counter(store_cat.get(o.store_id) for o in orders if slot_of(o.paid_at) == cur_slot)
    day_cat = Counter(store_cat.get(o.store_id) for o in orders if day_type(o.paid_at) == cur_day)
    slot_total, day_total = sum(slot_cat.values()), sum(day_cat.values())
    fav_cats = set(tprof["favorite_categories"]) if tprof else set()
    co = _co_visit_scores(db, user.id, set(visits)) if user else {}

    results = []
    for s in stores:
        best = recommend_menus(s, tprof or {}, 2)
        f: dict[str, float] = {}
        if tprof and has_history:
            avg = sum(score_menu(m, tprof) for m in best) / len(best)
            f["taste"] = min(1.0, max(0.0, (avg + 5) / 8)) + (0.2 if s.category in fav_cats else 0)
            f["taste"] = min(f["taste"], 1.0)
        f["loyalty"] = loyalty_raw.get(s.id, 0) / lmax if lmax else 0
        f["time_fit"] = slot_cat.get(s.category, 0) / slot_total if slot_total else 0
        f["day_fit"] = day_cat.get(s.category, 0) / day_total if day_total else 0
        f["co_visit"] = co.get(s.id, 0)
        f["popularity"] = pop.get(s.id, (0, 0))[0]
        dist = store_distance(s, lat, lng)
        if dist is not None:
            f["distance"] = math.exp(-dist / 800)

        used = {k: w for k, w in WEIGHTS.items() if k in f}
        score = sum(f[k] * w for k, w in used.items()) / sum(used.values())
        novelty = bool(user and has_history and s.id not in visits and s.category in fav_cats)
        if novelty:
            score += 0.06
        open_now = is_open(s, now)
        if not open_now:
            score *= 0.6

        reasons, tag = _reasons(s, f, visits.get(s.id, 0), cur_slot, cur_day, best, novelty, dist,
                                pop.get(s.id, (0, 0))[1], open_now)
        results.append({
            "store_id": s.id, "name": s.name, "discount": s.discount, "category": s.category, "tagline": s.tagline,
            "lat": s.lat, "lng": s.lng, "score": round(score, 3), "tag": tag, "reasons": reasons,
            "reason": " · ".join(reasons[:2]),
            "is_open": open_now, "distance_m": round(dist) if dist is not None else None,
            "walk_min": walk_minutes(dist) if dist is not None else None,
            "visits": visits.get(s.id, 0),
            "recommended_menus": [m.name for m in best],
            "signals": {k: round(v, 2) for k, v in f.items()},
        })
    results.sort(key=lambda r: r["score"], reverse=True)
    top = results[:limit]
    if with_ai_comment and user and top:
        _attach_ai_comments(top, cur_slot)
    return top


def _reasons(s, f, visits, slot, day, best, novelty, dist, pop_cnt, open_now) -> tuple[list[str], str]:
    cand: list[tuple[float, str, str]] = []  # (가중 점수, 문구, 태그)
    if visits:
        cand.append((f["loyalty"] * WEIGHTS["loyalty"] + 0.05, f"{visits}번 방문한 단골 가게", "단골"))
    if f.get("time_fit", 0) > 0:
        cand.append((f["time_fit"] * WEIGHTS["time_fit"], f"{slot}에 자주 드시는 {s.category}", "지금 딱"))
    if f.get("day_fit", 0) > 0.3:
        cand.append((f["day_fit"] * WEIGHTS["day_fit"], f"{day}에 자주 찾는 {s.category}", "지금 딱"))
    if f.get("taste", 0) > 0.6 and best:
        cand.append((f["taste"] * WEIGHTS["taste"], f"입맛에 맞는 '{best[0].name}'", "취향저격"))
    if f.get("co_visit", 0) > 0.3 and not visits:
        cand.append((f["co_visit"] * WEIGHTS["co_visit"], "비슷한 손님들이 자주 가는 곳", "새로운 발견"))
    if novelty:
        cand.append((0.08, f"좋아하는 {s.category}인데 아직 안 가본 곳", "새로운 발견"))
    if dist is not None and dist < 500:
        cand.append((f["distance"] * WEIGHTS["distance"], f"{round(dist)}m · 걸어서 {walk_minutes(dist)}분", "가까운"))
    if f.get("popularity", 0) > 0.6:
        cand.append((f["popularity"] * WEIGHTS["popularity"], f"요즘 인기 (최근 30일 {pop_cnt}건 주문)", "인기"))
    cand.sort(key=lambda x: x[0], reverse=True)
    reasons = [c[1] for c in cand]
    tag = cand[0][2] if cand else "추천"
    if not open_now:
        reasons.append("지금은 영업 시간이 아니에요")
    return reasons or ["새로운 맛집을 발견해보세요"], tag


def _attach_ai_comments(items: list[dict], slot: str) -> None:
    """LLM이 있으면 추천마다 한 줄 코멘트. 없으면 생략."""
    if not llm.is_enabled():
        return
    payload = [{"store_id": i["store_id"], "name": i["name"], "category": i["category"], "reasons": i["reasons"],
                "menus": i["recommended_menus"]} for i in items]
    res = llm.complete_json(
        f"지금은 {slot} 시간이야. 손님에게 각 가게를 추천하는 한 줄 멘트(25자 이내, 친근한 존댓말)를 써. "
        '형식: {"comments": {"<store_id>": "멘트"}}',
        [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], max_tokens=400)
    comments = (res or {}).get("comments", {})
    for i in items:
        if str(i["store_id"]) in comments:
            i["ai_comment"] = comments[str(i["store_id"])]
