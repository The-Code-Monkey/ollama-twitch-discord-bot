import json
import time
import asyncio
import aiohttp
import discord
from discord.ext import commands as discord_commands
from twitchio.ext import commands as twitch_commands

# --- CONFIGURATION ---
DISCORD_TOKEN = "YOUR_DISCORD_BOT_TOKEN"
TWITCH_TOKEN = "oauth:YOUR_TWITCH_ACCESS_TOKEN"
TWITCH_CHANNEL = "YOUR_TWITCH_CHANNEL_NAME"
BOT_PREFIX = "!"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5:7b"

# Global tracking for timeouts: {(platform, command_name): last_used_timestamp}
COOLDOWN_TRACKER = {}

def load_command_config(command_name: str) -> dict:
    """Reads only the requested command object from the JSON file."""
    try:
        with open("commands.json", "r") as f:
            data = json.load(f)
            return data.get(command_name.lower())
    except (FileNotFoundError, json.JSONDecodeError):
        print("Error reading or parsing commands.json")
        return None

def check_cooldown(platform: str, command_name: str, timeout_seconds: int) -> bool:
    """Returns True if the command is off cooldown and can be used."""
    key = (platform, command_name.lower())
    current_time = time.time()
    
    if key in COOLDOWN_TRACKER:
        elapsed = current_time - COOLDOWN_TRACKER[key]
        if elapsed < timeout_seconds:
            return False  # Still on cooldown
            
    COOLDOWN_TRACKER[key] = current_time
    return True

async def ask_isolated_qwen(username: str, user_prompt: str, required_info: list) -> str:
    """
    Sends ONLY the user text, username, and required variables to the AI.
    """
    instructions = (
        f"You are a helpful chat bot. You are talking to a user named '{username}'. "
        f"Please address them by their name or tag them naturally in your response.\n\n"
        "CRITICAL RULE: You MUST accurately include the following pieces of information "
        f"somewhere in your response text: {', '.join(required_info)}\n\n"
        f"User request: {user_prompt}"
    )
    
    payload = {
        "model": MODEL_NAME,
        "prompt": instructions,
        "stream": False
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_URL, json=payload) as response:
                if response.status == 200:
                    res_json = await response.json()
                    return res_json.get("response", "").strip()
                return "AI engine error."
    except Exception:
        return "Local AI connection timed out."
      

# --- DISCORD BOT ---
intents = discord.Intents.default()
intents.message_content = True
discord_bot = discord_commands.Bot(command_prefix=BOT_PREFIX, intents=intents)

@discord_bot.event
async def on_ready():
    print(f"Discord Bot online as {discord_bot.user.name}")

@discord_bot.event
async def on_message(message):
    if message.author == discord_bot.user or not message.content.startswith(BOT_PREFIX):
        return
    
    # Extract command token
    parts = message.content[len(BOT_PREFIX):].strip().split(" ", 1)
    cmd_name = parts[0].lower()
    user_args = parts[1] if len(parts) > 1 else ""
    
    config = load_command_config(cmd_name)
    if not config:
        return  # Command not found in commands.json
    
    # Enforce Cooldown
    if not check_cooldown("discord", cmd_name, config.get("timeout", 0)):
        return  # Silently ignore if on cooldown
        
    # Note: Checking Twitch Sub status inside Discord requires complex linking. 
    # For security and simplicity, we bypass 'isSub' constraints on Discord, or you can restrict it to a specific Discord Role if desired.
    
    # Process with isolated prompt
    response = await ask_isolated_qwen(user_args or cmd_name, config.get("required", []))
    if response:
        await message.channel.send(response)

# --- TWITCH BOT ---
class TwitchBot(twitch_commands.Bot):
    def __init__(self):
        super().__init__(token=TWITCH_TOKEN, prefix=BOT_PREFIX, initial_channels=[TWITCH_CHANNEL])

    async def event_ready(self):
        print(f"Twitch Bot online as {self.nick}")

    async def event_message(self, message):
        if message.echo or not message.content.startswith(BOT_PREFIX):
            return
            
        parts = message.content[len(BOT_PREFIX):].strip().split(" ", 1)
        cmd_name = parts[0].lower()
        user_args = parts[1] if len(parts) > 1 else ""
        
        config = load_command_config(cmd_name)
        if not config:
            return
            
        # Check Twitch Subscription constraint
        if config.get("isSub", False):
            # Check if user is a subscriber or the broadcaster
            if not (message.author.is_subscriber or message.author.is_mod or 'badges' in message.tags and 'broadcaster' in message.tags['badges']):
                await message.channel.send(f"@{message.author.name}, that command is reserved for channel subscribers!")
                return

        # Enforce Cooldown
        if not check_cooldown("twitch", cmd_name, config.get("timeout", 0)):
            return 
            
        response = await ask_isolated_qwen(user_args or cmd_name, config.get("required", []))
        if response:
            await message.channel.send(f"@{message.author.name} {response}")

twitch_bot = TwitchBot()

# --- RUN LOOP ---
async def main():
    await asyncio.gather(
        discord_bot.start(DISCORD_TOKEN),
        twitch_bot.start()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down safely.")
      
