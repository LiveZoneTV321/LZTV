#!/usr/bin/env python3
"""
LiveZoneTV automatic channel sync
- Downloads the latest Eamin TV Channel_Data.json API.
- Converts it to LiveZoneTV JSON format.
- Adds new channels and updates changed stream URLs automatically.
- Keeps the requested group order.
- Preserves manually configured channel-level referers from the previous output.
- Generates an M3U8-compatible M3U playlist (playlist file extension: .m3u).
"""

import json
import os
import tempfile
import urllib.request
from pathlib import Path

API_URL = "https://eamintv.vercel.app/IPTV/Apps/Info/Channel_Data/Api/Channel_Data.json"
OUTPUT_JSON = Path("LiveZoneTV_Channels.json")
OUTPUT_M3U = Path("LiveZoneTV_Playlist.m3u8")

# Previous converted JSON is used only to preserve channel-level referer values.
# Keep this file beside the script. It is optional.
PREVIOUS_JSON = Path("LiveZoneTV_Converted_Referer_Fixed.json")

GROUP_ORDER = [
    "𝐈𝐧𝐝𝐢𝐚𝐧 𝐁𝐚𝐧𝐠𝐥𝐚",
    "𝐈𝐧𝐝𝐢𝐚𝐧 𝐇𝐢𝐧𝐝𝐢",
    "𝐁𝐚𝐧𝐠𝐥𝐚",
    "𝐊𝐢𝐝𝐬",
    "𝐃𝐨𝐜𝐮𝐦𝐞𝐧𝐭𝐨𝐫𝐲",
    "𝐒𝐩𝐨𝐫𝐭𝐬",
]

# Source category -> group title used inside LiveZoneTV JSON and M3U.
GROUP_MAP = {
    "𝐁𝐚𝐧𝐠𝐥𝐚": "Bangla",
    "𝐈𝐧𝐝𝐢𝐚𝐧 𝐁𝐚𝐧𝐠𝐥𝐚": "indian Bangla",
    "𝐈𝐧𝐝𝐢𝐚𝐧 𝐇𝐢𝐧𝐝𝐢": "indian Hindi",
    "𝐊𝐢𝐝𝐬": "Kids",
    "𝐃𝐨𝐜𝐮𝐦𝐞𝐧𝐭𝐨𝐫𝐲": "Documentary",
    "𝐒𝐩𝐨𝐫𝐭𝐬": "Sports",
}

# Explicit output order, mapped to the output group names above.
OUTPUT_GROUP_ORDER = [
    "indian Bangla",
    "indian Hindi",
    "Bangla",
    "Kids",
    "Documentary",
    "Sports",
]


def read_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
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
        headers={"User-Agent": "LiveZoneTV-Channel-Sync/1.0"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8-sig")
    return json.loads(raw)


def load_old_referers():
    referers = {}
    if not PREVIOUS_JSON.exists():
        return referers

    try:
        old_data = read_json(PREVIOUS_JSON)
        for channel in old_data.get("channels", []):
            name = str(channel.get("name", "")).strip()
            referer = channel.get("referer")
            if name and referer:
                referers[name.casefold()] = referer
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Warning: previous JSON could not be read; referer preservation skipped: {exc}")
    return referers


def convert_channels(source, old_referers):
    categories = source.get("categories")
    if not isinstance(categories, list):
        raise ValueError("API format changed: 'categories' array was not found.")

    converted = []
    seen = set()

    # Sort categories in the exact requested order, irrespective of API order.
    order_index = {name: index for index, name in enumerate(GROUP_ORDER)}
    categories = sorted(
        categories,
        key=lambda item: order_index.get(str(item.get("name", "")).strip(), 999)
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

            # Do not create unusable entries without a channel name or stream URL.
            if not name or not url:
                continue

            # If API contains a new URL for a channel, that updated URL replaces
            # the previous URL. Duplicate name+URL pairs are ignored.
            unique_key = (name.casefold(), url)
            if unique_key in seen:
                continue
            seen.add(unique_key)

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

            # API referer takes priority; otherwise preserve manual old referer.
            referer = item.get("referer") or old_referers.get(name.casefold())
            if referer:
                channel["referer"] = str(referer).strip()

            converted.append(channel)

    # Enforce final channel group order.
    group_index = {name: index for index, name in enumerate(OUTPUT_GROUP_ORDER)}
    converted.sort(
        key=lambda c: (
            group_index.get(c["group"], 999),
            c["name"].casefold()
        )
    )
    return converted


def make_m3u(channels):
    lines = ["#EXTM3U"]
    for channel in channels:
        name = channel["name"].replace('"', "'")
        group = channel["group"].replace('"', "'")
        logo = channel.get("logo", "").replace('"', "'")
        tab = channel["tabs"][0]
        url = tab["url"]

        lines.append(
            f'#EXTINF:-1 tvg-name="{name}" tvg-logo="{logo}" group-title="{group}",{name}'
        )

        referer = channel.get("referer")
        if referer:
            # VLC-compatible HTTP Referer option for players that support it.
            lines.append(f"#EXTVLCOPT:http-ref={referer}")

        lines.append(url)

    return "\n".join(lines) + "\n"


def main():
    print("Fetching latest channel data...")
    source = fetch_api()

    old_referers = load_old_referers()
    channels = convert_channels(source, old_referers)

    if not channels:
        raise RuntimeError("No valid channels found. Existing output files were not overwritten.")

    output = {
        "playlist_name": "LiveZone TV",
        "channels": channels,
    }

    json_text = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    m3u_text = make_m3u(channels)

    atomic_write(OUTPUT_JSON, json_text)
    atomic_write(OUTPUT_M3U, m3u_text)

    group_counts = {}
    for channel in channels:
        group_counts[channel["group"]] = group_counts.get(channel["group"], 0) + 1

    print(f"Done. Total channels: {len(channels)}")
    for group in OUTPUT_GROUP_ORDER:
        print(f"  {group}: {group_counts.get(group, 0)}")
    print(f"JSON saved: {OUTPUT_JSON}")
    print(f"M3U playlist saved: {OUTPUT_M3U}")


if __name__ == "__main__":
    main()
