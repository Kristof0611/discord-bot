import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv

import os
import re
import sqlite3
import asyncio

from datetime import datetime, timezone, date, timedelta
from zoneinfo import ZoneInfo


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

TOKEN = os.getenv("TOKEN")

SERVER_ID = 1529030570410119259
TRACKER_CHANNEL_ID = 1532339634829267149

PH_TZ = ZoneInfo("Asia/Manila")

DEFAULT_DAILY_REQUIREMENT = 100_000
MAX_ADVANCE_DAYS = 365

# Roblox roster managers
LEADER_ROLE_ID = 1530461465209995447
CO_LEADER_ROLE_ID = 1531132914190778388

# Automatic reminder/report defaults (Philippines time)
DEFAULT_REMINDER_HOUR = 20       # 8:00 PM PH
DEFAULT_REMINDER_MINUTE = 0

DEFAULT_REPORT_HOUR = 0          # 12:05 AM PH
DEFAULT_REPORT_MINUTE = 5


# =========================================================
# GUILDS 1-10
# =========================================================

GUILD_CHANNELS = {
    1530941934753812651: "Guild 1",
    1530941966836043836: "Guild 2",
    1530942152690110565: "Guild 3",
    1530942182888837341: "Guild 4",
    1530942213612372038: "Guild 5",
    1531199068603154489: "Guild 6",
    1531856633439977532: "Guild 7",
    1532940571415679067: "Guild 8",
    1533320919500455996: "Guild 9",
    1533793502410965062: "Guild 10",
    1534837437631561809: "Guild 11",
}

GUILD_ROLES = {
    "Guild 1": 1529033508750884935,
    "Guild 2": 1529329932528910366,
    "Guild 3": 1529330155095593061,
    "Guild 4": 1529547406264242236,
    "Guild 5": 1530476999158796349,
    "Guild 6": 1531198563609088062,
    "Guild 7": 1531853188645261430,
    "Guild 8": 1532934229854257332,
    "Guild 9": 1533320139393601626,
    "Guild 10": 1533793609135034488,
    "Guild 11": 1534832842083926116,
}


# =========================================================
# DATABASE / RAILWAY PERSISTENCE
# =========================================================
# If you mount a Railway Volume at /data, this automatically
# stores the database there. Otherwise it uses donations.db.
#
# Recommended Railway Volume mount path:
# /data
#
# Optional Railway variable:
# DB_PATH=/data/donations.db
# =========================================================

DEFAULT_DB_PATH = (
    "/data/donations.db"
    if os.path.isdir("/data")
    else "donations.db"
)

DB_PATH = os.getenv("DB_PATH", DEFAULT_DB_PATH)

db_parent = os.path.dirname(DB_PATH)
if db_parent:
    os.makedirs(db_parent, exist_ok=True)

db = sqlite3.connect(DB_PATH)
cursor = db.cursor()


cursor.execute("""
CREATE TABLE IF NOT EXISTS donations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild TEXT NOT NULL,
    ign TEXT NOT NULL,
    previous_gold TEXT,
    current_gold TEXT,
    donation INTEGER NOT NULL,
    logged_by TEXT,
    logged_by_id TEXT,
    time TEXT,
    day TEXT NOT NULL,
    message_id TEXT,
    channel_id TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS donation_credit (
    guild TEXT NOT NULL,
    ign_key TEXT NOT NULL,
    display_ign TEXT NOT NULL,
    balance INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild, ign_key)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS donation_coverage (
    guild TEXT NOT NULL,
    ign_key TEXT NOT NULL,
    display_ign TEXT NOT NULL,
    covered_day TEXT NOT NULL,
    PRIMARY KEY (guild, ign_key, covered_day)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS credit_processed (
    donation_id INTEGER PRIMARY KEY
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS guild_settings (
    guild TEXT PRIMARY KEY,
    daily_requirement INTEGER NOT NULL DEFAULT 100000,
    reminder_enabled INTEGER NOT NULL DEFAULT 0,
    daily_report_enabled INTEGER NOT NULL DEFAULT 0,
    report_channel_id TEXT,
    reminder_hour INTEGER NOT NULL DEFAULT 20,
    reminder_minute INTEGER NOT NULL DEFAULT 0,
    report_hour INTEGER NOT NULL DEFAULT 0,
    report_minute INTEGER NOT NULL DEFAULT 5
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS automation_runs (
    run_key TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS roblox_members (
    guild TEXT NOT NULL,
    discord_user_id TEXT NOT NULL,
    roblox_ign_key TEXT NOT NULL,
    roblox_ign TEXT NOT NULL,
    roblox_username TEXT NOT NULL,
    added_by_id TEXT,
    added_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (guild, discord_user_id),
    UNIQUE (guild, roblox_ign_key)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS inactive_igns (
    guild TEXT NOT NULL,
    ign_key TEXT NOT NULL,
    display_ign TEXT NOT NULL,
    reason TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (guild, ign_key)
)
""")


db.commit()


def column_exists(table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    return column in [row[1] for row in cursor.fetchall()]


# Upgrade older DBs safely
for column_name, sql_type in [
    ("message_id", "TEXT"),
    ("channel_id", "TEXT"),
    ("logged_by_id", "TEXT"),
]:
    if not column_exists("donations", column_name):
        cursor.execute(
            f"ALTER TABLE donations ADD COLUMN {column_name} {sql_type}"
        )

db.commit()

cursor.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS
idx_donations_message_id
ON donations(message_id)
WHERE message_id IS NOT NULL
""")
db.commit()


# Seed settings for Guilds 1-10
for guild_name in GUILD_ROLES:
    cursor.execute("""
    INSERT OR IGNORE INTO guild_settings
    (
        guild,
        daily_requirement,
        reminder_enabled,
        daily_report_enabled,
        report_channel_id,
        reminder_hour,
        reminder_minute,
        report_hour,
        report_minute
    )
    VALUES (?, ?, 0, 0, ?, ?, ?, ?, ?)
    """, (
        guild_name,
        DEFAULT_DAILY_REQUIREMENT,
        str(TRACKER_CHANNEL_ID),
        DEFAULT_REMINDER_HOUR,
        DEFAULT_REMINDER_MINUTE,
        DEFAULT_REPORT_HOUR,
        DEFAULT_REPORT_MINUTE,
    ))

db.commit()


# Add DM reminder setting to older databases if needed.
if not column_exists("guild_settings", "dm_reminder_enabled"):
    cursor.execute("""
    ALTER TABLE guild_settings
    ADD COLUMN dm_reminder_enabled INTEGER NOT NULL DEFAULT 0
    """)
    db.commit()


# Add active-roster status to older databases if needed.
if not column_exists("roblox_members", "active"):
    cursor.execute("""
    ALTER TABLE roblox_members
    ADD COLUMN active INTEGER NOT NULL DEFAULT 1
    """)
    db.commit()


# =========================================================
# TIME
# =========================================================

def utc_now():
    return datetime.now(timezone.utc)


def ph_now():
    return datetime.now(PH_TZ)


def today_ph():
    return ph_now().date().isoformat()


def unix_timestamp(dt=None):
    if dt is None:
        dt = utc_now()
    return int(dt.timestamp())


def discord_time(timestamp):
    return f"<t:{timestamp}:F>\n<t:{timestamp}:R>"


def message_day_ph(message):
    return message.created_at.astimezone(PH_TZ).date().isoformat()


# =========================================================
# GENERAL HELPERS
# =========================================================

def normalize_name(name):
    if not name:
        return ""
    return re.sub(r"[^a-zA-Z0-9]", "", name).lower()


def get_member_names(member):

    names = set()

    if member.name:
        names.add(
            normalize_name(
                member.name
            )
        )

    if member.display_name:
        names.add(
            normalize_name(
                member.display_name
            )
        )

    if member.global_name:
        names.add(
            normalize_name(
                member.global_name
            )
        )

    return {
        name
        for name in names
        if name
    }


def names_match(
    ign,
    member
):

    ign_key = normalize_name(
        ign
    )

    if not ign_key:
        return False

    member_names = get_member_names(
        member
    )

    if ign_key in member_names:
        return True

    if len(ign_key) >= 4:

        for discord_name in member_names:

            if discord_name.startswith(
                ign_key
            ):
                return True

            if (
                len(discord_name) >= 4
                and ign_key.startswith(
                    discord_name
                )
            ):
                return True

    return False


def format_amount(amount):
    if amount >= 1_000_000_000:
        return f"{amount / 1_000_000_000:g}B"
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:g}M"
    if amount >= 1_000:
        return f"{amount / 1_000:g}K"
    return str(amount)


def convert_amount(value):
    value = value.upper().replace(",", "").replace(" ", "")
    try:
        if value.endswith("B"):
            return int(float(value[:-1]) * 1_000_000_000)
        if value.endswith("M"):
            return int(float(value[:-1]) * 1_000_000)
        if value.endswith("K"):
            return int(float(value[:-1]) * 1_000)
        return int(float(value))
    except ValueError:
        return 0


def normalize_message_text(value):
    """
    Normalize Discord text before parsing:
    - zero-width characters
    - non-breaking / Unicode spaces
    - code fences/backticks
    - repeated whitespace
    """
    if value is None:
        return ""

    value = str(value)

    # Remove common zero-width/invisible characters.
    value = re.sub(
        r"[\u200B-\u200D\u2060\uFEFF]",
        "",
        value
    )

    # Normalize Unicode spaces to normal spaces.
    value = value.replace("\u00A0", " ")
    value = value.replace("\u202F", " ")
    value = value.replace("\u2007", " ")

    # Remove Markdown code fences/backticks but keep text.
    value = value.replace("```", "")
    value = value.replace("`", "")

    # Normalize line endings.
    value = value.replace("\r\n", "\n")
    value = value.replace("\r", "\n")

    # Collapse horizontal whitespace while preserving lines.
    lines = []

    for line in value.split("\n"):
        line = re.sub(
            r"[ \t]+",
            " ",
            line
        ).strip()

        if line:
            lines.append(line)

    return "\n".join(lines)


def get_message_donation_text(message):
    """
    Combine every useful Discord text source into one normalized
    parser input:
    - message.content
    - message.system_content
    - embed title
    - embed description
    - embed author
    - embed fields
    - embed footer

    This helps with webhook/embed/code-block donation formats.
    """
    parts = []

    content = getattr(
        message,
        "content",
        None
    )

    if content:
        parts.append(
            content
        )

    system_content = getattr(
        message,
        "system_content",
        None
    )

    if system_content and system_content != content:
        parts.append(
            system_content
        )

    for embed in (
        getattr(
            message,
            "embeds",
            []
        )
        or []
    ):

        if embed.title:
            parts.append(
                str(embed.title)
            )

        if embed.description:
            parts.append(
                str(embed.description)
            )

        if (
            embed.author
            and embed.author.name
        ):
            parts.append(
                str(
                    embed.author.name
                )
            )

        for field in embed.fields:

            if field.name:
                parts.append(
                    str(field.name)
                )

            if field.value:
                parts.append(
                    str(field.value)
                )

        if (
            embed.footer
            and embed.footer.text
        ):
            parts.append(
                str(
                    embed.footer.text
                )
            )

    return normalize_message_text(
        "\n".join(
            str(part)
            for part in parts
            if part is not None
        )
    )


def _extract_amount_from_text(value):
    """
    Finds amounts such as:
    100K
    100,000
    24.9M
    1.2B
    """
    if not value:
        return 0

    match = re.search(
        r"(\d[\d,]*(?:\.\d+)?\s*[KMB]?)",
        value,
        re.IGNORECASE
    )

    if not match:
        return 0

    return convert_amount(
        match.group(1)
    )


def looks_like_donation_message(text):
    """
    Used only for live warnings.
    Normal chat should not trigger a warning.
    """
    lowered = text.lower()

    signals = 0

    for keyword in (
        "ign",
        "guild gold",
        "previous",
        "prev",
        "current",
        "daily donation",
        "donation",
        "donated",
        "gold donated",
        "gold donation",
    ):
        if keyword in lowered:
            signals += 1

    amount_hits = re.findall(
        r"\d[\d,]*(?:\.\d+)?\s*[KMB]?",
        text,
        re.IGNORECASE
    )

    # Require multiple donation-like clues.
    return (
        signals >= 2
        or (
            signals >= 1
            and len(amount_hits) >= 2
        )
    )


def parse_donation_message(text):
    """
    Flexible donation parser.

    It accepts the normal format and small mistakes such as:
      IGN: Player
      IGN - Player
      IGN Player
      Player IGN: Player

      Previous Guild Gold: 24.9M
      Prev Gold - 24.9M
      Before Gold: 24.9M

      Current Guild Gold: 25.0M
      Current Gold - 25.0M
      After Gold: 25.0M

      Daily Donation: 100K
      Gold donated: 100,000
      Donation - 100K
      Donated 100K

    If the donation line is missing but previous/current gold are
    both available, the bot calculates:
        current - previous

    Previous/current gold are optional as long as IGN and donation
    can still be identified.
    """

    raw_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    if not raw_lines:
        return None

    ign = None
    previous = "Unknown"
    current = "Unknown"
    donation_text = None
    donation_amount = 0

    previous_amount = 0
    current_amount = 0

    # -----------------------------------------------------
    # PASS 1: labelled lines
    # -----------------------------------------------------
    for line in raw_lines:
        clean = line.strip()

        # IGN variations
        ign_match = re.match(
            r"^(?:player\s*)?(?:ign|in[\s-]*game\s*name|roblox\s*ign|player)"
            r"\s*(?:[:=\-|>]\s*|\s+)(.+?)$",
            clean,
            re.IGNORECASE
        )

        if ign_match and not ign:
            candidate = ign_match.group(1).strip()

            if normalize_name(candidate) not in {
                "ign",
                "previousguildgold",
                "currentguildgold",
                "dailydonation",
                "golddonated",
                "donation",
                "donated",
            }:
                ign = candidate

            continue

        # Previous gold variations
        previous_match = re.match(
            r"^(?:previous|prev|before|old)"
            r"(?:\s+guild)?\s*(?:gold|amount)?"
            r"\s*(?:[:=\-|>]\s*|\s+)(.+?)$",
            clean,
            re.IGNORECASE
        )

        if previous_match:
            previous = previous_match.group(1).strip()
            previous_amount = _extract_amount_from_text(
                previous
            )
            continue

        # Current gold variations
        current_match = re.match(
            r"^(?:current|curr|after|new)"
            r"(?:\s+guild)?\s*(?:gold|amount)?"
            r"\s*(?:[:=\-|>]\s*|\s+)(.+?)$",
            clean,
            re.IGNORECASE
        )

        if current_match:
            current = current_match.group(1).strip()
            current_amount = _extract_amount_from_text(
                current
            )
            continue

        # Donation variations
        donation_match = re.match(
            r"^(?:daily\s+donation|gold\s+donated|gold\s+donation|"
            r"donation|donated|donate|gave|given|contribution)"
            r"\s*(?:[:=\-|>+]\s*|\s+)(.+?)$",
            clean,
            re.IGNORECASE
        )

        if donation_match and donation_amount <= 0:
            donation_text = donation_match.group(1).strip()
            donation_amount = _extract_amount_from_text(
                donation_text
            )
            continue

    # -----------------------------------------------------
    # PASS 2: tolerate small label typos / missing punctuation
    # -----------------------------------------------------
    if not ign:
        for line in raw_lines:
            lowered = line.lower()

            if lowered.startswith("ign"):
                remainder = re.sub(
                    r"^ign[\s:=\-]*",
                    "",
                    line,
                    flags=re.IGNORECASE
                ).strip()

                if remainder:
                    ign = remainder
                    break

    if previous == "Unknown":
        for line in raw_lines:
            lower = line.lower()

            if (
                ("prev" in lower or "previous" in lower or "before" in lower)
                and "gold" in lower
            ):
                amount = _extract_amount_from_text(
                    line
                )

                if amount > 0:
                    previous_amount = amount
                    previous = format_amount(
                        amount
                    )
                    break

    if current == "Unknown":
        for line in raw_lines:
            lower = line.lower()

            if (
                ("curr" in lower or "current" in lower or "after" in lower)
                and "gold" in lower
            ):
                amount = _extract_amount_from_text(
                    line
                )

                if amount > 0:
                    current_amount = amount
                    current = format_amount(
                        amount
                    )
                    break

    if donation_amount <= 0:
        for line in raw_lines:
            lower = line.lower()

            if (
                "donat" in lower
                or "gold given" in lower
                or "gold give" in lower
            ):
                amount = _extract_amount_from_text(
                    line
                )

                if amount > 0:
                    donation_amount = amount
                    donation_text = format_amount(
                        amount
                    )
                    break

    # -----------------------------------------------------
    # PASS 3: infer missing donation from gold difference
    # -----------------------------------------------------
    if (
        donation_amount <= 0
        and previous_amount > 0
        and current_amount > 0
        and current_amount > previous_amount
    ):
        donation_amount = (
            current_amount
            - previous_amount
        )

        donation_text = format_amount(
            donation_amount
        )

    # -----------------------------------------------------
    # PASS 4: infer IGN only when the message is clearly
    # donation-shaped. This avoids treating normal chat as a log.
    # -----------------------------------------------------
    if (
        not ign
        and donation_amount > 0
        and (
            previous_amount > 0
            or current_amount > 0
            or looks_like_donation_message(text)
        )
    ):
        for line in raw_lines:
            lower = line.lower()

            if any(
                word in lower
                for word in (
                    "gold",
                    "donat",
                    "previous",
                    "current",
                    "before",
                    "after",
                )
            ):
                continue

            candidate = line.strip("`*_- ")

            # Roblox/display-style name safety.
            if re.fullmatch(
                r"[A-Za-z0-9_ .\-]{2,32}",
                candidate
            ):
                ign = candidate
                break

    # -----------------------------------------------------
    # PASS 5: compact / one-line formats
    # Example:
    # HADLANG | 24.9M > 25M | +100K
    # -----------------------------------------------------
    if donation_amount <= 0:
        plus_amount = re.search(
            r"\+\s*(\d[\d,]*(?:\.\d+)?\s*[KMB]?)",
            text,
            re.IGNORECASE
        )

        if plus_amount:
            donation_text = plus_amount.group(1)
            donation_amount = convert_amount(
                donation_text
            )

    if not ign and donation_amount > 0:
        # Prefer the first name-like token/segment that is not a field label.
        segments = re.split(
            r"[|\\n]",
            text
        )

        for segment in segments:
            candidate = segment.strip(" `*_-:>+")

            if not candidate:
                continue

            lower = candidate.lower()

            if any(
                word in lower
                for word in (
                    "gold",
                    "donat",
                    "previous",
                    "current",
                    "before",
                    "after",
                    "amount",
                )
            ):
                continue

            if re.fullmatch(
                r"[A-Za-z0-9_ .\\-]{2,32}",
                candidate
            ):
                # Don't use a pure number as an IGN.
                if not re.fullmatch(
                    r"[\d,.]+[KMB]?",
                    candidate,
                    re.IGNORECASE
                ):
                    ign = candidate
                    break

    # -----------------------------------------------------
    # PASS 6: universal line heuristic
    # -----------------------------------------------------
    if donation_amount <= 0 or not ign:
        lines = [
            line.strip()
            for line in normalize_message_text(
                text
            ).splitlines()
            if line.strip()
        ]

        # Find numeric lines and classify them by nearby words.
        for line in lines:
            lower = line.lower()
            amount = _extract_amount_from_text(
                line
            )

            if amount <= 0:
                continue

            if (
                donation_amount <= 0
                and any(
                    key in lower
                    for key in (
                        "donat",
                        "gave",
                        "given",
                        "contribution",
                        "added",
                        "plus",
                    )
                )
            ):
                donation_amount = amount
                donation_text = format_amount(
                    amount
                )
                continue

            if (
                previous_amount <= 0
                and any(
                    key in lower
                    for key in (
                        "previous",
                        "prev",
                        "before",
                        "old gold",
                    )
                )
            ):
                previous_amount = amount
                previous = format_amount(
                    amount
                )
                continue

            if (
                current_amount <= 0
                and any(
                    key in lower
                    for key in (
                        "current",
                        "curr",
                        "after",
                        "new gold",
                    )
                )
            ):
                current_amount = amount
                current = format_amount(
                    amount
                )
                continue

        # If donation is still missing, use the positive gold delta.
        if (
            donation_amount <= 0
            and previous_amount > 0
            and current_amount > previous_amount
        ):
            donation_amount = (
                current_amount
                - previous_amount
            )

            donation_text = format_amount(
                donation_amount
            )

        # IGN fallback: take text after IGN label with any punctuation.
        if not ign:
            ign_any = re.search(
                r"(?:^|\n)\s*(?:player\s*)?"
                r"(?:roblox\s*)?(?:ign|in[\s-]*game\s*name)"
                r"\s*[^A-Za-z0-9_]*"
                r"([A-Za-z0-9_ .\-]{2,32})"
                r"(?:\n|$)",
                normalize_message_text(
                    text
                ),
                re.IGNORECASE
            )

            if ign_any:
                candidate = ign_any.group(
                    1
                ).strip()

                if normalize_name(
                    candidate
                ) not in {
                    "ign",
                    "previousguildgold",
                    "currentguildgold",
                    "dailydonation",
                    "golddonated",
                    "donation",
                    "donated",
                }:
                    ign = candidate

        # Final name-like line fallback for donation-shaped messages.
        if (
            not ign
            and donation_amount > 0
        ):
            for line in lines:
                lower = line.lower()

                if any(
                    word in lower
                    for word in (
                        "gold",
                        "donat",
                        "previous",
                        "current",
                        "before",
                        "after",
                        "amount",
                    )
                ):
                    continue

                candidate = re.sub(
                    r"^[^A-Za-z0-9_]+|[^A-Za-z0-9_ .\-]+$",
                    "",
                    line
                ).strip()

                if re.fullmatch(
                    r"[A-Za-z0-9_ .\-]{2,32}",
                    candidate
                ):
                    if not re.fullmatch(
                        r"[\d,.]+[KMB]?",
                        candidate,
                        re.IGNORECASE
                    ):
                        ign = candidate
                        break

    # -----------------------------------------------------
    # FINAL VALIDATION
    # -----------------------------------------------------
    if not ign or donation_amount <= 0:
        return None

    if normalize_name(ign) in {
        "ign",
        "previousguildgold",
        "currentguildgold",
        "dailydonation",
        "golddonated",
        "golddonation",
        "donation",
        "donated",
        "donate",
    }:
        return None

    return {
        "ign": ign.strip(),
        "previous": previous,
        "current": current,
        "donation_text": (
            donation_text
            or format_amount(
                donation_amount
            )
        ),
        "donation_amount": donation_amount,
    }


# =========================================================
# ROBLOX MEMBER HELPERS
# =========================================================

def can_manage_roblox(member):
    """
    Leader, Co-Leader, or Manage Server can add/edit/remove
    another person's Roblox information.
    """
    if member.guild_permissions.manage_guild:
        return True

    role_ids = {role.id for role in member.roles}

    return (
        LEADER_ROLE_ID in role_ids
        or CO_LEADER_ROLE_ID in role_ids
    )


def upsert_roblox_member(
    guild_name,
    discord_user_id,
    roblox_ign,
    roblox_username,
    added_by_id,
):
    ign_key = normalize_name(
        roblox_ign
    )

    if not ign_key:
        return False, "Invalid Roblox IGN."

    if not roblox_username.strip():
        return False, "Invalid Roblox username."

    # Read the member's old saved IGN first.
    cursor.execute("""
    SELECT
        roblox_ign_key,
        roblox_ign
    FROM roblox_members
    WHERE guild=? AND discord_user_id=?
    """, (
        guild_name,
        str(discord_user_id),
    ))

    old_row = cursor.fetchone()

    # One IGN cannot belong to two different Discord users.
    cursor.execute("""
    SELECT discord_user_id
    FROM roblox_members
    WHERE guild=? AND roblox_ign_key=?
    """, (
        guild_name,
        ign_key,
    ))

    existing = cursor.fetchone()

    if (
        existing
        and existing[0] != str(discord_user_id)
    ):
        return (
            False,
            "That Roblox IGN is already assigned to another "
            "Discord member in this guild."
        )

    # If a Leader corrected the member's IGN, retire the old/wrong
    # IGN from CURRENT tracking but keep every old donation row.
    if old_row:
        old_ign_key, old_ign = old_row

        if old_ign_key != ign_key:
            mark_ign_inactive(
                guild_name,
                old_ign,
                reason="replaced",
            )

    cursor.execute("""
    INSERT INTO roblox_members
    (
        guild,
        discord_user_id,
        roblox_ign_key,
        roblox_ign,
        roblox_username,
        added_by_id,
        added_at,
        active
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, 1)

    ON CONFLICT(guild, discord_user_id)
    DO UPDATE SET
        roblox_ign_key=excluded.roblox_ign_key,
        roblox_ign=excluded.roblox_ign,
        roblox_username=excluded.roblox_username,
        added_by_id=excluded.added_by_id,
        added_at=excluded.added_at,
        active=1
    """, (
        guild_name,
        str(discord_user_id),
        ign_key,
        roblox_ign.strip(),
        roblox_username.strip(),
        str(added_by_id),
        utc_now().isoformat(),
    ))

    db.commit()

    # The new/correct IGN is active again.
    mark_ign_active(
        guild_name,
        roblox_ign,
    )

    return True, None


def remove_roblox_member(
    guild_name,
    discord_user_id,
):
    """
    Remove from CURRENT tracking only.
    Donation history and lifetime totals stay untouched.
    """
    cursor.execute("""
    SELECT roblox_ign
    FROM roblox_members
    WHERE guild=? AND discord_user_id=?
    """, (
        guild_name,
        str(discord_user_id),
    ))

    row = cursor.fetchone()

    if row:
        mark_ign_inactive(
            guild_name,
            row[0],
            reason="removed",
        )

    cursor.execute("""
    UPDATE roblox_members
    SET active=0
    WHERE guild=? AND discord_user_id=?
    """, (
        guild_name,
        str(discord_user_id),
    ))

    db.commit()


def reactivate_roblox_member(
    guild_name,
    discord_user_id,
):
    cursor.execute("""
    SELECT roblox_ign
    FROM roblox_members
    WHERE guild=? AND discord_user_id=?
    """, (
        guild_name,
        str(discord_user_id),
    ))

    row = cursor.fetchone()

    cursor.execute("""
    UPDATE roblox_members
    SET active=1
    WHERE guild=? AND discord_user_id=?
    """, (
        guild_name,
        str(discord_user_id),
    ))

    db.commit()

    if row:
        mark_ign_active(
            guild_name,
            row[0],
        )


def get_roblox_member_by_discord(
    guild_name,
    discord_user_id,
):
    cursor.execute("""
    SELECT
        roblox_ign_key,
        roblox_ign,
        roblox_username,
        active
    FROM roblox_members
    WHERE guild=? AND discord_user_id=?
    """, (
        guild_name,
        str(discord_user_id),
    ))

    return cursor.fetchone()


def get_roblox_member_by_ign(
    guild_name,
    roblox_ign,
):
    cursor.execute("""
    SELECT
        discord_user_id,
        roblox_ign_key,
        roblox_ign,
        roblox_username,
        active
    FROM roblox_members
    WHERE guild=? AND roblox_ign_key=?
    """, (
        guild_name,
        normalize_name(roblox_ign),
    ))

    return cursor.fetchone()


def get_roblox_roster(
    guild_name,
):
    cursor.execute("""
    SELECT
        discord_user_id,
        roblox_ign,
        roblox_username,
        roblox_ign_key,
        active
    FROM roblox_members
    WHERE guild=?
    ORDER BY LOWER(roblox_ign) ASC
    """, (
        guild_name,
    ))

    return cursor.fetchall()


def get_active_roster_discord_ids(
    guild_name,
):
    cursor.execute("""
    SELECT discord_user_id
    FROM roblox_members
    WHERE guild=? AND active=1
    """, (
        guild_name,
    ))

    return {
        int(row[0])
        for row in cursor.fetchall()
    }


def mark_ign_inactive(
    guild_name,
    ign,
    reason="removed",
):
    ign_key = normalize_name(ign)

    if not ign_key:
        return

    cursor.execute("""
    INSERT INTO inactive_igns
    (
        guild,
        ign_key,
        display_ign,
        reason,
        updated_at
    )
    VALUES (?, ?, ?, ?, ?)

    ON CONFLICT(guild, ign_key)
    DO UPDATE SET
        display_ign=excluded.display_ign,
        reason=excluded.reason,
        updated_at=excluded.updated_at
    """, (
        guild_name,
        ign_key,
        ign,
        reason,
        utc_now().isoformat(),
    ))

    db.commit()


def mark_ign_active(
    guild_name,
    ign,
):
    cursor.execute("""
    DELETE FROM inactive_igns
    WHERE guild=? AND ign_key=?
    """, (
        guild_name,
        normalize_name(ign),
    ))

    db.commit()


def is_ign_inactive(
    guild_name,
    ign_key,
):
    cursor.execute("""
    SELECT 1
    FROM inactive_igns
    WHERE guild=? AND ign_key=?
    LIMIT 1
    """, (
        guild_name,
        ign_key,
    ))

    return cursor.fetchone() is not None


# =========================================================
# GUILD SETTINGS
# =========================================================

def get_guild_setting(guild_name):
    cursor.execute("""
    SELECT
        daily_requirement,
        reminder_enabled,
        daily_report_enabled,
        report_channel_id,
        reminder_hour,
        reminder_minute,
        report_hour,
        report_minute,
        dm_reminder_enabled
    FROM guild_settings
    WHERE guild=?
    """, (guild_name,))

    row = cursor.fetchone()

    if not row:
        return {
            "daily_requirement": DEFAULT_DAILY_REQUIREMENT,
            "reminder_enabled": False,
            "daily_report_enabled": False,
            "report_channel_id": str(TRACKER_CHANNEL_ID),
            "reminder_hour": DEFAULT_REMINDER_HOUR,
            "reminder_minute": DEFAULT_REMINDER_MINUTE,
            "report_hour": DEFAULT_REPORT_HOUR,
            "report_minute": DEFAULT_REPORT_MINUTE,
            "dm_reminder_enabled": False,
        }

    return {
        "daily_requirement": row[0],
        "reminder_enabled": bool(row[1]),
        "daily_report_enabled": bool(row[2]),
        "report_channel_id": row[3],
        "reminder_hour": row[4],
        "reminder_minute": row[5],
        "report_hour": row[6],
        "report_minute": row[7],
        "dm_reminder_enabled": bool(row[8]),
    }


def daily_requirement(guild_name):
    return get_guild_setting(guild_name)["daily_requirement"]


# =========================================================
# CREDIT / COVERAGE
# =========================================================

def is_day_covered(guild_name, ign_key, covered_day):
    cursor.execute("""
    SELECT 1
    FROM donation_coverage
    WHERE guild=? AND ign_key=? AND covered_day=?
    LIMIT 1
    """, (
        guild_name,
        ign_key,
        covered_day,
    ))
    return cursor.fetchone() is not None


def get_credit_balance(guild_name, ign_key):
    cursor.execute("""
    SELECT balance
    FROM donation_credit
    WHERE guild=? AND ign_key=?
    """, (
        guild_name,
        ign_key,
    ))

    row = cursor.fetchone()
    return row[0] if row else 0


def set_credit_balance(
    guild_name,
    ign_key,
    display_ign,
    balance,
    commit=True
):
    cursor.execute("""
    INSERT INTO donation_credit
    (
        guild,
        ign_key,
        display_ign,
        balance
    )
    VALUES (?, ?, ?, ?)
    ON CONFLICT(guild, ign_key)
    DO UPDATE SET
        display_ign=excluded.display_ign,
        balance=excluded.balance
    """, (
        guild_name,
        ign_key,
        display_ign,
        balance,
    ))

    if commit:
        db.commit()


def add_coverage(
    guild_name,
    ign_key,
    display_ign,
    covered_day
):
    cursor.execute("""
    INSERT OR IGNORE INTO donation_coverage
    (
        guild,
        ign_key,
        display_ign,
        covered_day
    )
    VALUES (?, ?, ?, ?)
    """, (
        guild_name,
        ign_key,
        display_ign,
        covered_day,
    ))


def apply_credit(
    guild_name,
    ign,
    amount,
    start_day,
    commit=True
):
    ign_key = normalize_name(ign)
    balance = get_credit_balance(guild_name, ign_key) + amount
    requirement = daily_requirement(guild_name)
    check_date = date.fromisoformat(start_day)

    days_added = 0

    while balance >= requirement and days_added < MAX_ADVANCE_DAYS:
        safety_hops = 0

        while is_day_covered(
            guild_name,
            ign_key,
            check_date.isoformat()
        ):
            check_date += timedelta(days=1)
            safety_hops += 1

            if safety_hops >= MAX_ADVANCE_DAYS:
                break

        if safety_hops >= MAX_ADVANCE_DAYS:
            break

        add_coverage(
            guild_name,
            ign_key,
            ign,
            check_date.isoformat()
        )

        balance -= requirement
        days_added += 1
        check_date += timedelta(days=1)

    set_credit_balance(
        guild_name,
        ign_key,
        ign,
        balance,
        commit=False,
    )

    if commit:
        db.commit()

    return balance


def covered_through_from_day(
    guild_name,
    ign_key,
    start_day
):
    current = date.fromisoformat(start_day)

    if not is_day_covered(
        guild_name,
        ign_key,
        current.isoformat()
    ):
        return None

    last = current
    checked = 0

    while (
        checked < MAX_ADVANCE_DAYS
        and is_day_covered(
            guild_name,
            ign_key,
            current.isoformat()
        )
    ):
        last = current
        checked += 1

        if checked >= MAX_ADVANCE_DAYS:
            break

        current += timedelta(days=1)

    return last.isoformat()


def get_covered_through(guild_name, ign_key):
    return covered_through_from_day(
        guild_name,
        ign_key,
        today_ph()
    )


def rebuild_player_credit(guild_name, ign):
    """
    Rebuild one player's coverage after an edit/removal.
    This avoids broken advance-payment math.
    """

    ign_key = normalize_name(ign)

    cursor.execute("""
    DELETE FROM donation_coverage
    WHERE guild=? AND ign_key=?
    """, (
        guild_name,
        ign_key,
    ))

    cursor.execute("""
    DELETE FROM donation_credit
    WHERE guild=? AND ign_key=?
    """, (
        guild_name,
        ign_key,
    ))

    db.commit()

    cursor.execute("""
    SELECT id, ign, donation, day
    FROM donations
    WHERE guild=?
    ORDER BY day ASC, id ASC
    """, (guild_name,))

    rows = cursor.fetchall()

    for donation_id, row_ign, amount, donation_day in rows:
        if normalize_name(row_ign) != ign_key:
            continue

        apply_credit(
            guild_name,
            row_ign,
            amount,
            donation_day,
        )


def get_streak(guild_name, ign_key):
    """
    Consecutive covered days ending today.
    """
    current = date.fromisoformat(today_ph())
    streak = 0

    while is_day_covered(
        guild_name,
        ign_key,
        current.isoformat()
    ):
        streak += 1
        current -= timedelta(days=1)

    return streak


# =========================================================
# DONATIONS / DUPLICATES
# =========================================================

def message_already_logged(message_id):
    cursor.execute("""
    SELECT id
    FROM donations
    WHERE message_id=?
    LIMIT 1
    """, (str(message_id),))

    return cursor.fetchone() is not None


def find_old_unlinked_donation(
    guild_name,
    ign,
    previous,
    current,
    amount,
    donation_day
):
    cursor.execute("""
    SELECT
        id,
        ign,
        previous_gold,
        current_gold
    FROM donations
    WHERE guild=?
      AND day=?
      AND donation=?
      AND message_id IS NULL
    ORDER BY id ASC
    """, (
        guild_name,
        donation_day,
        amount,
    ))

    wanted_ign = normalize_name(ign)

    for donation_id, db_ign, db_previous, db_current in cursor.fetchall():
        if normalize_name(db_ign) != wanted_ign:
            continue

        if (
            previous != "Unknown"
            and db_previous
            and db_previous != "Unknown"
            and db_previous.strip().lower()
            != previous.strip().lower()
        ):
            continue

        if (
            current != "Unknown"
            and db_current
            and db_current != "Unknown"
            and db_current.strip().lower()
            != current.strip().lower()
        ):
            continue

        return donation_id

    return None


def link_message_to_existing_donation(
    donation_id,
    message_id,
    channel_id
):
    cursor.execute("""
    UPDATE donations
    SET message_id=?, channel_id=?
    WHERE id=?
    """, (
        str(message_id),
        str(channel_id),
        donation_id,
    ))
    db.commit()


def save_donation(
    guild_name,
    ign,
    previous,
    current,
    donation,
    logged_by,
    logged_by_id,
    timestamp,
    donation_day,
    message_id,
    channel_id
):
    if message_already_logged(
        message_id
    ):
        return None

    cursor.execute("""
    INSERT INTO donations
    (
        guild,
        ign,
        previous_gold,
        current_gold,
        donation,
        logged_by,
        logged_by_id,
        time,
        day,
        message_id,
        channel_id
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        guild_name,
        ign,
        previous,
        current,
        donation,
        logged_by,
        str(logged_by_id),
        str(timestamp),
        donation_day,
        str(message_id),
        str(channel_id),
    ))

    donation_id = cursor.lastrowid

    apply_credit(
        guild_name,
        ign,
        donation,
        donation_day,
        commit=False,
    )

    cursor.execute("""
    INSERT OR IGNORE INTO credit_processed
    (donation_id)
    VALUES (?)
    """, (
        donation_id,
    ))

    db.commit()

    return donation_id


def get_leaderboard_data(guild_name, period):
    today = date.fromisoformat(today_ph())

    if period == "today":
        start_day = today.isoformat()

        cursor.execute("""
        SELECT ign, SUM(donation)
        FROM donations
        WHERE guild=? AND day=?
        GROUP BY LOWER(ign)
        ORDER BY SUM(donation) DESC
        LIMIT 10
        """, (
            guild_name,
            start_day,
        ))

    elif period == "week":
        start_day = (today - timedelta(days=6)).isoformat()

        cursor.execute("""
        SELECT ign, SUM(donation)
        FROM donations
        WHERE guild=? AND day>=?
        GROUP BY LOWER(ign)
        ORDER BY SUM(donation) DESC
        LIMIT 10
        """, (
            guild_name,
            start_day,
        ))

    else:
        cursor.execute("""
        SELECT ign, SUM(donation)
        FROM donations
        WHERE guild=?
        GROUP BY LOWER(ign)
        ORDER BY SUM(donation) DESC
        LIMIT 10
        """, (guild_name,))

    return cursor.fetchall()


# =========================================================
# MEMBER STATUS
# =========================================================

async def ensure_members(server):
    try:
        await asyncio.wait_for(
            server.chunk(cache=True),
            timeout=10,
        )
    except Exception as exc:
        print(f"Member chunk warning: {exc}")


def get_accounts(guild_name):
    cursor.execute("""
    SELECT ign_key, display_ign, balance
    FROM donation_credit
    WHERE guild=?
    """, (guild_name,))

    return cursor.fetchall()


def calculate_member_status(
    guild_name,
    members,
    check_day=None
):
    if check_day is None:
        check_day = today_ph()

    accounts = get_accounts(guild_name)

    account_lookup = {
        ign_key: (
            ign_key,
            display_ign,
            balance,
        )
        for ign_key, display_ign, balance in accounts
    }

    covered_members = []
    missing_members = []
    matched_keys = set()

    for member in members:
        matched = None

        # -------------------------------------------------
        # 1) Saved Discord / Roblox IGN / Roblox Username
        #    mapping has priority.
        # -------------------------------------------------
        saved = get_roblox_member_by_discord(
            guild_name,
            member.id,
        )

        if saved:
            saved_ign_key, saved_ign, saved_username, saved_active = saved

            if not saved_active:
                # Kicked/inactive players do not appear in current daily tracking.
                continue

            matched = account_lookup.get(
                saved_ign_key,
                (
                    saved_ign_key,
                    saved_ign,
                    0,
                )
            )

        # -------------------------------------------------
        # 2) Fall back to safe automatic name matching.
        # -------------------------------------------------
        if matched is None:
            for (
                ign_key,
                display_ign,
                balance
            ) in accounts:

                if names_match(
                    display_ign,
                    member
                ):
                    matched = (
                        ign_key,
                        display_ign,
                        balance,
                    )
                    break

        if matched is None:
            missing_members.append(
                member
            )
            continue

        ign_key, display_ign, balance = matched

        matched_keys.add(
            ign_key
        )

        if is_day_covered(
            guild_name,
            ign_key,
            check_day
        ):
            through = covered_through_from_day(
                guild_name,
                ign_key,
                check_day
            )

            covered_members.append(
                (
                    member,
                    display_ign,
                    through,
                    balance,
                )
            )
        else:
            missing_members.append(
                member
            )

    # -----------------------------------------------------
    # Donation IGNs that do not have a Discord mapping.
    # -----------------------------------------------------
    unlinked = []

    for (
        ign_key,
        display_ign,
        balance
    ) in accounts:

        if ign_key in matched_keys:
            continue

        # Old/kicked/replaced IGNs keep their historical donations,
        # but must not appear in current daily status.
        if is_ign_inactive(
            guild_name,
            ign_key,
        ):
            continue

        # If this IGN exists in the saved Roblox roster,
        # it is linked even when the user does not currently
        # have the guild Discord role.
        roster_match = get_roblox_member_by_ign(
            guild_name,
            display_ign,
        )

        if roster_match:
            roster_active = roster_match[-1]

            if roster_active:
                continue

        if any(
            names_match(
                display_ign,
                member
            )
            for member in members
        ):
            continue

        covered = is_day_covered(
            guild_name,
            ign_key,
            check_day
        )

        through = (
            covered_through_from_day(
                guild_name,
                ign_key,
                check_day
            )
            if covered
            else None
        )

        unlinked.append(
            (
                display_ign,
                balance,
                covered,
                through,
            )
        )

    return (
        covered_members,
        missing_members,
        unlinked,
    )


# =========================================================
# COMPONENTS V2 UI
# =========================================================

def make_view(
    accent_colour,
    blocks,
    *,
    url_button=None,
    timeout=180
):
    """
    blocks: list[str] where each item becomes a TextDisplay.
    """
    view = discord.ui.LayoutView(timeout=timeout)

    container = discord.ui.Container(
        accent_colour=accent_colour
    )

    for index, text in enumerate(blocks):
        if index > 0:
            container.add_item(
                discord.ui.Separator()
            )

        container.add_item(
            discord.ui.TextDisplay(text)
        )

    if url_button:
        row = discord.ui.ActionRow()
        row.add_item(
            discord.ui.Button(
                label=url_button[0],
                style=discord.ButtonStyle.link,
                url=url_button[1],
                emoji="🔗",
            )
        )
        container.add_item(
            discord.ui.Separator()
        )
        container.add_item(row)

    view.add_item(container)
    return view


def tracker_view(
    guild_name,
    ign,
    previous,
    current,
    donation_amount,
    author,
    timestamp,
    message_url,
    imported=False
):
    ign_key = normalize_name(ign)
    balance = get_credit_balance(
        guild_name,
        ign_key
    )
    through = get_covered_through(
        guild_name,
        ign_key
    )

    if through:
        if through == today_ph():
            coverage = "🟢 **Covered today**"
        else:
            pretty = datetime.strptime(
                through,
                "%Y-%m-%d"
            ).strftime("%d %b %Y")

            coverage = (
                f"🟢 **Paid through {pretty}**"
            )
    else:
        coverage = (
            "📚 **Historical payment recorded**"
            if imported
            else "🔴 **Not currently covered**"
        )

    if balance > 0:
        coverage += (
            f"\n💳 Credit remaining: "
            f"**{format_amount(balance)}**"
        )

    title = (
        "📚 **HISTORICAL DONATION**"
        if imported
        else "✅ **DONATION RECORDED**"
    )

    accent = (
        discord.Colour.blue()
        if imported
        else discord.Colour.green()
    )

    header = (
        f"{title}\n"
        f"-# {'Imported from old guild logs' if imported else 'Guild donation successfully tracked'}"
    )

    stats = (
        f"### 👤 Player\n**{ign}**\n"
        f"### 🛡️ Guild\n**{guild_name}**\n"
        f"### 💰 Donation\n"
        f"**{format_amount(donation_amount)}** "
        f"(`{donation_amount:,}`)"
    )

    gold = (
        f"### 🪙 Guild Gold\n"
        f"**{previous}**  ➜  **{current}**\n\n"
        f"### 📅 Coverage\n{coverage}"
    )

    details = (
        f"### 📝 Logged By\n{author.mention}\n"
        f"### 🕒 Original Time\n"
        f"<t:{timestamp}:F> • <t:{timestamp}:R>\n\n"
        f"-# 100K = 1 day • Daily reset: 12:00 AM Philippines Time"
    )

    return make_view(
        accent,
        [
            header,
            stats,
            gold,
            details,
        ],
        url_button=(
            "Jump to Message",
            message_url,
        ),
    )


def status_view(
    guild_name,
    members,
    covered_members,
    missing_members,
    unlinked,
):
    requirement = daily_requirement(
        guild_name
    )

    header = (
        f"👥 **{guild_name.upper()} DONATION STATUS**\n"
        f"-# Daily requirement: {format_amount(requirement)} "
        f"• Reset: 12:00 AM Philippines Time "
        f"• Updated <t:{unix_timestamp()}:R>"
    )

    stats = (
        f"### 👥 Members\n**{len(members)}**\n"
        f"### ✅ Covered Today\n**{len(covered_members)}**\n"
        f"### ❌ Missing Today\n**{len(missing_members)}**\n"
        f"### 🎮 Unlinked Accounts\n**{len(unlinked)}**"
    )

    covered_lines = []
    for member, ign, through, balance in covered_members[:35]:
        if through and through != today_ph():
            pretty = datetime.strptime(
                through,
                "%Y-%m-%d"
            ).strftime("%d %b")

            detail = f"Paid through **{pretty}**"
        else:
            detail = "Covered today"

        if balance > 0:
            detail += (
                f" • {format_amount(balance)} credit"
            )

        covered_lines.append(
            f"🟢 **{member.display_name}**\n"
            f"-# {detail}"
        )

    if len(covered_members) > 35:
        covered_lines.append(
            f"-# +{len(covered_members) - 35} more"
        )

    missing_lines = [
        f"🔴 {member.mention} • **{member.display_name}**"
        for member in missing_members[:35]
    ]

    if len(missing_members) > 35:
        missing_lines.append(
            f"-# +{len(missing_members) - 35} more"
        )

    unlinked_lines = []
    for ign, balance, covered, through in unlinked[:30]:
        if covered:
            if through and through != today_ph():
                pretty = datetime.strptime(
                    through,
                    "%Y-%m-%d"
                ).strftime("%d %b")
                detail = f"Paid through **{pretty}**"
            else:
                detail = "Covered today"

            icon = "🟢"
        else:
            detail = "Not covered today"
            icon = "🔴"

        if balance > 0:
            detail += (
                f" • {format_amount(balance)} credit"
            )

        unlinked_lines.append(
            f"{icon} **{ign}**\n-# {detail}"
        )

    if len(unlinked) > 30:
        unlinked_lines.append(
            f"-# +{len(unlinked) - 30} more"
        )

    blocks = [
        header,
        stats,
        (
            "## ✅ Covered Today\n"
            + (
                "\n".join(covered_lines)
                if covered_lines
                else "Nobody is covered yet."
            )
        ),
        (
            "## ❌ Missing Today\n"
            + (
                "\n".join(missing_lines)
                if missing_lines
                else "🎉 **Everyone is covered!**"
            )
        ),
        (
            "## 🎮 Unlinked Roblox Accounts\n"
            + (
                "\n".join(unlinked_lines)
                if unlinked_lines
                else "No unlinked accounts."
            )
            + "\n-# Their donations are saved; the bot just cannot match the IGN to a Discord member."
        ),
    ]

    return make_view(
        discord.Colour.purple(),
        blocks,
    )


def leaderboard_view(
    guild_name,
    data,
    period
):
    period_names = {
        "today": "Today",
        "week": "Last 7 Days",
        "all": "All Time",
    }

    title = (
        f"🏆 **{guild_name.upper()} DONATION LEADERBOARD**\n"
        f"-# {period_names[period]}"
    )

    if not data:
        body = "No donations recorded for this period."
    else:
        lines = []
        medals = ["🥇", "🥈", "🥉"]

        for index, (ign, amount) in enumerate(
            data,
            start=1
        ):
            rank = (
                medals[index - 1]
                if index <= 3
                else f"**{index}.**"
            )

            lines.append(
                f"{rank} **{ign}** — "
                f"**{format_amount(amount)}** "
                f"(`{amount:,}`)"
            )

        body = "\n\n".join(lines)

    return make_view(
        discord.Colour.gold(),
        [
            title,
            body,
            "-# Lifetime/history data is based on saved donation logs.",
        ],
    )


def simple_info_view(
    title,
    body,
    colour=discord.Colour.blurple()
):
    return make_view(
        colour,
        [
            f"## {title}",
            body,
        ],
    )


# =========================================================
# COVERAGE REPAIR
# =========================================================

def rebuild_all_coverage_safely():
    cursor.execute("DELETE FROM donation_coverage")
    cursor.execute("DELETE FROM donation_credit")
    db.commit()

    cursor.execute("""
    SELECT guild, ign, donation, day
    FROM donations
    ORDER BY day ASC, id ASC
    """)

    for guild_name, ign, amount, donation_day in cursor.fetchall():
        if not donation_day:
            continue

        try:
            apply_credit(
                guild_name,
                ign,
                amount,
                donation_day,
                commit=False,
            )
        except Exception as exc:
            print(
                f"COVERAGE REBUILD SKIP "
                f"{guild_name} / {ign}: {repr(exc)}"
            )

    db.commit()


# =========================================================
# BOT
# =========================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class DonationBot(commands.Bot):

    async def setup_hook(self):
        guild_obj = discord.Object(
            id=SERVER_ID
        )

        # 1) Remove stale server-specific commands first.
        self.tree.clear_commands(
            guild=guild_obj
        )
        await self.tree.sync(
            guild=guild_obj
        )

        # 2) Copy every CURRENT command in this file to the server.
        self.tree.copy_global_to(
            guild=guild_obj
        )

        # 3) Delete OLD GLOBAL commands from Discord.
        # This is what removes the duplicate /donationstatus
        # that still only shows Guild 1-9.
        self.tree.clear_commands(
            guild=None
        )
        await self.tree.sync()

        # 4) Sync only the fresh server commands.
        synced = await self.tree.sync(
            guild=guild_obj
        )

        print(
            f"Synced {len(synced)} server commands "
            f"to {SERVER_ID}"
        )
        print(
            "Old global slash commands cleared."
        )
        print(
            "Fresh server slash commands synced."
        )

        automation_loop.start()


bot = DonationBot(
    command_prefix="!",
    intents=intents,
)

# Prevent live logs, sync, and commands from writing to SQLite at the same time.
db_write_lock = asyncio.Lock()


# =========================================================
# CHOICES
# =========================================================

GUILD_CHOICES = [
    app_commands.Choice(
        name=f"Guild {i}",
        value=f"Guild {i}",
    )
    for i in range(1, 12)
]

SYNC_GUILD_CHOICES = [
    app_commands.Choice(
        name="All Guilds",
        value="ALL",
    )
] + GUILD_CHOICES

PERIOD_CHOICES = [
    app_commands.Choice(
        name="Today",
        value="today",
    ),
    app_commands.Choice(
        name="Last 7 Days",
        value="week",
    ),
    app_commands.Choice(
        name="All Time",
        value="all",
    ),
]


# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    print(f"Database: {DB_PATH}")
    print("Guild 10 enabled.")
    print("Guild 11 enabled.")


# =========================================================
# AUTO ROSTER UPDATE FROM DISCORD ROLES
# =========================================================

@bot.event
async def on_member_update(
    before,
    after,
):
    if after.guild.id != SERVER_ID:
        return

    before_role_ids = {
        role.id
        for role in before.roles
    }

    after_role_ids = {
        role.id
        for role in after.roles
    }

    for guild_name, role_id in GUILD_ROLES.items():

        had_role = (
            role_id in before_role_ids
        )

        has_role = (
            role_id in after_role_ids
        )

        if had_role == has_role:
            continue

        saved = get_roblox_member_by_discord(
            guild_name,
            after.id,
        )

        if not saved:
            continue

        if has_role:
            reactivate_roblox_member(
                guild_name,
                after.id,
            )

            print(
                f"Roster auto-reactivated: "
                f"{guild_name} / {after.id}"
            )

        else:
            remove_roblox_member(
                guild_name,
                after.id,
            )

            print(
                f"Roster auto-deactivated: "
                f"{guild_name} / {after.id}"
            )


# =========================================================
# LIVE / OLD LOG PROCESSING
# =========================================================

async def process_donation_message(
    message,
    imported=False
):
    if message.author.bot:
        return "invalid"

    if message.channel.id not in GUILD_CHANNELS:
        return "invalid"

    donation_source_text = get_message_donation_text(
        message
    )

    parsed = parse_donation_message(
        donation_source_text
    )

    if not parsed:
        return "invalid"

    if message_already_logged(
        message.id
    ):
        return "duplicate"

    guild_name = GUILD_CHANNELS[
        message.channel.id
    ]

    ign = parsed["ign"]
    previous = parsed["previous"]
    current = parsed["current"]
    donation_amount = parsed[
        "donation_amount"
    ]

    timestamp = unix_timestamp(
        message.created_at
    )

    donation_day = message_day_ph(
        message
    )

    async with db_write_lock:

        if imported:
            existing_id = (
                find_old_unlinked_donation(
                    guild_name,
                    ign,
                    previous,
                    current,
                    donation_amount,
                    donation_day,
                )
            )

            if existing_id:
                link_message_to_existing_donation(
                    existing_id,
                    message.id,
                    message.channel.id,
                )
                return "linked"

        donation_id = save_donation(
            guild_name=guild_name,
            ign=ign,
            previous=previous,
            current=current,
            donation=donation_amount,
            logged_by=message.author.display_name,
            logged_by_id=message.author.id,
            timestamp=timestamp,
            donation_day=donation_day,
            message_id=message.id,
            channel_id=message.channel.id,
        )

    if donation_id is None:
        return "duplicate"

    tracker = bot.get_channel(
        TRACKER_CHANNEL_ID
    )

    if tracker is None:
        try:
            tracker = await bot.fetch_channel(
                TRACKER_CHANNEL_ID
            )
        except Exception as exc:
            print(f"Tracker fetch error: {exc}")
            return "saved_no_tracker"

    await tracker.send(
        view=tracker_view(
            guild_name,
            ign,
            previous,
            current,
            donation_amount,
            message.author,
            timestamp,
            message.jump_url,
            imported=imported,
        )
    )

    return (
        "imported"
        if imported
        else "saved"
    )


@bot.event
async def on_message(message):
    await bot.process_commands(
        message
    )

    if message.author.bot:
        return

    if message.channel.id not in GUILD_CHANNELS:
        return

    try:
        result = await process_donation_message(
            message,
            imported=False,
        )

        if result == "saved":
            try:
                await message.add_reaction(
                    "✅"
                )
            except discord.HTTPException:
                pass

        elif (
            result == "invalid"
            and looks_like_donation_message(
                get_message_donation_text(
                    message
                )
            )
        ):
            try:
                await message.add_reaction(
                    "⚠️"
                )
            except discord.HTTPException:
                pass

            try:
                await message.reply(
                    "⚠️ **Donation Not Logged**\n"
                    "I could tell this looks like a donation log, "
                    "but I still couldn't safely find both the "
                    "**player IGN** and **donation amount**.\n\n"
                    "Small formatting mistakes are okay — you can use "
                    "`IGN`, `Gold donated`, `Daily Donation`, "
                    "`Previous/Current Gold`, etc.",
                    mention_author=False,
                    delete_after=30,
                )
            except discord.HTTPException:
                pass

    except Exception as exc:
        print(
            f"LIVE DONATION ERROR: "
            f"{repr(exc)}"
        )


# =========================================================
# /DONATIONSTATUS
# =========================================================

@bot.tree.command(
    name="donationstatus",
    description="See who is covered and missing today's donation"
)
@app_commands.describe(
    guild="Choose a guild"
)
@app_commands.choices(
    guild=GUILD_CHOICES
)
async def donationstatus(
    interaction: discord.Interaction,
    guild: app_commands.Choice[str],
):
    await interaction.response.defer(
        thinking=True
    )

    guild_name = guild.value
    role_id = GUILD_ROLES.get(
        guild_name
    )

    if not role_id:
        await interaction.followup.send(
            "❌ Guild role is not configured."
        )
        return

    server = interaction.guild

    if server is None:
        return

    await ensure_members(server)

    role = server.get_role(role_id)

    if role is None:
        await interaction.followup.send(
            f"❌ Couldn't find the role for "
            f"**{guild_name}**."
        )
        return

    members = [
        member
        for member in role.members
        if not member.bot
    ]

    # If a saved roster member was deactivated, exclude them from
    # current daily tracking even if they still temporarily have the Discord role.
    filtered_members = []

    for member in members:
        saved = get_roblox_member_by_discord(
            guild_name,
            member.id,
        )

        if saved and not saved[-1]:
            continue

        filtered_members.append(
            member
        )

    members = filtered_members

    covered, missing, unlinked = (
        calculate_member_status(
            guild_name,
            members,
        )
    )

    await interaction.followup.send(
        view=status_view(
            guild_name,
            members,
            covered,
            missing,
            unlinked,
        )
    )


# =========================================================
# /MISSING
# =========================================================

@bot.tree.command(
    name="missing",
    description="Show only members missing today's donation"
)
@app_commands.describe(
    guild="Choose a guild"
)
@app_commands.choices(
    guild=GUILD_CHOICES
)
async def missing(
    interaction: discord.Interaction,
    guild: app_commands.Choice[str],
):
    await interaction.response.defer(
        thinking=True
    )

    server = interaction.guild
    guild_name = guild.value

    if server is None:
        return

    await ensure_members(server)

    role = server.get_role(
        GUILD_ROLES[guild_name]
    )

    if role is None:
        await interaction.followup.send(
            "❌ Guild role not found."
        )
        return

    members = [
        member
        for member in role.members
        if not member.bot
    ]

    members = [
        member
        for member in members
        if not (
            (saved := get_roblox_member_by_discord(guild_name, member.id))
            and not saved[-1]
        )
    ]

    _, missing_members, _ = (
        calculate_member_status(
            guild_name,
            members,
        )
    )

    if missing_members:
        body = "\n".join(
            f"🔴 {m.mention} • **{m.display_name}**"
            for m in missing_members[:60]
        )

        if len(missing_members) > 60:
            body += (
                f"\n-# +{len(missing_members)-60} more"
            )
    else:
        body = "🎉 **Everyone is covered today!**"

    await interaction.followup.send(
        view=simple_info_view(
            f"❌ {guild_name} Missing Today",
            body,
            discord.Colour.red(),
        )
    )


# =========================================================
# /GUILDSUMMARY
# =========================================================

@bot.tree.command(
    name="guildsummary",
    description="Show a quick donation summary for a guild"
)
@app_commands.describe(
    guild="Choose a guild"
)
@app_commands.choices(
    guild=GUILD_CHOICES
)
async def guildsummary(
    interaction: discord.Interaction,
    guild: app_commands.Choice[str],
):
    await interaction.response.defer(
        thinking=True
    )

    guild_name = guild.value
    server = interaction.guild

    if server is None:
        return

    await ensure_members(server)

    role = server.get_role(
        GUILD_ROLES[guild_name]
    )

    if role is None:
        await interaction.followup.send(
            "❌ Guild role not found."
        )
        return

    members = [
        m
        for m in role.members
        if not m.bot
    ]

    members = [
        member
        for member in members
        if not (
            (saved := get_roblox_member_by_discord(guild_name, member.id))
            and not saved[-1]
        )
    ]

    covered, missing_members, unlinked = (
        calculate_member_status(
            guild_name,
            members,
        )
    )

    cursor.execute("""
    SELECT COALESCE(SUM(donation), 0)
    FROM donations
    WHERE guild=? AND day=?
    """, (
        guild_name,
        today_ph(),
    ))

    donated_today_amount = (
        cursor.fetchone()[0]
    )

    body = (
        f"### 👥 Members\n**{len(members)}**\n"
        f"### ✅ Covered\n**{len(covered)}**\n"
        f"### ❌ Missing\n**{len(missing_members)}**\n"
        f"### 🎮 Unlinked\n**{len(unlinked)}**\n"
        f"### 💰 Logged Today\n"
        f"**{format_amount(donated_today_amount)}** "
        f"(`{donated_today_amount:,}`)\n\n"
        f"-# Reset: 12:00 AM Philippines Time"
    )

    await interaction.followup.send(
        view=simple_info_view(
            f"📊 {guild_name} Summary",
            body,
            discord.Colour.purple(),
        )
    )


# =========================================================
# /LEADERBOARD
# =========================================================

@bot.tree.command(
    name="leaderboard",
    description="Show the donation leaderboard"
)
@app_commands.describe(
    guild="Choose a guild",
    period="Choose a time period",
)
@app_commands.choices(
    guild=GUILD_CHOICES,
    period=PERIOD_CHOICES,
)
async def leaderboard(
    interaction: discord.Interaction,
    guild: app_commands.Choice[str],
    period: app_commands.Choice[str],
):
    data = get_leaderboard_data(
        guild.value,
        period.value,
    )

    await interaction.response.send_message(
        view=leaderboard_view(
            guild.value,
            data,
            period.value,
        )
    )


# =========================================================
# /COVERAGE
# =========================================================

@bot.tree.command(
    name="coverage",
    description="Check one Roblox IGN's payment coverage"
)
@app_commands.describe(
    guild="Choose a guild",
    ign="Roblox IGN",
)
@app_commands.choices(
    guild=GUILD_CHOICES
)
async def coverage(
    interaction: discord.Interaction,
    guild: app_commands.Choice[str],
    ign: str,
):
    guild_name = guild.value
    ign_key = normalize_name(ign)

    cursor.execute("""
    SELECT display_ign
    FROM donation_credit
    WHERE guild=? AND ign_key=?
    """, (
        guild_name,
        ign_key,
    ))

    row = cursor.fetchone()

    if not row:
        await interaction.response.send_message(
            f"❌ No donation history found for **{ign}**.",
            ephemeral=True,
        )
        return

    display_ign = row[0]
    balance = get_credit_balance(
        guild_name,
        ign_key,
    )

    through = get_covered_through(
        guild_name,
        ign_key,
    )

    streak_count = get_streak(
        guild_name,
        ign_key,
    )

    if through:
        pretty = datetime.strptime(
            through,
            "%Y-%m-%d"
        ).strftime("%d %b %Y")

        coverage_text = (
            f"✅ Paid through **{pretty}**"
        )
    else:
        coverage_text = (
            "❌ Not covered today"
        )

    body = (
        f"### 🎮 IGN\n**{display_ign}**\n"
        f"### 📅 Coverage\n{coverage_text}\n"
        f"### 💳 Remaining Credit\n"
        f"**{format_amount(balance)}**\n"
        f"### 🔥 Current Streak\n"
        f"**{streak_count} day(s)**\n\n"
        f"-# Daily reset: 12:00 AM Philippines Time"
    )

    await interaction.response.send_message(
        view=simple_info_view(
            "📅 Player Coverage",
            body,
            discord.Colour.green()
            if through
            else discord.Colour.red(),
        )
    )


# =========================================================
# /STREAK
# =========================================================

@bot.tree.command(
    name="streak",
    description="Check one Roblox IGN's donation streak"
)
@app_commands.describe(
    guild="Choose a guild",
    ign="Roblox IGN",
)
@app_commands.choices(
    guild=GUILD_CHOICES
)
async def streak(
    interaction: discord.Interaction,
    guild: app_commands.Choice[str],
    ign: str,
):
    ign_key = normalize_name(ign)
    streak_count = get_streak(
        guild.value,
        ign_key,
    )

    body = (
        f"🔥 **{ign}** currently has a "
        f"**{streak_count}-day covered streak**."
    )

    await interaction.response.send_message(
        view=simple_info_view(
            f"🔥 {guild.value} Donation Streak",
            body,
            discord.Colour.orange(),
        )
    )


# =========================================================
# /HISTORY
# =========================================================

@bot.tree.command(
    name="history",
    description="Show recent donations for one Roblox IGN"
)
@app_commands.describe(
    guild="Choose a guild",
    ign="Roblox IGN",
    limit="How many logs to show (1-20)",
)
@app_commands.choices(
    guild=GUILD_CHOICES
)
async def history(
    interaction: discord.Interaction,
    guild: app_commands.Choice[str],
    ign: str,
    limit: app_commands.Range[int, 1, 20] = 10,
):
    guild_name = guild.value
    wanted_key = normalize_name(ign)

    cursor.execute("""
    SELECT
        ign,
        donation,
        day,
        time,
        message_id,
        channel_id
    FROM donations
    WHERE guild=?
    ORDER BY day DESC, id DESC
    """, (
        guild_name,
    ))

    matching = [
        row
        for row in cursor.fetchall()
        if normalize_name(row[0])
        == wanted_key
    ][:limit]

    if not matching:
        await interaction.response.send_message(
            f"❌ No history found for **{ign}**.",
            ephemeral=True,
        )
        return

    lines = []

    for (
        row_ign,
        amount,
        donation_day,
        timestamp,
        message_id,
        channel_id,
    ) in matching:

        try:
            ts = int(timestamp)
            time_text = f"<t:{ts}:d>"
        except Exception:
            time_text = donation_day

        line = (
            f"💰 **{format_amount(amount)}** "
            f"(`{amount:,}`) • {time_text}"
        )

        if (
            message_id
            and channel_id
            and interaction.guild
        ):
            line += (
                f" • [Log]"
                f"(https://discord.com/channels/"
                f"{interaction.guild.id}/"
                f"{channel_id}/"
                f"{message_id})"
            )

        lines.append(line)

    await interaction.response.send_message(
        view=simple_info_view(
            f"📜 {guild_name} • {ign} History",
            "\n".join(lines),
            discord.Colour.blurple(),
        )
    )


# =========================================================
# /EDITDONATION
# =========================================================

@bot.tree.command(
    name="editdonation",
    description="Correct a donation amount using the original Discord message ID"
)
@app_commands.describe(
    message_id="Original donation message ID",
    new_amount="New amount, e.g. 200K",
)
async def editdonation(
    interaction: discord.Interaction,
    message_id: str,
    new_amount: str,
):
    if not can_manage_roblox(interaction.user):
        await interaction.response.send_message(
            "❌ You need **Leader**, **Co-Leader**, or **Manage Server**.",
            ephemeral=True,
        )
        return

    amount = convert_amount(new_amount)

    if amount <= 0:
        await interaction.response.send_message(
            "❌ Invalid amount.",
            ephemeral=True,
        )
        return

    cursor.execute("""
    SELECT id, guild, ign, donation
    FROM donations
    WHERE message_id=?
    """, (
        message_id,
    ))

    row = cursor.fetchone()

    if not row:
        await interaction.response.send_message(
            "❌ Donation not found.",
            ephemeral=True,
        )
        return

    donation_id, guild_name, ign, old_amount = row

    cursor.execute("""
    UPDATE donations
    SET donation=?
    WHERE id=?
    """, (
        amount,
        donation_id,
    ))

    db.commit()

    rebuild_player_credit(
        guild_name,
        ign,
    )

    body = (
        f"👤 **{ign}**\n"
        f"🏰 **{guild_name}**\n"
        f"Old: ~~{format_amount(old_amount)}~~\n"
        f"New: **{format_amount(amount)}**\n\n"
        f"✅ Coverage was recalculated."
    )

    await interaction.response.send_message(
        view=simple_info_view(
            "✏️ Donation Updated",
            body,
            discord.Colour.orange(),
        ),
        ephemeral=True,
    )


# =========================================================
# /REMOVEDONATION
# =========================================================

@bot.tree.command(
    name="removedonation",
    description="Remove a donation using the original Discord message ID"
)
@app_commands.describe(
    message_id="Original donation message ID"
)
async def removedonation(
    interaction: discord.Interaction,
    message_id: str,
):
    if not can_manage_roblox(interaction.user):
        await interaction.response.send_message(
            "❌ You need **Leader**, **Co-Leader**, or **Manage Server**.",
            ephemeral=True,
        )
        return

    cursor.execute("""
    SELECT id, guild, ign, donation
    FROM donations
    WHERE message_id=?
    """, (
        message_id,
    ))

    row = cursor.fetchone()

    if not row:
        await interaction.response.send_message(
            "❌ Donation not found.",
            ephemeral=True,
        )
        return

    donation_id, guild_name, ign, amount = row

    cursor.execute("""
    DELETE FROM credit_processed
    WHERE donation_id=?
    """, (
        donation_id,
    ))

    cursor.execute("""
    DELETE FROM donations
    WHERE id=?
    """, (
        donation_id,
    ))

    db.commit()

    rebuild_player_credit(
        guild_name,
        ign,
    )

    body = (
        f"🗑️ Removed **{format_amount(amount)}** "
        f"from **{ign}** in **{guild_name}**.\n\n"
        f"✅ Coverage was recalculated."
    )

    await interaction.response.send_message(
        view=simple_info_view(
            "🗑️ Donation Removed",
            body,
            discord.Colour.red(),
        ),
        ephemeral=True,
    )


# =========================================================
# /GUILDSETTINGS
# =========================================================

@bot.tree.command(
    name="guildsettings",
    description="View or change reminder/report settings for a guild"
)
@app_commands.describe(
    guild="Choose a guild",
    daily_requirement_value="Optional new requirement, e.g. 100K",
    reminder="Enable/disable automatic reminder",
    daily_report="Enable/disable automatic daily report",
    dm_reminder="Enable/disable DM reminders to missing members",
    report_channel="Where reminders/reports are posted",
)
@app_commands.choices(
    guild=GUILD_CHOICES
)
async def guildsettings(
    interaction: discord.Interaction,
    guild: app_commands.Choice[str],
    daily_requirement_value: str | None = None,
    reminder: bool | None = None,
    daily_report: bool | None = None,
    dm_reminder: bool | None = None,
    report_channel: discord.TextChannel | None = None,
):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(
            "❌ You need **Manage Server**.",
            ephemeral=True,
        )
        return

    guild_name = guild.value
    current = get_guild_setting(
        guild_name
    )

    requirement = current[
        "daily_requirement"
    ]

    if daily_requirement_value is not None:
        parsed = convert_amount(
            daily_requirement_value
        )

        if parsed <= 0:
            await interaction.response.send_message(
                "❌ Invalid daily requirement.",
                ephemeral=True,
            )
            return

        requirement = parsed

    reminder_value = (
        int(reminder)
        if reminder is not None
        else int(current["reminder_enabled"])
    )

    report_value = (
        int(daily_report)
        if daily_report is not None
        else int(current["daily_report_enabled"])
    )

    dm_reminder_value = (
        int(dm_reminder)
        if dm_reminder is not None
        else int(current.get("dm_reminder_enabled", False))
    )

    channel_id = (
        str(report_channel.id)
        if report_channel
        else current["report_channel_id"]
    )

    cursor.execute("""
    UPDATE guild_settings
    SET
        daily_requirement=?,
        reminder_enabled=?,
        daily_report_enabled=?,
        dm_reminder_enabled=?,
        report_channel_id=?
    WHERE guild=?
    """, (
        requirement,
        reminder_value,
        report_value,
        dm_reminder_value,
        channel_id,
        guild_name,
    ))

    db.commit()

    updated = get_guild_setting(
        guild_name
    )

    body = (
        f"### 💰 Daily Requirement\n"
        f"**{format_amount(updated['daily_requirement'])}**\n"
        f"### ⏰ Reminder\n"
        f"**{'ON' if updated['reminder_enabled'] else 'OFF'}** "
        f"• 8:00 PM PH\n"
        f"### 📋 Daily Report\n"
        f"**{'ON' if updated['daily_report_enabled'] else 'OFF'}** "
        f"• 12:05 AM PH\n"
        f"### 💌 DM Reminder\n"
        f"**{'ON' if updated.get('dm_reminder_enabled', False) else 'OFF'}** "
        f"• 8:00 PM PH\n"
        f"### 📢 Report Channel\n"
        f"<#{updated['report_channel_id']}>\n\n"
        f"-# Changing the daily requirement affects how future/rebuilt coverage is calculated."
    )

    await interaction.response.send_message(
        view=simple_info_view(
            f"⚙️ {guild_name} Settings",
            body,
            discord.Colour.blurple(),
        ),
        ephemeral=True,
    )


# =========================================================
# OLD LOG SYNC
# =========================================================

async def fetch_channel_history(
    channel,
    after=None,
    attempts=3,
):
    last_error = None

    for attempt in range(
        1,
        attempts + 1
    ):
        try:
            messages = []

            async for message in channel.history(
                limit=None,
                oldest_first=True,
                after=after,
            ):
                messages.append(message)

            return messages

        except Exception as exc:
            last_error = exc
            print(
                f"History attempt {attempt} "
                f"failed: {repr(exc)}"
            )

            if attempt < attempts:
                await asyncio.sleep(3)

    raise last_error


@bot.tree.command(
    name="syncoldlogs",
    description="Import old donation logs safely"
)
@app_commands.describe(
    guild="One guild or all guilds",
    days="0 = all available history",
)
@app_commands.choices(
    guild=SYNC_GUILD_CHOICES
)
async def syncoldlogs(
    interaction: discord.Interaction,
    guild: app_commands.Choice[str],
    days: int = 0,
):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(
            "❌ You need **Manage Server**.",
            ephemeral=True,
        )
        return

    if days < 0:
        await interaction.response.send_message(
            "❌ Days cannot be negative.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(
        thinking=True,
        ephemeral=True,
    )

    if guild.value == "ALL":
        channels_to_scan = list(
            GUILD_CHANNELS.items()
        )
    else:
        channels_to_scan = [
            (channel_id, guild_name)
            for channel_id, guild_name
            in GUILD_CHANNELS.items()
            if guild_name == guild.value
        ]

    after = (
        utc_now() - timedelta(days=days)
        if days > 0
        else None
    )

    results = []
    totals = {
        "scanned": 0,
        "valid": 0,
        "imported": 0,
        "duplicate": 0,
        "linked": 0,
        "errors": 0,
    }

    for channel_id, guild_name in channels_to_scan:
        stats = {
            "scanned": 0,
            "valid": 0,
            "imported": 0,
            "duplicate": 0,
            "linked": 0,
            "errors": 0,
        }

        channel = bot.get_channel(
            channel_id
        )

        if channel is None:
            try:
                channel = await bot.fetch_channel(
                    channel_id
                )
            except Exception:
                stats["errors"] += 1
                results.append(
                    (guild_name, stats)
                )
                continue

        try:
            messages = await fetch_channel_history(
                channel,
                after=after,
            )
        except Exception:
            stats["errors"] += 1
            results.append(
                (guild_name, stats)
            )
            continue

        for message in messages:
            stats["scanned"] += 1

            # Keep Discord heartbeats/interactions responsive
            # while scanning large channel histories.
            if stats["scanned"] % 25 == 0:
                await asyncio.sleep(0)

            if not parse_donation_message(
                message.content
            ):
                continue

            stats["valid"] += 1

            try:
                result = await process_donation_message(
                    message,
                    imported=True,
                )

                if result == "imported":
                    stats["imported"] += 1
                elif result == "duplicate":
                    stats["duplicate"] += 1
                elif result == "linked":
                    stats["linked"] += 1

            except Exception as exc:
                stats["errors"] += 1
                print(
                    f"SYNC ERROR {message.id}: "
                    f"{repr(exc)}"
                )

        results.append(
            (guild_name, stats)
        )

        for key in totals:
            totals[key] += stats[key]

    guild_lines = []

    for guild_name, stats in results:
        guild_lines.append(
            f"**{guild_name}** — "
            f"{stats['valid']} valid • "
            f"{stats['imported']} new • "
            f"{stats['duplicate']} tracked • "
            f"{stats['linked']} linked • "
            f"{stats['errors']} errors"
        )

    body = (
        f"### 🔎 Scanned\n**{totals['scanned']:,}**\n"
        f"### 💰 Valid Logs\n**{totals['valid']:,}**\n"
        f"### 📥 Imported\n**{totals['imported']:,}**\n"
        f"### ⏭️ Already Tracked\n**{totals['duplicate']:,}**\n"
        f"### 🔗 Existing DB Linked\n**{totals['linked']:,}**\n"
        f"### ⚠️ Errors\n**{totals['errors']:,}**\n\n"
        f"## 🏰 Guild Results\n"
        + "\n".join(guild_lines)
        + "\n\n-# Duplicate protection uses the original Discord message ID."
    )

    await interaction.followup.send(
        view=simple_info_view(
            "🔄 Historical Sync Complete",
            body,
            (
                discord.Colour.green()
                if totals["errors"] == 0
                else discord.Colour.orange()
            ),
        ),
        ephemeral=True,
    )



# =========================================================
# ROBLOX MEMBER COMMANDS
# Format: Discord User / Roblox IGN / Roblox Username
# =========================================================

@bot.tree.command(
    name="linkroblox",
    description="Save Discord User / Roblox IGN / Roblox Username"
)
@app_commands.describe(
    guild="Choose a guild",
    roblox_ign="The IGN used in donation logs",
    roblox_username="The actual Roblox account username",
    member=(
        "Leave blank to link yourself. "
        "Leader/Co-Leader/Admin can choose another member."
    ),
)
@app_commands.choices(
    guild=GUILD_CHOICES
)
async def linkroblox(
    interaction: discord.Interaction,
    guild: app_commands.Choice[str],
    roblox_ign: str,
    roblox_username: str,
    member: discord.Member | None = None,
):
    guild_name = guild.value

    target = (
        member
        if member is not None
        else interaction.user
    )

    # Anyone may add/update themselves.
    # Another member requires Leader, Co-Leader or Manage Server.
    if (
        target.id != interaction.user.id
        and not can_manage_roblox(
            interaction.user
        )
    ):
        await interaction.response.send_message(
            "❌ Only **Leader**, **Co-Leader**, or "
            "**Manage Server** can edit another member.",
            ephemeral=True,
        )
        return

    success, error = upsert_roblox_member(
        guild_name,
        target.id,
        roblox_ign,
        roblox_username,
        interaction.user.id,
    )

    if not success:
        await interaction.response.send_message(
            f"❌ {error}",
            ephemeral=True,
        )
        return

    body = (
        f"### 👤 Discord User\n"
        f"{target.mention}\n"
        f"### 🎮 Roblox IGN\n"
        f"**{roblox_ign}**\n"
        f"### 🔎 Roblox Username\n"
        f"**{roblox_username}**\n"
        f"### 🛡️ Guild\n"
        f"**{guild_name}**\n\n"
        f"✅ Donation logs will match using the **Roblox IGN**."
    )

    await interaction.response.send_message(
        view=simple_info_view(
            "🔗 Roblox Member Saved",
            body,
            discord.Colour.green(),
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="myroblox",
    description="Check your saved Roblox IGN and Roblox username"
)
@app_commands.describe(
    guild="Choose a guild"
)
@app_commands.choices(
    guild=GUILD_CHOICES
)
async def myroblox(
    interaction: discord.Interaction,
    guild: app_commands.Choice[str],
):
    saved = get_roblox_member_by_discord(
        guild.value,
        interaction.user.id,
    )

    if not saved:
        await interaction.response.send_message(
            view=simple_info_view(
                "🎮 My Roblox Information",
                (
                    f"No Roblox information is saved for "
                    f"**{guild.value}**.\n\n"
                    f"Use `/linkroblox`."
                ),
                discord.Colour.orange(),
            ),
            ephemeral=True,
        )
        return

    ign_key, roblox_ign, roblox_username, active = saved

    await interaction.response.send_message(
        view=simple_info_view(
            "🎮 My Roblox Information",
            (
                f"### 🛡️ Guild\n**{guild.value}**\n"
                f"### 🎮 Roblox IGN\n**{roblox_ign}**\n"
                f"### 🔎 Roblox Username\n**{roblox_username}**\n"
                f"### 📌 Status\n**{'Active' if active else 'Inactive'}**"
            ),
            discord.Colour.green(),
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="unlinkroblox",
    description="Remove saved Roblox information"
)
@app_commands.describe(
    guild="Choose a guild",
    member=(
        "Leave blank to remove yourself. "
        "Leader/Co-Leader/Admin can choose another member."
    ),
)
@app_commands.choices(
    guild=GUILD_CHOICES
)
async def unlinkroblox(
    interaction: discord.Interaction,
    guild: app_commands.Choice[str],
    member: discord.Member | None = None,
):
    target = (
        member
        if member is not None
        else interaction.user
    )

    if (
        target.id != interaction.user.id
        and not can_manage_roblox(
            interaction.user
        )
    ):
        await interaction.response.send_message(
            "❌ Only **Leader**, **Co-Leader**, or "
            "**Manage Server** can remove another member.",
            ephemeral=True,
        )
        return

    saved = get_roblox_member_by_discord(
        guild.value,
        target.id,
    )

    if not saved:
        await interaction.response.send_message(
            "❌ No Roblox information is saved for that member.",
            ephemeral=True,
        )
        return

    remove_roblox_member(
        guild.value,
        target.id,
    )

    await interaction.response.send_message(
        view=simple_info_view(
            "🔓 Roblox Information Removed",
            (
                f"Removed the Roblox mapping for "
                f"{target.mention} in **{guild.value}**.\n\n"
                f"-# Existing donation history was not deleted."
            ),
            discord.Colour.orange(),
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="addroblox",
    description="Leader/Co-Leader: add a guild member's Roblox details"
)
@app_commands.describe(
    guild="Choose a guild",
    member="Discord user",
    roblox_ign="IGN used in donation logs",
    roblox_username="Actual Roblox account username",
)
@app_commands.choices(
    guild=GUILD_CHOICES
)
async def addroblox(
    interaction: discord.Interaction,
    guild: app_commands.Choice[str],
    member: discord.Member,
    roblox_ign: str,
    roblox_username: str,
):
    if not can_manage_roblox(
        interaction.user
    ):
        await interaction.response.send_message(
            "❌ This command is for **Leader**, **Co-Leader**, "
            "or **Manage Server**.",
            ephemeral=True,
        )
        return

    success, error = upsert_roblox_member(
        guild.value,
        member.id,
        roblox_ign,
        roblox_username,
        interaction.user.id,
    )

    if not success:
        await interaction.response.send_message(
            f"❌ {error}",
            ephemeral=True,
        )
        return

    body = (
        f"### 👤 Discord User\n"
        f"{member.mention}\n"
        f"### 🎮 Roblox IGN\n"
        f"**{roblox_ign}**\n"
        f"### 🔎 Roblox Username\n"
        f"**{roblox_username}**\n"
        f"### 🛡️ Guild\n"
        f"**{guild.value}**\n\n"
        f"✅ The bot will use **{roblox_ign}** to match "
        f"their donation logs."
    )

    await interaction.response.send_message(
        view=simple_info_view(
            "➕ Roblox Member Added",
            body,
            discord.Colour.green(),
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="removeroblox",
    description="Leader/Co-Leader: remove a guild member's Roblox mapping"
)
@app_commands.describe(
    guild="Choose a guild",
    member="Discord user",
)
@app_commands.choices(
    guild=GUILD_CHOICES
)
async def removeroblox(
    interaction: discord.Interaction,
    guild: app_commands.Choice[str],
    member: discord.Member,
):
    if not can_manage_roblox(
        interaction.user
    ):
        await interaction.response.send_message(
            "❌ This command is for **Leader**, **Co-Leader**, "
            "or **Manage Server**.",
            ephemeral=True,
        )
        return

    saved = get_roblox_member_by_discord(
        guild.value,
        member.id,
    )

    if not saved:
        await interaction.response.send_message(
            "❌ That member is not in the saved Roblox roster.",
            ephemeral=True,
        )
        return

    remove_roblox_member(
        guild.value,
        member.id,
    )

    await interaction.response.send_message(
        view=simple_info_view(
            "➖ Roblox Member Removed",
            (
                f"{member.mention} was removed from **current daily tracking** "
                f"for **{guild.value}**.\n\n"
                f"✅ Old donations, lifetime totals, leaderboard totals, "
                f"and history were preserved."
            ),
            discord.Colour.red(),
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="robloxroster",
    description="Show Discord User / Roblox IGN / Roblox Username"
)
@app_commands.describe(
    guild="Choose a guild"
)
@app_commands.choices(
    guild=GUILD_CHOICES
)
async def robloxroster(
    interaction: discord.Interaction,
    guild: app_commands.Choice[str],
):
    roster = get_roblox_roster(
        guild.value
    )

    if not roster:
        body = (
            "No Roblox members have been saved "
            "for this guild yet."
        )
    else:
        lines = []

        for (
            discord_user_id,
            roblox_ign,
            roblox_username,
            ign_key,
            active,
        ) in roster[:60]:

            status_icon = "🟢" if active else "⚫"
            status_text = "Active" if active else "Inactive"

            lines.append(
                f"{status_icon} 👤 <@{discord_user_id}>\n"
                f"└ 🎮 IGN: **{roblox_ign}**\n"
                f"└ 🔎 User: **{roblox_username}**\n"
                f"└ 📌 Status: **{status_text}**"
            )

        if len(roster) > 60:
            lines.append(
                f"-# +{len(roster) - 60} more members"
            )

        body = (
            f"**{len(roster)} saved member(s)**\n\n"
            + "\n\n".join(lines)
        )

    await interaction.response.send_message(
        view=simple_info_view(
            f"🎮 {guild.value} Roblox Roster",
            body,
            discord.Colour.blurple(),
        )
    )



# =========================================================
# /CLEANJUNKLOGS
# Removes malformed old imported rows such as field labels
# accidentally saved as Roblox IGNs.
# =========================================================

@bot.tree.command(
    name="cleanjunklogs",
    description="Remove malformed old donation rows from the database"
)
async def cleanjunklogs(
    interaction: discord.Interaction,
):
    if not can_manage_roblox(interaction.user):
        await interaction.response.send_message(
            "❌ This command is for **Leader**, **Co-Leader**, "
            "or someone with **Manage Server**.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(
        thinking=True,
        ephemeral=True,
    )

    # These are field labels that should never be player IGNs.
    bad_keys = {
        "ign",
        "previousguildgold",
        "currentguildgold",
        "dailydonation",
    }

    removed_donations = 0
    removed_accounts = 0
    removed_coverage = 0

    # Remove malformed donation rows.
    cursor.execute("""
    SELECT id, ign
    FROM donations
    ORDER BY id ASC
    """)

    for donation_id, ign in cursor.fetchall():
        if normalize_name(ign) in bad_keys:
            cursor.execute(
                "DELETE FROM credit_processed WHERE donation_id=?",
                (donation_id,)
            )
            cursor.execute(
                "DELETE FROM donations WHERE id=?",
                (donation_id,)
            )
            removed_donations += 1

    # Remove malformed credit accounts.
    cursor.execute("""
    SELECT guild, ign_key
    FROM donation_credit
    """)

    for guild_name, ign_key in cursor.fetchall():
        if normalize_name(ign_key) in bad_keys:
            cursor.execute("""
            DELETE FROM donation_credit
            WHERE guild=? AND ign_key=?
            """, (
                guild_name,
                ign_key,
            ))
            removed_accounts += 1

    # Remove malformed coverage accounts.
    cursor.execute("""
    SELECT guild, ign_key, covered_day
    FROM donation_coverage
    """)

    for guild_name, ign_key, covered_day in cursor.fetchall():
        if normalize_name(ign_key) in bad_keys:
            cursor.execute("""
            DELETE FROM donation_coverage
            WHERE guild=? AND ign_key=? AND covered_day=?
            """, (
                guild_name,
                ign_key,
                covered_day,
            ))
            removed_coverage += 1

    db.commit()

    body = (
        f"### 🧹 Cleanup Complete\n"
        f"**Donation rows removed:** {removed_donations}\n"
        f"**Junk credit accounts removed:** {removed_accounts}\n"
        f"**Junk coverage rows removed:** {removed_coverage}\n\n"
        f"-# Normal player donation data was left alone."
    )

    await interaction.followup.send(
        view=simple_info_view(
            "🧹 Junk Logs Cleaned",
            body,
            discord.Colour.green(),
        ),
        ephemeral=True,
    )



# =========================================================
# MESSAGE-ID DONATION TOOLS
# =========================================================

@bot.tree.command(
    name="checkmessage",
    description="Check whether a Discord donation message is already logged"
)
@app_commands.describe(
    message_id="Discord message ID to check"
)
async def checkmessage(
    interaction: discord.Interaction,
    message_id: str,
):
    message_id = message_id.strip()

    if not message_id.isdigit():
        await interaction.response.send_message(
            "❌ Please enter a valid Discord message ID.",
            ephemeral=True,
        )
        return

    cursor.execute("""
    SELECT
        id,
        guild,
        ign,
        donation,
        day,
        channel_id
    FROM donations
    WHERE message_id=?
    ORDER BY id DESC
    LIMIT 1
    """, (
        message_id,
    ))

    row = cursor.fetchone()

    if not row:
        await interaction.response.send_message(
            view=simple_info_view(
                "🔎 Donation Message Check",
                (
                    f"**Message ID:** `{message_id}`\n"
                    f"**Status:** ❌ Not Logged\n\n"
                    f"Use `/rescanmessage` if this is a donation "
                    f"message that should have been recorded."
                ),
                discord.Colour.orange(),
            ),
            ephemeral=True,
        )
        return

    (
        donation_id,
        guild_name,
        ign,
        donation,
        donation_day,
        channel_id,
    ) = row

    await interaction.response.send_message(
        view=simple_info_view(
            "🔎 Donation Message Check",
            (
                f"**Message ID:** `{message_id}`\n"
                f"**Status:** ✅ Logged\n\n"
                f"**Guild:** {guild_name}\n"
                f"**IGN:** {ign}\n"
                f"**Donation:** {format_amount(donation)}\n"
                f"**Date:** {donation_day}\n"
                f"**Database ID:** #{donation_id}\n"
                f"**Channel ID:** `{channel_id}`"
            ),
            discord.Colour.green(),
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="rescanmessage",
    description="Find one Discord message by ID and try to import its donation"
)
@app_commands.describe(
    message_id="Discord message ID to rescan"
)
async def rescanmessage(
    interaction: discord.Interaction,
    message_id: str,
):
    message_id = message_id.strip()

    if not message_id.isdigit():
        await interaction.response.send_message(
            "❌ Please enter a valid Discord message ID.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(
        thinking=True,
        ephemeral=True,
    )

    # Never duplicate a message that is already saved.
    if message_already_logged(
        message_id
    ):
        await interaction.followup.send(
            view=simple_info_view(
                "🔁 Message Rescan",
                (
                    f"**Message ID:** `{message_id}`\n"
                    f"**Status:** ✅ Already Logged\n\n"
                    f"No duplicate donation was created."
                ),
                discord.Colour.green(),
            ),
            ephemeral=True,
        )
        return

    target_message = None

    # Search only configured donation channels.
    for channel_id in GUILD_CHANNELS:
        channel = bot.get_channel(
            channel_id
        )

        if channel is None:
            try:
                channel = await bot.fetch_channel(
                    channel_id
                )
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ):
                continue

        try:
            target_message = await channel.fetch_message(
                int(message_id)
            )
            break

        except discord.NotFound:
            continue

        except (
            discord.Forbidden,
            discord.HTTPException,
        ):
            continue

    if target_message is None:
        await interaction.followup.send(
            view=simple_info_view(
                "🔁 Message Rescan",
                (
                    f"**Message ID:** `{message_id}`\n"
                    f"**Status:** ❌ Message Not Found\n\n"
                    f"The bot couldn't find that message in any "
                    f"configured donation channel."
                ),
                discord.Colour.red(),
            ),
            ephemeral=True,
        )
        return

    result = await process_donation_message(
        target_message,
        imported=True,
    )

    if result in (
        "saved",
        "linked",
        "duplicate",
    ):
        status_text = {
            "saved": "✅ Imported",
            "linked": "✅ Linked to Existing Donation",
            "duplicate": "✅ Already Logged",
        }.get(
            result,
            "✅ Processed",
        )

        await interaction.followup.send(
            view=simple_info_view(
                "🔁 Message Rescan",
                (
                    f"**Message ID:** `{message_id}`\n"
                    f"**Status:** {status_text}\n\n"
                    f"The message was processed without creating "
                    f"a duplicate donation."
                ),
                discord.Colour.green(),
            ),
            ephemeral=True,
        )
        return

    parsed = parse_donation_message(
        get_message_donation_text(
            target_message
        )
    )

    if parsed is None:
        extracted = get_message_donation_text(
            target_message
        )

        preview = extracted[:1200]

        if not preview:
            preview = "(No readable message/embed text found.)"

        details = (
            "The message was found, but the parser still "
            "couldn't safely identify both an IGN and a "
            "donation amount.\n\n"
            "**What the bot actually read:**\n"
            f"```{preview}```"
        )
    else:
        details = (
            f"Parser found **{parsed['ign']}** donating "
            f"**{format_amount(parsed['donation_amount'])}**, "
            f"but the message still wasn't imported."
        )

    await interaction.followup.send(
        view=simple_info_view(
            "🔁 Message Rescan",
            (
                f"**Message ID:** `{message_id}`\n"
                f"**Status:** ⚠️ Not Imported\n\n"
                f"{details}"
            ),
            discord.Colour.orange(),
        ),
        ephemeral=True,
    )


# =========================================================
# /FIXCOVERAGE
# =========================================================

@bot.tree.command(
    name="fixcoverage",
    description="Repair impossible advance-payment coverage dates"
)
async def fixcoverage(interaction: discord.Interaction):

    if not can_manage_roblox(interaction.user):
        await interaction.response.send_message(
            "❌ Leader, Co-Leader, or Manage Server required.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(
        thinking=True,
        ephemeral=True,
    )

    try:
        async with db_write_lock:
            rebuild_all_coverage_safely()

        await interaction.followup.send(
            view=simple_info_view(
                "🛠️ Coverage Repair Complete",
                (
                    "Coverage was rebuilt from the saved donation logs.\n\n"
                    f"Maximum advance coverage: **{MAX_ADVANCE_DAYS} days**\n"
                    "✅ Impossible coverage chains were removed."
                ),
                discord.Colour.green(),
            ),
            ephemeral=True,
        )

    except Exception as exc:
        print(f"FIXCOVERAGE ERROR: {repr(exc)}")
        await interaction.followup.send(
            "❌ Coverage repair failed. Check Railway logs.",
            ephemeral=True,
        )


# =========================================================
# DM REMINDERS
# =========================================================

async def send_missing_dm_reminders(
    guild_name,
    missing_members,
    reminder_day,
):
    sent = 0
    failed = 0

    for member in missing_members:
        run_key = (
            f"dmreminder:{guild_name}:"
            f"{reminder_day}:{member.id}"
        )

        if automation_done(run_key):
            continue

        try:
            await member.send(
                f"💰 **{guild_name} Donation Reminder**\n\n"
                f"You are still missing today's "
                f"**{format_amount(daily_requirement(guild_name))}** "
                f"guild donation.\n"
                f"Please donate before the **12:00 AM Philippines time reset**.\n\n"
                f"If you already paid in advance and think this is wrong, "
                f"contact a Leader or Co-Leader."
            )
            sent += 1

        except (discord.Forbidden, discord.HTTPException):
            failed += 1

        mark_automation_done(run_key)
        await asyncio.sleep(0.25)

    return sent, failed



# =========================================================
# /REACTIVATEPLAYER
# =========================================================

@bot.tree.command(
    name="reactivateplayer",
    description="Put an inactive Roblox member back into daily tracking"
)
@app_commands.describe(
    guild="Choose a guild",
    member="Discord member to reactivate",
)
@app_commands.choices(
    guild=GUILD_CHOICES
)
async def reactivateplayer(
    interaction: discord.Interaction,
    guild: app_commands.Choice[str],
    member: discord.Member,
):
    if not can_manage_roblox(
        interaction.user
    ):
        await interaction.response.send_message(
            "❌ Leader, Co-Leader, or Manage Server required.",
            ephemeral=True,
        )
        return

    saved = get_roblox_member_by_discord(
        guild.value,
        member.id,
    )

    if not saved:
        await interaction.response.send_message(
            "❌ That member has no saved Roblox roster entry.",
            ephemeral=True,
        )
        return

    reactivate_roblox_member(
        guild.value,
        member.id,
    )

    await interaction.response.send_message(
        view=simple_info_view(
            "✅ Player Reactivated",
            (
                f"{member.mention} is active again in "
                f"**{guild.value}** daily tracking.\\n\\n"
                f"Their existing donation history was kept."
            ),
            discord.Colour.green(),
        ),
        ephemeral=True,
    )



# =========================================================
# /SYNCPLAYERS
# Reconcile saved roster with the current Discord guild role.
# Does NOT delete donation history.
# =========================================================

@bot.tree.command(
    name="syncplayers",
    description="Update active players from the current Discord guild role"
)
@app_commands.describe(
    guild="Choose a guild"
)
@app_commands.choices(
    guild=GUILD_CHOICES
)
async def syncplayers(
    interaction: discord.Interaction,
    guild: app_commands.Choice[str],
):
    if not can_manage_roblox(
        interaction.user
    ):
        await interaction.response.send_message(
            "❌ Leader, Co-Leader, or Manage Server required.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(
        thinking=True,
        ephemeral=True,
    )

    server = interaction.guild

    if server is None:
        return

    guild_name = guild.value
    role_id = GUILD_ROLES.get(
        guild_name
    )

    role = server.get_role(
        role_id
    )

    if role is None:
        await interaction.followup.send(
            "❌ Guild role not found.",
            ephemeral=True,
        )
        return

    await ensure_members(
        server
    )

    role_member_ids = {
        member.id
        for member in role.members
        if not member.bot
    }

    cursor.execute("""
    SELECT
        discord_user_id,
        roblox_ign,
        active
    FROM roblox_members
    WHERE guild=?
    """, (
        guild_name,
    ))

    rows = cursor.fetchall()

    deactivated = 0
    reactivated = 0

    for (
        discord_user_id,
        roblox_ign,
        active,
    ) in rows:

        user_id = int(
            discord_user_id
        )

        should_be_active = (
            user_id in role_member_ids
        )

        if should_be_active and not active:
            reactivate_roblox_member(
                guild_name,
                user_id,
            )
            reactivated += 1

        elif (
            not should_be_active
            and active
        ):
            remove_roblox_member(
                guild_name,
                user_id,
            )
            deactivated += 1

    await interaction.followup.send(
        view=simple_info_view(
            "🔄 Player Roster Updated",
            (
                f"**Guild:** {guild_name}\n"
                f"**Removed from daily tracking:** {deactivated}\n"
                f"**Reactivated:** {reactivated}\n\n"
                f"✅ Old donation history and lifetime totals were preserved."
            ),
            discord.Colour.green(),
        ),
        ephemeral=True,
    )


# =========================================================
# AUTOMATIC REMINDER + DAILY REPORT
# =========================================================

def automation_done(run_key):
    cursor.execute("""
    SELECT 1
    FROM automation_runs
    WHERE run_key=?
    """, (
        run_key,
    ))

    return cursor.fetchone() is not None


def mark_automation_done(run_key):
    cursor.execute("""
    INSERT OR IGNORE INTO automation_runs
    (
        run_key,
        created_at
    )
    VALUES (?, ?)
    """, (
        run_key,
        utc_now().isoformat(),
    ))
    db.commit()


async def get_report_channel(
    guild_name
):
    setting = get_guild_setting(
        guild_name
    )

    channel_id = int(
        setting["report_channel_id"]
        or TRACKER_CHANNEL_ID
    )

    channel = bot.get_channel(
        channel_id
    )

    if channel is None:
        try:
            channel = await bot.fetch_channel(
                channel_id
            )
        except Exception:
            return None

    return channel


async def build_daily_status_for_day(
    guild_name,
    check_day
):
    server = bot.get_guild(
        SERVER_ID
    )

    if server is None:
        return None

    await ensure_members(server)

    role = server.get_role(
        GUILD_ROLES[guild_name]
    )

    if role is None:
        return None

    members = [
        m
        for m in role.members
        if not m.bot
    ]

    members = [
        member
        for member in members
        if not (
            (saved := get_roblox_member_by_discord(guild_name, member.id))
            and not saved[-1]
        )
    ]

    covered, missing_members, unlinked = (
        calculate_member_status(
            guild_name,
            members,
            check_day=check_day,
        )
    )

    return (
        members,
        covered,
        missing_members,
        unlinked,
    )


@tasks.loop(minutes=1)
async def automation_loop():
    now = ph_now()

    for guild_name in GUILD_ROLES:
        settings = get_guild_setting(
            guild_name
        )

        # -----------------------------------------
        # Reminder
        # -----------------------------------------
        if settings["reminder_enabled"]:
            if (
                now.hour
                == settings["reminder_hour"]
                and now.minute
                == settings["reminder_minute"]
            ):
                run_key = (
                    f"reminder:{guild_name}:"
                    f"{now.date().isoformat()}"
                )

                if not automation_done(run_key):
                    status = (
                        await build_daily_status_for_day(
                            guild_name,
                            now.date().isoformat(),
                        )
                    )

                    channel = await get_report_channel(
                        guild_name
                    )

                    if status and channel:
                        (
                            members,
                            covered,
                            missing_members,
                            unlinked,
                        ) = status

                        dm_sent = 0
                        dm_failed = 0

                        if settings.get("dm_reminder_enabled", False):
                            dm_sent, dm_failed = await send_missing_dm_reminders(
                                guild_name,
                                missing_members,
                                now.date().isoformat(),
                            )

                        if missing_members:
                            missing_text = "\n".join(
                                f"🔴 {m.mention}"
                                for m in missing_members[:50]
                            )
                        else:
                            missing_text = (
                                "🎉 Everyone is covered!"
                            )

                        body = (
                            f"### ⏰ Donation Reminder\n"
                            f"**{len(missing_members)}** "
                            f"member(s) are still missing today's "
                            f"{format_amount(daily_requirement(guild_name))}.\n\n"
                            f"{missing_text}\n\n"
                            f"💌 DM reminders sent: **{dm_sent}**"
                            f" • Failed/closed DMs: **{dm_failed}**\n\n"
                            f"-# Daily reset: 12:00 AM Philippines Time"
                        )

                        await channel.send(
                            view=simple_info_view(
                                f"⏰ {guild_name} Reminder",
                                body,
                                discord.Colour.orange(),
                            )
                        )

                    mark_automation_done(
                        run_key
                    )

        # -----------------------------------------
        # Daily report for yesterday
        # -----------------------------------------
        if settings["daily_report_enabled"]:
            if (
                now.hour
                == settings["report_hour"]
                and now.minute
                == settings["report_minute"]
            ):
                report_day = (
                    now.date()
                    - timedelta(days=1)
                ).isoformat()

                run_key = (
                    f"report:{guild_name}:"
                    f"{report_day}"
                )

                if not automation_done(run_key):
                    status = (
                        await build_daily_status_for_day(
                            guild_name,
                            report_day,
                        )
                    )

                    channel = await get_report_channel(
                        guild_name
                    )

                    if status and channel:
                        (
                            members,
                            covered,
                            missing_members,
                            unlinked,
                        ) = status

                        cursor.execute("""
                        SELECT COALESCE(SUM(donation), 0)
                        FROM donations
                        WHERE guild=? AND day=?
                        """, (
                            guild_name,
                            report_day,
                        ))

                        total = cursor.fetchone()[0]

                        body = (
                            f"### 📅 Date\n**{report_day}**\n"
                            f"### 👥 Members\n**{len(members)}**\n"
                            f"### ✅ Covered\n**{len(covered)}**\n"
                            f"### ❌ Missing\n**{len(missing_members)}**\n"
                            f"### 🎮 Unlinked\n**{len(unlinked)}**\n"
                            f"### 💰 Logged Donations\n"
                            f"**{format_amount(total)}** "
                            f"(`{total:,}`)"
                        )

                        await channel.send(
                            view=simple_info_view(
                                f"📋 {guild_name} Daily Report",
                                body,
                                discord.Colour.blurple(),
                            )
                        )

                    mark_automation_done(
                        run_key
                    )


@automation_loop.before_loop
async def before_automation_loop():
    await bot.wait_until_ready()


# =========================================================
# START
# =========================================================

if not TOKEN:
    raise RuntimeError(
        "TOKEN is missing from Railway variables."
    )


try:
    bot.run(TOKEN)
except Exception as exc:
    print("BOT CRASHED:")
    print(repr(exc))
