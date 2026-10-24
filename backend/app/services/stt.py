"""음성 인식 (Whisper).

.env 의 STT_PROVIDER 로 선택:
  groq   : GroqCloud API (whisper-large-v3-turbo). GROQ_API_KEY 필요. 빠르고 무료 등급 있음. (기본값)
  openai : OpenAI API (whisper-1). OPENAI_API_KEY 필요.
  local  : 내 컴퓨터에서 openai-whisper 실행. 키 필요 없음. 대신 설치가 무겁고(torch) ffmpeg 필요.
           pip install openai-whisper   /  WHISPER_MODEL=base (tiny, base, small, medium, large)

groq 과 openai 는 요청 형식이 같아서(OpenAI 호환) 주소·키·모델만 다릅니다.

메뉴 이름을 힌트(prompt)로 함께 넘겨서 '제육볶음', '로제떡볶이' 같은 단어를 더 잘 알아듣게 합니다.
"""
import logging
import os
import tempfile

import httpx

from ..config import settings

log = logging.getLogger(__name__)

ALLOWED_EXT = {"webm", "ogg", "wav", "mp3", "m4a", "mp4", "mpeg", "mpga", "flac"}
MAX_BYTES = 25 * 1024 * 1024  # Groq 무료 등급 / OpenAI 제한

# provider: (요청 주소, 키 설정 이름, 모델 설정 이름)
API_PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1/audio/transcriptions", "GROQ_API_KEY", "GROQ_STT_MODEL"),
    "openai": ("https://api.openai.com/v1/audio/transcriptions", "OPENAI_API_KEY", "WHISPER_API_MODEL"),
}

_local_model = None


# 조용하거나 잡음만 있을 때 Whisper가 지어내는 흔한 문장 (영상 자막 학습 영향)
HALLUCINATIONS = ["시청해주셔서감사합니다", "구독과좋아요", "구독좋아요", "다음영상에서", "MBC뉴스", "KBS뉴스",
                  "자막제공", "자막by", "한국어자막", "끝까지시청", "영상편집"]
NO_SPEECH_PROB = 0.6    # 이 구간이 '말이 아님'일 확률이 이보다 높으면 버림
MIN_AVG_LOGPROB = -1.0  # 모델이 자신 없는 구간(웅성거림 등)은 버림


class STTError(Exception):
    """사용자에게 그대로 보여줘도 되는 오류 메시지."""


class NoSpeech(STTError):
    """말소리가 아니라 잡음만 들어온 경우."""


def provider() -> str:
    p = settings.STT_PROVIDER
    return "openai" if p == "api" else p  # 예전 설정값 호환


def is_enabled() -> bool:
    if provider() == "local":
        try:
            import whisper  # noqa: F401
            return True
        except ImportError:
            return False
    if provider() in API_PROVIDERS:
        return bool(getattr(settings, API_PROVIDERS[provider()][1]))
    return False


def transcribe(data: bytes, filename: str = "audio.webm", hint: str = "") -> str:
    if not data:
        raise STTError("녹음된 소리가 없어요.")
    if len(data) > MAX_BYTES:
        raise STTError("녹음이 너무 길어요. 짧게 다시 말씀해 주세요.")
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "webm").lower()
    if ext not in ALLOWED_EXT:
        raise STTError(f"지원하지 않는 음성 형식이에요: .{ext}")

    if provider() == "local":
        text = _local(data, ext, hint)
    elif provider() in API_PROVIDERS:
        text = _api(provider(), data, filename, hint)
    else:
        raise STTError(f"알 수 없는 STT_PROVIDER: {provider()} (groq / openai / local)")
    text = clean_transcript(text, hint)
    if not text:
        raise NoSpeech("잘 못 알아들었어요. 다시 한 번 말씀해 주세요.")
    return text


def clean_transcript(text: str, hint: str = "") -> str:
    text = (text or "").strip()
    norm = text.replace(" ", "")
    if not norm.strip(".,!?~ "):
        return ""
    if any(h in norm for h in HALLUCINATIONS):
        return ""
    if hint and norm in hint.replace(" ", ""):  # 힌트 문장을 그대로 읊는 환각
        return ""
    return text


def _keep_segments(payload: dict) -> str:
    """verbose_json 의 구간별 신뢰도로 잡음 구간을 걸러냄."""
    segs = payload.get("segments")
    if not segs:
        return payload.get("text", "")
    kept = [sg.get("text", "") for sg in segs
            if sg.get("no_speech_prob", 0) <= NO_SPEECH_PROB and sg.get("avg_logprob", 0) >= MIN_AVG_LOGPROB]
    return "".join(kept)


def _api(name: str, data: bytes, filename: str, hint: str) -> str:
    url, key_name, model_name = API_PROVIDERS[name]
    key = getattr(settings, key_name)
    if not key:
        raise STTError(f"음성 인식이 설정되지 않았어요. ({key_name} 필요)")
    try:
        r = httpx.post(
            url,
            headers={"Authorization": f"Bearer {key}"},
            # prompt 는 224토큰 제한이 있어 짧게 자름
            data={"model": getattr(settings, model_name), "language": "ko", "prompt": hint[:200],
                  "response_format": "verbose_json", "temperature": "0"},
            files={"file": (filename, data)},
            timeout=60,
        )
    except httpx.HTTPError as e:
        log.warning("%s STT 연결 실패: %s", name, e)
        raise STTError("음성 인식 서버에 연결하지 못했어요. 글자로 입력해 주세요.")
    if r.status_code != 200:
        log.warning("%s STT 오류 %s: %s", name, r.status_code, r.text[:300])
        if r.status_code == 429:
            raise STTError("음성 인식 사용량이 잠시 초과됐어요. 글자로 입력해 주세요.")
        raise STTError("음성 인식에 실패했어요. 글자로 입력해 주세요.")
    return _keep_segments(r.json())


def _local(data: bytes, ext: str, hint: str) -> str:
    global _local_model
    try:
        import whisper
    except ImportError:
        raise STTError("로컬 Whisper가 설치되지 않았어요. (pip install openai-whisper)")
    if _local_model is None:
        _local_model = whisper.load_model(settings.WHISPER_MODEL)
    fd, path = tempfile.mkstemp(suffix="." + ext)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        result = _local_model.transcribe(path, language="ko", initial_prompt=hint or None, fp16=False,
                                         condition_on_previous_text=False)
        return _keep_segments(result)
    except FileNotFoundError:
        raise STTError("ffmpeg가 설치되지 않았어요. (로컬 Whisper는 ffmpeg 필요)")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
