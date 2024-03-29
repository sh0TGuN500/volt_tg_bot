import logging
import time
import os
import psycopg2 as sq

from math import ceil

from telegram import (
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
    Update,
    LabeledPrice,
    Message
)
from telegram.error import BadRequest
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    ConversationHandler,
    CallbackContext,
    PreCheckoutQueryHandler
)

DEBUG = False

if DEBUG:
    from owner_data import *
else:
    DATABASE_URL = os.environ.get('DATABASE_URL')
    BOT_TOKEN = os.environ['BOT_TOKEN']
    public_liqpay_sandbox = os.environ['public_liqpay_sandbox']
    bot_dev = int(os.environ['bot_dev'])
    bot_owner = int(os.environ['bot_owner'])
    forward_to = [bot_dev, bot_owner]


# BLACKLIST and couriers update and optimization
def blacklist_update(courier_reload=False) -> list:
    with sq.connect(DATABASE_URL) as blacklist:
        cursor = blacklist.cursor()
    cursor.execute("SELECT id FROM  users WHERE blocked = true")
    black_list = [i[0] for i in cursor.fetchall()]
    if courier_reload:
        cursor.execute("UPDATE couriers SET ready = false, is_free = true WHERE ready = true OR is_free = false")
    blacklist.commit()
    return black_list


BLACK_LIST = blacklist_update(True)

# Quick access da1ta-list
data_dict = dict()

separator = '🔽' * 14 + '\n'

# Enable logging
logging.basicConfig(
    format='%(name)s - %(levelname)s - %(message)s', level=logging.INFO
)  # %(asctime)s -  , filename='bot.log'

logger = logging.getLogger(__name__)


# Base variables for each reply function
def base(update_message: Message) -> tuple:
    user = update_message if update_message else None
    from_user = user.from_user if user else None
    return user, from_user


# Anti-space text filter
def space_filter(text: str) -> str:
    return ' '.join(text.split())


# Log func
def log(role, status, user, manual=None, sf=True) -> None:
    if manual:
        message: str = manual
    elif sf:
        message = space_filter(user.text)
    else:
        message: str = user.text if user.text else user.location
    user_name = user.from_user.username
    if user_name:
        user_data = (role, user.from_user.id, user.from_user.full_name,
                     user_name, status, message)
        logger.info('{0}: |{1}| {2}({3}): {4}: {5}'.format(*user_data))
    else:
        user_data = (role, user.from_user.id, user.from_user.full_name,
                     status, message)
        logger.info('{0}: |{1}| {2}: {3}: {4}'.format(*user_data))


def format_cour_order(cour_list_forward: list) -> list:
    cour_list_forward = [separator] + cour_list_forward
    cour_list_forward[1] = '🍲 Замовлення: ' + cour_list_forward[1]
    cour_list_forward[2] = '📅 Час доставки: ' + cour_list_forward[2]
    cour_list_forward[3] = '👩‍❤️‍👨 ПіБ: ' + cour_list_forward[3]
    cour_list_forward[5] = '📱 Телефон: ' + cour_list_forward[5]
    return cour_list_forward


# Courier problem-button part
def courier_problem_module(user, from_user, order_id, stage):
    data_dict[from_user.id]['check_message'] = user.message_id
    problem_message = f'Замовлення #{order_id}\nСтадія: {stage}\nВідмова' if order_id else user.text
    data_dict[from_user.id]['problem'] = problem_message
    log('Courier', 'Status', user)
    reply = 'Вкажіть причину' if user.text == button8 else 'Замовлення скасовано. Вкажіть причину'
    method: int = COURIER_PROBLEM
    reply_markup = help_markup
    with sq.connect(DATABASE_URL) as database:
        cur = database.cursor()
    if order_id:
        cur.execute(f"UPDATE orders SET courier_id = NULL WHERE pk = {order_id}")
    courier_status_filter = [True, False, from_user.id]
    cur.execute("UPDATE couriers SET is_free = %s, ready = %s WHERE telegram_id = %s", courier_status_filter)
    database.commit()
    return reply, reply_markup, method


# Pay function
def pay_preprocessor(user, order_id, chat_id, pay_value, pay_type, context):
    if pay_type == 1:
        title = "Оплата замовлення"
        description = f'Замовлення #{order_id} \n' \
                      f'Вартість продукції: {pay_value[0] / 100} грн \n' \
                      f'Вартість доставки: {pay_value[1] / 100} грн \n'
        # price * 100 so as to include 2 decimal points
        prices = [
            LabeledPrice('Продукція', pay_value[0]),
            LabeledPrice('Доставка', pay_value[1])
        ]
        log_text = f'Payment order: {order_id}, production: {pay_value[0]}, delivery: {pay_value[1]}'

    elif pay_type == 2:
        title = 'Чайові'
        prices = [LabeledPrice(title, pay_value * 100)]
        if order_id:
            description = f'Чайові до замовлення #{order_id}'
            log_text = f'Tip payment: {pay_value}, order: {order_id}'
        else:
            description = 'Чайові для власника сервісу'
            log_text = f'Tip payment: {pay_value}'

    # select a payload just for you to recognize its the donation from your bot
    payload = "Custom-Payload"
    # In order to get a provider_token see https://core.telegram.org/bots/payments#getting-a-token
    provider_token = public_liqpay_sandbox
    # price in hryvnias
    currency = "UAH"
    # optionally pass need_name=True, need_phone_number=True,
    # need_email=True, need_shipping_address=True, is_flexible=True
    context.bot.send_invoice(
        chat_id, title, description, payload, provider_token, currency, prices
    )
    reply = 'Здійснюється процес оплати...'
    reply_markup = ReplyKeyboardRemove()
    method: None = None
    log('Client', 'Tip', user, manual=log_text)

    return reply, reply_markup, method


def lol(lst, sz):
    return [lst[i:i + sz] for i in range(0, len(lst), sz)]


def keys_format(keys_list):
    line_len = ceil(len(keys_list) / ceil(len(keys_list) / 12))
    ready_keyboard = lol(keys_list, line_len)
    ready_keyboard.append([button16])
    return ready_keyboard


CLIENT, ORDER, NAME, LOCATION, CONTACT, HELP, ADMIN, COURIER, START_COUNT, PAY_TYPE, COURIER_LIST, \
SEND_COURIER, COURIER_READY, PURCHASE, COURIER_PROBLEM, DELIVERY, CANCELED, CANCEL_CALLBACK, REVIEW, \
END_COUNT, TIP, CONFIRM_PAY, DELIVERY_TIME = range(23)

button0 = '🍲 Замовлення'
button1 = '🆘 Підтримка'
button2 = 'Список нових замовлень'
button3 = 'Список незавершених замовлень'
button4 = 'Розрахувати чек'
button5 = 'Готовий'
button6 = 'Прийняти замовлення'
button7 = 'Відхилити замовлення'
button8 = 'Не готовий'
button9 = '🆘 Виникла проблема'
button10 = 'Придбав товари'
button11 = 'Замовлення виконав'
button12 = 'Оновити BLACKLIST'
button13 = 'Замовлення сформоване'
# button14 = 'Статус оплати'
button15 = 'Доставку виконав'
button16 = '<< Назад'
button17 = '💸 Оплатити замовлення'
button18 = '🍵 Чайові'
button19 = '⭐ Залишити відгук до останнього замовлення'
button20 = 'Відправити повідомлення'
button21 = 'Оплату отримав'
button22 = 'Безготівкова оплата'
button23 = 'Оплата готівкою'

client_keyboard = [
    [button0, button1],
    [button19],
    [button17, button18]
]

help_keyboard = [
    [button20],
    [button16]
]

payment_type_keyboard = [
    [button22],
    [button23]
]

admin_keyboard = [
    [button2],
    [button3],
    [button7],
    [button4],
    [button12]
]

courier_keyboard = [
    [KeyboardButton('Готовий', request_location=True)]
]

order_courier_keyboard = [
    [button6],
    [button7],
    [button9]
]

purchase_keyboard = [
    [button13],
    [button9]
]

delivery_keyboard = [
    [button15],
    [button9]
]

client_markup = ReplyKeyboardMarkup(client_keyboard, one_time_keyboard=True, resize_keyboard=True)

payment_type_markup = ReplyKeyboardMarkup(payment_type_keyboard, one_time_keyboard=True, resize_keyboard=True)

help_markup = ReplyKeyboardMarkup(help_keyboard, one_time_keyboard=True, resize_keyboard=True)

admin_markup = ReplyKeyboardMarkup(admin_keyboard, one_time_keyboard=True, resize_keyboard=True)

back_markup = ReplyKeyboardMarkup([[button16]], one_time_keyboard=True, resize_keyboard=True)

courier_markup = ReplyKeyboardMarkup(courier_keyboard, one_time_keyboard=True, resize_keyboard=True)

ready_courier_markup = ReplyKeyboardMarkup([[button8]], one_time_keyboard=True, resize_keyboard=True)

order_courier_markup = ReplyKeyboardMarkup(order_courier_keyboard, one_time_keyboard=True, resize_keyboard=True)

purchase_markup = ReplyKeyboardMarkup(purchase_keyboard, one_time_keyboard=True, resize_keyboard=True)

delivery_markup = ReplyKeyboardMarkup(delivery_keyboard, one_time_keyboard=True, resize_keyboard=True)

courier_problem_markup = ReplyKeyboardMarkup([[button9]], one_time_keyboard=True, resize_keyboard=True)

confirm_pay_markup = ReplyKeyboardMarkup([[button21], [button9]], one_time_keyboard=True, resize_keyboard=True)


def start(update: Update, context: CallbackContext) -> int or None:
    if update.message.from_user.id in BLACK_LIST:
        while True:
            time.sleep(86400)
    user, from_user = base(update.message)
    with sq.connect(DATABASE_URL) as database:
        cur = database.cursor()
    cur.execute("SELECT id FROM users WHERE id = %s", (from_user.id,))
    db_user_id = cur.fetchone()
    user_data = (from_user.id, from_user.full_name, from_user.username)

    if not db_user_id:
        cur.execute("INSERT INTO users (id, full_name, username) "
                    "VALUES (%s, %s, %s)", user_data)
    else:
        cur.execute("UPDATE users SET full_name = %s, username = %s "
                    "WHERE id = %s", (from_user.full_name, from_user.username, from_user.id))

    database.commit()

    cur.execute("SELECT telegram_id FROM couriers")
    couriers = [i[0] for i in cur.fetchall()]

    if from_user.id in forward_to:
        role = 'Admin'
        reply = f'Приветствую Вас, {user_data[1]}-Чемпион !\nЧемпион зверей !!! Чемпион людей !!! ✅'
        method: int = ADMIN
        reply_markup = admin_markup

    elif from_user.id in couriers:
        role = 'Courier'
        reply = f'Вітаю, кур\'єр доставки Volt, {user_data[1]}.' \
                '\nДотримуйтесь умов карантину\nБажаю гарного робочого дня! ✅'
        method: int = COURIER
        reply_markup = courier_markup

    else:
        role = 'Client'
        reply = f'Вітаю {user_data[1]}!\nТут Ви можете сформувати своє замовлення, а ми,' \
                '\nв свою чергу, забезпечимо його доставку. ✅'
        method: int = CLIENT
        reply_markup = client_markup

    log(role, 'Press', user)

    user.reply_text(reply, reply_markup=reply_markup)

    return method


# #################################################################################################################### #
# #################################################=ADMIN=PART=####################################################### #
# #################################################################################################################### #


def admin_menu(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    log('Admin', 'Admin menu', user)
    data_dict[from_user.id] = {'order_id': '', 'count': '', 'cancel': ''}
    with sq.connect(DATABASE_URL) as database:
        cur = database.cursor()
    global BLACK_LIST
    BLACK_LIST = blacklist_update()
    if user.text in [button2, button3, button4, button7]:
        order_list_keyboard = []

        if user.text == button2:
            orders_filter = [False, False, False]
            cur.execute("SELECT pk FROM orders WHERE courier_id ISNULL "
                        "AND completed = %s AND canceled = %s "
                        "AND purchased = %s", orders_filter)
            orders = [i[0] for i in cur.fetchall()]

        elif user.text == button3:
            orders_filter = [False, False, True]
            cur.execute("SELECT pk, courier_id FROM orders WHERE courier_id ISNULL "
                        "AND completed = %s AND canceled = %s "
                        "AND purchased = %s", orders_filter)
            orders = [i[0] for i in cur.fetchall()]

        elif user.text == button7:
            orders_filter = [False, False]
            cur.execute("SELECT pk FROM orders WHERE completed = %s"
                        " AND canceled = %s", orders_filter)
            orders = [i[0] for i in cur.fetchall()]

        else:
            uncounted_filter = [False, True, False, False]
            cur.execute("SELECT pk FROM orders WHERE counted = %s AND purchased = %s"
                        " AND completed = %s AND canceled = %s", uncounted_filter)
            orders = [i[0] for i in cur.fetchall()]

        if orders:
            order_list = [str(order_id) for order_id in orders]
            order_list_keyboard = keys_format(order_list)
            reply = 'Список замовлень 👇'
            reply_markup = ReplyKeyboardMarkup(order_list_keyboard, one_time_keyboard=True, resize_keyboard=True)
            if user.text in [button2, button3]:
                method: int = COURIER_LIST
            elif user.text == button4:
                method: int = START_COUNT
            else:
                method: int = CANCELED

        else:
            reply = 'Немає замовлень'
            reply_markup = admin_markup
            method: int = ADMIN

    else:
        BLACK_LIST = blacklist_update()
        reply = 'BLACKLIST оновлено'
        reply_markup = admin_markup
        method: int = ADMIN

    user.reply_text(reply, reply_markup=reply_markup)

    return method


def courier_list(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    log('Admin', 'Chose order', user)
    with sq.connect(DATABASE_URL) as database:
        cur = database.cursor()
    couriers_filter = [True, True]
    cur.execute("SELECT pk, name FROM couriers WHERE is_free = %s"
                " AND ready = %s", couriers_filter)
    couriers = cur.fetchall()

    if couriers and user.text != button16:
        data_dict[from_user.id]['order_id'] = user.text
        pk_list = [str(pk[0]) for pk in couriers]
        order_list_keyboard = keys_format(pk_list)
        reply = '\n'.join([f'{i[0]}: {i[1]}' for i in couriers])
        method: int = SEND_COURIER
        reply_markup = ReplyKeyboardMarkup(
            order_list_keyboard, one_time_keyboard=True, resize_keyboard=True
        )
    else:
        reply = '↩️' if user.text == button16 else "Немає вільних кур'єрів"
        method: int = ADMIN
        reply_markup = admin_markup
    user.reply_text(reply, reply_markup=reply_markup)

    return method


def send_courier(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    log('Admin', 'Chose courier', user)
    if user.text != button16:
        with sq.connect(DATABASE_URL) as database:
            cur = database.cursor()
        update_couriers_filter = [False, user.text]
        cur.execute("UPDATE couriers SET is_free = %s WHERE pk = %s", update_couriers_filter)
        order_id = data_dict[from_user.id]['order_id']
        cur.execute("SELECT telegram_id, name FROM couriers "
                    "WHERE pk = %s", [user.text])
        courier_id, courier_name = cur.fetchone()
        if courier_id in data_dict:
            data_dict[courier_id]['order_id'] = order_id
        else:
            data_dict[courier_id] = {'order_id': order_id}
        cur.execute("UPDATE orders SET courier_id = %s WHERE pk = %s", [courier_id, order_id])
        database.commit()

        cur.execute("SELECT text, delivery_time, full_name, adress, phone FROM orders"
                    " WHERE pk = %s", [order_id])
        cour_forward = list(cur.fetchone())
        cour_forward = format_cour_order(cour_forward)
        if len(cour_forward[4].split('  ')) == 2:
            coord = cour_forward.pop(4).split('  ')
            user.bot.send_message(chat_id=courier_id, text='\n\n'.join(map(str, cour_forward)))
            user.bot.send_location(chat_id=courier_id, latitude=coord[0], longitude=coord[1],
                                   reply_markup=order_courier_markup)
        else:
            cour_forward[4] = '🏡 Адреса: ' + cour_forward[4]
            user.bot.send_message(chat_id=courier_id, text='\n\n'.join(map(str, cour_forward)),
                                  reply_markup=order_courier_markup)
        reply = f'Кур\'єру {courier_name} назначено замовлення #{order_id}'
        for chat in forward_to:
            user.bot.send_message(chat_id=chat, text=reply) if chat != from_user.id else None
    elif user.text == button16:
        reply = '↩️'
    user.reply_text(reply, reply_markup=admin_markup)

    return ADMIN


def start_count(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    if user.text == button16:
        log('Admin', 'Turn back', user)
        reply = '↩️'
        reply_markup = admin_markup
        method = ADMIN
    else:
        message = f'Адмін {from_user.full_name} розраховує замовлення #{user.text}'
        for chat in forward_to:
            user.bot.send_message(chat_id=chat, text=message) if chat != from_user.id else None
        try:
            order_id: int = int(user.text)
        except ValueError:
            reply = f'Ви ввели "{user.text}", а потрібно ввети ціле число від 0 до 9\'999'
            reply_markup = back_markup
            method: int = START_COUNT
            log('Client', 'Order for counting', user, manual=f'ValueError: {user.text}')
        else:
            log('Admin', 'Order for counting', user)
            data_dict[from_user.id]['count'] = order_id
            reply = 'Вартість чеку і доставка 12.23 45,56:'
            reply_markup = back_markup
            method = END_COUNT
            '''#'''
    user.reply_text(reply, reply_markup=reply_markup)

    return method


def end_count(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    if user.text == button16:
        log('Admin', 'Turn back', user)
        reply = '↩️'
    else:
        try:
            money_correct = [int(float(i.replace(',', '.')) * 100) for i in user.text.split(' ')]
        except ValueError:
            text = f'Ти ввів {user.text}, а потрібно ввести два числа,' \
                   '\nЧек потім доставка, через пробіл (12,3 4.56)!\nВводи іще раз:'
            user.bot.send_message(text=text, chat_id=from_user.id)
            return END_COUNT

        log('Admin', 'Counting result', user)
        if len(money_correct) != 2:
            text = f'Ти ввів {user.text}, а потрібно ввести два числа,' \
                   '\nЧек потім доставка, через пробіл (12,3 4.56)!\nВводи іще раз:'
            user.bot.send_message(text=text, chat_id=from_user.id)
            return END_COUNT
        order_id = data_dict[from_user.id]['count']
        with sq.connect(DATABASE_URL) as database:
            cur = database.cursor()
        money_correct.append(True)
        money_correct.append(order_id)
        cur.execute("UPDATE orders SET products_price = %s, delivery_price = %s, "
                    f"counted = %s WHERE pk = %s", money_correct)
        database.commit()
        cur.execute("SELECT user_id, courier_id, payment_type "
                    "FROM orders WHERE pk = %s", [order_id])
        client_id, courier_id, pay_type = cur.fetchone()
        check, delivery = [float(i.replace(',', '.')) for i in user.text.split(' ')]
        text = f'Вартість вашого чеку: {check} грн\nВартість доставки: {delivery} грн' \
               f'\nСума до сплати: {round(check + delivery, 2)} грн'
        user.bot.send_message(text=text, chat_id=client_id)

        cur.execute("SELECT has_check, courier_id, user_id "
                    "FROM orders WHERE pk = %s", [order_id])
        check_list, courier_id, client_id = cur.fetchone()
        for check in eval(check_list):
            user.bot.forward_message(from_chat_id=courier_id, chat_id=client_id, message_id=check)
        if not pay_type:
            user.bot.send_message(text=text, chat_id=courier_id, reply_markup=confirm_pay_markup)
        reply = f'Замовлення #{order_id} розраховане, очікування оплати...'
        for chat in forward_to:
            user.bot.send_message(chat_id=chat, text=reply) if chat != from_user.id else None
    user.reply_text(reply, reply_markup=admin_markup)

    return ADMIN


def cancel_order(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    log('Admin', 'Cancel order', user)
    if user.text == button16:
        reply = '↩️'
        method: int = ADMIN
        reply_markup = admin_markup
    else:
        with sq.connect(DATABASE_URL) as database:
            cur = database.cursor()
        cur.execute("SELECT user_id, full_name, pk FROM orders "
                    "WHERE pk = %s", [user.text])
        client_id, client_name, order_id = cur.fetchone()
        data_dict[from_user.id]['cancel'] = [client_id, client_name, order_id]
        update_orders_filter = [True, user.text]
        cur.execute("UPDATE orders SET canceled = %s WHERE pk = %s", update_orders_filter)
        database.commit()
        reply = f'Замовлення # {user.text} скасовано, причина скасування:'
        method: int = CANCEL_CALLBACK
        reply_markup = ReplyKeyboardRemove()
    user.reply_text(reply, reply_markup=reply_markup)

    return method


def client_cancel_callback(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    log('Admin', 'Cancel callback', user)
    client_id, client_name, order_id = data_dict[from_user.id]['cancel']
    message = f'Шановний {client_name},\nВаше замовлення #{order_id} скасовано\nПричина:\n{user.text}'
    user.bot.send_message(text=message, chat_id=client_id)
    user.reply_text('Повідомлення відправленно', reply_markup=admin_markup)

    return ADMIN


# #################################################################################################################### #
# ##############################################=COURIER=PART=######################################################## #
# #################################################################################################################### #


def courier_menu(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    with sq.connect(DATABASE_URL) as database:
        cur = database.cursor()
    cur.execute("SELECT name FROM couriers WHERE telegram_id = %s", [from_user.id])
    courier_name: str = cur.fetchone()[0]
    update_couriers_filter = [True, True, from_user.id]
    cur.execute("UPDATE couriers SET ready = %s, is_free = %s WHERE telegram_id = %s", update_couriers_filter)
    database.commit()
    order_exist_filter = [from_user.id, False, False]
    cur.execute("SELECT pk FROM orders WHERE courier_id = %s"
                " AND completed = %s AND canceled = %s", order_exist_filter)
    order_exist: tuple = cur.fetchone()
    text = f'{courier_name} готовий'
    for chat in forward_to:
        user.bot.send_message(text=text, chat_id=chat)
        user.bot.send_location(location=user.location, chat_id=chat)
    log('Courier', 'Status', user, manual='Ready')
    if order_exist:
        data_dict[from_user.id] = {'order_id': order_exist[0]}
        cur.execute("SELECT text, delivery_time, full_name, adress, phone FROM orders"
                    " WHERE pk = %s", [order_exist[0]])
        cour_forward = list(cur.fetchone())
        cour_forward = format_cour_order(cour_forward)
        if len(cour_forward[4].split('  ')) == 2:
            coord = cour_forward.pop(4).split('  ')
            user.bot.send_message(chat_id=user.chat_id, text='\n\n'.join(map(str, cour_forward)))
            user.bot.send_location(chat_id=user.chat_id, latitude=coord[0], longitude=coord[1],
                                   reply_markup=order_courier_markup)
        else:
            cour_forward[4] = '🏡 Адреса: ' + cour_forward[4]
            user.bot.send_message(chat_id=user.chat_id, text='\n\n'.join(map(str, cour_forward)),
                                  reply_markup=order_courier_markup)
    reply_markup = order_courier_markup if order_exist else ready_courier_markup
    user.reply_text('Я відправлю тобі повідомлення, як тільки з\'явиться замовник 🗿',
                    reply_markup=reply_markup)
    return COURIER_READY


def ready_courier_menu(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    if from_user.id in data_dict:
        data_dict[from_user.id]['check_message'] = user.message_id
        if 'order_id' in data_dict[from_user.id]:
            order_id = data_dict[from_user.id]['order_id']
        else:
            order_id = False
    else:
        data_dict[from_user.id] = {'check_message': user.message_id}
        order_id = False
    with sq.connect(DATABASE_URL) as database:
        cur = database.cursor()
    if order_id and user.text == button6:
        message = f'{from_user.full_name} прийняв замовлення #{order_id}'
        for chat in forward_to:
            user.bot.send_message(chat_id=chat, text=message)
        cur.execute("SELECT payment_type, purchased, has_check, counted, paid "
                    "FROM orders WHERE pk = %s", [order_id])
        order_context: tuple = cur.fetchone()
        if order_context[1]:
            reply = f'Замовлення #{order_id}:\nПридбане\nТип оплати: '
            reply += 'безготівковий' if order_context[0] else 'готівка'
            log('Courier', 'Status', user, sf=False, manual='Resume delivery')
            reply_markup = courier_problem_markup
            method: int = DELIVERY
            if order_context[2]:
                reply += '\nЧек отриманий'
                if not order_context[0]:
                    method: int = CONFIRM_PAY
                if order_context[3]:
                    reply += '\nПлатіж розрахований'
                    if not order_context[0]:
                        reply_markup = confirm_pay_markup
                    if order_context[4]:
                        reply_markup = delivery_markup
                        method: int = DELIVERY
                        reply += '\nТа оплачений'
        else:
            log('Courier', 'Status', user, manual='Purchasing')
            reply = 'Направляйтесь до найближчої торгової точки яка видає чеки,\n' \
                    'І після закупівлі всіх товарів надішліть фото чеку! 📸'
            method: int = PURCHASE
            reply_markup = purchase_markup
        cur.execute("SELECT user_id FROM orders WHERE pk = %s", [order_id])
        client_id: int = cur.fetchone()[0]
        message = 'Кур\'єр ' + message
        user.bot.send_message(chat_id=client_id, text=message)
    elif user.text in [button7, button8, button9]:
        reply, reply_markup, method = courier_problem_module(user, from_user, order_id, 'Початок')
    database.commit()
    user.reply_text(reply, reply_markup=reply_markup)
    return method


def courier_purchase(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    order_id = data_dict[from_user.id]['order_id']
    with sq.connect(DATABASE_URL) as database:
        cur = database.cursor()
    if user.text == button13:
        check_message = data_dict[from_user.id]['check_message']
        log('Courier', 'Status', user, sf=False, manual='Send checks and delivery')
        update_orders_filter = [True, order_id]
        cur.execute("UPDATE orders SET purchased = %s WHERE pk = %s", update_orders_filter)
        message = f'Чеки до замовлення #{order_id}:'
        check_list = []
        for chat in forward_to:
            check_list.clear()
            user.bot.send_message(chat_id=chat, text=message)
            message_id = check_message + 4
            while user.message_id > message_id > check_message + 2:
                try:
                    user.bot.forward_message(from_chat_id=user.chat_id, chat_id=chat, message_id=message_id)
                except BadRequest:
                    break
                else:
                    check_list.append(message_id)
                    message_id += 1
        cur.execute(f"UPDATE orders SET has_check = '{check_list}' WHERE pk = {order_id}")
        cur.execute(f"SELECT payment_type, paid FROM orders WHERE pk = {order_id}")
        pay_type, paid = cur.fetchone()
        if pay_type:
            reply = ' 🚶🏼 Прямуйте за вказаною адресою, вас вже зачекались!'
            method: int = DELIVERY
            reply_markup = delivery_markup if paid else courier_problem_markup
        else:
            reply = ' 🚶🏼 Прямуй до замовника, він вже зачекався!\n' \
                    'Замовник обрав готівкову оплату, тому тобі потрібно підтвердити її отримання!\n' \
                    'А я розрахую суму і згодом повідомлю її тобі'
            method = CONFIRM_PAY
            reply_markup = courier_problem_markup
    else:
        reply, reply_markup, method = courier_problem_module(user, from_user, order_id, 'Покупка')
    database.commit()
    user.reply_text(reply, reply_markup=reply_markup)

    return method


def confirm_pay(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    log('Courier', 'Status', user, manual='Confirming pay')
    order_id = data_dict[from_user.id]['order_id']
    with sq.connect(DATABASE_URL) as database:
        cur = database.cursor()
    cur.execute(f"SELECT counted FROM orders WHERE pk = {order_id}")
    confirm = cur.fetchone()[0]
    if user.text == button21 and confirm:
        update_orders_filter = [True, order_id]
        cur.execute("UPDATE orders SET paid = %s WHERE pk = %s", update_orders_filter)
        database.commit()
        reply = '✅'
        method: int = DELIVERY
        reply_markup = delivery_markup
        message = f'Кур\'єр {from_user.full_name} підтвердив оплату замовлення #{order_id}'
        for chat in forward_to:
            user.bot.send_message(chat_id=chat, text=message) if chat != from_user.id else None
    elif user.text == button9:
        reply, reply_markup, method = courier_problem_module(user, from_user, order_id, 'Доставка|Оплата замовлення')
    user.reply_text(reply, reply_markup=reply_markup)

    return method


def courier_delivery(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    order_id = data_dict[from_user.id]['order_id']
    with sq.connect(DATABASE_URL) as database:
        cur = database.cursor()
    if user.text == button15:
        log('Courier', 'Status', user, manual='Delivery complete')
        cur.execute(f'SELECT name, pk FROM couriers WHERE telegram_id = {from_user.id}')
        name, cour_id = cur.fetchone()
        message = f'{name} (#{cour_id}) виконав замовлення #{order_id}'
        for chat in forward_to:
            user.bot.send_message(chat_id=chat, text=message)
        update_orders_filter = [True, order_id]
        cur.execute("UPDATE orders SET completed = %s WHERE pk = %s", update_orders_filter)
        update_couriers_filter = [True, True, from_user.id]
        cur.execute("UPDATE couriers SET is_free = %s, ready = %s WHERE telegram_id = %s", update_couriers_filter)
        reply = 'Замовлення успішно виконано'
        method = COURIER_READY
        reply_markup = ready_courier_markup
    elif user.text == button9:
        reply, reply_markup, method = courier_problem_module(user, from_user, order_id, 'Доставка')
    database.commit()

    user.reply_text(reply, reply_markup=reply_markup)

    return method


def courier_problem(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    message = f'{separator}\n👤 Кур\'єр {from_user.full_name}' \
              f'({from_user.username}):\n\n{data_dict[from_user.id]["problem"]}: '
    check_message = data_dict[from_user.id]['check_message']
    for chat in forward_to:
        user.bot.send_message(chat_id=chat, text=message)
        message_id = check_message + 2
        while user.message_id > message_id > check_message + 1:
            try:
                user.bot.forward_message(from_chat_id=user.chat_id, chat_id=chat, message_id=message_id)
            except BadRequest:
                break
            message_id += 1
    log('Courier', 'Problem', user, sf=False, manual='Message sent')
    user.reply_text('Очікуйте відповідь! ☎️', reply_markup=courier_markup)

    return COURIER


# ################################################===========######################################################### #
# ##############################################==CLIENT=PART==####################################################### #
# ################################################===========######################################################### #


def client_menu(update: Update, context: CallbackContext) -> int or None:
    user, from_user = base(update.message)
    log('Client', 'Choice', user)
    user_name = from_user.username
    if user_name:
        message = f'{separator}\n👤 Користувач {from_user.full_name}({user_name}): '
    else:
        message = f'{separator}\n👤 Користувач {from_user.full_name}: '
    data_dict[from_user.id] = {'text': [message], 'forward': [], 'db': [from_user.id],
                               'check_message': user.message_id, 'order': 0, 'pay_type': 0, 'tip_value': 0}
    if user.text == button0:
        reply = '🛍️ Введіть продукцію (в деталях: конкретна назва і кількість), яку би Ви хотіли замовити.'
        method: int = ORDER
        reply_markup = ReplyKeyboardRemove()
    elif user.text == button19:
        with sq.connect(DATABASE_URL) as database:
            cur = database.cursor()
        order_id_filter = [from_user.id, True, True]
        cur.execute("SELECT pk FROM orders WHERE user_id = %s "
                    "AND (completed = %s OR canceled = %s) AND review ISNULL", order_id_filter)
        order_id = cur.fetchone()
        if order_id:
            data_dict[from_user.id]['order']: int = order_id[0]
            reply = f'Відгук до замовлення #{order_id[0]}:'
            method: int = REVIEW
            reply_markup = ReplyKeyboardRemove()
        else:
            reply = 'Ви вже залишили відгук\n' \
                    'Або ще не отримали замовлення'
            method: int = CLIENT
            reply_markup = client_markup
    elif user.text in [button17, button18]:
        reply = 'В розробці'
        reply_markup = client_markup
        method: int = CLIENT
        '''elif user.text == button17:
            with sq.connect(DATABASE_URL) as database:
                cur = database.cursor()
            prices_filter = [1, True, False, from_user.id, False, False]
            prices: list = cur.execute("SELECT products_price, delivery_price, pk FROM orders "
                                       "WHERE payment_type = %s AND counted = %s AND completed = %s "
                                       "AND user_id = %s AND paid = %s AND canceled = %s", prices_filter).fetchall()
            if prices:
                data_dict[from_user.id]['pay_type']: int = 1
                for price in prices:
                    price: list
                    data_dict[from_user.id]['order']: int = price[2]
                    chat_id: int = user.chat_id
                    reply, reply_markup, method = pay_preprocessor(
                        user, price[2], chat_id, prices[:1], 1, context
                    )
            else:
                reply = 'Немає розрахованих платежів'
                method: int = CLIENT
                reply_markup = client_markup
        elif user.text == button18:
            with sq.connect(DATABASE_URL) as database:
                cur = database.cursor()
            orders_filter = [from_user.id, 0, False, True]
            orders = cur.execute("SELECT pk FROM orders WHERE user_id = %s AND tip = %s "
                                 "AND canceled = %s AND completed = %s AND courier_id IS NOT NULL", orders_filter).fetchall()
            if orders:
                data_dict[from_user.id]['order']: int = orders[-1][0]
                reply = f'Будь-ласка, введіть суму чайових в грн, до замовлення #{orders[-1][0]}'
                reply_markup = back_markup
                method = TIP
            else:
                data_dict[from_user.id]['order']: None = None
                reply = 'Замовлень немає. Якщо бажаєте підтримати власника чашкою чаю, ' \
                        'введіть суму чайових від 3 до 27 000 грн цілим числом:'
                reply_markup = back_markup
                method = TIP'''
    else:
        reply = 'Залиште своє повідомлення 💬\n' \
                'Є можливість прикріпити до 10 фотографій'
        method: int = HELP
        reply_markup = help_markup

    user.reply_text(reply, reply_markup=reply_markup)

    return method


def order(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    log('Client', 'Order', user)
    message = space_filter(user.text)
    data_dict[from_user.id]['text'].append(f'{button0}: ' + message)  # [1]
    data_dict[from_user.id]['db'].append(message)
    user.reply_text('📅 Вкажіть орієнтовну час та дату доставки:')

    return DELIVERY_TIME


def delivery_time(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    log('Client', 'Delivery time', user)
    message = space_filter(user.text)
    data_dict[from_user.id]['text'].append('📅 Час доставки: ' + message)  # [1]
    data_dict[from_user.id]['db'].append(message)
    user.reply_text("👩‍❤️‍👨 Свої данні (ПіБ).")

    return NAME


def full_name(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    log('Client', 'Client name', user)
    message = space_filter(user.text)
    data_dict[from_user.id]['text'].append('👩‍❤️‍👨 ПіБ: ' + message)  # [1]
    data_dict[from_user.id]['db'].append(message)
    button = [[KeyboardButton('🗺️ Вказати адресу на карті', request_location=True)]]
    user.reply_text(
        "🏡 Адреса, куди доставити замовлення.",
        reply_markup=ReplyKeyboardMarkup(button, one_time_keyboard=True, resize_keyboard=True)
    )

    return LOCATION


def get_location(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    if user.text:
        text = space_filter(user.text)
        message = '🏡 Адреса: ' + text
        db = text
        tag = 'text'
    else:
        message = user.message_id
        db = f'{user.location.latitude}  {user.location.longitude}'
        tag = 'forward'
    log('Client', 'Location', user, manual=db)
    data_dict[from_user.id][tag].append(message)
    data_dict[from_user.id]['db'].append(db)
    button = [[KeyboardButton('📲 Відправити поточний номер', request_contact=True)]]
    user.reply_text(
        '📱 Номер мобільного телефону.',
        reply_markup=ReplyKeyboardMarkup(button, one_time_keyboard=True, resize_keyboard=True)
    )

    return CONTACT


def get_contact(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    if user.text:
        text = space_filter(user.text)
        message = '📱 Телефон: ' + text
        db = text
        meta = 'text'
    else:
        message = user.message_id
        db = user.contact.phone_number
        meta = 'forward'

    log('Client', 'Phone', user, manual=db)

    data_dict[from_user.id][meta].append(message)
    data_dict[from_user.id]['db'].append(db)

    user.reply_text(
        ' 💸 Будь-ласка, оберіть зручний для вас вид оплати:',
        reply_markup=payment_type_markup
    )

    return PAY_TYPE


def type_of_payment(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    if user.text == button22:
        log('Client', 'Pay type in development', user, sf=False)
        user.reply_text('В розробці', reply_markup=payment_type_markup)
        return PAY_TYPE
    else:
        log('Client', 'Pay type', user, sf=False)
        message = 'Вид оплати: ' + user.text
        '''if user.text == button22:
            db = True
        else:'''
        db = False

        data_dict[from_user.id]['text'].append(message)
        data_dict[from_user.id]['db'].append(db)

        with sq.connect(DATABASE_URL) as database:
            cur = database.cursor()
        cur.execute("SELECT MAX(pk) FROM orders")
        try:
            order_id = cur.fetchone()[0] + 1
        except TypeError:
            order_id = 1
        order_filter = data_dict[from_user.id]['db']
        order_filter.append(order_id)
        cur.execute("INSERT INTO orders (user_id, text, delivery_time, full_name, adress, phone, payment_type, pk) "
                    "VALUES(%s, %s, %s, %s, %s, %s, %s, %s)", order_filter)
        database.commit()

        '''cur.execute("SELECT pk FROM orders WHERE user_id = %s", [from_user.id])
        order_id = cur.fetchall()[::-1][0][0]'''

        data_dict[from_user.id]['text'].append(f'Номер замовлення: {order_id}')

        for chat in forward_to:
            user.bot.send_message(chat_id=chat, text='\n\n'.join(data_dict[from_user.id]['text']))
            [user.bot.forward_message(from_chat_id=user.chat_id, chat_id=chat, message_id=i)
             for i in data_dict[from_user.id]['forward']]

        user.reply_text(
            'Дякуємо за ваше замовлення, очікуйте! ❤️\nУ разі виникнення питань, зв’яжіться з нами!'
            f'\nНомер вашого замовлення: {order_id}',
            reply_markup=client_markup
        )

        return CLIENT


def order_review(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    order_id = data_dict[from_user.id]['order']
    review_text = space_filter(user.text)
    with sq.connect(DATABASE_URL) as database:
        cur = database.cursor()
    review_list_filter = [review_text, from_user.id, order_id]
    cur.execute(f"UPDATE orders SET review = %s WHERE user_id = %s AND pk = %s", review_list_filter)
    database.commit()
    for chat in forward_to:
        user.bot.send_message(chat_id=chat, text=f'Відгук до замовлення #{order_id}\n'
                                                 f'Користувача {from_user.full_name}:\n\n{review_text}')
    user.reply_text('Дякую за ваш відгук', reply_markup=client_markup)
    log('Client', 'Order review', user, manual=f'Review to order #{order_id}')

    return CLIENT


def tip(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    if user.text == button16:
        reply = '↩️'
        reply_markup = client_markup
        method: int = CLIENT
        log('Client', 'Tip', user, manual='Turn back')
    else:
        try:
            value = int(user.text)
        except ValueError:
            reply = f'Ви ввели "{user.text}", а потрібно ввети ціле число від 3.00 до 27\'000.00'
            reply_markup = back_markup
            method: int = TIP
            log('Client', 'Tip', user, manual=f'ValueError: {user.text}')
        else:
            if 3 > value or value > 27000:
                reply = f'Ви ввели "{value}", а потрібно ввети ціле число від 3.00 до 27\'000.00'
                reply_markup = back_markup
                method: int = TIP
                log('Client', 'Tip', user, manual=f'Aboard integer: {user.text}')
            elif value == 0:
                order_id: int = data_dict[from_user.id]['order']
                with sq.connect(DATABASE_URL) as database:
                    cur = database.cursor()
                update_orders_filter = [-1, from_user.id, order_id]
                cur.execute("UPDATE orders SET tip = %s WHERE user_id = %s AND pk = %s", update_orders_filter)
                database.commit()
                reply = f'Чайові замовлення #{order_id} скасовані'
                reply_markup = client_markup
                method: int = CLIENT
                log('Client', 'Tip', user, manual='Tip cancel')
            else:
                data_dict[from_user.id]['pay_type']: int = 2
                data_dict[from_user.id]['tip_value']: int = value
                order_id: int = data_dict[from_user.id]['order']
                chat_id: int = user.chat_id
                reply, reply_markup, method = pay_preprocessor(
                    user, order_id, chat_id, value, 2, context
                )
    user.reply_text(reply, reply_markup=reply_markup)
    return method


def precheckout_callback(update: Update, context: CallbackContext) -> None:
    query = update.pre_checkout_query
    # check the payload, is this from your bot?
    if query.invoice_payload != 'Custom-Payload':
        # MAIN False pre_checkout_query
        query.answer(ok=False, error_message="Щось пішло не так...")
    else:
        query.answer(ok=True)


def successful_payment_callback(update: Update, context: CallbackContext) -> None:
    user, from_user = base(update.message)
    order_id: int = data_dict[from_user.id]['order']
    log_text = f'Payment {order_id} successful'
    log('Client', 'Tip', user, manual=log_text)
    with sq.connect(DATABASE_URL) as database:
        cur = database.cursor()
    if data_dict[from_user.id]['pay_type'] == 1:
        get_courier_id_filter = [from_user.id, order_id]
        cur.execute(f"SELECT courier_id FROM orders WHERE user_id = %s"
                    f" AND pk = %s", get_courier_id_filter)
        courier_id = cur.fetchone()[0]
        update_orders_filter = [True, from_user.id, order_id]
        cur.execute("UPDATE orders SET paid = %s WHERE user_id = %s AND pk = %s", update_orders_filter)
        database.commit()
        if courier_id:
            text = f'Замовлення #{order_id} оплачено'
            cur.execute("SELECT telegram_id FROM couriers WHERE is_free = %s"
                        " AND telegram_id = %s", [False, courier_id])
            courier_status = cur.fetchone()[0]
            user.bot.send_message(text=text, chat_id=courier_id,
                                  reply_markup=delivery_markup if courier_status else ReplyKeyboardRemove())
    elif data_dict[from_user.id]['pay_type'] == 2:
        tip_value: int = data_dict[from_user.id]['tip_value']
        if order_id:
            cur.execute(f"UPDATE orders SET tip = {tip_value * 100} "
                        f"WHERE user_id = {from_user.id} AND pk = {order_id}")
            text = f'Чайові по замовленню #{order_id}: {tip_value} грн'
        '''else:
            cur.execute(f"UPDATE users SET donations = donations + {tip_value * 100} WHERE id = {from_user.id}")
            text = f'Чайові власнику: {tip_value} грн'''
        for owner_id in forward_to:
            user.bot.send_message(text=text, chat_id=owner_id)
    database.commit()
    user.reply_text("Дякую за оплату!", reply_markup=client_markup)

    return CLIENT


def help_me(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    if user.text == button16:
        reply_text = '↩️'
        log_text = 'Support back'
    else:
        first_message = data_dict[from_user.id]['check_message']
        text = data_dict[from_user.id]['text']
        message = f'{text[0]}\n\n{button1}\n\nid: {from_user.id}'
        log_text = 'Support message'
        reply_text = 'Очікуйте відповідь! ☎️'
        while user.message_id == first_message + 2:
            user.reply_text('Будь ласка, введіть повідомлення для відправки!!!', reply_markup=help_markup)
            data_dict[from_user.id]['check_message'] += 2
            log('Client', 'Support', user, manual='Message not exist')
            return HELP
        else:
            for chat in forward_to:
                message_id = first_message + 2
                user.bot.send_message(chat_id=chat, text=message)
                message_count = 0
                while user.message_id > message_id > first_message + 1 and message_count < 10:
                    try:
                        user.bot.forward_message(from_chat_id=user.chat_id, chat_id=chat, message_id=message_id)
                        message_id += 1
                        message_count += 1
                    except BadRequest:
                        break

    log('Client', 'Support', user, manual=log_text)
    user.reply_text(reply_text, reply_markup=client_markup)

    return CLIENT


# #################################################################################################################### #
# ####################################################=END=########################################################### #
# #################################################################################################################### #


def stop(update: Update, context: CallbackContext) -> int:
    user, from_user = base(update.message)
    log('User', 'canceled the conversation', user)
    user.reply_text(
        'Дякуємо , що скористалися нашими послугами. До побачення! ❤️',
        reply_markup=ReplyKeyboardRemove()
    )

    return ConversationHandler.END


def main() -> None:
    # Create the Updater and pass it your bot's token.
    updater = Updater(BOT_TOKEN)  #

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher

    # Add conversation handler with the states MAIN, ORDER, LOCATION, HELP and BUSINESS
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CLIENT: [MessageHandler(Filters.regex(f'^({button0}|{button1}|{button19}|{button17}|{button18})$')
                                    & ~Filters.command, client_menu)],
            ADMIN: [MessageHandler(Filters.regex(f'^({button2}|{button3}|{button4}|{button7}|{button12})$')
                                   & ~Filters.command, admin_menu)],
            COURIER: [MessageHandler(Filters.location & ~Filters.command, courier_menu)],
            COURIER_READY: [MessageHandler(Filters.regex(f'^({button6}|{button7}|{button8}|{button9})$')
                                           & ~Filters.command, ready_courier_menu)],
            PURCHASE: [MessageHandler(Filters.regex(f'^({button13}|{button9})$')
                                      & ~Filters.command, courier_purchase)],
            DELIVERY: [MessageHandler(Filters.regex(f'^({button15}|{button9})$')
                                      & ~Filters.command, courier_delivery)],
            COURIER_PROBLEM: [MessageHandler(Filters.regex(f'^({button20})$')
                                             & ~Filters.command, courier_problem)],
            CONFIRM_PAY: [MessageHandler(Filters.regex(f'^({button21}|{button9})$')
                                         & ~Filters.command, confirm_pay)],
            START_COUNT: [MessageHandler(Filters.text & ~Filters.command, start_count)],
            END_COUNT: [MessageHandler(Filters.text & ~Filters.command, end_count)],
            REVIEW: [MessageHandler(Filters.text & ~Filters.command, order_review)],
            ORDER: [MessageHandler(Filters.text & ~Filters.command, order)],
            DELIVERY_TIME: [MessageHandler(Filters.text & ~Filters.command, delivery_time)],
            TIP: [MessageHandler(Filters.text & ~Filters.command, tip)],
            CANCELED: [MessageHandler(Filters.text & ~Filters.command, cancel_order)],
            CANCEL_CALLBACK: [MessageHandler(Filters.text & ~Filters.command, client_cancel_callback)],
            COURIER_LIST: [MessageHandler(Filters.text & ~Filters.command, courier_list)],
            SEND_COURIER: [MessageHandler(Filters.text & ~Filters.command, send_courier)],
            NAME: [MessageHandler(Filters.text & ~Filters.command, full_name)],
            LOCATION: [MessageHandler(Filters.location & ~Filters.command | Filters.text
                                      & ~Filters.command, get_location)],
            CONTACT: [MessageHandler(Filters.contact & ~Filters.command | Filters.text
                                     & ~Filters.command, get_contact)],
            PAY_TYPE: [MessageHandler(Filters.regex(f'^({button22}|{button23})$')
                                      & ~Filters.command, type_of_payment)],
            HELP: [MessageHandler(Filters.regex(f'^({button20}|{button16})$') & ~Filters.command, help_me)],
        },
        fallbacks=[CommandHandler('stop', stop)],
        run_async=True)

    dispatcher.add_handler(conv_handler)

    dispatcher.add_handler(PreCheckoutQueryHandler(precheckout_callback))

    # Success! Notify your user!
    dispatcher.add_handler(MessageHandler(Filters.successful_payment, successful_payment_callback))

    # Start the Bot
    updater.start_polling()

    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()


if __name__ == '__main__':
    main()
