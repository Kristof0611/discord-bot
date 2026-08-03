import discord
from discord.ext import commands
from dotenv import load_dotenv

import os
import sqlite3
import re
from datetime import datetime


# =========================
# CONFIG
# =========================

load_dotenv()

TOKEN = os.getenv("TOKEN")


# PUT YOUR CHANNEL IDS HERE
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


# PUT TRACKER CHANNEL ID HERE
TRACKER_CHANNEL_ID = 1532339634829267149


# =========================
# DATABASE
# =========================

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
    time TEXT
)
""")

db.commit()


def save_donation(
    guild,
    ign,
    previous,
    current,
    donation,
    logged_by,
    time
):

    cursor.execute("""
    INSERT INTO donations
    (
        guild,
        ign,
        previous_gold,
        current_gold,
        donation,
        logged_by,
        time
    )
    VALUES (?,?,?,?,?,?,?)
    """,
    (
        guild,
        ign,
        previous,
        current,
        donation,
        logged_by,
        time
    ))

    db.commit()



# =========================
# NUMBER CONVERTER
# =========================

def convert_amount(value):

    value = value.upper().replace(",", "")

    try:

        if "M" in value:
            return int(float(value.replace("M","")) * 1000000)

        if "K" in value:
            return int(float(value.replace("K","")) * 1000)

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
    print(f"Logged in as {bot.user}")

    bot.tree.clear_commands(guild=None)

    await bot.tree.sync()

    print("Old commands cleared and new commands synced")



# =========================
# MESSAGE READER
# =========================


@bot.event
async def on_message(message):

    await bot.process_commands(message)


    # ignore bots
    if message.author.bot:
        return


    # only watch guild channels
    if message.channel.id not in GUILD_CHANNELS:
        return


    text = message.content


    # find values

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


    # if not a donation log
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

    donation_number = convert_amount(
        donation_text
    )


    guild_name = GUILD_CHANNELS[
        message.channel.id
    ]


    time = datetime.now().strftime(
        "%d/%m/%Y %I:%M %p"
    )


    save_donation(
        guild_name,
        ign,
        previous,
        current,
        donation_number,
        message.author.display_name,
        time
    )



    # SEND TRACKER MESSAGE

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
            value=f"{donation_text} ({donation_number:,})",
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
# START
# =========================

bot.run(TOKEN)
