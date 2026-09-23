import os

DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
MAX_TRENDS = int(os.getenv("MAX_TRENDS", "10"))
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
VIDEO_SECONDS = int(os.getenv("VIDEO_SECONDS", "15"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
YOUTUBE_ENABLED = os.getenv("YOUTUBE_ENABLED", "false").lower() == "true"
TIKTOK_ENABLED = os.getenv("TIKTOK_ENABLED", "false").lower() == "true"

AI_MODE = os.getenv("AI_MODE", "template").lower()
VIDEO_COUNT = int(os.getenv("VIDEO_COUNT", "3"))
