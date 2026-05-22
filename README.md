# ollama-twitch-discord-bot

## INSTALLATION

1. **Clone the repository:**

```bash
   git clone [https://github.com/the-code-monkey/ollama-twitch-discord-bot.git](https://github.com/the-code-monkey/ollama-twitch-discord-bot.git)
   cd ollama-twitch-discord-bot
```

2. **Create an env file:**

To setup the bot create a .env file

```bash
# --- TWITCH CREDENTIALS ---
TWITCH_SECRET = ""
TWITCH_CLIENT_ID = ""
TWITCH_CHANNEL = ""
AUTHORIZATION_CODE=""

// these will come from the setup.py script
TWITCH_REFRESH_TOKEN = ""
TWITCH_TOKEN = ""
TWITCH_BOT_NUMERIC_ID = ""

```

Go to [Twitch Developer Console](https://dev.twitch.tv/console/apps) to register an application and generate your `TWITCH_SECRET` and `TWITCH_CLIENT_ID`. Ensure your redirect URI is set to `http://localhost:3000`.

Put the secret and client id into the .env file and the channel you wish to connect to.

3. **Install dependencies:**

Make sure you have Python 3.10+ installed.

pip install -r requirements.txt

4. **Initialize Twitch Tokens:**

Run the setup script to generate your refresh/access tokens and numeric ID. This will print out some tokens for you to add to the env file.

## OLLAMA SETUP

The bot requires a local Ollama instance running a model.

Install Ollama: Follow the instructions at ollama.com.

Choose a model: (qwen2.5:1.5b) is what i use.

```bash
   ollama pull qwen2.5:1.5b
```

### Start the service:

Ensure the Ollama service is running in the background (check systemctl status ollama on Linux).

### RUNNING THE BOT
Once your .env is populated and Ollama is active, start the bot:

```bash
  python bot.py
```


## COMMAND CONFIGURATION

The bot is powered by commands.json. You can define custom behavior for your chat commands here:

```json
{
  "hype": {
    "isSub": false,
    "timeout": 1,
    "required": [
      "Extremely high-energy, all-caps excitement.",
      "Use at least 5 of these emotes: andycodPog, andycodHype, etc."
    ]
  }
}
```

Add "history": true to any command that requires context from the last few chat messages (like !roast).

---
