import requests
import xml.etree.ElementTree as ET


def get_trends():
    url = "https://trends.google.com/trending/rss?geo=SE"

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()

        root = ET.fromstring(response.content)

        trends = []

        for item in root.findall(".//item"):
            title = item.find("title")

            if title is not None and title.text:
                trends.append(title.text)

        return trends[:10]

    except Exception as error:
        print(f"Could not get trends: {error}")
        return []


if __name__ == "__main__":
    trends = get_trends()

    for number, trend in enumerate(trends, start=1):
        print(f"{number}. {trend}")
