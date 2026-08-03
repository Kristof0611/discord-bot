import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

import os
import sqlite3
import re
from datetime import datetime, timezone, date, timedelta


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

TOKEN = os.getenv("TOKEN")

SERVER_ID = 1529030570410119259

# Every 100K covers one donation day
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


# Main donation history
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


# Credit balances
cursor.execute("""
CREATE TABLE IF NOT EXISTS donation_credit (
    guild TEXT NOT NULL,
    ign_key TEXT NOT NULL,
    display_ign TEXT NOT NULL,
    balance INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild, ign_key)
)
""")


# Every row = one fully paid donation day
cursor.execute("""
CREATE TABLE IF NOT EXISTS donation_coverage (
    guild TEXT NOT NULL,
    ign_key TEXT NOT NULL,
    display_ign TEXT NOT NULL,
    covered_day TEXT NOT NULL,
    PRIMARY KEY (guild, ign_key, covered_day)
)
""")


# Keeps old donations from being converted to credit twice
cursor.execute("""
CREATE TABLE IF NOT EXISTS credit_processed (
    donation_id INTEGER PRIMARY KEY
)
""")


db.commit()


# =========================================================
# TIME
# =========================================================

def get_now():
    return datetime.now(timezone.utc)


def get_today():
    return get_now().date().isoformat()


def get_timestamp():
    return int(get_now().timestamp())


# =========================================================
# NAME FUNCTIONS
# =========================================================

def normalize_name(name):
    return (
        name
        .strip()
        .lower()
        .replace(" ", "")
    )


def get_member_names(member):

    names = {
        normalize_name(member.display_name),
        normalize_name(member.name)
    }

    if member.global_name:
        names.add(
            normalize_name(member.global_name)
        )

    return names


# =========================================================
# NUMBER CONVERTER
# =========================================================

def convert_amount(value):

    value = value.upper()
    value = value.replace(",", "")
    value = value.replace(" ", "")

    try:

        if value.endswith("B"):
            return int(
                float(value[:-1]) * 1_000_000_000
            )

        if value.endswith("M"):
            return int(
                float(value[:-1]) * 1_000_000
            )

        if value.endswith("K"):
            return int(
                float(value[:-1]) * 1_000
            )

        return int(float(value))

    except ValueError:
        return 0


def format_amount(amount):

    if amount >= 1_000_000_000:
        value = amount / 1_000_000_000
        return f"{value:g}B"

    if amount >= 1_000_000:
        value = amount / 1_000_000
        return f"{value:g}M"

    if amount >= 1_000:
        value = amount / 1_000
        return f"{value:g}K"

    return str(amount)


# =========================================================
# CREDIT FUNCTIONS
# =========================================================

def is_day_covered(guild, ign_key, day):

    cursor.execute("""
    SELECT 1
    FROM donation_coverage
    WHERE guild=? AND ign_key=? AND covered_day=?
    LIMIT 1
    """, (
        guild,
        ign_key,
        day
    ))

    return cursor.fetchone() is not None


def get_credit_balance(guild, ign_key):

    cursor.execute("""
    SELECT balance
    FROM donation_credit
    WHERE guild=? AND ign_key=?
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


def apply_credit(
    guild,
    ign,
    amount,
    start_day=None
):

    """
    Adds donation credit.

    Every 100K covers one day.

    Coverage starts from the donation day forward.
    It NEVER goes backwards to repair old missed days.
    """

    if start_day is None:
        start_day = get_today()

    ign_key = normalize_name(ign)

    current_balance = get_credit_balance(
        guild,
        ign_key
    )

    new_balance = current_balance + amount

    check_date = date.fromisoformat(
        start_day
    )


    # Use every full 100K to cover a day
    while new_balance >= DAILY_REQUIREMENT:

        # Find the next day that isn't already covered
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


        new_balance -= DAILY_REQUIREMENT

        check_date += timedelta(
            days=1
        )


    set_credit_balance(
        guild,
        ign_key,
        ign,
        new_balance
    )

    return new_balance


def get_covered_through(
    guild,
    ign_key
):

    """
    Finds how far into the future the player
    is continuously covered starting today.
    """

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

    last_covered = today


    while is_day_covered(
        guild,
        ign_key,
        check_date.isoformat()
    ):

        last_covered = check_date

        check_date += timedelta(
            days=1
        )


    return last_covered.isoformat()


# =========================================================
# DONATION DATABASE
# =========================================================

def save_donation(
    guild,
    ign,
    previous,
    current,
    donation,
    logged_by,
    timestamp
):

    today = get_today()

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
        day
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        guild,
        ign,
        previous,
        current,
        donation,
        logged_by,
        str(timestamp),
        today
    ))

    donation_id = cursor.lastrowid

    db.commit()


    # Convert this donation into daily credit
    apply_credit(
        guild,
        ign,
        donation,
        today
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


def get_leaderboard(guild):

    cursor.execute("""
    SELECT ign, SUM(donation)
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
# CONVERT EXISTING DONATIONS
# =========================================================

def migrate_old_donations():

    """
    If you already had donations in donations.db
    before adding the credit system, this converts
    them one time.

    credit_processed prevents duplicates.
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


    for donation_id, guild, ign, amount, donation_day in rows:

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


    if converted > 0:

        print(
            f"Converted {converted} existing "
            f"donations to the new credit system."
        )


# Run migration once on startup
migrate_old_donations()


# =========================================================
# BOT
# =========================================================

intents = discord.Intents.default()

intents.message_content = True
intents.members = True


bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================================================
# GUILD CHOICES
# =========================================================

GUILD_CHOICES = [

    app_commands.Choice(
        name="Guild 1",
        value="Guild 1"
    ),

    app_commands.Choice(
        name="Guild 2",
        value="Guild 2"
    ),

    app_commands.Choice(
        name="Guild 3",
        value="Guild 3"
    ),

    app_commands.Choice(
        name="Guild 4",
        value="Guild 4"
    ),

    app_commands.Choice(
        name="Guild 5",
        value="Guild 5"
    ),

    app_commands.Choice(
        name="Guild 6",
        value="Guild 6"
    ),

    app_commands.Choice(
        name="Guild 7",
        value="Guild 7"
    ),

    app_commands.Choice(
        name="Guild 8",
        value="Guild 8"
    ),

    app_commands.Choice(
        name="Guild 9",
        value="Guild 9"
    ),
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
# DONATION STATUS
# =========================================================

@bot.tree.command(
    name="donationstatus",
    description="Check who is covered and missing today's 100K donation"
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

    await interaction.response.defer()

    guild_name = guild.value

    role_id = GUILD_ROLES.get(
        guild_name
    )


    if role_id is None:

        await interaction.followup.send(
            "❌ No Discord role is configured "
            "for that guild."
        )

        return


    discord_guild = interaction.guild


    if discord_guild is None:

        await interaction.followup.send(
            "❌ Use this command inside the server."
        )

        return


    # Try to ensure all server members are cached
    try:

        await discord_guild.chunk(
            cache=True
        )

    except Exception:

        pass


    role = discord_guild.get_role(
        role_id
    )


    if role is None:

        await interaction.followup.send(
            f"❌ I couldn't find the Discord role "
            f"for **{guild_name}**."
        )

        return


    members = [

        member

        for member in role.members

        if not member.bot
    ]


    covered_members = []

    missing_members = []


    # =====================================================
    # CHECK EVERY GUILD MEMBER
    # =====================================================

    for member in members:

        possible_names = get_member_names(
            member
        )

        matched_key = None


        # Find any donation IGN that matches
        for name in possible_names:

            cursor.execute("""
            SELECT ign_key
            FROM donation_credit
            WHERE guild=? AND ign_key=?
            """, (
                guild_name,
                name
            ))

            row = cursor.fetchone()


            if row:

                matched_key = row[0]

                break


        # No donation account has ever matched this member
        if matched_key is None:

            missing_members.append(
                member
            )

            continue


        # Check today's 100K coverage
        if is_day_covered(
            guild_name,
            matched_key,
            get_today()
        ):

            covered_through = get_covered_through(
                guild_name,
                matched_key
            )

            credit_balance = get_credit_balance(
                guild_name,
                matched_key
            )

            covered_members.append(
                (
                    member,
                    covered_through,
                    credit_balance
                )
            )


        else:

            missing_members.append(
                member
            )


    # =====================================================
    # FIND DONATION IGNS THAT DON'T MATCH DISCORD
    # =====================================================

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


    all_credit_accounts = cursor.fetchall()


    matched_discord_names = set()


    for member in members:

        matched_discord_names.update(
            get_member_names(member)
        )


    unmatched = []


    for ign_key, display_ign, balance in all_credit_accounts:

        if ign_key not in matched_discord_names:

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


    # =====================================================
    # EMBED
    # =====================================================

    timestamp = get_timestamp()


    embed = discord.Embed(
        title=(
            f"📊 {guild_name} "
            f"Donation Status"
        ),
        description=(
            f"Daily requirement: **100K**\n"
            f"Checked: <t:{timestamp}:F>"
        ),
        color=discord.Color.blue()
    )


    embed.add_field(
        name="👥 Members",
        value=str(
            len(members)
        ),
        inline=True
    )


    embed.add_field(
        name="✅ Covered",
        value=str(
            len(covered_members)
        ),
        inline=True
    )


    embed.add_field(
        name="❌ Missing",
        value=str(
            len(missing_members)
        ),
        inline=True
    )


    # =====================================================
    # COVERED
    # =====================================================

    if covered_members:

        covered_text = ""


        for member, covered_through, balance in covered_members:

            through_date = datetime.strptime(
                covered_through,
                "%Y-%m-%d"
            ).strftime(
                "%d %b"
            )


            line = (
                f"✅ **{member.display_name}**"
            )


            if covered_through != get_today():

                line += (
                    f" — covered through "
                    f"**{through_date} UTC**"
                )


            if balance > 0:

                line += (
                    f" + {format_amount(balance)} credit"
                )


            line += "\n"


            if (
                len(covered_text)
                + len(line)
                > 1000
            ):

                covered_text += (
                    "\n*More members not shown...*"
                )

                break


            covered_text += line


        embed.add_field(
            name="✅ Covered Today",
            value=covered_text,
            inline=False
        )


    else:

        embed.add_field(
            name="✅ Covered Today",
            value="Nobody is covered yet.",
            inline=False
        )


    # =====================================================
    # MISSING
    # =====================================================

    if missing_members:

        missing_text = ""


        for member in missing_members:

            line = (
                f"❌ {member.mention} "
                f"({member.display_name})\n"
            )


            if (
                len(missing_text)
                + len(line)
                > 1000
            ):

                missing_text += (
                    "\n*More members not shown...*"
                )

                break


            missing_text += line


        embed.add_field(
            name="❌ Missing Today's Donation",
            value=missing_text,
            inline=False
        )


    else:

        embed.add_field(
            name="❌ Missing Today's Donation",
            value="🎉 Everyone is covered!",
            inline=False
        )


    # =====================================================
    # UNMATCHED
    # =====================================================

    if unmatched:

        unmatched_text = ""


        for ign, balance in unmatched:

            line = (
                f"⚠️ **{ign}**"
            )


            if balance > 0:

                line += (
                    f" — {format_amount(balance)} credit"
                )


            line += "\n"


            if (
                len(unmatched_text)
                + len(line)
                > 1000
            ):

                break


            unmatched_text += line


        embed.add_field(
            name="⚠️ IGN Not Matched to Discord",
            value=(
                unmatched_text
                +
                "\nTheir IGN doesn't match their "
                "Discord nickname/username."
            ),
            inline=False
        )


    embed.set_footer(
        text=(
            "100K = 1 day • Advance payments "
            "carry forward • Reset uses UTC"
        )
    )


    await interaction.followup.send(
        embed=embed
    )


# =========================================================
# LEADERBOARD
# =========================================================

@bot.tree.command(
    name="leaderboard",
    description="Show the guild donation leaderboard"
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
            "No donations recorded yet."
        )


    else:

        text = ""

        medals = [
            "🥇",
            "🥈",
            "🥉"
        ]


        for index, row in enumerate(
            data,
            start=1
        ):

            ign = row[0]

            amount = row[1]


            if index <= 3:

                rank = medals[
                    index - 1
                ]

            else:

                rank = (
                    f"**#{index}**"
                )


            text += (
                f"{rank} **{ign}** — "
                f"{format_amount(amount)} "
                f"({amount:,})\n"
            )


        embed.description = text


    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# AUTOMATIC DONATION READER
# =========================================================

@bot.event
async def on_message(message):

    await bot.process_commands(
        message
    )


    if message.author.bot:
        return


    if message.channel.id not in GUILD_CHANNELS:
        return


    text = message.content


    # =====================================================
    # PARSE DONATION MESSAGE
    # =====================================================

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

        return


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

        print(
            f"Invalid donation amount: "
            f"{donation_text}"
        )

        return


    guild_name = GUILD_CHANNELS[
        message.channel.id
    ]


    timestamp = get_timestamp()


    # =====================================================
    # SAVE + APPLY CREDIT
    # =====================================================

    save_donation(
        guild_name,
        ign,
        previous,
        current,
        donation_amount,
        message.author.display_name,
        timestamp
    )


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


    print(
        f"Donation logged: "
        f"{guild_name} | "
        f"{ign} | "
        f"{donation_amount}"
    )


    # =====================================================
    # TRACKER CHANNEL
    # =====================================================

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
                f"Could not find tracker "
                f"channel: {e}"
            )

            return


    # =====================================================
    # TRACKER EMBED
    # =====================================================

    embed = discord.Embed(
        title="💰 Guild Donation Logged",
        color=discord.Color.green()
    )


    embed.add_field(
        name="Guild",
        value=guild_name,
        inline=False
    )


    embed.add_field(
        name="IGN",
        value=ign,
        inline=False
    )


    embed.add_field(
        name="Previous Gold",
        value=previous,
        inline=True
    )


    embed.add_field(
        name="Current Gold",
        value=current,
        inline=True
    )


    embed.add_field(
        name="Donation",
        value=(
            f"**{donation_text}**\n"
            f"`{donation_amount:,}`"
        ),
        inline=False
    )


    # =====================================================
    # PAYMENT COVERAGE
    # =====================================================

    if covered_through:

        through_date = datetime.strptime(
            covered_through,
            "%Y-%m-%d"
        ).strftime(
            "%d %B %Y"
        )


        if covered_through == get_today():

            coverage_text = (
                "✅ **Today is covered**"
            )

        else:

            coverage_text = (
                f"✅ Covered through "
                f"**{through_date} UTC**"
            )


    else:

        coverage_text = (
            "⚠️ Not enough credit to cover today"
        )


    if credit_balance > 0:

        coverage_text += (
            f"\n💳 Remaining credit: "
            f"**{format_amount(credit_balance)}**"
        )


    embed.add_field(
        name="Payment Coverage",
        value=coverage_text,
        inline=False
    )


    embed.add_field(
        name="Logged By",
        value=message.author.mention,
        inline=True
    )


    embed.add_field(
        name="Time Logged",
        value=(
            f"<t:{timestamp}:F>\n"
            f"<t:{timestamp}:R>"
        ),
        inline=True
    )


    embed.add_field(
        name="Original Log",
        value=(
            f"[Jump to message]"
            f"({message.jump_url})"
        ),
        inline=False
    )


    embed.set_footer(
        text=(
            "100K = 1 day • Extra donation "
            "automatically becomes advance credit"
        )
    )


    await tracker.send(
        embed=embed
    )


# =========================================================
# START
# =========================================================

if not TOKEN:

    raise RuntimeError(
        "TOKEN is missing from Railway "
        "environment variables."
    )


try:

    bot.run(
        TOKEN
    )


except Exception as e:

    print(
        "BOT CRASHED:"
    )

    print(e)
