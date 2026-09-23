# Viral Video System

Automated trend-to-content pipeline for original short-form videos.

## Current flow

Google News / Google Trends → trend scanner → opportunity builder → original-content manifest → Discord notification

## Safety mode

The system starts with `DRY_RUN=true`. It does not automatically publish videos. It also does not copy another creator's video, script, watermark, or footage.

## Run locally

    pip install -r requirements.txt
    python main.py

## Environment variables

- `DRY_RUN`: keep true while testing
- `MAX_TRENDS`: maximum topics processed per run
- `DISCORD_WEBHOOK_URL`: optional Discord webhook
- `OPENAI_API_KEY`: optional AI generation provider credential
- `YOUTUBE_ENABLED`: disabled until official YouTube credentials are configured
- `TIKTOK_ENABLED`: disabled until official TikTok credentials are configured

## Deployment

The repository is designed to run as a scheduled Render job. Publishing credentials must be added as private environment variables in Render; never commit secrets to GitHub.

## Next integrations

The architecture has separate modules for AI content generation, video rendering, YouTube publishing, TikTok publishing, and Discord notifications. Each integration can be enabled independently after its official API credentials are configured.
