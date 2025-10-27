import json
import os
import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler, CallbackContext

# --- Data Loading and Saving ---
def load_json(filename):
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return json.load(f)
    return {}

def save_json(data, filename):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=4)

# --- Bot Handlers ---
def start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    users_db = load_json('users.json')
    user_id = str(user.id)

    if user_id not in users_db:
        users_db[user_id] = {
            'first_name': user.first_name,
            'username': user.username,
            'balance': 0,
            'is_banned': False
        }
        save_json(users_db, 'users.json')

    welcome_text = "👋 Welcome to FaceSwap Bot!\nSwap faces easily between two photos 😎"
    keyboard = [
        [InlineKeyboardButton("🔁 Start Face Swap", callback_data='start_swap')],
        [InlineKeyboardButton("💰 Deposit Credits", callback_data='deposit_credits')],
        [InlineKeyboardButton("💬 Support", callback_data='support')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(welcome_text, reply_markup=reply_markup)

def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    user_id = str(query.from_user.id)
    config = load_json('config.json')
    users_db = load_json('users.json')

    # Check for maintenance mode
    if config.get('maintenance_mode', False):
        query.edit_message_text("🛠️ Bot is currently under maintenance. Please try again later.")
        return

    # Check if user is banned
    if users_db.get(user_id, {}).get('is_banned', False):
        query.edit_message_text("❌ You have been banned from using this bot.")
        return

    if query.data == 'start_swap':
        handle_swap_flow(update, context)
    elif query.data == 'deposit_credits':
        deposit_link = config.get('deposit_link', 'No deposit link set.')
        query.edit_message_text(f"Please use the following link to deposit credits:\n{deposit_link}")
    elif query.data == 'support':
        context.user_data['awaiting_support_message'] = True
        query.edit_message_text("Please send your support message now. Our team will get back to you.")

def handle_swap_flow(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = str(query.from_user.id)
    config = load_json('config.json')
    users_db = load_json('users.json')

    if config.get('earning_mode', True):
        credits_needed = config.get('credits_per_swap', 1)
        user_balance = users_db.get(user_id, {}).get('balance', 0)
        if user_balance < credits_needed:
            deposit_link = config.get('deposit_link', '')
            query.edit_message_text(f"Insufficient credits. You need {credits_needed} credit(s) to perform a swap.\n"
                                    f"Please [deposit here]({deposit_link}).", parse_mode=ParseMode.MARKDOWN)
            return

    context.user_data['swap_step'] = 1
    query.edit_message_text("📸 **Step 1/2:** Please send the photo containing the **face** you want to use.")

def message_handler(update: Update, context: CallbackContext) -> None:
    user_id = str(update.effective_user.id)
    config = load_json('config.json')
    users_db = load_json('users.json')

    # Handle support messages
    if context.user_data.get('awaiting_support_message'):
        support_requests = load_json('support.json') if os.path.exists('support.json') else []
        support_requests.append({
            'user_id': user_id,
            'username': update.effective_user.username,
            'first_name': update.effective_user.first_name,
            'message': update.message.text,
            'timestamp': update.message.date.isoformat(),
            'status': 'open'
        })
        save_json(support_requests, 'support.json')
        update.message.reply_text("✅ Your message has been sent. Our support team will review it shortly.")
        context.user_data['awaiting_support_message'] = False
        return

    # Handle face swap image flow
    if 'swap_step' in context.user_data:
        if not update.message.photo:
            update.message.reply_text("❌ Invalid input. Please send a photo.")
            return

        photo_file = update.message.photo[-1].get_file()
        
        if context.user_data['swap_step'] == 1:
            context.user_data['face_photo_id'] = photo_file.file_id
            context.user_data['swap_step'] = 2
            update.message.reply_text("🎯 **Step 2/2:** Great! Now send the **target photo** where the face should be swapped onto.")
        
        elif context.user_data['swap_step'] == 2:
            context.user_data['target_photo_id'] = photo_file.file_id
            processing_message = update.message.reply_text("⚙️ Processing your swap, please wait ⏳")

            try:
                # Get file paths
                face_photo_path = context.bot.get_file(context.user_data['face_photo_id']).file_path
                target_photo_path = context.bot.get_file(context.user_data['target_photo_id']).file_path

                # Call API
                api_url = config.get('face_api_url', "https://ng-faceswap.vercel.app/api/faceswap")
                response = requests.post(api_url, json={'face_image_url': face_photo_path, 'target_image_url': target_photo_path})
                
                if response.status_code == 200 and response.headers['Content-Type'].startswith('image/'):
                    # Deduct credits if in earning mode
                    if config.get('earning_mode', True):
                        credits_to_deduct = config.get('credits_per_swap', 1)
                        users_db[user_id]['balance'] -= credits_to_deduct
                        save_json(users_db, 'users.json')

                    # Send the result and clean up
                    output_path = f'result_{user_id}.jpg'
                    with open(output_path, 'wb') as f:
                        f.write(response.content)
                    
                    context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=open(output_path, 'rb'),
                        caption="✅ Swap successful! Here is your image."
                    )
                    os.remove(output_path)

                    # Update stats
                    stats = load_json('stats.json')
                    stats['total_swaps'] = stats.get('total_swaps', 0) + 1
                    stats['generated_files'] = stats.get('generated_files', 0) + 1
                    save_json(stats, 'stats.json')
                else:
                    update.message.reply_text(f"❌ API Error: {response.text}")
            
            except Exception as e:
                update.message.reply_text(f"An error occurred: {str(e)}")
            
            finally:
                processing_message.delete()
                # Reset swap state
                del context.user_data['swap_step']
                del context.user_data['face_photo_id']
                del context.user_data['target_photo_id']

# This function will be called from the web.py webhook
def handle_update(update_data):
    config = load_json('config.json')
    bot_token = config.get("bot_token")
    if not bot_token:
        print("Bot token not found in config.json. Cannot process update.")
        return

    updater = Updater(bot_token, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command | Filters.photo, message_handler))

    update = Update.de_json(update_data, updater.bot)
    dp.process_update(update)
