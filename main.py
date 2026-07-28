# -*- coding: utf-8 -*-
import os
import sys
import json
import asyncio
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import io
import logging
import functools
from PIL import Image, ImageDraw, ImageFont
import disnake
from disnake.ext import commands, tasks
from disnake.ui import Modal, TextInput, View, Button
from disnake import PartialEmoji, ui, ButtonStyle, Embed
import sqlite3

# ----------------------------
# ПУТИ
# ----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = BASE_DIR
os.makedirs(DATA_DIR, exist_ok=True)
# ----------------------------
# КОНФИГ
# ----------------------------
CONFIG = {
    "BOT_TOKEN": os.getenv("BOT_TOKEN"),

    "ADMIN_ROLES": [1478389663415931033, 1478389663377920171, 1502640936147226726, 1488231540470054932],
    "TICKET_VIEW_ROLES": [1478389663377920172, 1478389663415931033, 1478389663377920171, 1502640936147226726, 1488231540470054932],
    "TICKET_MANAGE_ROLES": [1478389663377920172, 1478389663415931033, 1478389663377920171, 1502640936147226726, 1488231540470054932],

    "PANEL_CHANNEL_ID": 1478389663931695120,
    "LOG_CHANNEL_ID": 1485322161794056202,
    "REVIEW_COUNT_CHANNEL": 1478389664392941659,
    "TICKET_CATEGORY_ID": 1531317342167105739,
    "PAID_CATEGORY_ID": 1531317464942510271,

    "ROLE_IDS": {"gold": 1478389663377920168, "bronze": 1478389663377920166, "century": 1478389663377920164},
    "MANAGER_ROLE_ID": 1478389663377920172,
    "AUTO_ROLE_ID": 1478389663377920170,

    "TICKET_COOLDOWN_SECONDS": 5,
    "GUILD_ID": 1478389663377920163,

    "DATA_DIR": DATA_DIR,
    "MENU_EMBED_PATH": os.path.join(BASE_DIR, "menu_embed.json"),
    "INFO_TEMPLATE_PATH": os.path.join(BASE_DIR, "info-o-zakaze.json"),
    "REKV_PATH": os.path.join(BASE_DIR, "rekv.json"),
    "POLICY_PATH": os.path.join(BASE_DIR, "policy.json"),
}

# ----------------------------
# ФАЙЛЫ ДАННЫХ (JSON)
# ----------------------------
FILES = {
    "promo": os.path.join(BASE_DIR, "promo_codes.json"),
    "used_promo": os.path.join(BASE_DIR, "used_promo.json"),
    "review_counts": os.path.join(BASE_DIR, "review_counts.json"),
}

# ----------------------------
# ИНИТ БОТА
# ----------------------------
intents = disnake.Intents.default()
intents.members = True
intents.messages = True
intents.guilds = True
intents.message_content = True
intents.moderation = True
intents.invites = True
intents.reactions = True
bot = commands.Bot(command_prefix='/', intents=intents)

# ----------------------------
# БАЗА ДАННЫХ (SQLite)
# ----------------------------
db = sqlite3.connect(os.path.join(BASE_DIR, "diamond.db"), check_same_thread=False, timeout=30)
db.row_factory = sqlite3.Row
db.execute("PRAGMA journal_mode=WAL")
db.execute("PRAGMA synchronous=NORMAL")
db.executescript("""
CREATE TABLE IF NOT EXISTS invites_snapshot (
    invite_code TEXT PRIMARY KEY,
    guild_id    INTEGER,
    uses        INTEGER,
    inviter_id  INTEGER
);
CREATE TABLE IF NOT EXISTS invites (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER,
    inviter_id  INTEGER,
    member_id   INTEGER,
    joined_at   INTEGER,
    is_bot      INTEGER DEFAULT 0,
    is_fake     INTEGER DEFAULT 0,
    left_at     INTEGER DEFAULT NULL
);
CREATE TABLE IF NOT EXISTS reaction_roles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER,
    channel_id  INTEGER,
    message_id  INTEGER,
    emoji       TEXT,
    role_id     INTEGER
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
""")
db.commit()

try:
    db.execute("ALTER TABLE invites ADD COLUMN is_bot INTEGER DEFAULT 0")
except sqlite3.OperationalError:
    pass
try:
    db.execute("ALTER TABLE invites ADD COLUMN is_fake INTEGER DEFAULT 0")
except sqlite3.OperationalError:
    pass

# ----------------------------
# UTILS
# ----------------------------
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def now_ts():
    return int(datetime.now(timezone.utc).timestamp())

def has_admin_roles(author):
    return any(r.id in CONFIG["ADMIN_ROLES"] for r in author.roles)

def has_ticket_view_roles(author):
    return any(r.id in CONFIG["TICKET_VIEW_ROLES"] for r in author.roles)

def has_ticket_manage_roles(author):
    return any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in author.roles)

def clean_embed_for_discohook(embed_dict):
    e = dict(embed_dict)
    if "image" in e and isinstance(e["image"], dict) and "url" in e["image"]:
        e["image"] = {"url": e["image"]["url"]}
    return e

# ================= ЭМОДЗИ =================
EMOJI_CLOSE = PartialEmoji(name="rekv", id=1531341231488106651)
EMOJI_POKKUS = PartialEmoji(name="pokkus", id=1531333673742372946)
EMOJI_PROMO = PartialEmoji(name="promo", id=1531333692864073728)
EMOJI_SLOMD = PartialEmoji(name="slomd", id=1531333714171265165)

# ================= ЛОГИРОВАНИЕ =================
async def log_discord(title, description, color=0x00ff00, fields=None):
    try:
        channel = bot.get_channel(CONFIG["LOG_CHANNEL_ID"])
        if not channel:
            channel = await bot.fetch_channel(CONFIG["LOG_CHANNEL_ID"])
        if not channel:
            return
        embed = disnake.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
        if fields:
            for name, value, inline in fields:
                embed.add_field(name=name, value=value, inline=inline)
        await channel.send(embed=embed)
    except Exception as e:
        print(f"[LOG ERROR] {e}")

def log_command(func):
    @functools.wraps(func)
    async def wrapper(ctx, *args, **kwargs):
        if not has_admin_roles(ctx.author):
            await ctx.send("⛔ У вас нет прав.", ephemeral=True)
            return
        await log_discord(
            "🔧 Использована команда",
            f"> **Команда:** `{func.__name__}`\n> **Пользователь:** {ctx.author} (`{ctx.author.id}`)",
            color=0x2f3136
        )
        return await func(ctx, *args, **kwargs)
    return wrapper

# ================= ЗАГРУЗКА ПРОМОКОДОВ =================
promo_codes = load_json(FILES["promo"], {})
used_promo = load_json(FILES["used_promo"], {})

# ================= РОЛИ ЗА ОТЗЫВЫ =================
def get_roles_for_count(count):
    role_ids = CONFIG["ROLE_IDS"]
    if count >= 15:
        return [role_ids["century"]]
    elif count >= 5:
        return [role_ids["bronze"]]
    elif count >= 1:
        return [role_ids["gold"]]
    return []

async def update_user_roles(member, count):
    target_roles = get_roles_for_count(count)
    all_buyer_roles = list(CONFIG["ROLE_IDS"].values())
    current_roles = [r.id for r in member.roles]
    to_remove = [rid for rid in all_buyer_roles if rid in current_roles and rid not in target_roles]
    to_add = [rid for rid in target_roles if rid not in current_roles]
    for rid in to_remove:
        role = member.guild.get_role(rid)
        if role:
            await member.remove_roles(role)
            await log_discord("🔄 Снята роль покупателя", f"> **Пользователь:** {member.mention}\n> **Роль:** {role.mention}")
    for rid in to_add:
        role = member.guild.get_role(rid)
        if role:
            await member.add_roles(role)
            await log_discord("🔄 Выдана роль покупателя", f"> **Пользователь:** {member.mention}\n> **Роль:** {role.mention}")

# ================= ТИКЕТ-СИСТЕМА =================
class BuyTicketModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="Товар", custom_id="item_name", min_length=4, max_length=50),
            TextInput(label="Способ оплаты", custom_id="payment_method", min_length=3, max_length=50),
            TextInput(label="Промокод (необязательно)", custom_id="promo_code", required=False, max_length=50),
        ]
        super().__init__(title="Создание тикета", components=components, custom_id="buy_ticket_modal")

    async def callback(self, inter: disnake.ModalInteraction):
        # ИЗМЕНЕНО: проверка прав убрана — теперь любой может создать тикет
        # (оставлен только кулдаун)
        cooldown = getattr(bot, "_ticket_cooldown", {})
        if inter.author.id in cooldown and time.time() - cooldown[inter.author.id] < CONFIG["TICKET_COOLDOWN_SECONDS"]:
            return await inter.response.send_message("⏳ Подождите 5 сек.", ephemeral=True)
        cooldown[inter.author.id] = time.time()
        bot._ticket_cooldown = cooldown

        item = inter.text_values["item_name"].strip()
        pay = inter.text_values["payment_method"].strip()
        promo = inter.text_values["promo_code"].strip().upper()
        promo_display = "Не активирован"
        if promo:
            if promo in promo_codes:
                promo_display = f"{promo} — {promo_codes[promo]}"
            else:
                promo_display = "Неверный промокод"

        guild = inter.guild
        cat = guild.get_channel(CONFIG["TICKET_CATEGORY_ID"])
        if not cat:
            return await inter.response.send_message("❌ Категория не найдена", ephemeral=True)

        overwrites = {
            guild.default_role: disnake.PermissionOverwrite(view_channel=False),
            inter.author: disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        }
        for rid in CONFIG["TICKET_VIEW_ROLES"] + CONFIG["TICKET_MANAGE_ROLES"]:
            role = guild.get_role(rid)
            if role:
                overwrites[role] = disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        channel_name = item.lower().replace(" ", "-")[:80]
        ticket = await cat.create_text_channel(name=channel_name, overwrites=overwrites)

        try:
            with open(CONFIG["INFO_TEMPLATE_PATH"], "r", encoding="utf-8") as f:
                template = json.load(f)
            embeds_data = template.get("embeds", [])
        except Exception as e:
            await log_discord("❌ Ошибка загрузки шаблона", f"Не удалось прочитать info-o-zakaze.json: {e}", color=0xff0000)
            embeds_data = [
                {"color": 0x676767, "image": {"url": "https://media.discordapp.net/attachments/1527006158282555412/1527179314465079417/image.png?ex=6a5efe12&is=6a5dac92&hm=128f983d9fcacd66b9fdac71708d848ee4a0a5777bc461004f7f161272b9403a&=&format=webp&quality=lossless&width=1870&height=727"}},
                {"title": "Информация о заказе", "color": 0x7c3131, "fields": []}
            ]

        banner_embed = disnake.Embed.from_dict(clean_embed_for_discohook(embeds_data[0]))

        info_template = embeds_data[1] if len(embeds_data) > 1 else {}
        info_embed = disnake.Embed.from_dict(clean_embed_for_discohook(info_template))
        new_fields = []
        for field in info_embed.fields:
            name = field.name
            value = field.value
            if "позиция" in name.lower() or "Позиция" in name:
                value = f"```{item}```"
            elif "оплаты" in name.lower() or "Способ оплаты" in name:
                value = f"```{pay}```"
            elif "промокод" in name.lower():
                value = f"```{promo_display}```"
            new_fields.append((name, value, field.inline))
        info_embed.clear_fields()
        for name, value, inline in new_fields:
            info_embed.add_field(name=name, value=value, inline=inline)

        manager_role_mention = f"<@&{CONFIG['MANAGER_ROLE_ID']}>"
        current_timestamp = int(time.time())
        description = info_embed.description or ""
        description = description.replace("Ожидайте <@&1154757071330365490>", f"Ожидайте {manager_role_mention}")
        description = description.replace("<t:1784558066:f>", f"<t:{current_timestamp}:f>")
        if not info_embed.description:
            description = f"**Статус - Не оплачен**\n> Ожидайте {manager_role_mention} для подтверждения.\n> Время: <t:{current_timestamp}:f>"
        info_embed.description = description

        view = TicketButtons()
        await ticket.send(
            f"> Добрый день, {inter.author.mention}, ваш тикет создан.\n"
            f"> Ожидайте ответа от <@&{CONFIG['MANAGER_ROLE_ID']}>",
            embeds=[banner_embed, info_embed],
            view=view
        )
        await inter.response.send_message(f"✅ Тикет создан: {ticket.mention}", ephemeral=True)

        await log_discord(
            "📩 Тикет создан",
            f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {ticket.mention}\n> **Товар:** `{item}`\n> **Оплата:** `{pay}`"
        )

# ================= КНОПКИ ТИКЕТОВ (широкие) =================
class TicketButtons(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label="ㅤㅤЗакрыть тикетㅤㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="ticket:close",
        emoji=EMOJI_CLOSE,
        row=0
    )
    async def close(self, button, inter):
        if not has_ticket_manage_roles(inter.author):
            return await inter.response.send_message("⛔ Нет прав", ephemeral=True)
        confirm = ConfirmCloseView(inter.channel)
        await inter.response.send_message("Подтвердите закрытие", view=confirm, ephemeral=True)

    @disnake.ui.button(
        label="ㅤㅤㅤㅤРеквизиты ㅤ ㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="ticket:requisites",
        emoji=EMOJI_SLOMD,
        row=0
    )
    async def requisites(self, button, inter):
        try:
            with open(CONFIG["REKV_PATH"], "r", encoding="utf-8") as f:
                data = json.load(f)
            embeds = [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data.get("embeds", [])]
            await inter.response.send_message(embeds=embeds)
        except Exception as e:
            await inter.response.send_message("❌ Ошибка загрузки реквизитов.", ephemeral=True)
        await log_discord("📄 Просмотр реквизитов", f"> **Пользователь:** {inter.author.mention}")

    @disnake.ui.button(
        label="ㅤㅤㅤㅤПолитикаㅤㅤㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="ticket:policy",
        emoji=EMOJI_PROMO,
        row=1
    )
    async def policy(self, button, inter):
        try:
            with open(CONFIG["POLICY_PATH"], "r", encoding="utf-8") as f:
                data = json.load(f)
            embeds = [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data.get("embeds", [])]
            await inter.response.send_message(embeds=embeds)
        except Exception as e:
            await inter.response.send_message("❌ Ошибка загрузки политики.", ephemeral=True)
        await log_discord("📜 Просмотр политики", f"> **Пользователь:** {inter.author.mention}")

    @disnake.ui.button(
        label="ㅤㅤㅤ  Оплатитьㅤㅤㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="ticket:pay",
        emoji=EMOJI_POKKUS,
        row=1
    )
    async def pay(self, button, inter):
        if not has_ticket_manage_roles(inter.author):
            return await inter.response.send_message("⛔ Нет прав", ephemeral=True)

        msg = inter.message
        if not msg.embeds or len(msg.embeds) < 2:
            return await inter.response.send_message("❌ Ошибка", ephemeral=True)

        info_embed = msg.embeds[1]
        if info_embed.description and "Статус - Заказ оплачен" in info_embed.description:
            return await inter.response.send_message("Заказ уже оплачен.", ephemeral=True)

        new_info = info_embed.to_dict()
        new_info["description"] = (
            f"**Статус - Заказ оплачен**\n"
            f"> Подтверждено: {inter.author.mention}\n"
            f"> Время: <t:{int(time.time())}:f>"
        )
        new_embed = disnake.Embed.from_dict(clean_embed_for_discohook(new_info))

        new_view = TicketButtonsPaid()
        await msg.edit(embeds=[msg.embeds[0], new_embed], view=new_view)

        paid_category = inter.guild.get_channel(CONFIG["PAID_CATEGORY_ID"])
        if paid_category:
            await inter.channel.edit(category=paid_category)

        manager_role = inter.guild.get_role(CONFIG["MANAGER_ROLE_ID"])
        ping = manager_role.mention if manager_role else "@менеджер"
        await inter.channel.send(f"💚 {ping} — заказ подтверждён как **оплаченный**!\n> Подтвердил: {inter.author.mention}")

        await inter.response.send_message("✅ Заказ отмечен как оплаченный.", ephemeral=True)
        await log_discord(
            "💰 Заказ оплачен",
            f"> **Канал:** {inter.channel.mention}\n> **Товар:** {info_embed.fields[0].value if info_embed.fields else '—'}\n> **Подтвердил:** {inter.author.mention}",
            color=0x2ecc71
        )

class TicketButtonsPaid(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label="ㅤㅤЗакрыть тикетㅤㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="ticket_paid:close",
        emoji=EMOJI_CLOSE,
        row=0
    )
    async def close(self, button, inter):
        if not has_ticket_manage_roles(inter.author):
            return await inter.response.send_message("⛔ Нет прав", ephemeral=True)
        confirm = ConfirmCloseView(inter.channel)
        await inter.response.send_message("Подтвердите закрытие", view=confirm, ephemeral=True)

    @disnake.ui.button(
        label="ㅤㅤㅤㅤРеквизиты ㅤ ㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="ticket_paid:requisites",
        emoji=EMOJI_SLOMD,
        row=0
    )
    async def requisites(self, button, inter):
        try:
            with open(CONFIG["REKV_PATH"], "r", encoding="utf-8") as f:
                data = json.load(f)
            embeds = [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data.get("embeds", [])]
            await inter.response.send_message(embeds=embeds)
        except Exception as e:
            await inter.response.send_message("❌ Ошибка загрузки реквизитов.", ephemeral=True)

    @disnake.ui.button(
        label="ㅤㅤㅤㅤПолитикаㅤㅤㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="ticket_paid:policy",
        emoji=EMOJI_PROMO,
        row=1
    )
    async def policy(self, button, inter):
        try:
            with open(CONFIG["POLICY_PATH"], "r", encoding="utf-8") as f:
                data = json.load(f)
            embeds = [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data.get("embeds", [])]
            await inter.response.send_message(embeds=embeds)
        except Exception as e:
            await inter.response.send_message("❌ Ошибка загрузки политики.", ephemeral=True)

    @disnake.ui.button(
        label="ㅤㅤㅤ  Оплатитьㅤㅤㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="ticket_paid:paid_done",
        disabled=True,
        emoji=EMOJI_POKKUS,
        row=1
    )
    async def paid_done(self, button, inter):
        await inter.response.send_message("Заказ уже оплачен.", ephemeral=True)

class ConfirmCloseView(View):
    def __init__(self, channel):
        super().__init__(timeout=60)
        self.channel = channel

    @disnake.ui.button(
        label="ㅤㅤПодтвердитьㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="confirm:close",
        emoji=EMOJI_CLOSE
    )
    async def confirm(self, button, inter):
        if not has_ticket_manage_roles(inter.author):
            return await inter.response.send_message("⛔ Нет прав", ephemeral=True)

        await inter.response.send_message("Тикет удаляется...", ephemeral=True)
        await asyncio.sleep(2)

        # ДОБАВЛЕНО: обработка ошибки, если канал уже удалён
        try:
            await self.channel.delete()
            await log_discord("🗑️ Тикет закрыт", f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {self.channel.name}")
        except disnake.NotFound:
            # Канал уже удалён — просто логируем, но не падаем
            await log_discord("⚠️ Тикет уже удалён", f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {self.channel.name} (не найден)")
        except Exception as e:
            await log_discord("❌ Ошибка при удалении тикета", f"> **Ошибка:** {str(e)}", color=0xff0000)

# ================= ПАНЕЛЬ (широкие кнопки) =================
class TicketPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label="ㅤㅤКупитьㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="panel:buy",
        emoji=EMOJI_POKKUS,
        row=0
    )
    async def buy(self, button, inter):
        # ИЗМЕНЕНО: проверка прав убрана — теперь любой может нажать и создать тикет
        await inter.response.send_modal(BuyTicketModal())
        await log_discord("🛒 Нажата кнопка Купить", f"> **Пользователь:** {inter.author.mention}")

    @disnake.ui.button(
        label=" Промокодыㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="panel:promo",
        emoji=EMOJI_PROMO,
        row=0
    )
    async def promo(self, button, inter):
        await inter.response.send_message("🎟️ Промокоды публикуются в <#1478434888834224350> , ожидайте!", ephemeral=True)
        await log_discord("🎟️ Просмотр промокодов", f"> **Пользователь:** {inter.author.mention}")

    @disnake.ui.button(
        label="ㅤㅤОплатаㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="panel:payinfo",
        emoji=EMOJI_SLOMD,
        row=0
    )
    async def payinfo(self, button, inter):
        await inter.response.send_message("💸 Пока что, оплата доступна только в рублях!", ephemeral=True)
        await log_discord("💳 Просмотр информации об оплате", f"> **Пользователь:** {inter.author.mention}")


# ================= ИНВАЙТЫ =================
async def sync_invites(guild: disnake.Guild):
    try:
        invites = await guild.invites()
    except Exception:
        return
    for inv in invites:
        db.execute("REPLACE INTO invites_snapshot (invite_code, guild_id, uses, inviter_id) VALUES (?, ?, ?, ?)",
                   (inv.code, guild.id, inv.uses, inv.inviter.id if inv.inviter else None))
    db.commit()

@bot.event
async def on_member_join(member: disnake.Member):
    auto_role = member.guild.get_role(CONFIG["AUTO_ROLE_ID"])
    if auto_role:
        try:
            await member.add_roles(auto_role)
            await log_discord("👤 Автороль выдана", f"> **Пользователь:** {member.mention}\n> **Роль:** {auto_role.mention}")
        except Exception as e:
            await log_discord("❌ Ошибка выдачи автороли", f"> **Пользователь:** {member.mention}\n> **Ошибка:** {e}", color=0xff0000)

    guild = member.guild
    snapshot_before = {row["invite_code"]: row for row in db.execute("SELECT * FROM invites_snapshot WHERE guild_id=?", (guild.id,)).fetchall()}
    try:
        invites_now = await guild.invites()
    except Exception:
        return
    used_invite = None
    for inv in invites_now:
        old = snapshot_before.get(inv.code)
        if old and inv.uses > old["uses"]:
            used_invite = inv
            break
    for inv in invites_now:
        db.execute("REPLACE INTO invites_snapshot (invite_code, guild_id, uses, inviter_id) VALUES (?, ?, ?, ?)",
                   (inv.code, guild.id, inv.uses, inv.inviter.id if inv.inviter else None))
    if not used_invite or not used_invite.inviter:
        db.commit()
        return
    inviter_id = used_invite.inviter.id
    is_bot = 1 if member.bot else 0
    joined_at = now_ts()
    db.execute("INSERT INTO invites (guild_id, inviter_id, member_id, joined_at, is_bot) VALUES (?, ?, ?, ?, ?)",
               (guild.id, inviter_id, member.id, joined_at, is_bot))
    db.commit()
    await log_discord(
        "📨 Использован инвайт",
        f"> **Пользователь:** {member.mention}\n> **Пригласил:** <@{inviter_id}>\n> **Код:** `{used_invite.code}`",
        color=0x00aaff
    )

@bot.event
async def on_member_remove(member: disnake.Member):
    guild = member.guild
    db.execute("UPDATE invites SET left_at=? WHERE guild_id=? AND member_id=? AND left_at IS NULL",
               (now_ts(), guild.id, member.id))
    row = db.execute("SELECT joined_at FROM invites WHERE guild_id=? AND member_id=? ORDER BY joined_at DESC LIMIT 1",
                     (guild.id, member.id)).fetchone()
    if row and (now_ts() - row["joined_at"]) < 600:
        db.execute("UPDATE invites SET is_fake=1 WHERE guild_id=? AND member_id=? AND is_fake=0",
                   (guild.id, member.id))
        await log_discord(
            "⚠️ Фейковый вход",
            f"> **Пользователь:** {member.mention}\n> Ушёл менее чем через 10 минут.",
            color=0xff6600
        )
    db.commit()

@bot.event
async def on_invite_create(invite: disnake.Invite):
    db.execute("REPLACE INTO invites_snapshot VALUES (?, ?, ?, ?)",
               (invite.code, invite.guild.id, invite.uses, invite.inviter.id if invite.inviter else None))
    db.commit()
    await log_discord(
        "📨 Создан инвайт",
        f"> **Код:** `{invite.code}`\n> **Создатель:** {invite.inviter.mention if invite.inviter else 'Неизвестно'}\n> **Канал:** {invite.channel.mention if invite.channel else 'Неизвестно'}\n> **Лимит:** `{invite.max_uses}`",
        color=0x00aaff
    )

@bot.event
async def on_invite_delete(invite: disnake.Invite):
    db.execute("DELETE FROM invites_snapshot WHERE invite_code=?", (invite.code,))
    db.commit()
    await log_discord(
        "🗑️ Удалён инвайт",
        f"> **Код:** `{invite.code}`\n> **Канал:** {invite.channel.mention if invite.channel else 'Неизвестно'}",
        color=0xff6600
    )

# ================= СТАТИСТИКА ИНВАЙТОВ =================
async def get_invite_stats(guild: disnake.Guild, user: disnake.Member):
    rows = db.execute("SELECT is_bot, left_at, is_fake, member_id FROM invites WHERE guild_id=? AND inviter_id=?",
                      (guild.id, user.id)).fetchall()
    total = len(rows)
    remaining = sum(1 for r in rows if r["left_at"] is None and r["member_id"] != 0)
    left = sum(1 for r in rows if r["left_at"] is not None)
    bots = sum(1 for r in rows if r["is_bot"] == 1)
    fake = sum(1 for r in rows if r["is_fake"] == 1)
    return {"total": total, "remaining": remaining, "left": left, "bots": bots, "fake": fake}

# ================= REACTION ROLE (обработчики) =================
@bot.event
async def on_raw_reaction_add(payload: disnake.RawReactionActionEvent):
    if payload.member is None or payload.member.bot:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    row = db.execute(
        "SELECT role_id FROM reaction_roles WHERE guild_id=? AND channel_id=? AND message_id=? AND emoji=?",
        (payload.guild_id, payload.channel_id, payload.message_id, str(payload.emoji))
    ).fetchone()
    if row:
        role = guild.get_role(row["role_id"])
        if role:
            try:
                await payload.member.add_roles(role)
                await log_discord(
                    "✅ Выдана реакционная роль",
                    f"> **Пользователь:** {payload.member.mention}\n> **Роль:** {role.mention}\n> **Реакция:** {payload.emoji}\n> **Сообщение:** <https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}>",
                    color=0x00ff00
                )
            except Exception as e:
                await log_discord("❌ Ошибка выдачи реакционной роли", str(e), color=0xff0000)

@bot.event
async def on_raw_reaction_remove(payload: disnake.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    row = db.execute(
        "SELECT role_id FROM reaction_roles WHERE guild_id=? AND channel_id=? AND message_id=? AND emoji=?",
        (payload.guild_id, payload.channel_id, payload.message_id, str(payload.emoji))
    ).fetchone()
    if row:
        role = guild.get_role(row["role_id"])
        if role:
            member = guild.get_member(payload.user_id)
            if member:
                try:
                    await member.remove_roles(role)
                    await log_discord(
                        "❌ Снята реакционная роль",
                        f"> **Пользователь:** {member.mention}\n> **Роль:** {role.mention}\n> **Реакция:** {payload.emoji}",
                        color=0xff0000
                    )
                except Exception as e:
                    await log_discord("❌ Ошибка снятия реакционной роли", str(e), color=0xff0000)

# ================= ОТЗЫВЫ И БАННЕР =================
async def update_review_counter(silent: bool = False):
    try:
        text_ch = bot.get_channel(CONFIG["REVIEW_COUNT_CHANNEL"])
        if not text_ch:
            text_ch = await bot.fetch_channel(CONFIG["REVIEW_COUNT_CHANNEL"])
        if not text_ch:
            print("[WARN] update_review_counter: review channel not found")
            return
        count = 1431
        async for m in text_ch.history(limit=None):
            count += 1
        print(f"[INFO] Review count: {count}")
        await update_server_banner(count, silent)
    except Exception as e:
        print(f"[ERROR] update_review_counter: {e}")
        if not silent:
            await log_discord("❌ Ошибка обновления счётчика отзывов", f"> **Ошибка:** `{str(e)}`", color=0xff0000)

async def update_server_banner(review_count: int, silent: bool = False):
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_path = os.path.join(script_dir, "banner.png")
        output_path = os.path.join(script_dir, "banner_ready.png")
        font_path = os.path.join(script_dir, "ProximaNova-ExtraBold.ttf")

        if not os.path.exists(base_path):
            print(f"[WARN] Banner file not found: {base_path}")
            return
        if not os.path.exists(font_path):
            print(f"[WARN] Font file not found: {font_path}")
            return

        img = Image.open(base_path).convert("RGBA")
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype(font_path, 400)
        text = str(review_count)
        draw.text((594, 540), text, font=font, fill=(255, 255, 255), anchor="mm")
        img.save(output_path)

        guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
        if not guild:
            print("[WARN] update_server_banner: guild not found")
            return
        with open(output_path, "rb") as f:
            await guild.edit(banner=f.read())
        print(f"[INFO] Banner updated with {review_count} reviews")
        if not silent:
            await log_discord("🖼️ Баннер обновлён", f"> **Количество отзывов:** `{review_count}`", color=0x00aaff)
    except Exception as e:
        print(f"[ERROR] Banner update error: {e}")
        if not silent:
            await log_discord("❌ Ошибка обновления баннера", f"> **Ошибка:** `{str(e)}`", color=0xff0000)

@tasks.loop(hours=24)
async def review_counter_task():
    await bot.wait_until_ready()
    await update_review_counter(silent=False)

@bot.event
async def on_message(message: disnake.Message):
    if message.author.bot:
        return

    if message.channel.id == CONFIG["REVIEW_COUNT_CHANNEL"]:
        counts = load_json(FILES["review_counts"], {})
        user_id = str(message.author.id)
        counts[user_id] = counts.get(user_id, 0) + 1
        save_json(FILES["review_counts"], counts)
        if isinstance(message.author, disnake.Member):
            await update_user_roles(message.author, counts[user_id])
            await log_discord(
                "✍️ Новый отзыв",
                f"> **Автор:** {message.author.mention}\n> **Теперь отзывов:** `{counts[user_id]}`",
                color=0x00ff00
            )
        return

    await bot.process_commands(message)

# ================= КОМАНДЫ =================
@bot.slash_command(name="refresh_panel", description="Обновить панель с кнопками (админ)")
@log_command
async def refresh_panel(ctx):
    await ctx.response.defer(ephemeral=True)
    channel = bot.get_channel(CONFIG["PANEL_CHANNEL_ID"])
    if not channel:
        return await ctx.edit_original_response(content="❌ Канал панели не найден.")
    deleted = 0
    async for msg in channel.history(limit=50):
        if msg.author == bot.user and msg.components:
            await msg.delete()
            deleted += 1
    try:
        with open(CONFIG["MENU_EMBED_PATH"], "r", encoding="utf-8") as f:
            menu_data = json.load(f)
        embed = disnake.Embed.from_dict(clean_embed_for_discohook(menu_data["embeds"][0]))
    except Exception as e:
        embed = disnake.Embed(color=0x676767)
        embed.set_image(url="https://cdn.discordapp.com/attachments/1485322161794056202/1531330433965621258/image.png?ex=6a68d21a&is=6a67809a&hm=43e08539a51f7994a7c5cbcc900a7bae1c07beeb16dca78f4784bfcd5afa58ec&")
    await channel.send(embed=embed, view=TicketPanelView())
    await ctx.edit_original_response(content=f"✅ Панель обновлена (удалено {deleted} старых сообщений).")
    await log_discord("🔄 Панель обновлена", f"> **Админ:** {ctx.author.mention}")

@bot.slash_command(name="say", description="Отправить сообщение от лица бота (админ)")
async def say(ctx, канал: disnake.TextChannel, тип: str = commands.Param(choices=["text", "embed"]), текст: Optional[str] = None, файл: Optional[disnake.Attachment] = None):
    if not has_admin_roles(ctx.author):
        return await ctx.send("⛔ Нет прав", ephemeral=True)
    if тип == "text":
        if not текст:
            return await ctx.send("Введите текст.", ephemeral=True)
        await канал.send(текст)
        await ctx.send("✅ Текст отправлен", ephemeral=True)
        await log_discord("📨 Say: текст", f"> **Админ:** {ctx.author.mention}\n> **Канал:** {канал.mention}")
        return
    if тип == "embed":
        if not текст and not файл:
            return await ctx.send("Укажите JSON или файл.", ephemeral=True)
        if текст and файл:
            return await ctx.send("Только один источник.", ephemeral=True)
        try:
            if файл:
                raw = await файл.read()
                data = json.loads(raw.decode("utf-8"))
            else:
                data = json.loads(текст)
            if "embeds" not in data:
                return await ctx.send("Нет поля 'embeds'.", ephemeral=True)
            embeds = [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data["embeds"]]
            content = data.get("content", " ")
            await канал.send(content=content, embeds=embeds)
            await ctx.send("✅ Embed отправлен", ephemeral=True)
            await log_discord("📨 Say: embed", f"> **Админ:** {ctx.author.mention}\n> **Канал:** {канал.mention}")
        except Exception as e:
            await ctx.send(f"❌ Ошибка: {e}", ephemeral=True)

@bot.slash_command(name="promo_add", description="Добавить промокод (админ)")
@log_command
async def promo_add(ctx, code: str, value: str):
    code = code.upper()
    promo_codes[code] = value
    save_json(FILES["promo"], promo_codes)
    await ctx.send(f"✅ Промокод `{code}` добавлен → {value}", ephemeral=True)
    await log_discord("➕ Промокод добавлен", f"> **Админ:** {ctx.author.mention}\n> **Код:** `{code}`\n> **Скидка:** `{value}`")

@bot.slash_command(name="promo_remove", description="Удалить промокод (админ)")
@log_command
async def promo_remove(ctx, code: str):
    code = code.upper()
    if code in promo_codes:
        promo_codes.pop(code)
        save_json(FILES["promo"], promo_codes)
        await ctx.send(f"✅ Промокод `{code}` удалён", ephemeral=True)
        await log_discord("➖ Промокод удалён", f"> **Админ:** {ctx.author.mention}\n> **Код:** `{code}`")
    else:
        await ctx.send("❌ Нет такого промокода", ephemeral=True)

@bot.slash_command(name="promo_list", description="Список промокодов (админ)")
@log_command
async def promo_list(ctx):
    if not promo_codes:
        return await ctx.send("Промокодов нет.", ephemeral=True)
    text = "\n".join([f"{k} → {v}" for k, v in promo_codes.items()])
    await ctx.send(f"```\n{text}\n```", ephemeral=True)

@bot.slash_command(name="profile", description="Показать профиль пользователя")
async def profile(inter, user: disnake.Member = None):
    user = user or inter.author
    counts = load_json(FILES["review_counts"], {})
    count = counts.get(str(user.id), 0)
    roles = get_roles_for_count(count)
    role_mentions = ", ".join([inter.guild.get_role(r).mention for r in roles if inter.guild.get_role(r)]) if roles else "Нет"
    embed = disnake.Embed(title=f"📋 Профиль {user.display_name}", color=user.color or 0x676767)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="👤 Роли покупателя", value=role_mentions, inline=False)
    embed.add_field(name="✍️ Отзывов", value=str(count), inline=True)
    embed.add_field(name="👑 Высшая роль", value=user.top_role.mention if user.top_role else "Нет", inline=True)
    embed.set_footer(text=f"ID: {user.id}")
    await inter.send(embed=embed, ephemeral=True)
    await log_discord("👤 Профиль", f"> **Кто:** {inter.author.mention}\n> **Профиль:** {user.mention}")

@bot.slash_command(name="пересчитать_отзывы", description="Пересчитать отзывы и обновить роли (админ)")
@log_command
async def пересчитать_отзывы(ctx):
    await ctx.response.defer(ephemeral=True)
    channel = bot.get_channel(CONFIG["REVIEW_COUNT_CHANNEL"])
    if not channel:
        return await ctx.edit_original_response(content="❌ Канал отзывов не найден.")
    counts = {}
    try:
        async for message in channel.history(limit=None):
            if message.author.bot:
                continue
            uid = str(message.author.id)
            counts[uid] = counts.get(uid, 0) + 1
    except Exception as e:
        return await ctx.edit_original_response(content=f"❌ Ошибка: {e}")
    if not counts:
        return await ctx.edit_original_response(content="ℹ️ Нет отзывов.")
    save_json(FILES["review_counts"], counts)
    guild = ctx.guild or bot.get_guild(int(CONFIG["GUILD_ID"]))
    if not guild:
        return await ctx.edit_original_response(content="❌ Сервер не найден.")
    updated = 0
    for uid_str, count in counts.items():
        uid = int(uid_str)
        member = guild.get_member(uid)
        if member:
            await update_user_roles(member, count)
            updated += 1
    await ctx.edit_original_response(
        content=f"✅ Пересчёт завершён!\nВсего пользователей: {len(counts)}\nОбновлено ролей: {updated}"
    )
    await log_discord(
        "📊 Пересчёт отзывов",
        f"> **Админ:** {ctx.author.mention}\n> **Записей:** `{len(counts)}`\n> **Ролей обновлено:** `{updated}`",
        color=0x00aaff
    )

# ================= REACTION ROLE (команда) - только ОДИН РАЗ =================
@bot.slash_command(name="reactionrole", description="Управление реакционными ролями")
async def reactionrole(inter: disnake.ApplicationCommandInteraction):
    pass

@reactionrole.sub_command(name="add", description="Добавить реакционную роль")
async def reactionrole_add(
    inter: disnake.ApplicationCommandInteraction,
    message_id: str,
    emoji: str,
    role: disnake.Role
):
    if not has_admin_roles(inter.author):
        return await inter.send("⛔ У вас нет прав.", ephemeral=True)

    try:
        msg = await inter.channel.fetch_message(int(message_id))
    except Exception:
        return await inter.send("❌ Сообщение не найдено в этом канале.", ephemeral=True)

    db.execute("INSERT INTO reaction_roles (guild_id, channel_id, message_id, emoji, role_id) VALUES (?, ?, ?, ?, ?)",
               (inter.guild.id, inter.channel.id, int(message_id), emoji, role.id))
    db.commit()

    try:
        await msg.add_reaction(disnake.PartialEmoji.from_str(emoji) if ":" in emoji else emoji)
    except Exception as e:
        await inter.send(f"⚠️ Не удалось поставить реакцию: {e}", ephemeral=True)
        return

    embed = disnake.Embed(
        title="✅ Реакционная роль добавлена",
        description=f"На сообщение {msg.jump_url} добавлена реакция {emoji}, выдающая роль {role.mention}.",
        color=0x00ff00
    )
    await inter.send(embed=embed, ephemeral=True)

    await log_discord(
        "➕ Добавлена реакционная роль",
        f"> **Админ:** {inter.author.mention}\n> **Реакция:** {emoji} → {role.mention}\n> **Сообщение:** [ссылка]({msg.jump_url})",
        color=0x00aaff
    )

# ================= INVITES (команда) =================
@bot.slash_command(name="invites", description="Статистика инвайтов пользователя")
async def invites(inter: disnake.ApplicationCommandInteraction, user: disnake.Member = None):
    user = user or inter.author
    stats = await get_invite_stats(inter.guild, user)
    if stats is None:
        return await inter.send("❌ Не удалось получить статистику.", ephemeral=True)

    embed = disnake.Embed(
        title=f"📨 Инвайты — {user.display_name}",
        color=0x676767,
        description=(
            f"**На сервере:** {stats['remaining']}\n"
            f"**Ушло:** {stats['left']}\n"
            f"**Ботов:** {stats['bots']}\n"
            f"**Фейков (ушли <10 мин):** {stats['fake']}\n"
            f"**Всего пришло:** {stats['total']}"
        )
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text="Статистика с момента запуска бота")
    await inter.send(embed=embed, ephemeral=True)
    await log_discord("📊 Просмотр инвайтов", f"> **Кто:** {inter.author.mention}\n> **Профиль:** {user.mention}")

# ================= ПАНЕЛЬ (отправка при запуске) =================
async def send_panel():
    await bot.wait_until_ready()
    channel = bot.get_channel(CONFIG["PANEL_CHANNEL_ID"])
    if not channel:
        channel = await bot.fetch_channel(CONFIG["PANEL_CHANNEL_ID"])
    if not channel:
        print("[WARN] Панельный канал не найден")
        return

    async for msg in channel.history(limit=50):
        if msg.author == bot.user and msg.components:
            return

    try:
        with open(CONFIG["MENU_EMBED_PATH"], "r", encoding="utf-8") as f:
            menu_data = json.load(f)
        embed = disnake.Embed.from_dict(clean_embed_for_discohook(menu_data["embeds"][0]))
    except Exception as e:
        print(f"[WARN] Не удалось загрузить menu_embed.json, используется fallback: {e}")
        embed = disnake.Embed(color=0x676767)
        embed.set_image(url="https://cdn.discordapp.com/attachments/1485322161794056202/1531330433965621258/image.png?ex=6a68d21a&is=6a67809a&hm=43e08539a51f7994a7c5cbcc900a7bae1c07beeb16dca78f4784bfcd5afa58ec&")
    await channel.send(embed=embed, view=TicketPanelView())
    await log_discord("🖼️ Панель отправлена", "Панель тикетов успешно отправлена в канал.")

# ================= ON_READY =================
@bot.event
async def on_ready():
    reset_flag = db.execute("SELECT value FROM settings WHERE key='invites_reset_done'").fetchone()
    if not reset_flag:
        db.execute("DELETE FROM invites")
        db.execute("DELETE FROM invites_snapshot")
        db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('invites_reset_done', '1')")
        db.commit()
        await log_discord("🔄 Сброс инвайтов", "Старые данные по инвайтам удалены. Начинаем учёт с нуля.", color=0xff6600)
        print("[INFO] Инвайты сброшены.")

    for guild in bot.guilds:
        await sync_invites(guild)

    await bot.change_presence(activity=disnake.Game(name="Основной работник"))
    bot.loop.create_task(send_panel())

    if not review_counter_task.is_running():
        review_counter_task.start()

    await log_discord("✅ Бот запущен", f"> **Gold Shop** готов к работе.", color=0x00ff00)
    print(f"✅ Bot ready as {bot.user}")

# ================= RUN =================
if __name__ == "__main__":
    if not CONFIG["BOT_TOKEN"]:
        print("❌ Токен не найден")
        sys.exit(1)
    try:
        bot.run(CONFIG["BOT_TOKEN"])
    except Exception as e:
        print(f"Ошибка запуска: {e}")
