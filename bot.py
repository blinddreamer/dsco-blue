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
WARBEACON_API = "https://warbeacon.net/api/br/recent"

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
    """Parse evetools API response into normalized BR list."""
    results = []

    # API may return {"success": true, "data": [...]} or a bare list
    if isinstance(data, dict):
        if not data.get("success") or not data.get("data"):
            return results
        groups = data["data"]
    elif isinstance(data, list):
        groups = data
    else:
        return results

    for group in groups:
        for item in group.get("items", []):
            uuid = item.get("uuid")
            if not uuid:
                continue

            teams_meta = item.get("teamsMetadata", [])
            teams_raw = item.get("teams", [])
            locations = item.get("locations", [])
            participant_count = item.get("participantCount", 0)

            if participant_count < MIN_PILOTS:
                continue

            # Find which team Fraternity is on
            frat_team_id = None
            for idx, team in enumerate(teams_raw):
                for key in team.keys():
                    # Keys are like "alliance_99003581" or "corporation_98519746"
                    entity_id = key.split("_", 1)[1] if "_" in key else key
                    if entity_id == FRATERNITY_ALLIANCE_ID or entity_id == DSCO_CORP_ID:
                        frat_team_id = idx
                        break
                if frat_team_id is not None:
                    break

            if frat_team_id is None:
                continue

            # Get ISK values per team
            frat_loss = 0
            enemy_loss = 0
            frat_participants = 0

            for meta in teams_meta:
                tid = meta.get("teamId", -1)
                loss_val = meta.get("totalLossValue", 0)
                pcount = meta.get("participantCount", 0)

                if tid == frat_team_id:
                    frat_loss = loss_val
                    frat_participants = pcount
                else:
                    enemy_loss += loss_val

            total_destroyed = enemy_loss
            total_lost = frat_loss

            if total_destroyed + total_lost == 0:
                continue

            efficiency = (total_destroyed / (total_destroyed + total_lost)) * 100

            # Get system name from first location
            system_name = "Unknown"
            region_name = ""
            if locations:
                system_name = locations[0].get("name", "Unknown")

            results.append({
                "uuid": uuid,
                "source": "evetools",
                "system": system_name,
                "efficiency": round(efficiency, 1),
                "isk_destroyed": total_destroyed,
                "isk_lost": total_lost,
                "pilots": participant_count,
                "frat_pilots": frat_participants,
                "url": f"https://br.evetools.org/br/{uuid}",
            })

    return results


# ---------------------------------------------------------------------------
# BR parsing — warbeacon format
# ---------------------------------------------------------------------------
def parse_warbeacon_brs(data: list) -> list:
    """Parse warbeacon API response into normalized BR list."""
    results = []

    for item in data:
        br_id = item.get("_id")
        if not br_id:
            continue

        teams = item.get("teams", [])
        allys = item.get("allys", [])
        timings = item.get("timings", [])
        total_pilots = item.get("totalPilots", 0)

        if total_pilots < MIN_PILOTS:
            continue

        # Check if Fraternity is in the fight
        frat_in_allys = any(
            a[0] == FRATERNITY_ALLIANCE_ID for a in allys if isinstance(a, list)
        )
        if not frat_in_allys:
            continue

        # Find which team Frat is on
        frat_team_idx = None
        for idx, team in enumerate(teams):
            if FRATERNITY_ALLIANCE_ID in team:
                frat_team_idx = idx
                break

        if frat_team_idx is None:
            # Teams not sorted yet — skip (can't determine win/loss)
            continue

        # Get system name
        system_name = "Unknown"
        if timings:
            sys_info = timings[0].get("system", {})
            system_name = sys_info.get("name", "Unknown")

        # Warbeacon doesn't have per-team ISK in the recent endpoint
        # so we use it mainly as a backup / dedup source
        results.append({
            "uuid": br_id,
            "source": "warbeacon",
            "system": system_name,
            "url": f"https://warbeacon.net/br/report/{br_id}",
            "pilots": total_pilots,
            # These will be 0 — evetools is preferred for ISK data
            "efficiency": 0,
            "isk_destroyed": 0,
            "isk_lost": 0,
            "frat_pilots": 0,
        })

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
    template = random.choice(SMIRKY_TEMPLATES)
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
        resp = requests.get(EVETOOLS_API, timeout=30)
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
            log.debug(f"Skipping {br['uuid']}: ISK destroyed {format_isk(br['isk_destroyed'])} below threshold")
            seen.add(br_key)
            continue

        if br["efficiency"] < MIN_EFFICIENCY:
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
