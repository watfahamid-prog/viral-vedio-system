from pipeline import build_opportunities
from script_generator import generate_script
from video import _choose_duration


def main():
    sample = [{
        "trend": "Example technology trend",
        "source": "google_news",
        "sources": ["google_news"],
        "score": 80,
        "metrics": {},
        "confidence": 0.8,
    }]
    opportunities = build_opportunities(sample)
    assert len(opportunities) == 1
    opportunity = opportunities[0]
    assert opportunity["category"] == "technology"
    assert opportunity["format"] in {"youtube_quick_explainer", "short_explainer"}

    script = generate_script(
        opportunity["trend"],
        opportunity["hook"],
        opportunity["format"],
    )
    assert len(script["scenes"]) == 5
    duration = _choose_duration(script, opportunity)
    assert 15 <= duration <= 90
    print("SELF-TEST OK")


if __name__ == "__main__":
    main()
