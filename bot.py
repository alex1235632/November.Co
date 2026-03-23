import discord
from discord.ext import commands
import os
import time
import sqlite3
import random

TOKEN = os.getenv("TOKEN")

WELCOME_CHANNEL_ID = 1483516724111347712
GOODBYE_CHANNEL_ID = 1483516724111347712
LOG_CHANNEL_ID = 1483516938423505220
APPLICATION_ID = 1483518969125011586

# ================= DATABASE =================
db = sqlite3.connect("bot.db", check_same_thread=False)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    xp INTEGER DEFAULT 0,
    level INTEGER DEFAULT 1,
    voice_time INTEGER DEFAULT 0,
    coins INTEGER DEFAULT 0
)
""")
db.commit()

# ================= INTENTS =================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents, application_id=APPLICATION_ID)

voice_sessions = {}
message_cooldown = {}
daily_cooldown = {}

# ================= HELPERS =================
def ensure_user(user_id):
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    db.commit()

def add_coins(user_id, amount):
    ensure_user(user_id)
    cursor.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
    coins = cursor.fetchone()[0]
    coins = max(0, coins + amount)
    cursor.execute("UPDATE users SET coins = ? WHERE user_id = ?", (coins, user_id))
    db.commit()

async def add_xp(user_id, amount):
    ensure_user(user_id)
    cursor.execute("SELECT xp, level FROM users WHERE user_id = ?", (user_id,))
    xp, level = cursor.fetchone()

    xp += amount
    needed = level * 100
    leveled = False

    while xp >= needed:
        xp -= needed
        level += 1
        needed = level * 100
        leveled = True

    cursor.execute("UPDATE users SET xp = ?, level = ? WHERE user_id = ?", (xp, level, user_id))
    db.commit()

    if leveled:
        channel = bot.get_channel(LOG_CHANNEL_ID)
        user = bot.get_user(user_id)
        if channel and user:
            await channel.send(f"🎉 LEVEL UP!\n👤 {user.mention}\n⭐ Level {level}")

# ================= EVENTS =================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    now = time.time()
    last = message_cooldown.get(message.author.id, 0)

    if now - last >= 30:
        await add_xp(message.author.id, 5)
        add_coins(message.author.id, 3)
        message_cooldown[message.author.id] = now

    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    log = bot.get_channel(LOG_CHANNEL_ID)
    now = time.time()

    if before.channel is None and after.channel is not None:
        voice_sessions[member.id] = now
        if log:
            await log.send(f"🔊 joined voice\n👤 {member.mention}\n🎧 {after.channel.name}")

    if before.channel and after.channel is None:
        start = voice_sessions.pop(member.id, None)
        if not start:
            return

        duration = int(now - start)
        minutes = duration // 60

        if minutes > 0:
            await add_xp(member.id, minutes * 10)
            add_coins(member.id, minutes * 5)

        cursor.execute("UPDATE users SET voice_time = voice_time + ? WHERE user_id = ?",
                       (duration, member.id))
        db.commit()

        h = duration // 3600
        m = (duration % 3600) // 60
        s = duration % 60

        if log:
            await log.send(f"🔇 left voice\n👤 {member.mention}\n⏱️ {h}h {m}m {s}s")

@bot.event
async def on_member_join(member):
    ch = bot.get_channel(WELCOME_CHANNEL_ID)
    if ch:
        await ch.send(f"🎉 Welcome {member.mention}!",
                      file=discord.File("images/welcome.png"))

@bot.event
async def on_member_remove(member):
    ch = bot.get_channel(GOODBYE_CHANNEL_ID)
    if ch:
        await ch.send(f"👋 {member.name} left the server",
                      file=discord.File("images/goodbye.png"))

@bot.event
async def on_member_update(before, after):
    log = bot.get_channel(LOG_CHANNEL_ID)
    if not log:
        return

    for role in set(after.roles) - set(before.roles):
        if not role.is_default():
            await log.send(f"✅ added role\n👤 {after.mention}\n🎭 {role.name}")

    for role in set(before.roles) - set(after.roles):
        if not role.is_default():
            await log.send(f"❌ removed role\n👤 {after.mention}\n🎭 {role.name}")

# ================= SLASH COMMANDS =================

@bot.tree.command(name="profile")
async def profile(interaction: discord.Interaction):
    ensure_user(interaction.user.id)
    cursor.execute("SELECT xp, level, voice_time, coins FROM users WHERE user_id = ?",
                   (interaction.user.id,))
    xp, level, voice, coins = cursor.fetchone()

    needed = level * 100
    progress = int((xp / needed) * 20)
    bar = "🟩" * progress + "⬛" * (20 - progress)

    h = voice // 3600
    m = (voice % 3600) // 60
    s = voice % 60

    await interaction.response.send_message(
        f"👤 {interaction.user.mention}\n"
        f"⭐ Level: {level}\n"
        f"📊 XP: {xp}/{needed}\n"
        f"{bar}\n"
        f"🎙️ Voice: {h}h {m}m {s}s\n"
        f"💰 Coins: {coins}"
    )

@bot.tree.command(name="voicetop")
async def voicetop(interaction: discord.Interaction):
    cursor.execute("SELECT user_id, voice_time FROM users ORDER BY voice_time DESC LIMIT 10")
    rows = cursor.fetchall()

    text = "🏆 Voice Leaderboard\n\n"
    for i, (uid, seconds) in enumerate(rows, start=1):
        member = interaction.guild.get_member(uid)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        name = member.name if member else f"User {uid}"
        text += f"{i}. {name} — {hours}h {minutes}m\n"

    await interaction.response.send_message(text)

@bot.tree.command(name="balance")
async def balance(interaction: discord.Interaction):
    ensure_user(interaction.user.id)
    cursor.execute("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,))
    coins = cursor.fetchone()[0]
    await interaction.response.send_message(f"💰 {coins} coins")

@bot.tree.command(name="add", description="Add xp, coins, or levels (Admin only)")
async def add(
    interaction: discord.Interaction,
    user: discord.Member,
    type: str,
    amount: int
):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ No permission.", ephemeral=True)
        return

    type = type.lower()

    if type == "xp":
        await add_xp(user.id, amount)
        await interaction.response.send_message(f"✅ Added {amount} XP to {user.mention}")

    elif type == "coins":
        add_coins(user.id, amount)
        await interaction.response.send_message(f"💰 Added {amount} coins to {user.mention}")

    elif type == "level":
        ensure_user(user.id)
        cursor.execute("SELECT level FROM users WHERE user_id = ?", (user.id,))
        level = cursor.fetchone()[0]
        level += amount
        if level < 1:
            level = 1
        cursor.execute("UPDATE users SET level = ?, xp = 0 WHERE user_id = ?", (level, user.id))
        db.commit()
        await interaction.response.send_message(f"⭐ {user.mention} is now level {level}")

    else:
        await interaction.response.send_message("Type must be xp, coins, or level.", ephemeral=True)


@bot.tree.command(name="remove", description="Remove xp, coins, or levels (Admin only)")
async def remove(
    interaction: discord.Interaction,
    user: discord.Member,
    type: str,
    amount: int
):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ No permission.", ephemeral=True)
        return

    type = type.lower()

    if type == "xp":
        ensure_user(user.id)
        cursor.execute("SELECT xp FROM users WHERE user_id = ?", (user.id,))
        xp = cursor.fetchone()[0]
        xp = max(0, xp - amount)
        cursor.execute("UPDATE users SET xp = ? WHERE user_id = ?", (xp, user.id))
        db.commit()
        await interaction.response.send_message(f"❌ Removed {amount} XP from {user.mention}")

    elif type == "coins":
        add_coins(user.id, -amount)
        await interaction.response.send_message(f"💰 Removed {amount} coins from {user.mention}")

    elif type == "level":
        ensure_user(user.id)
        cursor.execute("SELECT level FROM users WHERE user_id = ?", (user.id,))
        level = cursor.fetchone()[0]
        level -= amount
        if level < 1:
            level = 1
        cursor.execute("UPDATE users SET level = ?, xp = 0 WHERE user_id = ?", (level, user.id))
        db.commit()
        await interaction.response.send_message(f"⭐ {user.mention} is now level {level}")

    else:
        await interaction.response.send_message("Type must be xp, coins, or level.", ephemeral=True)

@bot.tree.command(name="gamble")
async def gamble(interaction: discord.Interaction, amount: int):
    ensure_user(interaction.user.id)
    cursor.execute("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,))
    coins = cursor.fetchone()[0]

    if amount <= 0 or amount > coins:
        await interaction.response.send_message("Invalid amount.", ephemeral=True)
        return

    if random.randint(1, 4) == 1:
        add_coins(interaction.user.id, amount)
        await interaction.response.send_message(f"🎉 You won {amount} coins! (25%)")
    else:
        add_coins(interaction.user.id, -amount)
        await interaction.response.send_message(f"💀 You lost {amount} coins.")

@bot.tree.command(name="jl5")
async def jl5(interaction: discord.Interaction):
    art = """⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣠⣤⣤⣤⣄⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣴⣿⣿⣿⣿⣿⣿⣿⣷⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⣿⣿⣿⣿⣿⣿⣿⣿⣿⣧⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⢿⣿⣿⣿⣿⣿⣿⣿⡿⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠻⠿⠿⠿⠟⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣴⣶⣿⣿⣶⣄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢰⣿⣿⣿⣿⣿⣿⣿⣷⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣿⣿⣿⣿⣿⣿⣿⣿⣿⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣼⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⢠⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⣸⣿⣿⣿⣿⣿⣿⣿⣿⡟⣿⣿⣿⣿⣧⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣤⣶⣾⣿⣶⣶⣤⡀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⢠⣿⣿⣿⣿⣿⣿⣿⣿⡿⠀⠘⢿⣿⣿⣿⣷⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣴⣿⣿⣿⣿⣿⣿⣿⣿⣿⡄⠀
⠀⠀⠀⠀⠀⠀⠀⣼⣿⣿⣿⣿⣿⣿⣿⣿⠇⠀⠀⠈⠻⣿⣿⣿⣿⣆⠀⠀⠀⠀⠀⠀⠀⠀⢰⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠀
⠀⠀⠀⠀⠀⠀⠀⣿⣿⣿⣿⣿⣿⣿⣿⡟⠀⣀⣤⣶⣶⣌⠻⣿⣿⣿⣷⡀⠀⠀⠀⠀⠀⠀⣸⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡟⠀
⠀⠀⠀⠀⠀⠀⠀⠹⣿⣿⣿⣿⣿⣿⣿⠁⣰⣿⣿⣿⣿⣿⣦⡙⢿⣿⣿⣿⠄⠀⠀⠀⠀⠀⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⠟⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⢿⣿⣿⣿⣿⣿⣿⠀⣿⣿⣿⣿⣿⣿⣿⣿⣦⣙⣛⣋⣼⣿⣿⣶⣿⣿⣿⣿⣿⣿⣯⡉⠉⠉⠁⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⢸⣿⣿⣿⣿⣿⣿⠀⢸⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡇⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠈⣿⣿⣿⣿⣿⣿⡆⠀⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡇⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⣿⣿⣿⣿⣿⡇⠀⢻⣿⣿⣿⣿⣿⡇⠀⠀⠈⠉⠉⢻⣿⣿⣿⣿⣿⣿⣿⣿⣿⠁⠀⠀⠀⠀⠀⠀⠀
⠀⣠⣴⣶⣶⣶⣶⣶⣶⣾⣿⣿⣿⣿⣿⡇⠀⠸⣿⣿⣿⣿⣿⡇⠀⠀⠀⠀⠀⠀⠹⢿⣿⣿⢿⣿⣿⣿⡿⠀⠀⠀⠀⠀⠀⠀⠀
⢸⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡇⢰⣶⣿⣿⣿⣿⣿⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⣿⣿⣿⣧⣄⣀⣀⣀⣀⣀⣀⡀
⠸⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡇⢸⣿⣿⣿⣿⣿⣿⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣼⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿
⠀⠀⠉⠉⠙⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠁⠛⠛⠛⠛⠛⠛⠛⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠉⠉⠉⠉⠉⠉⠉⠉⠉⠉⠉⠁"""
    await interaction.response.send_message(f"```{art}```")

bot.run("MTQ4MzUxODk2OTEyNTAxMTU4Ng.GUp116.9QZkUZIihDQuuLSfTS757b9LMwdtpC5FQQCvyE")
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

@bot.command()
async def join(ctx):
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        await channel.connect()
        await ctx.send(f"Joined {channel}")
    else:
        await ctx.send("You are not in a voice channel!")

@bot.command()
async def leave(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("Disconnected")
    else:
        await ctx.send("I am not in a voice channel")

bot.run("MTQ4MzUxODk2OTEyNTAxMTU4Ng.GUp116.9QZkUZIihDQuuLSfTS757b9LMwdtpC5FQQCvyE")
