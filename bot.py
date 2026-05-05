import asyncio
import os
import logging
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

current_partner_id = None
no_reply_task = None

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)


async def send_next():
    """Send /next to the chatbot to find a new partner."""
    global current_partner_id, no_reply_task
    current_partner_id = None
    if no_reply_task and not no_reply_task.done():
        no_reply_task.cancel()
    try:
        await client.send_message(CHATBOT_USERNAME, "/next")
        logger.info("Sent /next to look for new partner.")
    except FloodWaitError as e:
        logger.warning(f"Flood wait: sleeping {e.seconds}s")
        await asyncio.sleep(e.seconds)


async def no_reply_timeout():
    """Wait 60 seconds; if partner hasn't replied, send /next."""
    await asyncio.sleep(60)
    logger.info("Partner didn't reply in 60s. Moving on.")
    await send_next()


# -----------------------------------------------------------------------
# Messages FROM the ChatBot (forwarded from the stranger / system msgs)
# -----------------------------------------------------------------------
@client.on(events.NewMessage(from_users=CHATBOT_USERNAME))
async def handle_chatbot_message(event):
    global current_partner_id, no_reply_task

    text = event.raw_text.strip()
    lower = text.lower()
    logger.info(f"ChatBot → us: {text!r}")

    # Detect "You are now chatting with a random stranger" type messages
    partner_found_phrases = [
        "you are now chatting",
        "stranger is connected",
        "connected to a stranger",
        "found a partner",
        "chat partner found",
        "you're now talking",
    ]
    if any(p in lower for p in partner_found_phrases):
        current_partner_id = "stranger"   # symbolic; real ID not exposed by most chatbots
        logger.info("New chat partner found! Sending greeting.")
        # Cancel any previous timeout
        if no_reply_task and not no_reply_task.done():
            no_reply_task.cancel()
        await asyncio.sleep(1)
        await client.send_message(CHATBOT_USERNAME, "hi, be friends? 🙂")
        # Start 60-second no-reply timer
        no_reply_task = asyncio.create_task(no_reply_timeout())
        return

    # Detect partner disconnect
    disconnect_phrases = [
        "stranger has disconnected",
        "your partner disconnected",
        "partner left",
        "chat ended",
        "looking for",
    ]
    if any(p in lower for p in disconnect_phrases):
        logger.info("Partner disconnected. Sending /next.")
        await send_next()
        return

    # If we have an active partner and they sent something real → it's their reply
    if current_partner_id and text and not text.startswith("/"):
        # Cancel the no-reply timer since they replied
        if no_reply_task and not no_reply_task.done():
            no_reply_task.cancel()
        logger.info("Partner replied. Sending referral message.")
        await asyncio.sleep(1)
        await client.send_message(
            CHATBOT_USERNAME,
            f"text me my friend @{MY_USERNAME} 😊"
        )
        await asyncio.sleep(2)
        await send_next()


# -----------------------------------------------------------------------
# Direct Messages to ME (from strangers who found my username)
# -----------------------------------------------------------------------
@client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
async def handle_dm(event):
    # Ignore messages from the chatbot itself
    sender = await event.get_sender()
    if not isinstance(sender, User):
        return
    if sender.username and sender.username.lower() == CHATBOT_USERNAME.lstrip("@").lower():
        return
    # Ignore myself
    me = await client.get_me()
    if sender.id == me.id:
        return

    # Check if sender is in my contacts
    if sender.contact:
        logger.info(f"DM from contact {sender.id} — ignoring.")
        return

    # Only reply to their FIRST message (no previous messages from us)
    async for msg in client.iter_messages(event.chat_id, from_user=me.id, limit=1):
        logger.info(f"Already replied to {sender.id} — skipping auto-reply.")
        return

    logger.info(f"New DM from non-contact {sender.id}. Sending greeting.")
    await event.reply("hi, how are you? 👋")


# -----------------------------------------------------------------------
# Startup
# -----------------------------------------------------------------------
async def main():
    await client.start()
    me = await client.get_me()
    logger.info(f"Logged in as @{me.username} ({me.first_name})")
    logger.info("Userbot is running. Sending /start to ChatBot...")
    await client.send_message(CHATBOT_USERNAME, "/start")
    await asyncio.sleep(2)
    await client.send_message(CHATBOT_USERNAME, "/next")
    logger.info("Waiting for a chat partner…")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
