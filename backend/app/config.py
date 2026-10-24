"""환경설정. .env 파일 또는 환경변수에서 읽어옵니다."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'staging.db'}")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-change-me-please-32bytes-min")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

    # 결제 QR 코드 유효시간(초). 캡처 재사용 방지를 위해 짧게.
    PAYMENT_QR_TTL_SECONDS: int = int(os.getenv("PAYMENT_QR_TTL_SECONDS", "60"))

    # LLM (Anthropic Claude). 키가 없으면 규칙 기반 대체 로직으로 동작합니다.
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "claude-sonnet-5-5")

    # 음성 인식 (Whisper)  groq | openai | local
    STT_PROVIDER: str = os.getenv("STT_PROVIDER", "groq").lower()
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_STT_MODEL: str = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    WHISPER_API_MODEL: str = os.getenv("WHISPER_API_MODEL", "whisper-1")
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "base")          # local 일 때 모델 크기

    CORS_ORIGINS: list[str] = os.getenv("CORS_ORIGINS", "*").split(",")

    # 데모 편의 기능(키오스크에서 데모 손님 QR 대신 발급 등). 실서비스에서는 false.
    DEMO_MODE: bool = os.getenv("DEMO_MODE", "true").lower() == "true"
    # true면 데모용 가짜 기록(지난 주문·매출·대화·포인트)까지 채움. 기본은 빈 상태(계정·가게·메뉴·키오스크만)
    SEED_HISTORY: bool = os.getenv("SEED_HISTORY", "false").lower() == "true"


settings = Settings()
