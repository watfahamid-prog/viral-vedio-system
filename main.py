from datetime import datetime
from trends import get_trends


def main():
    print("=" * 50)
    print("🚀 VIRAL VIDEO SYSTEM")
    print("=" * 50)

    print(f"Scan time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("\n🔥 Current trend topics:\n")

    trends = get_trends()

    if not trends:
        print("No trends found.")
        return

    for number, trend in enumerate(trends, start=1):
        print(f"{number}. {trend}")

    print("\n✅ Trend scan completed!")


if __name__ == "__main__":
    main()
