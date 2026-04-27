"""War Empire Telegram Bot - main entry.

State is scoped PER GROUP (chat_id). A user has independent coins, team and
projects in every group where they /start the bot. Admin actions operate on
the group where /admin was run."""
import os
import time
import logging
import random
from collections import defaultdict

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatType, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import BadRequest, Forbidden

import database as db
import game

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("warbot")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_USER_ID = 6069597294

AWAIT_KEY = "awaiting"
AWAIT_DATA_KEY = "awaiting_data"
ADMIN_CHAT_KEY = "admin_chat_id"

AUCTION_INTERVAL_MINUTES = 8
AUCTION_DURATION_SECONDS = 90
TICK_SECONDS = game.TICK_SECONDS  # 5 seconds

# Owner-locked actions: only the user who opened the menu can use them
OWNER_LOCKED_ACTIONS = {
    "menu", "profile", "projects", "buildmenu", "build", "build_qty", "collect",
    "upgrade", "upgrade_do",
    "team", "team_create", "team_cancel", "team_browse", "team_join",
    "team_toggle", "team_members", "team_kick", "team_kick_do",
    "team_leave", "team_requests",
    "team_disband", "team_disband_yes",
    "attack_menu", "attack_do",
    "shop", "shop_item", "shop_buy",
    "lb", "lb_players", "lb_power", "lb_wealth",
    "help",
    # admin actions (owner_id will always be ADMIN_USER_ID)
    "amenu", "a_money", "a_proj", "a_proj_pick", "a_weap", "a_weap_pick",
    "a_stats", "a_auction_now", "a_broadcast",
    "a_reset", "a_reset_money", "a_reset_proj", "a_reset_sold",
    "a_reset_money_one", "a_reset_money_all_ask", "a_reset_money_all_yes",
    "a_reset_proj_one", "a_reset_proj_all_ask", "a_reset_proj_all_yes",
    "a_reset_sold_one", "a_reset_sold_all_ask", "a_reset_sold_all_yes",
}


PRIVATE_REDIRECT_TEXT = (
    "🏰 <b>أهلاً بك في إمبراطورية الحروب والمزادات</b> 🏰\n\n"
    "👋 شكراً لتواصلك معي!\n\n"
    "⚠️ <b>هذا البوت يعمل داخل المجموعات فقط.</b>\n\n"
    "📌 <b>للبدء، اتّبع هذه الخطوات:</b>\n"
    "1️⃣ أضِف البوت إلى مجموعتك (Group / Supergroup).\n"
    "2️⃣ ارفع البوت إلى رتبة <b>مشرف (Admin)</b> لكي يستطيع إدارة المزادات وإرسال الإشعارات.\n"
    "3️⃣ بعد ذلك، اكتب /start داخل المجموعة لتفتح قائمتك الخاصة وتبدأ ببناء إمبراطوريتك.\n\n"
    "⚔️ <b>ملاحظة مهمة:</b> كل مجموعة لها لعبتها المستقلة! "
    "أموالك ومشاريعك وفريقك في مجموعة واحدة لا تنتقل إلى مجموعات أخرى.\n\n"
    "🎯 بالتوفيق، أيها القائد!"
)


HELP_TEXT = (
    "📖 <b>شرح اللعبة — إمبراطورية الحروب والمزادات</b>\n"
    "━━━━━━━━━━━━━━━\n\n"
    "🌐 <b>كل مجموعة = لعبة مستقلة:</b> تقدّمك (مال، مشاريع، فريق) محفوظ "
    "في هذه المجموعة فقط ولا ينتقل إلى مجموعات أخرى.\n\n"
    "👤 <b>1) الملف الشخصي</b>\n"
    f"يعرض رصيدك من العملات، فريقك، ورتبتك. كل لاعب يبدأ بـ <b>5,000 عملة</b>.\n\n"
    "🏗️ <b>2) المشاريع</b>\n"
    f"ابنِ مشاريع تدرّ عليك دخلاً تلقائياً كل <b>{TICK_SECONDS} ثوانٍ</b>. "
    "يمكنك بناء أي عدد تريده من نفس النوع (مثلاً 5 مطاعم).\n"
    "الأنواع المتاحة: ☕ مقهى، 🏪 كشك، 🍽️ مطعم، 🛒 سوبرماركت، 🏭 مصنع، 🏨 فندق، 🛢️ بئر نفط، 🏦 بنك خاص.\n"
    "📈 <b>تطوير المشاريع:</b> اضغط «📈 تطوير …» لرفع مستوى مشروع واحد أو دفعة. "
    f"كل مستوى يضيف +<b>{game.LEVEL_INCOME_PCT_PER_STEP}%</b> من الدخل الأصلي حتى المستوى <b>{game.MAX_PROJECT_LEVEL}</b>. "
    "تكلفة التطوير ترتفع كلما رفعت المستوى — تطوير متدرّج ومتوازن.\n"
    "اضغط «جمع الأرباح» للتحصيل الفوري.\n\n"
    "🛡️ <b>3) الفرق (التحالفات)</b>\n"
    "أنشئ فريقاً وتصبح قائده أو اطلب الانضمام لفريق مفتوح. القائد يتحكم بالخزنة، يقبل/يرفض الطلبات، يطرد الأعضاء، يفتح أو يقفل الانضمام والهجوم، وله زر <b>💥 إغلاق/حلّ الفريق</b> نهائياً.\n"
    "🛡️ <b>قفل الهجوم</b> يضع فريقك في وضع دفاعي كامل: لا تستطيع الهجوم على غيرك، ولا يستطيع أحد الهجوم عليك.\n\n"
    "🛒 <b>4) المتجر العسكري</b>\n"
    "بعد الانضمام لفريق، اشترِ معدات تُودَع في الخزنة المشتركة:\n"
    "• 💂 جنود (مفرد، نخبة، كتيبة)\n"
    "• 🚀 صواريخ (عادية، متطورة)\n"
    "• 🛡️ مضادات (مفرد، درع شامل)\n\n"
    "⚔️ <b>5) الحروب</b>\n"
    "القائد يستطيع شنّ هجوم على فريق آخر <b>داخل نفس المجموعة</b>. <b>المال لا علاقة له بالحرب إطلاقاً</b>.\n"
    "• إذا فاز المهاجم: <b>الخاسر فقط</b> يخسر مضاداته وتتضرر مشاريعه 10%–100%. المهاجم يحتفظ بكل وحداته.\n"
    "• إذا فشل الهجوم: المهاجم يخسر <b>~80%</b> من جنوده وصواريخه فقط، ويبقى لديه <b>~20%</b> ينسحبون. الدفاع يحتفظ بكل شيء.\n"
    "الدخل ينخفض تبعاً لنسبة التلف. عند بلوغ الضرر 100% يُدمَّر المشروع.\n\n"
    "🎯 <b>6) المزادات التلقائية</b>\n"
    f"كل <b>{AUCTION_INTERVAL_MINUTES} دقائق</b> يفتح البوت مزاداً سريعاً مدته 90 ثانية بأحد ثلاثة صناديق:\n"
    "• 💰 صندوق الكنز — مال عشوائي (قد يصل إلى مليون عملة في حالات نادرة جداً)\n"
    "• 📦 صندوق موارد — أسلحة، مع فرصة ضئيلة جداً للأشياء النادرة (☢️ نووي، 🎖️ كتيبة، 🥷 وحدة تخفّي)\n"
    "• 🎁 صندوق مجهول — مفاجأة كاملة!\n"
    "زايد بأزرار <b>+100 / +500 / +1000</b>. الفائز يستلم محتويات الصندوق فوراً.\n\n"
    "🏆 <b>7) لوحة الشرف</b>\n"
    "لوحة الشرف خاصة بهذه المجموعة فقط: تابع ترتيبك بين أغنى لاعبيها، أقوى فرقها عسكرياً، وأثرى فرقها.\n\n"
    "🔒 <b>ملاحظة:</b> القائمة التي تفتحها بـ /start مخصّصة لك وحدك."
)


# ============== UTILITIES ==============

def fmt_user(row) -> str:
    if row is None:
        return "?"
    name = row["first_name"] or row["username"] or str(row["user_id"])
    return name


def cb(action: str, owner_id: int, *args) -> str:
    parts = [action, str(owner_id)] + [str(a) for a in args]
    return "|".join(parts)


def cb_free(action: str, *args) -> str:
    return "|".join([action] + [str(a) for a in args])


def cid_from_query(query) -> int:
    """Group chat_id where the menu was opened (callback always comes from there)."""
    return query.message.chat.id


def main_menu_kb(owner_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("👤 ملفي الشخصي", callback_data=cb("profile", owner_id))],
        [InlineKeyboardButton("🏗️ مشاريعي", callback_data=cb("projects", owner_id))],
        [InlineKeyboardButton("🛡️ فريقي", callback_data=cb("team", owner_id))],
        [InlineKeyboardButton("🛒 المتجر العسكري", callback_data=cb("shop", owner_id))],
        [InlineKeyboardButton("🏆 لوحة الشرف", callback_data=cb("lb", owner_id))],
        [InlineKeyboardButton("📖 شرح اللعبة", callback_data=cb("help", owner_id))],
    ]
    if owner_id == ADMIN_USER_ID:
        rows.append([InlineKeyboardButton("👑 لوحة الإدمن", callback_data=cb("amenu", owner_id))])
    return InlineKeyboardMarkup(rows)


def back_to_menu_kb(owner_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ القائمة الرئيسية", callback_data=cb("menu", owner_id))]]
    )


async def safe_edit(query, text: str, reply_markup=None):
    try:
        await query.edit_message_text(
            text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
        )
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return
        await query.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


def project_effective_income(p) -> int:
    info = game.PROJECTS.get(p["ptype"])
    if not info:
        return 0
    level = p["level"] if "level" in p.keys() else 0
    base = info["income_per_tick"] * game.level_income_multiplier(level)
    return int(base * (100 - p["damage"]) / 100)


# ============== /start ==============

WELCOME = (
    f"🏰 <b>أهلاً بك في إمبراطورية الحروب والمزادات</b> 🏰\n\n"
    f"⚔️ ابنِ إمبراطوريتك، جنّد جيشك، أنشئ مشاريعك، واحكم بقبضة من حديد.\n"
    f"💰 لديك <b>5,000 عملة</b> كرصيد ابتدائي.\n"
    f"⏱️ المشاريع تدرّ دخلاً تلقائياً كل <b>{TICK_SECONDS} ثوانٍ</b>.\n\n"
    f"🌐 <i>تقدّمك محفوظ في هذه المجموعة فقط.</i>\n"
    f"🔒 <i>هذه القائمة مخصّصة لك وحدك — على الآخرين كتابة /start ليفتحوا قائمتهم.</i>\n\n"
    f"اختر من الأزرار أدناه:"
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if user is None or chat is None:
        return

    # Private chat: redirect (admin uses /admin instead)
    if chat.type == ChatType.PRIVATE:
        await update.message.reply_text(PRIVATE_REDIRECT_TEXT, parse_mode=ParseMode.HTML)
        return

    db.register_chat(chat.id, chat.title)
    db.get_or_create_user(user.id, chat.id, user.username, user.first_name)

    name = user.first_name or user.username or "قائد"
    text = f"🎯 <b>{name}</b>،\n\n" + WELCOME
    await update.message.reply_text(
        text, reply_markup=main_menu_kb(user.id), parse_mode=ParseMode.HTML
    )


# ============== ROUTER ==============

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is None or query.data is None:
        return
    parts = query.data.split("|")
    action = parts[0]
    user = query.from_user
    chat = query.message.chat

    # Make sure this user has a record for this chat (groups only).
    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        db.register_chat(chat.id, chat.title)
        db.get_or_create_user(user.id, chat.id, user.username, user.first_name)

    # Free actions: anyone can interact (bid, req)
    if action not in OWNER_LOCKED_ACTIONS:
        await query.answer()
        handler = ROUTES.get(action)
        if handler is None:
            return
        try:
            await handler(update, context, parts)
        except Exception as e:
            log.exception("callback error: %s", e)
        return

    # Owner-locked: parts[1] must be owner_id
    try:
        owner_id = int(parts[1])
    except (IndexError, ValueError):
        await query.answer()
        return
    if owner_id != user.id:
        await query.answer(
            "⚠️ هذه القائمة ليست لك. اكتب /start لفتح قائمتك الخاصة.",
            show_alert=True,
        )
        return
    # Admin actions: extra check
    if action.startswith("a") and action in OWNER_LOCKED_ACTIONS and (
        action.startswith("amenu") or action.startswith("a_")
    ):
        if user.id != ADMIN_USER_ID:
            await query.answer("🚫 هذه اللوحة للإدمن فقط.", show_alert=True)
            return
        # Remember the group the admin is operating on (for awaiting flows
        # that may receive input in private).
        if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            context.user_data[ADMIN_CHAT_KEY] = chat.id

    await query.answer()
    handler = ROUTES.get(action)
    if handler is None:
        return
    try:
        await handler(update, context, parts)
    except Exception as e:
        log.exception("callback error: %s", e)
        try:
            await query.answer("حدث خطأ. حاول مرة أخرى.", show_alert=True)
        except Exception:
            pass


# ============== MAIN MENU ==============

async def h_menu(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    user = query.from_user
    name = user.first_name or user.username or "قائد"
    text = f"🎯 <b>{name}</b>،\n\n" + WELCOME
    await safe_edit(query, text, reply_markup=main_menu_kb(owner_id))


# ============== PROFILE ==============

async def h_profile(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    user = query.from_user
    cid = cid_from_query(query)
    u = db.get_user(user.id, cid)
    team_name = "—"
    rank = "🪖 جندي مستقل"
    if u and u["team_id"]:
        t = db.get_team(u["team_id"])
        if t:
            team_name = t["name"]
            rank = "👑 قائد" if t["leader_id"] == user.id else "⚔️ محارب"
    text = (
        f"👤 <b>الملف الشخصي</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🪪 الاسم: <b>{fmt_user(u)}</b>\n"
        f"🆔 المعرّف: <code>{user.id}</code>\n"
        f"💰 الرصيد: <b>{u['coins']:,}</b> عملة\n"
        f"🛡️ الفريق: <b>{team_name}</b>\n"
        f"🎖️ الرتبة: <b>{rank}</b>\n"
        f"<i>📍 خاص بهذه المجموعة فقط.</i>"
    )
    await safe_edit(query, text, reply_markup=back_to_menu_kb(owner_id))


# ============== PROJECTS ==============

async def h_projects(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    user = query.from_user
    cid = cid_from_query(query)
    projs = db.get_user_projects(user.id, cid)
    u = db.get_user(user.id, cid)

    text = (
        f"🏗️ <b>مشاريعي</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💰 رصيدك: <b>{u['coins']:,}</b> عملة\n\n"
    )
    upgrade_rows = []
    if not projs:
        text += "📭 لا توجد لديك مشاريع بعد.\n\n"
    else:
        groups = defaultdict(list)
        for p in projs:
            groups[p["ptype"]].append(p)
        total_income = 0
        text += f"<b>قائمة مشاريعك</b> (الدخل لكل {TICK_SECONDS} ثوانٍ):\n"
        for ptype, plist in groups.items():
            info = game.PROJECTS.get(ptype)
            if not info:
                continue
            total_eff = sum(project_effective_income(p) for p in plist)
            total_base = info["income_per_tick"] * len(plist)
            total_income += total_eff
            line = f"\n• {info['emoji']} <b>{info['name']} × {len(plist)}</b> — دخل: <b>{total_eff}</b>/{TICK_SECONDS}ث"
            if total_eff != total_base:
                line += f" (الأصلي {total_base})"
            text += line
            specials = [p for p in plist if p["damage"] > 0 or p["level"] > 0]
            for p in specials:
                tags = []
                if p["level"] > 0:
                    tags.append(f"⭐ مستوى {p['level']}")
                if p["damage"] > 0:
                    tags.append(f"💥 تالف {p['damage']}%")
                text += f"\n   #{p['id']} — " + " | ".join(tags)
            upgrade_rows.append([InlineKeyboardButton(
                f"📈 تطوير {info['emoji']} {info['name']}",
                callback_data=cb("upgrade", owner_id, ptype),
            )])
        text += f"\n\n📈 إجمالي دخلك: <b>{total_income}</b>/{TICK_SECONDS}ث\n"
    text += "\nاختر إجراء:"

    rows = [[InlineKeyboardButton("➕ بناء مشروع جديد", callback_data=cb("buildmenu", owner_id))]]
    if projs:
        rows.append([InlineKeyboardButton("💰 جمع الأرباح الآن", callback_data=cb("collect", owner_id))])
        rows.extend(upgrade_rows)
    rows.append([InlineKeyboardButton("⬅️ القائمة الرئيسية", callback_data=cb("menu", owner_id))])
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


# ---------- UPGRADE FLOW ----------

def _pick_lowest_level_projects(projs: list, n: int) -> list:
    upgradable = [p for p in projs if p["level"] < game.MAX_PROJECT_LEVEL]
    upgradable.sort(key=lambda p: (p["level"], p["id"]))
    return upgradable[:n]


def _calc_upgrade_cost(projects_to_upgrade: list, base_cost: int) -> int:
    return sum(game.level_upgrade_cost(base_cost, p["level"]) for p in projects_to_upgrade)


async def h_upgrade(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    ptype = parts[2]
    user = query.from_user
    cid = cid_from_query(query)
    if ptype not in game.PROJECTS:
        return
    info = game.PROJECTS[ptype]
    all_projs = db.get_user_projects(user.id, cid)
    plist = [p for p in all_projs if p["ptype"] == ptype]
    if not plist:
        await query.answer("لا تملك أي مشروع من هذا النوع.", show_alert=True)
        return
    u = db.get_user(user.id, cid)
    upgradable = [p for p in plist if p["level"] < game.MAX_PROJECT_LEVEL]
    count_total = len(plist)

    text = (
        f"📈 <b>تطوير {info['emoji']} {info['name']}</b>\n━━━━━━━━━━━━━━━\n"
        f"عدد ما تملك: <b>{count_total}</b>\n"
        f"💰 رصيدك: <b>{u['coins']:,}</b>\n\n"
        f"كل مستوى يضيف <b>{game.LEVEL_INCOME_PCT_PER_STEP}%</b> من الدخل الأصلي.\n"
        f"المستوى الأقصى: <b>{game.MAX_PROJECT_LEVEL}</b> "
        f"(= +{game.LEVEL_INCOME_PCT_PER_STEP * game.MAX_PROJECT_LEVEL}%)\n\n"
    )

    level_counts = defaultdict(int)
    for p in plist:
        level_counts[p["level"]] += 1
    text += "<b>التوزيع الحالي:</b>\n"
    for lvl in sorted(level_counts.keys()):
        eff = int(info["income_per_tick"] * game.level_income_multiplier(lvl))
        text += f"• مستوى {lvl}: {level_counts[lvl]} مشروع — {eff}/{TICK_SECONDS}ث لكل واحد\n"

    if not upgradable:
        text += "\n✅ كل مشاريعك بلغت المستوى الأقصى — لا حاجة للتطوير!"
        rows = [[InlineKeyboardButton("⬅️ رجوع للمشاريع", callback_data=cb("projects", owner_id))]]
        await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))
        return

    options = [1]
    if len(upgradable) >= 3:
        options.append(3)
    if len(upgradable) >= 5:
        options.append(5)
    if len(upgradable) > 5:
        options.append(10)
    options.append(len(upgradable))
    options = sorted(set(options))

    text += "\n<b>تكلفة الخيارات:</b>\n"
    rows = []
    button_row = []
    for n in options:
        chosen = _pick_lowest_level_projects(upgradable, n)
        cost = _calc_upgrade_cost(chosen, info["cost"])
        label = f"× {n}" if n != len(upgradable) else f"× الكل ({n})"
        text += f"• {label} → <b>{cost:,}</b> عملة\n"
        button_row.append(InlineKeyboardButton(
            label, callback_data=cb("upgrade_do", owner_id, ptype, n),
        ))
        if len(button_row) == 3:
            rows.append(button_row)
            button_row = []
    if button_row:
        rows.append(button_row)
    rows.append([InlineKeyboardButton("⬅️ رجوع", callback_data=cb("projects", owner_id))])
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


async def h_upgrade_do(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    ptype = parts[2]
    n = int(parts[3])
    user = query.from_user
    cid = cid_from_query(query)
    if ptype not in game.PROJECTS or n < 1:
        return
    info = game.PROJECTS[ptype]
    all_projs = db.get_user_projects(user.id, cid)
    plist = [p for p in all_projs if p["ptype"] == ptype]
    chosen = _pick_lowest_level_projects(plist, n)
    if not chosen:
        await query.answer("لا توجد مشاريع قابلة للتطوير.", show_alert=True)
        return
    cost = _calc_upgrade_cost(chosen, info["cost"])
    u = db.get_user(user.id, cid)
    if u["coins"] < cost:
        await query.answer(
            f"❌ تحتاج {cost:,} عملة (لديك {u['coins']:,}).",
            show_alert=True,
        )
        return
    db.add_coins(user.id, cid, -cost)
    db.upgrade_projects([p["id"] for p in chosen])
    await query.answer(
        f"✅ تم تطوير {len(chosen)} مشروع بـ {cost:,} عملة!",
        show_alert=True,
    )
    await h_upgrade(update, context, parts)


async def h_buildmenu(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    text = (
        f"🏗️ <b>اختر نوع المشروع للبناء:</b>\n━━━━━━━━━━━━━━━\n"
        f"<i>يمكنك بناء أي عدد من نفس النوع.</i>\n"
    )
    rows = []
    for key, info in game.PROJECTS.items():
        text += (
            f"\n{info['emoji']} <b>{info['name']}</b> — "
            f"تكلفة <b>{info['cost']:,}</b> | دخل <b>{info['income_per_tick']}</b>/{TICK_SECONDS}ث"
        )
        rows.append(
            [InlineKeyboardButton(
                f"{info['emoji']} {info['name']} ({info['cost']:,})",
                callback_data=cb("build_qty", owner_id, key),
            )]
        )
    rows.append([InlineKeyboardButton("⬅️ رجوع", callback_data=cb("projects", owner_id))])
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


async def h_build_qty(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    ptype = parts[2]
    if ptype not in game.PROJECTS:
        return
    info = game.PROJECTS[ptype]
    user = query.from_user
    cid = cid_from_query(query)
    u = db.get_user(user.id, cid)
    text = (
        f"{info['emoji']} <b>{info['name']}</b>\n━━━━━━━━━━━━━━━\n"
        f"تكلفة الوحدة: <b>{info['cost']:,}</b>\n"
        f"دخل الوحدة: <b>{info['income_per_tick']}</b>/{TICK_SECONDS}ث\n"
        f"رصيدك: <b>{u['coins']:,}</b>\n\n"
        f"اختر الكمية للبناء:"
    )
    rows = [
        [
            InlineKeyboardButton("× 1", callback_data=cb("build", owner_id, ptype, 1)),
            InlineKeyboardButton("× 3", callback_data=cb("build", owner_id, ptype, 3)),
            InlineKeyboardButton("× 5", callback_data=cb("build", owner_id, ptype, 5)),
        ],
        [
            InlineKeyboardButton("× 10", callback_data=cb("build", owner_id, ptype, 10)),
            InlineKeyboardButton("× 25", callback_data=cb("build", owner_id, ptype, 25)),
        ],
        [InlineKeyboardButton("⬅️ رجوع", callback_data=cb("buildmenu", owner_id))],
    ]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


async def h_build(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    user = query.from_user
    cid = cid_from_query(query)
    ptype = parts[2]
    qty = int(parts[3]) if len(parts) > 3 else 1
    if ptype not in game.PROJECTS or qty < 1:
        return
    info = game.PROJECTS[ptype]
    u = db.get_user(user.id, cid)
    total_cost = info["cost"] * qty
    if u["coins"] < total_cost:
        await query.answer(
            f"❌ تحتاج {total_cost:,} عملة (لديك {u['coins']:,}).",
            show_alert=True,
        )
        return
    db.add_coins(user.id, cid, -total_cost)
    db.add_projects_bulk(user.id, cid, ptype, qty)
    await query.answer(f"✅ تم بناء {qty} × {info['name']} بـ {total_cost:,}", show_alert=True)
    await h_projects(update, context, parts)


async def h_collect(update, context, parts):
    query = update.callback_query
    user = query.from_user
    cid = cid_from_query(query)
    earned = pay_user_projects(user.id, cid)
    await query.answer(f"💰 تم جمع {earned:,} عملة!", show_alert=True)
    await h_projects(update, context, parts)


def pay_user_projects(user_id: int, chat_id: int) -> int:
    projs = db.get_user_projects(user_id, chat_id)
    if not projs:
        return 0
    now = int(time.time())
    total = 0
    for p in projs:
        info = game.PROJECTS.get(p["ptype"])
        if not info:
            continue
        ticks = (now - p["last_payout_at"]) // TICK_SECONDS
        if ticks <= 0:
            continue
        level = p["level"] if "level" in p.keys() else 0
        base = info["income_per_tick"] * game.level_income_multiplier(level)
        eff = int(base * (100 - p["damage"]) / 100)
        gain = ticks * eff
        total += gain
        new_ts = p["last_payout_at"] + ticks * TICK_SECONDS
        db.update_project_payout(p["id"], new_ts)
    if total:
        db.add_coins(user_id, chat_id, total)
    return total


# ============== TEAM ==============

async def h_team(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    user = query.from_user
    cid = cid_from_query(query)
    u = db.get_user(user.id, cid)

    if u["team_id"] is None:
        text = (
            "🛡️ <b>فريقي</b>\n"
            "━━━━━━━━━━━━━━━\n"
            "أنت لا تنتمي لأي فريق حالياً <i>في هذه المجموعة</i>.\n"
            "أنشئ فريقك الخاص أو ابحث عن فريق منفتح للانضمام."
        )
        rows = [
            [InlineKeyboardButton("🛠️ إنشاء فريق", callback_data=cb("team_create", owner_id))],
            [InlineKeyboardButton("🔍 بحث عن فريق", callback_data=cb("team_browse", owner_id))],
            [InlineKeyboardButton("⬅️ القائمة الرئيسية", callback_data=cb("menu", owner_id))],
        ]
        await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))
        return

    t = db.get_team(u["team_id"])
    members = db.get_team_members(t["team_id"])
    is_leader = (t["leader_id"] == user.id)
    leader = db.get_user(t["leader_id"], t["chat_id"])

    text = (
        f"🛡️ <b>فريق {t['name']}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👑 القائد: <b>{fmt_user(leader)}</b>\n"
        f"👥 عدد الأعضاء: <b>{len(members)}</b>\n"
        f"💂 جنود: <b>{t['soldiers']:,}</b>\n"
        f"🚀 صواريخ: <b>{t['missiles']:,}</b>\n"
        f"🛡️ مضادات: <b>{t['antimissiles']:,}</b>\n"
        f"🚪 الانضمام: {'🔒 مغلق' if t['join_locked'] else '🔓 مفتوح'}\n"
        f"⚔️ الهجوم: {'🛡️ مقفل (دفاع كامل — لا يستطيع أحد مهاجمتك)' if t['attack_locked'] else '🔓 مسموح (يمكن مهاجمتك أيضاً)'}\n"
    )

    rows = [
        [InlineKeyboardButton("👥 عرض الأعضاء", callback_data=cb("team_members", owner_id))],
        [InlineKeyboardButton("🚪 مغادرة الفريق", callback_data=cb("team_leave", owner_id))],
    ]
    if is_leader:
        rows.insert(1, [
            InlineKeyboardButton(
                ("🔓 فتح الانضمام" if t["join_locked"] else "🔒 قفل الانضمام"),
                callback_data=cb("team_toggle", owner_id, "join_locked"),
            ),
            InlineKeyboardButton(
                ("🔓 فتح الهجوم" if t["attack_locked"] else "🛡️ قفل الهجوم (دفاع)"),
                callback_data=cb("team_toggle", owner_id, "attack_locked"),
            ),
        ])
        rows.insert(2, [InlineKeyboardButton("⚔️ شنّ هجوم", callback_data=cb("attack_menu", owner_id))])
        rows.insert(3, [InlineKeyboardButton("📥 طلبات الانضمام", callback_data=cb("team_requests", owner_id))])
        rows.insert(4, [InlineKeyboardButton("🚫 طرد عضو", callback_data=cb("team_kick", owner_id))])
        rows.append([InlineKeyboardButton("💥 إغلاق/حلّ الفريق", callback_data=cb("team_disband", owner_id))])
    rows.append([InlineKeyboardButton("⬅️ القائمة الرئيسية", callback_data=cb("menu", owner_id))])
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


# ---------- DISBAND TEAM ----------

async def h_team_disband(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    user = query.from_user
    cid = cid_from_query(query)
    u = db.get_user(user.id, cid)
    t = db.get_team(u["team_id"]) if u["team_id"] else None
    if not t or t["leader_id"] != user.id:
        await query.answer("هذا الإجراء للقائد فقط.", show_alert=True)
        return
    members = db.get_team_members(t["team_id"])
    text = (
        f"⚠️ <b>تأكيد إغلاق الفريق</b>\n━━━━━━━━━━━━━━━\n"
        f"🛡️ الفريق: <b>{t['name']}</b>\n"
        f"👥 الأعضاء الذين سيُخرجون: <b>{len(members)}</b>\n\n"
        f"<b>تنبيه:</b> هذا الإجراء يحلّ الفريق بشكل نهائي. "
        f"خزنة الفريق (جنود/صواريخ/مضادات) <u>ستضيع</u>، "
        f"وكل الأعضاء سيخرجون من الفريق.\n\n"
        f"المشاريع والمال الخاص بكل عضو لن تتأثر.\n\n"
        f"هل أنت متأكد؟"
    )
    rows = [
        [InlineKeyboardButton("⚠️ نعم، حلّ الفريق نهائياً", callback_data=cb("team_disband_yes", owner_id))],
        [InlineKeyboardButton("❌ تراجع", callback_data=cb("team", owner_id))],
    ]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


async def h_team_disband_yes(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    user = query.from_user
    cid = cid_from_query(query)
    u = db.get_user(user.id, cid)
    t = db.get_team(u["team_id"]) if u["team_id"] else None
    if not t or t["leader_id"] != user.id:
        await query.answer("هذا الإجراء للقائد فقط.", show_alert=True)
        return
    team_name = t["name"]
    members = db.get_team_members(t["team_id"])
    db.delete_team(t["team_id"])
    await query.answer(f"💥 تم حلّ فريق {team_name}.", show_alert=True)
    for m in members:
        if m["user_id"] == user.id:
            continue
        try:
            await context.bot.send_message(
                m["user_id"],
                f"⚠️ تم حلّ فريق <b>{team_name}</b> بواسطة القائد.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    text = (
        f"💥 <b>تم حلّ الفريق بنجاح</b>\n━━━━━━━━━━━━━━━\n"
        f"الفريق <b>{team_name}</b> أُغلق نهائياً وخرج جميع أعضائه."
    )
    await safe_edit(query, text, reply_markup=back_to_menu_kb(owner_id))


async def h_team_create(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    cid = cid_from_query(query)
    context.user_data[AWAIT_KEY] = "team_name"
    context.user_data[AWAIT_DATA_KEY] = str(cid)
    text = (
        "🛠️ <b>إنشاء فريق جديد</b>\n━━━━━━━━━━━━━━━\n"
        "أرسل الآن اسم فريقك (3-30 حرف) كرسالة نصية عادية <b>داخل هذه المجموعة</b>.\n"
        "ستصبح أنت القائد الذي يتحكم بكل قرارات الفريق."
    )
    rows = [[InlineKeyboardButton("❌ إلغاء", callback_data=cb("team_cancel", owner_id))]]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


async def h_team_cancel(update, context, parts):
    context.user_data.pop(AWAIT_KEY, None)
    context.user_data.pop(AWAIT_DATA_KEY, None)
    await h_team(update, context, parts)


async def h_team_browse(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    cid = cid_from_query(query)
    teams = db.list_open_teams(cid, 20)
    text = "🔍 <b>الفرق المفتوحة للانضمام</b> <i>(في هذه المجموعة)</i>\n━━━━━━━━━━━━━━━\n"
    rows = []
    if not teams:
        text += "📭 لا توجد فرق مفتوحة حالياً. كن أول من يؤسس!"
    else:
        for t in teams:
            members = db.get_team_members(t["team_id"])
            text += f"\n🛡️ <b>{t['name']}</b> — 👥 {len(members)}\n"
            rows.append([InlineKeyboardButton(
                f"📩 طلب الانضمام إلى {t['name']}",
                callback_data=cb("team_join", owner_id, t["team_id"]),
            )])
    rows.append([InlineKeyboardButton("⬅️ رجوع", callback_data=cb("team", owner_id))])
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


async def h_team_join(update, context, parts):
    query = update.callback_query
    user = query.from_user
    cid = cid_from_query(query)
    team_id = int(parts[2])
    t = db.get_team(team_id)
    if not t or t["chat_id"] != cid:
        await query.answer("الفريق غير موجود في هذه المجموعة.", show_alert=True)
        return
    if t["join_locked"]:
        await query.answer("هذا الفريق أغلق الانضمام.", show_alert=True)
        return
    u = db.get_user(user.id, cid)
    if u["team_id"] is not None:
        await query.answer("أنت بالفعل في فريق. غادر فريقك أولاً.", show_alert=True)
        return
    req_id = db.create_join_request(user.id, team_id, cid)
    if req_id is None:
        await query.answer("لقد قمت بإرسال طلب لهذا الفريق سابقاً.", show_alert=True)
        return

    leader_id = t["leader_id"]
    notify_text = (
        f"📥 <b>طلب انضمام جديد</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 العضو: <b>{fmt_user(u)}</b> (<code>{user.id}</code>)\n"
        f"🛡️ إلى فريق: <b>{t['name']}</b>"
    )
    notify_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ قبول", callback_data=cb_free("req", "accept", req_id)),
        InlineKeyboardButton("❌ رفض", callback_data=cb_free("req", "reject", req_id)),
    ]])
    sent_to_leader = False
    try:
        await context.bot.send_message(
            leader_id, notify_text, parse_mode=ParseMode.HTML, reply_markup=notify_kb
        )
        sent_to_leader = True
    except (Forbidden, BadRequest):
        try:
            await context.bot.send_message(
                t["chat_id"], notify_text, parse_mode=ParseMode.HTML, reply_markup=notify_kb
            )
            sent_to_leader = True
        except Exception:
            pass
    if sent_to_leader:
        await query.answer("✅ تم إرسال طلبك إلى القائد.", show_alert=True)
    else:
        await query.answer("تم تسجيل طلبك، لكن تعذّر إخطار القائد.", show_alert=True)


async def h_request(update, context, parts):
    query = update.callback_query
    user = query.from_user
    decision = parts[1]
    req_id = int(parts[2])
    req = db.get_join_request(req_id)
    if not req:
        await query.answer("الطلب غير موجود.", show_alert=True)
        return
    if req["status"] != "pending":
        await query.answer("تم البتّ في هذا الطلب مسبقاً.", show_alert=True)
        return
    t = db.get_team(req["team_id"])
    if not t or t["leader_id"] != user.id:
        await query.answer("هذا الإجراء للقائد فقط.", show_alert=True)
        return

    requester = db.get_user(req["user_id"], req["chat_id"])
    if decision == "accept":
        if requester and requester["team_id"] is not None:
            db.update_join_request(req_id, "rejected")
            await safe_edit(query, "❌ هذا العضو موجود بالفعل في فريق آخر.")
            return
        db.set_user_team(req["user_id"], req["chat_id"], t["team_id"])
        db.update_join_request(req_id, "accepted")
        await safe_edit(query,
            f"✅ تم قبول <b>{fmt_user(requester)}</b> في فريق <b>{t['name']}</b>.",
        )
        try:
            await context.bot.send_message(
                req["user_id"],
                f"🎉 تم قبولك في فريق <b>{t['name']}</b>!",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    else:
        db.update_join_request(req_id, "rejected")
        await safe_edit(query,
            f"❌ تم رفض طلب <b>{fmt_user(requester)}</b>.",
        )
        try:
            await context.bot.send_message(
                req["user_id"],
                f"😔 تم رفض طلبك للانضمام إلى فريق <b>{t['name']}</b>.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


async def h_team_toggle(update, context, parts):
    query = update.callback_query
    user = query.from_user
    cid = cid_from_query(query)
    flag = parts[2]
    u = db.get_user(user.id, cid)
    t = db.get_team(u["team_id"]) if u["team_id"] else None
    if not t or t["leader_id"] != user.id:
        await query.answer("هذا الإجراء للقائد فقط.", show_alert=True)
        return
    new_val = db.toggle_team_flag(t["team_id"], flag)
    if flag == "join_locked":
        label = "الانضمام"
        state = "🔒 مقفل" if new_val else "🔓 مفتوح"
    else:
        label = "الهجوم"
        state = "🛡️ دفاع كامل (لا يستطيع أحد مهاجمتك)" if new_val else "🔓 مفتوح (يمكن مهاجمتك)"
    await query.answer(f"{label}: {state}", show_alert=True)
    await h_team(update, context, parts)


async def h_team_members(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    user = query.from_user
    cid = cid_from_query(query)
    u = db.get_user(user.id, cid)
    if not u["team_id"]:
        await query.answer("لست في أي فريق.", show_alert=True)
        return
    t = db.get_team(u["team_id"])
    members = db.get_team_members(t["team_id"])
    text = f"👥 <b>أعضاء فريق {t['name']}</b>\n━━━━━━━━━━━━━━━\n"
    for m in members:
        crown = "👑" if m["user_id"] == t["leader_id"] else "•"
        text += f"{crown} <b>{fmt_user(m)}</b> — 💰 {m['coins']:,}\n"
    rows = [[InlineKeyboardButton("⬅️ رجوع", callback_data=cb("team", owner_id))]]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


async def h_team_kick(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    user = query.from_user
    cid = cid_from_query(query)
    u = db.get_user(user.id, cid)
    t = db.get_team(u["team_id"]) if u["team_id"] else None
    if not t or t["leader_id"] != user.id:
        await query.answer("هذا الإجراء للقائد فقط.", show_alert=True)
        return
    members = db.get_team_members(t["team_id"])
    text = "🚫 <b>اختر عضواً للطرد:</b>\n━━━━━━━━━━━━━━━"
    rows = []
    for m in members:
        if m["user_id"] == t["leader_id"]:
            continue
        rows.append([InlineKeyboardButton(
            f"❌ {fmt_user(m)}",
            callback_data=cb("team_kick_do", owner_id, m["user_id"]),
        )])
    if not rows:
        text += "\n\nلا يوجد أعضاء آخرون لطردهم."
    rows.append([InlineKeyboardButton("⬅️ رجوع", callback_data=cb("team", owner_id))])
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


async def h_team_kick_do(update, context, parts):
    query = update.callback_query
    user = query.from_user
    cid = cid_from_query(query)
    target_id = int(parts[2])
    u = db.get_user(user.id, cid)
    t = db.get_team(u["team_id"]) if u["team_id"] else None
    if not t or t["leader_id"] != user.id:
        await query.answer("هذا الإجراء للقائد فقط.", show_alert=True)
        return
    target = db.get_user(target_id, cid)
    if not target or target["team_id"] != t["team_id"]:
        await query.answer("العضو ليس في فريقك.", show_alert=True)
        return
    db.set_user_team(target_id, cid, None)
    await query.answer(f"تم طرد {fmt_user(target)}.", show_alert=True)
    try:
        await context.bot.send_message(
            target_id,
            f"⚠️ تم طردك من فريق <b>{t['name']}</b>.",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass
    await h_team(update, context, parts)


async def h_team_leave(update, context, parts):
    query = update.callback_query
    user = query.from_user
    cid = cid_from_query(query)
    u = db.get_user(user.id, cid)
    if not u["team_id"]:
        await query.answer("لست في فريق.", show_alert=True)
        return
    t = db.get_team(u["team_id"])
    if t and t["leader_id"] == user.id:
        members = db.get_team_members(t["team_id"])
        if len(members) > 1:
            await query.answer(
                "أنت القائد. اطرد الأعضاء أو حلّ الفريق قبل المغادرة.",
                show_alert=True,
            )
            return
    db.set_user_team(user.id, cid, None)
    await query.answer("👋 غادرت الفريق.", show_alert=True)
    await h_team(update, context, parts)


async def h_team_requests(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    user = query.from_user
    cid = cid_from_query(query)
    u = db.get_user(user.id, cid)
    t = db.get_team(u["team_id"]) if u["team_id"] else None
    if not t or t["leader_id"] != user.id:
        await query.answer("هذا الإجراء للقائد فقط.", show_alert=True)
        return
    reqs = db.list_pending_requests_for_team(t["team_id"])
    text = "📥 <b>طلبات الانضمام المعلّقة</b>\n━━━━━━━━━━━━━━━\n"
    rows = []
    if not reqs:
        text += "لا توجد طلبات معلّقة."
    else:
        for r in reqs:
            requester = db.get_user(r["user_id"], r["chat_id"])
            text += f"• <b>{fmt_user(requester)}</b> (<code>{r['user_id']}</code>)\n"
            rows.append([
                InlineKeyboardButton("✅ قبول", callback_data=cb_free("req", "accept", r["id"])),
                InlineKeyboardButton("❌ رفض", callback_data=cb_free("req", "reject", r["id"])),
            ])
    rows.append([InlineKeyboardButton("⬅️ رجوع", callback_data=cb("team", owner_id))])
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


# ============== ATTACK ==============

async def h_attack_menu(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    user = query.from_user
    cid = cid_from_query(query)
    u = db.get_user(user.id, cid)
    t = db.get_team(u["team_id"]) if u["team_id"] else None
    if not t or t["leader_id"] != user.id:
        await query.answer("الهجوم متاح للقائد فقط.", show_alert=True)
        return
    if t["attack_locked"]:
        await query.answer(
            "فريقك في وضع الدفاع. افتح الهجوم أولاً (سيُلغي حمايتك أيضاً).",
            show_alert=True,
        )
        return
    teams = [x for x in db.list_all_teams_in_chat(cid) if x["team_id"] != t["team_id"]]
    text = (
        f"⚔️ <b>اختر فريقاً لشنّ الهجوم</b> <i>(في هذه المجموعة فقط)</i>\n━━━━━━━━━━━━━━━\n"
        f"قوة فريقك: 💂 {t['soldiers']:,} × 10 + 🚀 {t['missiles']:,} × 50 = "
        f"<b>{t['soldiers']*10 + t['missiles']*50:,}</b>\n\n"
        f"<i>📌 المال لا يدخل في الحرب — فقط الوحدات والمشاريع.</i>\n"
        f"<i>📌 الفرق التي قفلت الهجوم محميّة بالكامل ولا تظهر للهجوم.</i>\n"
    )
    rows = []
    attackable = [x for x in teams if not x["attack_locked"]]
    for x in attackable:
        defense = x["antimissiles"] * 40
        text += f"\n🛡️ <b>{x['name']}</b> — دفاع تقريبي: {defense:,}\n"
        rows.append([InlineKeyboardButton(
            f"⚔️ هاجم {x['name']}", callback_data=cb("attack_do", owner_id, x["team_id"]),
        )])
    if not attackable:
        if teams:
            text += "\n🛡️ كل الفرق الأخرى في وضع الدفاع — لا يمكن مهاجمتها."
        else:
            text += "\nلا يوجد أي فريق آخر في هذه المجموعة."
    rows.append([InlineKeyboardButton("⬅️ رجوع", callback_data=cb("team", owner_id))])
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


def calc_damage_pct(attack_power: int, defense_power: int) -> int:
    overwhelm = (attack_power - defense_power) / max(defense_power, 1)
    base = 15 + int(max(0, overwhelm) * 50)
    base += random.randint(-5, 20)
    return max(10, min(100, base))


async def h_attack_do(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    user = query.from_user
    cid = cid_from_query(query)
    target_team_id = int(parts[2])
    u = db.get_user(user.id, cid)
    attacker = db.get_team(u["team_id"]) if u["team_id"] else None
    target = db.get_team(target_team_id)
    if not attacker or attacker["leader_id"] != user.id:
        await query.answer("للقائد فقط.", show_alert=True)
        return
    if not target or target["chat_id"] != cid:
        await query.answer("الفريق المستهدف غير موجود في هذه المجموعة.", show_alert=True)
        return
    if attacker["attack_locked"]:
        await query.answer(
            "فريقك في وضع الدفاع — لا يمكنك الهجوم. افتح الهجوم أولاً.",
            show_alert=True,
        )
        return
    # >>> NEW: Target's attack-lock = full defense shield, cannot be attacked
    if target["attack_locked"]:
        await query.answer(
            f"🛡️ فريق «{target['name']}» في وضع الدفاع الكامل — لا يمكن مهاجمته.",
            show_alert=True,
        )
        return
    if attacker["soldiers"] == 0 and attacker["missiles"] == 0:
        await query.answer("لا تملك أي وحدات هجوم!", show_alert=True)
        return

    soldiers_used = attacker["soldiers"]
    missiles_used = attacker["missiles"]
    attack_power = soldiers_used * 10 + missiles_used * 50
    defense_power = target["antimissiles"] * 40

    if attack_power > defense_power:
        defense_consumed = min(target["antimissiles"], (attack_power // 40) + 1)
        if defense_consumed > 0:
            db.consume_defense(target["team_id"], defense_consumed)

        overwhelm = (attack_power - defense_power) / max(defense_power, 1)
        n_targets = 1
        if overwhelm > 1:
            n_targets = 2
        if overwhelm > 3:
            n_targets = 3

        damaged_projects = db.random_projects_for_team(target["team_id"], n_targets)
        damage_lines = []
        for proj in damaged_projects:
            dmg_pct = calc_damage_pct(attack_power, defense_power)
            new_total, destroyed = db.apply_project_damage(proj["id"], dmg_pct)
            owner = db.get_user(proj["owner_id"], proj["chat_id"])
            info = game.PROJECTS[proj["ptype"]]
            if destroyed:
                damage_lines.append(
                    f"💥 <b>دُمِّر بالكامل</b> {info['emoji']} {info['name']} الخاص بـ {fmt_user(owner)}!"
                )
            else:
                damage_lines.append(
                    f"💢 ضرر {dmg_pct}% على {info['emoji']} {info['name']} الخاص بـ {fmt_user(owner)} (إجمالي التلف: {new_total}%)"
                )

        damage_text = "\n".join(damage_lines) if damage_lines else "💨 لا توجد مشاريع للعدو."
        text = (
            f"🏆 <b>نصر ساحق!</b>\n━━━━━━━━━━━━━━━\n"
            f"⚔️ {attacker['name']} هاجم {target['name']}\n"
            f"💥 قوة الهجوم: <b>{attack_power:,}</b>\n"
            f"🛡️ قوة الدفاع: <b>{defense_power:,}</b>\n\n"
            f"{damage_text}\n\n"
            f"✨ <b>أنت لم تخسر أي وحدة</b> — احتفظت بكل جنودك وصواريخك.\n"
            f"🛡️ العدو خسر {defense_consumed} مضاد صواريخ."
        )
        try:
            await context.bot.send_message(
                target["leader_id"],
                f"🚨 <b>تعرّض فريقك لهجوم ناجح!</b>\n"
                f"المهاجم: <b>{attacker['name']}</b>\n\n{damage_text}\n\n"
                f"📉 خسرت {defense_consumed} مضاد. مشاريعك المتضررة ستولّد دخلاً أقل.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    else:
        keep_soldiers = soldiers_used // 5
        keep_missiles = missiles_used // 5
        lost_soldiers = soldiers_used - keep_soldiers
        lost_missiles = missiles_used - keep_missiles
        db.consume_attack_units(attacker["team_id"], lost_soldiers, lost_missiles)
        text = (
            f"💔 <b>الهجوم فشل!</b>\n━━━━━━━━━━━━━━━\n"
            f"⚔️ {attacker['name']} هاجم {target['name']}\n"
            f"💥 قوة الهجوم: <b>{attack_power:,}</b>\n"
            f"🛡️ قوة الدفاع: <b>{defense_power:,}</b>\n\n"
            f"📉 خسرت <b>{lost_soldiers}</b> جندي و <b>{lost_missiles}</b> صاروخ.\n"
            f"🪖 تبقّى لك: <b>{keep_soldiers}</b> جندي و <b>{keep_missiles}</b> صاروخ "
            f"(انسحبوا قبل المعركة).\n"
            f"🛡️ <b>العدو سليم تماماً</b> ولم يخسر شيئاً."
        )
        try:
            await context.bot.send_message(
                target["leader_id"],
                f"🛡️ <b>صدّ هجوم بنجاح!</b>\n"
                f"المهاجم: <b>{attacker['name']}</b>\n"
                f"النتيجة: <b>دفاع ناجح</b> — لم تخسر أي وحدة.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    rows = [[InlineKeyboardButton("⬅️ القائمة الرئيسية", callback_data=cb("menu", owner_id))]]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


# ============== SHOP ==============

async def h_shop(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    user = query.from_user
    cid = cid_from_query(query)
    u = db.get_user(user.id, cid)
    t = db.get_team(u["team_id"]) if u["team_id"] else None

    text = (
        f"🛒 <b>المتجر العسكري</b>\n━━━━━━━━━━━━━━━\n"
        f"💰 رصيدك: <b>{u['coins']:,}</b>\n"
    )
    if t:
        text += (
            f"🏰 خزنة فريق <b>{t['name']}</b>:\n"
            f"💂 جنود: {t['soldiers']:,} | 🚀 صواريخ: {t['missiles']:,} | 🛡️ مضادات: {t['antimissiles']:,}\n"
        )
    else:
        text += "\n⚠️ يجب أن تنضم لفريق أولاً لشراء المعدات وإيداعها في الخزنة.\n"
    text += "\nاختر منتجاً:\n"
    rows = []
    for key, info in game.SHOP_ITEMS.items():
        rows.append([InlineKeyboardButton(
            f"{info['emoji']} {info['name']} — {info['cost']:,} عملة",
            callback_data=cb("shop_item", owner_id, key),
        )])
    rows.append([InlineKeyboardButton("⬅️ القائمة الرئيسية", callback_data=cb("menu", owner_id))])
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


async def h_shop_item(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    user = query.from_user
    cid = cid_from_query(query)
    item_key = parts[2]
    if item_key not in game.SHOP_ITEMS:
        return
    info = game.SHOP_ITEMS[item_key]
    u = db.get_user(user.id, cid)
    if not u["team_id"]:
        await query.answer("يجب الانضمام لفريق أولاً.", show_alert=True)
        return
    text = (
        f"{info['emoji']} <b>{info['name']}</b>\n━━━━━━━━━━━━━━━\n"
        f"السعر للحزمة: <b>{info['cost']:,}</b> (تحصل على {info['qty']} وحدة)\n"
        f"رصيدك: <b>{u['coins']:,}</b>\n\n"
        f"اختر العدد للشراء وإيداعه في خزنة الفريق:"
    )
    rows = [
        [
            InlineKeyboardButton("× 1", callback_data=cb("shop_buy", owner_id, item_key, 1)),
            InlineKeyboardButton("× 5", callback_data=cb("shop_buy", owner_id, item_key, 5)),
            InlineKeyboardButton("× 10", callback_data=cb("shop_buy", owner_id, item_key, 10)),
        ],
        [
            InlineKeyboardButton("× 25", callback_data=cb("shop_buy", owner_id, item_key, 25)),
            InlineKeyboardButton("× 50", callback_data=cb("shop_buy", owner_id, item_key, 50)),
            InlineKeyboardButton("× 100", callback_data=cb("shop_buy", owner_id, item_key, 100)),
        ],
        [InlineKeyboardButton("⬅️ رجوع", callback_data=cb("shop", owner_id))],
    ]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


async def h_shop_buy(update, context, parts):
    query = update.callback_query
    user = query.from_user
    cid = cid_from_query(query)
    item_key = parts[2]
    qty = int(parts[3])
    if item_key not in game.SHOP_ITEMS:
        return
    info = game.SHOP_ITEMS[item_key]
    u = db.get_user(user.id, cid)
    if not u["team_id"]:
        await query.answer("يجب الانضمام لفريق أولاً.", show_alert=True)
        return
    total_cost = info["cost"] * qty
    if u["coins"] < total_cost:
        await query.answer(
            f"❌ تحتاج {total_cost:,} عملة (لديك {u['coins']:,}).", show_alert=True,
        )
        return
    units_added = info["qty"] * qty
    db.add_coins(user.id, cid, -total_cost)
    db.add_to_vault(u["team_id"], info["vault_field"], units_added)
    await query.answer(
        f"✅ تم شراء {qty} حزمة (= {units_added} وحدة) من {info['name']} بـ {total_cost:,}.",
        show_alert=True,
    )
    await h_shop(update, context, parts)


# ============== LEADERBOARD ==============

async def h_lb(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    text = (
        "🏆 <b>لوحة الشرف</b> <i>(لهذه المجموعة)</i>\n━━━━━━━━━━━━━━━\n"
        "اختر التصنيف:"
    )
    rows = [
        [InlineKeyboardButton("👤 أغنى اللاعبين", callback_data=cb("lb_players", owner_id))],
        [InlineKeyboardButton("⚔️ أقوى الفرق عسكرياً", callback_data=cb("lb_power", owner_id))],
        [InlineKeyboardButton("💰 أثرى الفرق", callback_data=cb("lb_wealth", owner_id))],
        [InlineKeyboardButton("⬅️ القائمة الرئيسية", callback_data=cb("menu", owner_id))],
    ]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


def medal(i: int) -> str:
    return ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."


async def h_lb_players(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    cid = cid_from_query(query)
    rows_data = db.top_players_by_coins(cid, 10)
    text = "👤 <b>أغنى 10 لاعبين</b> <i>(في هذه المجموعة)</i>\n━━━━━━━━━━━━━━━\n"
    if not rows_data:
        text += "لا يوجد لاعبون بعد."
    else:
        for i, u in enumerate(rows_data):
            t_name = ""
            if u["team_id"]:
                t = db.get_team(u["team_id"])
                if t:
                    t_name = f" ({t['name']})"
            text += f"{medal(i)} <b>{fmt_user(u)}</b>{t_name} — 💰 {u['coins']:,}\n"
    rows = [[InlineKeyboardButton("⬅️ رجوع", callback_data=cb("lb", owner_id))]]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


async def h_lb_power(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    cid = cid_from_query(query)
    rows_data = db.top_teams_by_power(cid, 10)
    text = "⚔️ <b>أقوى 10 فرق عسكرياً</b> <i>(في هذه المجموعة)</i>\n━━━━━━━━━━━━━━━\n"
    if not rows_data:
        text += "لا توجد فرق بعد."
    else:
        for i, t in enumerate(rows_data):
            text += (
                f"{medal(i)} <b>{t['name']}</b> — قوة <b>{t['power']:,}</b>\n"
                f"     💂 {t['soldiers']:,} | 🚀 {t['missiles']:,} | 🛡️ {t['antimissiles']:,}\n"
            )
    rows = [[InlineKeyboardButton("⬅️ رجوع", callback_data=cb("lb", owner_id))]]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


async def h_lb_wealth(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    cid = cid_from_query(query)
    rows_data = db.top_teams_by_wealth(cid, 10)
    text = "💰 <b>أثرى 10 فرق</b> <i>(في هذه المجموعة)</i>\n━━━━━━━━━━━━━━━\n"
    if not rows_data:
        text += "لا توجد فرق بعد."
    else:
        for i, t in enumerate(rows_data):
            text += (
                f"{medal(i)} <b>{t['name']}</b> — 💰 <b>{t['total_wealth']:,}</b>"
                f" (👥 {t['member_count']})\n"
            )
    rows = [[InlineKeyboardButton("⬅️ رجوع", callback_data=cb("lb", owner_id))]]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


async def h_help(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    rows = [[InlineKeyboardButton("⬅️ القائمة الرئيسية", callback_data=cb("menu", owner_id))]]
    await safe_edit(query, HELP_TEXT, reply_markup=InlineKeyboardMarkup(rows))


# ============== ADMIN PANEL ==============

def is_admin(uid: int) -> bool:
    return uid == ADMIN_USER_ID


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if user is None or update.message is None or chat is None:
        return
    if not is_admin(user.id):
        await update.message.reply_text("🚫 هذا الأمر للإدمن فقط.")
        return
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await update.message.reply_text(
            "⚠️ <b>/admin يعمل داخل المجموعة فقط.</b>\n"
            "اذهب إلى المجموعة التي تريد إدارتها وأرسل /admin هناك.",
            parse_mode=ParseMode.HTML,
        )
        return
    db.register_chat(chat.id, chat.title)
    db.get_or_create_user(user.id, chat.id, user.username, user.first_name)
    context.user_data[ADMIN_CHAT_KEY] = chat.id
    await update.message.reply_text(
        admin_menu_text(chat.title or str(chat.id)),
        reply_markup=admin_menu_kb(user.id),
        parse_mode=ParseMode.HTML,
    )


def admin_menu_text(chat_label: str = "") -> str:
    suffix = f"\n📍 المجموعة الحالية: <b>{chat_label}</b>" if chat_label else ""
    return (
        "👑 <b>لوحة الإدمن</b>\n━━━━━━━━━━━━━━━\n"
        f"كل الإجراءات تطبَّق على المجموعة التي فتحت فيها هذه القائمة.{suffix}\n\n"
        "اختر إجراء:"
    )


def admin_menu_kb(owner_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 إعطاء مال للاعب", callback_data=cb("a_money", owner_id))],
        [InlineKeyboardButton("🏗️ إعطاء مشروع للاعب", callback_data=cb("a_proj", owner_id))],
        [InlineKeyboardButton("🔫 إعطاء أسلحة لفريق لاعب", callback_data=cb("a_weap", owner_id))],
        [InlineKeyboardButton("🧹 تصفير (مال / مشاريع / جنود)", callback_data=cb("a_reset", owner_id))],
        [InlineKeyboardButton("📊 إحصائيات", callback_data=cb("a_stats", owner_id))],
        [InlineKeyboardButton("🎯 بدء مزاد فوري هنا", callback_data=cb("a_auction_now", owner_id))],
        [InlineKeyboardButton("📢 رسالة لكل المجموعات", callback_data=cb("a_broadcast", owner_id))],
        [InlineKeyboardButton("⬅️ القائمة الرئيسية", callback_data=cb("menu", owner_id))],
    ])


async def h_amenu(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    chat = query.message.chat
    label = chat.title or str(chat.id) if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP) else ""
    await safe_edit(query, admin_menu_text(label), reply_markup=admin_menu_kb(owner_id))


async def h_a_money(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    context.user_data[AWAIT_KEY] = "admin_money"
    text = (
        "💰 <b>إعطاء مال للاعب</b> <i>(في هذه المجموعة)</i>\n━━━━━━━━━━━━━━━\n"
        "أرسل الآن رسالة بصيغة:\n"
        "<code>USER_ID المبلغ</code>\n\n"
        "مثال: <code>12345678 5000</code>\n"
        "(استخدم رقم سالب للسحب)"
    )
    rows = [[InlineKeyboardButton("⬅️ رجوع", callback_data=cb("amenu", owner_id))]]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


async def h_a_proj(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    text = "🏗️ <b>اختر نوع المشروع لإعطائه:</b>\n━━━━━━━━━━━━━━━"
    rows = []
    for key, info in game.PROJECTS.items():
        rows.append([InlineKeyboardButton(
            f"{info['emoji']} {info['name']}",
            callback_data=cb("a_proj_pick", owner_id, key),
        )])
    rows.append([InlineKeyboardButton("⬅️ رجوع", callback_data=cb("amenu", owner_id))])
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


async def h_a_proj_pick(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    ptype = parts[2]
    if ptype not in game.PROJECTS:
        return
    info = game.PROJECTS[ptype]
    context.user_data[AWAIT_KEY] = "admin_proj"
    context.user_data[AWAIT_DATA_KEY] = ptype
    text = (
        f"🏗️ <b>إعطاء {info['emoji']} {info['name']}</b> <i>(في هذه المجموعة)</i>\n━━━━━━━━━━━━━━━\n"
        f"أرسل الآن:\n<code>USER_ID العدد</code>\n\n"
        f"مثال: <code>12345678 3</code>"
    )
    rows = [[InlineKeyboardButton("⬅️ رجوع", callback_data=cb("a_proj", owner_id))]]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


async def h_a_weap(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    text = "🔫 <b>اختر نوع السلاح لإعطائه:</b>\n━━━━━━━━━━━━━━━"
    rows = [
        [InlineKeyboardButton("💂 جنود", callback_data=cb("a_weap_pick", owner_id, "soldiers"))],
        [InlineKeyboardButton("🚀 صواريخ", callback_data=cb("a_weap_pick", owner_id, "missiles"))],
        [InlineKeyboardButton("🛡️ مضادات", callback_data=cb("a_weap_pick", owner_id, "antimissiles"))],
        [InlineKeyboardButton("⬅️ رجوع", callback_data=cb("amenu", owner_id))],
    ]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


async def h_a_weap_pick(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    field = parts[2]
    if field not in ("soldiers", "missiles", "antimissiles"):
        return
    label = {"soldiers": "💂 جنود", "missiles": "🚀 صواريخ", "antimissiles": "🛡️ مضادات"}[field]
    context.user_data[AWAIT_KEY] = "admin_weap"
    context.user_data[AWAIT_DATA_KEY] = field
    text = (
        f"🔫 <b>إعطاء {label}</b> <i>(في هذه المجموعة)</i>\n━━━━━━━━━━━━━━━\n"
        f"أرسل الآن:\n<code>USER_ID الكمية</code>\n\n"
        f"مثال: <code>12345678 50</code>\n"
        f"⚠️ يجب أن يكون اللاعب عضواً في فريق."
    )
    rows = [[InlineKeyboardButton("⬅️ رجوع", callback_data=cb("a_weap", owner_id))]]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


# ---------- ADMIN RESET ----------

async def h_a_reset(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    text = (
        "🧹 <b>تصفير</b> <i>(في هذه المجموعة)</i>\n━━━━━━━━━━━━━━━\n"
        "اختر ما تريد تصفيره:"
    )
    rows = [
        [InlineKeyboardButton("💰 تصفير المال", callback_data=cb("a_reset_money", owner_id))],
        [InlineKeyboardButton("🏗️ تصفير المشاريع", callback_data=cb("a_reset_proj", owner_id))],
        [InlineKeyboardButton("💂 تصفير الجنود", callback_data=cb("a_reset_sold", owner_id))],
        [InlineKeyboardButton("⬅️ رجوع", callback_data=cb("amenu", owner_id))],
    ]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


def _reset_kind_label(kind: str) -> str:
    return {"money": "💰 المال", "proj": "🏗️ المشاريع", "sold": "💂 الجنود"}[kind]


async def _reset_submenu(update, context, parts, kind: str):
    query = update.callback_query
    owner_id = int(parts[1])
    label = _reset_kind_label(kind)
    text = (
        f"🧹 <b>تصفير {label}</b> <i>(في هذه المجموعة)</i>\n━━━━━━━━━━━━━━━\n"
        "هل تريد تصفير لاعب واحد محدد، أم لكل أعضاء المجموعة؟"
    )
    rows = [
        [InlineKeyboardButton("👤 لاعب واحد (بالـ ID)", callback_data=cb(f"a_reset_{kind}_one", owner_id))],
        [InlineKeyboardButton("👥 كل أعضاء المجموعة", callback_data=cb(f"a_reset_{kind}_all_ask", owner_id))],
        [InlineKeyboardButton("⬅️ رجوع", callback_data=cb("a_reset", owner_id))],
    ]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


async def h_a_reset_money(update, context, parts):
    await _reset_submenu(update, context, parts, "money")


async def h_a_reset_proj(update, context, parts):
    await _reset_submenu(update, context, parts, "proj")


async def h_a_reset_sold(update, context, parts):
    await _reset_submenu(update, context, parts, "sold")


async def _reset_one_prompt(update, context, parts, kind: str):
    query = update.callback_query
    owner_id = int(parts[1])
    label = _reset_kind_label(kind)
    context.user_data[AWAIT_KEY] = f"admin_reset_{kind}_one"
    text = (
        f"🧹 <b>تصفير {label} لِلاعب واحد</b> <i>(في هذه المجموعة)</i>\n━━━━━━━━━━━━━━━\n"
        "أرسل الآن <code>USER_ID</code> فقط.\n\n"
        "مثال: <code>12345678</code>"
    )
    rows = [[InlineKeyboardButton("⬅️ رجوع", callback_data=cb(f"a_reset_{kind}", owner_id))]]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


async def h_a_reset_money_one(update, context, parts):
    await _reset_one_prompt(update, context, parts, "money")


async def h_a_reset_proj_one(update, context, parts):
    await _reset_one_prompt(update, context, parts, "proj")


async def h_a_reset_sold_one(update, context, parts):
    await _reset_one_prompt(update, context, parts, "sold")


async def _reset_all_ask(update, context, parts, kind: str):
    query = update.callback_query
    owner_id = int(parts[1])
    label = _reset_kind_label(kind)
    chat = query.message.chat
    chat_label = chat.title or str(chat.id)
    text = (
        f"⚠️ <b>تأكيد تصفير {label} لكل المجموعة</b>\n━━━━━━━━━━━━━━━\n"
        f"📍 المجموعة: <b>{chat_label}</b>\n\n"
        f"<b>هذا الإجراء نهائي ولا يمكن التراجع عنه.</b>\n"
        f"هل أنت متأكد؟"
    )
    rows = [
        [InlineKeyboardButton("⚠️ نعم، نفّذ التصفير", callback_data=cb(f"a_reset_{kind}_all_yes", owner_id))],
        [InlineKeyboardButton("❌ إلغاء", callback_data=cb(f"a_reset_{kind}", owner_id))],
    ]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


async def h_a_reset_money_all_ask(update, context, parts):
    await _reset_all_ask(update, context, parts, "money")


async def h_a_reset_proj_all_ask(update, context, parts):
    await _reset_all_ask(update, context, parts, "proj")


async def h_a_reset_sold_all_ask(update, context, parts):
    await _reset_all_ask(update, context, parts, "sold")


def _do_reset_all(kind: str, chat_id: int) -> int:
    if kind == "money":
        return db.reset_all_coins_in_chat(chat_id)
    if kind == "proj":
        return db.delete_all_projects_in_chat(chat_id)
    if kind == "sold":
        return db.reset_all_soldiers_in_chat(chat_id)
    return 0


async def _reset_all_yes(update, context, parts, kind: str):
    query = update.callback_query
    owner_id = int(parts[1])
    chat = query.message.chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await query.answer("يجب أن يُنفّذ هذا داخل المجموعة.", show_alert=True)
        return
    affected = _do_reset_all(kind, chat.id)
    label = _reset_kind_label(kind)
    text = (
        f"✅ <b>تم تصفير {label}</b>\n━━━━━━━━━━━━━━━\n"
        f"عدد العناصر المتأثرة: <b>{affected:,}</b>"
    )
    rows = [[InlineKeyboardButton("⬅️ رجوع للوحة الإدمن", callback_data=cb("amenu", owner_id))]]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


async def h_a_reset_money_all_yes(update, context, parts):
    await _reset_all_yes(update, context, parts, "money")


async def h_a_reset_proj_all_yes(update, context, parts):
    await _reset_all_yes(update, context, parts, "proj")


async def h_a_reset_sold_all_yes(update, context, parts):
    await _reset_all_yes(update, context, parts, "sold")


async def h_a_stats(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    chat = query.message.chat
    cid = chat.id if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP) else None
    g = db.admin_global_stats()
    text = (
        f"📊 <b>إحصائيات اللعبة</b>\n━━━━━━━━━━━━━━━\n"
        f"<b>عام (كل المجموعات):</b>\n"
        f"💬 المجموعات المسجّلة: <b>{g['chats']:,}</b>\n"
        f"👤 إجمالي السجلات (لاعب × مجموعة): <b>{g['users']:,}</b>\n"
        f"👤 لاعبون فريدون: <b>{g['unique_users']:,}</b>\n"
        f"💰 إجمالي العملات: <b>{g['total_coins']:,}</b>\n"
        f"🛡️ إجمالي الفرق: <b>{g['teams']:,}</b>\n"
        f"🏗️ إجمالي المشاريع: <b>{g['projects']:,}</b>\n"
        f"🎯 المزادات النشطة الآن: <b>{g['active_auctions']:,}</b>\n"
    )
    if cid is not None:
        c = db.admin_chat_stats(cid)
        chat_label = chat.title or str(cid)
        text += (
            f"\n<b>📍 المجموعة الحالية ({chat_label}):</b>\n"
            f"👤 لاعبون: <b>{c['users']:,}</b>\n"
            f"💰 عملات: <b>{c['total_coins']:,}</b>\n"
            f"🛡️ فرق: <b>{c['teams']:,}</b>\n"
            f"🏗️ مشاريع: <b>{c['projects']:,}</b>\n"
        )
    rows = [[InlineKeyboardButton("⬅️ رجوع", callback_data=cb("amenu", owner_id))]]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


async def h_a_auction_now(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    chat = query.message.chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await query.answer("يجب تنفيذ هذا الإجراء داخل مجموعة.", show_alert=True)
        return
    db.register_chat(chat.id, chat.title)
    try:
        await start_auction_in_chat(context, chat.id, force=True)
        await query.answer("✅ تم إطلاق المزاد!", show_alert=True)
    except Exception as e:
        log.exception("admin force-auction: %s", e)
        await query.answer(f"خطأ: {e}", show_alert=True)
    chat_label = chat.title or str(chat.id)
    await safe_edit(query, admin_menu_text(chat_label), reply_markup=admin_menu_kb(owner_id))


async def h_a_broadcast(update, context, parts):
    query = update.callback_query
    owner_id = int(parts[1])
    context.user_data[AWAIT_KEY] = "admin_broadcast"
    text = (
        "📢 <b>رسالة جماعية</b>\n━━━━━━━━━━━━━━━\n"
        "أرسل الآن نص الرسالة التي تريد بثّها لكل المجموعات المسجّلة."
    )
    rows = [[InlineKeyboardButton("⬅️ رجوع", callback_data=cb("amenu", owner_id))]]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))


# ============== TEXT INPUT ==============

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if user is None or update.message is None or chat is None:
        return

    awaiting = context.user_data.get(AWAIT_KEY)

    # Allow admin to send admin inputs in private; otherwise redirect private chats.
    if chat.type == ChatType.PRIVATE:
        is_admin_input = is_admin(user.id) and awaiting and awaiting.startswith("admin_")
        if not is_admin_input:
            await update.message.reply_text(PRIVATE_REDIRECT_TEXT, parse_mode=ParseMode.HTML)
            return

    if not awaiting:
        return

    if awaiting == "team_name":
        await handle_team_name_input(update, context)
        return

    # Admin inputs
    if not is_admin(user.id):
        return
    text = (update.message.text or "").strip()

    # Resolve admin's target chat: prefer stored, otherwise use current group
    target_chat_id = context.user_data.get(ADMIN_CHAT_KEY)
    if target_chat_id is None and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        target_chat_id = chat.id
    if target_chat_id is None:
        await update.message.reply_text(
            "⚠️ افتح /admin داخل المجموعة المراد إدارتها أولاً.",
        )
        return

    if awaiting == "admin_money":
        await handle_admin_money(update, context, text, target_chat_id)
    elif awaiting == "admin_proj":
        ptype = context.user_data.get(AWAIT_DATA_KEY)
        await handle_admin_proj(update, context, text, ptype, target_chat_id)
    elif awaiting == "admin_weap":
        field = context.user_data.get(AWAIT_DATA_KEY)
        await handle_admin_weap(update, context, text, field, target_chat_id)
    elif awaiting == "admin_broadcast":
        await handle_admin_broadcast(update, context, text)
    elif awaiting == "admin_reset_money_one":
        await handle_admin_reset_one(update, context, text, target_chat_id, "money")
    elif awaiting == "admin_reset_proj_one":
        await handle_admin_reset_one(update, context, text, target_chat_id, "proj")
    elif awaiting == "admin_reset_sold_one":
        await handle_admin_reset_one(update, context, text, target_chat_id, "sold")


async def handle_team_name_input(update, context):
    user = update.effective_user
    chat = update.effective_chat
    name = (update.message.text or "").strip()
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await update.message.reply_text("⚠️ أرسل اسم الفريق داخل المجموعة.")
        return
    expected_cid = context.user_data.get(AWAIT_DATA_KEY)
    if expected_cid and str(chat.id) != str(expected_cid):
        await update.message.reply_text(
            "⚠️ أرسل اسم الفريق في نفس المجموعة التي فتحت فيها القائمة."
        )
        return
    if not (3 <= len(name) <= 30):
        await update.message.reply_text("⚠️ اسم الفريق يجب أن يكون بين 3 و30 حرفاً.")
        return
    cid = chat.id
    db.get_or_create_user(user.id, cid, user.username, user.first_name)
    u = db.get_user(user.id, cid)
    if u and u["team_id"]:
        await update.message.reply_text("أنت بالفعل في فريق في هذه المجموعة.")
        context.user_data.pop(AWAIT_KEY, None)
        context.user_data.pop(AWAIT_DATA_KEY, None)
        return
    team_id = db.create_team(name, user.id, cid)
    if team_id is None:
        await update.message.reply_text("❌ هذا الاسم مستخدم في هذه المجموعة. اختر اسماً آخر.")
        return
    context.user_data.pop(AWAIT_KEY, None)
    context.user_data.pop(AWAIT_DATA_KEY, None)
    await update.message.reply_text(
        f"🎉 تم تأسيس فريق <b>{name}</b>! أنت القائد.\n"
        f"افتح <b>🛡️ فريقي</b> من القائمة لإدارة الفريق.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb(user.id),
    )


def _parse_two_ints(text: str):
    parts = text.replace(",", " ").split()
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _parse_one_int(text: str):
    parts = text.replace(",", " ").split()
    if not parts:
        return None
    try:
        return int(parts[0])
    except ValueError:
        return None


async def handle_admin_money(update, context, text, chat_id):
    pair = _parse_two_ints(text)
    if not pair:
        await update.message.reply_text(
            "⚠️ صيغة غير صحيحة. أرسل: <code>USER_ID المبلغ</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    target_id, amount = pair
    target = db.get_user(target_id, chat_id)
    if not target:
        db.get_or_create_user(target_id, chat_id, None, None)
        target = db.get_user(target_id, chat_id)
    db.add_coins(target_id, chat_id, amount)
    target = db.get_user(target_id, chat_id)
    await update.message.reply_text(
        f"✅ تم {('إضافة' if amount >= 0 else 'سحب')} <b>{abs(amount):,}</b> "
        f"إلى/من <b>{fmt_user(target)}</b> (<code>{target_id}</code>) "
        f"في المجموعة <code>{chat_id}</code>.\n"
        f"الرصيد الحالي: <b>{target['coins']:,}</b>",
        parse_mode=ParseMode.HTML,
    )
    context.user_data.pop(AWAIT_KEY, None)
    context.user_data.pop(AWAIT_DATA_KEY, None)


async def handle_admin_proj(update, context, text, ptype, chat_id):
    if not ptype or ptype not in game.PROJECTS:
        await update.message.reply_text("⚠️ نوع المشروع غير صالح. ابدأ من جديد.")
        context.user_data.pop(AWAIT_KEY, None)
        context.user_data.pop(AWAIT_DATA_KEY, None)
        return
    pair = _parse_two_ints(text)
    if not pair:
        await update.message.reply_text(
            "⚠️ صيغة غير صحيحة. أرسل: <code>USER_ID العدد</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    target_id, count = pair
    if count < 1 or count > 100:
        await update.message.reply_text("⚠️ العدد يجب أن يكون بين 1 و100.")
        return
    target = db.get_user(target_id, chat_id)
    if not target:
        db.get_or_create_user(target_id, chat_id, None, None)
        target = db.get_user(target_id, chat_id)
    db.add_projects_bulk(target_id, chat_id, ptype, count)
    info = game.PROJECTS[ptype]
    await update.message.reply_text(
        f"✅ تم منح {count} × {info['emoji']} {info['name']} "
        f"للاعب <b>{fmt_user(target)}</b> (<code>{target_id}</code>) "
        f"في المجموعة <code>{chat_id}</code>.",
        parse_mode=ParseMode.HTML,
    )
    context.user_data.pop(AWAIT_KEY, None)
    context.user_data.pop(AWAIT_DATA_KEY, None)


async def handle_admin_weap(update, context, text, field, chat_id):
    if field not in ("soldiers", "missiles", "antimissiles"):
        await update.message.reply_text("⚠️ نوع السلاح غير صالح. ابدأ من جديد.")
        context.user_data.pop(AWAIT_KEY, None)
        context.user_data.pop(AWAIT_DATA_KEY, None)
        return
    pair = _parse_two_ints(text)
    if not pair:
        await update.message.reply_text(
            "⚠️ صيغة غير صحيحة. أرسل: <code>USER_ID الكمية</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    target_id, qty = pair
    if qty == 0:
        await update.message.reply_text("⚠️ الكمية لا يمكن أن تكون صفراً.")
        return
    target = db.get_user(target_id, chat_id)
    if not target:
        await update.message.reply_text(
            "⚠️ هذا اللاعب لم يستخدم البوت في هذه المجموعة بعد."
        )
        return
    if not target["team_id"]:
        await update.message.reply_text(
            "⚠️ هذا اللاعب ليس في أي فريق. الأسلحة تذهب لخزنة الفريق."
        )
        return
    db.add_to_user_team_vault(target_id, chat_id, field, qty)
    label = {"soldiers": "جندي", "missiles": "صاروخ", "antimissiles": "مضاد"}[field]
    await update.message.reply_text(
        f"✅ تم إضافة <b>{qty:,}</b> {label} لخزنة فريق اللاعب <b>{fmt_user(target)}</b>.",
        parse_mode=ParseMode.HTML,
    )
    context.user_data.pop(AWAIT_KEY, None)
    context.user_data.pop(AWAIT_DATA_KEY, None)


async def handle_admin_reset_one(update, context, text, chat_id, kind):
    target_id = _parse_one_int(text)
    if not target_id:
        await update.message.reply_text(
            "⚠️ صيغة غير صحيحة. أرسل <code>USER_ID</code> فقط.",
            parse_mode=ParseMode.HTML,
        )
        return
    target = db.get_user(target_id, chat_id)
    if not target:
        await update.message.reply_text(
            f"⚠️ اللاعب <code>{target_id}</code> ليس له سجل في هذه المجموعة.",
            parse_mode=ParseMode.HTML,
        )
        context.user_data.pop(AWAIT_KEY, None)
        return

    if kind == "money":
        db.set_user_coins(target_id, chat_id, 0)
        msg = f"✅ تم تصفير مال <b>{fmt_user(target)}</b> (<code>{target_id}</code>) في هذه المجموعة."
    elif kind == "proj":
        n = db.delete_user_projects(target_id, chat_id)
        msg = f"✅ تم حذف <b>{n}</b> مشروع للاعب <b>{fmt_user(target)}</b>."
    elif kind == "sold":
        ok = db.reset_user_soldiers(target_id, chat_id)
        if ok:
            msg = f"✅ تم تصفير جنود فريق اللاعب <b>{fmt_user(target)}</b>."
        else:
            msg = f"⚠️ اللاعب ليس في أي فريق — لا يوجد جنود لتصفيرها."
    else:
        msg = "⚠️ نوع تصفير غير معروف."

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    context.user_data.pop(AWAIT_KEY, None)


async def handle_admin_broadcast(update, context, text):
    if not text:
        await update.message.reply_text("⚠️ النص فارغ.")
        return
    chats = db.list_chats()
    sent = 0
    failed = 0
    for ch in chats:
        try:
            await context.bot.send_message(
                ch["chat_id"],
                f"📢 <b>رسالة من الإدمن:</b>\n━━━━━━━━━━━━━━━\n{text}",
                parse_mode=ParseMode.HTML,
            )
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(
        f"✅ تم بثّ الرسالة. نجح: {sent}، فشل: {failed}."
    )
    context.user_data.pop(AWAIT_KEY, None)


# ============== AUCTION ==============

async def schedule_auction(context: ContextTypes.DEFAULT_TYPE):
    chats = db.list_chats()
    if not chats:
        log.info("auction tick: no chats registered yet")
        return
    for ch in chats:
        try:
            await start_auction_in_chat(context, ch["chat_id"])
        except Exception as e:
            log.warning("auction skip in %s: %s", ch["chat_id"], e)


async def start_auction_in_chat(context: ContextTypes.DEFAULT_TYPE, chat_id: int, force: bool = False):
    if not force:
        existing = db.get_active_auction_in_chat(chat_id)
        if existing:
            if existing["ends_at"] < int(time.time()):
                db.close_auction(existing["id"])
            else:
                return
    box = game.random_auction_box()
    ends_at = int(time.time()) + AUCTION_DURATION_SECONDS
    auction_id = db.create_auction(chat_id, box["key"], box["name"], ends_at)
    text = build_auction_text(auction_id, box["desc"])
    kb = build_auction_kb(auction_id)
    msg = await context.bot.send_message(
        chat_id, text, parse_mode=ParseMode.HTML, reply_markup=kb
    )
    db.set_auction_message(auction_id, msg.message_id)
    context.job_queue.run_once(
        finish_auction_job, AUCTION_DURATION_SECONDS,
        data={"auction_id": auction_id, "chat_id": chat_id},
        name=f"close_auction_{auction_id}",
    )
    log.info("started auction %s in chat %s (box=%s)", auction_id, chat_id, box["key"])


def get_box_desc(box_key: str) -> str:
    for b in game.AUCTION_BOXES:
        if b["key"] == box_key:
            return b["desc"]
    return ""


def build_auction_text(auction_id: int, desc: str = "") -> str:
    auc = db.get_auction(auction_id)
    if not auc:
        return "مزاد غير متاح."
    if not desc:
        desc = get_box_desc(auc["item_key"])
    bidder = auc["bidder_name"] or "—"
    remaining = max(0, auc["ends_at"] - int(time.time()))
    return (
        f"🎯 <b>مزاد سريع!</b>\n━━━━━━━━━━━━━━━\n"
        f"📦 <b>{auc['item_name']}</b>\n"
        f"<i>{desc}</i>\n\n"
        f"💵 المزايدة الحالية: <b>{auc['current_bid']:,}</b> عملة\n"
        f"🏆 المتصدّر: <b>{bidder}</b>\n"
        f"⏱️ ينتهي خلال: <b>{remaining}</b> ثانية\n\n"
        f"اضغط على زرّ لرفع المزايدة:"
    )


def build_auction_kb(auction_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("+100", callback_data=cb_free("bid", auction_id, 100)),
        InlineKeyboardButton("+500", callback_data=cb_free("bid", auction_id, 500)),
        InlineKeyboardButton("+1000", callback_data=cb_free("bid", auction_id, 1000)),
    ]])


async def h_bid(update, context, parts):
    query = update.callback_query
    user = query.from_user
    chat = query.message.chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await query.answer("المزاد متاح في المجموعة فقط.", show_alert=True)
        return
    cid = chat.id
    db.get_or_create_user(user.id, cid, user.username, user.first_name)
    auction_id = int(parts[1])
    increment = int(parts[2])
    name = user.first_name or user.username or str(user.id)
    result = db.place_bid(auction_id, user.id, cid, name, increment)
    if result is None:
        u = db.get_user(user.id, cid)
        bal = u["coins"] if u else 0
        await query.answer(
            f"❌ لم تتم المزايدة. (رصيد: {bal:,})",
            show_alert=True,
        )
        return
    await query.answer(f"✅ مزايدتك الآن {result['current_bid']:,}")
    try:
        await query.edit_message_text(
            build_auction_text(auction_id),
            parse_mode=ParseMode.HTML,
            reply_markup=build_auction_kb(auction_id),
        )
    except BadRequest:
        pass


async def finish_auction_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    auction_id = data["auction_id"]
    chat_id = data["chat_id"]
    auc = db.close_auction(auction_id)
    if not auc:
        return
    if not auc["current_bidder"]:
        text = (
            f"📦 <b>انتهى المزاد بدون فائز</b>\n"
            f"العنصر: {auc['item_name']}"
        )
        try:
            await context.bot.edit_message_text(
                text, chat_id=chat_id, message_id=auc["message_id"],
                parse_mode=ParseMode.HTML,
            )
        except BadRequest:
            await context.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML)
        return

    reward = game.generate_reward(auc["item_key"])
    winner_id = auc["current_bidder"]
    winner = db.get_user(winner_id, chat_id)
    reward_text_parts = []

    if reward["type"] == "coins":
        db.add_coins(winner_id, chat_id, reward["qty"])
        reward_text_parts.append(reward["label"])
    else:
        grants = game.apply_reward_grants(reward)
        if winner and winner["team_id"]:
            for vault_field, qty in grants:
                db.add_to_vault(winner["team_id"], vault_field, qty)
            reward_text_parts.append(reward["label"])
            reward_text_parts.append("✅ <i>أُودعت في خزنة الفريق</i>")
        else:
            comp_total = 0
            cost_map = {"soldiers": 100, "missiles": 500, "antimissiles": 400}
            for vault_field, qty in grants:
                comp_total += cost_map.get(vault_field, 100) * qty
            db.add_coins(winner_id, chat_id, comp_total)
            reward_text_parts.append(reward["label"])
            reward_text_parts.append(
                f"💡 <i>لا تنتمي لفريق، تم تعويضك بـ {comp_total:,} عملة بدلاً من المعدات</i>"
            )

    reward_label = "\n".join(reward_text_parts)
    text = (
        f"🏆 <b>انتهى المزاد!</b>\n━━━━━━━━━━━━━━━\n"
        f"📦 <b>{auc['item_name']}</b>\n"
        f"👑 الفائز: <b>{auc['bidder_name']}</b>\n"
        f"💵 السعر النهائي: <b>{auc['current_bid']:,}</b>\n\n"
        f"🎁 <b>محتويات الصندوق:</b>\n{reward_label}"
    )
    try:
        await context.bot.edit_message_text(
            text, chat_id=chat_id, message_id=auc["message_id"],
            parse_mode=ParseMode.HTML,
        )
    except BadRequest:
        await context.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML)


# ============== INCOME PAYOUT JOB ==============

async def income_payout_job(context: ContextTypes.DEFAULT_TYPE):
    """Every TICK_SECONDS: pay each project's effective income (after damage, with level)."""
    projs = db.get_all_projects()
    by_user = {}
    now = int(time.time())
    for p in projs:
        info = game.PROJECTS.get(p["ptype"])
        if not info:
            continue
        ticks = (now - p["last_payout_at"]) // TICK_SECONDS
        if ticks <= 0:
            continue
        level = p["level"] if "level" in p.keys() else 0
        base = info["income_per_tick"] * game.level_income_multiplier(level)
        eff = int(base * (100 - p["damage"]) / 100)
        gain = ticks * eff
        if gain > 0:
            key = (p["owner_id"], p["chat_id"])
            by_user[key] = by_user.get(key, 0) + gain
        new_ts = p["last_payout_at"] + ticks * TICK_SECONDS
        db.update_project_payout(p["id"], new_ts)
    for (uid, cid), amount in by_user.items():
        db.add_coins(uid, cid, amount)


# ============== ROUTES ==============

ROUTES = {
    "menu": h_menu,
    "profile": h_profile,
    "projects": h_projects,
    "buildmenu": h_buildmenu,
    "build_qty": h_build_qty,
    "build": h_build,
    "collect": h_collect,
    "team": h_team,
    "team_create": h_team_create,
    "team_cancel": h_team_cancel,
    "team_browse": h_team_browse,
    "team_join": h_team_join,
    "team_toggle": h_team_toggle,
    "team_members": h_team_members,
    "team_kick": h_team_kick,
    "team_kick_do": h_team_kick_do,
    "team_leave": h_team_leave,
    "team_requests": h_team_requests,
    "team_disband": h_team_disband,
    "team_disband_yes": h_team_disband_yes,
    "upgrade": h_upgrade,
    "upgrade_do": h_upgrade_do,
    "req": h_request,
    "attack_menu": h_attack_menu,
    "attack_do": h_attack_do,
    "shop": h_shop,
    "shop_item": h_shop_item,
    "shop_buy": h_shop_buy,
    "bid": h_bid,
    "lb": h_lb,
    "lb_players": h_lb_players,
    "lb_power": h_lb_power,
    "lb_wealth": h_lb_wealth,
    "help": h_help,
    "amenu": h_amenu,
    "a_money": h_a_money,
    "a_proj": h_a_proj,
    "a_proj_pick": h_a_proj_pick,
    "a_weap": h_a_weap,
    "a_weap_pick": h_a_weap_pick,
    "a_stats": h_a_stats,
    "a_auction_now": h_a_auction_now,
    "a_broadcast": h_a_broadcast,
    "a_reset": h_a_reset,
    "a_reset_money": h_a_reset_money,
    "a_reset_proj": h_a_reset_proj,
    "a_reset_sold": h_a_reset_sold,
    "a_reset_money_one": h_a_reset_money_one,
    "a_reset_proj_one": h_a_reset_proj_one,
    "a_reset_sold_one": h_a_reset_sold_one,
    "a_reset_money_all_ask": h_a_reset_money_all_ask,
    "a_reset_proj_all_ask": h_a_reset_proj_all_ask,
    "a_reset_sold_all_ask": h_a_reset_sold_all_ask,
    "a_reset_money_all_yes": h_a_reset_money_all_yes,
    "a_reset_proj_all_yes": h_a_reset_proj_all_yes,
    "a_reset_sold_all_yes": h_a_reset_sold_all_yes,
}


# ============== APP BOOTSTRAP ==============

async def post_init(app: Application):
    cleared = db.cleanup_stale_auctions()
    if cleared:
        log.info("cleared %d stale active auctions on startup", cleared)
    app.job_queue.run_repeating(
        schedule_auction,
        interval=AUCTION_INTERVAL_MINUTES * 60,
        first=15,
        name="auction_tick",
    )
    app.job_queue.run_repeating(
        income_payout_job,
        interval=TICK_SECONDS,
        first=TICK_SECONDS,
        name="income_payout",
    )
    log.info(
        "Scheduled jobs: income tick=%ss, auction every %sm.",
        TICK_SECONDS, AUCTION_INTERVAL_MINUTES,
    )


def main():
    db.init_db()
    application = Application.builder().token(TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("admin", cmd_admin))
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    log.info("Bot starting (long polling)...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
