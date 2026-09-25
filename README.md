# Viral Video System

Automated trend-to-content pipeline for original short-form videos.

## Current pipeline

1. Find current topics from Google News and Google Trends RSS.
2. Optionally merge YouTube and TikTok research data when official credentials are available.
3. Score, deduplicate, diversify, and timestamp trend opportunities.
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

AI generation is now a real optional path, not only a placeholder. The system generates several short visual clips per video and falls back to the existing renderer if the AI provider is unavailable.\n\nThe videos no longer use one repeated blue template. The template generator also creates five scenes with different narrative structures so the three outputs are not clones.

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
- OPENAI_MODEL (optional; choose a model available to your API account)
- HF_TOKEN (optional; enables external AI video inference)
- AI_VIDEO_MODEL
- AI_VIDEO_PROVIDER
- TTS_ENGINE=edge (neural narration) or espeak
- TTS_VOICE
- YOUTUBE_API_KEY (future integration)
- TIKTOK_RESEARCH_TOKEN (optional research integration)
- YOUTUBE_ENABLED=false
- TIKTOK_ENABLED=false

## AI video engine

The workflow supports Hugging Face Inference Providers for text-to-video. The default model is LTX-Video, with Wan 2.1 1.3B available by setting VIDEO_ENGINE=hf_wan. Hugging Face currently documents text-to-video support through providers including fal-ai and lists LTX-Video, Wan 2.1, HunyuanVideo and CogVideoX among served models. The external inference provider may require its own paid credits; the repository therefore keeps an automatic template fallback.

Add a GitHub Actions secret named HF_TOKEN before enabling provider inference. Never commit the token to the repository.


## Current production defaults

The automation is designed to stay fast and reliable on GitHub Actions:
- 3 vertical videos per run
- 15–90 second duration based on narration length
- adaptive format and visual layout
- Edge TTS narration with local fallback
- optional AI video is disabled by default so a remote provider cannot stall a run
- generated videos and metadata are uploaded as GitHub Actions artifacts
- YouTube/TikTok publishing remains disabled until official credentials are configured
- a preflight self-test runs before video generation
