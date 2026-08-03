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

# Every 100K = 1 covered day
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
    PRIMARY KEY (guild, ign_key, covered_day)
)
""")


cursor.execute("""
CREATE TABLE IF NOT EXISTS credit_processed (
    donation_id INTEGER PRIMARY KEY
)
""")


db.commit()


# =========================================================
# TIME FUNCTIONS
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


# =========================================================
# NAME MATCHING
# =========================================================

def normalize_name(name):

    """
    Basic normalized version.

    Example:
    Chicken (@Kimoy)
    becomes:
    chickenkimoy
    """

    if not name:
        return ""

    return re.sub(
        r"[^a-zA-Z0-9]",
        "",
        name
    ).lower()


def get_member_names(member):

    names = set()


    # Discord username
    if member.name:

        names.add(
            normalize_name(
                member.name
            )
        )


    # Server nickname / display name
    if member.display_name:

        names.add(
            normalize_name(
                member.display_name
            )
        )


    # Global Discord display name
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

    """
    More flexible matching.

    Examples that can match:

    IGN:
    Chicken

    Discord:
    Chicken (@Kimoy123)

    ----------------

    IGN:
    Taekia

    Discord:
    Taekia 4 Her
    """

    ign_key = normalize_name(
        ign
    )


    if not ign_key:

        return False


    member_names = get_member_names(
        member
    )


    # Exact match first
    if ign_key in member_names:

        return True


    # Smart partial matching
    # Only do this for names with at least 4 characters
    # to avoid things like "A" matching everybody.
    if len(ign_key) >= 4:

        for discord_name in member_names:

            # IGN at beginning of Discord name
            if discord_name.startswith(
                ign_key
            ):

                return True


            # Discord username at beginning of IGN
            if (
                len(discord_name) >= 4
                and ign_key.startswith(
                    discord_name
                )
            ):

                return True


    return False


# =========================================================
# NUMBER FUNCTIONS
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
# ADVANCE PAYMENT
# =========================================================

def apply_credit(
    guild,
    ign,
    amount,
    start_day=None
):

    if start_day is None:

        start_day = get_today()


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


    # Every full 100K covers another day
    while balance >= DAILY_REQUIREMENT:


        # Skip days already paid
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
# SAVE DONATION
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


    donation_id = (
        cursor.lastrowid
    )


    db.commit()


    # Automatically convert donation
    # to daily coverage
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


# =========================================================
# LEADERBOARD
# =========================================================

def get_leaderboard(
    guild
):

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
# OLD DONATION MIGRATION
# =========================================================

def migrate_old_donations():

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
            f"Converted {converted} old "
            f"donations into credit."
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


        print(
            f"/donationstatus started "
            f"for {guild_name}"
        )


        role_id = GUILD_ROLES.get(
            guild_name
        )


        if role_id is None:

            await interaction.followup.send(
                "❌ No role is configured "
                "for this guild."
            )

            return


        discord_guild = (
            interaction.guild
        )


        if discord_guild is None:

            await interaction.followup.send(
                "❌ Use this inside "
                "the Discord server."
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


        # =================================================
        # ROLE
        # =================================================

        role = discord_guild.get_role(
            role_id
        )


        if role is None:

            await interaction.followup.send(
                f"❌ Can't find the role "
                f"for **{guild_name}**."
            )

            return


        members = [

            member

            for member in role.members

            if not member.bot
        ]


        print(
            f"Found {len(members)} members."
        )


        # =================================================
        # LOAD CREDIT ACCOUNTS
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


        # =================================================
        # MATCH IGNS TO DISCORD MEMBERS
        # =================================================

        covered_members = []

        missing_members = []

        matched_ign_keys = set()


        for member in members:

            matched_account = None


            # Check every known IGN against this member
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


            # IMPORTANT:
            # Mark it matched immediately,
            # even if they aren't covered today.
            #
            # This prevents the same IGN appearing
            # under "Not Matched to Discord".
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
        # UNMATCHED DONATION ACCOUNTS
        # =================================================

        unmatched = []


        for (
            ign_key,
            display_ign,
            balance
        ) in credit_accounts:


            # Already matched = NEVER show unmatched
            if ign_key in matched_ign_keys:

                continue


            # Extra safety:
            # Run through all role members one more time
            # before calling an IGN unmatched.
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


            # Only show unmatched IGNs that are
            # actually covered today
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


        # =================================================
        # EMBED
        # =================================================

        timestamp = get_timestamp()


        embed = discord.Embed(
            title=(
                f"📊 {guild_name} "
                f"Donation Status"
            ),
            description=(
                f"Daily Requirement: "
                f"**{format_amount(DAILY_REQUIREMENT)}**\n"
                f"Checked: <t:{timestamp}:F>\n"
                f"<t:{timestamp}:R>"
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


        # =================================================
        # COVERED MEMBERS
        # =================================================

        if covered_members:

            covered_text = ""


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

                    through_date = (
                        datetime.strptime(
                            covered_through,
                            "%Y-%m-%d"
                        )
                        .strftime(
                            "%d %b"
                        )
                    )


                    line += (
                        f" — paid through "
                        f"**{through_date}**"
                    )


                if balance > 0:

                    line += (
                        f" + "
                        f"{format_amount(balance)} "
                        f"credit"
                    )


                line += "\n"


                if (
                    len(covered_text)
                    + len(line)
                    > 1000
                ):

                    covered_text += (
                        "\n*More members "
                        "not shown...*"
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
                value=(
                    "Nobody is covered yet."
                ),
                inline=False
            )


        # =================================================
        # MISSING MEMBERS
        # =================================================

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
                        "\n*More members "
                        "not shown...*"
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
                value=(
                    "🎉 Everyone is covered!"
                ),
                inline=False
            )


        # =================================================
        # TRULY UNMATCHED IGNS
        # =================================================

        if unmatched:

            unmatched_text = ""


            for (
                display_ign,
                balance
            ) in unmatched:


                line = (
                    f"⚠️ **{display_ign}**"
                )


                if balance > 0:

                    line += (
                        f" — "
                        f"{format_amount(balance)} "
                        f"credit"
                    )


                line += "\n"


                if (
                    len(unmatched_text)
                    + len(line)
                    > 1000
                ):

                    unmatched_text += (
                        "\n*More not shown...*"
                    )

                    break


                unmatched_text += line


            embed.add_field(
                name="⚠️ IGN Not Matched to Discord",
                value=(
                    unmatched_text
                    +
                    "\nThese are donation IGNs "
                    "I genuinely couldn't match "
                    "to anyone with this guild role."
                ),
                inline=False
            )


        embed.set_footer(
            text=(
                "100K = 1 day • Advance payments "
                "carry forward • Daily reset: UTC"
            )
        )


        await interaction.followup.send(
            embed=embed
        )


        print(
            f"/donationstatus finished "
            f"for {guild_name}"
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
                "Check the Railway logs."
            )

        except Exception:

            pass


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
                f"(`{amount:,}`)\n"
            )


        embed.description = text


    embed.set_footer(
        text=(
            "Lifetime donation leaderboard"
        )
    )


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


    if (
        message.channel.id
        not in GUILD_CHANNELS
    ):

        return


    text = message.content


    # =====================================================
    # PARSE LOG
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
    # SAVE
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


    credit_balance = (
        get_credit_balance(
            guild_name,
            ign_key
        )
    )


    covered_through = (
        get_covered_through(
            guild_name,
            ign_key
        )
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

            tracker = (
                await bot.fetch_channel(
                    TRACKER_CHANNEL_ID
                )
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
    # COVERAGE
    # =====================================================

    if covered_through:


        if covered_through == get_today():

            coverage_text = (
                "✅ **Today's 100K is covered**"
            )


        else:

            through_date = (
                datetime.strptime(
                    covered_through,
                    "%Y-%m-%d"
                )
                .strftime(
                    "%d %B %Y"
                )
            )


            coverage_text = (
                f"✅ Paid through "
                f"**{through_date}**"
            )


    else:

        coverage_text = (
            "⚠️ Not enough credit "
            "to cover today"
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
            "100K = 1 day • Extra donations "
            "automatically pay future days"
        )
    )


    try:

        await tracker.send(
            embed=embed
        )


    except Exception as e:

        print(
            f"TRACKER SEND ERROR: {e}"
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


    print(
        repr(e)
    )
