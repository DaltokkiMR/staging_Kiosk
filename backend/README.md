# Staging 테이블오더 백엔드 (Python / FastAPI)

사장님 앱·웹, 소비자 앱·웹, 키오스크(테이블오더)가 함께 쓰는 서버입니다.

## 실행

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows (mac/linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env           # 필요하면 ANTHROPIC_API_KEY 입력
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- 데모 화면 모음: http://localhost:8000 (키오스크 `/kiosk/`, 손님 앱 `/consumer/`, 사장님 `/market/`)
- API 문서(직접 눌러보며 테스트): http://localhost:8000/docs
- Windows에서는 `run.bat` 더블클릭으로도 실행됩니다.
- 휴대폰으로 손님 앱을 열려면 같은 와이파이에서 `http://<PC의 IP>:8000/consumer/`
- 처음 실행하면 `staging.db`(SQLite)가 생기고 데모 데이터가 들어갑니다. 초기화하려면 파일을 지우고 재시작.
- 테스트: `pytest -q`

| 데모 계정 | 값 |
|---|---|
| 사장님 | owner@demo.com / 1234 |
| 손님 | user@demo.com / 1234 (평일 점심 한식·저녁 분식·주말 카페 패턴) |
| 다른 가맹점 사장님 | owner2@demo.com / 1234 |
| 키오스크 헤더 | `X-Kiosk-Key: demo-kiosk-key` (도도식당 1번 테이블) |

`ANTHROPIC_API_KEY`가 없으면 AI 기능은 규칙 기반으로 동작합니다(데모용). 키를 넣으면 Claude가 응답합니다.

## 데모 시나리오 (PC 한 대로)

1. 손님 앱(`/consumer/`) 로그인 → 바로 결제 QR이 뜸 → **QR 내용 복사**
2. 키오스크(`/kiosk/`) → **QR로 단골 확인** → 직접 입력에 붙여넣기 → "늘 드시던 김치찌개로 드릴까요?"
3. **AI에게 물어보기** → "맵기 조절 되나요?" → 사장님께 자동 전달
4. 메뉴 담고 **주문하고 결제하기 → 앱으로 결제** → QR 붙여넣기 (또는 **데모 손님 QR로 진행**)
   → 포인트 차감 → 카카오페이 잔액부족 → 지역화폐로 결제 성공. 손님 앱에도 결과가 뜸
5. 사장님(`/market/`) → 매출, **AI 손님 의견**에서 "맵기 조절 5명" → **옵션 추가** → 키오스크에 바로 반영

웹캠이 있으면 키오스크에서 손님 앱 QR을 카메라로 바로 찍을 수도 있어요.

## 인증

- 사장님/손님: `POST /api/auth/login` → `Authorization: Bearer <token>`
- 키오스크: 사장님이 `POST /api/owner/stores/{id}/kiosks`로 등록 → 받은 `api_key`를 `X-Kiosk-Key` 헤더로 사용

## 핵심 흐름 0 — 키오스크 첫 화면 "UNIORDER 앱 있나요?"

```
[키오스크 첫 화면]  왼쪽: 카메라 QR 인식      오른쪽: [없습니다] → 바로 주문(비회원)
[손님 앱]          결제 탭에서 카드를 골라 QR 표시 (카드 안 고르면 '우선순위대로')
QR 찍음  →  POST /api/kiosk/session/start {qr_payload}
           · 고른 결제카드가 이번 방문 결제까지 유지 (customer_session, 30분, 이 키오스크에서만)
           · 이 가게에서의 지난 대화·주문 기억 → "늘 드시던 김치찌개로 드릴까요? 지난번에 덜 맵게…" + 추천 메뉴
           · 손님 앱엔 '키오스크와 연결됐어요' 표시
결제할 때  ① 결제 계속하기  POST /api/kiosk/payments/session {order_id, customer_session}
          ② 결제 방식 바꾸기 POST /api/kiosk/session/methods → 카드 고르면 /payments/session {…, method_id}
                           (또는 '다른 카드 QR 찍기' → /payments/qr)
          ③ 카드결제       POST /api/kiosk/payments/card {order_id, customer_session?}  ※ 단말기는 데모(바로 승인)
결제 완료 → 손님 앱에도 결과 표시 → 키오스크는 첫 화면으로 (2분 동안 터치 없으면 자동으로도)
```

- 대화 기억은 **가게별**: 도도식당에서 한 말은 도도분식 키오스크에서 안 보여요. (`ai_service.customer_memory`)
- 지난번에 말한 알레르기·"덜 맵게"는 이번에 말 안 해도 추천과 AI 답변에 반영돼요.

## 핵심 흐름 1 — 앱으로 결제 (통합 결제)

```
[손님 앱]  POST /api/me/payment-qr  {}                → qr_payload 를 QR로 표시 (60초, 1회용)
           (카드 골라서 결제: {"method_id": 3})
[키오스크] '앱으로 결제' → QR 스캔
           POST /api/kiosk/payments/qr {order_id, qr_payload}
[서버]     ① 포인트(그 가게 전용) 먼저 차감
           ② 남은 금액을 등록 결제수단 우선순위대로 시도 (실패하면 다음 수단)
              - 가게가 지원하지 않는 수단은 건너뜀
              - 지역화폐는 가게 지역과 같아야 사용
           ③ 성공 시 결제금액의 point_rate 만큼 포인트 적립
[손님 앱]  GET /api/me/payment-qr/{token} 폴링 → 결제 결과 표시
```

결제수단: 신용카드, 체크카드, 삼성페이, 네이버페이, 카카오페이, 지역화폐, 온누리상품권, 포인트.
`app/services/payment_gateways.py`에 결제사별 어댑터가 있고 지금은 **Mock**입니다. 실제 연동 시 각 `charge()`만 PG/페이사 API 호출로 바꾸면 됩니다.

데모 시나리오(손님 계정): 카카오페이(잔액 5,000) → 마포사랑상품권 → 신한카드 → 온누리 순서.
22,000원 주문 시 포인트 차감 → 카카오페이 잔액부족 실패 → 지역화폐로 결제 성공 흐름을 볼 수 있습니다.
카드번호 끝자리가 `0000`이면 거절되도록 해두었습니다.

## 핵심 흐름 2 — AI

| 대상 | API | 내용 |
|---|---|---|
| 키오스크 | `POST /api/kiosk/ai/chat` | "이거 매워요?", "덜 단 거 없어요?" 대화 + 메뉴 추천. 손님이 원하지만 없는 옵션(맵기 조절 등)을 자동 기록 |
| 키오스크 | `POST /api/kiosk/identify` | QR 찍으면 단골 인식 → "늘 드시던 김치찌개로 드릴까요?" |
| 소비자 앱 | `GET /api/me/taste-profile` | 주문 기록 기반 입맛 분석 (맵기·단맛·좋아하는 카테고리) |
| 소비자 앱 | `GET /api/me/recommendations/stores` | 입맛에 맞는 가게 추천 |
| 소비자 앱 | `GET /api/me/recommendations/stores/{id}` | 그 가게에서 늘 먹던 메뉴 + 추천 메뉴 |
| 사장님 | `GET /api/owner/stores/{id}/insights` | 손님 질문 분석 → "맵기 조절 요청 4건, 옵션 추가 추천" |

## 핵심 흐름 3 — 손님 지도 + 행동 패턴 추천

| API | 내용 |
|---|---|
| `GET /api/map/stores?lat=&lng=` | 지도 핀용 가맹점 목록 (간단 정보: 이름·분류·한줄소개·영업중·거리·도보 분·가격대·대표메뉴). 지도 영역(`sw_lat,sw_lng,ne_lat,ne_lng`), 반경(`radius_m`), `category`, `q`, `open_now` 필터. 로그인 토큰을 보내면 `recommend`(순위·태그·이유)가 붙고 상위 3곳은 `highlight: true` |
| `GET /api/map/stores/{id}?lat=&lng=` | 핀을 눌렀을 때 상세: 주소·전화·영업시간·결제수단·인기메뉴·전체 메뉴. 로그인 시 `for_me`: 늘 먹던 거, 나에게 맞는 메뉴 + 이유, 포인트, 이 가게를 추천하는 이유 |
| `GET /api/me/behavior` | 행동 패턴: 주로 먹는 시간대·요일, 방문 주기, 자주 가는 가게, 시간대별 즐겨 먹는 종류 |
| `GET /api/me/recommendations/stores?lat=&lng=` | 가게 추천 (이유·태그 포함) |

추천 점수(`app/services/recommend.py`)는 아래 신호를 섞어서 계산하고, 응답의 `signals`에서 각 값을 볼 수 있어요.

- 입맛 적합도 · 단골도(최근 방문일수록 가중) · **지금 시간대 패턴**(점심엔 한식, 저녁엔 분식…) · 평일/주말 패턴
- 비슷한 손님(나와 같은 가게에 다니는 손님들이 가는 곳) · 최근 인기 · 거리 · 아직 안 가본 좋아하는 종류(보너스)
- 영업 시간이 아니면 점수를 낮춤

태그: `단골` `지금 딱` `취향저격` `새로운 발견` `가까운` `인기`. LLM 키가 있으면 추천마다 `ai_comment` 한 줄 멘트가 추가됩니다.
데모 지도 중심: 서울 마포구 망원동 (37.5555, 126.9100), 가맹점 9곳. 지도 SDK(카카오맵·네이버지도)는 프론트에서 붙이면 됩니다.

## 핵심 흐름 4 — 음성 대화 (Whisper · GroqCloud)

키오스크에서 🎤를 한 번 누르면 **종료를 누를 때까지 계속 대화**가 이어져요. (글자 입력도 언제든 가능)

```
듣기 → 말이 끝나면(0.85초 조용) 자동 전송 → Whisper 받아쓰기 → AI 답변 → 소리로 읽어줌 → 다시 듣기 …
```

- 말로 주문: "김치찌개 두 개 주세요" → 장바구니에 담김, "첫 번째 걸로 주세요"(방금 추천받은 것), "늘 먹던 거로 주세요", "결제할게요" → 결제 화면
  → 응답의 `actions`: `{"type":"add_to_cart","menu_item_id","quantity"}`, `{"type":"checkout"}` (글자 대화에서도 동일)
- AI가 말하는 중에 손님이 크게 말하거나 말풍선을 탭하면 끊고 바로 듣기
- 45초 동안 말이 없으면 자동 종료

**잡음·다른 사람 목소리 처리**

| 단계 | 방법 |
|---|---|
| 브라우저 | 에코 제거 · 잡음 제거 · 자동 음량 켜기 |
| 키오스크 (`Kiosk/app.js`의 `VAD`) | 목소리 대역(150~3800Hz)만 따로 측정 / 시작 0.7초 동안 매장 소음 측정 후 계속 따라감 / 소음보다 3배 이상 큰 소리만 손님 목소리로 판단(멀리서 말하는 사람은 작음) / 0.2초 이상 이어져야 말 시작(그릇 소리 무시) / 실제 목소리 0.35초 미만이면 버림 / AI가 말하는 동안은 훨씬 크게 말해야 끼어들기(스피커 소리 오인 방지) |
| 서버 (`stt.py`) | Whisper 구간별 신뢰도(`no_speech_prob`, `avg_logprob`)로 잡음 구간 삭제 / "시청해 주셔서 감사합니다" 같은 무음 환각 문장 삭제 |
| 서버 (`ai_service.py`) | "응", "아니" 같은 추임새만 들리면 무시 / LLM 키가 있으면 주문과 상관없는 옆 사람 대화도 판단해 무시 → 응답 `ignored: true` (화면에 안 보이고 계속 듣기) |

매장마다 소음이 다르니 `VAD` 숫자(`START_X`, `END_MS` 등)를 현장에서 조정하면 돼요.

| API | 내용 |
|---|---|
| `POST /api/kiosk/ai/voice` (multipart: `audio`, `session_id`, `customer_session`) | 한 마디 음성 → `transcript`, `reply`(짧게), `recommended_menus`, `actions`, `ignored` |
| `POST /api/kiosk/ai/chat` (JSON) | 글자 대화 (같은 `session_id`면 음성과 대화가 이어짐) |
| `POST /api/kiosk/stt` (multipart: `audio`) | 받아쓰기만 |

- 설정: `.env`의 `GROQ_API_KEY` (기본 `STT_PROVIDER=groq`, `whisper-large-v3-turbo`). OpenAI는 `STT_PROVIDER=openai` + `OPENAI_API_KEY`, 키 없이 PC에서 돌리려면 `STT_PROVIDER=local` + `pip install openai-whisper` + ffmpeg
- 마이크는 `localhost` 또는 `https`에서만 켜져요.

## 전체 API 목록

**인증** `/api/auth` — signup, login, me, me/preferences(입맛·알레르기 설정)

**공개** `/api/stores` — 가게 목록/상세, 메뉴
**지도** `/api/map` — stores (핀 목록), stores/{id} (상세)

**소비자** `/api/me`
- payment-methods (조회/등록/삭제), payment-methods/priority (우선순위 변경)
- payment-qr (발급), payment-qr/{token} (결과 확인)
- points (가게별 포인트), orders (주문내역)
- taste-profile, behavior, recommendations/...

**키오스크** `/api/kiosk` — store, menus, orders, payments/qr, identify, ai/chat, ai/voice, stt

**사장님** `/api/owner`
- stores (생성/수정: 지원 결제수단, 포인트 적립률, 위치 lat/lng, 영업시간, 휴무일, 한줄소개)
- menus (추가/수정/품절/숨김), menus/{id}/options (옵션 추가), options/{id} (삭제)
- kiosks (기기 등록), orders (주문 목록, 상태 변경)
- sales (기간별 매출, 일별/시간대별/메뉴별/결제수단별, 재방문 손님)
- insights (AI 손님 의견 분석)

## 폴더 구조

```
app/
  main.py            서버 진입점
  config.py          환경설정 (.env)
  models.py          DB 테이블
  schemas.py         요청/응답 형식
  security.py        로그인/권한/키오스크 인증
  seed.py            데모 데이터
  routers/           auth, stores, consumer, kiosk, owner
  services/
    payment_gateways.py  결제사별 어댑터 (Mock)
    payment_service.py   QR 결제·우선순위·포인트
    ai_service.py        키오스크 대화, 입맛 분석, 메뉴 추천, 사장님 인사이트
    recommend.py         행동 패턴 분석 + 가게 추천
    geo.py               거리·도보시간·영업 여부
    stt.py               음성 인식 (Whisper: Groq / OpenAI / 로컬)
    llm.py               Claude API 호출
    analytics.py         매출 통계
tests/test_flow.py   전체 흐름 테스트
```

## 실서비스 전에 할 것

- 결제 Mock → 실제 PG/페이사 연동, 결제 실패 시 부분 승인 취소 처리
- 카드 정보는 PG 빌링키만 저장 (원문 카드번호 저장 금지)
- SQLite → PostgreSQL, 마이그레이션(Alembic)
- `SECRET_KEY` 변경, CORS 도메인 제한, `DEMO_MODE=false`

## 시연 준비 (손님 회원가입부터 깨끗하게)
1. 서버를 끄고 `demo_reset.bat`(Windows) 또는 `./demo_reset.sh`(mac) 실행 = `python -m app.reset_db --demo`
   → 사장님 계정(owner@demo.com / 1234)·가게·메뉴·키오스크만 남고 **손님 계정 0명, 주문·매출·대화·포인트 0건**
2. `.env`에 `ANTHROPIC_API_KEY` 넣고 서버 실행
3. 손님 앱 → **계정이 없으신가요?** → 이름·생년월일·성별·휴대폰·이메일·비밀번호·약관이 미리 채워져 있음 → 가입하기
   (미리 채울 값은 `consumer/app.js`의 `SIGNUP_DEMO`)
4. 가입하면 바로 **입맛 설정**: 매운맛·짠맛·신맛·단맛·느끼한 맛(0 전혀 못 먹어요 ~ 5 아주 잘 먹어요), 알레르기, 식단,
   좋아요·싫어요·특이사항 줄글 → 저장하면 AI가 글에서 재료를 뽑아 추천에서 빼거나 더함
5. 키오스크에서 손님 앱 QR(또는 **데모 손님 QR** = 방금 가입한 손님) → 설정한 알레르기·싫어하는 것을 짚으며 인사하고 맞는 메뉴 추천
6. 키오스크 AI에게 "유아 음식 있나요?" → 사장님이 적어둔 **매장 안내**(사장님 › 가게 설정)를 보고 "유아 메뉴는 없지만 앞접시 드려요, 버터 갈릭 파스타는 안 매워요" 식으로 답함
   → 사장님 화면 오른쪽 위에 **실시간 알림**(5초 안) + 'AI 손님 의견'에 '유아·어린이 메뉴 1명'으로 쌓임
   (롤링파스타·도도식당은 매장 안내가 미리 들어가 있음, `app/seed.py`의 `ROLLING_NOTICE`)
7. 포인트: 첫 결제에 적립(롤링파스타 5%) → 다음 결제에서 포인트 먼저 차감
- 데모 모드에서는 가입하자마자 데모 결제수단(카카오페이 5,000원 → 지역화폐 → 신한카드 → 온누리)이 들어가서 결제까지 바로 이어져요.
- 리허설을 다시 하려면 1번부터 (같은 이메일로 두 번 가입할 수 없어요).

## 기록 없이 시작 / DB 비우기
- 기본 상태: 계정·가게·메뉴·키오스크만 있고 **매출·주문·대화·포인트 기록은 0건**으로 시작해요.
- 데모용 가짜 기록까지 채우려면 `.env`에 `SEED_HISTORY=true`.
- 테스트하다가 다시 비우고 싶으면: 서버를 끄고 `reset_db.bat` 실행.

## 할인 행사 · 가게 알림
- 사장님 화면 → 가게 설정 → 할인 행사(할인율·행사 이름·끝나는 시각). 진행 중이면 주문 합계에서 자동 할인(10원 단위 내림), 손님 앱·키오스크 광고에 남은 시간이 카운터로 보여요.
- 손님 앱 가게 상세의 종 버튼 = `PUT /api/me/store-alerts/{store_id}` (`GET /api/me/store-alerts`로 목록).
