"""Staging 테이블오더 백엔드 — FastAPI 진입점.

실행:  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
화면:  http://localhost:8000          (키오스크 / 손님 앱 / 사장님 화면 링크)
문서:  http://localhost:8000/docs
"""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from .config import BASE_DIR, settings
from .database import Base, SessionLocal, engine, get_db
from .models import PAY_TYPE_LABELS, User
from .routers import auth, consumer, kiosk, map, owner, stores
from .seed import seed
from .services import llm, stt
from .services.payment_service import QR_PREFIX, issue_qr_token


def _reset_if_schema_changed() -> None:
    """[데모용] 개발 중 모델이 바뀌어 예전 SQLite DB와 컬럼이 안 맞으면 DB를 새로 만듭니다.
    (실서비스에서는 Alembic 마이그레이션을 쓰세요.)"""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing:
            continue
        cols = {c["name"] for c in insp.get_columns(table.name)}
        if not {c.name for c in table.columns} <= cols:
            Base.metadata.drop_all(bind=engine)
            return


@asynccontextmanager
async def lifespan(app: FastAPI):
    _reset_if_schema_changed()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(title="Staging 테이블오더 API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth.router, stores.router, map.router, consumer.router, kiosk.router, owner.router):
    app.include_router(r)


@app.get("/api/health", tags=["기타"])
def health():
    return {"status": "ok", "llm_enabled": llm.is_enabled(), "demo_mode": settings.DEMO_MODE,
            "stt_enabled": stt.is_enabled(), "stt_provider": stt.provider()}


@app.get("/api/pay-types", tags=["기타"])
def pay_types():
    return [{"value": k.value, "label": v} for k, v in PAY_TYPE_LABELS.items()]


@app.post("/api/demo/qr", tags=["기타"])
def demo_qr(email: str = "user@demo.com", db: Session = Depends(get_db)):
    """[데모 전용] 휴대폰 없이 키오스크 결제를 시연할 때, 데모 손님의 결제 QR을 대신 발급합니다.
    DEMO_MODE=false 이면 비활성화됩니다."""
    if not settings.DEMO_MODE:
        raise HTTPException(404)
    user = db.query(User).filter_by(email=email).first()
    if user is None:
        raise HTTPException(404, "데모 손님 계정이 없습니다.")
    t = issue_qr_token(db, user, None, True)
    return {"qr_payload": QR_PREFIX + t.token, "name": user.name}


# ---------- 프론트엔드 정적 파일 (같은 서버에서 화면까지 제공) ----------
ROOT = BASE_DIR.parent
FRONTENDS = [("kiosk", "Kiosk", "키오스크 / 테이블오더", "매장 테이블·키오스크 화면"),
             ("consumer", "consumer", "손님 앱", "휴대폰으로 열기 · 결제 QR · 입맛 추천"),
             ("market", "market", "사장님", "매출 · AI 손님 의견 · 메뉴 관리")]

if (ROOT / "shared").is_dir():  # 공통 글꼴 등
    app.mount("/shared", StaticFiles(directory=ROOT / "shared"), name="shared")

for url, folder, _, _ in FRONTENDS:
    path = ROOT / folder
    if path.is_dir():
        app.mount(f"/{url}", StaticFiles(directory=path, html=True), name=url)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index():
    cards = "".join(
        f'<a href="/{u}/"><b>{t}</b><span>{d}</span></a>' for u, _, t, d in FRONTENDS
    )
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Staging 데모</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/web/static/pretendard.min.css">
<style>body{{margin:0;font-family:Pretendard,sans-serif;background:#FBF6EF;color:#2B1D14;display:grid;place-items:center;min-height:100vh}}
main{{width:min(560px,92vw)}}h1{{font-size:28px;margin:0 0 4px}}p{{color:#7A6555;margin:0 0 24px}}
a{{display:flex;flex-direction:column;gap:4px;padding:20px 22px;margin-bottom:12px;background:#fff;border-radius:16px;
text-decoration:none;color:inherit;border:1px solid #EADFD3}}a:hover{{border-color:#E2572B}}b{{font-size:18px}}span{{color:#7A6555;font-size:14px}}
small{{display:block;margin-top:16px;color:#9A8676}}</style></head><body><main>
<h1>Staging 테이블오더</h1><p>데모 화면을 골라주세요.</p>{cards}
<small>API 문서: <a style="display:inline;padding:0;border:0;background:none" href="/docs">/docs</a></small></main></body></html>"""
