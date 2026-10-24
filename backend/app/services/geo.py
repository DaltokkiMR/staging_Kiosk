"""거리 계산, 영업 여부."""
import math
from datetime import datetime, time

from ..models import Store

WALK_M_PER_MIN = 67  # 성인 보행 약 4km/h


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def walk_minutes(m: float) -> int:
    return max(1, round(m / WALK_M_PER_MIN))


def store_distance(store: Store, lat: float | None, lng: float | None) -> float | None:
    if lat is None or lng is None or store.lat is None or store.lng is None:
        return None
    return distance_m(lat, lng, store.lat, store.lng)


def _t(s: str) -> time:
    h, m = s.split(":")
    return time(int(h) % 24, int(m))


def is_open(store: Store, at: datetime | None = None) -> bool:
    at = at or datetime.now()
    o, c, now_t = _t(store.open_time or "00:00"), _t(store.close_time or "23:59"), at.time()
    closed = set(store.closed_weekdays or [])
    if o <= c:  # 같은 날 영업
        return at.weekday() not in closed and o <= now_t < c
    # 자정 넘김 (예: 18:00 ~ 02:00): 새벽 시간은 전날 영업으로 본다
    if now_t >= o:
        return at.weekday() not in closed
    if now_t < c:
        return (at.weekday() - 1) % 7 not in closed
    return False


def hours_text(store: Store) -> str:
    days = "월화수목금토일"
    txt = f"{store.open_time} ~ {store.close_time}"
    if store.closed_weekdays:
        txt += " · " + ",".join(days[d] for d in sorted(store.closed_weekdays)) + " 휴무"
    return txt
