import os

DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
MAX_TRENDS = int(os.getenv("MAX_TRENDS", "12"))
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
VIDEO_SECONDS = int(os.getenv("VIDEO_SECONDS", "24"))
VIDEO_MIN_SECONDS = int(os.getenv("VIDEO_MIN_SECONDS", "18"))
VIDEO_MAX_SECONDS = int(os.getenv("VIDEO_MAX_SECONDS", "60"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
TIKTOK_RESEARCH_TOKEN = os.getenv("TIKTOK_RESEARCH_TOKEN", "")
YOUTUBE_ENABLED = os.getenv("YOUTUBE_ENABLED", "false").lower() == "true"
TIKTOK_ENABLED = os.getenv("TIKTOK_ENABLED", "false").lower() == "true"
AI_MODE = os.getenv("AI_MODE", "template").lower()
VIDEO_ENGINE = os.getenv("VIDEO_ENGINE", "auto").lower()
COMFYUI_URL = os.getenv("COMFYUI_URL", "").rstrip("/")
TTS_ENGINE = os.getenv("TTS_ENGINE", "edge").lower()
TTS_VOICE = os.getenv("TTS_VOICE", "en-US-AriaNeural")
VIDEO_COUNT = int(os.getenv("VIDEO_COUNT", "3"))
AI_VIDEO_ENABLED = os.getenv("AI_VIDEO_ENABLED", "true").lower() == "true"
AI_VIDEO_TIMEOUT = int(os.getenv("AI_VIDEO_TIMEOUT", "180"))
AI_VIDEO_MAX_CLIPS = int(os.getenv("AI_VIDEO_MAX_CLIPS", "3"))
