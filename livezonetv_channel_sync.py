
#!/usr/bin/env python3
"""
LiveZoneTV automatic channel sync

- Fetches the latest Eamin TV Channel_Data.json API.
- Generates LiveZoneTV_Channels.json and LiveZoneTV_Playlist.m3u8.
- Adds new channels and updates changed stream URLs.
- Keeps the requested group order.
- Preserves manually configured channel-level Referer values.
- Writes both output files atomically.
"""

import json
import os
import tempfile
import urllib.request
from pathlib import Path

API_URL = "https://raw.githubusercontent.com/LiveZoneTV321/test/refs/heads/main/test.json"

OUTPUT_JSON = Path("LiveZoneTV_Channels.json")
OUTPUT_M3U = Path("LiveZoneTV_Playlist.m3u8")

# Optional original converted JSON.
PREVIOUS_JSON = Path("LiveZoneTV_Converted_Referer_Fixed.json")

GROUP_ORDER = [
    "𝐈𝐧𝐝𝐢𝐚𝐧 𝐁𝐚𝐧𝐠𝐥𝐚",
    "𝐈𝐧𝐝𝐢𝐚𝐧 𝐇𝐢𝐧𝐝𝐢",
    "𝐁𝐚𝐧𝐠𝐥𝐚",
    "𝐊𝐢𝐝𝐬",
    "𝐃𝐨𝐜𝐮𝐦𝐞𝐧𝐭𝐨𝐫𝐲",
    "𝐒𝐩𝐨𝐫𝐭𝐬",
]

GROUP_MAP = {
    "𝐁𝐚𝐧𝐠𝐥𝐚": "Bangla",
    "𝐈𝐧𝐝𝐢𝐚𝐧 𝐁𝐚𝐧𝐠𝐥𝐚": "indian Bangla",
    "𝐈𝐧𝐝𝐢𝐚𝐧 𝐇𝐢𝐧𝐝𝐢": "indian Hindi",
    "𝐊𝐢𝐝𝐬": "Kids",
    "𝐃𝐨𝐜𝐮𝐦𝐞𝐧𝐭𝐨𝐫𝐲": "Documentary",
    "𝐒𝐩𝐨𝐫𝐭𝐬": "Sports",
}

OUTPUT_GROUP_ORDER = [
    "indian Bangla",
    "indian Hindi",
    "Bangla",
    "Kids",
    "Documentary",
    "Sports",
]


def read_json(path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_name = tempfile.mkstemp(
        prefix=path.name,
        suffix=".tmp",
        dir=str(path.parent)
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
            file.write(content)

        os.replace(temp_name, path)

    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def fetch_api():
    request = urllib.request.Request(
        API_URL,
        headers={
            "User-Agent": "LiveZoneTV-Channel-Sync/1.0",
            "Accept": "application/json",
        }
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8-sig")

    data = json.loads(raw)

    if not isinstance(data, dict):
        raise ValueError("Invalid API response: expected a JSON object.")

    if not isinstance(data.get("categories"), list):
        raise ValueError("API format changed: 'categories' array not found.")

    return data


def load_old_referers():
    """
    Preserve manually configured channel-level Referer values.

    Priority:
    1. Existing LiveZoneTV_Channels.json
    2. LiveZoneTV_Converted_Referer_Fixed.json
    """

    referers = {}

    files = [OUTPUT_JSON, PREVIOUS_JSON]

    for path in files:
        if not path.exists():
            continue

        try:
            old_data = read_json(path)

            for channel in old_data.get("channels", []):
                name = str(channel.get("name", "")).strip()
                referer = str(channel.get("referer", "")).strip()

                if name and referer:
                    # Do not overwrite a Referer already loaded
                    # from the current output JSON.
                    referers.setdefault(name.casefold(), referer)

        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            print(f"Warning: Could not read {path}: {exc}")

    print(f"Preserved manual Referer entries: {len(referers)}")

    return referers


def convert_channels(source, old_referers):
    categories = source.get("categories")

    if not isinstance(categories, list):
        raise ValueError("API categories are invalid.")

    # Dictionary keyed by group + channel name.
    # If a channel URL changes, its existing entry is replaced.
    channel_map = {}

    order_index = {
        name: index
        for index, name in enumerate(GROUP_ORDER)
    }

    categories = sorted(
        categories,
        key=lambda item: order_index.get(
            str(item.get("name", "")).strip(),
            999
        )
    )

    for category in categories:
        source_group = str(category.get("name", "")).strip()
        output_group = GROUP_MAP.get(source_group)

        if not output_group:
            print(f"Skipping unknown category: {source_group}")
            continue

        channel_list = category.get("channels", [])

        if not isinstance(channel_list, list):
            continue

        for item in channel_list:
            name = str(item.get("name", "")).strip()
            url = str(item.get("stream_url", "")).strip()
            logo = str(item.get("logo", "") or "").strip()

            if not name or not url:
                continue

            key = (output_group.casefold(), name.casefold())

            # API Referer takes priority.
            # Otherwise keep the previous manually configured Referer.
            api_referer = str(item.get("referer") or "").strip()
            old_referer = old_referers.get(name.casefold(), "")

            referer = api_referer or old_referer

            channel = {
                "name": name,
                "logo": logo,
                "group": output_group,
                "tabs": [
                    {
                        "name": "Main Stream",
                        "url": url,
                    }
                ],
                "autoPlayBackup": True,
            }

            if referer:
                channel["referer"] = referer

            # Same channel with a changed URL replaces the old entry.
            # Same channel appearing again does not create duplicates.
            channel_map[key] = channel

    converted = list(channel_map.values())

    group_index = {
        name: index
        for index, name in enumerate(OUTPUT_GROUP_ORDER)
    }

    converted.sort(
        key=lambda channel: (
            group_index.get(channel["group"], 999),
            channel["name"].casefold()
        )
    )

    return converted


def make_m3u(channels):
    lines = ["#EXTM3U"]

    for channel in channels:
        name = channel["name"].replace('"', "'")
        group = channel["group"].replace('"', "'")
        logo = channel.get("logo", "").replace('"', "'")

        tabs = channel.get("tabs", [])

        if not tabs:
            continue

        url = str(tabs[0].get("url", "")).strip()

        if not url:
            continue

        lines.append(
            f'#EXTINF:-1 tvg-name="{name}" '
            f'tvg-logo="{logo}" '
            f'group-title="{group}",{name}'
        )

        referer = str(channel.get("referer", "")).strip()

        if referer:
            # M3UParser supports both http-referrer and http-referer.
            lines.append(f"#EXTVLCOPT:http-referrer={referer}")

        lines.append(url)

    return "\n".join(lines) + "\n"


def main():
    print("======================================")
    print(" LiveZoneTV Channel Auto Sync Started")
    print("======================================")

    print("Fetching latest API data...")
    source = fetch_api()

    old_referers = load_old_referers()

    print("Converting channels...")
    channels = convert_channels(source, old_referers)

    if not channels:
        raise RuntimeError(
            "No valid channels found. Existing output files were not overwritten."
        )

    output = {
        "playlist_name": "LiveZone TV",
        "channels": channels,
    }

    json_text = json.dumps(
        output,
        ensure_ascii=False,
        indent=2
    ) + "\n"

    m3u_text = make_m3u(channels)

    # Generate BOTH files on every successful run.
    atomic_write(OUTPUT_JSON, json_text)
    atomic_write(OUTPUT_M3U, m3u_text)

    group_counts = {}

    for channel in channels:
        group = channel["group"]
        group_counts[group] = group_counts.get(group, 0) + 1

    print("--------------------------------------")
    print(f"Total channels: {len(channels)}")

    for group in OUTPUT_GROUP_ORDER:
        print(f"{group}: {group_counts.get(group, 0)}")

    print("--------------------------------------")
    print(f"JSON generated: {OUTPUT_JSON}")
    print(f"M3U8 generated: {OUTPUT_M3U}")

    print(f"JSON size: {OUTPUT_JSON.stat().st_size} bytes")
    print(f"M3U8 size: {OUTPUT_M3U.stat().st_size} bytes")

    print("Both output files generated successfully.")
    print("======================================")


if __name__ == "__main__":
    main()
