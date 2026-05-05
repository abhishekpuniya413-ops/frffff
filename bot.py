import asyncio
import os
import logging
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import User
from telethon.errors import FloodWaitError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# --- Config from environment ---
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ["SESSION_STRING"]
MY_USERNAME = os.environ.get("MY_USERNAME", "wtw_dw")
CHATBOT_USERNAME = os.environ.get("CHATBOT_USERNAME", "ChatBot")

# State (globals set after client is created inside main)
current_partner_id = None
no_reply_task = None
client = None


# -----------------------------------------------------------------------
# Keep-alive web server (required for Render Web Service)
# -----------------------------------------------------------------------
async def keep_alive():
    async def handle(request):
        return web.Response(text="Bot is running! ✅")

    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Keep-alive web server started on port {port}")


# -----------------------------------------------------------------------
# Bot logic
# -----------------------------------------------------------------------
async def send_next():
    global current_partner_id, no_reply_task
    current_partner_id = None
    if no_reply_task and not no_reply_task.done():
        no_reply_task.cancel()
    try:
        await client.send_message(CHATBOT_USERNAME, "/next")
        logger.info("Sent /next — looking for new partner.")
    except FloodWaitError as e:
        logger.warning(f"FloodWait: sleeping {e.seconds}s")
        await asyncio.sleep(e.seconds)


async def no_reply_timeout():
    await asyncio.sleep(60)
    logger.info("Partner didn't reply in 60s — moving on.")
    await send_next()


async def handle_chatbot_message(event):
    global current_partner_id, no_reply_task

    text = event.raw_text.strip()
    lower = text.lower()
    logger.info(f"ChatBot → us: {text!r}")

    partner_found_phrases = [
        "you are now chatting",
        "stranger is connected",
        "connected to a stranger",
        "found a partner",
        "chat partner found",
        "you're now talking",
        "now talking to",
    ]
    if any(p in lower for p in partner_found_phrases):
        current_partner_id = "stranger"
        logger.info("Partner found — sending greeting.")
        if no_reply_task and not no_reply_task.done():
            no_reply_task.cancel()
        await asyncio.sleep(1)
        await client.send_message(CHATBOT_USERNAME, "hi, be friends? 🙂")
        no_reply_task = asyncio.create_task(no_reply_timeout())
        return

    disconnect_phrases = [
        "stranger has disconnected",
        "your partner disconnected",
        "partner left",
        "chat ended",
        "looking for",
        "disconnected",
    ]
    if any(p in lower for p in disconnect_phrases):
        logger.info("Partner disconnected — sending /next.")
        await send_next()
        return

    if current_partner_id and text and not text.startswith("/"):
        if no_reply_task and not no_reply_task.done():
            no_reply_task.cancel()
        logger.info("Partner replied — sending referral then /next.")
        await asyncio.sleep(1)
        await client.send_message(
            CHATBOT_USERNAME,
            f"text me my friend @{MY_USERNAME} 😊"
        )
        await asyncio.sleep(2)
        await send_next()


async def handle_dm(event):
    sender = await event.get_sender()
    if not isinstance(sender, User):
        return

    # Skip the chatbot itself
    if sender.username and sender.username.lower() == CHATBOT_USERNAME.lstrip("@").lower():
        return

    # Skip myself
    me = await client.get_me()
    if sender.id == me.id:
        return

    # Skip contacts
    if getattr(sender, "contact", False):
        logger.info(f"DM from contact {sender.id} — skipping.")
        return

    # Only auto-reply once (check if we've already messaged them)
    async for _ in client.iter_messages(event.chat_id, from_user=me.id, limit=1):
        logger.info(f"Already replied to {sender.id} — skipping.")
        return

    logger.info(f"New DM from non-contact @{sender.username} ({sender.id}) — greeting.")
    await event.reply("hi, how are you? 👋")


# -----------------------------------------------------------------------
# Startup — client created INSIDE the running event loop (fixes Py 3.14)
# -----------------------------------------------------------------------
async def main():
    global client

    # Start HTTP keep-alive first so Render health check passes immediately
    await keep_alive()

    # Create client inside async context — required on Python 3.10+
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

    # Register handlers via add_event_handler (not decorator, since client
    # is created dynamically)
    client.add_event_handler(
        handle_chatbot_message,
        events.NewMessage(from_users=CHATBOT_USERNAME)
    )
    client.add_event_handler(
        handle_dm,
        events.NewMessage(incoming=True, func=lambda e: e.is_private)
    )

    await client.start()
    me = await client.get_me()
    logger.info(f"✅ Logged in as @{me.username} ({me.first_name})")

    await client.send_message(CHATBOT_USERNAME, "/start")
    await asyncio.sleep(2)
    await client.send_message(CHATBOT_USERNAME, "/next")
    logger.info("Waiting for a chat partner…")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
