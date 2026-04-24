#!/usr/bin/env python3
"""
D-SCO Bluesky Battle Report Bot
Polls EVE Online battle report APIs for Fraternity. wins and posts them to Bluesky.
"""

import os
import json
import time
import random
import logging
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BLUESKY_HANDLE = os.getenv("BLUESKY_HANDLE", "")
BLUESKY_APP_PASSWORD = os.getenv("BLUESKY_APP_PASSWORD", "")

FRATERNITY_ALLIANCE_ID = "99003581"
DSCO_CORP_ID = "98519746"

# Friendly alliance IDs that fight alongside Fraternity
FRIENDLY_ALLIANCES = {
    "99003581",   # Fraternity.
    "498125261",  # Fraternity. ally
    "1727758877", # Fraternity. ally
    "1042504553", # Fraternity. ally
    "99013541",   # Fraternity. ally
    "99002685",   # Fraternity. ally
    "386292982",  # Fraternity. ally
    "99005393",   # Fraternity. ally
    "99001317",   # Fraternity. ally
    "99009129",   # Fraternity. ally
    "99013537",   # Fraternity. ally
    "154104258",  # Fraternity. ally
    "1411711376", # Fraternity. ally
    "99007203",   # Fraternity. ally
    "99011168",   # Fraternity. ally
}

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "600"))  # seconds
MIN_PILOTS = int(os.getenv("MIN_PILOTS", "20"))  # minimum pilots to post
MIN_ISK_DESTROYED = float(os.getenv("MIN_ISK_DESTROYED", "500000000"))  # 500M ISK minimum
MIN_EFFICIENCY = float(os.getenv("MIN_EFFICIENCY", "55"))  # minimum ISK efficiency %

SEEN_FILE = Path(os.getenv("SEEN_FILE", "/data/seen_brs.json"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

EVETOOLS_API = "https://br.evetools.org/api/v1/recent-br"
EVETOOLS_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; dsco-bluesky-bot/1.0)"}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("dsco-bot")

# ---------------------------------------------------------------------------
# Smirky comment templates
# ---------------------------------------------------------------------------
SMIRKY_TEMPLATES = [
    "Another day, another dunk. {system} sends its regards. 💀",
    "They came. They saw. They fed. {isk_destroyed} ISK destroyed in {system}. GF 🫡",
    "{system} turned into a content delivery system. {efficiency}% efficiency. You're welcome.",
    "Imagine undocking just to become a battle report statistic. {system}, {isk_destroyed} destroyed. 📊",
    "Local spike in {system}. Local drop in {system}. {efficiency}% ISK efficiency.",
    "Fraternity. does a little trolling in {system}. {isk_destroyed} ISK evaporated. ✨",
    "Breaking: ships explode in {system}. Fraternity. found not guilty. {efficiency}% efficiency says otherwise.",
    "{pilots} pilots walked into {system}. Not all of them walked out. {isk_destroyed} ISK destroyed.",
    "The D-SCO propaganda department is pleased to report: {system} secured. {efficiency}% efficiency. 🎯",
    "Someone forgot to check zkill before undocking in {system}. {isk_destroyed} ISK lesson delivered.",
    "Content acquired in {system}. {isk_destroyed} destroyed, {isk_lost} lost. Math checks out. ✅",
    "{system}: where ships go to die and Fraternity. goes to thrive. {efficiency}% efficient.",
    "Roses are red, wrecks are too. {isk_destroyed} ISK destroyed. GF to you. 🌹",
    "Fleet pinged. Fleet formed. Fleet dunked. {system}. {efficiency}%. EZ.",
    "POV: you jump into {system} and see Fraternity. on grid. {isk_destroyed} ISK destroyed.",
]

# ---------------------------------------------------------------------------
# Persistence — track which BRs we already posted
# ---------------------------------------------------------------------------
def load_seen() -> set:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except Exception:
            return set()
    return set()


def save_seen(seen: set):
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Keep only last 500 to avoid unbounded growth
    trimmed = sorted(seen)[-500:]
    SEEN_FILE.write_text(json.dumps(trimmed))


# ---------------------------------------------------------------------------
# Bluesky API helpers
# ---------------------------------------------------------------------------
class BlueskyClient:
    def __init__(self, handle: str, app_password: str):
        self.handle = handle
        self.app_password = app_password
        self.session = None
        self.pds = "https://bsky.social"

    def login(self):
        resp = requests.post(
            f"{self.pds}/xrpc/com.atproto.server.createSession",
            json={"identifier": self.handle, "password": self.app_password},
        )
        resp.raise_for_status()
        self.session = resp.json()
        log.info(f"Logged in to Bluesky as {self.handle}")

    def post(self, text: str, url: str = None):
        if not self.session:
            self.login()

        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Build facets for the link if provided
        facets = []
        embed = None

        if url:
            # Add link as an external embed (card-style)
            embed = {
                "$type": "app.bsky.embed.external",
                "external": {
                    "uri": url,
                    "title": "Battle Report",
                    "description": "EVE Online Battle Report",
                },
            }

        record = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": now,
            "langs": ["en"],
        }

        if facets:
            record["facets"] = facets
        if embed:
            record["embed"] = embed

        resp = requests.post(
            f"{self.pds}/xrpc/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {self.session['accessJwt']}"},
            json={
                "repo": self.session["did"],
                "collection": "app.bsky.feed.post",
                "record": record,
            },
        )

        if resp.status_code == 401:
            log.info("Token expired, re-authenticating...")
            self.login()
            resp = requests.post(
                f"{self.pds}/xrpc/com.atproto.repo.createRecord",
                headers={"Authorization": f"Bearer {self.session['accessJwt']}"},
                json={
                    "repo": self.session["did"],
                    "collection": "app.bsky.feed.post",
                    "record": record,
                },
            )

        resp.raise_for_status()
        log.info(f"Posted to Bluesky: {text[:80]}...")
        return resp.json()


# ---------------------------------------------------------------------------
# BR parsing — evetools format
# ---------------------------------------------------------------------------
def parse_evetools_brs(data) -> list:
    """Parse evetools API response into normalized BR list.

    Current format: flat list of BR objects with fields:
      _id, teams ([["alliance_id",...], [...]], totalLost (combined ISK),
      totalPilots, allys ([["alliance_id", count], ...]), timings
    No per-team ISK breakdown is available in this endpoint.
    """
    results = []

    if not isinstance(data, list):
        return results

    for item in data:
        br_id = item.get("_id")
        if not br_id:
            continue

        teams = item.get("teams", [])        # list of two lists of alliance/corp ID strings
        allys = item.get("allys", [])         # [["alliance_id", pilot_count], ...]
        total_pilots = item.get("totalPilots", 0)
        total_lost_isk = item.get("totalLost", 0)   # combined ISK both sides
        timings = item.get("timings", [])

        if total_pilots < MIN_PILOTS:
            continue

        # Find which team Fraternity is on
        frat_team_idx = None
        for idx, team in enumerate(teams):
            if FRATERNITY_ALLIANCE_ID in team or f"corp:{DSCO_CORP_ID}" in team:
                frat_team_idx = idx
                break

        if frat_team_idx is None:
            continue

        # Count Frat-side pilots from allys
        frat_team_set = set(teams[frat_team_idx])
        frat_pilots = sum(
            count for ally_id, count in allys
            if ally_id in frat_team_set
        )

        # Get system name and ID for dedup key
        system_name = "Unknown"
        system_id = 0
        start_ts = 0
        if timings:
            t = timings[0]
            sys_info = t.get("system", {})
            system_name = sys_info.get("name", "Unknown")
            system_id = t.get("systemID", 0)
            start_ts = t.get("start", 0)

        results.append({
            "uuid": br_id,
            "source": "evetools",
            "system": system_name,
            "_dedup_key": (system_id, start_ts // 86400),  # same system, same UTC day
            "isk_destroyed": total_lost_isk,
            "isk_lost": 0,
            "efficiency": 0,
            "pilots": total_pilots,
            "frat_pilots": frat_pilots,
            "url": f"https://br.evetools.org/br/{br_id}",
        })

    # Keep only the largest BR (by ISK) per system per day — same battle
    # submits many slightly different reports; posting all of them is spam.
    best: dict[tuple, dict] = {}
    for br in results:
        key = br["_dedup_key"]
        if key not in best or br["isk_destroyed"] > best[key]["isk_destroyed"]:
            best[key] = br
    results = list(best.values())

    for br in results:
        del br["_dedup_key"]

    return results



# ---------------------------------------------------------------------------
# Format ISK values nicely
# ---------------------------------------------------------------------------
def format_isk(value: float) -> str:
    if value >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:.1f}T"
    elif value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    elif value >= 1_000_000:
        return f"{value / 1_000_000:.0f}M"
    else:
        return f"{value:,.0f}"


# ---------------------------------------------------------------------------
# Generate post text
# ---------------------------------------------------------------------------
def generate_post(br: dict) -> str:
    if br["efficiency"] == 0:
        templates = [t for t in SMIRKY_TEMPLATES if "{efficiency}" not in t]
    else:
        templates = SMIRKY_TEMPLATES
    template = random.choice(templates)
    text = template.format(
        system=br["system"],
        efficiency=br["efficiency"],
        isk_destroyed=format_isk(br["isk_destroyed"]),
        isk_lost=format_isk(br["isk_lost"]),
        pilots=br["pilots"],
    )
    return text


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def poll_and_post(client: BlueskyClient, seen: set) -> set:
    """Poll APIs, find new Fraternity wins, post them."""

    new_brs = []

    # --- Poll evetools (preferred — has per-team ISK) ---
    try:
        log.debug("Polling evetools API...")
        resp = requests.get(EVETOOLS_API, headers=EVETOOLS_HEADERS, timeout=30)
        resp.raise_for_status()
        evetools_brs = parse_evetools_brs(resp.json())
        log.info(f"evetools: found {len(evetools_brs)} Fraternity BRs")
        new_brs.extend(evetools_brs)
    except Exception as e:
        log.warning(f"evetools API error: {e}")

    # --- Filter for wins we haven't posted ---
    posted_count = 0
    for br in new_brs:
        # Create a stable ID for dedup (use uuid)
        br_key = f"{br['source']}:{br['uuid']}"

        if br_key in seen:
            continue

        # Check minimum thresholds
        if br["isk_destroyed"] < MIN_ISK_DESTROYED:
            log.debug(f"Skipping {br['uuid']}: ISK {format_isk(br['isk_destroyed'])} below threshold")
            seen.add(br_key)
            continue

        if br["efficiency"] > 0 and br["efficiency"] < MIN_EFFICIENCY:
            log.debug(f"Skipping {br['uuid']}: efficiency {br['efficiency']}% below threshold")
            seen.add(br_key)
            continue

        # It's a win worth posting!
        log.info(
            f"New win: {br['system']} | {br['efficiency']}% eff | "
            f"destroyed {format_isk(br['isk_destroyed'])} | "
            f"lost {format_isk(br['isk_lost'])} | {br['pilots']} pilots"
        )

        try:
            text = generate_post(br)
            client.post(text=text, url=br["url"])
            posted_count += 1
        except Exception as e:
            log.error(f"Failed to post BR {br['uuid']}: {e}")

        seen.add(br_key)

        # Don't spam — wait a bit between posts
        if posted_count > 0:
            time.sleep(5)

    if posted_count == 0:
        log.debug("No new wins to post")

    return seen


def main():
    if not BLUESKY_HANDLE or not BLUESKY_APP_PASSWORD:
        log.error("BLUESKY_HANDLE and BLUESKY_APP_PASSWORD must be set!")
        log.error("Example: BLUESKY_HANDLE=dsco.bsky.social BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx")
        return

    log.info(f"D-SCO Bluesky Bot starting")
    log.info(f"  Handle: {BLUESKY_HANDLE}")
    log.info(f"  Poll interval: {POLL_INTERVAL}s")
    log.info(f"  Min pilots: {MIN_PILOTS}")
    log.info(f"  Min ISK destroyed: {format_isk(MIN_ISK_DESTROYED)}")
    log.info(f"  Min efficiency: {MIN_EFFICIENCY}%")

    client = BlueskyClient(BLUESKY_HANDLE, BLUESKY_APP_PASSWORD)
    seen = load_seen()

    # Login once at start to verify credentials
    try:
        client.login()
    except Exception as e:
        log.error(f"Failed to login to Bluesky: {e}")
        return

    while True:
        try:
            seen = poll_and_post(client, seen)
            save_seen(seen)
        except Exception as e:
            log.error(f"Error in poll loop: {e}", exc_info=True)

        log.debug(f"Sleeping {POLL_INTERVAL}s...")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
