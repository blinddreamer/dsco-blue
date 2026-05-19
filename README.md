# D-SCO Bluesky Battle Report Bot

Automatically posts Fraternity. battle report wins to Bluesky with smirky propaganda comments.

## How it works

1. Polls `warbeacon.net/api/br/battle-records` every 10 minutes (configurable)
2. Filters for **ended** battles where Fraternity. (alliance `99003581`) appears in the top factions
3. Skips battles below the minimum pilot / FRT pilot / ISK thresholds
4. For each qualifying battle, calls `warbeacon.net/api/br/auto` to fetch the full kill list for that system + time window
5. Builds team rosters from attacker/victim alliance IDs — FRT and any co-attackers form one side, their victims form the other
6. Skips the battle if FRT's side lost more ISK than the enemy (loss filter)
7. Resolves the solar system name via ESI batch lookup
8. Picks a random smirky propaganda line and posts to Bluesky with a link to the warbeacon BR
9. Deduplicates via MariaDB so the same battle is never posted twice

## Setup

### 1. Create a Bluesky App Password

Go to **Bluesky Settings → App Passwords → Add App Password** and create one for the bot.

### 2. Configure

Copy `.env.example` to `.env` (or set environment variables directly) and fill in the required values.

### 3. Deploy

```bash
docker compose up -d
```

Check logs:

```bash
docker compose logs -f
```

### 4. Test (dry run)

```bash
pip install requests pymysql
BLUESKY_HANDLE=you.bsky.social \
BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx \
DB_HOST=localhost DB_USER=dsco DB_PASSWORD=secret DB_NAME=dsco_bot \
LOG_LEVEL=DEBUG \
python bot.py
```

## Configuration

### Required

| Variable               | Description                                    |
| ---------------------- | ---------------------------------------------- |
| `BLUESKY_HANDLE`       | Your Bluesky handle (e.g. `dsco.bsky.social`)  |
| `BLUESKY_APP_PASSWORD` | Bluesky app password                           |
| `DB_USER`              | MariaDB username                               |
| `DB_PASSWORD`          | MariaDB password                               |

### Optional

| Variable            | Default       | Description                                                     |
| ------------------- | ------------- | --------------------------------------------------------------- |
| `DB_HOST`           | `localhost`   | MariaDB host                                                    |
| `DB_PORT`           | `3306`        | MariaDB port                                                    |
| `DB_NAME`           | `dsco_bot`    | MariaDB database name                                           |
| `POLL_INTERVAL`     | `600`         | Seconds between polls                                           |
| `MIN_PILOTS`        | `20`          | Minimum total pilots in a battle to consider                    |
| `MIN_FRT_PILOTS`    | `10`          | Minimum FRT pilots that must be present                         |
| `MIN_ISK_DESTROYED` | `500000000`   | Minimum total battle ISK (all sides) as a pre-filter — default 500M |
| `LOG_LEVEL`         | `INFO`        | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`)         |

`MIN_ISK_DESTROYED` filters on the combined battle ISK reported by warbeacon before the per-team kill fetch — it avoids calling `/api/br/auto` for tiny skirmishes. The actual win check uses per-side ISK from the kill data.

## Customizing Comments

Edit the `SMIRKY_TEMPLATES` list in `bot.py` to add or change the propaganda lines.

Available template variables:

| Variable          | Example   | Description                         |
| ----------------- | --------- | ----------------------------------- |
| `{system}`        | `O-VWPB`  | Solar system name                   |
| `{efficiency}`    | `67.2`    | FRT ISK efficiency %                |
| `{isk_destroyed}` | `41.1B`   | Enemy ISK destroyed (formatted)     |
| `{isk_lost}`      | `12.6B`   | FRT ISK lost (formatted)            |
| `{pilots}`        | `214`     | Total pilots in the fight           |

Templates containing `{efficiency}` or `{isk_lost}` are automatically excluded from the pool when those values are unavailable.

## External APIs used

| API | Purpose |
| --- | ------- |
| `warbeacon.net/api/br/battle-records` | Poll for recent ended battles with FRT present |
| `warbeacon.net/api/br/auto` | Fetch full kill list for a battle window to compute per-side ISK |
| `esi.evetech.net/latest/universe/names/` | Resolve solar system IDs to names |
| `bsky.social/xrpc/...` | Post to Bluesky |
