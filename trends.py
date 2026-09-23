import requests
import xml.etree.ElementTree as ET


def get_trends():
    sources = [
        "https://news.google.com/rss?hl=sv&gl=SE&ceid=SE:sv",
        "https://trends.google.com/trending/rss?geo=SE"
    ]

    trends = []

    for url in sources:
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=20
            )
            response.raise_for_status()

            root = ET.fromstring(response.content)

            for item in root.findall(".//item"):
                title = item.find("title")

                if title is not None and title.text:
                    value = title.text.strip()

                    if value and value != "...":
                        # Remove Google News source names after " - "
                        if " - " in value:
                            value = value.rsplit(" - ", 1)[0]

                        if value not in trends:
                            trends.append(value)

        except Exception as error:
            print(f"Source failed: {error}")

    return trends[:10]


if __name__ == "__main__":
    trends = get_trends()

    print("\n🔥 TOP 10 CURRENT TOPICS IN SWEDEN\n")

    if not trends:
        print("No topics found.")
    else:
        for number, trend in enumerate(trends, 1):
            print(f"{number}. {trend}")
