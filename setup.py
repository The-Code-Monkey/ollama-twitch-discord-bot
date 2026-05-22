import asyncio
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()


SECRET = os.getenv("TWITCH_SECRET")
CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
CHANNEL = os.getenv("TWITCH_CHANNEL")

# PASTE THE CODE STRING YOU COPIED FROM THE ADDRESS BAR HERE
AUTHORIZATION_CODE = os.getenv("AUTHORIZATION_CODE")

async def main():
    url = "https://id.twitch.tv/oauth2/token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": SECRET,
        "code": AUTHORIZATION_CODE,
        "grant_type": "authorization_code",
        "redirect_uri": "http://localhost"
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=payload) as resp:
            if resp.status != 200:
                print(f"❌ Swap failed! Status {resp.status}: {await resp.text()}")
                return

            data = await resp.json()
            access_token = data.get("access_token")
            refresh_token = data.get("refresh_token")

            print("\n" + "="*50)
            print("🚀 AUTHENTICATION DATA COLLECTED SUCCESSFULY! 🚀")
            print("="*50)
            print(f"TWITCH_REFRESH_TOKEN = \"{refresh_token}\"")
            print(f"TWITCH_TOKEN = \"oauth:{access_token}\"")

            # Fetch your numeric user ID automatically with our fresh authorization
            headers = {"Client-ID": CLIENT_ID, "Authorization": f"Bearer {access_token}"}
            async with session.get(f"https://api.twitch.tv/helix/users?login={CHANNEL}", headers=headers) as u_resp:
                if u_resp.status == 200:
                    u_data = await u_resp.json()
                    numeric_id = u_data["data"][0]["id"]
                    print(f"TWITCH_BOT_NUMERIC_ID = \"{numeric_id}\"")
                    print("="*50 + "\n")
                else:
                    print(f"❌ Failed to query profile: {await u_resp.text()}")

asyncio.run(main())
