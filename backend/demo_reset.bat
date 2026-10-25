@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
echo 시연용으로 데이터베이스를 초기화합니다 (손님 계정, 주문, 매출, 대화, 포인트 전부 삭제 / 사장님 계정, 가게, 메뉴, 키오스크는 남김)
echo 서버가 켜져 있으면 먼저 끄세요.
python -m app.reset_db --demo
pause
