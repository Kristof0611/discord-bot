import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

import os
import sqlite3
import re
from datetime import datetime, timezone


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

TOKEN = os.getenv("TOKEN")

# Discord Server ID
SERVER_ID = 1529030570410119259


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

db.commit()


# =========================================================
# GLOBAL TIME
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
# DATABASE FUNCTIONS
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
    VALUES (?,?,?,?,?,?,?,?)
    """,
    (
        guild,
        ign,
        previous,
        current,
        donation,
        logged_by,
        str(timestamp),
        today
    ))

    db.commit()


def donated_today(guild):

    today = get_today()

    cursor.execute("""
    SELECT ign, SUM(donation)
    FROM donations
    WHERE guild=? AND day=?
    GROUP BY LOWER(ign)
    ORDER BY SUM(donation) DESC
    """,
    (
        guild,
        today
    ))

    return cursor.fetchall()


def get_leaderboard(guild):

    cursor.execute("""
    SELECT ign, SUM(donation)
    FROM donations
    WHERE guild=?
    GROUP BY LOWER(ign)
    ORDER BY SUM(donation) DESC
    LIMIT 10
    """,
    (guild,))

    return cursor.fetchall()


# =========================================================
# NUMBER CONVERTER
# =========================================================

def convert_amount(value):

    value = value.upper()

    value = value.replace(
        ",",
        ""
    )

    value = value.replace(
        " ",
        ""
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


# =========================================================
# NAME MATCHING
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
        normalize_name(
            member.display_name
        ),

        normalize_name(
            member.name
        )
    }


    if member.global_name:

        names.add(
            normalize_name(
                member.global_name
            )
        )


    return names


# =========================================================
# BOT SETUP
# =========================================================

intents = discord.Intents.default()

intents.message_content = True

# Needed for guild-role member checking
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
# READY EVENT
# =========================================================

@bot.event
async def on_ready():

    print(
        f"Logged in as {bot.user}"
    )

    guild = discord.Object(
        id=SERVER_ID
    )

    # Copy global commands into this server
    # so changes appear almost immediately.
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
# DONATION STATUS COMMAND
# =========================================================

@bot.tree.command(
    name="donationstatus",
    description="See who donated and who has not donated today"
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


    # =====================================================
    # GET ROLE
    # =====================================================

    role_id = GUILD_ROLES.get(
        guild_name
    )


    if role_id is None:

        await interaction.followup.send(
            "❌ No role has been configured "
            "for this guild."
        )

        return


    discord_guild = interaction.guild


    if discord_guild is None:

        await interaction.followup.send(
            "❌ This command must be used "
            "inside the Discord server."
        )

        return


    role = discord_guild.get_role(
        role_id
    )


    if role is None:

        await interaction.followup.send(
            f"❌ I couldn't find the role for "
            f"**{guild_name}**.\n"
            "Check the role ID in the code."
        )

        return


    # =====================================================
    # GET MEMBERS WITH THE ROLE
    # =====================================================

    members = [

        member

        for member in role.members

        if not member.bot
    ]


    # =====================================================
    # GET TODAY'S DONATIONS
    # =====================================================

    donations = donated_today(
        guild_name
    )


    donation_lookup = {}


    for donation_ign, amount in donations:

        donation_lookup[
            normalize_name(
                donation_ign
            )
        ] = (
            donation_ign,
            amount
        )


    donated_members = []

    missing_members = []

    unmatched_donations = []

    matched_igns = set()


    # =====================================================
    # MATCH ROLE MEMBERS TO IGN
    # =====================================================

    for member in members:

        possible_names = get_member_names(
            member
        )

        found = None


        for name in possible_names:

            if name in donation_lookup:

                found = donation_lookup[
                    name
                ]

                break


        if found:

            donation_ign, amount = found


            donated_members.append(
                (
                    member,
                    donation_ign,
                    amount
                )
            )


            matched_igns.add(
                normalize_name(
                    donation_ign
                )
            )


        else:

            missing_members.append(
                member
            )


    # =====================================================
    # UNMATCHED IGNS
    # =====================================================

    for normalized_ign, data in donation_lookup.items():

        if normalized_ign not in matched_igns:

            unmatched_donations.append(
                data
            )


    # =====================================================
    # STATUS EMBED
    # =====================================================

    current_timestamp = get_timestamp()


    embed = discord.Embed(
        title=(
            f"📊 {guild_name} "
            f"Donation Status"
        ),
        description=(
            "Today's guild donation status\n"
            f"Checked: <t:{current_timestamp}:F>"
        ),
        color=discord.Color.blue()
    )


    embed.add_field(
        name="👥 Guild Members",
        value=str(
            len(members)
        ),
        inline=True
    )


    embed.add_field(
        name="✅ Donated",
        value=str(
            len(donated_members)
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
    # DONATED LIST
    # =====================================================

    if donated_members:

        donated_text = ""


        for member, ign, amount in donated_members:

            line = (
                f"✅ **{ign}** — "
                f"{amount:,}\n"
            )


            if (
                len(donated_text)
                + len(line)
                > 1000
            ):

                donated_text += (
                    "\n*More donors not shown...*"
                )

                break


            donated_text += line


        embed.add_field(
            name="✅ Donated Today",
            value=donated_text,
            inline=False
        )


    else:

        embed.add_field(
            name="✅ Donated Today",
            value=(
                "Nobody has been matched yet."
            ),
            inline=False
        )


    # =====================================================
    # MISSING LIST
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
                    "\n*More members "
                    "not shown...*"
                )

                break


            missing_text += line


        embed.add_field(
            name="❌ Not Donated Today",
            value=missing_text,
            inline=False
        )


    else:

        embed.add_field(
            name="❌ Not Donated Today",
            value=(
                "🎉 Everyone has donated!"
            ),
            inline=False
        )


    # =====================================================
    # UNMATCHED DONATIONS
    # =====================================================

    if unmatched_donations:

        unmatched_text = ""


        for ign, amount in unmatched_donations:

            line = (
                f"⚠️ **{ign}** — "
                f"{amount:,}\n"
            )


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
                "\nThese players donated, "
                "but their IGN does not match "
                "their Discord display name "
                "or username."
            ),
            inline=False
        )


    embed.set_footer(
        text=(
            "Daily donation status resets "
            "at 00:00 UTC"
        )
    )


    await interaction.followup.send(
        embed=embed
    )


# =========================================================
# LEADERBOARD COMMAND
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
                f"{rank} "
                f"**{ign}** — "
                f"{amount:,}\n"
            )


        embed.description = text


    current_timestamp = get_timestamp()


    embed.add_field(
        name="Updated",
        value=(
            f"<t:{current_timestamp}:F>\n"
            f"<t:{current_timestamp}:R>"
        ),
        inline=False
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


    # Ignore messages sent by bots
    if message.author.bot:

        return


    # Only monitor the 9 donation channels
    if message.channel.id not in GUILD_CHANNELS:

        return


    text = message.content


    # =====================================================
    # READ DONATION FORMAT
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


    # Not a donation log
    if (
        not ign_match
        or not donation_match
    ):

        return


    # =====================================================
    # GET VALUES
    # =====================================================

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


    # Ignore invalid amounts
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
    # SAVE DONATION
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


    print(
        f"Donation logged: "
        f"{guild_name} | "
        f"{ign} | "
        f"{donation_amount}"
    )


    # =====================================================
    # GET TRACKER CHANNEL
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
                f"Could not find "
                f"tracker channel: {e}"
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
        name="Daily Donation",
        value=(
            f"**{donation_text}**\n"
            f"`{donation_amount:,}`"
        ),
        inline=False
    )


    embed.add_field(
        name="Logged By",
        value=message.author.mention,
        inline=True
    )


    # Discord automatically converts this
    # into each person's local timezone.
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
            "Time automatically displays "
            "in your local timezone"
        )
    )


    await tracker.send(
        embed=embed
    )


# =========================================================
# START BOT
# =========================================================

if not TOKEN:

    raise RuntimeError(
        "TOKEN was not found. "
        "Check your Railway environment variables."
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
