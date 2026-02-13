import os
import time
import requests
from datetime import datetime
import json
import asyncio
import signal
import sys
import re
from pathlib import Path

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from telegram.error import TelegramError
from dotenv import load_dotenv

# ====================================================
# КОНФИГУРАЦИЯ
# ====================================================

# Загружаем переменные из .env файла
from pathlib import Path
env_path = Path(__file__).parent / '.env'
print(f"🔍 Ищем .env по пути: {env_path}")
print(f"📁 Файл существует: {env_path.exists()}")

if env_path.exists():
    with open(env_path, 'r', encoding='utf-8') as f:
        content = f.read().strip()
        print(f"📄 Содержимое .env: {content}")
else:
    print("❌ Файл .env НЕ НАЙДЕН!")
    print("📁 Содержимое папки:")
    for file in Path(__file__).parent.iterdir():
        print(f"  - {file.name}")

load_dotenv(dotenv_path=env_path)
TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN")

# Получаем токен из переменных окружения
TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN")

# Проверяем, что токен загрузился
if not TELEGRAM_BOT_TOKEN:
    print("❌ ОШИБКА: Токен не найден в .env файле!")
    print("📁 Текущая папка:", Path(__file__).parent)
    print("📄 Создайте файл .env с содержимым: BOT_TOKEN=ваш_токен")
    exit(1)
else:
    print(f"✅ Токен загружен: {TELEGRAM_BOT_TOKEN[:10]}...")

# Ваш Telegram ID
YOUR_ADMIN_ID = 1035969773

# Файл для сохранения подписанных пользователей
if os.path.exists('/app/data/users.json'):
    USERS_FILE = '/app/data/users.json'
    NOTIFIED_GAMES_FILE = '/app/data/notified_games.json'
    USER_SETTINGS_FILE = '/app/data/user_settings.json'
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    USERS_FILE = os.path.join(SCRIPT_DIR, "users.json")
    NOTIFIED_GAMES_FILE = os.path.join(SCRIPT_DIR, "notified_games.json")
    USER_SETTINGS_FILE = os.path.join(SCRIPT_DIR, "user_settings.json")

# Интервал проверки (в секундах)
CHECK_INTERVAL = 3600  # 1 час

# =============================================================================
# УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ И НАСТРОЙКАМИ
# =============================================================================

def load_users():
    """Загружает подписанных пользователей из файла"""
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"users": []}


def save_users(users_dict):
    """Сохраняет подписанных пользователей в файл"""
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users_dict, f, ensure_ascii=False, indent=2)


def add_user(chat_id):
    """Добавляет пользователя в список подписчиков"""
    users = load_users()
    if chat_id not in users["users"]:
        users["users"].append(chat_id)
        save_users(users)
        init_user_settings(chat_id)
        return True
    return False


def remove_user(chat_id):
    """Удаляет пользователя из списка подписчиков"""
    users = load_users()
    if chat_id in users["users"]:
        users["users"].remove(chat_id)
        save_users(users)
        remove_user_settings(chat_id)
        return True
    return False


# =============================================================================
# НАСТРОЙКИ ПОЛЬЗОВАТЕЛЕЙ
# =============================================================================

def load_user_settings():
    """Загружает настройки пользователей"""
    if os.path.exists(USER_SETTINGS_FILE):
        with open(USER_SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_user_settings(settings):
    """Сохраняет настройки пользователей"""
    with open(USER_SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def init_user_settings(chat_id):
    """Инициализирует настройки для нового пользователя"""
    settings = load_user_settings()
    if str(chat_id) not in settings:
        settings[str(chat_id)] = {
            "notify_free": True,
            "notify_discounts": False,
            "language": "ru"
        }
        save_user_settings(settings)


def remove_user_settings(chat_id):
    """Удаляет настройки пользователя"""
    settings = load_user_settings()
    if str(chat_id) in settings:
        del settings[str(chat_id)]
        save_user_settings(settings)


def get_user_setting(chat_id, key, default=None):
    """Получает конкретную настройку пользователя"""
    settings = load_user_settings()
    user_settings = settings.get(str(chat_id), {})
    return user_settings.get(key, default)


def update_user_setting(chat_id, key, value):
    """Обновляет настройку пользователя"""
    settings = load_user_settings()
    if str(chat_id) not in settings:
        init_user_settings(chat_id)
        settings = load_user_settings()

    settings[str(chat_id)][key] = value
    save_user_settings(settings)


# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

def load_notified_games():
    """Загружает список уже отправленных игр из файла"""
    if os.path.exists(NOTIFIED_GAMES_FILE):
        with open(NOTIFIED_GAMES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"steam": {}, "epic": {}}


def save_notified_games(games_dict):
    """Сохраняет список отправленных игр в файл"""
    with open(NOTIFIED_GAMES_FILE, 'w', encoding='utf-8') as f:
        json.dump(games_dict, f, ensure_ascii=False, indent=2)


def clean_old_games(games_dict, days=7):
    """Удаляет игры, отправленные более X дней назад"""
    current_time = time.time()
    max_age = days * 24 * 60 * 60

    cleaned = {"steam": {}, "epic": {}}
    removed_count = {"steam": 0, "epic": 0}

    for platform in ["steam", "epic"]:
        for game_id, notified_at in games_dict.get(platform, {}).items():
            age = current_time - notified_at
            if age < max_age:
                cleaned[platform][game_id] = notified_at
            else:
                removed_count[platform] += 1

    total_removed = sum(removed_count.values())
    if total_removed > 0:
        print(f"🧹 Очистка: {removed_count['steam']} Steam, {removed_count['epic']} Epic удалено (> {days} дней)")

    return cleaned


# =============================================================================
# STEAM ФУНКЦИИ
# =============================================================================

def is_game_free_to_play(app_id):
    """Проверяет, является ли игра Free-to-Play в Steam"""
    try:
        url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
        response = requests.get(url, timeout=10)

        if response.status_code == 200:
            data = response.json()
            if str(app_id) in data and data[str(app_id)]['success']:
                game_data = data[str(app_id)]['data']
                return game_data.get('is_free', False)
    except:
        pass
    return False


def get_game_details(app_id):
    """Получает полную информацию об игре в Steam, включая цену"""
    try:
        url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=ru&l=russian&v=1"
        response = requests.get(url, timeout=15)

        if response.status_code == 200:
            data = response.json()
            if str(app_id) in data and data[str(app_id)]['success']:
                game_data = data[str(app_id)]['data']
                price_overview = game_data.get('price_overview', {})

                if not price_overview and game_data.get('is_free', False) == False:
                    price_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=us&l=english"
                    price_response = requests.get(price_url, timeout=10)
                    if price_response.status_code == 200:
                        price_data = price_response.json()
                        if str(app_id) in price_data and price_data[str(app_id)]['success']:
                            price_overview = price_data[str(app_id)]['data'].get('price_overview', {})

                return {
                    'name': game_data.get('name', 'Неизвестно'),
                    'is_free': game_data.get('is_free', False),
                    'final_price': price_overview.get('final', 0) // 100 if price_overview else 0,
                    'original_price': price_overview.get('initial', 0) // 100 if price_overview else 0,
                    'discount_percent': price_overview.get('discount_percent', 0),
                    'currency': price_overview.get('currency', 'RUB'),
                    'release_date': game_data.get('release_date', {}).get('date', 'Неизвестно'),
                    'developer': game_data.get('developers', ['Неизвестно'])[0],
                    'publisher': game_data.get('publishers', ['Неизвестно'])[0],
                    'genres': [g['description'] for g in game_data.get('genres', [])],
                    'image': game_data.get('header_image', '')
                }
    except Exception as e:
        print(f"⚠️ Ошибка получения данных для {app_id}: {e}")

    return None


def check_steam_free_games():
    """Ищет игры со 100% скидкой в Steam"""
    free_games = []
    found_ids = set()

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        url = "https://store.steampowered.com/api/featured/"
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()

            for category in ['large_capsules', 'featured_win', 'featured_mac', 'featured_linux']:
                if category in data:
                    for game in data[category]:
                        discount = game.get('discount_percent', 0)
                        if discount == 100:
                            app_id = game.get('id')
                            if app_id and str(app_id) not in found_ids:
                                is_f2p = is_game_free_to_play(app_id)
                                if not is_f2p:
                                    found_ids.add(str(app_id))
                                    free_games.append({
                                        'title': game.get('name', 'Неизвестно'),
                                        'url': f"https://store.steampowered.com/app/{app_id}",
                                        'id': str(app_id),
                                        'platform': 'Steam'
                                    })

        search_url = "https://store.steampowered.com/search/results/"
        params = {
            'query': '',
            'start': 0,
            'count': 50,
            'maxprice': 'free',
            'specials': 1,
            'ndl': 1
        }

        response = requests.get(search_url, params=params, headers=headers, timeout=10)

        if response.status_code == 200:
            html = response.text
            app_ids = re.findall(r'data-ds-appid="(\d+)"', html)

            for app_id in app_ids[:10]:
                if str(app_id) not in found_ids:
                    details = get_game_details(app_id)
                    if details and details.get('original_price', 0) > 0:
                        found_ids.add(str(app_id))
                        free_games.append({
                            'title': details.get('name', 'Неизвестно'),
                            'url': f"https://store.steampowered.com/app/{app_id}",
                            'id': str(app_id),
                            'platform': 'Steam'
                        })

    except Exception as e:
        print(f"❌ Ошибка при проверке Steam: {e}")

    return free_games


def check_steam_discounts():
    """Проверяет игры со скидками в Steam (всегда ищет 90%+)"""
    discounted_games = []
    found_ids = set()
    min_discount = 90

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7'
        }

        print(f"\n🔍 ПРОВЕРКА СКИДОК STEAM (90%+)...")

        search_url = "https://store.steampowered.com/search/results/"
        params = {
            'query': '',
            'start': 0,
            'count': 100,
            'specials': 1,
            'ndl': 1,
            'sort_by': 'Price_DESC',
            'category1': 998,
            'os': 'win',
            'discounts': 1
        }

        response = requests.get(search_url, params=params, headers=headers, timeout=15)

        if response.status_code == 200:
            html = response.text
            app_ids = re.findall(r'data-ds-appid="(\d+)"', html)

            for app_id in app_ids[:30]:
                if str(app_id) not in found_ids:
                    details = get_game_details(app_id)
                    if details:
                        discount = details.get('discount_percent', 0)
                        if discount >= min_discount and discount < 100:
                            found_ids.add(str(app_id))
                            discounted_games.append({
                                'title': details.get('name', 'Неизвестно'),
                                'url': f"https://store.steampowered.com/app/{app_id}",
                                'id': str(app_id),
                                'discount': discount,
                                'original_price': details.get('original_price', 0),
                                'final_price': details.get('final_price', 0),
                                'currency': details.get('currency', 'RUB'),
                                'platform': 'Steam'
                            })
                            print(f"✅ Найдена скидка {discount}%: {details.get('name')}")

        url = "https://store.steampowered.com/api/featuredcategories/"
        response = requests.get(url, headers=headers, timeout=15)

        if response.status_code == 200:
            data = response.json()

            categories = ['specials', 'coming_soon', 'top_sellers', 'new_releases', 'discounts']

            for category in categories:
                if category in data:
                    if isinstance(data[category], dict):
                        items = data[category].get('items', [])
                    else:
                        items = data[category]

                    for game in items:
                        discount = game.get('discount_percent', 0)
                        if discount >= min_discount and discount < 100:
                            app_id = game.get('id')
                            if app_id and str(app_id) not in found_ids:
                                found_ids.add(str(app_id))
                                discounted_games.append({
                                    'title': game.get('name', 'Неизвестно'),
                                    'url': f"https://store.steampowered.com/app/{app_id}",
                                    'id': str(app_id),
                                    'discount': discount,
                                    'original_price': game.get('original_price', 0) // 100 if game.get(
                                        'original_price') else 0,
                                    'final_price': game.get('final_price', 0) // 100 if game.get('final_price') else 0,
                                    'currency': 'RUB',
                                    'platform': 'Steam'
                                })
                                print(f"✅ Найдена скидка {discount}%: {game.get('name')}")

        discounted_games.sort(key=lambda x: x['discount'], reverse=True)

        unique_games = []
        seen_titles = set()
        for game in discounted_games:
            if game['title'] not in seen_titles:
                seen_titles.add(game['title'])
                unique_games.append(game)

        discounted_games = unique_games[:10]

        print(f"\n📊 ВСЕГО НАЙДЕНО: {len(discounted_games)} игр со скидкой 90%+")

    except Exception as e:
        print(f"❌ Ошибка при проверке скидок Steam: {e}")

    return discounted_games


# =============================================================================
# EPIC GAMES ФУНКЦИИ
# =============================================================================

def check_epic_free_games():
    """Ищет бесплатные игры в Epic Games Store"""
    free_games = []

    try:
        url = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
        params = {
            'locale': 'ru-RU',
            'country': 'RU',
            'allowCountries': 'RU'
        }

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        response = requests.get(url, params=params, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()

            if 'data' in data and 'Catalog' in data['data']:
                games = data['data']['Catalog']['searchStore']['elements']

                for game in games:
                    promotions = game.get('promotions')
                    if promotions:
                        promo_offers = promotions.get('promotionalOffers')

                        if promo_offers and len(promo_offers) > 0:
                            offers = promo_offers[0].get('promotionalOffers', [])

                            if len(offers) > 0:
                                price_info = game.get('price', {}).get('totalPrice', {})
                                original_price = price_info.get('originalPrice', 0)
                                current_price = price_info.get('discountPrice', 0)

                                if original_price > 0 and current_price == 0:
                                    game_id = game.get('id')
                                    end_date = offers[0].get('endDate', '')

                                    free_games.append({
                                        'title': game.get('title', 'Неизвестно'),
                                        'url': f"https://store.epicgames.com/ru/free-games",
                                        'id': game_id,
                                        'platform': 'Epic Games',
                                        'end_date': end_date,
                                        'description': game.get('description', ''),
                                        'image': game.get('keyImages', [{}])[0].get('url', '') if game.get(
                                            'keyImages') else ''
                                    })

    except Exception as e:
        print(f"❌ Ошибка при проверке Epic Games: {e}")

    return free_games


def format_epic_end_date(end_date):
    """Форматирует дату окончания раздачи Epic Games"""
    try:
        if end_date:
            dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            return dt.strftime('%d.%m.%Y %H:%M')
    except:
        pass
    return 'Неизвестно'


# =============================================================================
# ФОРМАТИРОВАНИЕ СООБЩЕНИЙ
# =============================================================================

def format_game_message(game, game_type='free'):
    """Форматирует сообщение об игре"""
    if game['platform'] == 'Steam':
        if game_type == 'free':
            return (
                f"🎮 <b>{game['title']}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 <b>Цена:</b> <s>Обычная</s> → <b>БЕСПЛАТНО!</b>\n"
                f"🎯 <b>Тип:</b> Временная акция\n"
                f"🔗 <b>Ссылка:</b> {game['url']}\n\n"
                f"⏰ <i>Успей забрать!</i>"
            )
        else:
            return (
                f"🔥 <b>{game['title']}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 <b>Цена:</b> <s>{game['original_price']} ₽</s>\n"
                f"💎 <b>Сейчас:</b> <b>{game['final_price']} ₽</b> (-{game['discount']}%)\n"
                f"🔗 <b>Ссылка:</b> {game['url']}\n\n"
                f"⭐ <i>Огромная скидка!</i>"
            )
    else:
        end_date = format_epic_end_date(game.get('end_date', ''))
        return (
            f"🎮 <b>{game['title']}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Цена:</b> <s>999 ₽</s> → <b>БЕСПЛАТНО!</b>\n"
            f"📅 <b>До:</b> {end_date}\n"
            f"🔗 <b>Ссылка:</b> {game['url']}\n\n"
            f"⭐ <i>Забери бесплатно навсегда!</i>"
        )


# =============================================================================
# TELEGRAM - КОМАНДЫ
# =============================================================================

async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /myid - Показать ваш Telegram ID"""
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"🆔 Ваш Telegram ID: <code>{chat_id}</code>",
        parse_mode='HTML'
    )


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /broadcast - Отправить сообщение всем (только для админа)"""
    chat_id = update.effective_chat.id

    if chat_id != YOUR_ADMIN_ID:
        await update.message.reply_text("❌ У вас нет прав на эту команду")
        return

    if not context.args:
        await update.message.reply_text(
            "❌ Использование: /broadcast Текст сообщения\n\n"
            "Пример: /broadcast 🎮 Внимание! Новая раздача!"
        )
        return

    message_text = ' '.join(context.args)

    status_msg = await update.message.reply_text("📨 Начинаю рассылку...")

    success = await broadcast_message(context.bot, message_text)

    await status_msg.edit_text(f"✅ Рассылка завершена!\nОтправлено: {success} пользователям")


async def broadcast_message(bot, text, parse_mode='HTML'):
    """Отправляет сообщение всем подписанным пользователям"""
    users = load_users()
    success_count = 0
    failed_users = []

    for user_id in users["users"]:
        try:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=False
            )
            success_count += 1
            await asyncio.sleep(0.05)
        except TelegramError as e:
            print(f"⚠️ Ошибка отправки {user_id}: {e}")
            if "Forbidden" in str(e) or "blocked" in str(e).lower():
                failed_users.append(user_id)

    if failed_users:
        for user_id in failed_users:
            remove_user(user_id)
        print(f"🧹 Удалено {len(failed_users)} пользователей, заблокировавших бота")

    print(f"✅ Сообщение отправлено {success_count}/{len(users['users'])} пользователям")
    return success_count


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start - Подписаться"""
    chat_id = update.effective_chat.id

    if add_user(chat_id):
        await update.message.reply_text(
            "✅ <b>Подписка оформлена!</b> 🎮\n\n"
            "Я буду уведомлять тебя о новых бесплатных играх и больших скидках в:\n"
            "• Steam\n"
            "• Epic Games Store\n\n"
            "✅ <b>Ты в деле! Жди уведомлений!</b>",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            "ℹ️ Ты уже подписан на уведомления.\n\n"
            "Я пришлю тебе сообщение, как только появится новая бесплатная игра!",
            parse_mode='HTML'
        )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stop - Отписаться от бота"""
    chat_id = update.effective_chat.id

    if remove_user(chat_id):
        await update.message.reply_text(
            "❌ <b>Подписка отменена</b>\n\n"
            "Ты больше не будешь получать уведомления о бесплатных играх и скидках.\n\n"
            "Используй /start чтобы подписаться снова 😊",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            "ℹ️ Ты не был подписан.\n\n"
            "Используй /start чтобы оформить подписку",
            parse_mode='HTML'
        )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help - Показать помощь"""
    await update.message.reply_text(
        "🤖 <b>Бот бесплатных игр</b>\n\n"
        "<b>Что я делаю:</b>\n"
        "• Автоматически проверяю новые раздачи КАЖДЫЙ ЧАС\n"
        "• Мгновенно присылаю уведомления о бесплатных играх\n"
        "• Ищу скидки 90% и выше в Steam\n\n"
        "<b>Команды:</b>\n"
        "/start - Подписаться на уведомления\n"
        "/stop - Отписаться от уведомлений\n"
        "/myid - Узнать свой Telegram ID\n"
        "/help - Показать это сообщение\n\n"
        "✅ <b>Подписывайся и получай игры бесплатно!</b>",
        parse_mode='HTML'
    )


# =============================================================================
# ОТПРАВКА УВЕДОМЛЕНИЙ
# =============================================================================

async def send_notification_to_all(bot, game_info, game_type='free'):
    """Отправляет уведомление всем подписанным пользователям с учетом настроек"""
    users = load_users()
    message = format_game_message(game_info, game_type)

    success_count = 0
    failed_users = []

    for user_id in users["users"]:
        if game_type == 'free' and not get_user_setting(user_id, "notify_free", True):
            continue
        if game_type == 'discount' and not get_user_setting(user_id, "notify_discounts", False):
            continue

        try:
            await bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode='HTML',
                disable_web_page_preview=False
            )
            success_count += 1
            await asyncio.sleep(0.05)
        except TelegramError as e:
            print(f"⚠️ Ошибка отправки {user_id}: {e}")
            if "Forbidden" in str(e) or "blocked" in str(e).lower():
                failed_users.append(user_id)

    if failed_users:
        for user_id in failed_users:
            remove_user(user_id)
        print(f"🧹 Удалено {len(failed_users)} пользователей, заблокировавших бота")

    print(f"✓ Уведомление отправлено {success_count}/{len(users['users'])} пользователям: {game_info['title']}")
    return success_count > 0


# =============================================================================
# СИГНАЛЫ И КОРРЕКТНОЕ ЗАВЕРШЕНИЕ
# =============================================================================

shutdown_flag = False


def signal_handler(sig, frame):
    """Обработчик для корректного завершения бота"""
    global shutdown_flag
    print("\n\n⚠️  Бот остановлен пользователем")
    print("🔄 Закрываю соединения...")
    shutdown_flag = True
    sys.exit(0)


# =============================================================================
# MAIN - ПАРАЛЛЕЛЬНЫЕ ЗАДАЧИ
# =============================================================================

async def bot_listener():
    """Задача 1: Слушает команды пользователей"""
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("myid", cmd_myid))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))

    await app.initialize()
    await app.start()

    print("🎧 Бот слушает команды пользователей...")
    print(f"👑 Админ ID: {YOUR_ADMIN_ID}")
    print("📋 Доступные команды: /start, /stop, /help, /myid, /broadcast\n")

    await app.updater.start_polling()

    try:
        while not shutdown_flag:
            await asyncio.sleep(1)
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


async def games_checker():
    """Задача 2: Периодически проверяет бесплатные игры"""
    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    await asyncio.sleep(5)
    print("🔍 Запуск проверщика игр...\n")

    notified_games = load_notified_games()
    notified_games = clean_old_games(notified_games, days=7)
    save_notified_games(notified_games)

    while not shutdown_flag:
        try:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Проверяю предложения...")

            print("🔍 Проверяю Steam (бесплатные)...")
            steam_free = check_steam_free_games()

            for game in steam_free:
                if game['id'] not in notified_games['steam']:
                    if await send_notification_to_all(bot, game, 'free'):
                        notified_games['steam'][game['id']] = time.time()
                        save_notified_games(notified_games)

            print("🔍 Проверяю Epic Games...")
            epic_games = check_epic_free_games()

            for game in epic_games:
                if game['id'] not in notified_games['epic']:
                    if await send_notification_to_all(bot, game, 'free'):
                        notified_games['epic'][game['id']] = time.time()
                        save_notified_games(notified_games)

            print("🔍 Проверяю большие скидки в Steam...")
            discounts = check_steam_discounts()

            for game in discounts:
                game_id = f"discount_{game['id']}"
                if game_id not in notified_games['steam']:
                    if await send_notification_to_all(bot, game, 'discount'):
                        notified_games['steam'][game_id] = time.time()
                        save_notified_games(notified_games)

            notified_games = clean_old_games(notified_games, days=7)
            save_notified_games(notified_games)

            print(f"⏳ Следующая проверка через {CHECK_INTERVAL // 60} минут...\n")

            for i in range(CHECK_INTERVAL // 10):
                if shutdown_flag:
                    break
                await asyncio.sleep(10)

        except Exception as e:
            print(f"❌ Ошибка в проверщике игр: {e}")
            await asyncio.sleep(60)


async def main():
    """Главная функция"""
    if TELEGRAM_BOT_TOKEN == "TU_TOKEN_DE_BOT":
        print("❌ ОШИБКА: Настрой TELEGRAM_BOT_TOKEN")
        return

    print("=" * 60)
    print("🤖 БОТ БЕСПЛАТНЫХ ИГР - Запуск...")
    print("=" * 60)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print(f"⏱️  Интервал проверки: {CHECK_INTERVAL // 60} минут")
    print(f"📁 Файл пользователей: {USERS_FILE}")
    print(f"📁 Файл настроек: {USER_SETTINGS_FILE}")
    print(f"📁 Файл игр: {NOTIFIED_GAMES_FILE}\n")
    print("💡 Нажми Ctrl+C для остановки бота\n")

    try:
        await asyncio.gather(
            bot_listener(),
            games_checker()
        )
    except KeyboardInterrupt:
        print("\n⚠️  Бот остановлен пользователем")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️  Бот успешно остановлен")
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")