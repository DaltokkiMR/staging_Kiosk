#!/usr/bin/env bash
# 시연용 DB 초기화 (mac/linux): 손님 계정·주문·매출·대화·포인트 삭제, 사장님 계정·가게·메뉴·키오스크는 남김
# 서버가 켜져 있으면 먼저 끄세요.
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
python -m app.reset_db --demo
