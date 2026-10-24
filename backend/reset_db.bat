@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
echo 데이터베이스를 비웁니다 (매출, 주문, 대화, 포인트 기록 삭제 / 계정, 가게, 메뉴, 키오스크는 남김)
echo 서버가 켜져 있으면 먼저 끄세요.
python -m app.reset_db
pause
