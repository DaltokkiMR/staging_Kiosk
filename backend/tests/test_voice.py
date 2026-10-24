"""음성 인식(Whisper) 테스트 — 실제 OpenAI 호출 없이 가짜 응답으로 확인."""
import os

os.environ["SEED_HISTORY"] = "true"  # 테스트는 데모 기록이 있는 상태에서
import tempfile

os.environ.setdefault("DATABASE_URL", f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'voice.db')}")
os.environ["ANTHROPIC_API_KEY"] = ""

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402

K = {"X-Kiosk-Key": "demo-kiosk-key"}
AUDIO = {"audio": ("voice.webm", b"\x1aE\xdf\xa3fake-webm-bytes", "audio/webm")}


class FakeResp:
    def __init__(self, status, payload):
        self.status_code, self._p, self.text = status, payload, str(payload)

    def json(self):
        return self._p


def test_voice(monkeypatch):
    sent = {}

    def fake_post(url, headers, data, files, timeout):
        sent.update(url=url, data=data, auth=headers["Authorization"], fname=files["file"][0])
        return FakeResp(200, {"text": " 불고기 덜 달게 되나요? "})

    with TestClient(app) as c:
        # 기본은 Groq. 키 없으면 친절한 오류 (텍스트 대화는 계속 가능)
        monkeypatch.setattr(settings, "STT_PROVIDER", "groq")
        monkeypatch.setattr(settings, "GROQ_API_KEY", "")
        r = c.post("/api/kiosk/ai/voice", headers=K, files=AUDIO, data={"session_id": "v0"})
        assert r.status_code == 400 and "GROQ_API_KEY" in r.json()["detail"]
        assert c.get("/api/health").json()["stt_enabled"] is False

        monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk-test")
        monkeypatch.setattr(httpx, "post", fake_post)
        assert c.get("/api/health").json()["stt_enabled"] is True

        # 받아쓰기만
        r = c.post("/api/kiosk/stt", headers=K, files=AUDIO)
        assert r.json()["text"] == "불고기 덜 달게 되나요?"
        assert sent["url"] == "https://api.groq.com/openai/v1/audio/transcriptions"
        assert sent["data"]["model"] == "whisper-large-v3-turbo" and sent["data"]["language"] == "ko"
        assert "제육볶음" in sent["data"]["prompt"]  # 메뉴 이름 힌트
        assert sent["auth"] == "Bearer gsk-test"

        # OpenAI 로 바꿔도 동작
        monkeypatch.setattr(settings, "STT_PROVIDER", "openai")
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")
        c.post("/api/kiosk/stt", headers=K, files=AUDIO)
        assert sent["url"].startswith("https://api.openai.com") and sent["data"]["model"] == "whisper-1"
        monkeypatch.setattr(settings, "STT_PROVIDER", "groq")

        # 음성으로 AI 대화 → 텍스트 대화와 같은 세션으로 이어짐
        r = c.post("/api/kiosk/ai/voice", headers=K, files=AUDIO, data={"session_id": "v1"}).json()
        assert r["transcript"] == "불고기 덜 달게 되나요?"
        assert r["reply"] and "단맛 조절" in r["unmet_requests"]
        r2 = c.post("/api/kiosk/ai/chat", headers=K, json={"session_id": "v1", "message": "안 매운 거 추천해줘"}).json()
        assert r2["reply"]

        # 지원 안 하는 형식 / 빈 파일
        bad = c.post("/api/kiosk/stt", headers=K, files={"audio": ("a.txt", b"hi", "text/plain")})
        assert bad.status_code == 400
        empty = c.post("/api/kiosk/stt", headers=K, files={"audio": ("a.webm", b"", "audio/webm")})
        assert empty.status_code == 400

        # Whisper API 실패 시
        monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp(500, {"error": "x"}))
        r = c.post("/api/kiosk/stt", headers=K, files=AUDIO)
        assert r.status_code == 400 and "글자로" in r.json()["detail"]

        # 키오스크 키 없이는 불가
        assert c.post("/api/kiosk/stt", files=AUDIO).status_code == 422


def test_live_voice_noise_and_ordering(monkeypatch):
    """라이브 음성: 잡음 무시, 말로 주문(담기/결제)."""
    texts = []

    def fake_post(url, headers, data, files, timeout):
        assert data["response_format"] == "verbose_json"
        return FakeResp(200, texts.pop(0))

    def seg(text, nsp=0.05, lp=-0.2):
        return {"text": text, "no_speech_prob": nsp, "avg_logprob": lp}

    with TestClient(app) as c:
        monkeypatch.setattr(settings, "STT_PROVIDER", "groq")
        monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk-test")
        monkeypatch.setattr(httpx, "post", fake_post)
        voice = lambda: c.post("/api/kiosk/ai/voice", headers=K, files=AUDIO, data={"session_id": "live1"}).json()

        # 1) 잡음 구간(no_speech_prob 높음)만 → 무시
        texts.append({"text": "웅성웅성", "segments": [seg("웅성웅성", nsp=0.9)]})
        r = voice(); assert r["ignored"] and r["reply"] == ""
        # 2) Whisper 환각 문장 → 무시
        texts.append({"text": "시청해 주셔서 감사합니다.", "segments": [seg("시청해 주셔서 감사합니다.")]})
        assert voice()["ignored"]
        # 3) 옆 사람 추임새 → 무시
        texts.append({"text": "응 그래", "segments": [seg("응"), seg(" 그래", lp=-0.3)]})
        texts[-1]["segments"] = [seg("응")]
        assert voice()["ignored"]
        # 4) 신뢰도 낮은 구간은 버리고 손님 말만 남김
        texts.append({"text": "...", "segments": [seg("어쩌구저쩌구", lp=-1.6), seg("제육볶음 두 개 주세요")]})
        r = voice()
        assert r["transcript"] == "제육볶음 두 개 주세요"
        assert r["actions"][0]["type"] == "add_to_cart" and r["actions"][0]["quantity"] == 2
        assert "담았어요" in r["reply"]
        # 5) 추천 받은 뒤 "첫 번째 걸로 주세요"
        texts.append({"text": "안 매운 거 추천해 주세요", "segments": [seg("안 매운 거 추천해 주세요")]})
        rec = voice()
        assert rec["recommended_menus"] and "(" not in rec["reply"]  # 소리로 읽기 좋게 괄호 없음
        texts.append({"text": "첫 번째 걸로 주세요", "segments": [seg("첫 번째 걸로 주세요")]})
        r = voice()
        assert r["actions"] == [{"type": "add_to_cart", "menu_item_id": rec["recommended_menus"][0]["id"], "quantity": 1}]
        # 6) 로제떡볶이 vs 떡볶이 구분 (분식 키오스크)
        texts.append({"text": "로제떡볶이 하나 주세요", "segments": [seg("로제떡볶이 하나 주세요")]})
        r = c.post("/api/kiosk/ai/voice", headers={"X-Kiosk-Key": "demo-kiosk-key-2"}, files=AUDIO,
                   data={"session_id": "live2"}).json()
        assert len(r["actions"]) == 1
        # 7) 결제
        texts.append({"text": "이제 결제할게요", "segments": [seg("이제 결제할게요")]})
        assert {"type": "checkout"} in voice()["actions"]
        # 글자 대화도 같은 기능 (ignored 없음)
        t = c.post("/api/kiosk/ai/chat", headers=K, json={"session_id": "live1", "message": "김치찌개 하나 담아줘"}).json()
        assert t["actions"][0]["type"] == "add_to_cart" and not t["ignored"]
