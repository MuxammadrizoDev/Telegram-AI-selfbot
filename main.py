import os
import asyncio
import threading
import random
from io import BytesIO
from PIL import Image
from http.server import HTTPServer, BaseHTTPRequestHandler
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from google import genai
from google.genai import types


# --- A. Health Check Web Server for Render ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Bot is online and active!")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()


def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()


threading.Thread(target=run_web_server, daemon=True).start()

# --- B. Secrets & API Setup ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
TELEGRAM_SESSION = os.environ.get("TELEGRAM_SESSION", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# Initialize official Gemini client
gemini_client = genai.Client(api_key=GEMINI_API_KEY)
GEMINI_MODEL = "gemini-3.6-flash"

# --- C. Global State & Saved Storage ---
BOT_ACTIVE = True
REPLY_TO_OWNER = False  # AI Co-Pilot Mode toggle (default: OFF)
MY_ID = None
user_sessions = {}
SAVED_NOTES = []
# Write here description of you
LANG_INSTRUCTIONS = {
    "uz": (

    ),
    "en": (

    ),
    "ru": (

    )
}

# --- D. Telethon Client Setup ---
client = TelegramClient(StringSession(TELEGRAM_SESSION), API_ID, API_HASH)


@client.on(events.NewMessage)
async def handle_all_messages(event):
    global BOT_ACTIVE, REPLY_TO_OWNER, MY_ID, SAVED_NOTES

    if not event.is_private:
        return

    sender_id = event.sender_id
    user_text = (event.text or "").strip()
    lowered = user_text.lower()
    is_owner = (sender_id == MY_ID)

    # ----------------------------------------------------
    # 1. OWNER CONTROLS (Commands sent by YOU)
    # ----------------------------------------------------
    if is_owner:
        if lowered == "/off":
            BOT_ACTIVE = False
            await event.reply("🤖 **| AI Assistant |**\n🛑 Auto-responder is now **OFF**.")
            return
        elif lowered == "/on":
            BOT_ACTIVE = True
            await event.reply("🤖 **| AI Assistant |**\n✅ Auto-responder is now **ON**.")
            return
        elif lowered in ["/copilot on", "/copilot-on"]:
            REPLY_TO_OWNER = True
            await event.reply(
                "🤖 **| AI Assistant |**\n🚀 **AI Co-Pilot Enabled!** I will now respond when you send messages.")
            return
        elif lowered in ["/copilot off", "/copilot-off"]:
            REPLY_TO_OWNER = False
            await event.reply(
                "🤖 **| AI Assistant |**\n🛑 **AI Co-Pilot Disabled!** I will ignore your messages and only respond to other contacts.")
            return
        elif lowered == "/status":
            status_str = "🟢 **ON**" if BOT_ACTIVE else "🔴 **OFF**"
            copilot_str = "🟢 **ON**" if REPLY_TO_OWNER else "🔴 **OFF**"
            await event.reply(
                f"🤖 **| AI Assistant |**\n\n"
                f"📊 **Bot Status:** {status_str}\n"
                f"🧠 **AI Co-Pilot Mode:** {copilot_str}\n"
                f"💬 **Active Chats:** {len(user_sessions)}\n"
                f"📝 **Saved Notes:** {len(SAVED_NOTES)}"
            )
            return
        elif lowered in ["/notes", "/saved"]:
            if not SAVED_NOTES:
                await event.reply("🤖 **| AI Assistant |**\n📭 **No saved messages yet!**")
            else:
                digest = "🤖 **| AI Assistant |**\n📥 **Saved Messages from Users:**\n\n"
                for idx, note in enumerate(SAVED_NOTES, 1):
                    digest += f"**{idx}.** {note}\n\n"
                await event.reply(digest)
            return
        elif lowered == "/clearnotes":
            SAVED_NOTES.clear()
            await event.reply("🤖 **| AI Assistant |**\n🗑️ **All saved messages have been cleared!**")
            return

        if not REPLY_TO_OWNER:
            return

    if not BOT_ACTIVE:
        return

    sender = await event.get_sender()
    if getattr(sender, 'bot', False):
        return

    if sender_id not in user_sessions:
        user_sessions[sender_id] = {"lang": "uz", "history": [], "welcomed": False}

    session = user_sessions[sender_id]

    # ----------------------------------------------------
    # 2. LANGUAGE SWITCH COMMANDS
    # ----------------------------------------------------
    if lowered in ["/eng", "/en"]:
        session["lang"] = "en"
        await event.reply("🤖 **| AI Assistant |**\n🇺🇸 Language set to **English**!")
        return
    elif lowered in ["/uz", "/uzb"]:
        session["lang"] = "uz"
        await event.reply("🤖 **| AI Assistant |**\n🇺🇿 Muloqot tili **O'zbek tiliga** o'zgartirildi!")
        return
    elif lowered in ["/rus", "/ru"]:
        session["lang"] = "ru"
        await event.reply("🤖 **| AI Assistant |**\n🇷🇺 Язык переключен на **Русский**!")
        return

    # ----------------------------------------------------
    # 3. EXPLICIT NOTE TAKING
    # ----------------------------------------------------
    note_trigger_phrases = ["tell owner", "save my message", "leave a message", "xabar qoldirish", "egasiga ayt",
                            "передай"]
    is_note_cmd = lowered.startswith("/note") or any(phrase in lowered for phrase in note_trigger_phrases)

    if is_note_cmd and not is_owner:
        note_content = user_text.replace("/note", "").strip() or user_text
        sender_name = getattr(sender, 'first_name', 'User')

        formatted_note = f"👤 **From:** {sender_name} (`{sender_id}`)\n💬 **Note:** {note_content}"
        SAVED_NOTES.append(formatted_note)

        ack_msgs = {
            "uz": "📝 **Xabaringiz saqlandi!** Hisob egasiga yetkazib qo'yaman.",
            "en": "📝 **Message saved!** I have notified the owner.",
            "ru": "📝 **Сообщение сохранено!** Я передал его владельцу."
        }

        async with client.action(event.chat_id, 'typing'):
            await asyncio.sleep(random.uniform(2.0, 4.0))

        await event.reply(f"🤖 **| AI Assistant |**\n{ack_msgs.get(session['lang'], ack_msgs['uz'])}")

        try:
            await client.send_message("me", f"🚨 **NEW MESSAGE LEFT FOR YOU!**\n\n{formatted_note}")
        except Exception as e:
            print(f"Failed to push alert to Saved Messages: {e}", flush=True)

        return

    # ----------------------------------------------------
    # 4. FIRST-CONTACT GREETING
    # ----------------------------------------------------
    if not session["welcomed"] and not is_owner:
        session["welcomed"] = True
        greeting = (
            "🤖 **| AI Assistant |**\n\n"
            "Hello! I am an AI assistant.\n"
            "The account owner is currently busy.\n\n"
            "💡 *Tip: You can say 'Save my message' or send `/note your message` to leave a note for the owner!*\n\n"
            "🌐 **Select Language:** `/eng` | `/uz` | `/rus`"
        )
        await event.reply(greeting)
        return

    # ----------------------------------------------------
    # 5. MEDIA & VISION ANALYSIS
    # ----------------------------------------------------
    image_bytes = None
    prompt_caption = user_text if user_text else "What is in this image or sticker?"

    if event.photo or event.sticker:
        media_bytes = await event.download_media(file=bytes)
        if media_bytes:
            try:
                # Convert photo or sticker into JPEG bytes for Gemini API
                img = Image.open(BytesIO(media_bytes)).convert("RGB")
                buffered = BytesIO()
                img.save(buffered, format="JPEG")
                image_bytes = buffered.getvalue()
            except Exception as e:
                print(f"Error converting media: {e}", flush=True)

    elif event.video or event.voice or event.document:
        msgs = {
            "uz": "📥 Media xabaringiz qabul qilindi! Hisob egasiga xabar berib qo'ydim.",
            "en": "📥 Received your media file! I will notify the owner.",
            "ru": "📥 Медиафайл получен! Я уведомил владельца."
        }
        await event.reply(f"🤖 **| AI Assistant |**\n{msgs.get(session['lang'], msgs['uz'])}")
        return

    # ----------------------------------------------------
    # 6. AI RESPONSE GENERATION WITH GEMINI API
    # ----------------------------------------------------
    lang_key = session["lang"]
    sys_inst = LANG_INSTRUCTIONS.get(lang_key, LANG_INSTRUCTIONS["uz"])
    session["history"] = session["history"][-6:]

    safe_user_text = user_text if user_text else "[Sent media/attachment]"

    try:
        async with client.action(event.chat_id, 'typing'):
            # Convert session history to Gemini content structure
            contents = []
            for msg in session["history"]:
                role = "user" if msg["role"] == "user" else "model"
                contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])]))

            # Build current payload
            current_parts = [types.Part.from_text(text=prompt_caption if image_bytes else safe_user_text)]

            # Properly format image bytes for google-genai SDK
            if image_bytes:
                current_parts.append(
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type="image/jpeg"
                    )
                )

            contents.append(types.Content(role="user", parts=current_parts))

            # Config with increased token limit to allow complete responses
            config = types.GenerateContentConfig(
                system_instruction=sys_inst,
                max_output_tokens=8192
            )

            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: gemini_client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=contents,
                    config=config
                )
            )

            # Realistic typing delay (anti-ban simulation)
            await asyncio.sleep(random.uniform(2.5, 5.0))

        if response.text:
            raw_reply = response.text.strip()
            ai_reply = f"🤖 **| AI Assistant |**\n{raw_reply}"

            session["history"].append({"role": "user", "content": safe_user_text})
            session["history"].append({"role": "assistant", "content": raw_reply})

            await event.reply(ai_reply)
        else:
            await event.reply("🤖 **| AI Assistant |**\n⚠️ *(Received empty response)*")

    except Exception as e:
        print(f"❌ Error generating response: {e}", flush=True)
        await event.reply("🤖 **| AI Assistant |**\n⏳ *(Assistant is temporarily busy, please try again in a moment!)*")


# --- E. Startup Sequence ---
async def main():
    global MY_ID
    await client.connect()
    if not await client.is_user_authorized():
        print("❌ Session expired!", flush=True)
        return

    me = await client.get_me()
    MY_ID = me.id
    print(f"✅ Bot initialized for {me.first_name} [ID: {MY_ID}]", flush=True)
    await client.run_until_disconnected()


if __name__ == "__main__":
    client.loop.run_until_complete(main())
