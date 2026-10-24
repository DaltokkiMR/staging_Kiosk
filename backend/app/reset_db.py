"""DB 비우기: 모든 기록(매출·주문·결제·대화·포인트)을 지우고 기본 데이터(계정·가게·메뉴·키오스크)만 다시 넣습니다.
실행: python -m app.reset_db   (SEED_HISTORY=true 면 데모 기록까지 채움)"""
from .database import Base, SessionLocal, engine
from .seed import seed


def main() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed(db)
    print("완료: 기록 없는 상태로 초기화했어요.")


if __name__ == "__main__":
    main()
