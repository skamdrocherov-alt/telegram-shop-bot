import os
import html
import httpx

from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Update,
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


# =========================
# НАСТРОЙКИ
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")

SELLER_USERNAME = os.getenv(
    "SELLER_USERNAME",
    "balovanaya_kisa"
).replace("@", "").lower()

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_SECRET = os.getenv(
    "WEBHOOK_SECRET",
    "change_this_secret_123"
)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан")

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL не задан")

if not SUPABASE_SECRET_KEY:
    raise RuntimeError("SUPABASE_SECRET_KEY не задан")


# =========================
# TELEGRAM
# =========================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()


# =========================
# SUPABASE
# =========================

REST_URL = f"{SUPABASE_URL}/rest/v1"

HEADERS = {
    "apikey": SUPABASE_SECRET_KEY,
    "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
    "Content-Type": "application/json",
}


async def supabase_request(
    method: str,
    endpoint: str,
    **kwargs
):
    headers = HEADERS.copy()

    if method.upper() in ("POST", "PATCH", "DELETE"):
        headers["Prefer"] = "return=representation"

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.request(
            method,
            f"{REST_URL}/{endpoint}",
            headers=headers,
            **kwargs
        )

    if response.status_code >= 400:
        raise RuntimeError(
            f"Supabase error {response.status_code}: {response.text}"
        )

    if not response.text:
        return None

    return response.json()


async def get_products():
    return await supabase_request(
        "GET",
        "products",
        params={
            "select": "id,name,price,quantity",
            "order": "id.asc"
        }
    )


async def get_product(product_id: int):
    result = await supabase_request(
        "GET",
        "products",
        params={
            "select": "id,name,price,quantity",
            "id": f"eq.{product_id}",
            "limit": "1"
        }
    )

    return result[0] if result else None


async def add_product(name: str, price: float, quantity: int):
    return await supabase_request(
        "POST",
        "products",
        json={
            "name": name,
            "price": price,
            "quantity": quantity
        }
    )


async def update_product(product_id: int, data: dict):
    return await supabase_request(
        "PATCH",
        "products",
        params={
            "id": f"eq.{product_id}"
        },
        json=data
    )


async def delete_product(product_id: int):
    return await supabase_request(
        "DELETE",
        "products",
        params={
            "id": f"eq.{product_id}"
        }
    )


async def buy_product(product_id: int):
    return await supabase_request(
        "POST",
        "rpc/buy_product",
        json={
            "p_product_id": product_id
        }
    )


async def get_setting(key: str):
    result = await supabase_request(
        "GET",
        "settings",
        params={
            "select": "key,value",
            "key": f"eq.{key}",
            "limit": "1"
        }
    )

    return result[0]["value"] if result else None


async def set_setting(key: str, value: str):
    existing = await get_setting(key)

    if existing is None:
        await supabase_request(
            "POST",
            "settings",
            json={
                "key": key,
                "value": value
            }
        )
    else:
        await supabase_request(
            "PATCH",
            "settings",
            params={
                "key": f"eq.{key}"
            },
            json={
                "value": value
            }
        )


# =========================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================

def is_admin(user) -> bool:
    username = (user.username or "").lower()

    return username == SELLER_USERNAME


def money(value):
    try:
        number = float(value)

        if number.is_integer():
            return f"{int(number)} ₽"

        return f"{number:.2f} ₽"

    except Exception:
        return f"{value} ₽"


def catalog_keyboard(products):
    buttons = []

    for product in products:
        product_id = product["id"]
        name = product["name"]
        price = money(product["price"])
        quantity = product["quantity"]

        if quantity > 0:
            text = f"🛒 {name} — {price}"
            buttons.append([
                InlineKeyboardButton(
                    text=text,
                    callback_data=f"product:{product_id}"
                )
            ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def product_keyboard(product_id: int, available: bool):
    buttons = []

    if available:
        buttons.append([
            InlineKeyboardButton(
                text="🛒 Купить",
                callback_data=f"buy:{product_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="📞 Связаться с продавцом",
            url=f"https://t.me/{SELLER_USERNAME}"
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад в каталог",
            callback_data="catalog"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# =========================
# КЛАВИАТУРА АДМИНА
# =========================

def admin_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Добавить товар",
                    callback_data="admin:add"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📦 Список товаров",
                    callback_data="admin:list"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💰 Изменить цену",
                    callback_data="admin:price"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Изменить количество",
                    callback_data="admin:qty"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Переименовать",
                    callback_data="admin:rename"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Удалить товар",
                    callback_data="admin:delete"
                )
            ]
        ]
    )


# =========================
# FSM
# =========================

class AdminStates(StatesGroup):
    add_product = State()
    edit_price = State()
    edit_quantity = State()
    rename_product = State()
    delete_product = State()


# =========================
# START
# =========================

@dp.message(CommandStart())
async def start_handler(message: Message):

    # Запоминаем Telegram ID продавца,
    # когда продавец сам запустил бота
    if is_admin(message.from_user):
        await set_setting(
            "seller_chat_id",
            str(message.from_user.id)
        )

    products = await get_products()

    text = (
        "🛍 <b>Магазин</b>\n\n"
        "Выберите товар:"
    )

    if not products:
        text += "\n\nПока товаров нет."

        await message.answer(
            text,
            parse_mode="HTML"
        )
        return

    available_products = [
        p for p in products
        if p["quantity"] > 0
    ]

    if not available_products:
        text += "\n\nВсе товары закончились."

        await message.answer(
            text,
            parse_mode="HTML"
        )
        return

    await message.answer(
        text,
        reply_markup=catalog_keyboard(available_products),
        parse_mode="HTML"
    )


# =========================
# КАТАЛОГ
# =========================

@dp.callback_query(F.data == "catalog")
async def catalog_handler(callback: CallbackQuery):

    products = await get_products()

    available_products = [
        p for p in products
        if p["quantity"] > 0
    ]

    if not available_products:
        await callback.message.edit_text(
            "📦 Сейчас все товары закончились."
        )

        await callback.answer()
        return

    await callback.message.edit_text(
        "🛍 <b>Каталог</b>\n\nВыберите товар:",
        reply_markup=catalog_keyboard(available_products),
        parse_mode="HTML"
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("product:"))
async def product_handler(callback: CallbackQuery):

    product_id = int(callback.data.split(":")[1])

    product = await get_product(product_id)

    if not product:
        await callback.answer(
            "Товар не найден",
            show_alert=True
        )
        return

    name = html.escape(str(product["name"]))
    price = money(product["price"])
    quantity = product["quantity"]

    if quantity > 0:
        text = (
            f"📦 <b>{name}</b>\n\n"
            f"💰 Цена: <b>{price}</b>\n"
            f"📊 Остаток: <b>{quantity} шт.</b>"
        )
    else:
        text = (
            f"📦 <b>{name}</b>\n\n"
            f"💰 Цена: <b>{price}</b>\n"
            f"❌ Товар закончился."
        )

    await callback.message.edit_text(
        text,
        reply_markup=product_keyboard(
            product_id,
            quantity > 0
        ),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================
# ПОКУПКА
# =========================

@dp.callback_query(F.data.startswith("buy:"))
async def buy_handler(callback: CallbackQuery):

    product_id = int(callback.data.split(":")[1])

    try:
        result = await buy_product(product_id)

    except Exception:
        await callback.answer(
            "Не удалось оформить покупку. Попробуйте ещё раз.",
            show_alert=True
        )
        return

    if not result:
        await callback.answer(
            "❌ Товар закончился.",
            show_alert=True
        )
        return

    product = result[0]

    name = product["name"]
    price = product["price"]
    remaining = product["quantity"]

    buyer = callback.from_user

    buyer_username = (
        f"@{buyer.username}"
        if buyer.username
        else "без username"
    )

    buyer_name = (
        f"{buyer.first_name or ''} "
        f"{buyer.last_name or ''}"
    ).strip()

    seller_chat_id = await get_setting("seller_chat_id")

    # Уведомление продавцу
    if seller_chat_id:

        notification = (
            "🔔 <b>Новый заказ!</b>\n\n"
            f"📦 Товар: <b>{html.escape(str(name))}</b>\n"
            f"💰 Цена: <b>{money(price)}</b>\n\n"
            f"👤 Покупатель: {html.escape(buyer_name)}\n"
            f"🔗 Username: {html.escape(buyer_username)}\n"
            f"🆔 ID: <code>{buyer.id}</code>\n\n"
            f"📊 Осталось: <b>{remaining} шт.</b>"
        )

        try:
            await bot.send_message(
                int(seller_chat_id),
                notification,
                parse_mode="HTML"
            )
        except Exception:
            pass

    await callback.message.edit_text(
        "✅ <b>Заказ оформлен!</b>\n\n"
        f"📦 {html.escape(str(name))}\n"
        f"💰 {money(price)}\n\n"
        "Продавец получил уведомление.\n"
        "Для уточнения деталей свяжитесь с продавцом.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📞 Связаться с продавцом",
                        url=f"https://t.me/{SELLER_USERNAME}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🛍 Вернуться в каталог",
                        callback_data="catalog"
                    )
                ]
            ]
        ),
        parse_mode="HTML"
    )

    await callback.answer("Заказ оформлен!")


# =========================
# АДМИН-ПАНЕЛЬ
# =========================

@dp.message(Command("admin"))
async def admin_handler(message: Message):

    if not is_admin(message.from_user):
        await message.answer("⛔ Доступ запрещён.")
        return

    await message.answer(
        "⚙️ <b>Панель администратора</b>\n\n"
        "Здесь можно управлять товарами:",
        reply_markup=admin_keyboard(),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "admin:list")
async def admin_list(callback: CallbackQuery):

    if not is_admin(callback.from_user):
        await callback.answer(
            "⛔ Доступ запрещён",
            show_alert=True
        )
        return

    products = await get_products()

    if not products:
        text = "📦 Товаров пока нет."
    else:
        lines = ["📦 <b>Товары:</b>\n"]

        for p in products:
            lines.append(
                f"ID: <code>{p['id']}</code>\n"
                f"Название: {html.escape(str(p['name']))}\n"
                f"Цена: {money(p['price'])}\n"
                f"Количество: {p['quantity']}\n"
            )

        text = "\n".join(lines)

    await callback.message.answer(
        text,
        parse_mode="HTML"
    )

    await callback.answer()


# =========================
# ДОБАВЛЕНИЕ
# =========================

@dp.callback_query(F.data == "admin:add")
async def admin_add(callback: CallbackQuery, state: FSMContext):

    if not is_admin(callback.from_user):
        await callback.answer(
            "⛔ Доступ запрещён",
            show_alert=True
        )
        return

    await state.set_state(AdminStates.add_product)

    await callback.message.answer(
        "➕ <b>Добавление товара</b>\n\n"
        "Отправь одной строкой:\n\n"
        "<code>Название | Цена | Количество</code>\n\n"
        "Например:\n"
        "<code>iPhone 15 | 70000 | 5</code>",
        parse_mode="HTML"
    )

    await callback.answer()


@dp.message(AdminStates.add_product)
async def add_product_handler(message: Message, state: FSMContext):

    if not is_admin(message.from_user):
        return

    try:
        parts = [x.strip() for x in message.text.split("|")]

        if len(parts) != 3:
            raise ValueError

        name = parts[0]
        price = float(parts[1].replace(",", "."))
        quantity = int(parts[2])

        if not name or price < 0 or quantity < 0:
            raise ValueError

        await add_product(
            name,
            price,
            quantity
        )

        await message.answer(
            "✅ Товар добавлен!"
        )

        await state.clear()

    except Exception:
        await message.answer(
            "❌ Неверный формат.\n\n"
            "Используй:\n"
            "<code>Название | Цена | Количество</code>",
            parse_mode="HTML"
        )


# =========================
# ИЗМЕНЕНИЕ ЦЕНЫ
# =========================

@dp.callback_query(F.data == "admin:price")
async def admin_price(callback: CallbackQuery, state: FSMContext):

    if not is_admin(callback.from_user):
        await callback.answer(
            "⛔ Доступ запрещён",
            show_alert=True
        )
        return

    await state.set_state(AdminStates.edit_price)

    await callback.message.answer(
        "💰 Отправь:\n\n"
        "<code>ID товара | Новая цена</code>\n\n"
        "Например:\n"
        "<code>3 | 59990</code>",
        parse_mode="HTML"
    )

    await callback.answer()


@dp.message(AdminStates.edit_price)
async def edit_price_handler(message: Message, state: FSMContext):

    try:
        parts = [x.strip() for x in message.text.split("|")]

        product_id = int(parts[0])
        price = float(parts[1].replace(",", "."))

        if price < 0:
            raise ValueError

        product = await get_product(product_id)

        if not product:
            await message.answer("❌ Товар не найден.")
            return

        await update_product(
            product_id,
            {"price": price}
        )

        await message.answer(
            "✅ Цена изменена."
        )

        await state.clear()

    except Exception:
        await message.answer(
            "❌ Формат:\n"
            "<code>ID | Новая цена</code>",
            parse_mode="HTML"
        )


# =========================
# ИЗМЕНЕНИЕ КОЛИЧЕСТВА
# =========================

@dp.callback_query(F.data == "admin:qty")
async def admin_quantity(callback: CallbackQuery, state: FSMContext):

    if not is_admin(callback.from_user):
        await callback.answer(
            "⛔ Доступ запрещён",
            show_alert=True
        )
        return

    await state.set_state(AdminStates.edit_quantity)

    await callback.message.answer(
        "📊 Отправь:\n\n"
        "<code>ID товара | Новое количество</code>\n\n"
        "Например:\n"
        "<code>3 | 20</code>",
        parse_mode="HTML"
    )

    await callback.answer()


@dp.message(AdminStates.edit_quantity)
async def edit_quantity_handler(
    message: Message,
    state: FSMContext
):

    try:
        parts = [x.strip() for x in message.text.split("|")]

        product_id = int(parts[0])
        quantity = int(parts[1])

        if quantity < 0:
            raise ValueError

        product = await get_product(product_id)

        if not product:
            await message.answer("❌ Товар не найден.")
            return

        await update_product(
            product_id,
            {"quantity": quantity}
        )

        await message.answer(
            "✅ Количество изменено."
        )

        await state.clear()

    except Exception:
        await message.answer(
            "❌ Формат:\n"
            "<code>ID | Новое количество</code>",
            parse_mode="HTML"
        )


# =========================
# ПЕРЕИМЕНОВАНИЕ
# =========================

@dp.callback_query(F.data == "admin:rename")
async def admin_rename(callback: CallbackQuery, state: FSMContext):

    if not is_admin(callback.from_user):
        await callback.answer(
            "⛔ Доступ запрещён",
            show_alert=True
        )
        return

    await state.set_state(AdminStates.rename_product)

    await callback.message.answer(
        "✏️ Отправь:\n\n"
        "<code>ID товара | Новое название</code>\n\n"
        "Например:\n"
        "<code>3 | iPhone 15 Pro Max</code>",
        parse_mode="HTML"
    )

    await callback.answer()


@dp.message(AdminStates.rename_product)
async def rename_product_handler(
    message: Message,
    state: FSMContext
):

    try:
        parts = message.text.split("|", 1)

        product_id = int(parts[0].strip())
        name = parts[1].strip()

        if not name:
            raise ValueError

        product = await get_product(product_id)

        if not product:
            await message.answer("❌ Товар не найден.")
            return

        await update_product(
            product_id,
            {"name": name}
        )

        await message.answer(
            "✅ Товар переименован."
        )

        await state.clear()

    except Exception:
        await message.answer(
            "❌ Формат:\n"
            "<code>ID | Новое название</code>",
            parse_mode="HTML"
        )


# =========================
# УДАЛЕНИЕ
# =========================

@dp.callback_query(F.data == "admin:delete")
async def admin_delete(callback: CallbackQuery, state: FSMContext):

    if not is_admin(callback.from_user):
        await callback.answer(
            "⛔ Доступ запрещён",
            show_alert=True
        )
        return

    await state.set_state(AdminStates.delete_product)

    await callback.message.answer(
        "🗑 Отправь ID товара для удаления.\n\n"
        "Например:\n"
        "<code>3</code>",
        parse_mode="HTML"
    )

    await callback.answer()


@dp.message(AdminStates.delete_product)
async def delete_product_handler(
    message: Message,
    state: FSMContext
):

    try:
        product_id = int(message.text.strip())

        product = await get_product(product_id)

        if not product:
            await message.answer("❌ Товар не найден.")
            return

        await delete_product(product_id)

        await message.answer(
            f"✅ Товар «{html.escape(str(product['name']))}» удалён.",
            parse_mode="HTML"
        )

        await state.clear()

    except Exception:
        await message.answer(
            "❌ Отправь только ID товара."
        )


# =========================
# WEBHOOK
# =========================

@app.get("/")
async def health():
    return {
        "status": "ok",
        "bot": "running"
    }


@app.post("/webhook")
async def telegram_webhook(request: Request):

    secret = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token"
    )

    if secret != WEBHOOK_SECRET:
        raise HTTPException(
            status_code=403,
            detail="Forbidden"
        )

    data = await request.json()

    update = Update.model_validate(data)

    await dp.feed_update(
        bot,
        update
    )

    return {
        "ok": True
    }


# =========================
# STARTUP / SHUTDOWN
# =========================

@app.on_event("startup")
async def startup():

    if WEBHOOK_URL:

        await bot.set_webhook(
            url=WEBHOOK_URL,
            secret_token=WEBHOOK_SECRET,
            drop_pending_updates=True
        )

        print(
            f"Webhook установлен: {WEBHOOK_URL}"
        )

    else:
        print(
            "WEBHOOK_URL не задан. "
            "Webhook не установлен."
        )


@app.on_event("shutdown")
async def shutdown():

    await bot.session.close()
