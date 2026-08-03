import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

import os
import sqlite3
import re
import asyncio

from datetime import datetime, timezone, date, timedelta


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

TOKEN = os.getenv("TOKEN")

SERVER_ID = 1529030570410119259

# 100K = 1 donation day
DAILY_REQUIREMENT = 100_000


# =========================================================
# GUILD DONATION CHANNELS
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
}


# =========================================================
# GUILD ROLE IDS
# =========================================================

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
}


# =========================================================
# TRACKER CHANNEL
# =========================================================

TRACKER_CHANNEL_ID = 1532339634829267149


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect("donations.db")

cursor = db.cursor()


cursor.execute("""
CREATE TABLE IF NOT EXISTS donations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild TEXT,
    ign TEXT,
    previous_gold TEXT,
    current_gold TEXT,
    donation INTEGER,
    logged_by TEXT,
    time TEXT,
    day TEXT
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
    PRIMARY KEY (
        guild,
        ign_key,
        covered_day
    )
)
""")


cursor.execute("""
CREATE TABLE IF NOT EXISTS credit_processed (
    donation_id INTEGER PRIMARY KEY
)
""")


db.commit()


# =========================================================
# DATABASE UPGRADES
# =========================================================

def column_exists(table, column):

    cursor.execute(
        f"PRAGMA table_info({table})"
    )

    columns = [
        row[1]
        for row in cursor.fetchall()
    ]

    return column in columns


# Add message_id to old databases
if not column_exists(
    "donations",
    "message_id"
):

    cursor.execute("""
    ALTER TABLE donations
    ADD COLUMN message_id TEXT
    """)


# Add channel_id
if not column_exists(
    "donations",
    "channel_id"
):

    cursor.execute("""
    ALTER TABLE donations
    ADD COLUMN channel_id TEXT
    """)


db.commit()


# Prevent the same Discord message
# from ever being imported twice.
cursor.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS
idx_donations_message_id
ON donations(message_id)
WHERE message_id IS NOT NULL
""")


db.commit()


# =========================================================
# TIME
# =========================================================

def get_now():

    return datetime.now(
        timezone.utc
    )


def get_today():

    return get_now().date().isoformat()


def get_timestamp():

    return int(
        get_now().timestamp()
    )


def discord_timestamp(
    timestamp
):

    return (
        f"<t:{timestamp}:F>\n"
        f"<t:{timestamp}:R>"
    )


# =========================================================
# NAME FUNCTIONS
# =========================================================

def normalize_name(name):

    if not name:

        return ""

    return re.sub(
        r"[^a-zA-Z0-9]",
        "",
        name
    ).lower()


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


    # Exact match
    if ign_key in member_names:

        return True


    # Flexible matching
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


# =========================================================
# AMOUNT FUNCTIONS
# =========================================================

def convert_amount(value):

    value = (
        value.upper()
        .replace(",", "")
        .replace(" ", "")
    )


    try:

        if value.endswith("B"):

            return int(
                float(value[:-1])
                * 1_000_000_000
            )


        if value.endswith("M"):

            return int(
                float(value[:-1])
                * 1_000_000
            )


        if value.endswith("K"):

            return int(
                float(value[:-1])
                * 1_000
            )


        return int(
            float(value)
        )


    except ValueError:

        return 0


def format_amount(amount):

    if amount >= 1_000_000_000:

        return (
            f"{amount / 1_000_000_000:g}B"
        )


    if amount >= 1_000_000:

        return (
            f"{amount / 1_000_000:g}M"
        )


    if amount >= 1_000:

        return (
            f"{amount / 1_000:g}K"
        )


    return str(
        amount
    )


# =========================================================
# MESSAGE PARSER
# =========================================================

def parse_donation_message(text):

    ign_match = re.search(
        r"IGN:\s*(.+)",
        text,
        re.IGNORECASE
    )


    previous_match = re.search(
        r"Previous Guild Gold:\s*(.+)",
        text,
        re.IGNORECASE
    )


    current_match = re.search(
        r"Current Guild Gold:\s*(.+)",
        text,
        re.IGNORECASE
    )


    donation_match = re.search(
        r"Daily Donation:\s*(.+)",
        text,
        re.IGNORECASE
    )


    if (
        not ign_match
        or not donation_match
    ):

        return None


    ign = (
        ign_match
        .group(1)
        .strip()
    )


    previous = (

        previous_match
        .group(1)
        .strip()

        if previous_match

        else "Unknown"
    )


    current = (

        current_match
        .group(1)
        .strip()

        if current_match

        else "Unknown"
    )


    donation_text = (
        donation_match
        .group(1)
        .strip()
    )


    donation_amount = convert_amount(
        donation_text
    )


    if donation_amount <= 0:

        return None


    return {
        "ign": ign,
        "previous": previous,
        "current": current,
        "donation_text": donation_text,
        "donation_amount": donation_amount,
    }


# =========================================================
# CREDIT FUNCTIONS
# =========================================================

def is_day_covered(
    guild,
    ign_key,
    day
):

    cursor.execute("""
    SELECT 1
    FROM donation_coverage

    WHERE guild=?
    AND ign_key=?
    AND covered_day=?

    LIMIT 1
    """, (
        guild,
        ign_key,
        day
    ))


    return (
        cursor.fetchone()
        is not None
    )


def get_credit_balance(
    guild,
    ign_key
):

    cursor.execute("""
    SELECT balance
    FROM donation_credit

    WHERE guild=?
    AND ign_key=?
    """, (
        guild,
        ign_key
    ))


    row = cursor.fetchone()


    if row:

        return row[0]


    return 0


def set_credit_balance(
    guild,
    ign_key,
    display_ign,
    balance
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
        guild,
        ign_key,
        display_ign,
        balance
    ))


    db.commit()


def add_coverage(
    guild,
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
        guild,
        ign_key,
        display_ign,
        covered_day
    ))


    db.commit()


# =========================================================
# ADVANCE PAYMENT SYSTEM
# =========================================================

def apply_credit(
    guild,
    ign,
    amount,
    start_day
):

    """
    100K = 1 day.

    Example:
    200K on Aug 2
    covers:
    Aug 2
    Aug 3

    If Aug 3 is already covered,
    the second 100K automatically
    moves to Aug 4.
    """

    ign_key = normalize_name(
        ign
    )


    balance = get_credit_balance(
        guild,
        ign_key
    )


    balance += amount


    check_date = date.fromisoformat(
        start_day
    )


    while balance >= DAILY_REQUIREMENT:


        # Never stack two payments
        # onto the same covered day.
        while is_day_covered(
            guild,
            ign_key,
            check_date.isoformat()
        ):

            check_date += timedelta(
                days=1
            )


        add_coverage(
            guild,
            ign_key,
            ign,
            check_date.isoformat()
        )


        balance -= DAILY_REQUIREMENT


        check_date += timedelta(
            days=1
        )


    set_credit_balance(
        guild,
        ign_key,
        ign,
        balance
    )


    return balance


def get_covered_through(
    guild,
    ign_key
):

    today = date.fromisoformat(
        get_today()
    )


    if not is_day_covered(
        guild,
        ign_key,
        today.isoformat()
    ):

        return None


    check_date = today

    last_day = today


    while is_day_covered(
        guild,
        ign_key,
        check_date.isoformat()
    ):

        last_day = check_date


        check_date += timedelta(
            days=1
        )


    return last_day.isoformat()


# =========================================================
# DUPLICATE PROTECTION
# =========================================================

def message_already_logged(
    message_id
):

    cursor.execute("""
    SELECT id
    FROM donations
    WHERE message_id=?
    LIMIT 1
    """, (
        str(message_id),
    ))


    return (
        cursor.fetchone()
        is not None
    )


def find_old_unlinked_donation(
    guild,
    ign,
    previous,
    current,
    amount,
    donation_day
):

    """
    Old versions of the bot did not save
    Discord message IDs.

    During /syncoldlogs we try to match
    old database rows to their Discord
    messages before importing anything.

    This prevents the old donation from
    being counted twice.
    """

    cursor.execute("""
    SELECT
        id,
        ign,
        previous_gold,
        current_gold,
        donation

    FROM donations

    WHERE guild=?
    AND day=?
    AND donation=?
    AND message_id IS NULL

    ORDER BY id ASC
    """, (
        guild,
        donation_day,
        amount
    ))


    rows = cursor.fetchall()


    target_ign = normalize_name(
        ign
    )


    for (
        donation_id,
        database_ign,
        database_previous,
        database_current,
        database_amount
    ) in rows:


        if (
            normalize_name(database_ign)
            != target_ign
        ):

            continue


        # Extra protection using gold values
        if (
            previous != "Unknown"
            and database_previous
            and database_previous != "Unknown"
        ):

            if (
                database_previous.strip().lower()
                != previous.strip().lower()
            ):

                continue


        if (
            current != "Unknown"
            and database_current
            and database_current != "Unknown"
        ):

            if (
                database_current.strip().lower()
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

    SET
        message_id=?,
        channel_id=?

    WHERE id=?
    """, (
        str(message_id),
        str(channel_id),
        donation_id
    ))


    db.commit()


# =========================================================
# SAVE NEW DONATION
# =========================================================

def save_donation(
    guild,
    ign,
    previous,
    current,
    donation,
    logged_by,
    timestamp,
    donation_day,
    message_id,
    channel_id
):

    # Absolute duplicate protection
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
        time,
        day,
        message_id,
        channel_id
    )

    VALUES (
        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
    )
    """, (
        guild,
        ign,
        previous,
        current,
        donation,
        logged_by,
        str(timestamp),
        donation_day,
        str(message_id),
        str(channel_id)
    ))


    donation_id = (
        cursor.lastrowid
    )


    db.commit()


    # Apply the payment ONCE.
    apply_credit(
        guild,
        ign,
        donation,
        donation_day
    )


    cursor.execute("""
    INSERT OR IGNORE INTO credit_processed
    (
        donation_id
    )

    VALUES (?)
    """, (
        donation_id,
    ))


    db.commit()


    return donation_id


# =========================================================
# LEADERBOARD
# =========================================================

def get_leaderboard(
    guild
):

    cursor.execute("""
    SELECT
        ign,
        SUM(donation)

    FROM donations

    WHERE guild=?

    GROUP BY LOWER(ign)

    ORDER BY SUM(donation) DESC

    LIMIT 10
    """, (
        guild,
    ))


    return cursor.fetchall()


# =========================================================
# MIGRATE PREVIOUS DATABASE
# =========================================================

def migrate_old_donations():

    """
    Processes old database rows only once.

    credit_processed prevents the bot from
    rebuilding their credit every restart.
    """

    cursor.execute("""
    SELECT
        id,
        guild,
        ign,
        donation,
        day

    FROM donations

    ORDER BY id ASC
    """)


    rows = cursor.fetchall()


    converted = 0


    for (
        donation_id,
        guild,
        ign,
        amount,
        donation_day
    ) in rows:


        cursor.execute("""
        SELECT 1
        FROM credit_processed
        WHERE donation_id=?
        """, (
            donation_id,
        ))


        if cursor.fetchone():

            continue


        if not donation_day:

            donation_day = get_today()


        apply_credit(
            guild,
            ign,
            amount,
            donation_day
        )


        cursor.execute("""
        INSERT OR IGNORE INTO credit_processed
        (
            donation_id
        )

        VALUES (?)
        """, (
            donation_id,
        ))


        converted += 1


    db.commit()


    if converted:

        print(
            f"Converted {converted} "
            f"old database donations."
        )


migrate_old_donations()


# =========================================================
# BOT SETUP
# =========================================================

intents = discord.Intents.default()

intents.message_content = True
intents.members = True


bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================================================
# GUILD OPTIONS
# =========================================================

GUILD_CHOICES = [

    app_commands.Choice(
        name=f"Guild {i}",
        value=f"Guild {i}"
    )

    for i in range(
        1,
        10
    )
]


# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():

    print(
        f"Logged in as {bot.user}"
    )


    guild = discord.Object(
        id=SERVER_ID
    )


    bot.tree.copy_global_to(
        guild=guild
    )


    synced = await bot.tree.sync(
        guild=guild
    )


    print(
        f"Synced {len(synced)} commands "
        f"to server {SERVER_ID}"
    )


# =========================================================
# BUILD TRACKER EMBED
# =========================================================

def build_tracker_embed(
    guild_name,
    ign,
    previous,
    current,
    donation_text,
    donation_amount,
    author,
    timestamp,
    message_url,
    imported=False
):

    ign_key = normalize_name(
        ign
    )


    credit_balance = get_credit_balance(
        guild_name,
        ign_key
    )


    covered_through = get_covered_through(
        guild_name,
        ign_key
    )


    if imported:

        title = (
            "📥 Historical Donation Imported"
        )

        colour = discord.Color.blurple()

    else:

        title = (
            "💰 Donation Recorded"
        )

        colour = discord.Color.green()


    embed = discord.Embed(
        title=title,
        color=colour
    )


    # =========================================
    # PLAYER + GUILD
    # =========================================

    embed.add_field(
        name="👤 Player",
        value=f"**{ign}**",
        inline=True
    )


    embed.add_field(
        name="🏰 Guild",
        value=f"**{guild_name}**",
        inline=True
    )


    embed.add_field(
        name="💰 Donation",
        value=(
            f"**{format_amount(donation_amount)}**\n"
            f"`{donation_amount:,}`"
        ),
        inline=True
    )


    # =========================================
    # GOLD
    # =========================================

    embed.add_field(
        name="Before",
        value=previous,
        inline=True
    )


    embed.add_field(
        name="After",
        value=current,
        inline=True
    )


    # =========================================
    # COVERAGE
    # =========================================

    if covered_through:


        if covered_through == get_today():

            coverage = (
                "✅ **Covered today**"
            )


        else:

            through_date = (
                datetime.strptime(
                    covered_through,
                    "%Y-%m-%d"
                )
                .strftime(
                    "%d %b %Y"
                )
            )


            coverage = (
                f"✅ Covered through "
                f"**{through_date}**"
            )


    else:

        coverage = (
            "ℹ️ Historical payment applied"
            if imported
            else "⚠️ Not covered today"
        )


    if credit_balance > 0:

        coverage += (
            f"\n💳 Remaining credit: "
            f"**{format_amount(credit_balance)}**"
        )


    embed.add_field(
        name="📅 Payment Coverage",
        value=coverage,
        inline=False
    )


    # =========================================
    # LOG INFORMATION
    # =========================================

    embed.add_field(
        name="📝 Logged By",
        value=author.mention,
        inline=True
    )


    embed.add_field(
        name="🕒 Logged At",
        value=discord_timestamp(
            timestamp
        ),
        inline=True
    )


    embed.add_field(
        name="🔗 Source",
        value=(
            f"[View original log]"
            f"({message_url})"
        ),
        inline=False
    )


    if imported:

        embed.set_footer(
            text=(
                "Historical import • "
                "Original message time preserved • "
                "100K = 1 day"
            )
        )


    else:

        embed.set_footer(
            text=(
                "100K = 1 day • "
                "Extra donations automatically "
                "cover future days"
            )
        )


    return embed


# =========================================================
# PROCESS DONATION MESSAGE
# =========================================================

async def process_donation_message(
    message,
    imported=False
):

    if message.author.bot:

        return "invalid"


    if (
        message.channel.id
        not in GUILD_CHANNELS
    ):

        return "invalid"


    parsed = parse_donation_message(
        message.content
    )


    if not parsed:

        return "invalid"


    # Already imported / processed
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

    donation_text = (
        parsed["donation_text"]
    )

    donation_amount = (
        parsed["donation_amount"]
    )


    # Always use ORIGINAL Discord message time.
    created_at = (
        message.created_at
        .astimezone(
            timezone.utc
        )
    )


    timestamp = int(
        created_at.timestamp()
    )


    donation_day = (
        created_at
        .date()
        .isoformat()
    )


    # =====================================================
    # OLD DATABASE MATCH
    # =====================================================

    if imported:

        existing_id = (
            find_old_unlinked_donation(
                guild_name,
                ign,
                previous,
                current,
                donation_amount,
                donation_day
            )
        )


        # This was already processed by the
        # previous version of the bot.
        # Link its message ID but DO NOT add
        # any credit again.
        if existing_id:

            link_message_to_existing_donation(
                existing_id,
                message.id,
                message.channel.id
            )


            return "linked"


    # =====================================================
    # NEW DONATION
    # =====================================================

    donation_id = save_donation(
        guild=guild_name,
        ign=ign,
        previous=previous,
        current=current,
        donation=donation_amount,
        logged_by=message.author.display_name,
        timestamp=timestamp,
        donation_day=donation_day,
        message_id=message.id,
        channel_id=message.channel.id
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


        except Exception as e:

            print(
                f"Tracker channel error: {e}"
            )

            return "saved_no_tracker"


    embed = build_tracker_embed(
        guild_name=guild_name,
        ign=ign,
        previous=previous,
        current=current,
        donation_text=donation_text,
        donation_amount=donation_amount,
        author=message.author,
        timestamp=timestamp,
        message_url=message.jump_url,
        imported=imported
    )


    await tracker.send(
        embed=embed
    )


    return "imported" if imported else "saved"


# =========================================================
# LIVE DONATION READER
# =========================================================

@bot.event
async def on_message(message):

    await bot.process_commands(
        message
    )


    if message.author.bot:

        return


    if (
        message.channel.id
        not in GUILD_CHANNELS
    ):

        return


    try:

        result = (
            await process_donation_message(
                message,
                imported=False
            )
        )


        if result == "saved":

            print(
                f"Live donation processed: "
                f"{message.id}"
            )


    except Exception as e:

        print(
            "LIVE DONATION ERROR:"
        )

        print(
            repr(e)
        )


# =========================================================
# SYNC OLD LOGS
# =========================================================

@bot.tree.command(
    name="syncoldlogs",
    description="Import old donation messages from all guild channels"
)
@app_commands.describe(
    days=(
        "How many days back to scan. "
        "Use 0 for all available history."
    )
)
async def syncoldlogs(
    interaction: discord.Interaction,
    days: int = 0
):

    # Only people with Manage Server
    # can perform a full historical sync.
    if not (
        interaction.user.guild_permissions
        .manage_guild
    ):

        await interaction.response.send_message(
            "❌ You need **Manage Server** "
            "permission to run this command.",
            ephemeral=True
        )

        return


    if days < 0:

        await interaction.response.send_message(
            "❌ Days cannot be negative.",
            ephemeral=True
        )

        return


    await interaction.response.defer(
        thinking=True,
        ephemeral=True
    )


    imported = 0

    duplicates = 0

    linked = 0

    invalid = 0

    errors = 0

    scanned = 0


    print(
        "Starting old donation sync..."
    )


    after = None


    if days > 0:

        after = (
            get_now()
            - timedelta(
                days=days
            )
        )


    for (
        channel_id,
        guild_name
    ) in GUILD_CHANNELS.items():


        channel = bot.get_channel(
            channel_id
        )


        if channel is None:

            try:

                channel = (
                    await bot.fetch_channel(
                        channel_id
                    )
                )


            except Exception as e:

                print(
                    f"Could not access "
                    f"{guild_name}: {e}"
                )

                errors += 1

                continue


        print(
            f"Scanning {guild_name}..."
        )


        try:

            history = channel.history(
                limit=None,
                oldest_first=True,
                after=after
            )


            async for message in history:

                scanned += 1


                try:

                    result = (
                        await process_donation_message(
                            message,
                            imported=True
                        )
                    )


                    if result == "imported":

                        imported += 1


                    elif result == "duplicate":

                        duplicates += 1


                    elif result == "linked":

                        linked += 1


                    elif result == "invalid":

                        invalid += 1


                except Exception as e:

                    errors += 1


                    print(
                        f"Sync message error "
                        f"{message.id}: "
                        f"{repr(e)}"
                    )


        except Exception as e:

            errors += 1


            print(
                f"History error for "
                f"{guild_name}: "
                f"{repr(e)}"
            )


    # =====================================================
    # SYNC SUMMARY
    # =====================================================

    summary = discord.Embed(
        title="✅ Historical Sync Complete",
        description=(
            "The bot finished checking the "
            "guild donation channels."
        ),
        color=discord.Color.green()
    )


    summary.add_field(
        name="📥 Imported",
        value=str(imported),
        inline=True
    )


    summary.add_field(
        name="🔗 Existing Logs Linked",
        value=str(linked),
        inline=True
    )


    summary.add_field(
        name="⏭️ Already Tracked",
        value=str(duplicates),
        inline=True
    )


    summary.add_field(
        name="🔎 Messages Scanned",
        value=f"{scanned:,}",
        inline=True
    )


    summary.add_field(
        name="💬 Non-Donation Messages",
        value=f"{invalid:,}",
        inline=True
    )


    summary.add_field(
        name="⚠️ Errors",
        value=str(errors),
        inline=True
    )


    summary.add_field(
        name="🛡️ Duplicate Protection",
        value=(
            "Every Discord message is tracked "
            "by its unique message ID. "
            "Re-running this command will not "
            "stack advance payments."
        ),
        inline=False
    )


    await interaction.followup.send(
        embed=summary,
        ephemeral=True
    )


    print(
        f"Historical sync complete. "
        f"Imported={imported}, "
        f"Linked={linked}, "
        f"Duplicates={duplicates}, "
        f"Errors={errors}"
    )


# =========================================================
# DONATION STATUS
# =========================================================

@bot.tree.command(
    name="donationstatus",
    description="Check who is covered and who is missing today's 100K"
)
@app_commands.describe(
    guild="Choose a guild"
)
@app_commands.choices(
    guild=GUILD_CHOICES
)
async def donationstatus(
    interaction: discord.Interaction,
    guild: app_commands.Choice[str]
):

    await interaction.response.defer(
        thinking=True
    )


    try:

        guild_name = guild.value


        role_id = GUILD_ROLES.get(
            guild_name
        )


        if role_id is None:

            await interaction.followup.send(
                "❌ Guild role is not configured."
            )

            return


        discord_guild = (
            interaction.guild
        )


        if discord_guild is None:

            await interaction.followup.send(
                "❌ Use this command in the server."
            )

            return


        # =================================================
        # LOAD MEMBERS
        # =================================================

        try:

            await asyncio.wait_for(
                discord_guild.chunk(
                    cache=True
                ),
                timeout=10
            )


        except asyncio.TimeoutError:

            print(
                "Member loading timed out. "
                "Using cached members."
            )


        except Exception as e:

            print(
                f"Member loading error: {e}"
            )


        role = discord_guild.get_role(
            role_id
        )


        if role is None:

            await interaction.followup.send(
                f"❌ I couldn't find the role "
                f"for **{guild_name}**."
            )

            return


        members = [

            member

            for member in role.members

            if not member.bot
        ]


        # =================================================
        # CREDIT ACCOUNTS
        # =================================================

        cursor.execute("""
        SELECT
            ign_key,
            display_ign,
            balance

        FROM donation_credit

        WHERE guild=?
        """, (
            guild_name,
        ))


        credit_accounts = (
            cursor.fetchall()
        )


        covered_members = []

        missing_members = []

        matched_ign_keys = set()


        # =================================================
        # MATCH MEMBERS
        # =================================================

        for member in members:

            matched_account = None


            for (
                ign_key,
                display_ign,
                balance
            ) in credit_accounts:


                if names_match(
                    display_ign,
                    member
                ):

                    matched_account = (
                        ign_key,
                        display_ign,
                        balance
                    )

                    break


            if matched_account is None:

                missing_members.append(
                    member
                )

                continue


            (
                ign_key,
                display_ign,
                balance
            ) = matched_account


            matched_ign_keys.add(
                ign_key
            )


            if is_day_covered(
                guild_name,
                ign_key,
                get_today()
            ):

                covered_through = (
                    get_covered_through(
                        guild_name,
                        ign_key
                    )
                )


                covered_members.append(
                    (
                        member,
                        display_ign,
                        covered_through,
                        balance
                    )
                )


            else:

                missing_members.append(
                    member
                )


        # =================================================
        # UNMATCHED IGNS
        # =================================================

        unmatched = []


        for (
            ign_key,
            display_ign,
            balance
        ) in credit_accounts:


            if ign_key in matched_ign_keys:

                continue


            matched_someone = False


            for member in members:

                if names_match(
                    display_ign,
                    member
                ):

                    matched_someone = True

                    matched_ign_keys.add(
                        ign_key
                    )

                    break


            if matched_someone:

                continue


            if is_day_covered(
                guild_name,
                ign_key,
                get_today()
            ):

                unmatched.append(
                    (
                        display_ign,
                        balance
                    )
                )


        timestamp = get_timestamp()


        # =================================================
        # STATUS UI
        # =================================================

        embed = discord.Embed(
            title=(
                f"📊 {guild_name} "
                f"Daily Donation Status"
            ),
            description=(
                f"**Daily Requirement:** "
                f"{format_amount(DAILY_REQUIREMENT)}\n"
                f"**Status:** <t:{timestamp}:R>"
            ),
            color=discord.Color.blurple()
        )


        embed.add_field(
            name="👥 Members",
            value=f"**{len(members)}**",
            inline=True
        )


        embed.add_field(
            name="✅ Covered",
            value=f"**{len(covered_members)}**",
            inline=True
        )


        embed.add_field(
            name="❌ Missing",
            value=f"**{len(missing_members)}**",
            inline=True
        )


        # =================================================
        # COVERED LIST
        # =================================================

        if covered_members:

            text = ""


            for (
                member,
                display_ign,
                covered_through,
                balance
            ) in covered_members:


                line = (
                    f"✅ **{member.display_name}**"
                )


                if (
                    covered_through
                    and covered_through
                    != get_today()
                ):

                    through = (
                        datetime.strptime(
                            covered_through,
                            "%Y-%m-%d"
                        )
                        .strftime(
                            "%d %b"
                        )
                    )


                    line += (
                        f"  •  Paid through "
                        f"**{through}**"
                    )


                if balance > 0:

                    line += (
                        f"  •  "
                        f"{format_amount(balance)} credit"
                    )


                line += "\n"


                if (
                    len(text)
                    + len(line)
                    > 1000
                ):

                    text += (
                        "\n*More members not shown...*"
                    )

                    break


                text += line


            embed.add_field(
                name="✅ Covered Today",
                value=text,
                inline=False
            )


        else:

            embed.add_field(
                name="✅ Covered Today",
                value="Nobody is covered yet.",
                inline=False
            )


        # =================================================
        # MISSING LIST
        # =================================================

        if missing_members:

            text = ""


            for member in missing_members:

                line = (
                    f"❌ {member.mention} "
                    f"• {member.display_name}\n"
                )


                if (
                    len(text)
                    + len(line)
                    > 1000
                ):

                    text += (
                        "\n*More members not shown...*"
                    )

                    break


                text += line


            embed.add_field(
                name="❌ Missing Today's Donation",
                value=text,
                inline=False
            )


        else:

            embed.add_field(
                name="❌ Missing Today's Donation",
                value=(
                    "🎉 **Everyone is covered today!**"
                ),
                inline=False
            )


        # =================================================
        # UNMATCHED
        # =================================================

        if unmatched:

            text = ""


            for (
                display_ign,
                balance
            ) in unmatched:


                line = (
                    f"⚠️ **{display_ign}**"
                )


                if balance > 0:

                    line += (
                        f" • "
                        f"{format_amount(balance)} credit"
                    )


                line += "\n"


                if (
                    len(text)
                    + len(line)
                    > 1000
                ):

                    break


                text += line


            embed.add_field(
                name="⚠️ IGN Not Matched",
                value=(
                    text
                    +
                    "\n*These IGNs could not be matched "
                    "to a member with this guild role.*"
                ),
                inline=False
            )


        embed.set_footer(
            text=(
                "100K = 1 day • Advance payments carry forward • "
                "Duplicate logs are ignored"
            )
        )


        await interaction.followup.send(
            embed=embed
        )


    except Exception as e:

        print(
            "DONATION STATUS ERROR:"
        )

        print(
            repr(e)
        )


        try:

            await interaction.followup.send(
                "❌ Something went wrong. "
                "Check Railway logs."
            )


        except Exception:

            pass


# =========================================================
# LEADERBOARD
# =========================================================

@bot.tree.command(
    name="leaderboard",
    description="Show the guild lifetime donation leaderboard"
)
@app_commands.describe(
    guild="Choose a guild"
)
@app_commands.choices(
    guild=GUILD_CHOICES
)
async def leaderboard(
    interaction: discord.Interaction,
    guild: app_commands.Choice[str]
):

    data = get_leaderboard(
        guild.value
    )


    embed = discord.Embed(
        title=(
            f"🏆 {guild.value} "
            f"Donation Leaderboard"
        ),
        color=discord.Color.gold()
    )


    if not data:

        embed.description = (
            "No donations have been recorded yet."
        )


    else:

        medals = [
            "🥇",
            "🥈",
            "🥉"
        ]


        text = ""


        for index, (
            ign,
            amount
        ) in enumerate(
            data,
            start=1
        ):


            rank = (
                medals[index - 1]
                if index <= 3
                else f"`#{index}`"
            )


            text += (
                f"{rank} **{ign}**\n"
                f"└ {format_amount(amount)} "
                f"• `{amount:,}`\n"
            )


        embed.description = text


    embed.set_footer(
        text="Lifetime donations across all recorded logs"
    )


    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# START BOT
# =========================================================

if not TOKEN:

    raise RuntimeError(
        "TOKEN is missing from Railway."
    )


try:

    bot.run(
        TOKEN
    )


except Exception as e:

    print(
        "BOT CRASHED:"
    )

    print(
        repr(e)
    )
