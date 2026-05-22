import os
import re
import json
import time
import asyncio
import aiohttp
from collections import defaultdict
from dotenv import load_dotenv

# Modern TwitchIO v3 imports
import twitchio
from twitchio.ext import commands as twitch_commands

# Load environment variables
load_dotenv()

TWITCH_SECRET = os.getenv("TWITCH_SECRET")
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CHANNEL = os.getenv("TWITCH_CHANNEL")
TWITCH_BOT_NUMERIC_ID = os.getenv("TWITCH_BOT_NUMERIC_ID")
TWITCH_REFRESH_TOKEN = os.getenv("TWITCH_REFRESH_TOKEN")
TWITCH_TOKEN = os.getenv("TWITCH_TOKEN")

BOT_PREFIX = "!"
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL_NAME = "qwen2.5:1.5b"

COOLDOWN_TRACKER = {}
TWITCH_HISTORY_CACHE = defaultdict(list)
MAX_TWITCH_HISTORY = 5

async def refresh_twitch_token():
    global TWITCH_TOKEN
    url = "https://id.twitch.tv/oauth2/token"
    payload = {
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": TWITCH_REFRESH_TOKEN
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    TWITCH_TOKEN = f"oauth:{data.get('access_token')}"
                    print("🔄 Twitch access token successfully rotated.")
    except Exception as e:
        print(f"❌ Failed to run token rotation loop: {e}")

def load_command_config(command_name: str) -> dict:
    try:
        with open("commands.json", "r") as f:
            return json.load(f).get(command_name.lower())
    except Exception:
        return None

def check_cooldown(platform: str, command_name: str, timeout_seconds: int) -> bool:
    key = (platform, command_name.lower())
    current_time = time.time()

    if key in COOLDOWN_TRACKER:
        elapsed_time = current_time - COOLDOWN_TRACKER[key]
        if elapsed_time < timeout_seconds:
            # Calculate exactly how much time is left
            remaining_time = timeout_seconds - elapsed_time
            print(f"⏳ [COOLDOWN] !{command_name} ignored. {int(remaining_time)} seconds remaining.")
            return False

    # If we pass the check, reset the timer to right now
    COOLDOWN_TRACKER[key] = current_time
    return True

async def ask_isolated_qwen(username: str, user_prompt: str, required_info: list, history: list = None) -> str:
    # 1. Prepare history section if it exists
    history_str = ""
    if history:
        # We limit the history passed to the AI to prevent context-bloat
        recent_history = "\n".join(history[-5:])
        history_str = f"USE THIS CHAT HISTORY MUST INCLUDE:\n{recent_history}\n\n"

    # Use a clear separator that the model recognizes as a task
    instructions = (
        f"Role: Stream Chat Bot. Keep response under 450 characters.\n"
        f"Constraints: NO questions. NO repeating user prompt. Include: {', '.join(required_info)}.\n"
        f"{history_str}\n"
        f"User: {username}\n"
        f"Input: {user_prompt}\n"
        f"Answer:"
    )

    print(f"--- AI PROMPT DEBUG ---\n{instructions}\n-----------------------")

    payload = {
        "model": "qwen2.5:1.5b",
        "prompt": instructions,
        "stream": False,
        "keep_alive": 0,
        "raw": False,
        "stop": ["User:", "Input:", "Answer:", "User request:", "\n\n"],
        "options": {
            "num_predict": 150, # Limits total tokens generated to keep it short
            "temperature": 0.7
        }
    }
    ollama_auto_started = False

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(OLLAMA_URL, json=payload, timeout=15) as response:
                    if response.status == 200:
                        result = (await response.json()).get("response", "").strip()

                        # --- NEW: LENGTH CHECK & SHORTENING LOOP ---
                        if len(result) > 500:
                            print(f"✂️ AI response was {len(result)} characters. Asking Qwen to condense...")
                            shorten_instructions = (
                                f"Take the following text and rewrite it to be strictly under 450 characters. "
                                f"Keep the core message and tone intact.\n\nOriginal text:\n{result}"
                            )
                            shorten_payload = {"model": MODEL_NAME, "prompt": shorten_instructions, "stream": False}

                            # Ask Ollama to shorten its own response
                            async with session.post(OLLAMA_URL, json=shorten_payload, timeout=15) as short_response:
                                if short_response.status == 200:
                                    result = (await short_response.json()).get("response", "").strip()

                            # Absolute fail-safe: if the AI STILL fails the assignment, chop it so Twitch doesn't drop it
                            if len(result) > 500:
                                print("⚠️ AI failed to shorten enough. Hard-truncating text.")
                                result = result[:450] + "..."
                        # ------------------------------------------

                        return result
                    return "AI engine error status code."
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError):
            if ollama_auto_started:
                return "Local AI connection timed out."
            print(f"⚠️ Ollama is offline. Attempting auto-start...")
            try:
                await asyncio.create_subprocess_exec(
                    "ollama", "run", MODEL_NAME,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
                )
                ollama_auto_started = True
                await asyncio.sleep(8)
                continue
            except Exception:
                return "Auto-start execution failed."

# --- CLEAN TWITCHIO V3 BOT ENGINE ---
class TwitchBot(twitch_commands.Bot):
    def __init__(self, token_string: str):
        self.raw_token = token_string
        super().__init__(
            client_id=TWITCH_CLIENT_ID,
            client_secret=TWITCH_SECRET,
            bot_id=TWITCH_BOT_NUMERIC_ID,
            owner_id=TWITCH_BOT_NUMERIC_ID,
            prefix=BOT_PREFIX
        )

    # We MUST have a setup_hook to tell Twitch to forward chat to our socket!
    async def setup_hook(self) -> None:
        print("📡 Registering live chat event subscriptions via WebSocket...")
        try:
            # 1. Add your token AND refresh token to the internal manager
            await self.add_token(token=self.raw_token, refresh=TWITCH_REFRESH_TOKEN)

            # 2. Build the chat subscription targeting your specific room
            chat_subscription = twitchio.eventsub.ChatMessageSubscription(
                broadcaster_user_id=TWITCH_BOT_NUMERIC_ID,
                user_id=TWITCH_BOT_NUMERIC_ID
            )

            # 3. Fire the subscription using your numeric ID to map to the token we just added
            await self.subscribe_websocket(payload=chat_subscription, token_for=TWITCH_BOT_NUMERIC_ID)
            print("✅ WebSocket chat stream successfully registered and listening!")
        except Exception as e:
            print(f"❌ EventSub configuration dropped: {e}")

    async def event_ready(self) -> None:
        print(f"🟢 Twitch Bot successfully logged in as: {self.user.name}")
        try:
            # Post a welcome confirmation message to your channel room container
            target_channel = self.create_partialuser(self.bot_id)
            await target_channel.send_message(
                sender=self.user,
                message="🤖 Local AI Bot online and listening! Configured via commands.json."
            )
            print("💬 Sent online confirmation message to Twitch chat room successfully!")
        except Exception as e:
            print(f"⚠️ Failed to transmit online notification: {e}")

    # --- NATIVE CHAT MESSAGE EVENT ---
    # In TwitchIO v3, the default routing endpoint for messages is event_message
    async def event_message(self, message: twitchio.ChatMessage) -> None:
        raw_name = message.chatter.name
        username = f"@{raw_name}"
        chat_content = message.text.strip()

        # Print all chat text directly to terminal to ensure it works live
        print(f"📥 [CHAT] {raw_name}: {chat_content}")

        # Scenario A: Regular message (No prefix matching "!")
        if not chat_content.startswith(BOT_PREFIX):
              # Only track other users' chat
              TWITCH_HISTORY_CACHE[raw_name].append(f"{raw_name}: {chat_content}")
              if len(TWITCH_HISTORY_CACHE[raw_name]) > MAX_TWITCH_HISTORY:
                TWITCH_HISTORY_CACHE[raw_name].pop(0)

        # Scenario B: Command extraction
        parts = chat_content[len(BOT_PREFIX):].split(" ", 1)
        cmd_name = parts[0].lower()
        user_args = parts[1] if len(parts) > 1 else ""

        config = load_command_config(cmd_name)
        if not config:
            return

        # 1. Enforce Subscription Gate
        if config.get("isSub", False):
            is_broadcaster = (raw_name.lower() == TWITCH_CHANNEL.lower())
            if not (message.chatter.subscriber or message.chatter.is_moderator or is_broadcaster):
                try:
                    target = self.create_partialuser(message.broadcaster.id)
                    await target.send_message(sender=self.user, message=f"{username}, that command is for subscribers!")
                except Exception as e:
                    print(f"⚠️ Failed to send sub alert: {e}")
                return

        # 2. Enforce Cooldown Manager
        if not check_cooldown("twitch", cmd_name, config.get("timeout", 5) * 60):
            return

        print(f"🚀 Processing JSON command !{cmd_name} for {username}...")

        effective_prompt = user_args if user_args.strip() else f"Tell me about {cmd_name}"

        use_history = config.get("history", False)
        # 2. Get the history only if the command requires it
        user_history = TWITCH_HISTORY_CACHE.get(raw_name, []) if use_history else None
        # 3. Call Auto-Booting Local Qwen Engine
        response = await ask_isolated_qwen(
            username,
            effective_prompt,
            config.get("required", []),
            history=user_history
        )

        if response:
            # --- REGEX EMOTE ENFORCER ---
            # List your emotes here
            emotes = [
                "andycodCoffee", "andycodGasm", "andycodHype", "andycodLove",
                "andycodLurk", "andycodPog", "andycodRaid", "andycodRaiding",
                "andycodSadge", "andycodSweat"
            ]

            # Create a regex pattern: (andycodcoffee|andycodgasm|...)
            # The 're.IGNORECASE' flag handles the finding part
            pattern = re.compile(f"({'|'.join(map(re.escape, emotes))})", re.IGNORECASE)

            # Create a lookup map for the replacement (lowercase -> correct casing)
            emote_lookup = {e.lower(): e for e in emotes}

            # Replace matches using the lookup map
            response = pattern.sub(lambda m: emote_lookup[m.group(0).lower()], response)
            # ---------------------------

            final_reply = f"{username} {response}" if username not in response else response

            TWITCH_HISTORY_CACHE[raw_name].append(f"{raw_name}: {chat_content}")
            TWITCH_HISTORY_CACHE[raw_name].append(f"Bot: {response}")

            # 4. Return Output via v3 PartialUser Send Methods
            try:
                target = self.create_partialuser(message.broadcaster.id)
                await target.send_message(sender=self.user, message=final_reply)
                print(f"📤 Sent AI response to {username}")
            except Exception as e:
                print(f"❌ Failed to deliver message payload: {e}")

# --- RUN LOOP ---
async def main():
    await refresh_twitch_token()

    # Strip oauth prefix context out for standard string field registration
    raw_token = TWITCH_TOKEN.replace("oauth:", "")

    bot = TwitchBot(token_string=raw_token)

    print("🚀 Launching Twitch v3 engine...")
    await bot.start()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Shutting down safely.")
