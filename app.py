# app.py -- full offline assistant with persona/avatar support + emoji-stripped TTS
import os
import json
import re
import traceback
from io import BytesIO
from flask import Flask, render_template, request, jsonify
import speech_recognition as sr
from gtts import gTTS

# --- App setup ---
app = Flask(__name__, static_folder="static", template_folder="templates")

CONV_FILE = "conversations.json"
STATIC_TTS_PATH = os.path.join(app.static_folder, "response.mp3")

# --- Emoji removal helper (so TTS won't speak emoji names) ---
# Pattern covers common emoji/pictograph ranges
EMOJI_PATTERN = re.compile(
    "[" 
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F680-\U0001F6FF"  # transport & map symbols
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002700-\U000027BF"  # dingbats
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE
)

def strip_emojis(text: str) -> str:
    """Remove emojis/pictographs from text for TTS. Returns cleaned text."""
    if not text:
        return text
    cleaned = EMOJI_PATTERN.sub("", text)
    cleaned = " ".join(cleaned.split()).strip()
    if cleaned == "":
        return "Okay."
    return cleaned

# --- Persistence helpers ---
def load_conversations():
    if os.path.exists(CONV_FILE):
        try:
            with open(CONV_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_conversations(conv):
    try:
        with open(CONV_FILE, "w", encoding="utf-8") as f:
            json.dump(conv, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Could not save conversations:", e)

conversations = load_conversations()
SYSTEM_PROMPT = "You are a friendly local voice assistant. Keep replies short and helpful."

# --- Persona-aware reply generator (cat, winnie, narwhal) ---
def generate_reply(user_text, persona="narwhal"):
    """Local rule-based replies that match avatar personalities."""
    if not user_text or not user_text.strip():
        # generic short fallback per persona
        if persona == "cat":
            return "😼 I didn’t catch that."
        if persona == "winnie":
            return "🧸 I didn’t quite hear you, sweet one."
        return "🐋 I didn’t quite catch that."

    t = user_text.lower().strip()

    # choose prefixes & styles
    if persona == "cat":
        prefix = "😼 "
        style = "cool"
    elif persona == "winnie":
        prefix = "🧸 "
        style = "soft"
    else:
        prefix = "🐋 "
        style = "playful"

    # helper tone functions
    def tone_cat(msg): return prefix + msg.capitalize() + " 😏"
    def tone_winnie(msg): return prefix + msg.capitalize() + " 🌸"
    def tone_narwhal(msg): return prefix + msg.capitalize() + " 🎉"

    # rules
    if any(g in t for g in ["hello", "hi", "hey", "hiya"]):
        if style == "cool":
            return tone_cat("yo, what's up")
        if style == "soft":
            return tone_winnie("hi there, friend")
        return tone_narwhal("hey hey! how's the ocean today")

    if "how are you" in t:
        if style == "cool":
            return tone_cat("i'm chilling, as always")
        if style == "soft":
            return tone_winnie("i'm cozy and calm, thanks for asking")
        return tone_narwhal("bubbly and fantastic!")

    if "weather" in t:
        if style == "cool":
            return tone_cat("i don't check the weather — i make it cool")
        if style == "soft":
            return tone_winnie("looks lovely in my little cloud world")
        return tone_narwhal("probably sunny somewhere, splash!")

    # math handling (very simple)
    if any(op in t for op in ["+", "-", "*", "/", "plus", "minus", "times", "divide"]):
        try:
            expr = "".join(ch for ch in t if ch.isdigit() or ch in "+-*/.() ")
            if expr.strip():
                result = eval(expr, {"__builtins__": {}}, {})
                if style == "cool":
                    return tone_cat(f"easy math. it's {result}")
                if style == "soft":
                    return tone_winnie(f"the answer is {result}, sweet one")
                return tone_narwhal(f"that makes {result}, splash math!")
        except Exception:
            if style == "cool":
                return tone_cat("nah, that expression's messy")
            if style == "soft":
                return tone_winnie("hmm, couldn't solve that one")
            return tone_narwhal("whoopsie, math overflow!")

    if "who are you" in t or "what are you" in t:
        if style == "cool":
            return tone_cat("i'm the cat who knows things. that's all")
        if style == "soft":
            return tone_winnie("i'm winnie, your gentle little helper")
        return tone_narwhal("i'm narwhal! the splashy sidekick you never knew you needed!")

    # fallback by persona
    if style == "cool":
        return tone_cat("not my field, but sounds interesting")
    if style == "soft":
        return tone_winnie("sorry, i don't know that, but i'm happy to listen")
    return tone_narwhal("no clue, but i bet it's fun!")

# --- Routes ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/process_voice", methods=["POST"])
def process_voice():
    # Validate upload
    if "audio" not in request.files:
        return jsonify({"error": "No audio uploaded"}), 400

    # Read audio bytes
    audio_file = request.files["audio"]
    audio_bytes = BytesIO(audio_file.read())

    # Speech recognition
    recognizer = sr.Recognizer()
    try:
        with sr.AudioFile(audio_bytes) as source:
            audio_data = recognizer.record(source)
            user_text = recognizer.recognize_google(audio_data)
    except sr.UnknownValueError:
        user_text = ""
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Speech recognition failed: {str(e)}"}), 500

    # Manage conversation memory
    sess = request.form.get("session_id", "default")
    if sess not in conversations:
        conversations[sess] = [{"role": "system", "content": SYSTEM_PROMPT}]
    conversations[sess].append({"role": "user", "content": user_text})

    # Persona (from frontend)
    persona = request.form.get("persona", "narwhal")

    # Generate reply using persona
    assistant_text = generate_reply(user_text, persona=persona)
    conversations[sess].append({"role": "assistant", "content": assistant_text})
    save_conversations(conversations)

    # Text-to-Speech (gTTS) -> save to static file (strip emojis before speaking)
    audio_url = None
    try:
        tts_text = strip_emojis(assistant_text)
        tts = gTTS(tts_text)
        os.makedirs(app.static_folder, exist_ok=True)
        tts.save(STATIC_TTS_PATH)
        audio_url = "/static/response.mp3"
    except Exception as e:
        print("TTS failed:", e)
        traceback.print_exc()
        audio_url = None

    # Return JSON (include persona so frontend can confirm)
    return jsonify({
        "user_text": user_text,
        "assistant_text": assistant_text,
        "audio": audio_url,
        "persona": persona
    })

# --- Run server ---
if __name__ == "__main__":
    app.run(debug=True)
