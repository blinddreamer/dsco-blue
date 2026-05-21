#!/usr/bin/env python3
"""
D-SCO Bluesky Battle Report Bot
Polls EVE Online battle report APIs for Fraternity. wins and posts them to Bluesky.
"""

import os
import time
import random
import logging
from contextlib import closing
from datetime import datetime, timezone

import pymysql
import requests
from collections import defaultdict

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BLUESKY_HANDLE = os.getenv("BLUESKY_HANDLE", "")
BLUESKY_APP_PASSWORD = os.getenv("BLUESKY_APP_PASSWORD", "")

FRATERNITY_ALLIANCE_ID = "99003581"
DSCO_CORP_ID = "98519746"

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

EVETOOLS_API = "https://br.evetools.org/api/v1/recent-br"
EVETOOLS_COMPOSITION_API = "https://br.evetools.org/newapi/br/composition/{}"
EVETOOLS_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; dsco-bluesky-bot/1.0)"}

REDDIT_USER = os.getenv("REDDIT_WATCH_USER", "eve_revisionism")
REDDIT_SUBREDDIT = os.getenv("REDDIT_WATCH_SUBREDDIT", "Eve")
REDDIT_HEADERS = {"User-Agent": "dsco-bluesky-bot/1.0 (cross-poster)"}

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

    def post(self, text: str, url: str = None, embed_title: str = "Battle Report"):
        if not self.session:
            self.login()

        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        embed = None

        if url:
            embed = {
                "$type": "app.bsky.embed.external",
                "external": {
                    "uri": url,
                    "title": embed_title,
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

        # ally_id → pilot count lookup
        # No team data = can't determine winner, skip.
        if not teams:
            continue

        ally_pilot_map = {e[0]: e[1] for e in allys if isinstance(e, (list, tuple)) and len(e) == 2}

        # teams entries may be a list of IDs or, rarely, a bare string.
        def _team_ids(team_entry):
            if isinstance(team_entry, list):
                return team_entry
            if isinstance(team_entry, str):
                return [team_entry]
            return []

        # Find which team FRT is on.
        frat_team_idx = None
        for idx, team in enumerate(teams):
            if FRATERNITY_ALLIANCE_ID in _team_ids(team) or f"corp:{DSCO_CORP_ID}" in _team_ids(team):
                frat_team_idx = idx
                break

        if frat_team_idx is None:
            continue

        # Normalise teams to lists of strings for later use
        norm_teams = [_team_ids(t) for t in teams]
        frat_pilots = sum(ally_pilot_map.get(a, 0) for a in norm_teams[frat_team_idx])

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
            "_dedup_key": (system_id, start_ts // 86400) if system_id else (br_id, 0),
            "isk_destroyed": total_lost_isk,
            "isk_lost": 0,
            "efficiency": 0,
            "pilots": total_pilots,
            "frat_pilots": frat_pilots,
            "_norm_teams": norm_teams,
            "_frat_team_idx": frat_team_idx,
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


def fetch_team_isk_lost(br_id: str, norm_teams: list, frat_team_idx: int) -> tuple:
    """Fetch composition data and return (frat_isk_lost, enemy_isk_lost).

    Calls /newapi/br/composition/{id}, iterates every killmail, and sums ISK
    lost per team based on the victim's alliance ID.
    Returns (0, 0) on any error so the caller can decide what to do.
    """
    try:
        resp = requests.get(
            EVETOOLS_COMPOSITION_API.format(br_id),
            headers=EVETOOLS_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.warning(f"Composition fetch failed for {br_id}: {e}")
        return None, None

    # Build lookup: str(alliance_id) -> team index
    team_lookup = {}
    for idx, team_ids in enumerate(norm_teams):
        for ally_id in team_ids:
            team_lookup[str(ally_id)] = idx

    isk_by_team = defaultdict(float)
    for related in data.get("relateds", []):
        for km in related.get("kms", []):
            victim_ally = str(km.get("victim", {}).get("ally", 0))
            value = km.get("totalValue", 0)
            team_idx = team_lookup.get(victim_ally)
            if team_idx is not None:
                isk_by_team[team_idx] += value

    frat_isk = isk_by_team.get(frat_team_idx, 0)
    enemy_isk = sum(v for k, v in isk_by_team.items() if k != frat_team_idx)
    return frat_isk, enemy_isk


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
    # Bluesky enforces a 300-grapheme limit
    if len(text) > 300:
        text = text[:297] + "..."
    return text


# ---------------------------------------------------------------------------
# Reddit cross-poster
# ---------------------------------------------------------------------------
def fetch_reddit_posts() -> list:
    """Return recent posts by REDDIT_USER in REDDIT_SUBREDDIT as normalized dicts."""
    url = f"https://www.reddit.com/user/{REDDIT_USER}/submitted.json?limit=25&sort=new"
    try:
        resp = requests.get(url, headers=REDDIT_HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.warning(f"Reddit fetch failed: {e}")
        return []

    posts = []
    for child in data.get("data", {}).get("children", []):
        p = child.get("data", {})
        if p.get("subreddit", "").lower() != REDDIT_SUBREDDIT.lower():
            continue
        post_id = p.get("id", "")
        if not post_id:
            continue
        posts.append({
            "uuid": post_id,
            "source": "reddit",
            "title": p.get("title", ""),
            "url": f"https://www.reddit.com{p.get('permalink', '')}",
        })
    return posts


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def poll_and_post(client: BlueskyClient, seen: set) -> tuple:
    """Poll APIs, find new Fraternity wins, post them. Returns (seen, newly_added)."""

    new_brs = []
    newly_added = set()

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
            newly_added.add(br_key)
            continue

        if br["frat_pilots"] < MIN_FRT_PILOTS:
            log.info(f"Skipping {br['uuid']}: only {br['frat_pilots']} FRT pilots — below minimum of {MIN_FRT_PILOTS}")
            seen.add(br_key)
            newly_added.add(br_key)
            continue

        # Fetch per-team ISK from the composition endpoint and compare.
        frat_isk, enemy_isk = fetch_team_isk_lost(
            br["uuid"], br["_norm_teams"], br["_frat_team_idx"]
        )

        if frat_isk is None:
            # Composition fetch failed — don't mark seen so we retry next cycle.
            log.warning(f"Skipping {br['uuid']}: could not fetch composition data (will retry)")
            continue

        efficiency = enemy_isk / (frat_isk + enemy_isk) * 100 if (frat_isk + enemy_isk) > 0 else 0

        if frat_isk > enemy_isk:
            log.info(
                f"Skipping {br['uuid']}: FRT lost {format_isk(frat_isk)} "
                f"vs enemy {format_isk(enemy_isk)} — loss, not posting"
            )
            seen.add(br_key)
            newly_added.add(br_key)
            continue

        # Update BR dict with real per-team ISK so the post template can use it.
        br["isk_destroyed"] = enemy_isk
        br["isk_lost"] = frat_isk
        br["efficiency"] = round(efficiency, 1)

        # It's a win — post it.
        log.info(
            f"New win: {br['system']} | FRT lost {format_isk(frat_isk)} "
            f"enemy lost {format_isk(enemy_isk)} | {efficiency:.1f}% efficiency"
        )

        try:
            text = generate_post(br)
            client.post(text=text, url=br["url"], embed_title=f"Battle Report — {br['system']}")
            posted_count += 1
        except Exception as e:
            log.error(f"Failed to post BR {br['uuid']}: {e}")

        seen.add(br_key)
        newly_added.add(br_key)

        # Sleep between posts to avoid spamming (skip delay before the first post)
        if posted_count > 1:
            time.sleep(5)

    if posted_count == 0:
        log.debug("No new wins to post")

    # --- Poll Reddit for u/REDDIT_USER posts in r/REDDIT_SUBREDDIT ---
    reddit_posts = fetch_reddit_posts()
    log.info(f"Reddit: found {len(reddit_posts)} recent posts by u/{REDDIT_USER} in r/{REDDIT_SUBREDDIT}")
    for post in reddit_posts:
        br_key = f"reddit:{post['uuid']}"
        if br_key in seen:
            continue
        title = post["title"]
        if len(title) > 300:
            title = title[:297] + "..."
        try:
            client.post(text=title, url=post["url"], embed_title=post["title"])
            log.info(f"Cross-posted Reddit post {post['uuid']}: {title[:60]}")
        except Exception as e:
            log.error(f"Failed to cross-post Reddit post {post['uuid']}: {e}")
        seen.add(br_key)
        newly_added.add(br_key)
        time.sleep(3)

    return seen, newly_added


def main():
    if not BLUESKY_HANDLE or not BLUESKY_APP_PASSWORD:
        log.error("BLUESKY_HANDLE and BLUESKY_APP_PASSWORD must be set!")
        log.error("Example: BLUESKY_HANDLE=dsco.bsky.social BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx")
        return

    log.info("D-SCO Bluesky Bot starting")
    log.info(f"  Handle: {BLUESKY_HANDLE}")
    log.info("  Source: evetools (br.evetools.org)")
    log.info(f"  Poll interval: {POLL_INTERVAL}s")
    log.info(f"  Min pilots: {MIN_PILOTS}")
    log.info(f"  Min FRT pilots: {MIN_FRT_PILOTS}")
    log.info(f"  Min ISK destroyed: {format_isk(MIN_ISK_DESTROYED)}")
    log.info(f"  Reddit cross-poster: u/{REDDIT_USER} in r/{REDDIT_SUBREDDIT}")

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
