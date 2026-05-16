import json
import time
import asyncio
import aiohttp
import discord
from collections import defaultdict
from discord.ext import commands as discord_commands
from twitchio.ext import commands as twitch_commands

# --- CONFIGURATION ---
DISCORD_TOKEN = "YOUR_DISCORD_BOT_TOKEN"
TWITCH_TOKEN = "oauth:YOUR_TWITCH_ACCESS_TOKEN"
TWITCH_CHANNEL = "YOUR_TWITCH_CHANNEL_NAME"
BOT_PREFIX = "!"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5:7b"

COOLDOWN_TRACKER = {}
TWITCH_HISTORY_CACHE = defaultdict(list)
MAX_TWITCH_HISTORY = 5

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
    
    parts = message.content[len(BOT_PREFIX):].strip().split(" ", 1)
    cmd_name = parts[0].lower()
    user_args = parts[1] if len(parts) > 1 else ""
    
    config = load_command_config(cmd_name)
    if not config:
        return
    
    if not check_cooldown("discord", cmd_name, config.get("timeout", 0)):
        return  
        
    # Get Discord display name (e.g., "JohnDoe")
    username = message.author.display_name
    
    response = await ask_isolated_qwen(username, user_args or cmd_name, config.get("required", []))
    
    if response:
        # If the AI forgot to include the username, we can enforce a mention at the start
        if username not in response and message.author.name wilderness not in response:
            await message.channel.send(f"{message.author.mention} {response}")
        else:
            await message.channel.send(response)

# --- TWITCH BOT ---
class TwitchBot(twitch_commands.Bot):
    def __init__(self):
        super().__init__(token=TWITCH_TOKEN, prefix=BOT_PREFIX, initial_channels=[TWITCH_CHANNEL])

    async def event_ready(self):
        print(f"Twitch Bot online as {self.nick}")
        
        # Connect to Twitch WebSockets EventSub for tracking followers
        try:
            # Dynamically fetch the Broadcaster ID needed for EventSub registration
            users = await self.fetch_users(names=[TWITCH_CHANNEL])
            if users:
                broadcaster_id = users[0].id
                # Subscribe to channel follow events
                await self.subscribe_eventsub_channel_follows(broadcaster_id=broadcaster_id)
                print(f"Successfully subscribed to Follow Events for channel: {TWITCH_CHANNEL}")
        except Exception as e:
            print(f"Failed to initialize Twitch Follow EventSub: {e}")

    # TRIGGERED WHEN A NEW USER FOLLOWS
    async def event_eventsub_notification_channel_follow(self, event):
        new_follower = event.user.name
        display_name = f"@{new_follower}"
        
        print(f"New Follower Detected: {new_follower}")
        
        # Pull any memory data if they chatted prior to hitting follow
        user_history = TWITCH_HISTORY_CACHE.get(new_follower, [])
        
        # Ask Qwen engine to construct a dedicated welcome string
        welcome_response = await ask_isolated_qwen(
            username=display_name, 
            user_prompt="", 
            required_info=[], 
            history=user_history, 
            is_welcome=True
        )
        
        if welcome_response:
            channel = self.get_channel(TWITCH_CHANNEL)
            if channel:
                # Ensure the user is properly highlighted in chat
                if display_name not in welcome_response:
                    await channel.send(f"{display_name} {welcome_response}")
                else:
                    await channel.send(welcome_response)

    async def event_message(self, message):
        if message.echo:
            return
            
        raw_name = message.author.name
        if not message.content.startswith(BOT_PREFIX):
            TWITCH_HISTORY_CACHE[raw_name].append(f"{raw_name}: {message.content}")
            if len(TWITCH_HISTORY_CACHE[raw_name]) > MAX_TWITCH_HISTORY:
                TWITCH_HISTORY_CACHE[raw_name].pop(0)
            return 
            
        parts = message.content[len(BOT_PREFIX):].strip().split(" ", 1)
        cmd_name = parts[0].lower()
        user_args = parts[1] if len(parts) > 1 else ""
        
        config = load_command_config(cmd_name)
        if not config:
            return
            
        if config.get("isSub", False):
            if not (message.author.is_subscriber or message.author.is_mod or 'badges' in message.tags and 'broadcaster' in message.tags['badges']):
                await message.channel.send(f"@{raw_name}, that command is reserved for channel subscribers!")
                return

        if not check_cooldown("twitch", cmd_name, config.get("timeout", 0)):
            return 
            
        username = f"@{raw_name}"
        user_history = TWITCH_HISTORY_CACHE.get(raw_name, [])
        
        response = await ask_isolated_qwen(username, user_args or cmd_name, config.get("required", []), history=user_history)
        
        if response:
            if username not in response:
                await message.channel.send(f"{username} {response}")
            else:
                await message.channel.send(response)
                

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
      
