# Viral Video System

Automated trend-to-content pipeline for original short-form videos.

## Current pipeline

1. Find current topics from Google News and Google Trends RSS.
2. Optionally merge YouTube and TikTok research data when official credentials are available.
3. Score, deduplicate, and diversify the trend opportunities.
4. Create three different short-form concepts/scripts.
5. Render three visually different vertical videos with narration.
6. Write manifests, a run summary, and performance-ready metadata.
7. Upload all generated files to the GitHub Actions artifact.
8. Send a Discord completion notification when a webhook is configured.
9. Keep YouTube/TikTok publishing disabled until their official APIs are added.

## Video improvements

Each run intentionally uses three visual identities:
- Editorial: light paper-style layout with red/orange accents.
- Story: dark warm layout with moving rings and conversational hook card.
- Explained: mint editorial layout with structured step cards.

The videos no longer use one repeated blue template. The template generator also creates five scenes with different narrative structures so the three outputs are not clones.

## Important

- DRY_RUN=true remains enabled during testing.
- AI_MODE=template does not require OpenAI API credits.
- YouTube API/upload is intentionally the final integration.
- Never commit API keys or Discord webhooks to the repository.

## GitHub Actions

The workflow runs manually, on pushes to main, and every 6 hours. Generated videos and metadata are retained as an artifact for 7 days.

## Environment variables

- MAX_TRENDS
- VIDEO_COUNT
- VIDEO_SECONDS
- DISCORD_WEBHOOK_URL
- OPENAI_API_KEY (optional)
- YOUTUBE_API_KEY (future integration)
- TIKTOK_RESEARCH_TOKEN (optional research integration)
- YOUTUBE_ENABLED=false
- TIKTOK_ENABLED=false
