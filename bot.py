import os
import sqlite3
import discord
from dotenv import load_dotenv
from discord.ext import commands
from discord import app_commands

# Load token
load_dotenv()
TOKEN = os.getenv("TOKEN")

# Database
conn = sqlite3.connect("points.db")
c = conn.cursor()
c.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0)")
conn.commit()

def ensure(i):
    c.execute("INSERT OR IGNORE INTO users(id, points) VALUES(?, 0)", (i,))
    conn.commit()

def pts(i):
    ensure(i)
    return c.execute("SELECT points FROM users WHERE id=?", (i,)).fetchone()[0]

def add(i, a):
    ensure(i)
    c.execute("UPDATE users SET points = points + ? WHERE id=?", (a, i))
    conn.commit()

# ---------------- FIX #1: INTENTS ----------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------- FIX #2: SYNC PROPERLY ----------------
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")
    print("Slash commands synced")

# ---------------- COMMANDS ----------------

@bot.tree.command(name="points", description="Check a user's points")
async def points(interaction: discord.Interaction, user: discord.Member = None):

    # If no user is mentioned, check yourself
    if user is None:
        user = interaction.user

    total = pts(user.id)

    await interaction.response.send_message(
        f"💰 {user.mention} has **{total} points**."
    )
@bot.tree.command(name="leaderboard", description="Top users")
async def leaderboard(interaction: discord.Interaction):
    rows = c.execute("SELECT id, points FROM users ORDER BY points DESC LIMIT 10").fetchall()

    txt = ""
    for n, (uid, p) in enumerate(rows, 1):
        try:
            user = await bot.fetch_user(uid)
            txt += f"{n}. {user.name}: {p}\n"
        except:
            txt += f"{n}. Unknown User ({uid}): {p}\n"

    await interaction.response.send_message(txt or "No data yet")

@bot.tree.command(name="givepoints", description="Admin gives points")
@app_commands.checks.has_permissions(administrator=True)
async def givepoints(
    interaction: discord.Interaction,
    user: discord.Member,
    amount: int,
    reason: str
):

    add(user.id, amount)
    new_total = pts(user.id)

    await interaction.response.send_message(
        f"✅ Added **{amount} points** to {user.mention}\n📌 Reason: {reason}"
    )

    try:
        await user.send(
            f"🎉 **Points Awarded!**\n"
            f"You have been awarded **{amount} training points** by **{interaction.user.name}**.\n"
            f"📌 Reason: {reason}\n"
            f"💰 New Total: {new_total}"
        )
    except:
        await interaction.followup.send("⚠️ Could not DM user.", ephemeral=True)
@bot.tree.command(name="removepoints", description="Admin removes points")
@app_commands.checks.has_permissions(administrator=True)
async def removepoints(
    interaction: discord.Interaction,
    user: discord.Member,
    amount: int,
    reason: str
):

    add(user.id, -amount)
    new_total = pts(user.id)

    await interaction.response.send_message(
        f"⚠️ Removed **{amount} points** from {user.mention}\n📌 Reason: {reason}"
    )

    try:
        await user.send(
            f"⚠️ **Points Removed**\n"
            f"**{amount} training points** were removed by **{interaction.user.name}**.\n"
            f"📌 Reason: {reason}\n"
            f"💰 New Total: {new_total}"
        )
    except:
        await interaction.followup.send("⚠️ Could not DM user.", ephemeral=True)
# ---------------- FIX #3: TOKEN SAFETY ----------------
bot.run(TOKEN)