def publish(video_path: str):
    """Publishing adapters are intentionally disabled until official API credentials exist."""
    return {
        "youtube": {"enabled": False, "status": "waiting_for_official_api_credentials"},
        "tiktok": {"enabled": False, "status": "waiting_for_official_api_credentials"},
        "video": video_path,
    }
