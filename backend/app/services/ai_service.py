"""AI 기능: 키오스크 대화/추천, 손님 성향 분석, 가게 추천, 사장님 인사이트."""
import json
import re
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import ChatLog, MenuItem, Order, OrderItem, OrderStatus, Store, User
from . import llm

# 손님이 원할 수 있는 옵션 카테고리: (손님 말에 나오는 표현, 가게 옵션/태그에서 찾을 키워드)
REQUEST_CATALOG: dict[str, tuple[list[str], list[str]]] = {
    "맵기 조절": (["맵기", "덜 맵", "안 맵게", "맵게 해", "더 맵게", "맵게 가능", "순한 맛"], ["맵"]),
    "단맛 조절": (["덜 달", "단맛", "당도", "안 달게", "덜 단"], ["단맛", "당도", "달"]),
    "양 조절(곱빼기 등)": (["곱빼기", "양 많", "양 적", "대자", "소자", "사이즈", "양 조절"], ["곱빼기", "양 ", "양추가", "사이즈", "대자", "소자"]),
    "재료 빼기": (["빼주", "빼고", "빼 주", "없이 해", "넣지 말"], ["빼"]),
    "채식/비건 메뉴": (["비건", "채식", "고기 없", "베지"], ["비건", "채식"]),
    "포장": (["포장", "테이크아웃", "가져갈"], ["포장"]),
    "아이용 메뉴": (["아이", "어린이", "애기", "키즈"], ["어린이", "키즈", "아이"]),
}

ALLERGEN_WORDS = ["땅콩", "새우", "갑각류", "우유", "유제품", "계란", "달걀", "밀", "글루텐", "대두", "콩", "견과", "조개", "생선", "돼지고기", "소고기"]


# ---------------- 공통 유틸 ----------------
def menu_to_dict(m: MenuItem) -> dict:
    return {
        "id": m.id, "name": m.name, "category": m.category, "price": m.price, "description": m.description,
        "spicy_level": m.spicy_level, "sweetness": m.sweetness, "tags": m.tags, "allergens": m.allergens,
        "options": [{"group": o.group, "name": o.name, "extra_price": o.extra_price} for o in m.options],
    }


def store_option_keywords(store: Store) -> str:
    parts = []
    for m in store.menus:
        parts += [o.group + " " + o.name for o in m.options]
        parts += m.tags
    return " ".join(parts)


def detect_unmet_requests(store: Store, text: str) -> list[str]:
    available = store_option_keywords(store)
    unmet = []
    for name, (phrases, option_keys) in REQUEST_CATALOG.items():
        if any(p in text for p in phrases) and not any(k in available for k in option_keys):
            unmet.append(name)
    return unmet


def usual_items(db: Session, user_id: int, store_id: int, limit: int = 3) -> list[dict]:
    """'늘 먹던 거' — 이 가게에서 가장 많이 주문한 메뉴."""
    rows = (
        db.query(OrderItem.menu_item_id, OrderItem.name, OrderItem.quantity, Order.id)
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.user_id == user_id, Order.store_id == store_id,
                Order.status.in_([OrderStatus.PAID.value, OrderStatus.SERVED.value]))
        .all()
    )
    counter: Counter = Counter()
    names = {}
    orders_with: dict[int, set] = {}
    for menu_id, name, qty, order_id in rows:
        counter[menu_id] += qty
        names[menu_id] = name
        orders_with.setdefault(menu_id, set()).add(order_id)
    return [{"menu_item_id": mid, "name": names[mid], "order_count": len(orders_with[mid]), "total_quantity": q}
            for mid, q in counter.most_common(limit)]


# ---------------- 손님 성향 ----------------
def taste_profile(db: Session, user: User) -> dict:
    rows = (
        db.query(OrderItem, MenuItem, Order.store_id)
        .join(Order, Order.id == OrderItem.order_id)
        .join(MenuItem, MenuItem.id == OrderItem.menu_item_id)
        .filter(Order.user_id == user.id, Order.status.in_([OrderStatus.PAID.value, OrderStatus.SERVED.value]))
        .all()
    )
    prefs = user.preferences or {}
    total_qty = sum(oi.quantity for oi, _, _ in rows)
    if total_qty:
        avg_spicy = sum(m.spicy_level * oi.quantity for oi, m, _ in rows) / total_qty
        avg_sweet = sum(m.sweetness * oi.quantity for oi, m, _ in rows) / total_qty
    else:
        avg_spicy = avg_sweet = None

    categories = Counter()
    menus = Counter()
    stores = Counter()
    tags = Counter()
    less_spicy_option = 0
    for oi, m, store_id in rows:
        categories[m.category] += oi.quantity
        menus[m.name] += oi.quantity
        stores[store_id] += 1
        for t in m.tags:
            tags[t] += oi.quantity
        if any("덜" in o.get("name", "") or "순한" in o.get("name", "") for o in oi.options):
            less_spicy_option += 1

    profile = {
        "order_item_count": total_qty,
        "spicy_preference": prefs.get("spicy", round(avg_spicy, 1) if avg_spicy is not None else None),
        "sweet_preference": prefs.get("sweet", round(avg_sweet, 1) if avg_sweet is not None else None),
        "observed_avg_spicy": round(avg_spicy, 1) if avg_spicy is not None else None,
        "observed_avg_sweet": round(avg_sweet, 1) if avg_sweet is not None else None,
        "favorite_categories": [c for c, _ in categories.most_common(3) if c],
        "favorite_menus": [n for n, _ in menus.most_common(5)],
        "favorite_tags": [t for t, _ in tags.most_common(5)],
        "frequent_store_ids": [s for s, _ in stores.most_common(5)],
        "often_requests_less_spicy": less_spicy_option >= 2,
        "dislikes": prefs.get("dislikes", []),
        "allergies": prefs.get("allergies", []),
    }
    profile["summary"] = _profile_summary(profile)
    return profile


def _profile_summary(p: dict) -> str:
    if p["order_item_count"] == 0 and p["spicy_preference"] is None:
        return "아직 주문 기록이 없어요. 몇 번 주문하면 입맛을 알려드릴게요!"
    ai = llm.complete(
        "너는 음식 취향 분석가야. 손님의 주문 데이터를 보고 친근한 한국어 2문장으로 입맛을 요약해.",
        [{"role": "user", "content": json.dumps(p, ensure_ascii=False)}], max_tokens=200,
    )
    if ai:
        return ai.strip()
    spicy = p["spicy_preference"]
    sweet = p["sweet_preference"]
    s = []
    if spicy is not None:
        s.append("매운 음식을 즐기는" if spicy >= 3 else "순한 맛을 좋아하는" if spicy <= 1 else "적당히 매운 걸 좋아하는")
    if sweet is not None:
        s.append("단 음식 좋아하는" if sweet >= 3 else "달지 않은 음식 선호하는")
    head = ", ".join(s) + " 입맛이에요." if s else "다양하게 드시는 입맛이에요."
    if p["favorite_categories"]:
        head += f" 특히 {', '.join(p['favorite_categories'])} 메뉴를 자주 드셨어요."
    return head


def score_menu(m: MenuItem, profile: dict) -> float:
    score = 0.0
    if profile.get("spicy_preference") is not None:
        score -= abs(m.spicy_level - profile["spicy_preference"]) * 1.0
    if profile.get("sweet_preference") is not None:
        score -= abs(m.sweetness - profile["sweet_preference"]) * 0.6
    if m.category in profile.get("favorite_categories", []):
        score += 1.5
    score += sum(0.5 for t in m.tags if t in profile.get("favorite_tags", []))
    if m.name in profile.get("favorite_menus", []):
        score += 1.0
    if profile.get("max_spicy") is not None and m.spicy_level > profile["max_spicy"]:
        score -= 5
    for bad in profile.get("allergies", []) + profile.get("dislikes", []):
        if bad in m.allergens or bad in m.name or bad in m.description:
            score -= 100
    return score


def recommend_menus(store: Store, profile: dict, limit: int = 3) -> list[MenuItem]:
    menus = [m for m in store.menus if m.is_available]
    return sorted(menus, key=lambda m: score_menu(m, profile), reverse=True)[:limit]


# ---------------- 손님 기억 (가게별) ----------------
def customer_memory(db: Session, user: User, store: Store, exclude_session: str | None = None) -> dict:
    """이 손님이 '이 가게에서' 예전에 한 대화·주문. 가게마다 따로 기억함."""
    q = db.query(ChatLog).filter(ChatLog.store_id == store.id, ChatLog.user_id == user.id, ChatLog.role == "user")
    if exclude_session:
        q = q.filter(ChatLog.session_id != exclude_session)
    logs = q.order_by(ChatLog.created_at.desc()).limit(30).all()
    text = " ".join(l.content for l in logs)
    allergies = [a for a in ALLERGEN_WORDS if a in text]
    allergies = [a for a in allergies if not any(a != b and a in b for b in allergies)]
    less_spicy = any(w in text for w in ["덜 맵", "안 맵", "안맵", "순한", "맵기 조절", "맵지 않"])
    less_sweet = any(w in text for w in ["덜 달", "안 달", "달지 않", "단맛 조절"])
    unmet = list(dict.fromkeys(r for l in logs for r in (l.unmet_requests or [])))
    last_order = (db.query(Order).filter(Order.user_id == user.id, Order.store_id == store.id,
                                         Order.status.in_([OrderStatus.PAID.value, OrderStatus.SERVED.value]))
                  .order_by(Order.paid_at.desc()).first())
    return {
        "past_questions": [l.content for l in logs[:5]],
        "mentioned_allergies": allergies,
        "wants_less_spicy": less_spicy,
        "wants_less_sweet": less_sweet,
        "past_unmet_requests": unmet[:3],
        "usual_items": usual_items(db, user.id, store.id),
        "last_order": [f"{i.name} {i.quantity}개" for i in last_order.items] if last_order else [],
        "last_visit_days_ago": (datetime.now() - last_order.paid_at).days if last_order else None,
    }


def apply_memory(profile: dict | None, mem: dict | None) -> dict:
    """기억을 추천용 입맛 프로필에 반영 (덜 맵게 원했던 손님 → 순한 메뉴 우선, 언급한 알레르기 제외)."""
    p = dict(profile or {})
    if not mem:
        return p
    p["allergies"] = list(dict.fromkeys((p.get("allergies") or []) + mem["mentioned_allergies"]))
    if mem["wants_less_spicy"]:
        p["max_spicy"] = 2  # 지난번에 덜 맵게 원했음 → 많이 매운 메뉴는 뒤로
        p["spicy_preference"] = min(p.get("spicy_preference") if p.get("spicy_preference") is not None else 1, 1)
    if mem["wants_less_sweet"]:
        p["sweet_preference"] = min(p.get("sweet_preference") if p.get("sweet_preference") is not None else 1, 1)
    return p


def welcome_message(user: User, store: Store, mem: dict, recs: list[MenuItem], method_label: str | None) -> str:
    """앱 QR을 찍자마자 보여줄 인사 (지난 대화·주문 기반)."""
    payload = {"name": user.name, "store": store.name, "memory": mem, "recommend": [m.name for m in recs],
               "pay": method_label}
    ai = llm.complete(
        "너는 식당 키오스크의 AI 직원이야. 단골을 기억하는 사장님처럼 손님에게 첫 인사를 해. "
        "지난 대화·주문 기억을 자연스럽게 한 가지만 언급하고 오늘 메뉴를 하나 권해. 2문장, 소리로 읽기 좋게, 괄호·이모지 없이.",
        [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], max_tokens=150)
    if ai:
        return ai.strip()
    usual = mem["usual_items"]
    if not usual and not mem["past_questions"]:
        msg = f"{user.name}님, {store.name}에 처음 오셨네요! 반가워요."
        return msg + (f" 오늘은 {recs[0].name} 어떠세요?" if recs else "")
    msg = f"{user.name}님, 또 오셨네요!"
    if usual:
        msg += f" 늘 드시던 {usual[0]['name']}(으)로 드릴까요?"
    if mem["wants_less_spicy"]:
        msg += " 지난번에 덜 맵게 드시고 싶다고 하셔서, 순한 메뉴도 골라뒀어요."
    elif mem["mentioned_allergies"]:
        msg += f" {', '.join(mem['mentioned_allergies'])} 들어간 메뉴는 빼고 추천할게요."
    return msg


# ---------------- 말로 주문하기 (액션) ----------------
ORDER_WORDS = ["주세요", "줘", "담아", "시킬게", "주문할게", "주문해", "먹을게", "로 할게", "으로 할게", "할게요", "추가"]
CHECKOUT_WORDS = ["결제할게", "결제해", "결제하기", "결제할래", "계산할게", "계산해"]
NUM_WORDS = {"한": 1, "하나": 1, "두": 2, "둘": 2, "세": 3, "셋": 3, "네": 4, "넷": 4, "다섯": 5}
REF_WORDS = {"첫번째": 0, "두번째": 1, "세번째": 2}
# 키오스크에 하는 말이 아닌 짧은 추임새 (주변 대화가 잡혔을 가능성)
FILLERS = {"응", "어", "아", "음", "네", "예", "그래", "아니", "뭐", "야", "오", "와", "헐", "ㅋㅋ", "진짜", "그치", "맞아"}


def _qty_after(compact: str, pos: int) -> int:
    tail = compact[pos:pos + 8]
    m = re.match(r"(\d+)(개|그릇|인분|접시|잔)?", tail)
    if m:
        return max(1, min(int(m.group(1)), 20))
    for w, n in sorted(NUM_WORDS.items(), key=lambda x: -len(x[0])):
        if re.match(w + r"(개|그릇|인분|접시|잔)", tail) or (w in ("하나", "둘", "셋", "넷") and tail.startswith(w)):
            return n
    return 1


def detect_actions(store: Store, msg: str, last_reco_ids: list[int], usual: list[dict]) -> list[dict]:
    """손님 말에서 '담아줘/주세요/결제할게요' 같은 행동을 찾아냄 (LLM 없을 때)."""
    compact = msg.replace(" ", "")
    actions: list[dict] = []
    wants_order = any(w.replace(" ", "") in compact for w in ORDER_WORDS)
    if wants_order:
        taken = compact
        for m in sorted([m for m in store.menus if m.is_available], key=lambda m: -len(m.name)):
            key = m.name.replace(" ", "")
            idx = taken.find(key)
            if idx >= 0:
                actions.append({"type": "add_to_cart", "menu_item_id": m.id, "quantity": _qty_after(compact, idx + len(key))})
                taken = taken[:idx] + "#" * len(key) + taken[idx + len(key):]  # '로제떡볶이' 안의 '떡볶이' 중복 방지
        if not actions:
            if any(w in compact for w in ["늘먹던", "먹던거", "항상먹는", "평소"]) and usual:
                actions.append({"type": "add_to_cart", "menu_item_id": usual[0]["menu_item_id"], "quantity": 1})
            elif last_reco_ids:
                ref = next((i for w, i in REF_WORDS.items() if w in compact and i < len(last_reco_ids)), None)
                if ref is None and any(w in compact for w in ["그걸로", "그거", "그메뉴", "그것"]):
                    ref = 0
                if ref is not None:
                    actions.append({"type": "add_to_cart", "menu_item_id": last_reco_ids[ref], "quantity": 1})
    if any(w in compact for w in CHECKOUT_WORDS):
        actions.append({"type": "checkout"})
    return actions


def _action_reply(store: Store, actions: list[dict]) -> str:
    by_id = {m.id: m for m in store.menus}
    added = [f"{by_id[a['menu_item_id']].name} {a['quantity']}개" for a in actions if a["type"] == "add_to_cart"]
    parts = [", ".join(added) + " 담았어요!"] if added else []
    if any(a["type"] == "checkout" for a in actions):
        parts.append("결제 화면으로 넘어갈게요.")
    elif added:
        parts.append("더 필요하신 거 있으세요?")
    return " ".join(parts)


def looks_like_background(text: str) -> bool:
    """추임새 한두 마디 등 손님이 키오스크에 한 말로 보기 어려운 경우."""
    t = re.sub(r"[^가-힣a-zA-Z0-9 ]", "", text).strip()
    return not t or t in FILLERS or (len(t.replace(" ", "")) <= 2 and t not in {"추천", "결제"})


def _shorten(text: str) -> str:
    """소리로 읽기 좋게: 괄호 제거, 두 문장까지."""
    text = re.sub(r"\([^)]*\)", "", text)
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(sentences[:2]).strip()


# ---------------- 키오스크 대화 ----------------
def kiosk_chat(db: Session, store: Store, session_id: str, message: str, user: User | None,
               spoken: bool = False) -> dict:
    """spoken=True: 음성 대화(답을 소리로 읽어줌) → 짧게, 그리고 주변 대화가 잡힌 것 같으면 ignored."""
    history = (
        db.query(ChatLog).filter_by(store_id=store.id, session_id=session_id)
        .order_by(ChatLog.id.desc()).limit(10).all()
    )[::-1]
    mem = customer_memory(db, user, store, exclude_session=session_id) if user else None
    profile = apply_memory(taste_profile(db, user), mem) if user else None
    usual = mem["usual_items"] if mem else []
    menus = [m for m in store.menus if m.is_available]

    system = (
        f"너는 '{store.name}' 식당의 친절한 사장님처럼 손님을 응대하는 키오스크 AI야. "
        "손님의 질문(맵기, 단맛, 알레르기, 양, 추천 등)에 메뉴 정보에 근거해서만 짧고 따뜻하게 답해. "
        "메뉴에 없는 정보는 지어내지 말고 '직원에게 확인해 주세요'라고 해. "
        "단골 손님이면 '늘 드시던 거로 드릴까요?'처럼 먼저 챙겨줘. "
        "손님이 메뉴를 달라고 하면(주세요, 담아줘, 그걸로 할게요 등) actions 에 add_to_cart 를, 결제하겠다고 하면 checkout 을 넣어.\n"
        + ("지금은 음성 대화라 답이 소리로 읽혀. 1~2문장, 짧고 자연스러운 말투로. 목록·괄호·이모지 금지. "
           "식당 주문·메뉴와 상관없는 옆 사람끼리의 대화나 잡담이 잘못 들어온 것 같으면 ignore 를 true 로.\n\n"
           if spoken else "\n")
        +
        f"[가게 설명] {store.description}\n"
        f"[메뉴] {json.dumps([menu_to_dict(m) for m in menus], ensure_ascii=False)}\n"
        f"[손님 성향] {json.dumps(profile, ensure_ascii=False) if profile else '알 수 없음(비회원)'}\n"
        f"[이 가게 단골 메뉴] {json.dumps(usual, ensure_ascii=False)}\n"
        f"[이 손님이 이 가게에서 예전에 한 대화·주문] {json.dumps(mem, ensure_ascii=False) if mem else '없음'}\n"
        "예전 대화에서 말한 알레르기·맵기 취향은 기억하고 반영해.\n\n"
        '출력 형식: {"reply": "손님에게 할 말", "recommended_menu_ids": [메뉴 id], '
        '"unmet_requests": ["손님이 원했지만 가게에 없는 옵션/메뉴를 짧은 명사구로. 예: 맵기 조절, 곱빼기. 없으면 빈 배열"], '
        '"actions": [{"type": "add_to_cart", "menu_item_id": 메뉴id, "quantity": 수량} 또는 {"type": "checkout"}. 없으면 빈 배열], '
        '"ignore": false}'
    )
    messages = [{"role": h.role, "content": h.content} for h in history] + [{"role": "user", "content": message}]
    by_id = {m.id: m for m in menus}
    if spoken and looks_like_background(message):
        return {"reply": "", "recommended_menus": [], "unmet_requests": [], "actions": [], "ignored": True}

    last_reco = next((h.meta.get("recommended_menu_ids", []) for h in reversed(history)
                      if h.role == "assistant" and h.meta), [])
    result = llm.complete_json(system, messages, max_tokens=600)
    if result and result.get("ignore") and spoken:
        return {"reply": "", "recommended_menus": [], "unmet_requests": [], "actions": [], "ignored": True}

    if result is None:
        actions = detect_actions(store, message, last_reco, usual)
        if actions:
            result = {"reply": _action_reply(store, actions), "recommended_menu_ids": [], "unmet_requests": [],
                      "actions": actions}
        else:
            result = _rule_based_chat(store, message, profile, usual)
            if spoken:
                result["reply"] = _shorten(result["reply"])

    valid_ids = {m.id for m in menus}
    rec_ids = [i for i in result.get("recommended_menu_ids", []) if i in valid_ids][:3]
    unmet = list(dict.fromkeys((result.get("unmet_requests") or []) + detect_unmet_requests(store, message)))
    reply = result.get("reply") or "죄송해요, 다시 한 번 말씀해 주시겠어요?"
    actions = []
    for a in result.get("actions") or []:
        if a.get("type") == "checkout":
            actions.append({"type": "checkout"})
        elif a.get("type") == "add_to_cart" and a.get("menu_item_id") in valid_ids:
            actions.append({"type": "add_to_cart", "menu_item_id": a["menu_item_id"],
                            "quantity": max(1, min(int(a.get("quantity") or 1), 20))})

    uid = user.id if user else None
    db.add(ChatLog(store_id=store.id, user_id=uid, session_id=session_id, role="user", content=message, unmet_requests=unmet))
    db.add(ChatLog(store_id=store.id, user_id=uid, session_id=session_id, role="assistant", content=reply,
                   meta={"recommended_menu_ids": rec_ids} if rec_ids else {}))
    db.commit()
    return {"reply": reply, "recommended_menus": [by_id[i] for i in rec_ids], "unmet_requests": unmet,
            "actions": actions, "ignored": False}


def _rule_based_chat(store: Store, msg: str, profile: dict | None, usual: list[dict]) -> dict:
    """LLM 키가 없을 때 쓰는 간단한 규칙 기반 응답."""
    menus = [m for m in store.menus if m.is_available]
    found = [a for a in ALLERGEN_WORDS if a in msg] + [a for a in (profile or {}).get("allergies", []) if a not in msg]
    excluded = [a for a in found if not any(a != b and a in b for b in found)]  # '땅콩' 안의 '콩' 중복 제거
    pool = [m for m in menus if not any(a in m.allergens or a in m.name for a in excluded)]
    reply, picks = "", []
    option_hits = [(m, o) for m in pool for o in m.options if o.name in msg or (len(o.group) >= 2 and o.group in msg)]

    unmet = detect_unmet_requests(store, msg)
    if option_hits:
        picks = list(dict.fromkeys(m for m, _ in option_hits))[:3]
        reply = "네, 가능해요! " + ", ".join(
            f"{m.name}은(는) '{o.name}'" + (f"(+{o.extra_price:,}원)" if o.extra_price else "") for m, o in option_hits[:3]
        ) + " 선택하실 수 있어요."
    elif unmet:
        alt = ""
        if "맵기 조절" in unmet or "아이용 메뉴" in unmet:
            picks = sorted(pool, key=lambda m: m.spicy_level)[:3]
            alt = " 대신 덜 매운 " + ", ".join(f"{m.name}(맵기 {m.spicy_level})" for m in picks) + " 어떠세요?"
        elif "단맛 조절" in unmet:
            picks = sorted(pool, key=lambda m: m.sweetness)[:3]
            alt = " 대신 달지 않은 " + ", ".join(m.name for m in picks) + " 어떠세요?"
        reply = f"죄송해요, 지금은 {', '.join(unmet)}이(가) 어려워요.{alt} 손님 의견은 사장님께 꼭 전달할게요!"
    elif any(w in msg for w in ["안 매운", "안매운", "덜 매운", "순한", "맵지 않", "안 맵"]):
        picks = sorted(pool, key=lambda m: m.spicy_level)[:3]
        reply = "맵지 않은 메뉴로는 " + ", ".join(f"{m.name}(맵기 {m.spicy_level})" for m in picks) + " 추천드려요."
    elif "매워" in msg or "매운" in msg or "맵" in msg:
        named = [m for m in pool if m.name in msg]
        if named:
            m = named[0]
            level = ["전혀 안 매워요", "거의 안 매워요", "살짝 매콤해요", "적당히 매워요", "꽤 매워요", "아주 매워요"][m.spicy_level]
            reply = f"{m.name}은(는) {level}. (맵기 {m.spicy_level}/5)"
            picks = [m]
        else:
            picks = sorted(pool, key=lambda m: -m.spicy_level)[:3]
            reply = "매운 걸 좋아하시면 " + ", ".join(m.name for m in picks) + " 어떠세요?"
    elif any(w in msg for w in ["덜 단", "안 단", "달지 않", "안달", "덜 달"]):
        picks = sorted(pool, key=lambda m: m.sweetness)[:3]
        reply = "달지 않은 메뉴로는 " + ", ".join(m.name for m in picks) + " 있어요."
    elif "달" in msg or "단 " in msg:
        picks = sorted(pool, key=lambda m: -m.sweetness)[:3]
        reply = "달달한 메뉴로는 " + ", ".join(m.name for m in picks) + " 있어요."
    elif any(w in msg for w in ["늘 먹던", "먹던 거", "항상", "저번"]) and usual:
        picks = [m for m in pool if m.id == usual[0]["menu_item_id"]]
        reply = f"늘 드시던 {usual[0]['name']}(으)로 드릴까요?"
    else:
        picks = recommend_menus(store, profile, 3) if profile else pool[:3]
        reply = "오늘은 " + ", ".join(m.name for m in picks) + " 추천드려요!"
        if usual:
            reply = f"늘 드시던 {usual[0]['name']}도 있고요, " + reply

    if excluded:
        reply += f" ({', '.join(excluded)} 들어간 메뉴는 뺐어요. 정확한 성분은 직원에게 한 번 더 확인해 주세요.)"
    return {"reply": reply, "recommended_menu_ids": [m.id for m in picks], "unmet_requests": unmet}


# ---------------- 사장님 인사이트 ----------------
def owner_insights(db: Session, store: Store, days: int = 30) -> dict:
    since = datetime.now() - timedelta(days=days)
    logs = db.query(ChatLog).filter(ChatLog.store_id == store.id, ChatLog.role == "user",
                                    ChatLog.created_at >= since).all()
    unmet = Counter()
    examples: dict[str, list[str]] = {}
    for log in logs:
        for req in log.unmet_requests or []:
            unmet[req] += 1
            examples.setdefault(req, [])
            if len(examples[req]) < 3:
                examples[req].append(log.content)

    topics = Counter()
    topic_words = {"맵기": ["맵", "매운", "매워"], "단맛": ["달", "단맛"], "알레르기/성분": ALLERGEN_WORDS,
                   "추천 요청": ["추천", "뭐가 맛", "인기"], "양": ["양", "곱빼기"], "가격": ["얼마", "가격", "싸"]}
    for log in logs:
        for topic, words in topic_words.items():
            if any(w in log.content for w in words):
                topics[topic] += 1

    unmet_list = [{"request": r, "count": c, "examples": examples[r]} for r, c in unmet.most_common()]
    data = {"period_days": days, "total_questions": len(logs), "unmet_requests": unmet_list,
            "question_topics": dict(topics.most_common()),
            "menus": [menu_to_dict(m) for m in store.menus]}

    ai = llm.complete_json(
        "너는 소상공인 식당 컨설턴트야. 키오스크에서 손님들이 한 질문 통계를 보고 사장님께 드릴 조언을 써. "
        '형식: {"summary": "2~3문장 요약", "suggestions": [{"title": "짧은 제목", "detail": "구체적인 실행 방법", "priority": "high|medium|low"}]}',
        [{"role": "user", "content": json.dumps(data, ensure_ascii=False)}], max_tokens=900,
    )
    if ai is None:
        suggestions = [{
            "title": f"'{u['request']}' 옵션 추가",
            "detail": f"최근 {days}일간 손님 {u['count']}명이 '{u['request']}'을(를) 찾았어요. 메뉴 옵션에 추가하는 걸 고려해보세요.",
            "priority": "high" if u["count"] >= 5 else "medium",
        } for u in unmet_list]
        top = topics.most_common(1)
        summary = (f"최근 {days}일간 키오스크 질문 {len(logs)}건 중 "
                   + (f"'{top[0][0]}' 관련 질문이 가장 많았어요." if top else "특별히 많은 주제는 없었어요."))
        ai = {"summary": summary, "suggestions": suggestions}

    return {"store_id": store.id, "period_days": days, "total_questions": len(logs),
            "unmet_requests": unmet_list, "question_topics": data["question_topics"],
            "summary": ai.get("summary", ""), "suggestions": ai.get("suggestions", [])}
