import requests
import xml.etree.ElementTree as ET


def get_trends():
    url = "https://trends.google.com/trending/rss?geo=SE"

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; ViralVideoSystem/1.0)"
        }

        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()

        root = ET.fromstring(response.content)
        trends = []

        for item in root.findall(".//item"):
            title = item.find("title")

            if title is not None and title.text:
                value = title.text.strip()

                if value and value != "...":
                    trends.append(value)

        trends = list(dict.fromkeys(trends))

        if not trends:
            print("No real Google Trends topics were returned.")
            return []

        return trends[:10]

    except ET.ParseError as error:
        print(f"Google Trends returned data that could not be read: {error}")
        return []

    except requests.RequestException as error:
        print(f"Could not connect to Google Trends: {error}")
        return []

    except Exception as error:
        print(f"Could not get trends: {error}")
        return []


if __name__ == "__main__":
    trends = get_trends()

    if not trends:
        print("No trends found.")
    else:
        for number, trend in enumerate(trends, start=1):
            print(f"{number}. {trend}")
