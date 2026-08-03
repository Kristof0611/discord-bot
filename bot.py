import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

import os
import sqlite3
import re
from datetime import datetime, date


# =========================
# CONFIG
# =========================

load_dotenv()

TOKEN = os.getenv("TOKEN")


# YOUR GUILD DONATION CHANNELS
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


# TRACKER CHANNEL
TRACKER_CHANNEL_ID = 1532339634829267149



# =========================
# DATABASE
# =========================

db = sqlite3.connect("donations.db")

cursor = db.cursor()


# Donation history

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


# Guild member roster

cursor.execute("""
CREATE TABLE IF NOT EXISTS members (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    guild TEXT,

    ign TEXT

)
""")


db.commit()



# =========================
# DATABASE FUNCTIONS
# =========================


def save_donation(
    guild,
    ign,
    previous,
    current,
    donation,
    logged_by,
    time
):

    today = str(date.today())


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
        time,
        today
    ))


    db.commit()



def add_member(guild, ign):

    cursor.execute("""
    INSERT INTO members
    (
        guild,
        ign
    )

    VALUES (?,?)

    """,
    (
        guild,
        ign
    ))


    db.commit()



def remove_member(guild, ign):

    cursor.execute("""
    DELETE FROM members
    WHERE guild=? AND ign=?

    """,
    (
        guild,
        ign
    ))


    db.commit()



def get_members(guild):

    cursor.execute("""
    SELECT ign
    FROM members
    WHERE guild=?

    """,
    (guild,))


    return [
        x[0]
        for x in cursor.fetchall()
    ]



def donated_today(guild):

    today = str(date.today())


    cursor.execute("""
    SELECT ign, donation
    FROM donations
    WHERE guild=? AND day=?

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

    GROUP BY ign

    ORDER BY SUM(donation) DESC

    LIMIT 10

    """,
    (guild,))


    return cursor.fetchall()
    # =========================
# NUMBER CONVERTER
# =========================

def convert_amount(value):

    value = value.upper().replace(",", "")

    try:

        if "M" in value:
            return int(float(value.replace("M", "")) * 1000000)

        if "K" in value:
            return int(float(value.replace("K", "")) * 1000)

        return int(value)

    except:
        return 0



# =========================
# BOT SETUP
# =========================

intents = discord.Intents.default()

intents.message_content = True


bot = commands.Bot(
    command_prefix="!",
    intents=intents
)



@bot.event
async def on_ready():

    print(
        f"Logged in as {bot.user}"
    )


    await bot.tree.sync()


    print(
        "Commands synced"
    )



# =========================
# ADD MEMBER COMMAND
# =========================


@bot.tree.command(
    name="addmember",
    description="Add a member to a guild roster"
)
@app_commands.describe(
    guild="Guild name",
    ign="Player IGN"
)
async def addmember(
    interaction: discord.Interaction,
    guild: str,
    ign: str
):

    add_member(
        guild,
        ign
    )


    await interaction.response.send_message(
        f"✅ Added **{ign}** to **{guild}** roster"
    )



# =========================
# REMOVE MEMBER COMMAND
# =========================


@bot.tree.command(
    name="removemember",
    description="Remove a member from roster"
)
@app_commands.describe(
    guild="Guild name",
    ign="Player IGN"
)
async def removemember(
    interaction: discord.Interaction,
    guild: str,
    ign: str
):

    remove_member(
        guild,
        ign
    )


    await interaction.response.send_message(
        f"🗑️ Removed **{ign}** from **{guild}**"
    )



# =========================
# DONATION STATUS
# =========================


@bot.tree.command(
    name="donationstatus",
    description="Show who donated and who did not"
)
@app_commands.describe(
    guild="Guild name"
)
async def donationstatus(
    interaction: discord.Interaction,
    guild: str
):


    members = get_members(guild)


    donated = donated_today(guild)


    donated_names = [
        x[0]
        for x in donated
    ]


    embed = discord.Embed(
        title=f"📊 {guild} Donation Status",
        color=discord.Color.blue()
    )


    yes = ""

    no = ""


    for member in members:

        if member in donated_names:

            amount = next(
                x[1]
                for x in donated
                if x[0] == member
            )

            yes += (
                f"✅ {member} "
                f"- {amount:,}\n"
            )

        else:

            no += (
                f"❌ {member}\n"
            )


    if yes:

        embed.add_field(
            name="Donated Today",
            value=yes,
            inline=False
        )


    if no:

        embed.add_field(
            name="Not Donated",
            value=no,
            inline=False
        )


    if not yes and not no:

        embed.description = (
            "No members found."
        )


    await interaction.response.send_message(
        embed=embed
    )



# =========================
# LEADERBOARD
# =========================


@bot.tree.command(
    name="leaderboard",
    description="Show donation leaderboard"
)
@app_commands.describe(
    guild="Guild name"
)
async def leaderboard(
    interaction: discord.Interaction,
    guild: str
):

    data = get_leaderboard(
        guild
    )


    embed = discord.Embed(
        title=f"🏆 {guild} Leaderboard",
        color=discord.Color.gold()
    )


    text = ""


    for index, row in enumerate(data, 1):

        text += (
            f"**{index}. {row[0]}** "
            f"- {row[1]:,}\n"
        )


    if text:

        embed.description = text

    else:

        embed.description = (
            "No donations recorded."
        )


    await interaction.response.send_message(
        embed=embed
    )
    # =========================
# AUTOMATIC DONATION READER
# =========================


@bot.event
async def on_message(message):

    await bot.process_commands(message)


    # ignore bots
    if message.author.bot:
        return


    # only watch donation channels
    if message.channel.id not in GUILD_CHANNELS:
        return


    text = message.content


    # FIND DATA

    ign = re.search(
        r"IGN:\s*(.+)",
        text
    )

    previous = re.search(
        r"Previous Guild Gold:\s*(.+)",
        text
    )

    current = re.search(
        r"Current Guild Gold:\s*(.+)",
        text
    )

    donation = re.search(
        r"Daily Donation:\s*(.+)",
        text
    )


    # ignore normal messages
    if not ign or not donation:
        return



    ign = ign.group(1).strip()


    previous = (
        previous.group(1).strip()
        if previous
        else "Unknown"
    )


    current = (
        current.group(1).strip()
        if current
        else "Unknown"
    )


    donation_text = donation.group(1).strip()


    donation_amount = convert_amount(
        donation_text
    )


    guild_name = GUILD_CHANNELS[
        message.channel.id
    ]


    time = datetime.now().strftime(
        "%d/%m/%Y %I:%M %p"
    )


    # SAVE DATA

    save_donation(
        guild_name,
        ign,
        previous,
        current,
        donation_amount,
        message.author.display_name,
        time
    )



    # SEND TO TRACKER CHANNEL

    tracker = bot.get_channel(
        TRACKER_CHANNEL_ID
    )


    if tracker:


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
            value=previous
        )


        embed.add_field(
            name="Current Gold",
            value=current
        )


        embed.add_field(
            name="Daily Donation",
            value=f"{donation_text} ({donation_amount:,})",
            inline=False
        )


        embed.add_field(
            name="Logged By",
            value=message.author.mention
        )


        embed.set_footer(
            text=time
        )


        await tracker.send(
            embed=embed
        )



# =========================
# START BOT
# =========================


bot.run(TOKEN)
