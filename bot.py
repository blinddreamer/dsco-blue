#!/usr/bin/env python3
"""
D-SCO Bluesky Battle Report Bot
Polls EVE Online battle report APIs for Fraternity. battles and posts them to Bluesky.
"""

import os
import time
import random
import logging
from contextlib import closing
from datetime import datetime, timezone

import pymysql
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BLUESKY_HANDLE = os.getenv("BLUESKY_HANDLE", "")
BLUESKY_APP_PASSWORD = os.getenv("BLUESKY_APP_PASSWORD", "")

FRATERNITY_ALLIANCE_ID = "99003581"

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "600"))  # seconds
MIN_PILOTS = int(os.getenv("MIN_PILOTS", "20"))  # minimum pilots to post
MIN_ISK_DESTROYED = float(os.getenv("MIN_ISK_DESTROYED", "500000000"))  # 500M ISK minimum
MIN_FRT_PILOTS = int(os.getenv("MIN_FRT_PILOTS", "10"))  # minimum FRT pilots in BR

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = int(os.getenv("DB_PORT", "3306"))
DB_USER     = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME     = os.getenv("DB_NAME", "dsco_bot")

WARBEACON_API = "https://warbeacon.net/api/br/battle-records"
WARBEACON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; dsco-bluesky-bot/1.0)",
    "Accept": "application/json",
}
WARBEACON_AUTO_API = "https://warbeacon.net/api/br/auto"
ESI_NAMES_API = "https://esi.evetech.net/latest/universe/names/"

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
    "The enemy FC is currently updating their résumé. {system}, {isk_destroyed} destroyed. 📝",
    "{pilots} pilots. One outcome. {isk_destroyed} ISK gone. {system} added to the list.",
    "Skill issue detected in {system}. {isk_destroyed} ISK removed from the game. 🛠️",
    "Hot drop? Structure bash? Doesn't matter. {system}. {isk_destroyed}. We showed up.",
    "Some called it a bait. Fraternity. called it content. {system}. {isk_destroyed} ISK destroyed.",
    "Good fight! (It wasn't for them.) {system}, {isk_destroyed} ISK destroyed. 🤝",
    "The battle for {system} lasted long enough to hurt. {isk_destroyed} ISK says so.",
    "News from the front: {system} still belongs to whoever has more ships. Currently us. {isk_destroyed} ISK.",
    "They formed. We formed harder. {system}. {isk_destroyed} gone. Simple.",
    "In {system} today, {pilots} pilots learned an important lesson about grid awareness. {isk_destroyed} ISK tuition paid.",
    "Warp to zero. Apply damage. Collect tears. {system}. {isk_destroyed} ISK destroyed. 😢",
    "Another killboard update brought to you by Fraternity. in {system}. {isk_destroyed} ISK. You're welcome.",
    "{isk_destroyed} ISK destroyed in {system}. The enemy fleet is now a debris field. 🌌",
    "The map turned red in {system}. {isk_destroyed} ISK destroyed. Fraternity. sends its regards. 🔴",
    "Bridge up. Fleet in. Fleet wins. {system}. {isk_destroyed}. Classic.",
    "Field control established in {system}. {isk_destroyed} ISK taxed from the locals. 💰",
    "They thought the numbers were in their favor. {system} disagrees. {isk_destroyed} ISK destroyed.",
    "Cap escalation? Sure. {system} handled it. {isk_destroyed} ISK handled with it. 🚀",
    "Intel said 'not that many.' Intel was wrong. {system}. {isk_destroyed} destroyed.",
    "Logi died first. The rest followed. {system}. {isk_destroyed} ISK. Story as old as EVE.",
    "{system}: visited by Fraternity., reviewed one star, would not recommend undocking. {isk_destroyed} ISK.",
    "FC said 'hold cloak.' Nobody held cloak. {isk_destroyed} ISK destroyed in {system}.",
    "Another day, another system on the board. {system}. {isk_destroyed} ISK. Don't be late to the next one.",
    "They undocked. We noticed. {system}. {isk_destroyed} ISK destroyed. Noticed very hard. 👀",
    "Battle report filed. Enemy tears collected. {system}. {isk_destroyed} ISK gone. Have a good evening.",
    "If you're reading this you lost ships in {system}. {isk_destroyed} ISK. GG no RE. 🫠",
    "Sometimes EVE is a strategy game. Sometimes it's {system}. {isk_destroyed} ISK destroyed.",
    "The wrecks in {system} tell a story. {isk_destroyed} ISK. It's not a happy one for the other side.",
    "D-SCO on comms: 'gf.' D-SCO on zkill: {isk_destroyed} destroyed in {system}. Both true. ✌️",
    "Local was fun in {system} for exactly one side. {isk_destroyed} ISK destroyed. Guess which side.",
]

# ---------------------------------------------------------------------------
# Persistence — MariaDB
# ---------------------------------------------------------------------------
def _db():
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME, charset="utf8mb4",
        autocommit=True,
    )


def init_db():
    with closing(_db()) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS seen_brs (
                    br_key VARCHAR(255) PRIMARY KEY,
                    seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
    log.info("DB ready")


def load_seen() -> set:
    with closing(_db()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT br_key FROM seen_brs")
            return {row[0] for row in cur.fetchall()}


def save_seen(seen: set):
    if not seen:
        return
    with closing(_db()) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT IGNORE INTO seen_brs (br_key) VALUES (%s)",
                [(k,) for k in seen],
            )


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

        if embed:
            record["embed"] = embed

        def _do_post():
            return requests.post(
                f"{self.pds}/xrpc/com.atproto.repo.createRecord",
                headers={"Authorization": f"Bearer {self.session['accessJwt']}"},
                json={
                    "repo": self.session["did"],
                    "collection": "app.bsky.feed.post",
                    "record": record,
                },
            )

        resp = _do_post()

        # Bluesky returns 401 for invalid tokens, but sometimes returns 400
        # with error "ExpiredToken" — handle both by re-authenticating once.
        if resp.status_code in (400, 401):
            try:
                err = resp.json().get("error", "")
            except Exception:
                err = ""
            if resp.status_code == 401 or err in ("ExpiredToken", "AuthenticationRequired"):
                log.info(f"Session expired ({resp.status_code} {err}), re-authenticating...")
                self.login()
                resp = _do_post()

        resp.raise_for_status()
        log.info(f"Posted to Bluesky: {text[:80]}...")
        return resp.json()


# ---------------------------------------------------------------------------
# BR parsing — warbeacon format
# ---------------------------------------------------------------------------
def resolve_system_names(brs: list) -> None:
    """Resolve solarSystemId → name via ESI, modifies BRs in-place."""
    system_ids = list({br["_system_id"] for br in brs if br.get("_system_id")})
    if not system_ids:
        return
    try:
        resp = requests.post(ESI_NAMES_API, json=system_ids, timeout=15)
        resp.raise_for_status()
        id_to_name = {entry["id"]: entry["name"] for entry in resp.json()}
        for br in brs:
            sid = br.get("_system_id")
            if sid:
                br["system"] = id_to_name.get(sid, br["system"])
    except Exception as e:
        log.warning(f"ESI name resolution failed: {e}")
    for br in brs:
        br.pop("_system_id", None)


def fetch_team_isk(solar_system_id: int, start_time: str, end_time: str) -> tuple:
    """Fetch kills from warbeacon /api/br/auto and return (frat_isk_lost, enemy_isk_lost).

    Uses attacker/victim alliance data to build team rosters the same way warbeacon does,
    so FRT allies dying count as FRT-side losses, not enemy losses. Returns (0, 0) on failure.
    """
    try:
        resp = requests.post(
            WARBEACON_AUTO_API,
            headers=WARBEACON_HEADERS,
            json={"locations": [{"id": solar_system_id, "startTime": start_time, "endTime": end_time}]},
            timeout=30,
        )
        resp.raise_for_status()
        kills = resp.json().get("data", {}).get("killmails", [])
    except Exception as e:
        log.warning(f"warbeacon auto fetch failed for system {solar_system_id}: {e}")
        return 0, 0

    if not kills:
        return 0, 0

    frat_id = int(FRATERNITY_ALLIANCE_ID)

    # Build team rosters:
    # - FRT in attackers → victim is enemy, co-attackers are FRT allies
    # - Known FRT ally is victim → attackers are enemies
    frat_side = {frat_id}
    enemy_side = set()

    for kill in kills:
        victim_alliance = kill.get("victim", {}).get("alliance_id")
        attacker_alliances = {
            a["alliance_id"] for a in kill.get("attackers", []) if a.get("alliance_id")
        }
        if frat_id in attacker_alliances:
            if victim_alliance:
                enemy_side.add(victim_alliance)
            frat_side.update(attacker_alliances)
        elif victim_alliance in frat_side:
            enemy_side.update(attacker_alliances)

    enemy_side -= frat_side

    frat_isk = 0.0
    enemy_isk = 0.0
    for kill in kills:
        victim_alliance = kill.get("victim", {}).get("alliance_id")
        value = kill.get("total_value", 0)
        if victim_alliance in frat_side:
            frat_isk += value
        elif victim_alliance in enemy_side:
            enemy_isk += value

    log.debug(
        f"warbeacon auto {solar_system_id}: FRT side lost {format_isk(frat_isk)}, "
        f"enemy lost {format_isk(enemy_isk)} "
        f"({len(kills)} kills, {len(frat_side)} frt alliances, {len(enemy_side)} enemy alliances)"
    )
    return frat_isk, enemy_isk


def parse_warbeacon_brs(data: dict) -> list:
    """Parse warbeacon /api/br/battle-records response into normalized BR list."""
    results = []
    records = data.get("data", {}).get("records", [])

    for item in records:
        if item.get("status") != "ended":
            continue

        participant_count = item.get("participantCount", 0)
        if participant_count < MIN_PILOTS:
            continue

        top_factions = item.get("topFactions", [])
        frat_entry = next(
            (f for f in top_factions if f.get("factionId") == int(FRATERNITY_ALLIANCE_ID)),
            None,
        )
        if frat_entry is None:
            continue

        solar_system_id = item.get("solarSystemId")
        start_time = item.get("startTime", "")
        br_link = item.get("brLink", "")

        if not solar_system_id or not start_time or not br_link:
            continue

        end_time = item.get("endTime", "")
        start_hour = start_time[:13]  # "2026-05-19T15" — stable per-battle bucket
        br_uuid = f"{solar_system_id}_{start_hour}"

        results.append({
            "uuid": br_uuid,
            "source": "warbeacon",
            "_system_id": solar_system_id,   # popped by resolve_system_names
            "_solar_system_id": solar_system_id,  # kept for zkillboard lookup
            "_start_time": start_time,
            "_end_time": end_time,
            "system": str(solar_system_id),
            "_dedup_key": (solar_system_id, start_hour),
            "isk_destroyed": item.get("totalValue", 0),  # pre-filter; replaced with enemy ISK after zkill
            "isk_lost": 0,
            "efficiency": 0,
            "pilots": participant_count,
            "frat_pilots": frat_entry.get("participantCount", 0),
            "url": br_link,
        })

    # Keep only the highest-ISK record per (system, start-hour) — dedup same battle
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
    templates = SMIRKY_TEMPLATES
    if br["efficiency"] == 0:
        templates = [t for t in templates if "{efficiency}" not in t]
    if br["isk_lost"] == 0:
        templates = [t for t in templates if "{isk_lost}" not in t]
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
def poll_and_post(client: BlueskyClient, seen: set) -> tuple:
    """Poll warbeacon, find new Fraternity battles, post them. Returns (seen, newly_added)."""

    new_brs = []
    newly_added = set()

    try:
        log.debug("Polling warbeacon API...")
        resp = requests.get(WARBEACON_API, headers=WARBEACON_HEADERS, timeout=30)
        resp.raise_for_status()
        warbeacon_brs = parse_warbeacon_brs(resp.json())
        log.info(f"warbeacon: found {len(warbeacon_brs)} Fraternity BRs")
        new_brs.extend(warbeacon_brs)
    except Exception as e:
        log.warning(f"warbeacon API error: {e}")

    # Resolve system names for all new BRs in one ESI batch call
    unresolved = [br for br in new_brs if br.get("_system_id")]
    if unresolved:
        resolve_system_names(unresolved)

    posted_count = 0
    for br in new_brs:
        br_key = f"{br['source']}:{br['uuid']}"

        if br_key in seen:
            continue

        if br["isk_destroyed"] < MIN_ISK_DESTROYED:
            log.debug(f"Skipping {br['uuid']}: ISK {format_isk(br['isk_destroyed'])} below threshold")
            seen.add(br_key)
            newly_added.add(br_key)
            continue

        if br["frat_pilots"] < MIN_FRT_PILOTS:
            log.info(f"Skipping {br['uuid']}: only {br['frat_pilots']} FRT pilots — below minimum of {MIN_FRT_PILOTS}")
            seen.add(br_key)
            newly_added.add(br_key)
            continue

        # Fetch per-side ISK from warbeacon to determine win/loss
        frat_isk, enemy_isk = fetch_team_isk(
            br["_solar_system_id"], br["_start_time"], br["_end_time"]
        )

        if frat_isk == 0 and enemy_isk == 0:
            log.warning(f"Skipping {br['uuid']}: no kill data returned for {br['system']}")
            seen.add(br_key)
            newly_added.add(br_key)
            continue

        if frat_isk >= enemy_isk:
            log.info(
                f"Skipping {br['uuid']}: FRT lost {format_isk(frat_isk)} "
                f"vs enemy {format_isk(enemy_isk)} — loss, not posting"
            )
            seen.add(br_key)
            newly_added.add(br_key)
            continue

        efficiency = enemy_isk / (frat_isk + enemy_isk) * 100
        br["isk_destroyed"] = enemy_isk
        br["isk_lost"] = frat_isk
        br["efficiency"] = round(efficiency, 1)

        log.info(
            f"New win: {br['system']} | FRT lost {format_isk(frat_isk)} "
            f"enemy lost {format_isk(enemy_isk)} | {efficiency:.1f}% efficiency"
        )

        try:
            text = generate_post(br)
            client.post(text=text, url=br["url"])
            posted_count += 1
        except Exception as e:
            log.error(f"Failed to post BR {br['uuid']}: {e}")

        seen.add(br_key)
        newly_added.add(br_key)

        if posted_count > 0:
            time.sleep(5)

    if posted_count == 0:
        log.debug("No new battles to post")

    return seen, newly_added


def main():
    if not BLUESKY_HANDLE or not BLUESKY_APP_PASSWORD:
        log.error("BLUESKY_HANDLE and BLUESKY_APP_PASSWORD must be set!")
        log.error("Example: BLUESKY_HANDLE=dsco.bsky.social BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx")
        return

    log.info(f"D-SCO Bluesky Bot starting")
    log.info(f"  Handle: {BLUESKY_HANDLE}")
    log.info(f"  Source: warbeacon (battle detection + team ISK via /api/br/auto)")
    log.info(f"  Poll interval: {POLL_INTERVAL}s")
    log.info(f"  Min pilots: {MIN_PILOTS}")
    log.info(f"  Min FRT pilots: {MIN_FRT_PILOTS}")
    log.info(f"  Min ISK: {format_isk(MIN_ISK_DESTROYED)}")

    try:
        init_db()
    except Exception as e:
        log.error(f"Failed to connect to DB: {e}")
        return

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
            seen, newly_added = poll_and_post(client, seen)
            save_seen(newly_added)
        except Exception as e:
            log.error(f"Error in poll loop: {e}", exc_info=True)

        log.debug(f"Sleeping {POLL_INTERVAL}s...")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
