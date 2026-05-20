# D-SCO Bluesky Battle Report Bot

Automatically posts Fraternity. battle report wins to Bluesky with smirky propaganda comments.

## How it works

1. Polls `br.evetools.org/api/v1/recent-br` every 10 minutes (configurable)
2. Filters for battles where Fraternity. (alliance `99003581`) or D-SCO (corp `98519746`) appears on a team
3. Skips battles below the minimum total pilot / FRT pilot / ISK thresholds
4. For each qualifying battle, calls `br.evetools.org/newapi/br/composition/{id}` to fetch per-team ISK lost
5. Skips the battle if FRT's side lost more ISK than the enemy (loss filter) — equal ISK (draws) are posted
6. Picks a random smirky propaganda line and posts to Bluesky with a link to the evetools BR
7. Deduplicates via MariaDB — same system + same UTC day keeps only the largest BR by ISK, so multi-submit spam is collapsed before posting

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

| Variable               | Description                                   |
| ---------------------- | --------------------------------------------- |
| `BLUESKY_HANDLE`       | Your Bluesky handle (e.g. `dsco.bsky.social`) |
| `BLUESKY_APP_PASSWORD` | Bluesky app password                          |
| `DB_USER`              | MariaDB username                              |
| `DB_PASSWORD`          | MariaDB password                              |

### Optional

| Variable            | Default     | Description                                                                          |
| ------------------- | ----------- | ------------------------------------------------------------------------------------ |
| `DB_HOST`           | `localhost` | MariaDB host                                                                         |
| `DB_PORT`           | `3306`      | MariaDB port                                                                         |
| `DB_NAME`           | `dsco_bot`  | MariaDB database name                                                                |
| `POLL_INTERVAL`     | `600`       | Seconds between polls                                                                |
| `MIN_PILOTS`        | `20`        | Minimum total pilots in a battle to consider                                         |
| `MIN_FRT_PILOTS`    | `10`        | Minimum FRT/D-SCO pilots that must be present in the BR                              |
| `MIN_ISK_DESTROYED` | `500000000` | Minimum combined battle ISK (both sides) as a pre-filter — default 500M             |
| `LOG_LEVEL`         | `INFO`      | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`)                              |

`MIN_ISK_DESTROYED` is checked against the combined ISK from the evetools summary endpoint before the per-team composition fetch — it avoids hitting the composition API for tiny skirmishes. The actual win/loss check uses per-side ISK from the composition data.

## Win criteria (all must pass)

1. Fraternity. or D-SCO is on a team in the BR
2. Total pilots ≥ `MIN_PILOTS`
3. FRT/D-SCO pilots in BR ≥ `MIN_FRT_PILOTS`
4. Combined battle ISK ≥ `MIN_ISK_DESTROYED`
5. Composition data is fetchable (retried next cycle on failure)
6. Enemy ISK lost > FRT ISK lost (draws count as wins)

## Customizing Comments

Edit the `SMIRKY_TEMPLATES` list in `bot.py` to add or change the propaganda lines.

Available template variables:

| Variable          | Example  | Description                     |
| ----------------- | -------- | ------------------------------- |
| `{system}`        | `O-VWPB` | Solar system name               |
| `{efficiency}`    | `67.2`   | FRT ISK efficiency %            |
| `{isk_destroyed}` | `41.1B`  | Enemy ISK destroyed (formatted) |
| `{isk_lost}`      | `12.6B`  | FRT ISK lost (formatted)        |
| `{pilots}`        | `214`    | Total pilots in the fight       |

Templates containing `{efficiency}` or `{isk_lost}` are automatically excluded from the pool when those values are unavailable.

Posts are capped at 300 graphemes to comply with the Bluesky limit.

## External APIs used

| API                                          | Purpose                                              |
| -------------------------------------------- | ---------------------------------------------------- |
| `br.evetools.org/api/v1/recent-br`           | Poll for recent BRs with FRT/D-SCO present           |
| `br.evetools.org/newapi/br/composition/{id}` | Fetch per-team kill data to compute per-side ISK     |
| `bsky.social/xrpc/...`                       | Post to Bluesky (auto re-authenticates on token expiry) |
