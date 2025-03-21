import telebot
import psutil
import time
import threading

# Replace with your Telegram Bot Token
BOT_TOKEN = '7801992252:AAEVyldGbrwIPuvuGNLfyIOMb6dSkfH83j8'
bot = telebot.TeleBot(BOT_TOKEN)

# Replace with your Telegram User ID (owner)
OWNER_ID = 6191432888

# Global flag and thread reference for monitoring
monitoring = False
monitor_thread = None

def network_monitor(chat_id, interval=5):
    """
    Continuously send network packet rates to the given chat every 'interval' seconds.
    Sends a new message every 5 seconds.
    """
    old_stats = psutil.net_io_counters()
    while monitoring:
        time.sleep(interval)
        new_stats = psutil.net_io_counters()
        sent = new_stats.bytes_sent - old_stats.bytes_sent
        recv = new_stats.bytes_recv - old_stats.bytes_recv
        message = f"Sent: {sent/1024:.2f} KB/s, Received: {recv/1024:.2f} KB/s"
        try:
            bot.send_message(chat_id, message)
        except Exception as e:
            print("Error sending message:", e)
        old_stats = new_stats

@bot.message_handler(commands=['run'])
def handle_run(message):
    # Only allow the owner to run this command
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ You are not authorized to use this command.")
        return

    global monitoring, monitor_thread
    if monitoring:
        bot.reply_to(message, "Network monitoring is already running!")
        return
    monitoring = True
    bot.reply_to(message, "Starting network monitoring every 5 seconds...")
    monitor_thread = threading.Thread(target=network_monitor, args=(message.chat.id, 5))
    monitor_thread.start()

@bot.message_handler(commands=['stop'])
def handle_stop(message):
    # Only allow the owner to run this command
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ You are not authorized to use this command.")
        return

    global monitoring, monitor_thread
    if not monitoring:
        bot.reply_to(message, "Network monitoring is not running!")
        return
    monitoring = False
    monitor_thread.join()
    bot.reply_to(message, "Network monitoring has been stopped.")

# Start polling for commands
bot.polling()
