import asyncio
import bisect
import functools
import json
import os
import random
import re
import time
from collections import deque
from datetime import datetime
from urllib.parse import quote, unquote

import libsql
import aiohttp
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest, TelegramForbiddenError
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message, CallbackQuery, ErrorEvent, InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery,
)
from aiohttp import web

def _load_dotenv_if_present():
    for path in ("/home/container/.env", os.path.join(os.path.dirname(__file__), ".env")):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    os.environ.setdefault(key, value)
        except Exception as e:
            print(f".env не удалось прочитать ({path}): {e}")
        break

_load_dotenv_if_present()

TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_USERNAME = "MaksGeometryGd"
ADMIN_USER_ID = 7148430462
TURSO_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")

# --- Обязательная подписка на канал (проверяется на !ферма, эволюция, перерождение) ---
REQUIRED_CHANNEL_USERNAME = "mggnoganews"          # без @ и без ссылки
REQUIRED_CHANNEL_URL = "https://t.me/mggnoganews"
REQUIRED_CHANNEL_CHAT_ID = f"@{REQUIRED_CHANNEL_USERNAME}"
SUBSCRIPTION_CHECK_CACHE_TTL = 300  # сек, чтобы не долбить Telegram API на каждый фарм
_subscription_cache: dict[int, tuple[bool, float]] = {}

PREMIUM_MIKU = '<tg-emoji emoji-id="5199793038410391513">🤩</tg-emoji>'
PREMIUM_MGG = '<tg-emoji emoji-id="6327920744789444368">🥰</tg-emoji>'

PREMIUM_BADGE_EVO = '<tg-emoji emoji-id="5370704514561093615">🏅</tg-emoji>'
PREMIUM_BADGE_CASE = '<tg-emoji emoji-id="5328257610472775810">🎖️</tg-emoji>'
PREMIUM_BADGE_FARM = '<tg-emoji emoji-id="5415966542078683753">🥇</tg-emoji>'
PREMIUM_BADGE_EVO5 = '<tg-emoji emoji-id="5372812377135789260">👑</tg-emoji>'

# ==== Бейджи за уровень эволюции (10/25/50/100/250/500/1000/5000/10000) ====
# emoji-id пустые — вставь свои готовые id, fallback-эмодзи уже расставлены по смыслу названия.
PREMIUM_BADGE_EVO10 = '<tg-emoji emoji-id="6019118557621653717">🔰</tg-emoji>'
PREMIUM_BADGE_EVO25 = '<tg-emoji emoji-id="6021737443995160656">🥈</tg-emoji>'
PREMIUM_BADGE_EVO50 = '<tg-emoji emoji-id="6021831143001689820">🥋</tg-emoji>'
PREMIUM_BADGE_EVO100 = '<tg-emoji emoji-id="5462948145652594708">🏆</tg-emoji>'
PREMIUM_BADGE_EVO250 = '<tg-emoji emoji-id="6008035368744521190">👑</tg-emoji>'
PREMIUM_BADGE_EVO500 = '<tg-emoji emoji-id="5802946896494334636">☄️</tg-emoji>'
PREMIUM_BADGE_EVO1000 = '<tg-emoji emoji-id="5206263763124117710">🌌</tg-emoji>'
PREMIUM_BADGE_EVO5000 = '<tg-emoji emoji-id="5787496116719195306">🔱</tg-emoji>'
PREMIUM_BADGE_EVO10000 = '<tg-emoji emoji-id="5267389029011182710">🛡️</tg-emoji>'
PREMIUM_BADGE_EVO50000 = '<tg-emoji emoji-id="5888974760720732797">💥</tg-emoji>'
PREMIUM_BADGE_EVO100000 = '<tg-emoji emoji-id="6325484162597784431">📜</tg-emoji>'
PREMIUM_BADGE_EVO1000000 = '<tg-emoji emoji-id="5431805131630852717">🌟</tg-emoji>'

# ==== Бейджи за открытые кейсы (50/500/5000) ====
PREMIUM_BADGE_CASE50 = '<tg-emoji emoji-id="5235695112419303615">🎁</tg-emoji>'
PREMIUM_BADGE_CASE500 = '<tg-emoji emoji-id="5188400169506334671">🎰</tg-emoji>'
PREMIUM_BADGE_CASE5000 = '<tg-emoji emoji-id="5460938959951513194">💣</tg-emoji>'

# ==== Бейджи за суммарно нафармленные очки ноги ====
PREMIUM_BADGE_FARM1M = '<tg-emoji emoji-id="5463270938214678914">🌱</tg-emoji>'
PREMIUM_BADGE_FARM500M = '<tg-emoji emoji-id="5174879174371837069">🚀</tg-emoji>'
PREMIUM_BADGE_FARM5B = '<tg-emoji emoji-id="5431610634036845778">⚙️</tg-emoji>'
PREMIUM_BADGE_FARM1T = '<tg-emoji emoji-id="5388722374814214652">⚡️</tg-emoji>'
PREMIUM_BADGE_FARM1Q = '<tg-emoji emoji-id="5298816567436400568">🌌</tg-emoji>'
PREMIUM_BADGE_FARM1QI = '<tg-emoji emoji-id="5418296093685342477">🦵</tg-emoji>'

# ==== Бейджи за баланс монет ====
PREMIUM_BADGE_COIN1K = '<tg-emoji emoji-id="5449418135381759397">🪙</tg-emoji>'
PREMIUM_BADGE_COIN10K = '<tg-emoji emoji-id="5190526908462292507">💰</tg-emoji>'
PREMIUM_BADGE_COIN100K = '<tg-emoji emoji-id="5431389597839937743">💵</tg-emoji>'
PREMIUM_BADGE_COIN10M = '<tg-emoji emoji-id="5415594207068822547">🏦</tg-emoji>'
PREMIUM_BADGE_COIN1B = '<tg-emoji emoji-id="5285087180488726417">👑</tg-emoji>'
PREMIUM_BADGE_COIN10B = '<tg-emoji emoji-id="5323396295904209738">🏛️</tg-emoji>'

# ==== Бейджи за баланс очков перерождения ====
PREMIUM_BADGE_REBIRTH100 = '<tg-emoji emoji-id="6032728694802354547">🕯️</tg-emoji>'
PREMIUM_BADGE_REBIRTH10K = '<tg-emoji emoji-id="6265068953588994740">✨</tg-emoji>'
PREMIUM_BADGE_REBIRTH1M = '<tg-emoji emoji-id="5337128947027036693">🌠</tg-emoji>'
PREMIUM_BADGE_REBIRTH1B = '<tg-emoji emoji-id="5228699714500710949">👁️</tg-emoji>'
PREMIUM_BADGE_REBIRTH10B = '<tg-emoji emoji-id="5242433645523775166">♾️</tg-emoji>'

# ==== Бейдж за ультра-перерождение ====
PREMIUM_BADGE_ULTRA_REBIRTH = '<tg-emoji emoji-id="5447546448763699600">🔥</tg-emoji>'

# ==== Бейджи за стрик ежедневного бонуса ====
PREMIUM_BADGE_STREAK7 = '<tg-emoji emoji-id="5314665117017718786">📅</tg-emoji>'
PREMIUM_BADGE_STREAK30 = '<tg-emoji emoji-id="5274013522144016987">🗓️</tg-emoji>'

# ==== Бейджи за количество крафтов ====
PREMIUM_BADGE_CRAFT10 = '<tg-emoji emoji-id="5231151548121244459">🔨</tg-emoji>'
PREMIUM_BADGE_CRAFT100 = '<tg-emoji emoji-id="5354931010943347669">⚒️</tg-emoji>'

# ==== Бейджи за очки престижа ====
PREMIUM_BADGE_PRESTIGE10 = '<tg-emoji emoji-id="5049027699067062001">🎭</tg-emoji>'
PREMIUM_BADGE_PRESTIGE100 = '<tg-emoji emoji-id="5406980362393902143">🧘</tg-emoji>'
PREMIUM_BADGE_PRESTIGE25000 = '<tg-emoji emoji-id="5386617411342449059">📿</tg-emoji>'
PREMIUM_BADGE_PRESTIGE50000 = '<tg-emoji emoji-id="5388706032463671610">🕊️</tg-emoji>'
PREMIUM_BADGE_PRESTIGE100000 = '<tg-emoji emoji-id="6251413878165472946">👁️</tg-emoji>'
PREMIUM_BADGE_PRESTIGE250000 = '<tg-emoji emoji-id="5460788837959623745">🌀</tg-emoji>'
PREMIUM_BADGE_PRESTIGE500000 = '<tg-emoji emoji-id="5330274071848438189">🧠</tg-emoji>'
PREMIUM_BADGE_PRESTIGE1000000 = '<tg-emoji emoji-id="5192703340189871377">♾️</tg-emoji>'

PREMIUM_DAILY_CHARM = '<tg-emoji emoji-id="5233570349148311519">🧿</tg-emoji>'
# Простые emoji (без custom tg-emoji-id) — награда за ?бонус для ютубер/тиктокер команд.
PREMIUM_YOUTUBE_BUTTON = '💎'
PREMIUM_TIKTOK_LEGEND = '🏆'

PREMIUM_MK_MGG = '<tg-emoji emoji-id="5420141555233071341">🧿</tg-emoji>'
PREMIUM_MK_SANDSMOON = '<tg-emoji emoji-id="5197260300490907908">🌙</tg-emoji>'
PREMIUM_MK_FIXSAHAL1 = '<tg-emoji emoji-id="6325473957755488220">🔧</tg-emoji>'
PREMIUM_MK_MK = '<tg-emoji emoji-id="5776399733702528178">🪝</tg-emoji>'
PREMIUM_MK_PANTHER = '<tg-emoji emoji-id="5393538390362705684">⚡️</tg-emoji>'
PREMIUM_MK_VECTOR = '<tg-emoji emoji-id="6206233738494347353">↗️</tg-emoji>'
PREMIUM_MK_BROKEN = '<tg-emoji emoji-id="5208923808169222461">💔</tg-emoji>'

PREMIUM_OWNER_BADGE = '<tg-emoji emoji-id="5204056085509477484">💠</tg-emoji>'
PREMIUM_VIP_BADGE = '<tg-emoji emoji-id="5233333941263437275">💎</tg-emoji>'
PREMIUM_VIP_ITEM = '<tg-emoji emoji-id="5344025423258864934">🎗️</tg-emoji>'

# ==== Составные значки титулов — каждый титул из нескольких частей prem-emoji подряд ====
TITLE_EMOJI_PARTS = {
    "player": [
        '<tg-emoji emoji-id="5269360036747978766">🎮</tg-emoji>',
        '<tg-emoji emoji-id="5269735399709777697">👤</tg-emoji>',
    ],
    "admin": [
        '<tg-emoji emoji-id="5269679247307350615">👑</tg-emoji>',
        '<tg-emoji emoji-id="5269665108275013658">⚡</tg-emoji>',
    ],
    "moderator": [
        '<tg-emoji emoji-id="5269655289979774850">🔶</tg-emoji>',
        '<tg-emoji emoji-id="5271729342571914132">🛡️</tg-emoji>',
        '<tg-emoji emoji-id="5269674084756661883">⚙️</tg-emoji>',
    ],
    "vip": [
        '<tg-emoji emoji-id="5269643272661281263">💎</tg-emoji>',
        '<tg-emoji emoji-id="5269239665994541541">👑</tg-emoji>',
    ],
    "premium": [
        '<tg-emoji emoji-id="5269663940043907620">✨</tg-emoji>',
        '<tg-emoji emoji-id="5269654675799450919">🌟</tg-emoji>',
        '<tg-emoji emoji-id="5269504386303828342">💫</tg-emoji>',
    ],
    "developer": [
        '<tg-emoji emoji-id="5269421351701092924">🛠️</tg-emoji>',
        '<tg-emoji emoji-id="5269551527864869857">👨‍💻</tg-emoji>',
        '<tg-emoji emoji-id="5269417305841903768">⚡</tg-emoji>',
        '<tg-emoji emoji-id="5269542809081258001">🔧</tg-emoji>',
    ],
    "tiktoker": [
        '<tg-emoji emoji-id="5269309596652053580">🎵</tg-emoji>',
        '<tg-emoji emoji-id="5269571366318813700">🎬</tg-emoji>',
        '<tg-emoji emoji-id="5269648692910010278">📱</tg-emoji>',
    ],
    "youtuber": [
        '<tg-emoji emoji-id="5269329911847365713">▶️</tg-emoji>',
        '<tg-emoji emoji-id="5269216271307682935">🎥</tg-emoji>',
        '<tg-emoji emoji-id="5269432741954367180">🔴</tg-emoji>',
    ],
}

def title_emoji_badge(title: str) -> str:
    """Собирает составной значок титула из нескольких prem-emoji частей подряд (см.
    TITLE_EMOJI_PARTS) — например Модератор состоит из 3 частей, Разработчик из 4."""
    parts = TITLE_EMOJI_PARTS.get(title)
    return "".join(parts) if parts else ""

PREMIUM_MK_MARY = '<tg-emoji emoji-id="6328022870521808963">🌹</tg-emoji>'
PREMIUM_MK_VERON03 = '<tg-emoji emoji-id="5429446558930182229">🔷</tg-emoji>'
PREMIUM_STRANGE_COIN = '<tg-emoji emoji-id="5035428694441592026">🪙</tg-emoji>'

PREMIUM_POWER_AMULET = '<tg-emoji emoji-id="5364047860713143546">💪</tg-emoji>'
PREMIUM_GALAXY_POWER_AMULET = '<tg-emoji emoji-id="5451648825431175858">🌠</tg-emoji>'
PREMIUM_GALAXY_MIGHT_AMULET = '<tg-emoji emoji-id="5335070858828344908">🌋</tg-emoji>'
PREMIUM_HYBRID_AMULET = '<tg-emoji emoji-id="5204242195032336769">🧬</tg-emoji>'
PREMIUM_FRIENDSHIP_ESSENCE = '<tg-emoji emoji-id="5843554051341422500">🤝</tg-emoji>'
PREMIUM_TIME_PARTICLE = '<tg-emoji emoji-id="5363857580777029543">⏳</tg-emoji>'
PREMIUM_GOD_ESSENCE = '<tg-emoji emoji-id="5242602154270667208">👁️</tg-emoji>'
PREMIUM_DEVOTION_COIN = '<tg-emoji emoji-id="5416007206829047767">🟡</tg-emoji>'
PREMIUM_OLD_VASE = '<tg-emoji emoji-id="6334461494649948210">🏺</tg-emoji>'
PREMIUM_GOLDEN_VASE = '<tg-emoji emoji-id="5954115825324527429">⚱️</tg-emoji>'
PREMIUM_GODLY_VASE = '<tg-emoji emoji-id="5242521945756413456">🏆</tg-emoji>'
PREMIUM_LUCKY_CHARM = '<tg-emoji emoji-id="5435935451355555165">🍀</tg-emoji>'
PREMIUM_SWIFT_PILL = '<tg-emoji emoji-id="5886217713839246898">⚡</tg-emoji>'
PREMIUM_PARTY_SET = '<tg-emoji emoji-id="5852607601883221665">🎉</tg-emoji>'
PREMIUM_WARM_CANDLE = '<tg-emoji emoji-id="5253717838870363235">🕯</tg-emoji>'
PREMIUM_KOSHKO_AMULET = '<tg-emoji emoji-id="5371041424680710006">🐈</tg-emoji>'

PREMIUM_CRAFT_POINT = '<tg-emoji emoji-id="5254028100979787948">💠</tg-emoji>'

PREMIUM_KOTYARA_AMULET = '<tg-emoji emoji-id="5415692772273312091">🐱</tg-emoji>'
PREMIUM_MIKU_AMULET = '<tg-emoji emoji-id="5397821533613735774">🎤</tg-emoji>'
PREMIUM_GOLDA_ITEM = '<tg-emoji emoji-id="5330230039843709983">🥇</tg-emoji>'
PREMIUM_KARAMBIT_GOLD = '<tg-emoji emoji-id="5060114895148680390">🔪</tg-emoji>'
PREMIUM_BUTTERFLY_LEGACY = '<tg-emoji emoji-id="4943160586331490355">🦋</tg-emoji>'

PREMIUM_KREST_AMULET = '<tg-emoji emoji-id="5282820155015971423">✝️</tg-emoji>'
PREMIUM_FATI_AMULET = '<tg-emoji emoji-id="5404393696865041225">🤲</tg-emoji>'
PREMIUM_GUITARIST_CROWN = '<tg-emoji emoji-id="5445191681404057893">👑</tg-emoji>'
PREMIUM_VILON_AMULET = '<tg-emoji emoji-id="5386386711469117619">🔱</tg-emoji>'
PREMIUM_MIKU_RING = '<tg-emoji emoji-id="5292079619174852549">💍</tg-emoji>'
PREMIUM_MIKU_FAN_AMULET = '<tg-emoji emoji-id="5199714801286132798">🎧</tg-emoji>'

PREMIUM_BADGE_TESTER = '<tg-emoji emoji-id="5217791863368470760">🥰</tg-emoji>'
PREMIUM_BADGE_SUPPORT = '<tg-emoji emoji-id="5947343263194157527">🛠️</tg-emoji>'
PREMIUM_BADGE_POWER = '<tg-emoji emoji-id="5780703608760700844">💪</tg-emoji>'
PREMIUM_BADGE_TOP1_PAST = '<tg-emoji emoji-id="5363999757079429238">👑</tg-emoji>'

PREMIUM_CHAOS_ORB = '<tg-emoji emoji-id="5201679280672616755">🌀</tg-emoji>'
PREMIUM_CHRONOS_CLOCK = '<tg-emoji emoji-id="5237697056805510735">⏰</tg-emoji>'
PREMIUM_CHRONOS_ORB = '<tg-emoji emoji-id="5305669252181672918">🔮</tg-emoji>'
PREMIUM_BADGE_CHAOS_MASTER = '<tg-emoji emoji-id="5237888066886064441">⚡️</tg-emoji>'

PREMIUM_NOGOST_COIN = '<tg-emoji emoji-id="5413879072008724252">🪙</tg-emoji>'
PREMIUM_GODLY_NOGOST_COIN = '<tg-emoji emoji-id="5361563655924110883">🪙</tg-emoji>'
PREMIUM_CRAFT_COIN = '<tg-emoji emoji-id="5334956805971792834">🪙</tg-emoji>'
PREMIUM_BITCOIN = '<tg-emoji emoji-id="5474537505015486009">🪙</tg-emoji>'
PREMIUM_REBIRTH_COIN = '<tg-emoji emoji-id="6032751750186799376">🪙</tg-emoji>'
PREMIUM_EVOLUTION_COIN = '<tg-emoji emoji-id="5366230850855777158">🪙</tg-emoji>'
PREMIUM_AWAKENING_COIN = '<tg-emoji emoji-id="5767231090922101971">🪙</tg-emoji>'
PREMIUM_BADGE_INVESTOR = '<tg-emoji emoji-id="5298614648138919107">💹</tg-emoji>'

# ==== Эво-апгрейд: премиум-эмодзи для ожерелий/карманной звезды/искры (вставь свои emoji-id) ====
PREMIUM_REBIRTH_SPARK = '<tg-emoji emoji-id="5467837274429335080">✨</tg-emoji>'
PREMIUM_STAR_NECKLACE = '<tg-emoji emoji-id="5415853988165734070">📿</tg-emoji>'
PREMIUM_BLAZING_STAR_NECKLACE = '<tg-emoji emoji-id="5938541999031325561">📿</tg-emoji>'
PREMIUM_POCKET_STAR = '<tg-emoji emoji-id="5435957248314579621">🌠</tg-emoji>'

# ==== Крафт 3 ур.: Любитель Мастерства + его дроп-предмет nano-IT (вставь свои emoji-id) ====
PREMIUM_MASTERY_LOVER_AMULET = '<tg-emoji emoji-id="5936158605714661655">🤖</tg-emoji>'
PREMIUM_NANO_IT = '<tg-emoji emoji-id="5452097366045783407">🔩</tg-emoji>'

PREMIUM_ICE_SHARD = '<tg-emoji emoji-id="5363812028353898315">🧊</tg-emoji>'
PREMIUM_EMBER = '<tg-emoji emoji-id="5773638078321135255">🔥</tg-emoji>'
PREMIUM_DRAGON_CLAW = '<tg-emoji emoji-id="5307771389564954063">🐉</tg-emoji>'
PREMIUM_PARADOX_CHARM = '<tg-emoji emoji-id="5467522315887594988">🧿</tg-emoji>'
PREMIUM_SHADOW_MASK = '<tg-emoji emoji-id="5463247917189977301">🕶️</tg-emoji>'
PREMIUM_TIDE_WAVE = '<tg-emoji emoji-id="5994370062708904465">🌊</tg-emoji>'
PREMIUM_WARRIOR_SKULL = '<tg-emoji emoji-id="5231105033625423869">💀</tg-emoji>'
PREMIUM_BROKEN_CLOCK = '<tg-emoji emoji-id="5431903044000306112">🕰️</tg-emoji>'
PREMIUM_ESSENCE_DROP = '<tg-emoji emoji-id="5260717261173304462">🩸</tg-emoji>'
PREMIUM_COMET_SHARD = '<tg-emoji emoji-id="5294390831271129091">🌠</tg-emoji>'
PREMIUM_ANCIENT_STONE = '<tg-emoji emoji-id="5224412151728328775">🪨</tg-emoji>'
PREMIUM_FATE_THREAD = '<tg-emoji emoji-id="5366343945934624965">🧵</tg-emoji>'
PREMIUM_KOSHKO_GIFT = '<tg-emoji emoji-id="6217230280701251264">🎀</tg-emoji>'

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

REGULAR_THRESHOLDS = [10, 50, 150, 300, 500, 800, 1200, 1600, 2000, 2400,
                       3000, 3600, 4200, 4800, 5400, 6000, 6600, 7200, 7800, 8400]

CUSTOM_LEVELS = [
    (9000,  "🦵🍀", "нога удачи"),
    (9600,  "🦵🌬️", "нога воздухана"),
    (10200, "🦵🌔", "нога SandsMoon"),
    (10800, "🦵🍗", "гигантская нога"),
    (11400, "🦵✨", "блестящая нога"),
    (12000, "🦵🥉", "бронзовая нога"),
    (12600, "🦵🥈", "серебряная нога"),
    (13200, "🦵🏆", "золотая нога"),
    (13800, "🦵💎", "алмазная нога"),
    (14400, "🦵💀", "нога смерти"),
    (15000, "🦵😎", "нога Fixsahal1"),
    (15600, "🦵👼", "нога ангела"),
    (16200, "🦵🐺", "нога Волка"),
    (16800, PREMIUM_MIKU, "нога Мику"),
    (17400, "🦵🏇", "нога героя"),
    (18000, "🦵👁", "нога полу-бога"),
    (18600, "🦵🌌", "космическая нога"),
    (19200, "🦵🧿", "нога бога"),
    (19800, PREMIUM_MGG, "нога MGG"),
]

ALL_THRESHOLDS = REGULAR_THRESHOLDS + [t for t, _, _ in CUSTOM_LEVELS]
MAX_LEVEL_SCORE = ALL_THRESHOLDS[-1]

EXTRA_TIERS = [
    (40, 42, "🦵☄️", "нога Метеорита"),
    (43, 45, "🦵🌠✨", "нога Кометы"),
    (46, 48, "🦵🪐", "нога Планеты"),
    (49, 50, "🦵🪐💍", "нога Сатурна"),
    (51, 53, "🦵⚡🔥", "нога Плазмы"),
    (54, 55, "🦵🔥🌊", "нога Солнечной вспышки"),
    (56, 58, "🦵📡✨", "нога Пульсара"),
    (59, 60, "🦵📡💫", "нога Магнетара"),
    (61, 65, "🦵🌠", "нога Квазара"),
    (66, 70, "🦵🌠🌠", "нога Блазара"),
    (71, 75, "🦵🌑🕳️", "нога Тёмной Материи"),
    (76, 80, "🦵🌑⚡", "нога Тёмной Энергии"),
    (81, 90, "🦵⚫🕳️", "нога Чёрной дыры"),
    (91, 100, "🦵⚫🌀", "нога Сверхмассивной чёрной дыры"),
    (101, 112, "🦵🌌", "нога галактики"),
    (113, 125, "🦵🌌✨", "нога Млечного Пути"),
    (126, 138, "🦵🌠🌌", "нога вселенной"),
    (139, 150, "🦵🌠🌌🔭", "нога Наблюдаемой вселенной"),
    (151, 175, "🦵🌀🌌", "нога Мультивселенной"),
    (176, 200, "🦵⚛️🌀", "нога Сингулярности"),
    (201, 250, "🦵⚛️💥", "нога Большого Взрыва"),
    (251, 300, "🦵🌀🌌♾️", "нога Метавселенной"),
    (301, 400, "🦵☢️⚛️", "нога Антиматерии"),
    (401, 500, "🦵☢️🌀", "нога Аннигиляции"),
    (501, 750, "🦵⬛🌌", "нога пустоты"),
    (751, 1000, "🦵⬛♾️", "нога Абсолютной пустоты"),
    (1001, 1250, "🦵♾️🌀", "нога Парадокса"),
    (1251, 1500, "🦵♾️🔁", "нога Временной петли"),
    (1501, 1750, "🦵🟩💻", "нога Матрицы"),
    (1751, 2000, "🦵🟩🧠", "нога Симуляции"),
    (2001, 2500, "🦵🔷🔁", "нога Фрактала"),
    (2501, 3000, "🦵🔷♾️", "нога Бесконечного Фрактала"),
    (3001, 4000, "🦵🌀⏳🕳️", "нога Разрыва пространственно-временного континуума"),
    (4001, 5000, "🦵🌀⏳💥", "нога Коллапса реальности"),
    (5001, 5500, "🦵🚀", "нога Сверхсветового прыжка"),
    (5501, 6000, "🦵🚀💫", "нога Прыжка через червоточину"),
    (6001, 6750, "🦵🚀🌌", "нога Гиперпространственного прыжка"),
    (6751, 7500, "🦵🌀🕳️", "нога Кротовой норы"),
    (7501, 8500, "🦵⏳🌀", "нога Искривления времени"),
    (8501, 9750, "🦵⏳🔀", "нога Временного парадокса"),
    (9751, 11250, "🦵⏳❌", "нога Стирателя моментов"),
    (11251, 13000, "🦵⏳❌🌀", "нога Стирателя тайм-лайнов"),
    (13001, 15000, "🦵⏳❌🕳️", "нога Стирателя эпох"),
    (15001, 17500, "🦵⏳❌🌌", "нога Стирателя вселенных"),
    (17501, 20000, "🦵⏳❌♾️", "нога Стирателя реальностей"),
]
MGG_MEGA_LEVEL = 20001
MGG_MEGA_EMOJI = PREMIUM_MGG
MGG_MEGA_NAME = "нога кошко-девочки MGG"

ULTRA_REQUIRED_EVO = 50
ULTRA_REQUIRED_LEG_LEVEL = MGG_MEGA_LEVEL
ULTRA_REQUIRED_REBIRTHS = 5

ULTRA_LEG_LEVEL = 20002
ULTRA_LEG_EMOJI = "🦵🧪"
ULTRA_LEG_NAME = "тест нога"

# Визуальные тиры для ULTRA-диапазона (level >= 20002). Первые тиры узкие (шаг 15),
# дальше ширина каждого тира растёт геометрически (x~2.15), чтобы за разумное число
# ступеней дойти до астрономических уровней. Всё, что выше последнего тира (до
# ULTRA_LEVEL_CAP = 2×10^100), попадает в ULTRA_LEG_NAME как «потолочное» название —
# такие уровни физически недостижимы обычным фармом, только через ручную admin-выдачу.
ULTRA_TIERS = [
    (20002, 20016, "🦵⚠️🌀", "нога Аномалии"),
    (20017, 20048, "🦵🧬", "нога Мутации"),
    (20049, 20117, "🦵🌡️", "нога Абсолютного нуля"),
    (20118, 20265, "🦵🔬", "нога Планковской длины"),
    (20266, 20583, "🦵🌫️", "нога Квантовой пены"),
    (20584, 21267, "🦵🎲🌀", "нога Квантовой неопределённости"),
    (21268, 22738, "🦵🐈‍⬛📦", "нога кота Шрёдингера"),
    (22739, 25901, "🦵🕸️", "нога Струнной теории"),
    (25902, 32701, "🦵📐🌌", "нога 11-го измерения"),
    (32702, 47321, "🦵🌈🌀", "нога Браны"),
    (47322, 78754, "🦵🪞🌌", "нога Зеркальной вселенной"),
    (78755, 146335, "🦵🔁♾️", "нога Вечного возвращения"),
    (146336, 291634, "🦵🌌❌", "нога Схлопывания вселенной"),
    (291635, 604027, "🦵🧊💫", "нога Большого Замерзания"),
    (604028, 1275672, "🦵🔥🌌", "нога Большого Сжатия"),
    (1275673, 2719709, "🦵📖🌌", "нога Книги Судеб вселенной"),
    (2719710, 5824389, "🦵🎭🌌", "нога Иллюзии реальности"),
    (5824390, 12499451, "🦵🧩♾️", "нога Головоломки бытия"),
    (12499452, 26850834, "🦵👁️‍🗨️", "нога Всевидящего наблюдателя"),
    (26850835, 57706307, "🦵🌌🧠", "нога Космического разума"),
    (57706308, 124045574, "🦵⚙️🌌", "нога Симулятора вселенных"),
    (124045575, 266674998, "🦵🗺️♾️", "нога Карты всех вселенных"),
    (266674999, 573328260, "🦵🧿🌌", "нога Ока Мультиверса"),
    (573328261, 1232632773, "🦵🔗🌌", "нога Сцепленных вселенных"),
    (1232632774, 2650137476, "🦵🌌🌌", "нога Вселенной вселенных"),
    (2650137477, 5697772587, "🦵♾️🧠", "нога Бесконечного разума"),
    (5697772588, 12025085910546, "🦵📜♾️", "нога Летописи бытия"),
    (12025085910547, 25853934684689, "🦵🗿♾️", "нога Изначального творца"),
    (25853934684690, 55585959549096, "🦵🌌👑", "нога Владыки мультивселенной"),
    (55585959549097, 119509813007571, "🦵♾️👑", "нога Императора бесконечности"),
    (119509813007572, 256946097943292, "🦵❔♾️", "нога За пределами понимания"),
]

ULTRA_LEVEL_CAP = 2 * 10 ** 100

ULTRA_REBIRTH_BOOST = 5.0

LEG_POINT = 1
LEG_LIMIT = 5
MEK_POINT = 18
MEK_LIMIT = 10

# ==== Эво-апгрейд: новые «ноги»-эмодзи, открывающиеся по уровню эволюции ====
# Каждая запись: emoji -> (evolution_level_required, точки за штуку, лимит символов в сообщении).
# Точки считаются как MEK_POINT * (1 + bonus_pct/100), т.е. «на X% выше, чем робоноги».
EVO_LEG_TIERS = {
    "🦶": {"level": 10, "bonus_pct": 20, "limit": 10},
    "👣": {"level": 20, "bonus_pct": 30, "limit": 5},
    "🧦": {"level": 50, "bonus_pct": 50, "limit": 5},
    "👟": {"level": 100, "bonus_pct": 100, "limit": 5},
    "🥾": {"level": 250, "bonus_pct": 200, "limit": 5},
    "🩴": {"level": 500, "bonus_pct": 500, "limit": 3},
    "👢": {"level": 1000, "bonus_pct": 1200, "limit": 2},
}
EVO_LEG_EMOJI_ORDER = ["🦶", "👣", "🧦", "👟", "🥾", "🩴", "👢"]
# level -> emoji, для быстрой проверки «на этом уровне эволюции разблокировалась новая нога».
EVO_LEG_UNLOCK_BY_LEVEL = {cfg["level"]: emoji for emoji, cfg in EVO_LEG_TIERS.items()}

# Уровни эволюции для остальных разблокировок «Эво-апгрейда».
EVO_UNLOCK_REBIRTH_SPARK_LEVEL = 5    # ✨ Искра перерождения
EVO_UNLOCK_MEK2_LEVEL = 10            # доп. бонус к добыче «фермы» (см. EVO_FARM_BONUS_LVL10); сама 🦶 через EVO_LEG_TIERS
EVO_UNLOCK_NECKLACE_CRAFTS_LEVEL = 15  # крафты: Ожерелье из звёзд / пылающей звезды / Карманная звезда

# Доп. добыча фермы (команда «ферма») при достижении 10 уровня эволюции.
EVO_FARM_BONUS_LVL10 = 4000

# 🔥📿 Ожерелье пылающей звезды (крафт-бустер 15 ур. эволюции, +210% к добыче при экипировке):
# при фарме ног независимые шансы дать очки перерождения / очки престижа.
BLAZING_NECKLACE_REBIRTH_CHANCE = 0.017
BLAZING_NECKLACE_REBIRTH_RANGE = (1, 15)
BLAZING_NECKLACE_PRESTIGE_CHANCE = 0.012
BLAZING_NECKLACE_PRESTIGE_RANGE = (1, 3)

# 📿 Ожерелье из звёзд (крафт-бустер 15 ур. эволюции, +120% к добыче при экипировке):
# шанс дать предмет из кейса 1 при фарме ног.
STAR_NECKLACE_CASE1_DROP_CHANCE = 0.025

# 🔥 Оберег стихий (крафт-бустер 0 ур. крафта, +145% к добыче при экипировке):
# шанс при фарме ног дать небольшую бонус-фарму очков ноги.
ELEMENTAL_CHARM_PROC_CHANCE = 0.03
ELEMENTAL_CHARM_PROC_RANGE = (5, 50)

# 🕶️ Амулет сумерек (крафт-бустер 0 ур. крафта, +195% к добыче при экипировке):
# шанс при фарме ног дать 1 очко перерождения.
TWILIGHT_AMULET_PROC_CHANCE = 0.02
TWILIGHT_AMULET_REBIRTH_AMOUNT = 1

# 🐺 Клык хаоса (крафт-бустер 0 ур. крафта, +140% к добыче при экипировке):
# шанс при фарме ног дать небольшой бонус монет.
CHAOS_FANG_PROC_CHANCE = 0.03
CHAOS_FANG_COIN_RANGE = (10, 40)

# 🌠 Карманная звезда (не бустер, пассивный предмет из крафта 15 ур. эволюции):
# буст команды «ферма» x1.6 + гарантированные очки перерождения за каждый её вызов,
# и отдельно буст x1.2 обычной фармы ног (🦵/🦿/... в чате).
POCKET_STAR_FARM_CMD_MULT = 1.6
POCKET_STAR_FARM_CMD_REBIRTH_RANGE = (1, 10)
POCKET_STAR_LEG_FARM_MULT = 1.2

# 30 уровень: пассивный буст «Поток эволюции» — шанс на доп. эволюцию сверху при каждой эволюции.
EVO_FLOW_UNLOCK_LEVEL = 30
EVO_FLOW_EXTRA_CHANCE = 0.10

# Шанс кражи предмета у случайного игрока того же чата при фарме ног (🦵/🦿) — не привязан
# к какому-либо бустеру, срабатывает у всех. Ворует только из CASE_SELLABLE_ITEMS (кейсы
# 1-2-3), никогда крафтовые/уникальные/эво-предметы. Если у выбранной жертвы нечего украсть —
# тихий промах, без сообщения.
LEG_STEAL_CHANCE = 0.01

# Сколько бейджей игрок может ОДНОВРЕМЕННО показывать (в топах/профиле/инфо) — как слоты
# экипировки в инвентаре: заработать можно сколько угодно, но включить показ — не больше этого.
BADGES_DISPLAY_LIMIT = 5

# 🔱 Амулет Вилона: пока экипирован, каждый фарм ног (🦵/🦿) идёт в счётчик; на VILON_TRIGGER_EVERY-й
# раз счётчик сбрасывается и активируется x1.5 к добыче фермы/ног на VILON_BOOST_SECONDS секунд.
VILON_TRIGGER_EVERY = 20
VILON_BOOST_SECONDS = 15
VILON_BOOST_MULT = 1.5

# 🐱 Амулет Котяры: пока экипирован, при каждом фарме ног — шанс KOTYARA_BOOST_CHANCE дать
# x2 к добыче на KOTYARA_BOOST_SECONDS секунд (поверх обычного пассивного буста амулета).
KOTYARA_BOOST_CHANCE = 0.25
KOTYARA_BOOST_SECONDS = 10
KOTYARA_BOOST_MULT = 2

# 🐱 Амулет Котяры доп.эффект: символ 😺 в тексте фарма ног (лимит 3 за сообщение, как обычные
# ноги/мек-ноги). Если в сообщении >=3 шт. 😺 — x1.5 к итогу фарма фермы/ног, и НЕЗАВИСИМО в этот
# же момент шанс KOTYARA_CAT_COIN_CHANCE дать ещё случайные KOTYARA_CAT_COIN_MIN..MAX монет.
KOTYARA_CAT_SYMBOL_LIMIT = 3
KOTYARA_CAT_FARM_MULT = 1.5
KOTYARA_CAT_COIN_CHANCE = 0.05
KOTYARA_CAT_COIN_MIN, KOTYARA_CAT_COIN_MAX = 100, 1000

# 💍 Кольцо Мику: пока экипировано, символ 🎶 в тексте фарма ног (лимит 1 за сообщение)
# удваивает итог фарма — применяется как множитель поверх total, аналогично 🌌/⭐️.
MIKU_RING_SYMBOL_LIMIT = 1
MIKU_RING_FARM_MULT = 2

# Бейджи за уровень эволюции — (ключ, название) по возрастанию порога. Сами emoji-константы
# (PREMIUM_BADGE_EVO<N>) берутся из premium_emoji.py по этому же ключу с префиксом evo_milestone_.
EVO_MILESTONE_BADGE_LEVELS = [
    ("evo_milestone_10", 10, "Новичок в эво"),
    ("evo_milestone_25", 25, "Средний в эво"),
    ("evo_milestone_50", 50, "Мастер эво"),
    ("evo_milestone_100", 100, "Эво-чемпион"),
    ("evo_milestone_250", 250, "Король эво"),
    ("evo_milestone_500", 500, "Уничтожитель Эво"),
    ("evo_milestone_1000", 1000, "Всемогущий в эво"),
    ("evo_milestone_5000", 5000, "Эво-бог"),
    ("evo_milestone_10000", 10000, "Эво-Титан"),
    ("evo_milestone_50000", 50000, "Эво-Крушитель"),
    ("evo_milestone_100000", 100000, "Эво-Легенда"),
    ("evo_milestone_1000000", 1000000, "Эво-Абсолют"),
]

# Бейджи за количество открытых кейсов (любых).
CASE_MILESTONE_BADGE_LEVELS = [
    ("case_milestone_50", 50, "Любитель кейсов"),
    ("case_milestone_500", 500, "Кейсовый безумец"),
    ("case_milestone_5000", 5000, "Разоритель Кейсов"),
]

# Бейджи за суммарно нафармленные очки ноги (total_farmed).
FARM_MILESTONE_BADGE_LEVELS = [
    ("farm_milestone_1m", 1_000_000, "Начальный фармер"),
    ("farm_milestone_500m", 500_000_000, "Продвинутый фармер"),
    ("farm_milestone_5b", 5_000_000_000, "Мастер фарма"),
    ("farm_milestone_1t", 1_000_000_000_000, "Бог фарма"),
    ("farm_milestone_1q", 1_000_000_000_000_000, "Всемогущий фармер"),
    ("farm_milestone_1qi", 1_000_000_000_000_000_000, "Фармер-ногость"),
]

# Бейджи за баланс монет (🪙, coins).
COIN_MILESTONE_BADGE_LEVELS = [
    ("coin_milestone_1k", 1_000, "Мелкий вкладчик"),
    ("coin_milestone_10k", 10_000, "Коллекционер монет"),
    ("coin_milestone_100k", 100_000, "Денежный мешок"),
    ("coin_milestone_10m", 10_000_000, "Магнат"),
    ("coin_milestone_1b", 1_000_000_000, "Коин-Олигарх"),
    ("coin_milestone_10b", 10_000_000_000, "Хозяин Экономики"),
]

# Бейджи за баланс очков перерождения (🉑, rebirth_points).
REBIRTH_MILESTONE_BADGE_LEVELS = [
    ("rebirth_milestone_100", 100, "Первое дыхание"),
    ("rebirth_milestone_10k", 10_000, "Искра цикла"),
    ("rebirth_milestone_1m", 1_000_000, "Странник перерождений"),
    ("rebirth_milestone_1b", 1_000_000_000, "Владыка Циклов"),
    ("rebirth_milestone_10b", 10_000_000_000, "Бессмертный"),
]

# Бейджи за стрик ежедневного бонуса (bonus_streak — дней подряд, см. daily_bonus()).
STREAK_MILESTONE_BADGE_LEVELS = [
    ("streak_milestone_7", 7, "Неутомимый"),
    ("streak_milestone_30", 30, "Железная воля"),
]

# Бейджи за количество успешных крафтов (crafts_done).
CRAFT_MILESTONE_BADGE_LEVELS = [
    ("craft_milestone_10", 10, "Ремесленник"),
    ("craft_milestone_100", 100, "Мастер-Кузнец"),
]

# Бейджи за баланс очков престижа (💠🔮 prestige_points).
PRESTIGE_MILESTONE_BADGE_LEVELS = [
    ("prestige_milestone_10", 10, "Искушённый"),
    ("prestige_milestone_100", 100, "Просветлённый"),
    ("prestige_milestone_25000", 25000, "Хранитель Мудрости"),
    ("prestige_milestone_50000", 50000, "Вознёсшийся"),
    ("prestige_milestone_100000", 100000, "Владыка Престижа"),
    ("prestige_milestone_250000", 250000, "Трансцендентный"),
    ("prestige_milestone_500000", 500000, "Абсолютный Разум"),
    ("prestige_milestone_1000000", 1000000, "За Гранью Престижа"),
]

FARM_COOLDOWN = 1200
FARM_BASE = (70, 170)
FARM_EVOLVED = (500, 900)

EXCHANGE_RATE = 200
REVERSE_EXCHANGE_RATE = 150
CRAFT_POINTS_EXCHANGE_RATE = 100
CRAFT_MAX_LEVEL = 3

DAILY_TABLE = [100, 250, 500, 750, 1000]
DAILY_MIN_GAP = 20 * 3600
DAILY_STREAK_LIMIT = 48 * 3600

BADGE_EVO_TOTAL = 30000

EVO_HARDNESS_RATE = 0.20
EVO_BOOST_STEP = 0.10

# Базовый уровень ноги (порог очков), нужный, чтобы сделать «эволюция» с 0 эво.
# С каждой пройденной эволюцией сам требуемый уровень растёт на 1 (39 -> 40 -> 41 -> ...),
# независимо от EVO_HARDNESS_RATE (которое усложняет стоимость ЭТОГО же уровня в процентах).
EVO_REQUIRED_BASE_LEVEL = 39

VIP_BOOST = 2.0

LEG_REPLY_COOLDOWN = 1
LEG_FARM_COOLDOWN = 0.8
VIP_STARS_PRICE = 15
VIP_FOREVER_SECONDS = 100 * 365 * 86400
PING_INTERVAL = 600

TEXTS = {
    "promo_create_1": 'Формат: !промокод создать "тип" "количество" "активаций" "название"\n'
                       'Тип: ноги/эво/коин/очкп/крафт или предмет:<ключ>.',
    "promo_create_2": '❌ Неизвестный тип награды: «{v0}». Смотри формат: ноги/эво/коин/очкп/крафт или предмет:<ключ>.',
    "promo_create_3": '❌ Количество должно быть положительным числом.',
    "promo_create_4": '❌ Число активаций должно быть положительным числом.',
    "promo_create_5": '❌ Промокод «{v0}» уже существует. Сначала удали его: !промокод удалить "{v0}".',
    "promo_create_6": '✅ Промокод «{v0}» создан!\nНаграда: {v1} × {v2}\nАктиваций: {v3}',
    "promo_delete_1": 'Формат: !промокод удалить "название"',
    "promo_delete_2": '❌ Промокод «{v0}» не найден.',
    "promo_delete_3": '🗑 Промокод «{v0}» удалён.',
    "promo_list_1": 'Активных промокодов пока нет.',
    "promo_list_2": '🎟 <b>Промокоды ({v0}):</b>\n{v1}',
    "promo_redeem_1": 'Формат: промокод <название> (или промо <название>)',
    "promo_redeem_2": '❌ Такого промокода не существует.',
    "promo_redeem_3": '⚠️ Активации промокода «{v0}» закончились.',
    "promo_redeem_4": '⚠️ Ты уже активировал этот промокод раньше.',
    "promo_redeem_5": '🎉 Промокод «{v0}» активирован! Получено: {v1}',

    "promo_create_badge_1": 'Формат: !промокод создать бейдж "название_бейджа" "название_промокода"\n'
                             'Доступные бейджи: фанат мику, сапорт, потужность, топ1 в прошлом.',
    "promo_create_badge_2": '❌ Неизвестный бейдж: «{v0}». Смотри список доступных бейджей: фанат мику, сапорт, потужность, топ1 в прошлом.',
    "promo_create_badge_3": '❌ Промокод «{v0}» уже существует. Сначала удали его: !промокод удалить "{v0}".',
    "promo_create_badge_4": '✅ Промокод «{v0}» создан!\nНаграда: {v1} бейдж «{v2}»\nАктиваций: 1',

    "maybe_announce_levelup_1": '🎉 {v0} поднялся до нового уровня! {v1}{v2}{v3}',
    "notify_off_1": 'Уведомления о новом уровне выключены.',
    "notify_on_1": 'Уведомления о новом уровне включены.',
    "vip_info_command_1": 'У тебя уже есть VIP-статус! 💎',
    "vip_info_command_2": '💎 VIP даёт постоянный буст +{v0}% к добыче.\nЦена: {v1} звёзд Telegram — выдаётся навсегда. Для оформления напиши админу.',
    "auto_evolve_not_vip_1": '⚠️ Авто-эволюция доступна только с VIP-статусом. Команда «вип» — как получить.',
    "auto_evolve_on_1": '⚙️💎 Авто-эволюция включена. Как только хватит очков — эволюция сработает сама.',
    "auto_evolve_off_1": '⚙️ Авто-эволюция выключена.',
    "auto_rebirth_not_vip_1": '⚠️ Авто-перерождение доступно только с VIP-статусом. Команда «вип» — как получить.',
    "auto_rebirth_on_1": '♻️💎 Авто-перерождение включено. Как только эволюция достигнет {v0} — перерождение сработает само.',
    "auto_rebirth_off_1": '♻️ Авто-перерождение выключено.',
    "ping_not_vip_1": '⚠️ Команда «пинг» доступна только с VIP-статусом. Команда «вип» — как получить.',
    "vip_stats_not_vip_1": '⚠️ Команда «стата» доступна только с VIP-статусом. Команда «вип» — как получить.',
    "compact_off_1": '📋 Краткий режим выключен — бонусы (вазы, монеты, шары и т.д.) снова показываются полностью.',
    "compact_on_1": '📋 Краткий режим включён — доп. тексты бонусов при фарме скрыты, видна только основная строка.',
    "auto_sell_on_1": '💰 Авто-продажа включена. Настрой список предметов: «авто продажа настройка».',
    "auto_sell_off_1": '💰 Авто-продажа выключена.',
    "vip_case_open_1": 'Формат: вип открыть кейс <номер> <кол-во> (максимум 20 за раз).',
    "vip_case_open_2": '⚠️ Авто-эволюция VIP-only. Команда «вип» — как получить.',
    "vip_case_open_3": 'Такого кейса нет. Посмотри «кейсы» — список номеров.',
    "vip_case_open_4": 'Максимум 20 кейсов за одну команду.',
    "vip_case_open_5": 'Не хватает монет: нужно {v0} 🪙, у тебя {v1} 🪙.',
    "vip_case_open_6": '💎📦 Открыто {v0}× «{v1}» за {v2} 🪙 (осталось {v3} 🪙):\n{v4}',
    "buy_vip_invoice_1": 'Это не твоя покупка!',
    "process_successful_payment_1": '💎 Оплата прошла! VIP-статус выдан навсегда. Спасибо за поддержку!',
    "badges_menu_1": 'У тебя пока нет значков. Качай ногу, эволюционируй, открывай кейсы!',
    "badges_menu_2": f'🏷 Твои значки (жми, чтобы включить/выключить показ — максимум {BADGES_DISPLAY_LIMIT} одновременно):',
    "toggle_badge_1": 'Это не твои значки!',
    "toggle_badge_2": 'Готово!',
    "toggle_badge_3": f'Уже показано максимум значков ({BADGES_DISPLAY_LIMIT}) — сначала выключи один, чтобы включить другой.',
    "count_legs_1": '{v0} {v1} → +{v2} очков{v3} {v4}(Всего: {v5}){v6}',
    "count_legs_2": 'Лютый рофл засчитан! {v0} → +{v1} очков{v2} (Всего: {v3}){v4}',
    "info_player_1": 'Игрок не найден (он ещё не писал ноги в этом боте).',
    "cmd_ban_player_1": 'Бан работает только в групповых чатах.',
    "cmd_ban_player_2": 'Банить может только владелец бота.',
    "cmd_ban_player_3": 'Ответь этой командой на сообщение того, кого банишь, либо напиши !бан @username (юзер должен был хоть раз написать боту).',
    "cmd_ban_player_4": 'Нельзя забанить самого себя.',
    "cmd_ban_player_5": 'Нельзя забанить владельца бота.',
    "cmd_ban_player_6": '🚫 Уничтожен.',
    "cmd_ban_player_7": '{v0} уже забанен.',
    "cmd_unban_player_1": '✅ {v0} разбанен.',
    "cmd_unban_player_2": '{v0} не был забанен в игре.',
    "send_legs_top_1": 'В топе пока пусто, никто еще не кинул ногу... 🧍',
    "send_evo_top_1": 'В топе пока пусто.',
    "send_coin_top_1": 'В топе пока пусто.',
    "send_rebirth_top_1": 'В топе пока пусто.',
    "send_gold_coin_top_1": 'В топе гкоин пока пусто.',
    "send_diamond_coin_top_1": 'В топе акоин пока пусто.',
    "require_subscription_1": '📝 Для работы на ферме нужно быть подписанным на канал.\nПодписывайтесь на канал и бегом обратно фармить',
    "farm_1": 'Ферма на кулдауне ⏳ Осталось {v0} мин {v1} сек',
    "farm_2": '{v0} 🦵 +{v1} очков (Всего: {v2}){v3}{v4}{v5}{v6}',
    "farm_3": 'Наферметил ногу! 🦵 +{v0} очков (Всего: {v1}){v2}{v3}{v4}',
    "daily_bonus_1": 'Бонус уже забирал сегодня ⏳ Приходи через {v0} ч {v1} мин',
    "daily_bonus_2": '🎁 День {v0}: +{v1} очков ноги (Всего: {v2}){v3}',
    "reverse_exchange_1": 'Количество монет должно быть больше нуля.',
    "reverse_exchange_2": 'Недостаточно монет. У тебя {v0} 🪙.',
    "reverse_exchange_3": 'Обменял {v0} 🪙 → +{v1} очков ноги (Всего очков: {v2})',
    "exchange_1": 'Формат: обменять <количество монет>. Курс: {v0} очков ноги = 1 монета.',
    "exchange_2": 'Количество монет должно быть больше нуля.',
    "exchange_3": 'Недостаточно очков. У тебя {v0}, максимум можешь обменять на {v1} 🪙.',
    "exchange_4": 'Обменял {v0} очков → +{v1} 🪙 монет (Всего монет: {v2}){v3}',
    "gold_coin_exchange_1": 'Формат: обменять гкоин <количество>. Курс: 1000 🪙 = 1 🌕 (указывай сколько 🌕 хочешь получить).',
    "gold_coin_exchange_2": 'Нужен обменник 1 лвл, чтобы обменивать на 🌕 гкоин. Прокачай его в апгрейдах (апг).',
    "gold_coin_exchange_3": 'Недостаточно монет. У тебя {v0} 🪙, нужно {v1} 🪙 на {v2} 🌕. Максимум сейчас можешь получить {v3} 🌕.',
    "gold_coin_exchange_4": 'Обменял {v0} 🪙 → +{v1} 🌕 (Всего гкоин: {v2})',
    "diamond_coin_exchange_1": 'Формат: обменять акоин <количество>. Курс: 1000 🌕 = 1 💎 (указывай сколько 💎 хочешь получить).',
    "diamond_coin_exchange_2": 'Нужен обменник 2 лвл, чтобы обменивать на 💎 акоин. Прокачай его в апгрейдах (апг).',
    "diamond_coin_exchange_3": 'Недостаточно гкоин. У тебя {v0} 🌕, нужно {v1} 🌕 на {v2} 💎. Максимум сейчас можешь получить {v3} 💎.',
    "diamond_coin_exchange_4": 'Обменял {v0} 🌕 → +{v1} 💎 (Всего акоин: {v2})',
    "transfer_currency_1": 'Ответь этой командой на сообщение того, кому передаёшь.',
    "transfer_currency_2": 'Нельзя передать самому себе.',
    "transfer_currency_3": 'Передавать можно только с 1 уровня эволюции.',
    "transfer_currency_4": 'Недостаточно очков. У тебя {v0}.',
    "transfer_currency_5": '{v0} передал {v1} очков игроку {v2}.',
    "transfer_currency_6": 'Недостаточно монет. У тебя {v0}.',
    "transfer_currency_7": '{v0} передал {v1} 🪙 игроку {v2}.',
    "transfer_item_direct_1": 'Ответь этой командой на сообщение того, кому передаёшь предмет.',
    "transfer_item_direct_2": '❌ Такого предмета не существует: «{v0}». Проверь название в «инвентарь».',
    "transfer_item_direct_3": '🚫 {v0} {v1} нельзя передать — это уникальный или божественный предмет.',
    "transfer_item_direct_4": 'Нельзя передать предмет самому себе.',
    "transfer_item_direct_5": 'У тебя нет предмета «{v0}».',
    "transfer_item_direct_6": '{v0} {v1} передан игроку {v2}!',
    "give_or_transfer_1": 'Укажи, что передать: число+валюту («дать 100 коин») или название предмета («передать свеча»).',
    "give_or_transfer_2": 'Некорректное количество.',
    "give_or_transfer_3": '❌ Такой валюты не существует: «{v0}». Доступно: ног, коин.',
    "give_or_transfer_4": 'Некорректное количество.',
    "sell_item_1": 'Не нашёл такой предмет среди {v0}. Если это не то — попробуй «{v1} <название>».',
    "sell_item_2": '🚫 {v0} {v1} нельзя продать — это уникальный или божественный предмет.',
    "sell_item_3": 'У тебя нет предмета «{v0}».',
    "sell_item_4": 'Продал {v0} {v1} за {v2} 🪙.{v3}',
    "sell_item_4_all": 'Продал всё: {v0} {v1} x{v2} за {v3} 🪙.{v4}',
    "sell_wrong_format_1": 'Не понял формат. Укажи тип: «продать б <название>» — для бустеров, «продать п <название>» — для предметов.',
    "destroy_item_1": 'Не нашёл такой предмет среди {v0}. Если это не то — попробуй «{v1} <название>».',
    "destroy_item_2": '🚫 {v0} {v1} нельзя уничтожить — это уникальный или божественный предмет.',
    "destroy_item_3": 'У тебя нет предмета «{v0}».',
    "destroy_item_4": '🗑 Уничтожил {v0} {v1}. Без награды — назад не вернуть.',
    "destroy_wrong_format_1": 'Не понял формат. Укажи тип: «уничтожение б <название>» — для бустеров, «уничтожение п <название>» — для предметов.',
    "inventory_1": '🎒 Инвентарь пуст.',
    "inventory_back_to_menu_1": 'Это не твой инвентарь!',
    "inventory_open_category_1": 'Это не твой инвентарь!',
    "toggle_equip_1": 'Это не твой инвентарь!',
    "potion_brew_busy_1": '🔥 Котёл уже занят — дождись, пока текущее зелье сварится.',
    "potion_brew_no_coins_1": 'Не хватает монет: нужно {v0} 🪙, у тебя {v1} 🪙.',
    "potion_brew_started_1": '⚗️ Варка начата: {v0} {v1} будет готово через {v2}.',
    "potion_collect_none_1": 'Котёл пуст — нечего забирать.',
    "potion_collect_not_ready_1": 'Зелье ещё варится — подожди {v0}.',
    "potion_collect_ok_1": '✅ Забрал: {v0} {v1}!',
    "potion_use_none_1": 'У тебя нет такого зелья в запасе.',
    "potion_use_ok_1": '{v0} {v1} выпито! Действует {v2}.',
    "potion_use_ok_charges_1": '{v0} {v1} выпито! Действует следующие {v2} использования фермы.',
    "toggle_equip_2": 'Этот предмет нельзя экипировать — он действует пассивно, пока лежит в инвентаре.',
    "toggle_equip_4": 'Готово!',
    "toggle_equip_5": 'Занято максимум слотов ({v0}) — сначала сними один бустер, чтобы надеть другой.',
    "craft_do_1": 'Это не твой крафт!',
    "craft_do_2": 'Рецепт не найден.',
    "craft_do_3": 'Нужен уровень крафта {v0}, у тебя {v1}.',
    "craft_do_4": 'Готово!',
    "send_case_inspect_1": 'Такого кейса нет.',
    "open_case_instant_1": 'Такого кейса нет.',
    "open_case_instant_2": 'Не хватает монет. Нужно {v0} 🪙, у тебя {v1} 🪙.',
    "open_case_instant_3": '🎉 Выпало: {v0} {v1} (+{v2}%)!\nОстаток монет: {v3} 🪙',
    "case_list_1": 'Доступные кейсы:',
    "inspect_case_callback_1": 'Это не твоё меню!',
    "buy_case_1": 'Это не твой кейс!',
    "buy_case_2": 'Не хватает монет. Нужно {v0} 🪙',
    "buy_case_3": 'Кейс открыт!',
    "evolve_1": 'Нужно достичь «ногу мгг» (39 ур, {v0} очков), чтобы эволюционировать.',
    "evolve_2": '🎆 ЭВОЛЮЦИЯ! Прогресс сброшен, теперь у тебя {v0} уровень эволюции навсегда.\n⚠️ Прокачка уровней теперь на {v1}% сложнее.{v2}',
    "toggle_event_1": '🌟 Ивент «Золотая ногость» запущен! Х2 к фарме ног во всех чатах.',
    "toggle_event_2": 'Ивент «Золотая ногость» окончен.',
    "upgrade_change_page_1": 'Это не твоё меню прокачки!',
    "upgrade_buy_1": 'Это не твоё меню прокачки!',
    "upgrade_buy_2": 'Этот раздел ещё в разработке.',
    "upgrade_buy_3": 'Максимальный уровень уже достигнут.',
    "upgrade_buy_4": 'Не хватает 🉑. Нужно {v0}, у тебя {v1}.',
    "upgrade_buy_5": 'Улучшено! {v0} → {v1} лвл',
    "prestige_buy_4": 'Не хватает 🔮. Нужно {v0}, у тебя {v1}.',
    "rebirth_1": 'Перерождение доступно с {v0} уровня эволюции (сейчас у тебя {v1}). Каждые {v2} уровней эво = 1 🉑.',
    "rebirth_2": '🉑 <b>ПЕРЕРОЖДЕНИЕ!</b>\nОчки ноги и эволюция сброшены. Получено: +{v0} 🉑 (Всего: {v1}) и +{v3} 🔮 престижа.\n⚠️ Эволюции теперь на {v2}% сложнее, чем с нуля.\nПрокачки из меню «апгрейд» остались с тобой навсегда.',
    "ultra_rebirth_locked_1": (
        '🌌 <b>Ультра перерождение</b> заблокировано:\n'
        '● Эволюция: {v0}/{v1}\n'
        '● Уровень ноги: {v2}/{v3}\n'
        '● Перерождений: {v4}/{v5}\n'
        '● Монета Пробуждения в инвентаре: {v6}\n'
        '● Хвост Джевила в инвентаре: {v7}\n'
        '⚠️ Нужны все пять условий сразу.'
    ),
    "ultra_rebirth_already_1": '🌌 Ты уже прошёл Ультра перерождение — второй раз нельзя.',
    "ultra_rebirth_confirm_1": (
        '🌌 <b>Тайны ждут вас.</b>\n'
        'За порогом — обнуление очков, эволюции и перерождений. Пути назад не будет.\n'
        'Открой то, что видели не все: {v0} {v1} ({v2} лвл) и постоянный буст +{v3}% к добыче.\n'
        'Прокачки и предметы шагнут в неизвестность вместе с тобой.'
    ),
    "ultra_rebirth_success_1": (
        '🌌✨ <b>Порог пройден. Тайны раскрыты.</b>\n'
        'Открыт {v0} {v1} ({v2} лвл) и постоянный буст добычи +{v3}%.\n'
        'Получено +{v4} 🔮 очков престижа.\n'
        'Прокачки и предметы остались с тобой навсегда.'
    ),
    "ultra_rebirth_cancelled_1": 'Ультра перерождение отменено — прогресс не тронут.',
    "ultra_rebirth_not_owner_1": 'Это не твоё подтверждение!',
    "show_balance_1": '💰 <b>Твой баланс</b>\n━━━━━━━━━━━━━━━━━━\n👣 Очки ноги: <code>{v0}</code>\n🪙 Монеты: <code>{v1}</code>\n🌕 Голд коин: <code>{v6}</code>\n💎 Алмаз коин: <code>{v7}</code>\n🉑 Очки перерождения: <code>{v2}</code> (перерождений: {v3})\n💠 Очки крафта: <code>{v5}</code>\n{v4}',
    "admin_give_rebirth_1": 'Формат: !дать очкп <количество> [себе] (в ответ на сообщение игрока)',
    "admin_give_rebirth_2": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_give_rebirth_3": 'Некорректное количество.',
    "admin_give_rebirth_4": 'Выдано {v0} 🉑 игроку {v1} (Всего: {v2})',
    "admin_take_rebirth_1": 'Формат: !снять очкп <количество> [себе] (в ответ на сообщение игрока)',
    "admin_take_rebirth_2": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_take_rebirth_3": 'Некорректное количество.',
    "admin_take_rebirth_4": 'Снято {v0} 🉑 у игрока {v1} (Осталось: {v2})',
    "broadcast_news_1": 'Напиши текст новости после команды: !новость <текст>',
    "broadcast_news_2": 'Разослано в {v0} чатов. Не удалось: {v1}.',
    "admin_give_legs_1": 'Формат: !дать ног <количество> [себе] (в ответ на сообщение игрока)',
    "admin_give_legs_2": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_give_legs_3": 'Некорректное количество.',
    "admin_give_legs_4": 'Выдано {v0} очков ноги игроку {v1}. Теперь у него: {v2}',
    "admin_take_legs_1": 'Формат: !снять ноги <количество> [себе] (в ответ на сообщение игрока)',
    "admin_take_legs_2": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_take_legs_3": 'Некорректное количество.',
    "admin_take_legs_4": 'Снято очков у {v0}. Теперь у него: {v1}',
    "admin_give_evo_1": 'Формат: !дать эво <количество> [себе] (в ответ на сообщение игрока)',
    "admin_give_evo_2": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_give_evo_3": 'Некорректное количество.',
    "admin_give_evo_4": 'Выдано {v0} уровней эволюции игроку {v1}. Теперь: {v2}',
    "admin_take_evo_1": 'Формат: !снять эво <количество> [себе] (в ответ на сообщение игрока)',
    "admin_take_evo_2": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_take_evo_3": 'Некорректное количество.',
    "admin_take_evo_4": 'Снято {v0} уровней эволюции у {v1}. Теперь: {v2}',
    "admin_give_coin_1": 'Формат: !дать коин <количество> [себе] (в ответ на сообщение игрока)',
    "admin_give_coin_2": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_give_coin_3": 'Некорректное количество.',
    "admin_give_coin_4": 'Выдано {v0} 🪙 игроку {v1}. Теперь: {v2}',
    "admin_take_coin_1": 'Формат: !снять коин <количество> [себе] (в ответ на сообщение игрока)',
    "admin_take_coin_2": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_take_coin_3": 'Некорректное количество.',
    "admin_take_coin_4": 'Снято {v0} 🪙 у {v1}. Теперь: {v2}',
    "admin_give_boost_1": 'Формат: !дать б <название бустера> [себе] (в ответ на сообщение игрока)',
    "admin_give_boost_2": 'Не нашёл такой бустер. Для пассивных предметов используй «!дать п».',
    "admin_give_boost_3": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_give_boost_4": 'Выдан бустер {v0} {v1} игроку {v2}.',
    "admin_take_boost_1": 'Формат: !снять б <название бустера> [себе] (в ответ на сообщение игрока)',
    "admin_take_boost_2": 'Не нашёл такой бустер. Для пассивных предметов используй «!снять п».',
    "admin_take_boost_3": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_take_boost_4": 'Снят бустер {v0} {v1} у игрока {v2}.',
    "admin_take_boost_5": 'У игрока {v0} нет предмета «{v1}».',
    "admin_give_passive_1": 'Формат: !дать п <название предмета> [себе] (в ответ на сообщение игрока)',
    "admin_give_passive_2": 'Не нашёл такой пассивный предмет. Для бустеров используй «!дать б».',
    "admin_give_passive_3": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_give_passive_4": 'Выдан предмет {v0} {v1} игроку {v2}.',
    "admin_take_passive_1": 'Формат: !снять п <название предмета> [себе] (в ответ на сообщение игрока)',
    "admin_take_passive_2": 'Не нашёл такой пассивный предмет. Для бустеров используй «!снять б».',
    "admin_take_passive_3": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_take_passive_4": 'Снят предмет {v0} {v1} у игрока {v2}.',
    "admin_take_passive_5": 'У игрока {v0} нет предмета «{v1}».',
    "admin_give_vip_1": 'Формат: !дать вип <дней> [себе] (в ответ на сообщение игрока)',
    "admin_give_vip_2": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_give_vip_3": 'Некорректное количество дней.',
    "admin_give_vip_4": 'Выдан VIP на {v0} дн. игроку {v1}.',
    "admin_take_vip_1": 'Формат: !снять вип [себе] (в ответ на сообщение игрока)',
    "admin_take_vip_2": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_take_vip_3": 'VIP снят у игрока {v0}.',
    "admin_reset_1": 'Формат: !сбросить [себе] (в ответ на сообщение игрока)',
    "admin_reset_2": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_reset_3": 'Полный сброс прогресса игрока {v0} выполнен.',

    "nick_set_too_long": 'Слишком длинный ник — максимум 50 символов (у тебя {v0}).',
    "nick_set_empty": 'Укажи сам ник: +ник <текст>',
    "nick_set_taken": 'Этот ник уже занят другим игроком.',
    "nick_set_ok": 'Ник установлен: {v0}',
    "nick_clear_ok": 'Ник сброшен, теперь отображается твой обычный юзернейм.',

    "admin_set_legs_1": 'Формат: !установить ног <число> [себе] (в ответ на сообщение игрока)',
    "admin_set_legs_2": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_set_legs_3": 'Некорректное число.',
    "admin_set_legs_4": 'Игроку {v0} установлено очков: {v1} (было {v2}).',
    "admin_give_legs_lvl_1": 'Формат: !дать ноги лвл<число> [себе] (в ответ на сообщение игрока), например: !дать ноги лвл20001',
    "admin_give_legs_lvl_2": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_give_legs_lvl_3": 'Максимальный доступный уровень для этого игрока: {v0}.',
    "admin_give_legs_lvl_4": 'Игроку {v1} установлен {v0} лвл ноги (очков: {v2}).',

    "admin_set_evo_1": 'Формат: !установить эво <число> [себе] (в ответ на сообщение игрока)',
    "admin_set_evo_2": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_set_evo_3": 'Некорректное число.',
    "admin_set_evo_4": 'Игроку {v0} установлен уровень эволюции: {v1} (было {v2}).',

    "admin_reset_cd_1": 'Формат: !сброс кд [себе] (в ответ на сообщение игрока)',
    "admin_reset_cd_2": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_reset_cd_3": 'Кулдаун фермы сброшен у игрока {v0}.',

    "admin_reset_bonus_1": 'Формат: !сброс бонус [себе] (в ответ на сообщение игрока)',
    "admin_reset_bonus_2": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_reset_bonus_3": 'Ежедневный бонус сброшен у игрока {v0} — можно забрать снова.',

    "admin_give_case_1": 'Формат: !дать кейс <номер> <кол-во> [себе] (в ответ на сообщение игрока)',
    "admin_give_case_2": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_give_case_3": 'Нет кейса с таким номером.',
    "admin_give_case_4": 'Количество должно быть от 1 до 100.',
    "admin_give_case_5": '🎁 Игроку {v0} бесплатно открыт кейс «{v1}» {v2} раз(а):\n{v3}',

    "admin_debug_1": 'Формат: !дебаг @username',
    "admin_debug_2": 'Игрок не найден (он ещё не писал ноги в этом боте).',
    "admin_debug_3": '🛠 <b>Дебаг {v0}:</b>\n<code>{v1}</code>',

    "admin_show_text_1": 'Формат: !текст <ключ>',
    "admin_show_text_2": 'Нет такого ключа в TEXTS.',
    "admin_show_text_3": '🔑 <code>{v0}</code>:\n{v1}',

    "admin_simulate_evo_1": 'Формат: !симулировать эволюция @username',
    "admin_simulate_evo_2": 'Игрок не найден (он ещё не писал ноги в этом боте).',
    "admin_simulate_evo_3": '🔬 Симуляция эволюции для {v0}:\nОчков: {v1} / нужно {v2}\nТекущая эво: {v3}\n{v4}',
    "admin_simulate_evo_ok": '✅ Условие выполнено — может эволюционировать.',
    "admin_simulate_evo_fail": '❌ Не хватает {v0} очков.',

    "admin_stats_1": (
        '📊 <b>Статистика бота:</b>\n'
        '● Игроков всего: <code>{v0}</code>\n'
        '● Суммарно очков в экономике: <code>{v1}</code>\n'
        '● Суммарно монет в обороте: <code>{v2}</code>\n'
        '● Суммарно 🉑 очков перерождения: <code>{v3}</code>\n'
        '● Открыто кейсов всего: <code>{v4}</code>\n'
        '● Активных VIP: <code>{v5}</code>\n'
        '● Забанено из топов: <code>{v6}</code>'
    ),

    "admin_restart_1": '♻️ Перезапускаю бота...',
    "admin_unshow_all_badges_1": '🏷 Показ бейджей отключён у всех игроков. Каждый может заново включить нужные через «бейджи».',

    "admin_event_custom_1": 'Формат: !ивент х<множитель> <минуты>, например: !ивент х3 30',
    "admin_event_custom_2": 'Множитель и время должны быть положительными числами.',
    "admin_event_custom_3": '🌟 Ивент запущен! Множитель х{v0} на {v1} мин. (для всех чатов).',

    "admin_set_rebirth_1": 'Формат: !установить очкп <число> [себе] (в ответ на сообщение игрока)',
    "admin_set_rebirth_2": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_set_rebirth_3": 'Некорректное число.',
    "admin_set_rebirth_4": 'Игроку {v0} установлено очков перерождения: {v1} (было {v2}).',

    "admin_wipe_economy_1": 'Формат: !обнулить экономику @username',
    "admin_wipe_economy_2": 'Игрок не найден (он ещё не писал ноги в этом боте).',
    "admin_wipe_economy_3": 'Экономика игрока {v0} обнулена: очки, монеты и 🉑 сброшены в 0. Инвентарь и апгрейды не тронуты.',

    "admin_personal_boost_1": 'Формат: !мультипликатор ферма <число> <минуты> [себе] (в ответ на сообщение игрока)',
    "admin_personal_boost_2": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_personal_boost_3": 'Множитель и время должны быть положительными числами.',
    "admin_personal_boost_4": '🚀 Игроку {v0} выдан личный буст фермы х{v1} на {v2} мин.',

    "admin_give_item_1": 'Формат: !дать предмет <ключ> <кол-во> [себе] (в ответ на сообщение игрока)',
    "admin_give_item_2": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_give_item_3": 'Нет предмета с таким ключом.',
    "admin_give_item_4": 'Количество должно быть от 1 до 1000.',
    "admin_give_item_5": 'Игроку {v0} выдано: {v1} {v2} × {v3}.',
    "admin_give_key_1": 'Формат: !дать ключ <ключ> <кол-во> [себе] (в ответ на сообщение игрока)',
    "admin_give_key_2": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_give_key_3": 'Нет предмета с таким ключом.',
    "admin_give_key_4": 'Количество должно быть от 1 до 1000.',
    "admin_give_key_5": 'Игроку {v0} выдано: {v1} {v2} × {v3}.',

    "admin_clear_inventory_1": 'Формат: !очистить инвентарь @username',
    "admin_clear_inventory_2": 'Игрок не найден (он ещё не писал ноги в этом боте).',
    "admin_clear_inventory_3": 'Инвентарь игрока {v0} полностью очищен.',

    "admin_set_upgrade_1": 'Формат: !дать апгрейд <ключ> <уровень> [себе] (в ответ на сообщение игрока)',
    "admin_set_upgrade_2": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_set_upgrade_3": 'Нет апгрейда с таким ключом.',
    "admin_set_upgrade_4": 'Уровень должен быть от 0 до {v0}.',
    "admin_set_upgrade_5": 'Игроку {v0} установлен апгрейд «{v1}»: уровень {v2}.',

    "admin_ultra_rebirth_1": 'Формат: !ультра навсегда себе (или ответом на сообщение игрока)',
    "admin_ultra_rebirth_2": 'Игроку {v0} выдан статус Ультра перерождения (принудительно, без сброса прогресса).',
    "admin_vip_forever_1": 'Ответь этой командой на сообщение игрока, либо допиши «себе».',
    "admin_vip_forever_2": '👑 Игроку {v0} выдан VIP навсегда.',

    "admin_reset_nick_1": 'Формат: !сброс ник @username',
    "admin_reset_nick_2": 'Игрок не найден (он ещё не писал ноги в этом боте).',
    "admin_reset_nick_3": 'У игрока не было установлено ника.',
    "admin_reset_nick_4": 'Ник игрока {v0} сброшен (был: {v1}).',

    "admin_list_vip_1": 'Сейчас нет игроков с активным VIP.',
    "admin_list_vip_2": '👑 <b>Активный VIP ({v0}):</b>\n{v1}',

    "admin_list_nicknames_1": 'Сейчас ни у кого не установлен ник.',
    "admin_list_nicknames_2": '📛 <b>Установленные ники ({v0}):</b>\n{v1}',

    "admin_find_1": 'Формат: !найти @username',
    "admin_find_2": 'Игрок не найден (он ещё не писал ноги в этом боте).',
    "admin_find_3": '🔎 {v0} — бот видел его в {v1} чате(ах):\n{v2}',
    "admin_find_4": 'Бот не встречал этого игрока ни в одном чате.',
    "admin_players_1": 'Игроков пока нет.',
    "admin_players_2": '👥 <b>Игроки ({v0}):</b>\n{v1}',
    "admin_logs_all_1": 'Логов пока нет.',
    "admin_logs_all_2": '📜 <b>Все логи ({v0}):</b>\n{v1}',
    "admin_top_spam_1": 'За выбранный период команд от игроков не было.',
    "admin_top_spam_2": '🚨 <b>Топ спама за {v0} мин. ({v1} игроков):</b>\n{v2}',
    "admin_list_chats_1": 'Бот пока нигде не активен (ещё никто не писал команды в группах).',
    "admin_list_chats_2": '💬 Чаты бота ({v0}):\n{v1}',
    "cmd_ban_chat_1": 'Формат: !бан чат "название или начало названия".',
    "cmd_ban_chat_2": 'Ни один чат не начинается с "{v0}".',
    "cmd_ban_chat_3": '🚫 Уничтожено чатов: {v0}\n{v1}\n\nЗабанено игроков: {v2}\nБот покинул чатов: {v3}',
    "flood_ban_1": '🚫 Уничтожен. Если бан случайный, можно попросить у @{v0} разбанить вас.',

    "admin_logs_1": 'Лог пуст.',
    "admin_logs_2": '📜 <b>Последние действия ({v0}):</b>\n{v1}',
    "admin_logs_clear_1": '🧹 Очищено записей лога: {v0}. Осталось: {v1} (за последние 7 дней).',

    "admin_ping_1": '🏓 Понг! Ответ БД за {v0} мс.',
    "admin_ping_2": '🏓 Понг! 5 замеров SELECT 1 (мс): {v0}\nmin={v1} avg={v2} max={v3}',

    "admin_event_stop_1": 'Ивент остановлен.',
    "admin_event_stop_2": 'Ивент и так не активен.',

    "admin_event_status_1": '🌟 Ивент активен. Множитель х{v0}. Осталось: {v1}',
    "admin_event_status_2": 'Ивент сейчас не активен.',
    "admin_event_status_forever": 'без ограничения по времени',

    "help_root_1": (
        '❓ <b>Помощь</b>\n'
        'Введите значение: <b>бустер / предмет / зелье / бейдж / команда</b>\n\n'
        'Например: «помощь бейдж vip», «помощь бустер эссенция бога», «помощь команда апг».'
    ),
    "help_unknown_section_1": (
        '❓ Не понял раздел «{v0}».\n'
        'Введите значение: <b>бустер / предмет / зелье / бейдж / команда</b>'
    ),

    "help_badge_general_1": (
        '🏷 <b>Бейджи</b> — значки за достижения и события, отображаются рядом с ником в топах.\n'
        'Их можно скрывать/показывать через команду «значки».\n'
        'Спроси про конкретный: «помощь бейдж <название>» (например vip, владелец, фанат мику).'
    ),
    "help_badge_not_found_1": (
        '❓ Бейдж «{v0}» не найден.\n'
        'Доступные: {v1}\n'
        'Формат: «помощь бейдж <название>»'
    ),
    "help_badge_ambiguous_1": (
        '❓ Уточни, какой бейдж имеешь в виду «{v0}»:\n{v1}'
    ),

    "help_booster_general_1": (
        '🧪 <b>Бустеры</b> — экипируемые предметы, дающие постоянный процентный буст к добыче, пока надеты.\n'
        'Экипировать/снять можно через «инвентарь» → «Бустеры».\n'
        'Спроси про конкретный: «помощь бустер <название>» (например эссенция бога).'
    ),
    "help_booster_not_found_1": (
        '❓ Бустер «{v0}» не найден.\n'
        'Проверь название или посмотри список: «мои бустеры».\n'
        'Формат: «помощь бустер <название>»'
    ),
    "help_booster_ambiguous_1": (
        '❓ Уточни, какой бустер имеешь в виду «{v0}»:\n{v1}'
    ),
    "help_booster_info_1": '🧪 <b>{v0} {v1}</b>\n{v2}',

    "help_item_general_1": (
        '📦 <b>Предметы</b> — вещи без прямого процентного буста: сырьё для крафта, коллекционные или пассивные предметы.\n'
        'Посмотреть свои: «инвентарь» → «Предметы».\n'
        'Спроси про конкретный: «помощь предмет <название>» (например странная монета).'
    ),
    "help_item_not_found_1": (
        '❓ Предмет «{v0}» не найден.\n'
        'Проверь название или посмотри список: «мои предметы».\n'
        'Формат: «помощь предмет <название>»'
    ),
    "help_item_ambiguous_1": (
        '❓ Уточни, какой предмет имеешь в виду «{v0}»:\n{v1}'
    ),
    "help_item_info_1": '📦 <b>{v0} {v1}</b>\n{v2}',

    "help_potion_general_1": (
        '⚗️ <b>Зелья</b> — варятся в котле за монеты и время, при использовании дают временный эффект.\n'
        'Открой «мои зелья» — там кнопками: варить, забрать готовое, выпить.\n'
        'Спроси про конкретное: «помощь зелье <название>».'
    ),
    "help_potion_not_found_1": (
        '❓ Зелье «{v0}» не найдено.\n'
        'Проверь название или посмотри список: «мои зелья».\n'
        'Формат: «помощь зелье <название>»'
    ),
    "help_potion_ambiguous_1": (
        '❓ Уточни, какое зелье имеешь в виду «{v0}»:\n{v1}'
    ),
    "help_potion_info_1": '⚗️ <b>{v0} {v1}</b>\n{v2}',

    "help_command_general_1": (
        '🛠 <b>Команды</b> — основные действия в боте: ферма, бонус, апгрейд, крафт, кейсы и т.д.\n'
        'Спроси про конкретную: «помощь команда <название>» (например апг).'
    ),
    "help_command_not_found_1": (
        '❓ Команда «{v0}» не найдена.\n'
        'Доступные: {v1}\n'
        'Формат: «помощь команда <название>»'
    ),
    "help_command_ambiguous_1": (
        '❓ Уточни, какую команду имеешь в виду «{v0}»:\n{v1}'
    ),
    "help_command_info_1": '🛠 <b>{v0} {v1}</b>\n{v2}',

    "admin_give_all_1": '❓ Не понял, кому выдавать. Ответь на сообщение игрока командой «!дать всё» или напиши «!дать всё себе».',
    "admin_give_all_2": '✅ {v0} получил(а) все предметы, бустеры и зелья (по 1 шт. каждого): {v1} 📦🧪 + {v2} ⚗️.',

    "admin_levelup_notify_off_all_1": '✅ Показ нового уровня отключён у всех игроков ({v0}).',
}

ITEMS = {
    "amulet": ("🪬", "Амулет галактики", 17, 10),
    "orb":    ("🔮", "Шар парадокса", 14, 20),
    "pill":   ("💊", "Таблетка силы", 12, 30),
    "candle": ("🪔", "Свеча солнцестояния", 14, 35),
    "gift":   ("💮", "Подарок кошко-девочки", 65, 5),
    "star":   ("⭐️", "Звезда перерождения", 30, 0),
    "daily_charm": (PREMIUM_DAILY_CHARM, "Дневной амулет", 150, 0),
    "youtube_button": (PREMIUM_YOUTUBE_BUTTON, "Бриллиантовая кнопка Ютуба", 550, 0),
    "tiktok_legend": (PREMIUM_TIKTOK_LEGEND, "Легенда Ногости", 550, 0),
    "mk_mgg":       (PREMIUM_MK_MGG, "Амулет MGG", 145, 0.57),
    "mk_sandsmoon": (PREMIUM_MK_SANDSMOON, "Амулет SandsMoon", 40, 3.45),
    "mk_fixsahal1": (PREMIUM_MK_FIXSAHAL1, "Амулет Fixsahal1", 45, 5.75),
    "mk_mk":        (PREMIUM_MK_MK, "Амулет Rpuk_01", 90, 1.72),
    "mk_panther":   (PREMIUM_MK_PANTHER, "Амулет Haos", 60, 8.04),
    "mk_vector":    (PREMIUM_MK_VECTOR, "Амулет Vector", 40, 4.02),
    "mk_broken":    (PREMIUM_MK_BROKEN, "Сломанный амулет", 2, 60),
    "mk_mary":      (PREMIUM_MK_MARY, "Амулет Mary", 50, 5.75),
    "mk_veron03":   (PREMIUM_MK_VERON03, "Амулет @tuxpq", 35, 10),
    "vip_charm":    (PREMIUM_VIP_ITEM, "VIP-амулет", 270, 0),
    "strange_coin": (PREMIUM_STRANGE_COIN, "Странная монета", 0, 0.7),

    "power_amulet":        (PREMIUM_POWER_AMULET, "Амулет силы", 75, 0),
    "galaxy_power_amulet": (PREMIUM_GALAXY_POWER_AMULET, "Амулет силы галактики", 80, 0),
    "galaxy_might_amulet": (PREMIUM_GALAXY_MIGHT_AMULET, "Амулет Мощи галактики", 135, 0),
    "hybrid_amulet":       (PREMIUM_HYBRID_AMULET, "Неактивированный гибридный амулет", 0, 0),
    "friendship_essence":  (PREMIUM_FRIENDSHIP_ESSENCE, "Эссенция дружбы", 0, 0),
    "time_particle":       (PREMIUM_TIME_PARTICLE, "Частица времени", 0, 0),
    "god_essence":         (PREMIUM_GOD_ESSENCE, "Эссенция Бога", 700, 0),
    "koshko_amulet":       (PREMIUM_KOSHKO_AMULET, "Амулет кошко-девочки", 800, 0),
    "devotion_coin":       (PREMIUM_DEVOTION_COIN, "Монета боготворства", 0, 0),
    "old_vase":            (PREMIUM_OLD_VASE, "Старая ваза", 0, 0.4),
    "golden_vase":         (PREMIUM_GOLDEN_VASE, "Золотая ваза", 0, 0),
    "godly_vase":          (PREMIUM_GODLY_VASE, "Боготворная ваза", 0, 0),

    "lucky_charm":  (PREMIUM_LUCKY_CHARM, "Малый амулет удачи", 70, 0),
    "swift_pill":   (PREMIUM_SWIFT_PILL, "Ускоренная таблетка", 55, 0),
    "party_set":    (PREMIUM_PARTY_SET, "Праздничный набор", 115, 0),
    "warm_candle":  (PREMIUM_WARM_CANDLE, "Тёплая свеча", 0, 0),

    # ==== Крафт-бустеры 0 уровня из сырья Кейса 3 (Стихий и Крафта) ====
    "elemental_charm": ("🔥", "Оберег стихий", 145, 0),
    "twilight_amulet": ("🕶️", "Амулет сумерек", 195, 0),

    # ==== Крафт-бустеры 0 уровня из сырья Кейса 2 (Сапортов) ====
    "support_totem": ("🪄", "Сапорт-тотем", 135, 0),
    "chaos_fang":    ("🐺", "Клык хаоса", 140, 0),

    "ice_shard":     (PREMIUM_ICE_SHARD, "Ледяной осколок", 80, 12),
    "ember":         (PREMIUM_EMBER, "Уголёк", 75, 12),
    "dragon_claw":   (PREMIUM_DRAGON_CLAW, "Коготь дракона", 90, 8),
    "paradox_charm": (PREMIUM_PARADOX_CHARM, "Оберег парадокса", 65, 5),
    "shadow_mask":   (PREMIUM_SHADOW_MASK, "Маска тени", 155, 1.5),
    "tide_wave":     (PREMIUM_TIDE_WAVE, "Волна прилива", 85, 10),
    "warrior_skull": (PREMIUM_WARRIOR_SKULL, "Череп воина", 78, 7),
    "broken_clock":  (PREMIUM_BROKEN_CLOCK, "Сломанные часы", 0, 15),
    "essence_drop":  (PREMIUM_ESSENCE_DROP, "Капля эссенции", 0, 10),
    "comet_shard":   (PREMIUM_COMET_SHARD, "Осколок кометы", 0, 3),
    "koshko_gift":  (PREMIUM_KOSHKO_GIFT, "Дар кошко-девочки", 0, 2),
    "ancient_stone": (PREMIUM_ANCIENT_STONE, "Древний камень", 0, 18),
    "fate_thread":   (PREMIUM_FATE_THREAD, "Нить судьбы", 0, 4),

    "kotyara_amulet":  (PREMIUM_KOTYARA_AMULET, "Амулет Котяры", 280, 0),
    "miku_amulet":     (PREMIUM_MIKU_AMULET, "Амулет Мику", 85, 0),
    "golda":           (PREMIUM_GOLDA_ITEM, "Голда", 52, 0),
    "karambit_gold":   (PREMIUM_KARAMBIT_GOLD, "Керамбит голд", 228, 0),
    "butterfly_legacy": (PREMIUM_BUTTERFLY_LEGACY, "Бабочка легаси", 69, 0),
    "krest_amulet":    (PREMIUM_KREST_AMULET, "Амулет Креста", 100, 0),
    "fati_amulet":     (PREMIUM_FATI_AMULET, "Амулет Фати", 80, 0),
    "guitarist_crown": (PREMIUM_GUITARIST_CROWN, "Корона Гитариста", 150, 0),
    "vilon_amulet":    (PREMIUM_VILON_AMULET, "Амулет Вилона", 120, 0),
    "miku_ring":       (PREMIUM_MIKU_RING, "Кольцо Мику", 250, 0),

    "chaos_orb":     (PREMIUM_CHAOS_ORB, "Шар хаоса", 0, 100),
    "chronos_clock": (PREMIUM_CHRONOS_CLOCK, "Часы Хроноса", 0, 120),
    "chronos_orb":   (PREMIUM_CHRONOS_ORB, "Хвост Джевила", 0, 120),

    "miku_fan_amulet": (PREMIUM_MIKU_FAN_AMULET, "Амулет Фаната Мику", 300, 0),

    "nogost_coin":       (PREMIUM_NOGOST_COIN, "Монета Ногости", 200, 0),
    "godly_nogost_coin": (PREMIUM_GODLY_NOGOST_COIN, "Монета Бога Ногости", 500, 0),
    "craft_coin":        (PREMIUM_CRAFT_COIN, "Монета Крафта", 0, 0),
    "bitcoin":           (PREMIUM_BITCOIN, "Биткоин", 0, 0),
    "rebirth_coin":      (PREMIUM_REBIRTH_COIN, "Монета Перерождения", 0, 0),
    "evolution_coin":    (PREMIUM_EVOLUTION_COIN, "Монета Эволюции", 0, 0),
    "awakening_coin":    (PREMIUM_AWAKENING_COIN, "Монета Пробуждения", 0, 0),

    # ==== Эво-апгрейд (10/15 ур. эволюции) ====
    "rebirth_spark":  (PREMIUM_REBIRTH_SPARK, "Искра перерождения", 0, 20),
    "star_necklace":  (PREMIUM_STAR_NECKLACE, "Ожерелье из звёзд", 120, 0),
    "blazing_star_necklace": (PREMIUM_BLAZING_STAR_NECKLACE, "Ожерелье пылающей звезды", 210, 0),
    "pocket_star":    (PREMIUM_POCKET_STAR, "Карманная звезда", 0, 0),

    # ==== Крафт 3 ур.: Любитель Мастерства + его дроп-предмет nano-IT ====
    "mastery_lover_amulet": (PREMIUM_MASTERY_LOVER_AMULET, "Любитель Мастерства", 600, 0),
    "nano_it":              (PREMIUM_NANO_IT, "nano-IT", 0, 0),
}

# Разделение ITEMS на «бустеры» (экипируемые, дают процентный буст к добыче) и «предметы»
# (сырьё для крафта / пассивные / коллекционные) для команды «помощь бустер|предмет».
# Правило: boost_percent > 0 -> бустер. Единственное исключение — chronos_orb: он тоже
# экипируется (см. _format_equipped_item_line), но эффект случайный (10-400%), поэтому
# в ITEMS у него boost_percent = 0 — добавляем его в бустеры вручную.
HELP_BOOSTER_KEYS = {k for k, v in ITEMS.items() if v[2] > 0} | {"chronos_orb"}
HELP_ITEM_KEYS = set(ITEMS.keys()) - HELP_BOOSTER_KEYS

# Бейджи за уровень эволюции (см. EVO_MILESTONE_BADGE_LEVELS в config.py). Эмодзи-константы
# PREMIUM_BADGE_EVO<N> лежат в premium_emoji.py — здесь просто собираем их в один список
# (key, emoji, label, threshold), который перебирает badge_list() в economy.py.
EVO_MILESTONE_BADGES = [
    (key, globals()[f"PREMIUM_BADGE_EVO{threshold}"], label, threshold)
    for key, threshold, label in EVO_MILESTONE_BADGE_LEVELS
]

# Бейджи за открытые кейсы — тот же паттерн (key, emoji, label, threshold), перебирается в badge_list().
CASE_MILESTONE_BADGES = [
    ("case_milestone_50", PREMIUM_BADGE_CASE50, "Любитель кейсов", 50),
    ("case_milestone_500", PREMIUM_BADGE_CASE500, "Кейсовый безумец", 500),
    ("case_milestone_5000", PREMIUM_BADGE_CASE5000, "Разоритель Кейсов", 5000),
]

# Бейджи за суммарно нафармленные очки ноги (total_farmed).
FARM_MILESTONE_BADGES = [
    ("farm_milestone_1m", PREMIUM_BADGE_FARM1M, "Начальный фармер", 1_000_000),
    ("farm_milestone_500m", PREMIUM_BADGE_FARM500M, "Продвинутый фармер", 500_000_000),
    ("farm_milestone_5b", PREMIUM_BADGE_FARM5B, "Мастер фарма", 5_000_000_000),
    ("farm_milestone_1t", PREMIUM_BADGE_FARM1T, "Бог фарма", 1_000_000_000_000),
    ("farm_milestone_1q", PREMIUM_BADGE_FARM1Q, "Всемогущий фармер", 1_000_000_000_000_000),
    ("farm_milestone_1qi", PREMIUM_BADGE_FARM1QI, "Фармер-ногость", 1_000_000_000_000_000_000),
]

# Бейджи за баланс монет (🪙).
COIN_MILESTONE_BADGES = [
    ("coin_milestone_1k", PREMIUM_BADGE_COIN1K, "Мелкий вкладчик", 1_000),
    ("coin_milestone_10k", PREMIUM_BADGE_COIN10K, "Коллекционер монет", 10_000),
    ("coin_milestone_100k", PREMIUM_BADGE_COIN100K, "Денежный мешок", 100_000),
    ("coin_milestone_10m", PREMIUM_BADGE_COIN10M, "Магнат", 10_000_000),
    ("coin_milestone_1b", PREMIUM_BADGE_COIN1B, "Коин-Олигарх", 1_000_000_000),
    ("coin_milestone_10b", PREMIUM_BADGE_COIN10B, "Хозяин Экономики", 10_000_000_000),
]

# Бейджи за баланс очков перерождения (🉑).
REBIRTH_MILESTONE_BADGES = [
    ("rebirth_milestone_100", PREMIUM_BADGE_REBIRTH100, "Первое дыхание", 100),
    ("rebirth_milestone_10k", PREMIUM_BADGE_REBIRTH10K, "Искра цикла", 10_000),
    ("rebirth_milestone_1m", PREMIUM_BADGE_REBIRTH1M, "Странник перерождений", 1_000_000),
    ("rebirth_milestone_1b", PREMIUM_BADGE_REBIRTH1B, "Владыка Циклов", 1_000_000_000),
    ("rebirth_milestone_10b", PREMIUM_BADGE_REBIRTH10B, "Бессмертный", 10_000_000_000),
]

# Бейджи за стрик ежедневного бонуса (bonus_streak).
STREAK_MILESTONE_BADGES = [
    ("streak_milestone_7", PREMIUM_BADGE_STREAK7, "Неутомимый", 7),
    ("streak_milestone_30", PREMIUM_BADGE_STREAK30, "Железная воля", 30),
]

# Бейджи за количество успешных крафтов (crafts_done).
CRAFT_MILESTONE_BADGES = [
    ("craft_milestone_10", PREMIUM_BADGE_CRAFT10, "Ремесленник", 10),
    ("craft_milestone_100", PREMIUM_BADGE_CRAFT100, "Мастер-Кузнец", 100),
]

# Бейджи за баланс очков престижа (prestige_points).
PRESTIGE_MILESTONE_BADGES = [
    ("prestige_milestone_10", PREMIUM_BADGE_PRESTIGE10, "Искушённый", 10),
    ("prestige_milestone_100", PREMIUM_BADGE_PRESTIGE100, "Просветлённый", 100),
    ("prestige_milestone_25000", PREMIUM_BADGE_PRESTIGE25000, "Хранитель Мудрости", 25000),
    ("prestige_milestone_50000", PREMIUM_BADGE_PRESTIGE50000, "Вознёсшийся", 50000),
    ("prestige_milestone_100000", PREMIUM_BADGE_PRESTIGE100000, "Владыка Престижа", 100000),
    ("prestige_milestone_250000", PREMIUM_BADGE_PRESTIGE250000, "Трансцендентный", 250000),
    ("prestige_milestone_500000", PREMIUM_BADGE_PRESTIGE500000, "Абсолютный Разум", 500000),
    ("prestige_milestone_1000000", PREMIUM_BADGE_PRESTIGE1000000, "За Гранью Престижа", 1000000),
]

def find_item_key_by_name(query: str, allowed_keys: set):
    """Ищет ключ в ITEMS по русскому названию, ограничиваясь набором allowed_keys
    (бустеры либо предметы). Как find_item_by_name (см. команды «!дать б/п»): сначала точное
    совпадение, иначе — по вхождению подстроки в название.
    Возвращает (key, None) при однозначном совпадении, (None, [варианты]) если совпадений
    несколько, (None, []) если не найдено вообще."""
    q = (query or "").strip().lower()
    if not q:
        return None, []
    for key in allowed_keys:
        if ITEMS[key][1].strip().lower() == q:
            return key, None
    matches = [key for key in allowed_keys if q in ITEMS[key][1].lower()]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        matches.sort(key=lambda k: ITEMS[k][1])
        return None, matches
    return None, []

NON_TRADABLE_ITEMS = {
    "vip_charm",
    "kotyara_amulet", "miku_amulet", "golda", "karambit_gold", "butterfly_legacy",
    "krest_amulet", "fati_amulet", "guitarist_crown", "vilon_amulet", "miku_ring",
    "chaos_orb", "chronos_clock", "chronos_orb",
    "miku_fan_amulet",
    "nogost_coin", "godly_nogost_coin", "craft_coin", "bitcoin",
    "rebirth_coin", "evolution_coin", "awakening_coin",
    "pocket_star", "rebirth_spark", "star_necklace", "blazing_star_necklace",
    "mastery_lover_amulet",
    "god_essence", "koshko_amulet",
}

PASSIVE_ITEMS = {
    "strange_coin",
    "hybrid_amulet", "friendship_essence", "time_particle", "devotion_coin",
    "old_vase", "golden_vase", "godly_vase", "warm_candle",
    "broken_clock", "essence_drop", "comet_shard", "koshko_gift", "ancient_stone", "fate_thread",
    "craft_coin", "bitcoin", "rebirth_coin", "evolution_coin", "awakening_coin",
    "pocket_star", "nano_it",
    "chaos_orb", "chronos_clock", "rebirth_spark",
}

SELL_PRICE = {
    "amulet": 8, "orb": 6, "pill": 5, "candle": 4, "gift": 20, "star": 15, "daily_charm": 10,
    "mk_mgg": 60, "mk_sandsmoon": 18, "mk_fixsahal1": 14, "mk_mk": 22, "mk_panther": 10,
    "mk_vector": 18, "mk_broken": 8, "mk_mary": 20, "mk_veron03": 30, "vip_charm": 50,
    "strange_coin": 12,
    "power_amulet": 40, "galaxy_power_amulet": 90, "galaxy_might_amulet": 150,
    "hybrid_amulet": 200, "friendship_essence": 260, "time_particle": 220,
    "god_essence": 1000, "koshko_amulet": 1400, "devotion_coin": 60, "old_vase": 15, "golden_vase": 120, "godly_vase": 500,
    "lucky_charm": 20, "swift_pill": 18, "party_set": 25, "warm_candle": 14,
    "elemental_charm": 55, "twilight_amulet": 120, "support_totem": 85, "chaos_fang": 130,
    "ice_shard": 15, "ember": 15, "dragon_claw": 22, "paradox_charm": 28, "shadow_mask": 45,
    "tide_wave": 16, "warrior_skull": 24,
    "broken_clock": 8, "essence_drop": 14, "comet_shard": 30, "koshko_gift": 35,
    "ancient_stone": 6, "fate_thread": 32,
    "nogost_coin": 300, "godly_nogost_coin": 900, "craft_coin": 150, "bitcoin": 250,
    "rebirth_coin": 400, "evolution_coin": 350, "awakening_coin": 1200,
    "rebirth_spark": 25, "star_necklace": 180, "blazing_star_necklace": 420,
}

ITEM_FLAT_BONUS = {
    "amulet": 1, "orb": 1, "pill": 1, "candle": 1,
    "star": 2, "gift": 3,
}

CASES = {
    1: {"name": "Базовый кейс", "price": 20, "pool": ["amulet", "orb", "pill", "candle", "gift", "old_vase"]},
    2: {"name": "Кейс Сапортов", "price": 50,
        "pool": ["mk_mgg", "mk_sandsmoon", "mk_fixsahal1", "mk_mk", "mk_panther", "mk_vector",
                 "mk_broken", "mk_mary", "mk_veron03", "strange_coin"]},
    3: {"name": "Кейс Стихий и Крафта", "price": 500,
        "pool": ["ice_shard", "ember", "dragon_claw", "paradox_charm", "shadow_mask", "tide_wave", "warrior_skull",
                 "broken_clock", "essence_drop", "comet_shard", "koshko_gift", "ancient_stone", "fate_thread"]},
}

CASE_SELLABLE_ITEMS = list(dict.fromkeys(
    CASES[1]["pool"] + CASES[2]["pool"] + CASES[3]["pool"]
))
AUTOSELL_PAGE_SIZE = 8

def parse_auto_sell_items(raw: str) -> set:
    return set(x for x in (raw or "").split(",") if x)

def format_auto_sell_items(items: set) -> str:
    return ",".join(sorted(items))

async def apply_case_reward(user_id: int, item_key: str, upgrades: dict,
                             auto_sell_enabled: bool, auto_sell_items: set) -> tuple[int, str]:
    """Выдаёт выпавший из кейса предмет — либо в инвентарь как обычно, либо, если включена
    авто-продажа и этот предмет отмечен в конфиге, сразу продаёт его за монеты.
    Возвращает (получено_монет, текст-пометка для ответа, например ' (авто-продано за 8🪙)')."""
    if auto_sell_enabled and item_key in auto_sell_items and item_key not in NON_TRADABLE_ITEMS:
        sell_lvl = upgrade_level(upgrades, "sell_boost")
        price = SELL_PRICE.get(item_key, 1) + sell_bonus_coins(upgrades)
        await db_exec("UPDATE users SET coins = coins + ? WHERE user_id = ?", (price, user_id))
        return price, f" (авто-продано за {price}🪙)"
    await add_item(user_id, item_key)
    return 0, ""

ALL_PLAYER_AMULETS = [
    "amulet", "mk_mgg", "mk_sandsmoon", "mk_fixsahal1", "mk_mk",
    "mk_panther", "mk_vector", "mk_mary", "mk_veron03",
]

RECIPES = {
    "lucky_charm": {
        "level": 0,
        "ingredients": {"amulet": 1, "orb": 1},
    },
    "swift_pill": {
        "level": 0,
        "ingredients": {"pill": 2, "candle": 1},
    },
    "party_set": {
        "level": 0,
        "ingredients": {"gift": 1, "candle": 1, "pill": 1},
    },
    "warm_candle": {
        "level": 0,
        "ingredients": {"candle": 3},
    },

    "power_amulet": {
        "level": 0,
        "ingredients": {"pill": 1, "mk_broken": 1},
    },
    "elemental_charm": {
        "level": 0,
        "ingredients": {"ice_shard": 2, "ember": 2, "dragon_claw": 1},
    },
    "twilight_amulet": {
        "level": 0,
        "ingredients": {"shadow_mask": 1, "warrior_skull": 2, "tide_wave": 2},
    },
    "support_totem": {
        "level": 0,
        "ingredients": {"mk_fixsahal1": 1, "mk_mk": 1, "mk_vector": 1},
    },
    "chaos_fang": {
        "level": 0,
        "ingredients": {"mk_panther": 1, "mk_veron03": 1, "daily_charm": 1},
    },
    "galaxy_power_amulet": {
        "level": 1,
        "ingredients": {"power_amulet": 1, "candle": 1, "amulet": 1},
    },
    "galaxy_might_amulet": {
        "level": 1,
        "ingredients": {"galaxy_power_amulet": 1, "power_amulet": 1},
    },
    "hybrid_amulet": {
        "level": 2,
        "ingredients": {"orb": 1, "galaxy_might_amulet": 1},
        "needs_all_amulets": True,
    },
    "friendship_essence": {
        "level": 2,
        "ingredients": {"hybrid_amulet": 1, "star": 1, "gift": 1},
    },
    "time_particle": {
        "level": 1,
        "ingredients": {"pill": 1, "orb": 1, "amulet": 1, "candle": 1, "gift": 1},
    },
    "god_essence": {
        "level": 2,
        "ingredients": {"time_particle": 1, "friendship_essence": 1, "mk_broken": 1},
        "craft_points_cost": 1,
    },
    "koshko_amulet": {
        "level": 2,
        "ingredients": {"party_set": 1, "mk_mgg": 1, "god_essence": 1, "time_particle": 1},
    },
    "devotion_coin": {
        "level": 1,
        "ingredients": {"strange_coin": 1},
        "coin_cost": 1000,
    },
    "golden_vase": {
        "level": 1,
        "ingredients": {"old_vase": 1},
        "score_cost": 50000,
    },
    "godly_vase": {
        "level": 2,
        "ingredients": {"golden_vase": 1, "devotion_coin": 1},
        "craft_points_cost": 1,
    },

    "chaos_orb": {
        "level": 1,
        "ingredients": {"orb": 10, "paradox_charm": 2},
    },
    "chronos_clock": {
        "level": 1,
        "ingredients": {"broken_clock": 10, "essence_drop": 1},
        "rebirth_cost": 5,
    },
    "chronos_orb": {
        "level": 3,
        "ingredients": {"chaos_orb": 69, "chronos_clock": 1, "essence_drop": 5},
        "craft_points_cost": 20,
    },

    "mastery_lover_amulet": {
        "level": 3,
        "ingredients": {"chronos_orb": 2},
        "rebirth_cost": 1488,
        "refund_ingredients": {"chronos_orb": 1},
    },

    "miku_fan_amulet": {
        "level": 1,
        "ingredients": {"mk_sandsmoon": 1, "miku_amulet": 1},
    },

    "nogost_coin": {
        "level": 2,
        "ingredients": {"strange_coin": 1},
        "score_cost": 10_000_000,
    },
    "godly_nogost_coin": {
        "level": 3,
        "ingredients": {"nogost_coin": 3, "godly_vase": 3},
    },
    "craft_coin": {
        "level": 3,
        "ingredients": {"strange_coin": 1},
        "craft_points_cost": 50,
    },
    "bitcoin": {
        "level": 2,
        "ingredients": {"strange_coin": 5},
        "coin_cost": 1_000_000,
    },
    "rebirth_coin": {
        "level": 3,
        "ingredients": {"strange_coin": 1},
        "rebirth_cost": 5000,
    },
    "evolution_coin": {
        "level": 2,
        "ingredients": {"strange_coin": 1, "galaxy_might_amulet": 5},
    },
    "awakening_coin": {
        "level": 3,
        "ingredients": {"evolution_coin": 1, "rebirth_coin": 1},
    },

    # ==== Эво-апгрейд: рецепты 15 уровня эволюции ====
    "star_necklace": {
        "level": 1,
        "ingredients": {"star": 2, "mk_broken": 20},
    },
    "blazing_star_necklace": {
        "level": 1,
        "ingredients": {"star_necklace": 1, "rebirth_spark": 5},
        "rebirth_cost": 5,
    },
    "pocket_star": {
        "level": 1,
        "ingredients": {"star": 5},
        "rebirth_cost": 5,
    },
}

UNIQUE_BOOSTER_TIERS = ["power_amulet", "galaxy_power_amulet", "galaxy_might_amulet", "god_essence", "koshko_amulet"]

UNIQUE_LIMIT_OVERRIDES = {
    "power_amulet": {"mek_limit": 15},
    "galaxy_power_amulet": {"galaxy_limit": 1},
    "galaxy_might_amulet": {"galaxy_limit": 1},
    "god_essence": {"mek_limit": 30, "leg_limit": 15, "galaxy_limit": 5, "star_limit": 1},
    "koshko_amulet": {"mek_limit": 30, "leg_limit": 15, "galaxy_limit": 5, "star_limit": 1, "paw_limit": 3},
}
GOD_ESSENCE_TIMER_CUT = 5
GOD_ESSENCE_FARM_SPEED = 5
TIME_PARTICLE_FARM_SPEED = 4
PAW_POINT_MULTIPLIER = 3
ICE_SHARD_SAVE_CHANCE = 0.20

EVOLUTION_COIN_SAVE_PCT = 0.30
REBIRTH_COIN_SAVE_PCT = 0.50
AWAKENING_COIN_SAVE_PCT = 0.70
AWAKENING_COIN_PRESTIGE_CHANCE = 0.01
AWAKENING_COIN_PRESTIGE_AMOUNT = 3
AWAKENING_COIN_BADGE_CHANCE = 0.0001
DRAGON_CLAW_POTION_MULT = 4
TIDE_WAVE_PROC_CHANCE = 0.05

CHAOS_ORB_FARM_CHANCE = 0.02
CHAOS_ORB_FARM_MIN = 1
CHAOS_ORB_FARM_MAX = 10_000_000
CHAOS_ORB_BREW_CUT = 0.90

CHRONOS_ORB_REBIRTH_CHANCE = 0.009
CHRONOS_ORB_REBIRTH_MIN, CHRONOS_ORB_REBIRTH_MAX = 1, 500
CHRONOS_ORB_FARM_MULT_MIN, CHRONOS_ORB_FARM_MULT_MAX = 0.1, 5.0
CHRONOS_ORB_COIN_CHANCE = 0.05
CHRONOS_ORB_COIN_MIN, CHRONOS_ORB_COIN_MAX = 1, 10_000
CHRONOS_ORB_LEGS_CHANCE = 0.02
CHRONOS_ORB_LEGS_MIN, CHRONOS_ORB_LEGS_MAX = 1, 10_000_000
CHRONOS_ORB_NO_CD_CHANCE = 0.07
CHRONOS_ORB_PRESTIGE_CHANCE = 0.01
CHRONOS_ORB_PRESTIGE_MIN, CHRONOS_ORB_PRESTIGE_MAX = 0, 20
CHRONOS_ORB_POTION_CHANCE = 0.01
CHRONOS_ORB_BOOSTER_CHANCE = 0.01
CHRONOS_ORB_BADGE_CHANCE = 0.001
CHRONOS_ORB_STRANGE_COIN_CHANCE = 0.0069
CHRONOS_ORB_OLD_VASE_CHANCE = 0.0069

CHRONOS_BOOST_INTERVAL = 300
CHRONOS_BOOST_MIN, CHRONOS_BOOST_MAX = 10, 400

# ==== 🤖 Любитель Мастерства: пока экипирован, при каждом фарме ног независимо
# проверяются 5 эффектов (несколько могут сработать одновременно за один фарм) ====
MASTERY_LOVER_BITCOIN_CHANCE_CHANCE = 0.005   # шанс временно поднять шанс дропа биткоина
MASTERY_LOVER_BITCOIN_CHANCE_BONUS = 0.001    # +0.1% к шансу дропа биткоина при этом проке
MASTERY_LOVER_CRAFT_CHANCE = 0.01
MASTERY_LOVER_CRAFT_AMOUNT = 15
MASTERY_LOVER_REBIRTH_CHANCE = 0.02
MASTERY_LOVER_REBIRTH_AMOUNT = 200
MASTERY_LOVER_PRESTIGE_CHANCE = 0.015
MASTERY_LOVER_PRESTIGE_AMOUNT = 50
MASTERY_LOVER_NANO_IT_CHANCE = 0.03
NANO_IT_BOOST_PCT_PER_UNIT = 5

GOD_ESSENCE_FLAVOR = f"{PREMIUM_GOD_ESSENCE} Сила бога активирована."
KOSHKO_AMULET_FLAVOR = f"{PREMIUM_KOSHKO_AMULET} Сила кошко-девочки активна."
CHRONOS_ORB_FLAVOR = f"{PREMIUM_CHRONOS_ORB} ХАОС! ХАОС! ХАОС!"
GOD_TIER_LIKE = {"god_essence", "koshko_amulet"}

# ---- Справочные тексты для «помощь бустер <название>» ----
# Источник получения (крафт/номер кейса) определяем автоматически по RECIPES/CASES —
# так описание не разъедется с реальными данными при правке рецептов или пулов кейсов.
# HELP_BOOSTER_SOURCE_OVERRIDE — для бустеров, чей реальный источник не крафт/кейс
# (например, начисляется напрямую кодом за игровое действие) — переопределяет автоопределение.
HELP_BOOSTER_SOURCE_OVERRIDE = {
    "star": "даётся автоматически за каждое перерождение",
    "daily_charm": "выпадает за ежедневный бонус (команда «бонус») на 5-й день серии",
    "vip_charm": "выдаётся при покупке VIP-статуса",
}

def _help_booster_source(key: str) -> str:
    if key in HELP_BOOSTER_SOURCE_OVERRIDE:
        return HELP_BOOSTER_SOURCE_OVERRIDE[key]
    sources = []
    if key in RECIPES:
        sources.append("получается в крафтах")
    for case_num, case_data in CASES.items():
        if key in case_data["pool"]:
            sources.append(f"выпадает из «{case_data['name']}»")
    if not sources:
        return "выдаётся вручную админом или по промокоду"
    return ", ".join(sources)

# Дополнительные «изюминки» для особых бустеров — то, что не считать по одной формуле
# (уникальные слоты, секретные механики, случайный эффект и т.д.).
HELP_BOOSTER_EXTRA = {
    "god_essence": (
        "Это топовый крафтовый бустер уникального яруса — при равном экипе перебивает "
        "все остальные уникальные бустеры (амулеты силы, амулет кошко-девочки — кроме него самого). "
        "Также увеличивает лимиты по ногам/мек-ногам/галактикам и ускоряет кулдаун фермы."
    ),
    "koshko_amulet": (
        "Самый сильный уникальный бустер в игре — перебивает даже Эссенцию Бога. "
        "Даёт максимальные лимиты по ногам/мек-ногам/галактикам/звёздам и открывает лимит «лап»."
    ),
    "power_amulet": "Первая ступень уникальных бустеров — открывает увеличенный лимит по мек-ногам.",
    "guitarist_crown": (
        f"Пассивный эффект пока экипирована: шанс {round(LEG_STEAL_CHANCE * 100)}% при фарме ног "
        "украсть 1 предмет из Кейса 1/2/3 у случайного игрока этого же чата."
    ),
    "vilon_amulet": (
        f"Пассивный эффект пока экипирован: каждые {VILON_TRIGGER_EVERY} фармов ног подряд "
        f"даёт x{VILON_BOOST_MULT} к добыче фермы и ног на {VILON_BOOST_SECONDS} секунд."
    ),
    "galaxy_power_amulet": "Вторая ступень уникальных бустеров — открывает лимит по галактикам.",
    "galaxy_might_amulet": "Третья ступень уникальных бустеров, требуется для дальнейшего крафта Гибридного амулета.",
    "chronos_orb": (
        "Особый бустер: вместо фиксированного процента даёт СЛУЧАЙНЫЙ буст добычи от 10% до 400% "
        "при каждом фарме — иногда почти ничего, иногда джекпот. Дополнительно может случайно "
        "подарить очки перерождения, монеты, ноги, снять кулдаун фермы, дать очки престижа, "
        "зелье, другой бустер, бейдж, странную монету или старую вазу — всё это ХАОС!"
    ),
    "vip_charm": "Мощный бустер, доступный только тем, у кого куплен VIP-статус (см. «помощь бейдж vip»).",
    "star_necklace": "Пассивный эффект пока экипировано: шанс 2.5% при фарме ног выдать случайный предмет из Базового кейса.",
    "blazing_star_necklace": (
        "Пассивный эффект пока экипировано: при фарме ног — шанс 1.7% на 1-15 🉑 очков перерождения "
        "и независимый шанс 1.2% на 1-3 очка престижа."
    ),
    "kotyara_amulet": (
        f"Пассивный эффект пока экипирован: при фарме ног — шанс {round(KOTYARA_BOOST_CHANCE * 100)}% "
        f"включить x{KOTYARA_BOOST_MULT} к добыче на {KOTYARA_BOOST_SECONDS} секунд (поверх обычного буста). "
        f"Дополнительно: {KOTYARA_CAT_SYMBOL_LIMIT}+ символов 😺 в сообщении фарма ног дают x{KOTYARA_CAT_FARM_MULT} "
        f"к итогу, и тогда же шанс {round(KOTYARA_CAT_COIN_CHANCE * 100)}% на {KOTYARA_CAT_COIN_MIN}-{KOTYARA_CAT_COIN_MAX}🪙."
    ),
    "mastery_lover_amulet": (
        "Топовый крафтовый бустер (3 ур. крафта). Пока экипирован, при каждом фарме ног независимо "
        "проверяются 5 эффектов: 0.5% — временно повышает шанс дропа 🟠 Биткоина на этот фарм; "
        "1% — +15💠 очков крафта; 2% — +200🉑 очков перерождения; 1.5% — +50🔮 очков престижа; "
        "3% — +1 предмет nano-IT (пассивно даёт +5% к добыче за каждую единицу в инвентаре)."
    ),
}

def format_help_booster_text(key: str) -> str:
    emoji, name, boost, _ = ITEMS[key]
    lines = [f"+{boost}% к добыче, пока экипирован." if key != "chronos_orb" else "Даёт случайный буст добычи (см. ниже)."]
    lines.append(f"Как получить: {_help_booster_source(key)}.")
    extra = HELP_BOOSTER_EXTRA.get(key)
    if extra:
        lines.append(extra)
    return "\n".join(lines)

# ---- Справочные тексты для «помощь предмет <название>» ----
# Кто использует этот предмет как ингредиент в крафте — считаем по RECIPES, чтобы карта
# «зачем он нужен» не расходилась с реальными рецептами.
_HELP_ITEM_USED_IN = {}
for _target, _recipe in RECIPES.items():
    for _ing in _recipe["ingredients"]:
        _HELP_ITEM_USED_IN.setdefault(_ing, []).append(_target)

# Пассивные эффекты — срабатывают, просто пока предмет лежит в инвентаре (экипировать не нужно).
# Для «сейв-монет» (evolution/rebirth/awakening) используем реальные проценты из констант,
# для остального — текст по факту того, что делает соответствующий apply_*_proc.
HELP_ITEM_EXTRA = {
    "strange_coin": "Пассивный эффект: пока лежит в инвентаре — +5 🪙 к каждому базовому фарму ног.",
    "warm_candle": "Пассивный эффект: пока лежит в инвентаре — +3 🪙 к каждому базовому фарму ног.",
    "devotion_coin": "Пассивный эффект: пока лежит в инвентаре — +15 🪙 к фарму (иногда +35 🪙 с шансом 10%).",
    "old_vase": "Пассивный эффект: при фарме ног — небольшой шанс (~1%) на +1 🉑 очко перерождения.",
    "golden_vase": "Пассивный эффект: при фарме ног — шанс (~6%) на +1 🉑 очко перерождения (сильнее Старой вазы).",
    "godly_vase": (
        "Пассивный эффект: при фарме ног — шанс на очки перерождения по нарастающей, "
        "вплоть до редкого джекпота +200 🉑 (сильнее всех остальных ваз)."
    ),
    "bitcoin": "Пассивный эффект: при базовом фарме ног — очень редкий шанс (0.05%) на джекпот +15 000 000 🪙.",
    "rebirth_coin": "Пассивный эффект: пока лежит в инвентаре — гарантированно +2 🉑 к каждому базовому фарму ног.",
    "craft_coin": "Пассивный эффект: при фарме ног — шанс дать +1 💠 очко крафта.",
    "evolution_coin": f"При эволюции сохраняет {round(EVOLUTION_COIN_SAVE_PCT * 100)}% очков ноги вместо полного обнуления.",
    "rebirth_coin": (
        "Пассивный эффект: пока лежит в инвентаре — гарантированно +2 🉑 к каждому базовому фарму ног. "
        f"Также при перерождении сохраняет {round(REBIRTH_COIN_SAVE_PCT * 100)}% очков ноги."
    ),
    "awakening_coin": (
        f"Самая мощная сейв-монета: сохраняет {round(AWAKENING_COIN_SAVE_PCT * 100)}% очков ноги и "
        "уровня эволюции при ЛЮБОМ сбросе (и эволюция, и перерождение). Есть небольшой шанс "
        "дополнительно дать очки престижа или редкий бейдж."
    ),
    "chaos_orb": (
        "Пассивный эффект: пока лежит в инвентаре (экипировать не нужно) — "
        f"режет время варки зелий на {round(CHAOS_ORB_BREW_CUT * 100)}% и даёт независимый шанс "
        f"{round(CHAOS_ORB_FARM_CHANCE * 100)}% при фарме ног поймать бонус-фарму "
        f"({CHAOS_ORB_FARM_MIN}-{CHAOS_ORB_FARM_MAX} очков ноги). Также крафт-сырьё для Хвоста Джевила."
    ),
    "chronos_clock": (
        "Пассивный эффект: пока лежит в инвентаре (экипировать не нужно) — время action-зелий "
        "не тикает, пока предмет в инвентаре (зелье не истекает, доедает своё после расхода/продажи предмета). "
        "Также крафт-сырьё для Хвоста Джевила."
    ),
    "rebirth_spark": "Даётся автоматически при достижении 5 уровня эволюции. Крафт-сырьё для Ожерелья пылающей звезды.",
    "pocket_star": (
        "Пассивный эффект: пока лежит в инвентаре (экипировать не нужно) — команда «ферма» "
        f"даёт в {POCKET_STAR_FARM_CMD_MULT}x больше и гарантированно "
        f"+{POCKET_STAR_FARM_CMD_REBIRTH_RANGE[0]}-{POCKET_STAR_FARM_CMD_REBIRTH_RANGE[1]} 🉑 очков перерождения. "
        f"Обычная фарма ног (🦵/🦿... в чате) — x{POCKET_STAR_LEG_FARM_MULT}."
    ),
    "nano_it": (
        f"Пассивный эффект: пока лежит в инвентаре (экипировать не нужно) — даёт +{NANO_IT_BOOST_PCT_PER_UNIT}% "
        "к добыче за КАЖДУЮ единицу в инвентаре (например, 3 шт. = +15%, суммируется с остальными бустерами). "
        "Выпадает случайно от 🤖 Любителя Мастерства."
    ),
}

def _help_item_source(key: str) -> str:
    if key in RECIPES:
        return "получается в крафтах"
    for case_num, case_data in CASES.items():
        if key in case_data["pool"]:
            return f"выпадает из «{case_data['name']}»"
    return "выдаётся вручную админом или по промокоду"

def format_help_item_text(key: str) -> str:
    lines = [f"Как получить: {_help_item_source(key)}."]

    used_in = _HELP_ITEM_USED_IN.get(key)
    if used_in:
        used_names = ", ".join(esc(ITEMS[u][1]) for u in used_in if u in ITEMS)
        lines.append(f"Используется как ингредиент в крафте: {used_names}.")

    extra = HELP_ITEM_EXTRA.get(key)
    if extra:
        lines.append(extra)

    if not used_in and not extra:
        lines.append("Коллекционный предмет — можно продать или уничтожить, прямого эффекта не даёт.")

    return "\n".join(lines)

def get_active_unique_tier(active_items):
    """Самый сильный уникальный крафт-бустер среди экипированных, либо None."""
    equipped = set(_normalize_active_items(active_items))
    best = None
    for key in UNIQUE_BOOSTER_TIERS:
        if key in equipped:
            best = key
    return best

def active_farm_limits(active_items, prestige_upgrades: dict = None) -> dict:
    """Лимиты за сообщение (🦵/🦿/🌌/⭐️) с учётом сильнейшего уникального бустера
    + постоянных бонусов дерева престижа (p_legs/p_mek, см. PRESTIGE_UPGRADES)
    + плоского бонуса от 🔥 Уголька (+1 к лимиту 🦵, складывается с чем угодно)
    + плоского бонуса от 🔶 Монеты Бога Ногости (+15 к лимиту 🦵, только пока экипирована)."""
    tier = get_active_unique_tier(active_items)
    overrides = UNIQUE_LIMIT_OVERRIDES.get(tier, {})
    prestige_upgrades = prestige_upgrades or {}
    leg_bonus = prestige_bonus(prestige_upgrades, "p_legs")
    mek_bonus = prestige_bonus(prestige_upgrades, "p_mek")
    equipped = set(_normalize_active_items(active_items))
    if "ember" in equipped:
        leg_bonus += 1
    if "godly_nogost_coin" in equipped:
        leg_bonus += 15
    return {
        "mek_limit": overrides.get("mek_limit", MEK_LIMIT) + mek_bonus,
        "leg_limit": overrides.get("leg_limit", LEG_LIMIT) + leg_bonus,
        "galaxy_limit": overrides.get("galaxy_limit", 0),
        "star_limit": overrides.get("star_limit", 0),
        "paw_limit": overrides.get("paw_limit", 0),
    }

def recipe_missing_ingredients(inventory_map: dict, coins: int, score: int, recipe: dict,
                                prestige_upgrades: dict = None, craft_points: int = 0, rebirth_points: int = 0) -> list:
    """Список недостающих требований рецепта в виде читаемых строк. Пустой список = всё есть."""
    missing = []
    for ing_key, qty in recipe.get("ingredients", {}).items():
        have = inventory_map.get(ing_key, 0)
        if have < qty:
            name = ITEMS[ing_key][1]
            missing.append(f"{name}: {have}/{qty}")
    if recipe.get("needs_all_amulets"):
        for ing_key in ALL_PLAYER_AMULETS:
            if inventory_map.get(ing_key, 0) < 1:
                missing.append(f"{ITEMS[ing_key][1]}: 0/1")
    coin_cost = craft_coin_cost_with_discount(recipe.get("coin_cost", 0), prestige_upgrades)
    if coin_cost and coins < coin_cost:
        missing.append(f"Монеты: {coins}/{coin_cost} 🪙")
    score_cost = recipe.get("score_cost", 0)
    if score_cost and score < score_cost:
        missing.append(f"Очки ног: {score}/{score_cost}")
    craft_points_cost = recipe.get("craft_points_cost", 0)
    if craft_points_cost and craft_points < craft_points_cost:
        missing.append(f"Очки крафта: {craft_points}/{craft_points_cost} 💠")
    rebirth_cost = recipe.get("rebirth_cost", 0)
    if rebirth_cost and rebirth_points < rebirth_cost:
        missing.append(f"Очки перерождения: {rebirth_points}/{rebirth_cost} 🉑")
    return missing

def format_recipe_requirements(recipe: dict) -> str:
    parts = [f"{qty}x {ITEMS[k][1]}" for k, qty in recipe.get("ingredients", {}).items()]
    if recipe.get("needs_all_amulets"):
        parts.append("по 1x каждого амулета игрока (кроме VIP и Сломанного)")
    if recipe.get("coin_cost"):
        parts.append(f"{recipe['coin_cost']} 🪙")
    if recipe.get("score_cost"):
        parts.append(f"{recipe['score_cost']} очков ног")
    if recipe.get("craft_points_cost"):
        parts.append(f"{recipe['craft_points_cost']} 💠")
    if recipe.get("rebirth_cost"):
        parts.append(f"{recipe['rebirth_cost']} 🉑")
    result = " + ".join(parts)
    if recipe.get("refund_ingredients"):
        refund_parts = [f"{qty}x {ITEMS[k][1]}" for k, qty in recipe["refund_ingredients"].items()]
        result += f" (вернётся: {', '.join(refund_parts)})"
    return result

REBIRTH_MIN_EVO = 5
REBIRTH_EVO_STEP = 3
REBIRTH_POINTS_PER_STEP = 2
REBIRTH_HARDNESS_STEP = 0.125
PRESTIGE_PER_REBIRTH = 1
PRESTIGE_PER_ULTRA_REBIRTH = 50

def _linear_cost(base: int, step: int):
    return lambda level: base + step * (level - 1)

def _per_n_levels_cost(base: int, step: int, n: int):
    return lambda level: base + step * ((level - 1) // n)

def _percent_growth_cost(base: int, growth_pct: float, start_level: int):
    """Цена уровня start_level равна base, а для каждого следующего уровня растёт на
    growth_pct% относительно предыдущего (сложный процент от start_level)."""
    factor = 1 + growth_pct / 100
    return lambda level: round(base * (factor ** (level - start_level)))

def _tiered_cost(old_fn, new_fn, threshold_level: int):
    """До threshold_level (не включая) цена считается по old_fn, начиная с threshold_level —
    по new_fn. Используется для веток, где ТЗ меняет формулу цены с определённого уровня
    (напр. Ферма ДОБЫЧА: 1-9 ур — старая линейная цена, 10+ ур — новая с ростом 15%)."""
    return lambda level: new_fn(level) if level >= threshold_level else old_fn(level)

UPGRADES = {
    "farm_yield": {
        "name": "Ферма ДОБЫЧА",
        "desc": "+10% к добыче фермы за лвл (с 10 ур: +1.5х к ферме за апгрейд, считая от 10 ур)",
        "max_level": 10,
        "max_level_by_upgrader": {2: 15, 3: 20},
        "cost": _tiered_cost(_linear_cost(1, 1), _percent_growth_cost(500, 15, 10), 10),
        "extra_cost": lambda level: ("coins", round(5000 * (1.15 ** (level - 10)))) if level >= 10 else None,
        "category": 1,
    },
    "farm_cd": {
        "name": "Ферма КД",
        "desc": "-2 мин к КД фермы за лвл (с 5 ур: -20 сек к КД фермы за апгрейд)",
        "max_level": 5,
        "max_level_by_upgrader": {2: 8, 3: 13},
        "cost": _tiered_cost(_linear_cost(1, 2), _percent_growth_cost(1500, 35, 5), 5),
        "extra_cost": lambda level: ("gold_coin", round(150 * (1.35 ** (level - 5)))) if level >= 5 else None,
        "category": 1,
    },
    "auto_farm_legs": {
        "name": "Авто-Ферма НОГИ",
        "desc": "1:10 ног/мин · 2:100 ног/30с · 3:1000 ног/10с · 4:10000 ног/5с · 5-6: x1.5 добычи за уровень (от 4 ур)",
        "max_level": 3,
        "max_level_by_upgrader": {2: 4, 3: 6},
        "cost": _tiered_cost(
            lambda level: 7300 if level == 4 else _linear_cost(1, 4)(level),
            _percent_growth_cost(15000, 40, 5), 5,
        ),
        "extra_cost": lambda level: (
            ("diamond_coin", 10) if level == 4
            else (("diamond_coin", round(10 * (1.40 ** (level - 5)))) if level >= 5 else None)
        ),
        "category": 1,
    },
    "auto_farm_coins": {
        "name": "Авто-Ферма КОИНЫ",
        "desc": "1:1 коин/5мин · 2:5 коин/5мин · 3:10 коин/3мин · 4:100 коин/1мин · 5-6: x1.5 добычи за уровень (от 4 ур)",
        "max_level": 3,
        "max_level_by_upgrader": {2: 4, 3: 6},
        "cost": _tiered_cost(
            lambda level: 5000 if level == 4 else _linear_cost(1, 2)(level),
            _percent_growth_cost(10000, 40, 5), 5,
        ),
        "extra_cost": lambda level: (
            ("prestige_points", 7000) if level == 4
            else (("prestige_points", round(7000 * (1.40 ** (level - 5)))) if level >= 5 else None)
        ),
        "category": 1,
    },
    "booster": {
        "name": "Бустер",
        "desc": "+5% буст ко всему за лвл",
        "max_level": 50,
        "max_level_by_upgrader": {2: 75, 3: 85},
        "cost": _tiered_cost(_per_n_levels_cost(1, 1, 3), _percent_growth_cost(400, 5, 50), 50),
        "category": 2,
    },
    "equip_slots": {
        "name": "Слоты экипировки",
        "desc": "+1 слот экипировки за лвл (база 1, макс 5 слотов на 4 лвл)",
        "max_level": 2,
        "max_level_by_upgrader": {2: 3, 3: 4},
        "cost": lambda level: (30000 if level == 4 else 20000) if level >= 3 else _linear_cost(5, 5)(level),
        "extra_cost": lambda level: (
            ("diamond_coin", 100) if level == 3
            else (("diamond_coin", 200) if level == 4 else None)
        ),
        "category": 2,
    },
    "discount": {
        "name": "Скидка",
        "desc": "-10% к цене кейсов за лвл (ограничено 70% суммарно)",
        "max_level": 3,
        "max_level_by_upgrader": {2: 5, 3: 7},
        "cost": _tiered_cost(_linear_cost(1, 1), _percent_growth_cost(1000, 10, 3), 3),
        "category": 2,
    },
    "sell_boost": {
        "name": "Продажа",
        "desc": "+2 коина к продаже за лвл (3 лвл: 1% шанс +1 🉑 при продаже)",
        "max_level": 3,
        "max_level_by_upgrader": {2: 4, 3: 7},
        "cost": lambda level: 2000 + 1000 * (level - 4) if level >= 4 else _linear_cost(2, 2)(level),
        "category": 2,
    },
    "crafts": {
        "name": "Крафты", "desc": "Открывает уровни рецептов крафта (0/1/2/3) за 🉑",
        "max_level": CRAFT_MAX_LEVEL,
        "cost": lambda level: 5000 if level == CRAFT_MAX_LEVEL else _linear_cost(15, 20)(level),
        "category": 3,
        "extra_cost": lambda level: (
            ("craft_points", 10) if level == CRAFT_MAX_LEVEL else None
        ),
    },
    "brew_speed": {
        "name": "Скорость готовки зелья",
        "desc": "-10% времени варки зелья за лвл (не быстрее 10% от базового времени)",
        "max_level": 5,
        "max_level_by_upgrader": {2: 7, 3: 9},
        "cost": lambda level: 3000 + 1500 * (level - 6) if level >= 6 else _linear_cost(3, 3)(level),
        "extra_cost": lambda level: ("gold_coin", 500 + 250 * (level - 6)) if level >= 6 else None,
        "category": 3,
    },
    "brew_duration": {
        "name": "Длительность зелья",
        "desc": "+20% к длительности эффекта зелий за лвл",
        "max_level": 3,
        "max_level_by_upgrader": {2: 4, 3: 6},
        "cost": lambda level: 5000 + 5000 * (level - 4) if level >= 4 else _linear_cost(5, 5)(level),
        "extra_cost": lambda level: ("coins", 50000 * (level - 3)) if level >= 4 else None,
        "category": 3,
    },
    "exchanger": {
        "name": "Обменник",
        "desc": "1 лвл: открывает обмен на 🌕 гкоин · 2 лвл: открывает обмен на 💎 акоин · "
                "3 лвл: открывает обмен очкп→престиж (команда «обменять престиж <кол-во>», курс 1 🔮 = 30 🉑)",
        "max_level": 2,
        "max_level_by_upgrader": {2: 3},
        "cost": lambda level: 50000 if level == 3 else (100 if level == 1 else 10000),
        "extra_cost": lambda level: (
            [("prestige_points", 50000), ("diamond_coin", 50)] if level == 3
            else (("coins", 10000) if level == 1 else ("gold_coin", 10000))
        ),
        "category": 3,
    },
    # ==== Абсолютно новые прокачки, категория 4 — открывается на 2 ур. апгрейдера ====
    "auto_farm_rebirth": {
        "name": "Авто-ферма очкп",
        "desc": "Пассивно копит 🉑 очки перерождения со временем. 1:1 очкп/5мин · 2:10 очкп/3мин · 3:15 очкп/2мин",
        "max_level": 2,
        "max_level_by_upgrader": {3: 3},
        "cost": _percent_growth_cost(2500, 50, 1),
        "category": 4,
    },
    "transfer": {
        "name": "Передача",
        "desc": "Открывает передачу 🉑 очков перерождения другому игроку (команда «дать очкп <количество>»)",
        "max_level": 1,
        "cost": lambda level: 15000,
        "extra_cost": lambda level: [("craft_points", 10), ("diamond_coin", 10)],
        "category": 4,
    },
    "potion_booster": {
        "name": "Бустер зелья",
        "desc": "Усиливает эффекты зелья скорости и зелья удачи. 1:x1.2 усиления · 2:x2 усиления · 3:x3 усиления",
        "max_level": 2,
        "max_level_by_upgrader": {3: 3},
        "cost": _percent_growth_cost(500, 400, 1),  # рост x5 за уровень = +400%
        "category": 4,
    },
    "auto_farm_gold_coin": {
        "name": "Авто-ферма ГКОИН",
        "desc": "Пассивно копит 🌕 голд коины со временем. 1:1 гкоин/1мин · 2:5 гкоин/30сек · 3:8 гкоин/20сек",
        "max_level": 2,
        "max_level_by_upgrader": {3: 3},
        "cost": _percent_growth_cost(6000, 30, 1),
        "extra_cost": lambda level: ("gold_coin", round(5000 * (1.30 ** (level - 1)))),
        "category": 4,
    },
    # ==== Апдейт 2.6, категория 5 — открывается на 3 ур. апгрейдера ====
    "echo_farm": {
        "name": "Эхо фарма",
        "desc": "Шанс задвоить добычу за фарм ног. 1:5% · 2:10% · 3:15%",
        "max_level": 3,
        "cost": _percent_growth_cost(3000, 60, 1),
        "category": 5,
    },
    "coin_magnet": {
        "name": "Магнит монет",
        "desc": "Прямая прибавка монет к каждому фарму ног (без шанса). 1:+3🪙 · 2:+7🪙 · 3:+12🪙",
        "max_level": 3,
        "cost": _percent_growth_cost(2000, 50, 1),
        "category": 5,
    },
    "fast_exchange": {
        "name": "Быстрый обмен",
        "desc": "Снижает курс обмена очкп→престиж (обменник 3 лвл). База 30🉑=1🔮. 1:27🉑 · 2:24🉑 · 3:20🉑",
        "max_level": 3,
        "cost": _percent_growth_cost(4000, 60, 1),
        "extra_cost": lambda level: ("diamond_coin", 20),
        "category": 5,
    },
    "case_collector": {
        "name": "Коллекционер кейсов",
        "desc": "Шанс получить доп. предмет при открытии кейса (кейс всё равно тратится). 1:3% · 2:6% · 3:10%",
        "max_level": 3,
        "cost": _percent_growth_cost(3500, 55, 1),
        "category": 5,
    },
}
UPGRADE_ORDER = list(UPGRADES.keys())
UPGRADE_CATEGORIES = {1: "🌾 Ферма", 2: "🎒 Экономика", 3: "🔨 Крафты и прочее", 4: "🔺 Новые прокачки", 5: "✨ Апдейт 2.6"}
UPGRADE_EXTRA_CURRENCY_LABELS = {
    "craft_points": "💠 очков крафта",
    "coins": "🪙 монет",
    "gold_coin": "🌕 гкоин",
    "diamond_coin": "💎 акоин",
    "prestige_points": "🔮 престижа",
}

# ==== Уровень апгрейдера (мета-прокачка над всем деревом апгрейдов) ====
# Когда ВСЕ ветки во ВСЕХ открытых на данный момент категориях прокачаны до максимума,
# в меню появляется отдельная кнопка "прокачать апгрейдер" — платный переход на
# следующий уровень апгрейдера (1..UPGRADER_LEVEL_MAX), который открывает новые
# max_level у части веток (см. UPGRADES) и/или новые категории (см. UPGRADER_UNLOCK_CATEGORY).
UPGRADER_LEVEL_MAX = 5
UPGRADER_LEVEL_UP_COST = {
    # текущий уровень -> цена перехода на следующий, в 💎 акоин (diamond_coin)
    1: 500,
    2: 2000,
    3: 5000,
    4: 10000,
}
# С какого уровня апгрейдера открывается категория (вкладка) — 4 (ветки 13-16) на 2 ур.
# апгрейдера, 5 (ветки 17-20, апдейт 2.6) на 3 ур. апгрейдера.
UPGRADER_UNLOCK_CATEGORY = {
    4: 2,
    5: 3,
}

def upgrader_next_cost(current_level: int):
    """Цена перехода на следующий уровень апгрейдера (в 💎 акоин), либо None на максимуме."""
    if current_level >= UPGRADER_LEVEL_MAX:
        return None
    return UPGRADER_LEVEL_UP_COST.get(current_level)

def unlocked_categories(upgrader_lvl: int) -> list:
    """Список номеров категорий (вкладок), доступных при данном уровне апгрейдера."""
    cats = [1, 2, 3]
    for cat, need_lvl in UPGRADER_UNLOCK_CATEGORY.items():
        if upgrader_lvl >= need_lvl and cat not in cats:
            cats.append(cat)
    return sorted(cats)

def all_upgrades_maxed(upgrades: dict, upgrader_lvl: int) -> bool:
    """True, если все ветки во всех НА ДАННЫЙ МОМЕНТ открытых категориях прокачаны до максимума
    (максимум считается с учётом уже достигнутого upgrader_lvl — см. effective_max_level).
    Ветки с cfg['wip'] (уровни 3-5 апгрейдера без функционала) не имеют цены (upgrade_next_cost
    вернёт None из-за cost is None/wip), но всё равно проверяются наравне — то есть их тоже
    'нужно' формально докупить до max_level, если у них не выставлен wip. Ветки с cfg.get('wip')
    считаются готовыми сразу (не блокируют переход)."""
    cats = set(unlocked_categories(upgrader_lvl))
    for key in UPGRADE_ORDER:
        cfg = UPGRADES[key]
        if cfg["category"] not in cats:
            continue
        if cfg.get("wip"):
            continue
        level = upgrade_level(upgrades, key)
        if level < effective_max_level(key, upgrader_lvl):
            return False
    return True

def upgrader_can_level_up(upgrades: dict, upgrader_lvl: int) -> bool:
    """Можно ли показывать кнопку прокачки уровня апгрейдера прямо сейчас."""
    if upgrader_lvl >= UPGRADER_LEVEL_MAX:
        return False
    return all_upgrades_maxed(upgrades, upgrader_lvl)

def _prestige_cost(base: int, growth: float):
    return lambda level: round(base * (growth ** (level - 1)))

def _echelon_bonus(level: int) -> int:
    """Общий паттерн разреженности: чем выше уровень, тем реже даётся следующая "ступенька" эффекта.
    Уровни 1-5: +1 ступень за уровень. С 5 ур эшелоны удваиваются бесконечно — границы [5,10) шаг 2,
    [10,20) шаг 4, [20,40) шаг 8, [40,80) шаг 16 и т.д. Проверено: с 5 ур нужно пройти 2 уровня ради
    следующей ступени (5→7), с 10 ур — 4 уровня (10→14). Замкнутая формула — быстрая даже для
    гигантских уровней (после Ультра перерождения), не цикл по каждому уровню."""
    if level <= 0:
        return 0
    if level <= 5:
        return level
    bonus = 5
    start = 5
    gap = 2
    while start < level:
        end = start * 2
        span = min(level, end) - start
        bonus += span // gap
        if level >= end:
            start = end
            gap *= 2
        else:
            break
    return bonus

def _milestone_bonus(milestones: list):
    """Особая кривая для 'штучных' веток (напр. Слоты: +1 на 1 ур, следующий +1 только на 100 ур).
    milestones — отсортированный список уровней, на которых бонус увеличивается на 1.
    Использует bisect — быстро даже для больших списков милстоунов."""
    def _fn(level: int) -> int:
        return bisect.bisect_right(milestones, level)
    return _fn

def _per_level_bonus(level: int) -> int:
    """Прямая (не разреженная) кривая: каждый купленный уровень сразу даёт +1 к эффекту.
    Используется только для 'Слоты' — это очень мощный бонус, поэтому взамен разреженности
    его цена растёт в 10 раз за уровень (см. _prestige_cost(2, 10) в p_slots)."""
    return max(0, level)

PRESTIGE_UPGRADES = {
    "p_legs": {
        "name": "Обычные ноги", "emoji": "🦵",
        "desc": "+1 к лимиту 🦵",
        "cost": _prestige_cost(1, 1.08),
        "bonus": _echelon_bonus,
    },
    "p_mek": {
        "name": "Робо ноги", "emoji": "🦿",
        "desc": "+1 к лимиту 🦿",
        "cost": _prestige_cost(1, 1.09),
        "bonus": _echelon_bonus,
    },
    "p_slots": {
        "name": "Слоты", "emoji": "🎒",
        "desc": "+1 слот экипировки за КАЖДЫЙ уровень (цена растёт x10 за уровень — самая дорогая ветка)",
        "cost": _prestige_cost(2, 10.0),
        "bonus": _per_level_bonus,
    },
    "p_farm_speed": {
        "name": "Скорость фарма", "emoji": "⏱️",
        "desc": "-1% к КД фермы",
        "cost": _prestige_cost(1, 1.08),
        "bonus": _echelon_bonus,
    },
    "p_farm_yield": {
        "name": "Добыча", "emoji": "📈",
        "desc": "+0.5% к множителю фермы",
        "cost": _prestige_cost(1, 1.08),
        "bonus": _echelon_bonus,
    },
    "p_brew_speed": {
        "name": "Скорость варки", "emoji": "🔥",
        "desc": "-2% времени варки зелий",
        "cost": _prestige_cost(1, 1.08),
        "bonus": _echelon_bonus,
    },
    "p_craft_discount": {
        "name": "Скидка крафта", "emoji": "🔨",
        "desc": "-1% к стоимости крафта",
        "cost": _prestige_cost(1, 1.08),
        "bonus": _echelon_bonus,
    },
    "p_echo": {
        "name": "Эхо", "emoji": "🔮",
        "desc": "+1% шанс бонус-очка перерождения",
        "cost": _prestige_cost(1, 1.10),
        "bonus": _echelon_bonus,
    },
}
PRESTIGE_ORDER = list(PRESTIGE_UPGRADES.keys())
PRESTIGE_PAGE_SIZE = 4

BADGES_PAGE_SIZE = 6

POTIONS = {
    "potion_speed": {
        "emoji": "🧪⚡", "name": "Зелье ускорения",
        "desc": "x2 к добыче фермы",
        "effect": "farm_x2",
        "brew_cost": 40, "brew_seconds": 600,
        "duration_seconds": 1800,
    },
    "potion_luck": {
        "emoji": "🧪🍀", "name": "Зелье удачи",
        "desc": "x2 к шансу проков ваз и Эссенции Бога",
        "effect": "luck_x2",
        "brew_cost": 50, "brew_seconds": 900,
        "duration_seconds": 1800,
    },
    "potion_haste": {
        "emoji": "🧪🌀", "name": "Зелье без КД",
        "desc": "Следующие 3 фарма без ожидания кулдауна",
        "effect": "no_cd",
        "brew_cost": 60, "brew_seconds": 1200,
        "charges": 3,
    },
    "potion_evo_reset": {
        "emoji": "🧪🌑", "name": "Зелье сброса эволюции",
        "desc": "Мгновенно: сбрасывает уровень эволюции и усложнение от неё к 0 (остальной прогресс не трогает)",
        "effect": "reset_evo",
        "instant": True,
        "brew_cost": 5000, "brew_seconds": 7200,
        "extra_cost": [("star", 3)],
    },
    "potion_rebirth_reset": {
        "emoji": "🧪🌘", "name": "Зелье сброса перерождения",
        "desc": "Мгновенно: сбрасывает счётчик перерождений и усложнение от них к 0 (остальной прогресс не трогает)",
        "effect": "reset_rebirth",
        "instant": True,
        "brew_cost": 8000, "brew_seconds": 9000,
        "extra_cost": [("star", 5), ("amulet", 1)],
    },
    "potion_debuff": {
        "emoji": "🧪🌚", "name": "Зелье дебаффа",
        "desc": "Мгновенно: снимает 50% скрытого усложнения от эволюции и перерождения за каждое использование",
        "effect": "hardness_debuff",
        "instant": True,
        "brew_cost": 50000, "brew_seconds": 93600,
        "extra_cost": [("star", 10), ("amulet", 3), ("orb", 1), ("rebirth_points", 500)],
    },
    "potion_rebirth_farm": {
        "emoji": "🧪🉑", "name": "Зелье валюты перерождения",
        "desc": "Гарантированно +1 🉑 очко перерождения за каждый фарм ног, пока действует",
        "effect": "rebirth_on_farm",
        "brew_cost": 750, "brew_seconds": 1500,
        "duration_seconds": 300,
    },
}
POTION_ORDER = list(POTIONS.keys())
NO_CD_CHARGES_KEY = "potion_haste"

AUTO_FARM_LEGS_RATES = {1: (10, 60), 2: (100, 30), 3: (1000, 10), 4: (10000, 5), 5: (15000, 5), 6: (22500, 5)}
AUTO_FARM_COINS_RATES = {1: (1, 300), 2: (5, 300), 3: (10, 180), 4: (100, 60), 5: (150, 60), 6: (225, 60)}
AUTO_FARM_REBIRTH_RATES = {1: (1, 300), 2: (10, 180), 3: (15, 120)}  # (очкп, за сколько секунд)
AUTO_FARM_GOLD_COIN_RATES = {1: (1, 60), 2: (5, 30), 3: (8, 20)}  # (гкоин, за сколько секунд)

AMOUNT = r"(\d+(?:\.\d+)?к{0,4})"
_AMOUNT_TOKEN_RE = re.compile(r"^\d+(?:\.\d+)?к{0,4}$", re.IGNORECASE)

ADMIN_GIVE_LEGS_RE = re.compile(rf"^!дать ног {AMOUNT}(\s+себе)?$", re.IGNORECASE)
ADMIN_TAKE_LEGS_RE = re.compile(rf"^!снять ноги (?:{AMOUNT}|все)(\s+себе)?$", re.IGNORECASE)
ADMIN_GIVE_EVO_RE = re.compile(rf"^!дать эво {AMOUNT}(\s+себе)?$", re.IGNORECASE)
ADMIN_TAKE_EVO_RE = re.compile(rf"^!снять эво (?:{AMOUNT}|все)(\s+себе)?$", re.IGNORECASE)
ADMIN_GIVE_COIN_RE = re.compile(rf"^!дать коин {AMOUNT}(\s+себе)?$", re.IGNORECASE)
ADMIN_TAKE_COIN_RE = re.compile(rf"^!снять коин (?:{AMOUNT}|все)(\s+себе)?$", re.IGNORECASE)
ADMIN_GIVE_BOOST_RE = re.compile(r"^!дать б (.+?)(\s+себе)?$", re.IGNORECASE)
ADMIN_TAKE_BOOST_RE = re.compile(r"^!снять б (.+?)(\s+себе)?$", re.IGNORECASE)
ADMIN_GIVE_ITEM_RE = re.compile(r"^!дать п (.+?)(\s+себе)?$", re.IGNORECASE)
ADMIN_TAKE_ITEM_RE = re.compile(r"^!снять п (.+?)(\s+себе)?$", re.IGNORECASE)
ADMIN_GIVE_VIP_RE = re.compile(rf"^!дать вип {AMOUNT}(\s+себе)?$", re.IGNORECASE)
ADMIN_TAKE_VIP_RE = re.compile(r"^!снять вип(\s+себе)?$", re.IGNORECASE)
ADMIN_RESET_RE = re.compile(r"^!сбросить(\s+себе)?$", re.IGNORECASE)
ADMIN_GIVE_REBIRTH_RE = re.compile(rf"^!дать очкп {AMOUNT}(\s+себе)?$", re.IGNORECASE)
ADMIN_TAKE_REBIRTH_RE = re.compile(rf"^!снять очкп (?:{AMOUNT}|все)(\s+себе)?$", re.IGNORECASE)
ADMIN_GIVE_CRAFT_RE = re.compile(rf"^!дать (?:крафт|очкк) {AMOUNT}(\s+себе)?$", re.IGNORECASE)
ADMIN_TAKE_CRAFT_RE = re.compile(rf"^!снять (?:крафт|очкк) (?:{AMOUNT}|все)(\s+себе)?$", re.IGNORECASE)
ADMIN_GIVE_GOLD_COIN_RE = re.compile(rf"^!дать (?:гкоин|голдкоин) {AMOUNT}(\s+себе)?$", re.IGNORECASE)
ADMIN_TAKE_GOLD_COIN_RE = re.compile(rf"^!снять (?:гкоин|голдкоин) (?:{AMOUNT}|все)(\s+себе)?$", re.IGNORECASE)
ADMIN_GIVE_DIAMOND_COIN_RE = re.compile(rf"^!дать (?:акоин|алмкоин|алмазкоин) {AMOUNT}(\s+себе)?$", re.IGNORECASE)
ADMIN_TAKE_DIAMOND_COIN_RE = re.compile(rf"^!снять (?:акоин|алмкоин|алмазкоин) (?:{AMOUNT}|все)(\s+себе)?$", re.IGNORECASE)
ADMIN_GIVE_PRESTIGE_RE = re.compile(rf"^!дать престиж {AMOUNT}(\s+себе)?$", re.IGNORECASE)
ADMIN_TAKE_PRESTIGE_RE = re.compile(rf"^!снять престиж (?:{AMOUNT}|все)(\s+себе)?$", re.IGNORECASE)
ADMIN_GIVE_LEGS_LVL_RE = re.compile(r"^!дать ноги лвл(\d+)(\s+себе)?$", re.IGNORECASE)
ADMIN_GIVE_TITLE_RE = re.compile(r"^!дать титул (\S+)(\s+себе)?$", re.IGNORECASE)
ADMIN_TAKE_TITLE_RE = re.compile(r"^!снять титул (\S+)(\s+себе)?$", re.IGNORECASE)

PEER_GIVE_LEGS_RE = re.compile(rf"^дать ног {AMOUNT}$", re.IGNORECASE)
PEER_GIVE_COIN_RE = re.compile(rf"^дать коин {AMOUNT}$", re.IGNORECASE)

EXCHANGE_RE = re.compile(rf"^обменять {AMOUNT}$", re.IGNORECASE)
REVERSE_EXCHANGE_RE = re.compile(rf"^обменять {AMOUNT} коин$", re.IGNORECASE)
CRAFT_EXCHANGE_RE = re.compile(rf"^обменять {AMOUNT} (?:крафт|очкк)$", re.IGNORECASE)
CRAFT_EXCHANGE_TO_RE = re.compile(rf"^обменять (?:крафт|очкк) {AMOUNT}$", re.IGNORECASE)
GOLD_COIN_EXCHANGE_RE = re.compile(rf"^обменять (?:гкоин|голдкоин) {AMOUNT}$", re.IGNORECASE)
DIAMOND_COIN_EXCHANGE_RE = re.compile(rf"^обменять (?:акоин|алмкоин|алмазкоин) {AMOUNT}$", re.IGNORECASE)
PRESTIGE_EXCHANGE_RE = re.compile(rf"^обменять престиж {AMOUNT}$", re.IGNORECASE)
CASE_NUM_RE = re.compile(r"^кейс (\d+)$", re.IGNORECASE)
INFO_RE = re.compile(r"^инфо\s+@?(\w+)$", re.IGNORECASE)
NICK_SET_RE = re.compile(r"^\+ник\s+(.+)$", re.IGNORECASE)
NICK_CLEAR_RE = re.compile(r"^-ник$", re.IGNORECASE)
ADMIN_SET_LEGS_RE = re.compile(rf"^!установить ног {AMOUNT}(\s+себе)?$", re.IGNORECASE)
ADMIN_SET_EVO_RE = re.compile(rf"^!установить эво {AMOUNT}(\s+себе)?$", re.IGNORECASE)
ADMIN_RESET_CD_RE = re.compile(r"^!сброс кд(\s+себе)?$", re.IGNORECASE)
ADMIN_RESET_BONUS_RE = re.compile(r"^!сброс бонус(\s+себе)?$", re.IGNORECASE)
ADMIN_GIVE_CASE_RE = re.compile(r"^!дать кейс\s+(\d+)\s+(\d+)(\s+себе)?$", re.IGNORECASE)
ADMIN_DEBUG_RE = re.compile(r"^!дебаг\s+@?(\w+)$", re.IGNORECASE)
ADMIN_SHOW_TEXT_RE = re.compile(r"^!текст\s+(\S+)$", re.IGNORECASE)
ADMIN_SIMULATE_EVO_RE = re.compile(r"^!симулировать эволюция\s+@?(\w+)$", re.IGNORECASE)
ADMIN_EVENT_CUSTOM_RE = re.compile(r"^!ивент\s+х(\d+(?:\.\d+)?)\s+(\d+)$", re.IGNORECASE)

ADMIN_SET_REBIRTH_RE = re.compile(rf"^!установить очкп {AMOUNT}(\s+себе)?$", re.IGNORECASE)
ADMIN_WIPE_ECONOMY_RE = re.compile(r"^!обнулить экономику\s+@?(\w+)$", re.IGNORECASE)
ADMIN_PERSONAL_BOOST_RE = re.compile(r"^!мультипликатор ферма\s+(\d+(?:\.\d+)?)\s+(\d+)(\s+себе)?$", re.IGNORECASE)
ADMIN_GIVE_ITEM_KEY_RE = re.compile(r"^!дать предмет\s+(\S+)\s+(\d+)(\s+себе)?$", re.IGNORECASE)
ADMIN_GIVE_KEY_RE = re.compile(r"^!дать ключ\s+(\S+)\s+(\d+)(\s+себе)?$", re.IGNORECASE)
ADMIN_CLEAR_INVENTORY_RE = re.compile(r"^!очистить инвентарь\s+@?(\w+)$", re.IGNORECASE)
ADMIN_SET_UPGRADE_RE = re.compile(r"^!дать апгрейд\s+(\S+)\s+(\d+)(\s+себе)?$", re.IGNORECASE)
ADMIN_VIP_FOREVER_RE = re.compile(r"^!вип навсегда(\s+себе)?$", re.IGNORECASE)
ADMIN_ULTRA_REBIRTH_RE = re.compile(r"^!ультра навсегда(\s+себе)?$", re.IGNORECASE)
ADMIN_RESET_NICK_RE = re.compile(r"^!сброс ник\s+@?(\w+)$", re.IGNORECASE)
ADMIN_FIND_RE = re.compile(r"^!найти\s+@?(\w+)$", re.IGNORECASE)
ADMIN_GIVE_ALL_RE = re.compile(r"^!дать всё(\s+себе)?$", re.IGNORECASE)
ADMIN_LEVELUP_NOTIFY_OFF_ALL_RE = re.compile(r"^!смс выкл всем$", re.IGNORECASE)

PROMO_CREATE_RE = re.compile(
    r'^!промокод создать\s+"([^"]+)"\s+"([^"]+)"\s+"([^"]+)"\s+"([^"]+)"$', re.IGNORECASE
)
PROMO_CREATE_BADGE_RE = re.compile(
    r'^!промокод создать бейдж\s+"([^"]+)"\s+"([^"]+)"$', re.IGNORECASE
)
PROMO_DELETE_RE = re.compile(r'^!промокод удалить\s+"([^"]+)"$', re.IGNORECASE)
PROMO_LIST_RE = re.compile(r'^!промокод список$', re.IGNORECASE)
PROMO_REDEEM_RE = re.compile(r'^(?:промокод|промо)\s+(\S+)$', re.IGNORECASE)

NEWS_PREFIX = "!новость "

FIXED_COMMANDS = {
    "моя нога", "топ ног", "гл топ ног", "топ эво", "гл топ эво", "топ коин", "гл топ коин",
    "топ гкоин", "гл топ гкоин", "топ акоин", "гл топ акоин",
    "ферма", "фарма", "инвентарь", "эволюция", "кейс", "кейсы", "бонус",
    "смс выкл", "смс вкл", "вип", "!ивент ноги", "бейджи",
    "перерождение", "апгрейд", "прокачка", "апг", "престиж", "баланс", "топ очкп", "гл топ очкп",
    "топ ноги вся", "топ коин вся", "топ эво вся", "топ очкп вся", "топ вся", "гл топ", "крафты", "крафт",
    "мои предметы", "предметы", "мои бустеры", "бустеры", "мой инвентарь", "-ник",
    "мои зелья", "зелья",
    "!список вип", "!список ников", "!список чат", "!логи", "!логи вся", "!пинг", "!ивент стоп", "!ивент статус",
    "!игроки",
    "ультра перерождение", "ультра перерождение подтверждаю",
    "авто эво вкл", "авто эво выкл", "авто эволюция вкл", "авто эволюция выкл",
    "авто перерождение вкл", "авто перерождение выкл", "авто рб вкл", "авто рб выкл",
    "авто ребёрт вкл", "авто ребёрт выкл", "авто реберт вкл", "авто реберт выкл",
    "авто продажа вкл", "авто продажа выкл", "авто продажа настройка", "авто продажа конфиг", "авто продажа настройки",
    "!смс выкл всем",
}
PREFIX_COMMANDS = (
    "обменять ", "!дать ног", "!снять ноги", "!дать эво", "!снять эво",
    "!дать коин", "!снять коин", "!дать б", "!снять б", "!дать п", "!снять п", "!дать вип", "!снять вип", "!сбросить",
    "передать ", "дать ", "кейс ", NEWS_PREFIX, "инфо ", "продать",
    "!дать очкп", "!снять очкп", "!дать крафт", "открыть кейс", "осмотреть кейс", "осмотр кейс", "крафты ", "крафт ", "уничтожение",
    "!дать гкоин", "!снять гкоин", "!дать акоин", "!снять акоин", "!дать престиж", "!снять престиж",
    "!дать титул", "!снять титул",
    "+ник ", "!установить ног", "!установить эво",
    "!сброс кд", "!сброс бонус", "!дать кейс", "!дебаг ", "!текст ", "!симулировать эволюция", "!ивент х",
    "!установить очкп", "!обнулить экономику", "!мультипликатор ферма", "!дать предмет",
    "!очистить инвентарь", "!дать апгрейд", "!вип навсегда", "!сброс ник", "!найти ", "!ультра навсегда",
    "вип открыть кейс", "бустеры поиск ", "!дать ключ", "!дать всё", "!бан", "!разбан",
    "?сброс ", "?буст", "?ускорение ", "?бонус", "?хелп", "?помощь",
)

def is_command_text(text: str) -> bool:
    t = text.lower()
    if t in FIXED_COMMANDS:
        return True
    return any(t.startswith(p) for p in PREFIX_COMMANDS)

_TOP_WORDS = ["топ", "топчик", "ладдер", "лидеры", "лиддеры", "рейтинг", "top", "ladder", "lider", "liders", "leaders", "rating"]
_LEG_WORDS = ["ног", "ноги", "ногой", "leg", "legs", "foot", "feet"]
_COIN_WORDS = ["коин", "коины", "коинов", "монета", "монеты", "монет", "coin", "coins", "money", "валюта"]
_GOLD_COIN_WORDS = ["гкоин", "гкоины", "гкоинов", "голдкоин", "голд коин", "голд-коин", "gold coin", "goldcoin"]
_DIAMOND_COIN_WORDS = ["акоин", "акоины", "акоинов", "алмкоин", "алмазкоин", "алмаз коин", "алмаз-коин", "diamond coin", "diamondcoin"]
_EVO_WORDS = ["эво", "эволюция", "эволюции", "эволюционировать", "evolution", "evolutions", "evo"]
_BALANCE_WORDS = ["баланс", "бал", "кошелек", "кошелёк", "деньги", "bal", "balance", "cash", "счет", "счёт"]
_REBIRTH_WORDS = ["перерождение", "перерождения", "ребёрт", "реберт", "ребёрты", "ребирты", "рб", "rebirth", "rb", "rebith"]
_CASE_WORDS = ["кейс", "сундук", "коробка", "case", "box"]
_CASES_WORDS = ["кейсы", "сундуки", "коробки", "cases", "boxes"]
_VIP_WORDS = ["вип", "vip", "випка", "premium", "премиум"]
_EXCHANGE_WORDS = ["обменять", "обмен", "обменник", "свап", "swap", "exchange"]

ALIAS_PHRASES = {}

def _register_phrases(canon: str, words):
    for w in words:
        ALIAS_PHRASES[w.lower()] = canon

_register_phrases("вип", _VIP_WORDS)
_register_phrases("баланс", _BALANCE_WORDS)
_register_phrases("перерождение", _REBIRTH_WORDS)
_register_phrases("эволюция", _EVO_WORDS)
_register_phrases("кейс", _CASE_WORDS)
_register_phrases("кейсы", _CASES_WORDS)
ALIAS_PHRASES["моя ношка"] = "моя нога"
ALIAS_PHRASES["моя ножка"] = "моя нога"
ALIAS_PHRASES["моя ноги"] = "моя нога"

for _top in _TOP_WORDS:
    for _leg in _LEG_WORDS:
        ALIAS_PHRASES[f"{_top} {_leg}"] = "топ ног"
        ALIAS_PHRASES[f"гл {_top} {_leg}"] = "гл топ ног"
        ALIAS_PHRASES[f"{_top} {_leg} вся"] = "топ ноги вся"
    for _coin in _COIN_WORDS:
        ALIAS_PHRASES[f"{_top} {_coin}"] = "топ коин"
        ALIAS_PHRASES[f"гл {_top} {_coin}"] = "гл топ коин"
        ALIAS_PHRASES[f"{_top} {_coin} вся"] = "топ коин вся"
    for _gcoin in _GOLD_COIN_WORDS:
        ALIAS_PHRASES[f"{_top} {_gcoin}"] = "топ гкоин"
        ALIAS_PHRASES[f"гл {_top} {_gcoin}"] = "гл топ гкоин"
        ALIAS_PHRASES[f"{_top} {_gcoin} вся"] = "топ гкоин вся"
    for _dcoin in _DIAMOND_COIN_WORDS:
        ALIAS_PHRASES[f"{_top} {_dcoin}"] = "топ акоин"
        ALIAS_PHRASES[f"гл {_top} {_dcoin}"] = "гл топ акоин"
        ALIAS_PHRASES[f"{_top} {_dcoin} вся"] = "топ акоин вся"
    for _evo in _EVO_WORDS:
        ALIAS_PHRASES[f"{_top} {_evo}"] = "топ эво"
        ALIAS_PHRASES[f"гл {_top} {_evo}"] = "гл топ эво"
        ALIAS_PHRASES[f"{_top} {_evo} вся"] = "топ эво вся"
    for _rb in _REBIRTH_WORDS:
        ALIAS_PHRASES[f"{_top} {_rb}"] = "топ очкп"
        ALIAS_PHRASES[f"гл {_top} {_rb}"] = "гл топ очкп"
        ALIAS_PHRASES[f"{_top} {_rb} вся"] = "топ очкп вся"
    ALIAS_PHRASES[f"{_top} вся"] = "топ вся"
ALIAS_PHRASES.pop("топ топ", None)

def normalize_alias_text(text: str) -> str:
    """Заменяет известную фразу-алиас на канонический текст команды. Не трогает команды
    с параметрами (числа, названия предметов, юзернеймы) — под них есть отдельная токенная
    замена ниже (normalize_alias_prefix), не полнофразовая."""
    if not text:
        return text
    stripped = text.strip()
    if not stripped:
        return text
    lowered = stripped.lower()
    return ALIAS_PHRASES.get(lowered, text)

_PARAM_TERM_TO_CANON = {}
for _w in _LEG_WORDS:
    _PARAM_TERM_TO_CANON[_w.lower()] = "ног"
for _w in _COIN_WORDS:
    _PARAM_TERM_TO_CANON[_w.lower()] = "коин"
for _w in _EVO_WORDS:
    _PARAM_TERM_TO_CANON[_w.lower()] = "эво"
for _w in _REBIRTH_WORDS:
    _PARAM_TERM_TO_CANON[_w.lower()] = "очкп"
for _w in _EXCHANGE_WORDS:
    _PARAM_TERM_TO_CANON[_w.lower()] = "обменять"
for _w in _CASE_WORDS:
    _PARAM_TERM_TO_CANON[_w.lower()] = "кейс"

_PARAM_PROTECTED = {"б", "п"}

_CASE_WORDS_SET = {w.lower() for w in _CASE_WORDS}

def normalize_case_number(text: str) -> str:
    """'сундук 2' / 'box 2' -> 'кейс 2'. Первое слово само является термином кейса,
    число (аргумент) не трогаем."""
    if not text:
        return text
    stripped = text.strip()
    if not stripped:
        return text
    parts = stripped.split(" ", 1)
    if len(parts) != 2:
        return text
    first, rest = parts[0].lower(), parts[1]
    if first in _CASE_WORDS_SET and first != "кейс" and rest.strip().isdigit():
        return "кейс " + rest
    return text

def normalize_alias_prefix(text: str) -> str:
    """Для команд вида '<преф> <термин> <аргументы...>' заменяет только термин сразу после
    известного префикса (!дать/!снять/дать/продать/обменять/кейс), не трогая аргументы."""
    if not text:
        return text
    stripped = text.strip()
    if not stripped:
        return text

    lowered = stripped.lower()
    known_prefixes = ("!дать ", "!снять ", "дать ")
    matched_prefix = None
    for p in known_prefixes:
        if lowered.startswith(p):
            matched_prefix = p
            break
    if matched_prefix is None:
        return text

    original_prefix = stripped[:len(matched_prefix)]
    rest = stripped[len(matched_prefix):]
    if not rest:
        return text

    rest_words = rest.split(" ", 1)
    term = rest_words[0]
    tail = rest_words[1] if len(rest_words) > 1 else ""
    lterm = term.lower()

    if lterm in _PARAM_PROTECTED:
        return text
    if lterm not in _PARAM_TERM_TO_CANON:
        return text

    canon_term = _PARAM_TERM_TO_CANON[lterm]
    if matched_prefix == "!снять " and canon_term == "ног":
        canon_term = "ноги"

    if canon_term == lterm:
        return text

    new_text = original_prefix + canon_term + (" " + tail if tail else "")
    return new_text

def normalize_exchange_suffix(text: str) -> str:
    """'обменять 10 монет' / 'обменять 10 coin' -> 'обменять 10 коин'. Не трогает 'обменять 10'
    (старая команда очки->монеты, без термина в хвосте)."""
    if not text:
        return text
    stripped = text.strip()
    lowered = stripped.lower()
    if not lowered.startswith("обменять "):
        return text
    rest = stripped[len("обменять "):].strip()
    if not rest:
        return text
    parts = rest.split(" ", 1)
    if len(parts) != 2:
        return text
    amount_word, term = parts[0], parts[1].strip()
    if not _AMOUNT_TOKEN_RE.match(amount_word):
        return text
    lterm = term.lower()
    if lterm not in _PARAM_TERM_TO_CANON:
        return text
    canon_term = _PARAM_TERM_TO_CANON[lterm]
    if canon_term != "коин" or canon_term == lterm:
        return text
    return f"обменять {amount_word} {canon_term}"

_FUZZY_CANDIDATES = None
_FUZZY_MAX_DIST = 1
_FUZZY_MIN_LEN = 4

def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]

def _get_fuzzy_candidates():
    global _FUZZY_CANDIDATES
    if _FUZZY_CANDIDATES is None:
        _FUZZY_CANDIDATES = sorted(set(FIXED_COMMANDS) | set(ALIAS_PHRASES.keys()))
    return _FUZZY_CANDIDATES

def normalize_alias_fuzzy(text: str) -> str:
    if not text:
        return text
    stripped = text.strip()
    if not stripped or " " in stripped:
        return text
    # Команды контент-мейкеров (?сброс/?буст/?ускорение/?бонус/?хелп) — отдельное пространство
    # имён, начинающееся с "?". Не подгонять их fuzzy-совпадением к обычным словам вроде "бонус"
    # (расстояние Левенштейна между "?бонус" и "бонус" — всего 1, что укладывалось в
    # _FUZZY_MAX_DIST и приводило к слиянию этих разных команд).
    if stripped.startswith("?"):
        return text
    lowered = stripped.lower()
    if lowered in FIXED_COMMANDS or lowered in ALIAS_PHRASES:
        return text
    if len(lowered) < _FUZZY_MIN_LEN:
        return text
    best_word = None
    best_dist = _FUZZY_MAX_DIST + 1
    for cand in _get_fuzzy_candidates():
        if " " in cand:
            continue
        if abs(len(cand) - len(lowered)) > _FUZZY_MAX_DIST:
            continue
        d = _levenshtein(lowered, cand)
        if d < best_dist:
            best_dist = d
            best_word = cand
            if d == 0:
                break
    if best_word is None or best_dist > _FUZZY_MAX_DIST:
        return text
    canon = ALIAS_PHRASES.get(best_word, best_word)
    return canon

_BAN_ALIAS_WORDS = ("swoon", "snowgrave")
_BAN_ALIAS_RE = re.compile(
    r"^(?:" + "|".join(re.escape(w) for w in _BAN_ALIAS_WORDS) + r")(\s+.*)?$",
    re.IGNORECASE,
)

def normalize_ban_alias(text: str) -> str:
    """'swoon' / 'snowgrave' -> '!бан', как отдельные алиасы команды бана (по просьбе
    пользователя). Не через ALIAS_PHRASES, потому что та таблица только для фраз БЕЗ
    аргументов (точное совпадение всей строки) — а !бан принимает опциональный
    '@username' в хвосте, который здесь нужно сохранить как есть."""
    if not text:
        return text
    stripped = text.strip()
    if not stripped:
        return text
    m = _BAN_ALIAS_RE.match(stripped)
    if not m:
        return text
    tail = m.group(1) or ""
    return "!бан" + tail

def apply_command_aliases(text: str) -> str:
    """Единая точка входа: применяет все виды алиасинга по порядку. Возвращает исходный текст,
    если ни один нормализатор не нашёл, что менять (в т.ч. для обычных сообщений с ногами 🦵/🦿 —
    там нет алиасов, и текст останется как есть)."""
    if not text:
        return text
    if text != text.strip():
        stripped_lower = text.strip().lower()
        if stripped_lower in FIXED_COMMANDS or stripped_lower in ALIAS_PHRASES:
            text = text.strip()
    result = normalize_ban_alias(text)
    if result != text:
        return result
    result = normalize_alias_text(text)
    if result != text:
        return result
    result = normalize_case_number(text)
    if result != text:
        return result
    result = normalize_exchange_suffix(text)
    if result != text:
        return result
    result = normalize_alias_prefix(text)
    if result != text:
        return result
    result = normalize_alias_fuzzy(text)
    return result

def esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def parse_amount(text: str):
    m = re.match(r"^(\d+(?:\.\d+)?)(к{0,4})$", text.strip().lower())
    if not m:
        return None
    number = float(m.group(1))
    k_count = len(m.group(2))
    return round(number * (1000 ** k_count))

TG_EMOJI_RE = re.compile(r"<tg-emoji[^>]*>(.*?)</tg-emoji>")

def plain_emoji(emoji_html: str) -> str:
    m = TG_EMOJI_RE.match(emoji_html or "")
    return m.group(1) if m else (emoji_html or "")

def strip_premium_emoji(text: str) -> str:
    """Убирает все <tg-emoji> обёртки из готового текста, оставляя фолбэк-символы."""
    return TG_EMOJI_RE.sub(lambda m: m.group(1), text or "")

async def safe_reply(message: Message, text: str, reply_markup=None):
    """Как message.reply(), но если Telegram отклонил сообщение из-за невалидного
    emoji-id в premium-эмодзи (битый/непризнанный custom_emoji_id) — повторяет
    отправку с обычными эмодзи вместо того, чтобы command тихо "не открывался"."""
    try:
        return await message.reply(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        return await message.reply(strip_premium_emoji(text), reply_markup=reply_markup)

async def safe_edit_text(callback: CallbackQuery, text: str, reply_markup=None):
    """Как callback.message.edit_text(), но не роняет хендлер, если Telegram отклонил
    правку. Это критично для инлайн-кнопок: если edit_text бросает исключение ДО того,
    как хендлер успел вызвать callback.answer(), Telegram держит кнопку в состоянии
    "часики" до собственного таймаута — именно это ощущается как "не нажимается"/
    "нажимается криво". Ловим и гасим самые частые причины:
    - "message is not modified" — юзер дважды подряд нажал одну и ту же кнопку
      (текст/клавиатура не изменились); это не ошибка, просто нечего обновлять.
    - "message to edit not found" / "query is too old" — сообщение удалено или
      кнопка нажата на старом сообщении после рестарта бота.
    - невалидный premium emoji-id — как и раньше, повторяем без премиум-обёртки.
    """
    try:
        return await callback.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        err = str(e).lower()
        if "message is not modified" in err:
            return None
        if "message to edit not found" in err or "query is too old" in err or "message can't be edited" in err:
            return None
        try:
            return await callback.message.edit_text(strip_premium_emoji(text), reply_markup=reply_markup)
        except TelegramBadRequest:
            return None

def build_regular_visual(level: int) -> str:
    if level <= 5:
        return "🦵" * level
    idx = level - 6
    tier = idx // 5
    pos = idx % 5 + 1
    tier_emoji = ["🦵🏻", "🦵🏽", "🦿"][tier]
    prev_emoji = ["🦵", "🦵🏻", "🦵🏽"][tier]
    return tier_emoji * pos + prev_emoji * (5 - pos)

# Начиная с level 20002 (старт ULTRA-диапазона) стоимость КАЖДОГО отдельного уровня растёт
# по своей отдельной шкале: level 20002 стоит ровно 100 000 000 очков, дальше — «почучуть»
# (полиномиально, степень n^1.15) относительно позиции n = level - 20001 в этом диапазоне.
# Формула суммируется точно (прямой цикл) до ULTRA_EXACT_SUM_CUTOFF, а выше — через
# приближение Эйлера-Маклорена (расхождение < 0.002% уже на границе, дальше меньше) —
# без этого точный цикл был бы слишком медленным на экстремальных уровнях (level ~ 10^100).
ULTRA_STEP_BASE_COST = 100_000_000
ULTRA_STEP_POWER = 1.15
ULTRA_EXACT_SUM_CUTOFF = 1000

@functools.lru_cache(maxsize=4096)
def _ultra_step_cost(n: int) -> int:
    """Стоимость перехода на n-й уровень ULTRA-диапазона (n=1 -> level 20002 -> 100 000 000)."""
    return round(ULTRA_STEP_BASE_COST * n ** ULTRA_STEP_POWER)

@functools.lru_cache(maxsize=4096)
def _ultra_extra_score(n: int) -> int:
    """Сумма стоимостей уровней 1..n сверх базового threshold(level=20001), n = level - 20001."""
    if n <= 0:
        return 0
    if n <= ULTRA_EXACT_SUM_CUTOFF:
        return sum(_ultra_step_cost(i) for i in range(1, n + 1))
    p = ULTRA_STEP_POWER
    approx = n ** (p + 1) / (p + 1) + n ** p / 2 + p * n ** (p - 1) / 12 - p * (p - 1) * (p - 2) * n ** (p - 3) / 720
    return round(ULTRA_STEP_BASE_COST * approx)

def base_level_threshold(level: int) -> int:
    if level <= 39:
        return ALL_THRESHOLDS[level - 1]
    if level <= ULTRA_REQUIRED_LEG_LEVEL:  # <= 20001, старая формула без изменений
        return MAX_LEVEL_SCORE + round(200 * (level - 39) ** 1.5)
    t20001 = MAX_LEVEL_SCORE + round(200 * (ULTRA_REQUIRED_LEG_LEVEL - 39) ** 1.5)
    return t20001 + _ultra_extra_score(level - ULTRA_REQUIRED_LEG_LEVEL)

def hardness_kwargs(row) -> dict:
    evo_mult = row[53] if len(row) > 53 and row[53] is not None else 1.0
    rebirth_mult = row[54] if len(row) > 54 and row[54] is not None else 1.0
    return {"evo_mult": evo_mult, "rebirth_mult": rebirth_mult}

def hardness_multiplier(evolution_level: int, rebirth_count: int = 0, active_items=None,
                        evo_mult: float = 1.0, rebirth_mult: float = 1.0) -> float:
    evo_extra = EVO_HARDNESS_RATE * evolution_level * evo_mult
    rebirth_extra = REBIRTH_HARDNESS_STEP * rebirth_count * rebirth_mult
    if active_items and "paradox_charm" in set(_normalize_active_items(active_items)):
        evo_extra *= 0.5
        rebirth_extra *= 0.5
    return (1 + evo_extra) * (1 + rebirth_extra)

def hardness_percent(evolution_level: int, rebirth_count: int = 0, active_items=None,
                     evo_mult: float = 1.0, rebirth_mult: float = 1.0) -> int:
    return round((hardness_multiplier(evolution_level, rebirth_count, active_items, evo_mult, rebirth_mult) - 1) * 100)

def level_threshold(level: int, evolution_level: int, rebirth_count: int = 0, active_items=None,
                    evo_mult: float = 1.0, rebirth_mult: float = 1.0) -> int:
    hardness = hardness_multiplier(evolution_level, rebirth_count, active_items, evo_mult, rebirth_mult)
    return round(base_level_threshold(level) * hardness)

def get_level_index(score: int, evolution_level: int = 0, rebirth_count: int = 0,
                     ultra_rebirth: bool = False, evo_mult: float = 1.0, rebirth_mult: float = 1.0) -> int:
    cap = ULTRA_LEVEL_CAP if ultra_rebirth else ULTRA_REQUIRED_LEG_LEVEL
    lo, hi = 0, cap
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if level_threshold(mid, evolution_level, rebirth_count, None, evo_mult, rebirth_mult) <= score:
            lo = mid
        else:
            hi = mid - 1
    return lo

def get_level_visual(level: int):
    if level == 0:
        return "🧍", "обычный безногий челик", True
    if level <= 20:
        return build_regular_visual(level), "", True
    if level <= 39:
        _, emoji, name = CUSTOM_LEVELS[level - 21]
        return emoji, name, True
    if level >= ULTRA_LEG_LEVEL:
        for start, end, emoji, name in ULTRA_TIERS:
            if start <= level <= end:
                return emoji, name, True
        return ULTRA_LEG_EMOJI, ULTRA_LEG_NAME, True
    if level >= MGG_MEGA_LEVEL:
        return MGG_MEGA_EMOJI, MGG_MEGA_NAME, True
    for start, end, emoji, name in EXTRA_TIERS:
        if start <= level <= end:
            return emoji, name, True
    return "❓", "неизвестный уровень", True

def next_level_text(score: int, evolution_level: int, rebirth_count: int = 0,
                     ultra_rebirth: bool = False, evo_mult: float = 1.0, rebirth_mult: float = 1.0) -> str:
    level = get_level_index(score, evolution_level, rebirth_count, ultra_rebirth, evo_mult, rebirth_mult)
    cap = ULTRA_LEVEL_CAP if ultra_rebirth else ULTRA_REQUIRED_LEG_LEVEL
    if level >= cap:
        return "Ты достиг абсолютного предела ноги — дальше только легенды 🌌"
    nxt = level_threshold(level + 1, evolution_level, rebirth_count, None, evo_mult, rebirth_mult)
    return f"До {level + 1} уровня осталось {nxt - score} очков"

def coin_tree_slot_bonus(inventory_map: dict) -> int:
    """+1 слот экипировки за 🟣 Монету Перерождения, +1 слот за ⚪️ Монету Пробуждения
    (суммируются, если есть обе — по 1 шт. каждой достаточно, лёжа в инвентаре, экипировать
    не нужно)."""
    bonus = 0
    if inventory_map.get("rebirth_coin", 0) > 0:
        bonus += 1
    if inventory_map.get("awakening_coin", 0) > 0:
        bonus += 1
    return bonus

def equipped_slots_max(upgrades: dict, prestige_upgrades: dict = None, bonus_slots: int = 0) -> int:
    prestige_upgrades = prestige_upgrades or {}
    return 1 + upgrade_level(upgrades, "equip_slots") + prestige_bonus(prestige_upgrades, "p_slots") + bonus_slots

def parse_equipped(equipped_str: str) -> list:
    """Очередь экипированных предметов: индекс 0 = надет раньше всех (первым вылетит при переполнении)."""
    return [k for k in (equipped_str or "").split(",") if k]

def format_equipped(items: list) -> str:
    return ",".join(items)

def equip_item(equipped_str: str, item_key: str, max_slots: int) -> list:
    """Добавляет item_key в конец очереди. Если он уже был в очереди — переставляет в конец
    (эквивалент «снял и заново надел»). При переполнении вылетает элемент с индекса 0."""
    items = [k for k in parse_equipped(equipped_str) if k != item_key]
    items.append(item_key)
    while len(items) > max_slots:
        items.pop(0)
    return items

def unequip_item(equipped_str: str, item_key: str) -> list:
    """Убирает item_key из очереди, если он там есть."""
    return [k for k in parse_equipped(equipped_str) if k != item_key]

def parse_potions(potions_str: str) -> dict:
    """'key:value,key:value' -> {key: value}. Для time-based зелий value = unix until_ts,
    для charge-based (no_cd) value = оставшиеся заряды."""
    result = {}
    for part in (potions_str or "").split(","):
        if not part or ":" not in part:
            continue
        key, _, val = part.partition(":")
        if key in POTIONS:
            try:
                result[key] = int(val)
            except ValueError:
                pass
    return result

def format_potions(potions: dict) -> str:
    return ",".join(f"{k}:{v}" for k, v in potions.items() if v > 0)

def active_potions_now(potions_str: str, now: int = None, active_items=None, inventory_map: dict = None) -> dict:
    """Отфильтровывает истёкшие time-based зелья (charge-based остаются, пока заряды > 0).
    ⏰ Часы Хроноса: ПАССИВНЫЙ эффект — пока лежат в инвентаре (экипировать не нужно), время
    action-зелий не тикает (не удаляем по истечению) — сама запись until_ts в БД не трогается,
    поэтому после расхода/продажи предмета зелье честно доедает оставшееся время."""
    now = now or int(time.time())
    frozen = bool(inventory_map and inventory_map.get("chronos_clock", 0) > 0)
    parsed = parse_potions(potions_str)
    result = {}
    for key, val in parsed.items():
        cfg = POTIONS[key]
        if cfg["effect"] == "no_cd":
            if val > 0:
                result[key] = val
        else:
            if val > now or frozen:
                result[key] = val
    return result

def potion_duration_seconds(key: str, upgrades: dict) -> int:
    base = POTIONS[key].get("duration_seconds", 0)
    bonus = 1 + 0.20 * upgrade_level(upgrades, "brew_duration")
    return round(base * bonus)

def brew_seconds_for(key: str, upgrades: dict, prestige_upgrades: dict = None, active_items=None, inventory_map: dict = None) -> int:
    """🌀 Шар хаоса: ПАССИВНЫЙ эффект — пока лежит в инвентаре (экипировать не нужно),
    режет время варки зелий на CHAOS_ORB_BREW_CUT."""
    base = POTIONS[key]["brew_seconds"]
    cut = 1 - 0.10 * upgrade_level(upgrades, "brew_speed")
    if prestige_upgrades:
        p_speed = prestige_bonus(prestige_upgrades, "p_brew_speed")
        if p_speed:
            cut -= 0.02 * p_speed
    if inventory_map and inventory_map.get("chaos_orb", 0) > 0:
        cut -= CHAOS_ORB_BREW_CUT
    cut = max(0.1, cut)
    return max(30, round(base * cut))

def has_potion_effect(potions: dict, effect: str) -> bool:
    return any(POTIONS[k]["effect"] == effect for k in potions)

async def consume_no_cd_charge(user_id: int, potions: dict) -> dict:
    """Списывает 1 заряд зелья 'без КД', если оно активно. Возвращает обновлённый potions dict."""
    if NO_CD_CHARGES_KEY not in potions:
        return potions
    left = potions[NO_CD_CHARGES_KEY] - 1
    new_potions = dict(potions)
    if left > 0:
        new_potions[NO_CD_CHARGES_KEY] = left
    else:
        new_potions.pop(NO_CD_CHARGES_KEY, None)
    await db_exec("UPDATE users SET active_potions = ? WHERE user_id = ?", (format_potions(new_potions), user_id))
    return new_potions

def parse_potion_stock(stock_str: str) -> dict:
    """Сваренные, но не выпитые зелья: 'key:qty,key:qty' -> {key: qty}."""
    result = {}
    for part in (stock_str or "").split(","):
        if not part or ":" not in part:
            continue
        key, _, qty = part.partition(":")
        if key in POTIONS:
            try:
                q = int(qty)
                if q > 0:
                    result[key] = q
            except ValueError:
                pass
    return result

def format_potion_stock(stock: dict) -> str:
    return ",".join(f"{k}:{v}" for k, v in stock.items() if v > 0)

def get_multiplier(evolution_level: int, active_items, vip_active: bool, upgrades: dict = None,
                    ultra_rebirth: bool = False, chronos_boost_pct: int = 100, nano_it_count: int = 0) -> float:
    mult = 1.0
    if evolution_level >= 2:
        mult += EVO_BOOST_STEP
    if evolution_level >= 3:
        mult += EVO_BOOST_STEP * (evolution_level - 2)
    equipped_set = set(_normalize_active_items(active_items))
    total_boost_percent = 0
    for item_key in equipped_set:
        if item_key in ITEMS and item_key != "chronos_orb":
            total_boost_percent += ITEMS[item_key][2]
    mult += total_boost_percent / 100
    if "chronos_orb" in equipped_set:
        mult += chronos_boost_pct / 100
    if vip_active:
        mult += VIP_BOOST
    if upgrades:
        mult += 0.05 * upgrade_level(upgrades, "booster")
    if ultra_rebirth:
        mult += ULTRA_REBIRTH_BOOST
    if nano_it_count:
        mult += (NANO_IT_BOOST_PCT_PER_UNIT * nano_it_count) / 100
    return mult

def _normalize_active_items(active_items):
    """Принимает список/кортеж ключей предметов, либо None. Строки сюда не передаём —
    для строки очереди сначала вызывай parse_equipped()."""
    if active_items is None:
        return []
    if isinstance(active_items, str):
        return [active_items] if active_items in ITEMS else parse_equipped(active_items)
    return [k for k in active_items if k]

def total_flat_bonus(active_items) -> int:
    return sum(ITEM_FLAT_BONUS.get(k, 0) for k in _normalize_active_items(active_items))

def parse_hidden(hidden_str: str) -> set:
    return set(h for h in (hidden_str or "").split(",") if h)

def parse_shown(shown_str: str) -> set:
    """Явно включённые (не скрытые) ключи бейджей — whitelist модель, аналог инвентаря:
    сколько бы бейджей игрок ни заработал, показываются только эти, максимум BADGES_DISPLAY_LIMIT."""
    return set(s for s in (shown_str or "").split(",") if s)

def parse_upgrades(upgrades_str: str) -> dict:
    result = {}
    for part in (upgrades_str or "").split(","):
        if not part or ":" not in part:
            continue
        key, _, lvl = part.partition(":")
        if key in UPGRADES:
            try:
                result[key] = int(lvl)
            except ValueError:
                pass
    return result

def format_upgrades(upgrades: dict) -> str:
    return ",".join(f"{k}:{v}" for k, v in upgrades.items() if v > 0)

def upgrade_level(upgrades: dict, key: str) -> int:
    return upgrades.get(key, 0)

def effective_max_level(key: str, upgrader_lvl: int = 1) -> int:
    """Итоговый max_level ветки с учётом уровня апгрейдера игрока. Часть веток расширяется
    на 2 уровне апгрейдера (см. UPGRADES[key]['max_level_by_upgrader'] — словарь
    {порог_уровня_апгрейдера: новый_max_level}). Берём наибольший порог, который игрок уже
    достиг; если веток-расширений нет или апгрейдер ещё не прокачан — базовый max_level."""
    cfg = UPGRADES[key]
    result = cfg["max_level"]
    extra = cfg.get("max_level_by_upgrader")
    if extra:
        for threshold in sorted(extra):
            if upgrader_lvl >= threshold:
                result = extra[threshold]
    return result

def upgrade_next_cost(key: str, upgrades: dict, upgrader_lvl: int = 1):
    cfg = UPGRADES[key]
    if cfg.get("wip") or cfg["cost"] is None:
        return None
    level = upgrade_level(upgrades, key)
    if level >= effective_max_level(key, upgrader_lvl):
        return None
    return cfg["cost"](level + 1)

def upgrade_next_extra_cost(key: str, upgrades: dict, upgrader_lvl: int = 1):
    """Доп. стоимость в другой валюте для следующего уровня апгрейда (напр. крафты ур.3 = 🉑+💠).
    Возвращает (currency_field, amount) либо None, если для этого уровня доп. валюты нет.
    Для веток с несколькими доп. валютами сразу (см. exchanger 3 ур.) используй
    upgrade_next_extra_costs — эта функция возвращает только первую пару, для обратной совместимости."""
    costs = upgrade_next_extra_costs(key, upgrades, upgrader_lvl)
    return costs[0] if costs else None

def upgrade_next_extra_costs(key: str, upgrades: dict, upgrader_lvl: int = 1) -> list:
    """Как upgrade_next_extra_cost, но всегда возвращает СПИСОК пар (currency_field, amount) —
    ветки cfg['extra_cost'] могут возвращать одну пару (старый формат, для обратной
    совместимости), список пар (несколько доп. валют сразу — напр. exchanger 3 ур. тратит
    и prestige_points, и diamond_coin), или None/пустой список, если доп. валюты не нужны."""
    cfg = UPGRADES[key]
    if cfg.get("wip") or cfg["cost"] is None or not cfg.get("extra_cost"):
        return []
    level = upgrade_level(upgrades, key)
    if level >= effective_max_level(key, upgrader_lvl):
        return []
    raw = cfg["extra_cost"](level + 1)
    if not raw:
        return []
    if isinstance(raw, tuple):
        return [raw]
    return list(raw)

def parse_prestige_upgrades(upgrades_str: str) -> dict:
    result = {}
    for part in (upgrades_str or "").split(","):
        if not part or ":" not in part:
            continue
        key, _, lvl = part.partition(":")
        if key in PRESTIGE_UPGRADES:
            try:
                result[key] = int(lvl)
            except ValueError:
                pass
    return result

def format_prestige_upgrades(upgrades: dict) -> str:
    return ",".join(f"{k}:{v}" for k, v in upgrades.items() if v > 0)

def prestige_level(upgrades: dict, key: str) -> int:
    return upgrades.get(key, 0)

def prestige_next_cost(key: str, upgrades: dict) -> int:
    """Бесконечная ветка — цена следующего уровня всегда определена, потолка нет."""
    level = prestige_level(upgrades, key)
    return PRESTIGE_UPGRADES[key]["cost"](level + 1)

def prestige_bonus(upgrades: dict, key: str) -> int:
    """Текущий эффект ветки на её нынешнем уровне (0, если ветка ещё не куплена)."""
    level = prestige_level(upgrades, key)
    return PRESTIGE_UPGRADES[key]["bonus"](level)

async def claim_offline_auto_farm(user_id: int, row) -> tuple:
    """Начисляет оффлайн-доход от Авто-Ферм НОГИ/КОИНЫ/очкп/ГКОИН по разнице времени, используя
    общий таймер last_auto_claim (единая точка отсчёта для всех авто-ферм разом).
    Возвращает (legs_gained, coins_gained, rebirth_gained, gold_coin_gained, new_score, new_coins)."""
    upgrades = parse_upgrades(row[16])
    legs_lvl = upgrade_level(upgrades, "auto_farm_legs")
    coins_lvl = upgrade_level(upgrades, "auto_farm_coins")
    rebirth_lvl = upgrade_level(upgrades, "auto_farm_rebirth")
    gold_coin_lvl = upgrade_level(upgrades, "auto_farm_gold_coin")
    score, coins = row[2], row[5]
    last_claim = row[17] or 0
    now = int(time.time())

    if not (legs_lvl or coins_lvl or rebirth_lvl or gold_coin_lvl):
        if not last_claim:
            await db_exec("UPDATE users SET last_auto_claim = ? WHERE user_id = ?", (now, user_id))
        return 0, 0, 0, 0, score, coins

    if not last_claim:
        await db_exec("UPDATE users SET last_auto_claim = ? WHERE user_id = ?", (now, user_id))
        return 0, 0, 0, 0, score, coins

    elapsed = max(0, now - last_claim)
    legs_gained = 0
    coins_gained = 0
    rebirth_gained = 0
    gold_coin_gained = 0

    if legs_lvl:
        amount, per_seconds = AUTO_FARM_LEGS_RATES[legs_lvl]
        legs_gained = int(elapsed // per_seconds) * amount
    if coins_lvl:
        amount, per_seconds = AUTO_FARM_COINS_RATES[coins_lvl]
        coins_gained = int(elapsed // per_seconds) * amount
    if rebirth_lvl:
        amount, per_seconds = AUTO_FARM_REBIRTH_RATES[rebirth_lvl]
        rebirth_gained = int(elapsed // per_seconds) * amount
    if gold_coin_lvl:
        amount, per_seconds = AUTO_FARM_GOLD_COIN_RATES[gold_coin_lvl]
        gold_coin_gained = int(elapsed // per_seconds) * amount

    if not (legs_gained or coins_gained or rebirth_gained or gold_coin_gained):
        return 0, 0, 0, 0, score, coins

    new_score = score + legs_gained
    new_coins = coins + coins_gained
    await db_exec(
        "UPDATE users SET score = ?, coins = ?, total_farmed = total_farmed + ?, "
        "rebirth_points = rebirth_points + ?, gold_coin = gold_coin + ?, last_auto_claim = ? WHERE user_id = ?",
        (new_score, new_coins, legs_gained, rebirth_gained, gold_coin_gained, now, user_id),
    )
    return legs_gained, coins_gained, rebirth_gained, gold_coin_gained, new_score, new_coins

def rebirth_hardness_multiplier(rebirth_count: int) -> float:
    return 1 + REBIRTH_HARDNESS_STEP * rebirth_count

def farm_yield_multiplier(upgrades: dict) -> float:
    """1-10 ур: обычные +10%/ур (аддитивно). 11-15 ур (открываются на 2 ур. апгрейдера):
    каждый уровень выше 10-го умножает результат ещё на x1.5 (мультипликативно, а не аддитивно —
    так задумано в ТЗ как отдельная, более мощная кривая для верхних уровней)."""
    level = upgrade_level(upgrades, "farm_yield")
    base_level = min(level, 10)
    multiplier = 1 + 0.10 * base_level
    extra_levels = max(0, level - 10)
    if extra_levels:
        multiplier *= 1.5 ** extra_levels
    return multiplier

POTION_BOOST_MULTIPLIERS = {0: 1.0, 1: 1.2, 2: 2.0, 3: 3.0}  # уровень ветки 'potion_booster' -> усиление

def potion_boost_multiplier(upgrades: dict) -> float:
    """Усиление эффектов зелья скорости и зелья удачи от ветки апгрейда 'potion_booster'
    (ветка 15, категория 4). Без прокачки — x1.0 (эффекты зелий работают как раньше)."""
    level = upgrade_level(upgrades, "potion_booster")
    return POTION_BOOST_MULTIPLIERS.get(level, 1.0)

# ==== Апдейт 2.6, категория 5 (ветки открываются на 3 ур. апгрейдера) ====
ECHO_FARM_CHANCE = {0: 0, 1: 0.05, 2: 0.10, 3: 0.15}  # уровень 'echo_farm' -> шанс x2 фарма
COIN_MAGNET_FLAT = {0: 0, 1: 3, 2: 7, 3: 12}  # уровень 'coin_magnet' -> флат 🪙 за фарм
FAST_EXCHANGE_RATE = {0: 30, 1: 27, 2: 24, 3: 20}  # уровень 'fast_exchange' -> курс 🉑 за 1 🔮
CASE_COLLECTOR_CHANCE = {0: 0, 1: 0.03, 2: 0.06, 3: 0.10}  # уровень 'case_collector' -> шанс доп. предмета

def echo_farm_chance(upgrades: dict) -> float:
    return ECHO_FARM_CHANCE.get(upgrade_level(upgrades, "echo_farm"), 0)

def coin_magnet_bonus(upgrades: dict) -> int:
    return COIN_MAGNET_FLAT.get(upgrade_level(upgrades, "coin_magnet"), 0)

def prestige_exchange_rate(upgrades: dict) -> int:
    return FAST_EXCHANGE_RATE.get(upgrade_level(upgrades, "fast_exchange"), 30)

def case_collector_chance(upgrades: dict) -> float:
    return CASE_COLLECTOR_CHANCE.get(upgrade_level(upgrades, "case_collector"), 0)

def farm_cd_seconds(upgrades: dict, active_items=None, has_time_particle: bool = False,
                     prestige_upgrades: dict = None) -> int:
    """1-5 ур: обычные -2 мин (120 сек) за уровень. 6-8 ур (открываются на 2 ур. апгрейдера):
    каждый уровень выше 5-го снимает ещё 20 сек — отдельная, более мелкая кривая для
    верхних уровней, как и у Ферма ДОБЫЧА."""
    level = upgrade_level(upgrades, "farm_cd")
    base_level = min(level, 5)
    extra_levels = max(0, level - 5)
    reduction = 120 * base_level + 20 * extra_levels
    cooldown = max(60, FARM_COOLDOWN - reduction)

    tier = get_active_unique_tier(active_items) if active_items is not None else None
    if tier in GOD_TIER_LIKE:
        cooldown = cooldown / GOD_ESSENCE_FARM_SPEED - GOD_ESSENCE_TIMER_CUT
    elif has_time_particle:
        cooldown = cooldown / TIME_PARTICLE_FARM_SPEED

    if prestige_upgrades:
        p_speed = prestige_bonus(prestige_upgrades, "p_farm_speed")
        if p_speed:
            cooldown *= max(0.1, 1 - 0.01 * p_speed)

    return max(30, round(cooldown))

def booster_upgrade_multiplier(upgrades: dict) -> float:
    return 1 + 0.05 * upgrade_level(upgrades, "booster")

def case_discount(upgrades: dict) -> float:
    """Ограничена 70% сверху (жёсткий clamp) — при высоких уровнях ветки (после 3 ур.
    апгрейдера линейная формула 10%/ур иначе ушла бы в 100%+ и обнулила/увела в минус цену кейсов)."""
    return min(0.70, 0.10 * upgrade_level(upgrades, "discount"))

def case_price_with_discount(base_price: int, upgrades: dict) -> int:
    discount = case_discount(upgrades)
    return max(1, round(base_price * (1 - discount)))

def craft_coin_cost_with_discount(base_cost: int, prestige_upgrades: dict = None) -> int:
    """Скидка крафта — целиком за счёт ветки престижа p_craft_discount (обычной скидки крафта
    в игре не было ранее, эта механика впервые вводится через дерево престижа)."""
    if not base_cost:
        return 0
    if not prestige_upgrades:
        return base_cost
    discount = 0.01 * prestige_bonus(prestige_upgrades, "p_craft_discount")
    discount = min(0.9, discount)
    return max(1, round(base_cost * (1 - discount)))

def sell_bonus_coins(upgrades: dict) -> int:
    return 2 * upgrade_level(upgrades, "sell_boost")

def badge_list(username: str, evolution_level: int, cases_opened: int, total_farmed: int, vip_active: bool,
                promo_badges: set = frozenset(), coins: int = 0, rebirth_points: int = 0,
                ultra_rebirth: bool = False, bonus_streak: int = 0, crafts_done: int = 0,
                prestige_points: int = 0):
    result = []
    if username and username.lower() == ADMIN_USERNAME.lower():
        result.append(("owner", PREMIUM_OWNER_BADGE, "Владелец"))
    if vip_active:
        result.append(("vip", PREMIUM_VIP_BADGE, "VIP"))
    if evolution_level >= 1:
        result.append(("evo", PREMIUM_BADGE_EVO, "1+ эволюция"))
    if cases_opened >= 5:
        result.append(("case", PREMIUM_BADGE_CASE, "5+ кейсов"))
    if total_farmed >= BADGE_EVO_TOTAL:
        result.append(("farm", PREMIUM_BADGE_FARM, "30k нафармлено"))
    if evolution_level >= 5:
        result.append(("evo5", PREMIUM_BADGE_EVO5, "5 эволюция"))
    for key, emoji, label, threshold in EVO_MILESTONE_BADGES:
        if evolution_level >= threshold:
            result.append((key, emoji, label))
    for key, emoji, label, threshold in CASE_MILESTONE_BADGES:
        if cases_opened >= threshold:
            result.append((key, emoji, label))
    for key, emoji, label, threshold in FARM_MILESTONE_BADGES:
        if total_farmed >= threshold:
            result.append((key, emoji, label))
    for key, emoji, label, threshold in COIN_MILESTONE_BADGES:
        if coins >= threshold:
            result.append((key, emoji, label))
    for key, emoji, label, threshold in REBIRTH_MILESTONE_BADGES:
        if rebirth_points >= threshold:
            result.append((key, emoji, label))
    if ultra_rebirth:
        result.append(("ultra_rebirth", PREMIUM_BADGE_ULTRA_REBIRTH, "Ультра-Феникс"))
    for key, emoji, label, threshold in STREAK_MILESTONE_BADGES:
        if bonus_streak >= threshold:
            result.append((key, emoji, label))
    for key, emoji, label, threshold in CRAFT_MILESTONE_BADGES:
        if crafts_done >= threshold:
            result.append((key, emoji, label))
    for key, emoji, label, threshold in PRESTIGE_MILESTONE_BADGES:
        if prestige_points >= threshold:
            result.append((key, emoji, label))
    for key in promo_badges:
        if key in PROMO_BADGES:
            emoji, name = PROMO_BADGES[key]
            result.append((key, emoji, name))
    return result

def get_badges(username: str, evolution_level: int, cases_opened: int, total_farmed: int, vip_active: bool,
                shown: set = frozenset(), promo_badges: set = frozenset(), coins: int = 0,
                rebirth_points: int = 0, ultra_rebirth: bool = False, bonus_streak: int = 0,
                crafts_done: int = 0, prestige_points: int = 0) -> str:
    """shown — whitelist явно включённых ключей бейджей (см. parse_shown). Показываются
    только они, максимум BADGES_DISPLAY_LIMIT штук — как со слотами экипировки в инвентаре,
    а не «все заработанные минус скрытые»."""
    earned = badge_list(username, evolution_level, cases_opened, total_farmed, vip_active, promo_badges,
                         coins, rebirth_points, ultra_rebirth, bonus_streak, crafts_done, prestige_points)
    visible = [emoji for key, emoji, _ in earned if key in shown]
    return "".join(visible[:BADGES_DISPLAY_LIMIT])

def badges_keyboard(earned, shown: set, user_id: int, page: int = 0) -> InlineKeyboardMarkup:
    total_pages = max(1, (len(earned) - 1) // BADGES_PAGE_SIZE + 1)
    page = max(0, min(page, total_pages - 1))
    start = page * BADGES_PAGE_SIZE
    rows = []
    for key, emoji, label in earned[start:start + BADGES_PAGE_SIZE]:
        state = "✅ показан" if key in shown else "🙈 скрыт"
        rows.append([InlineKeyboardButton(
            text=f"{plain_emoji(emoji)} {label} — {state}",
            callback_data=f"badge:{user_id}:{page}:{key}",
        )])

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=f"badge_page:{user_id}:{page - 1}", style="primary"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="badge_noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"badge_page:{user_id}:{page + 1}", style="primary"))
        rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)

def farm_range(evolution_level: int):
    return FARM_EVOLVED if evolution_level >= 1 else FARM_BASE

def is_admin(message: Message) -> bool:
    return message.from_user.id == ADMIN_USER_ID or (message.from_user.username or "").lower() == ADMIN_USERNAME.lower()

# ==== Система титулов/привилегий ====
# is_admin() выше — это на самом деле проверка "это Разработчик?" (единственный человек,
# захардкоженный в ADMIN_USER_ID/ADMIN_USERNAME, полный доступ без ограничений). Оставляем имя
# is_admin как есть для обратной совместимости со всеми существующими вызовами по файлу, но
# заводим is_developer как алиас с понятным названием для новых мест кода.
is_developer = is_admin

def is_developer_id(user_id: int) -> bool:
    """Версия is_developer, принимающая user_id напрямую (когда нет объекта Message под рукой,
    например при работе с чужим профилем через reply/инфо)."""
    return user_id == ADMIN_USER_ID

# Приоритет показа титула в профиле/инфо (см. TITLE_PRIORITY) — чем МЕНЬШЕ число, тем выше
# приоритет: при показе всегда берётся титул с наименьшим числом среди тех, что есть у игрока.
# Права на команды — НЕЗАВИСИМО от этого: у игрока может быть одновременно admin_role='admin' И
# content_role='youtuber' (оба набора команд доступны), но в профиле покажется только "Ютубер"
# (у него приоритет 2 против 4 у админа).
TITLE_PRIORITY = {
    "developer": 1,
    "youtuber": 2,
    "tiktoker": 3,
    "admin": 4,
    "moderator": 5,
    "premium": 6,
    "vip": 7,
    "player": 8,
}

TITLE_LABELS = {
    "developer": "Разработчик",
    "youtuber": "Ютубер",
    "tiktoker": "Тиктокер",
    "admin": "Админ",
    "moderator": "Модератор",
    "premium": "Премиум",
    "vip": "VIP",
    "player": "Игрок",
}

def get_active_titles(row) -> set:
    """Все титулы, которыми ОБЛАДАЕТ игрок одновременно (для проверки прав на команды) —
    в отличие от get_display_title, который возвращает только один (самый приоритетный) для
    показа. row — полный USER_COLUMNS row (индексы 42/43/44 = admin_role/content_role/
    is_premium_title, добавлены в конец USER_COLUMNS)."""
    titles = {"player"}
    admin_role = (row[42] or "") if len(row) > 42 else ""
    content_role = (row[43] or "") if len(row) > 43 else ""
    is_premium = bool(row[44]) if len(row) > 44 else False
    vip_until = row[12] if len(row) > 12 else 0

    if admin_role == "admin":
        titles.add("admin")
    elif admin_role == "moderator":
        titles.add("moderator")
    if content_role == "youtuber":
        titles.add("youtuber")
    elif content_role == "tiktoker":
        titles.add("tiktoker")
    if is_premium:
        titles.add("premium")
    if is_vip_active(vip_until):
        titles.add("vip")
    return titles

async def get_active_titles_for_user(user_id: int) -> set:
    """Как get_active_titles, но сама читает row по user_id и добавляет 'developer', если это
    Разработчик (is_developer_id) — удобно вызывать напрямую по чужому user_id без Message."""
    row = await get_user(user_id)
    if not row:
        return {"player"}
    titles = get_active_titles(row)
    if is_developer_id(user_id):
        titles.add("developer")
    return titles

def status_lines(vip_active: bool, vip_until: int, ultra_rebirth: bool, now: int) -> tuple:
    ultra_line = "● Статус: 🌌 После Ультра перерождения\n" if ultra_rebirth else "● Статус: До Ультра перерождения\n"
    if vip_active:
        d, rem = divmod(max(0, vip_until - now), 86400)
        h = rem // 3600
        vip_line = f"● VIP статус: активен ({d} дн {h} ч) {PREMIUM_VIP_BADGE}\n"
    else:
        vip_line = "● VIP статус: не активен\n"
    return ultra_line, vip_line

def get_display_title(titles: set) -> str:
    """Из набора титулов игрока выбирает ОДИН — с наименьшим числом в TITLE_PRIORITY (см. выше:
    выше привилегия визуально перекрывает более низкие в профиле/инфо)."""
    return min(titles, key=lambda t: TITLE_PRIORITY.get(t, 99))

# ==== Проверки прав на команды (модератор/админ), для использования в хендлерах ====
# Разработчик (is_admin/is_developer) всегда проходит любую из этих проверок — полный доступ.
# Админ имеет доступ ко ВСЕМ модераторским командам тоже (админ выше модератора в иерархии
# прав, не только в приоритете показа) — см. ТЗ: "Админ — доступ ко всем командам".
async def is_moderator_or_above(message: Message) -> bool:
    """Модераторские команды (бан, список чат, найти, топ спам, ники, ивент с ограничениями) —
    доступны Разработчику, Админу и Модератору."""
    if is_developer(message):
        return True
    row = await get_user(message.from_user.id)
    if not row:
        return False
    admin_role = row[42] if len(row) > 42 else ""
    return admin_role in ("admin", "moderator")

async def is_admin_role_or_above(message: Message) -> bool:
    """Админские команды (полный список !дать/!снять и т.д. с лимитами/КД) — доступны
    Разработчику и Админу (модератору НЕ доступны)."""
    if is_developer(message):
        return True
    row = await get_user(message.from_user.id)
    if not row:
        return False
    admin_role = row[42] if len(row) > 42 else ""
    return admin_role == "admin"

# ==== Лимиты и общий КД для роли Админ (Разработчик не ограничен ничем) ====
# Лимит — максимум за ОДНУ выдачу; общий КД 1 час — на ЛЮБУЮ из этих выдающих команд разом
# (использовал одну — жди час перед следующей, даже другой валюты).
ADMIN_GIVE_COOLDOWN = 600  # 10 минут (было 3600 = 1 час)
ADMIN_GIVE_LIMITS = {
    "ноги": 10_000_000_000,
    "коин": 20_000_000,
    "очкп": 15_000,
    "престиж": 20_000,
    "очкк": 200,
    "акоин": 50,
    "гкоин": 5_000,
    "эво": 50,
    "перерождение": 10,
}
# Команды, которые Админу вообще недоступны (даже с лимитом) — VIP и УП (ультра-перерождение).
ADMIN_FORBIDDEN_ACTIONS = {"vip", "ultra"}

async def admin_role_gate(message: Message, currency: str = None, amount: int = None, action: str = None) -> str:
    """Единая проверка для админских выдающих команд. Возвращает пустую строку, если действие
    разрешено, иначе — текст ошибки для ответа пользователю (и хендлер должен просто
    await message.reply(err); return). Разработчику всё разрешено без всяких проверок здесь —
    хендлер сам должен звать эту функцию только после is_admin_role_or_above (то есть только
    для тех, кто уже прошёл проверку "админ или выше").
    currency: ключ в ADMIN_GIVE_LIMITS (если команда даёт валюту с числовым лимитом).
    action: 'vip' или 'ultra', если команда — одна из полностью запрещённых для Админа."""
    if is_developer(message):
        return ""

    if action and action in ADMIN_FORBIDDEN_ACTIONS:
        return "Админу запрещено выдавать VIP и Ультра-перерождение — это может только Разработчик."

    if currency and amount is not None:
        limit = ADMIN_GIVE_LIMITS.get(currency)
        if limit is not None and amount > limit:
            return f"Админу нельзя выдавать больше {limit} за раз ({currency})."

    row = await get_user(message.from_user.id)
    last_give = (row[45] if len(row) > 45 else 0) or 0  # admin_last_give
    now = int(time.time())
    wait_left = ADMIN_GIVE_COOLDOWN - (now - last_give)
    if wait_left > 0:
        wm, ws = divmod(wait_left, 60)
        return f"КД на выдачу для роли Админ: подожди ещё {wm} мин {ws} сек (общий КД на все выдающие команды)."

    await db_exec("UPDATE users SET admin_last_give = ? WHERE user_id = ?", (now, message.from_user.id))
    return ""

async def has_content_role(message: Message, role: str) -> bool:
    """role: 'youtuber' или 'tiktoker'. Разработчик тоже проходит (полный доступ), хотя ему эти
    команды вряд ли понадобятся."""
    if is_developer(message):
        return True
    row = await get_user(message.from_user.id)
    if not row:
        return False
    content_role = row[43] if len(row) > 43 else ""
    return content_role == role

async def get_content_role(message: Message) -> str:
    """Возвращает 'youtuber', 'tiktoker' или '' — какая контент-роль (если есть) у автора
    сообщения. Разработчик получает 'youtuber' по умолчанию (чтобы мог тестировать команды),
    так как обе роли делят одни и те же команды ?сброс/?буст/?ускорение/?хелп — различается
    только награда в ?бонус."""
    if is_developer(message):
        return "youtuber"
    row = await get_user(message.from_user.id)
    if not row:
        return ""
    content_role = row[43] if len(row) > 43 else ""
    return content_role if content_role in ("youtuber", "tiktoker") else ""

CONTENT_BONUS_TEXT_ITEMS = {
    "youtube_button": "Вы уникальны.",
    "tiktok_legend": "Вы легенда.",
}

def content_bonus_text_override(active_items) -> str:
    items = set(_normalize_active_items(active_items))
    for item_key, text in CONTENT_BONUS_TEXT_ITEMS.items():
        if item_key in items:
            return text
    return ""

def subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url=REQUIRED_CHANNEL_URL)],
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")],
    ])

async def is_subscribed(user_id: int) -> bool:
    """Проверяет подписку на REQUIRED_CHANNEL_CHAT_ID с коротким кэшем,
    чтобы не спамить getChatMember на каждый фарм/эво/перерождение."""
    cached = _subscription_cache.get(user_id)
    now = time.monotonic()
    if cached and now - cached[1] < SUBSCRIPTION_CHECK_CACHE_TTL:
        return cached[0]

    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL_CHAT_ID, user_id)
        subscribed = member.status not in ("left", "kicked")
        print(f"[sub-check] user={user_id} status={member.status} -> subscribed={subscribed}")
    except Exception as e:
        # ВРЕМЕННО (диагностика): раньше любая ошибка тут пропускала пользователя (subscribed=True).
        # Сейчас логируем во весь голос, чтобы увидеть причину. Пока не разберёмся — считаем НЕ подписанным.
        print(f"[sub-check] ОШИБКА при проверке ({REQUIRED_CHANNEL_CHAT_ID}, user={user_id}): {type(e).__name__}: {e}")
        subscribed = False

    _subscription_cache[user_id] = (subscribed, now)
    return subscribed

async def require_subscription(message: Message) -> bool:
    """Возвращает True если можно продолжать выполнение команды.
    Если пользователь не подписан — отправляет требование подписаться и возвращает False."""
    user_id = message.from_user.id
    if is_admin(message):
        return True
    if await is_subscribed(user_id):
        return True
    await message.reply(TEXTS["require_subscription_1"], reply_markup=subscription_keyboard())
    return False

@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    _subscription_cache.pop(user_id, None)  # форс-рекheck, не ждём TTL кэша
    if await is_subscribed(user_id):
        await callback.answer("✅ Подписка подтверждена! Можешь фармить дальше.", show_alert=True)
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
    else:
        await callback.answer("❌ Подписки пока не вижу. Подпишись на канал и попробуй ещё раз.", show_alert=True)

def roll_case_item(case_num: int) -> str:
    pool = CASES[case_num]["pool"]
    weights = [ITEMS[k][3] for k in pool]
    return random.choices(pool, weights=weights, k=1)[0]

def case_drop_table(case_num: int) -> list:
    """Список (item_key, эмодзи, имя, буст%, шанс_в_процентах) для конкретного кейса,
    отсортированный по убыванию шанса."""
    pool = CASES[case_num]["pool"]
    weights = [ITEMS[k][3] for k in pool]
    total = sum(weights)
    rows = []
    for k, w in zip(pool, weights):
        emoji, name, percent, _ = ITEMS[k]
        chance = round(w / total * 100, 2) if total else 0
        rows.append((k, emoji, name, percent, chance))
    rows.sort(key=lambda r: r[4], reverse=True)
    return rows

def find_item_by_name(query: str, only_passive=None):
    q = query.strip().lower()
    candidates = ITEMS.items()
    if only_passive is True:
        candidates = [(k, v) for k, v in candidates if k in PASSIVE_ITEMS]
    elif only_passive is False:
        candidates = [(k, v) for k, v in candidates if k not in PASSIVE_ITEMS]
    for key, (_, name, _, _) in candidates:
        if name.lower() == q:
            return key
    matches = [key for key, (_, name, _, _) in candidates if q in name.lower()]
    if len(matches) == 1:
        return matches[0]
    return None

async def resolve_target(message: Message, to_self: bool):
    if to_self:
        return message.from_user
    if message.reply_to_message:
        return message.reply_to_message.from_user
    return None

from concurrent.futures import ThreadPoolExecutor

DB_WORKER_COUNT = int(os.environ.get("DB_WORKER_COUNT", "5"))

_db_queues: list = []
_db_worker_tasks: list = []
_db_conns: list = []
_db_executor = ThreadPoolExecutor(max_workers=DB_WORKER_COUNT, thread_name_prefix="db-worker")

_user_cache: dict = {}
_USERS_WRITE_RE = re.compile(r"\b(?:UPDATE|DELETE\s+FROM)\s+users\b", re.IGNORECASE)

def _invalidate_user_cache(user_id):
    _user_cache.pop(user_id, None)

# In-memory множество забаненных в игре user_id. Держим отдельно от _user_cache,
# потому что GameBanMiddleware проверяет его на КАЖДОМ входящем апдейте (message
# и callback_query) — гонять полный SELECT по users на каждое сообщение было бы
# слишком дорого. Заполняется при старте из БД (см. _load_game_banned_ids) и
# обновляется точечно в самих командах !бан/!разбан.
_game_banned_ids: set = set()

async def _load_game_banned_ids():
    rows = await db_query("SELECT user_id FROM users WHERE game_banned = 1")
    _game_banned_ids.clear()
    _game_banned_ids.update(r[0] for r in rows)

# In-memory множество забаненных чатов (banned_chats.chat_id) — та же логика, что
# и у _game_banned_ids: ChatBanMiddleware проверяет его на каждом апдейте, поэтому
# держим в памяти вместо SELECT на каждое сообщение. Заполняется при старте
# (_load_banned_chat_ids) и обновляется точечно в !бан чат.
_banned_chat_ids: set = set()

async def _load_banned_chat_ids():
    rows = await db_query("SELECT chat_id FROM banned_chats")
    _banned_chat_ids.clear()
    _banned_chat_ids.update(r[0] for r in rows)

def _connect(worker_idx):
    if _db_conns[worker_idx] is None:
        _db_conns[worker_idx] = libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)
    return _db_conns[worker_idx]

def _drop_conn(worker_idx):
    """Убивает протухшее соединение воркера, чтобы следующий _connect() создал новое.
    Без этого одно оборвавшееся HTTP/hrana-соединение (сетевой сбой, таймаут Turso,
    обрыв стрима) навсегда застревало в _db_conns[worker_idx] — _connect() проверяет
    только 'is None' и отдавал бы тот же мёртвый объект дальше, а значит КАЖДЫЙ
    следующий запрос, попавший на этот воркер (то есть всегда одни и те же user_id,
    см. _pick_worker), падал бы с ошибкой навсегда, до перезапуска бота."""
    conn = _db_conns[worker_idx]
    _db_conns[worker_idx] = None
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass

def _is_retryable_db_error(e: Exception) -> bool:
    """Отличаем 'протухло соединение/сеть моргнула' (стоит переподключиться и
    повторить) от логических ошибок SQL (плохой запрос — повтор не поможет и
    только зациклит ту же ошибку). Проверяем по тексту, а не по типу исключения,
    потому что разные версии libsql/hrana поднимают разные классы ошибок на
    сетевые обрывы, а стабильного публичного типа для этого нет."""
    text = str(e).lower()
    markers = (
        "locked", "busy", "closed", "connection", "timeout", "timed out",
        "broken pipe", "reset", "stream", "hrana", "network", "unavailable",
        "eof", "disconnect",
    )
    return any(m in text for m in markers)

def _run_with_reconnect(worker_idx, fn, sql=None, params=None):
    """Общая обвязка для _exec_sync/_exec_many_sync/_query_sync: один повтор
    на свежем соединении при транзиентной ошибке. ГЛАВНЫЙ ФИКС бага 'рандомные
    команды отваливаются после включения DB_WORKER_COUNT=5': на одном потоке
    протухшее соединение было бы видно сразу и на всех командах (сразу заметили
    бы), а теперь оно тихо убивает только тот воркер (= только те user_id,
    которые на него шардируются) — выглядит как 'рандомные' отвалы конкретных
    юзеров/команд, хотя на самом деле это всегда один и тот же воркер.
    sql/params передаются только для тегирования исключения через _tag_db_error
    (диагностика в error_handler) — на саму retry-логику не влияют."""
    try:
        return fn()
    except Exception as e:
        if not _is_retryable_db_error(e):
            _tag_db_error(e, worker_idx, sql, params)
            raise
        _drop_conn(worker_idx)
        try:
            return fn()
        except Exception as e2:
            _tag_db_error(e2, worker_idx, sql, params)
            raise

def _tag_db_error(e: Exception, worker_idx, sql, params):
    """Вешает на исключение, какой воркер/запрос его вызвал — читается в
    error_handler (_bot_last_sql/_bot_last_params), чтобы в логе ошибки сразу
    было видно, на каком из DB_WORKER_COUNT воркеров и на каком именно SQL
    всё упало, а не только голый traceback без этого контекста."""
    try:
        e._bot_worker_idx = worker_idx
        e._bot_last_sql = sql
        e._bot_last_params = params
    except Exception:
        pass

def _exec_sync(worker_idx, sql, params):
    def attempt():
        conn = _connect(worker_idx)
        conn.execute(sql, params)
        conn.commit()
    _run_with_reconnect(worker_idx, attempt, sql, params)

def _exec_many_sync(worker_idx, sql, params_list):
    def attempt():
        conn = _connect(worker_idx)
        conn.executemany(sql, params_list)
        conn.commit()
    _run_with_reconnect(worker_idx, attempt, sql, params_list)

def _query_sync(worker_idx, sql, params):
    def attempt():
        conn = _connect(worker_idx)
        cur = conn.execute(sql, params)
        return cur.fetchall()
    return _run_with_reconnect(worker_idx, attempt, sql, params)

async def _db_worker(worker_idx):
    """Один из DB_WORKER_COUNT потоков. Каждый воркер берёт задачи строго из
    СВОЕЙ очереди по одной — его соединение всегда используется из одного и
    того же потока (никаких гонок внутри соединения), но разные воркеры со
    своими соединениями могут работать параллельно, а не ждать друг друга."""
    loop = asyncio.get_event_loop()
    queue = _db_queues[worker_idx]
    while True:
        fn, sql, params, future = await queue.get()
        try:
            result = await loop.run_in_executor(_db_executor, fn, worker_idx, sql, params)
            if not future.done():
                future.set_result(result)
        except Exception as e:
            if not future.done():
                future.set_exception(e)
        finally:
            queue.task_done()

def _ensure_db_workers():
    global _db_queues, _db_worker_tasks, _db_conns
    if not _db_queues:
        _db_queues = [asyncio.Queue() for _ in range(DB_WORKER_COUNT)]
        _db_conns = [None] * DB_WORKER_COUNT
        _db_worker_tasks = [None] * DB_WORKER_COUNT
    for i in range(DB_WORKER_COUNT):
        if _db_worker_tasks[i] is None or _db_worker_tasks[i].done():
            _db_worker_tasks[i] = asyncio.create_task(_db_worker(i))

_USER_ID_PARAM_RE = re.compile(r"user_id\s*=\s*\?", re.IGNORECASE)

def _pick_worker(sql: str, params) -> int:
    """Выбирает воркер по user_id, а НЕ по первому попавшемуся int-параметру
    (старое поведение было ненадёжным: 'UPDATE inventory SET qty = ? WHERE
    user_id = ? ...' раньше шардировалось по qty, а не по user_id — при
    DB_WORKER_COUNT > 1 это давало гонки для одного и того же игрока между
    операциями с разным первым параметром). Теперь ищем позицию именно
    того '?', который соответствует 'user_id = ?' в самом SQL, и берём
    параметр с этим индексом. Если такого условия в запросе нет (массовые
    INSERT/DELETE без фильтра по игроку, служебные апдейты) — используем
    старую эвристику "первый int-параметр" как безопасный fallback, а если
    и её нет — все такие запросы идут в воркер 0."""
    m = _USER_ID_PARAM_RE.search(sql)
    if m:
        idx = sql[:m.end()].count("?") - 1
        if 0 <= idx < len(params):
            p = params[idx]
            if isinstance(p, int) and not isinstance(p, bool):
                return p % DB_WORKER_COUNT
    for p in params:
        if isinstance(p, int) and not isinstance(p, bool):
            return p % DB_WORKER_COUNT
    return 0

async def _db_submit(fn, sql, params):
    _ensure_db_workers()
    worker_idx = _pick_worker(sql, params)
    future = asyncio.get_event_loop().create_future()
    await _db_queues[worker_idx].put((fn, sql, params, future))
    return await future

async def _db_submit_many(fn, sql, params_list, shard_key=None):
    """Как _db_submit, но для executemany-задач: worker выбирается по shard_key
    (если передан — например user_id при батче для одного игрока), иначе
    всегда воркер 0 (безопасный дефолт для батчей вроде лога действий, где
    в одном батче замешаны разные игроки и единого user_id для шардирования нет)."""
    _ensure_db_workers()
    if shard_key is not None:
        worker_idx = shard_key % DB_WORKER_COUNT
    else:
        worker_idx = 0
    future = asyncio.get_event_loop().create_future()
    await _db_queues[worker_idx].put((fn, sql, params_list, future))
    return await future

async def db_exec(sql, params=()):
    await _db_submit(_exec_sync, sql, params)
    if _USERS_WRITE_RE.search(sql):
        if "WHERE user_id = ?" in sql and params:
            _invalidate_user_cache(params[-1])
        else:
            _user_cache.clear()

async def db_exec_many(sql, params_list, shard_key=None):
    """Как db_exec, но один запрос в очередь воркера выполняет executemany
    сразу для списка наборов параметров — используется для батчинга (см.
    _flush_player_log_buffer), чтобы N записей стоили очереди воркера как одна.
    shard_key: если все строки батча относятся к ОДНОМУ user_id (например,
    массовая выдача предметов из кейса), передай его сюда — иначе (батч из
    вперемешку разных игроков, как в логе действий) не передавай, тогда
    батч уйдёт в воркер 0."""
    if not params_list:
        return
    await _db_submit_many(_exec_many_sync, sql, params_list, shard_key)

async def db_query(sql, params=()):
    return await _db_submit(_query_sync, sql, params)

async def db_query_one(sql, params=()):
    rows = await db_query(sql, params)
    return rows[0] if rows else None

USER_COLUMNS = (
    "user_id, username, score, evolution_level, last_farm, coins, active_item, "
    "cases_opened, total_farmed, last_bonus, bonus_streak, levelup_notify, vip_until, hidden_badges, "
    "rebirth_points, rebirth_count, upgrades, last_auto_claim, equipped_items, nickname, top_banned, "
    "ultra_rebirth, auto_evolve, active_potions, brewing_potion, brewing_until, potion_stock, "
    "prestige_points, prestige_upgrades, auto_rebirth, auto_sell, auto_sell_items, craft_points, "
    "promo_badges, chronos_boost_pct, compact_mode, crafts_done, vilon_streak, vilon_boost_until, shown_badges, "
    "kotyara_boost_until, game_banned, admin_role, content_role, is_premium_title, admin_last_give, "
    "first_seen, moderator_event_last, content_reset_last, content_boost_last, content_boost_until, "
    "content_speedup_last, content_bonus_last, evo_hardness_mult, rebirth_hardness_mult"
)

def display_name(username: str, nickname: str = None) -> str:
    """Имя для отображения: ник, если задан, иначе обычный telegram-username."""
    return nickname if nickname else username

async def init_db():
    await db_exec("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            score INTEGER DEFAULT 0,
            evolution_level INTEGER DEFAULT 0,
            last_farm INTEGER DEFAULT 0,
            coins INTEGER DEFAULT 0,
            active_item TEXT,
            cases_opened INTEGER DEFAULT 0,
            total_farmed INTEGER DEFAULT 0,
            last_bonus INTEGER DEFAULT 0,
            bonus_streak INTEGER DEFAULT 0,
            levelup_notify INTEGER DEFAULT 1,
            vip_until INTEGER DEFAULT 0
        )
    """)
    await db_exec("""
        CREATE TABLE IF NOT EXISTS inventory (
            user_id INTEGER,
            item_key TEXT,
            qty INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, item_key)
        )
    """)
    await db_exec("""
        CREATE TABLE IF NOT EXISTS chat_members (
            user_id INTEGER,
            chat_id INTEGER,
            PRIMARY KEY (user_id, chat_id)
        )
    """)
    await db_exec("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    await db_exec("""
        CREATE TABLE IF NOT EXISTS personal_boosts (
            user_id INTEGER PRIMARY KEY,
            multiplier REAL DEFAULT 1,
            until INTEGER DEFAULT 0
        )
    """)
    await db_exec("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER,
            admin_username TEXT,
            command TEXT
        )
    """)
    await db_exec("""
        CREATE TABLE IF NOT EXISTS player_action_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER,
            user_id INTEGER,
            username TEXT,
            command TEXT
        )
    """)
    await db_exec("""
        CREATE INDEX IF NOT EXISTS idx_player_action_log_user_ts
        ON player_action_log (user_id, ts)
    """)
    await db_exec("""
        CREATE TABLE IF NOT EXISTS banned_chats (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            banned_by TEXT,
            banned_at INTEGER
        )
    """)
    await db_exec("""
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            banned_by TEXT,
            banned_at INTEGER,
            reason TEXT DEFAULT 'manual'
        )
    """)
    try:
        await db_exec("ALTER TABLE banned_users ADD COLUMN reason TEXT DEFAULT 'manual'")
    except Exception:
        pass
    await db_exec("""
        CREATE TABLE IF NOT EXISTS promocodes (
            code TEXT PRIMARY KEY,
            reward_type TEXT NOT NULL,
            reward_key TEXT DEFAULT '',
            amount INTEGER NOT NULL,
            activations_left INTEGER NOT NULL,
            created_by TEXT,
            created_at INTEGER
        )
    """)
    await db_exec("""
        CREATE TABLE IF NOT EXISTS promocode_uses (
            user_id INTEGER,
            code TEXT,
            used_at INTEGER,
            PRIMARY KEY (user_id, code)
        )
    """)
    for stmt in (
        "ALTER TABLE users ADD COLUMN levelup_notify INTEGER DEFAULT 1",
        "ALTER TABLE users ADD COLUMN vip_until INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN hidden_badges TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN rebirth_points INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN rebirth_count INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN upgrades TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN last_auto_claim INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN active_item2 TEXT DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN equipped_items TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN nickname TEXT DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN top_banned INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN ultra_rebirth INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN auto_evolve INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN active_potions TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN brewing_potion TEXT DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN brewing_until INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN potion_stock TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN prestige_points INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN prestige_upgrades TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN auto_rebirth INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN auto_sell INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN auto_sell_items TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN craft_points INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN promo_badges TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN chronos_boost_pct INTEGER DEFAULT 100",
        "ALTER TABLE users ADD COLUMN compact_mode INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN crafts_done INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN vilon_streak INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN vilon_boost_until INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN shown_badges TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN kotyara_boost_until INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN game_banned INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN game_banned_snapshot TEXT DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN gold_coin INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN diamond_coin INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN upgrader_level INTEGER DEFAULT 1",
        # ==== Система титулов/привилегий ====
        # admin_role: '' | 'moderator' | 'admin' — взаимоисключающие (одна колонка, выдача
        # одного автоматически стирает другое). Разработчик НЕ хранится тут — вычисляется
        # отдельно через ADMIN_USER_ID (см. is_developer), он всегда один и задан в коде.
        "ALTER TABLE users ADD COLUMN admin_role TEXT DEFAULT ''",
        # content_role: '' | 'tiktoker' | 'youtuber' — тоже взаимоисключающие для простоты
        # (в ТЗ явно не сказано, что они сочетаются, а sочетаются именно с admin_role).
        "ALTER TABLE users ADD COLUMN content_role TEXT DEFAULT ''",
        # is_premium_title: отдельный флаг титула "Премиум" (команда !дать титул премиум) —
        # не связан с VIP (vip_until уже существует) и не связан с admin_role/content_role.
        "ALTER TABLE users ADD COLUMN is_premium_title INTEGER DEFAULT 0",
        # Общий КД на 1 час для ВСЕХ выдающих команд роли 'admin' разом (см. ТЗ: "КД 1 час
        # общий на все команды выдачи"). Храним unix-время последней выдачи.
        "ALTER TABLE users ADD COLUMN admin_last_give INTEGER DEFAULT 0",
        # Unix-время первого обращения к боту — для "Время в боте" в инфо/моя нога. NULL для
        # существующих игроков (мигрировавших до этого патча) — обрабатываем это как "неизвестно".
        "ALTER TABLE users ADD COLUMN first_seen INTEGER DEFAULT NULL",
        # КД 4 часа на команду "!ивент хN M" — только для роли Модератор (см. ТЗ: "ивент
        # (ограничение максимальный буст х5 на 30 минут и то кд ивента 4 часа)"). Разработчик и
        # Админ не ограничены этим полем.
        "ALTER TABLE users ADD COLUMN moderator_event_last INTEGER DEFAULT 0",
        # ==== КД для ютубер/тиктокер команд (?сброс, ?буст, ?ускорение, ?бонус) ====
        "ALTER TABLE users ADD COLUMN content_reset_last INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN content_boost_last INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN content_boost_until INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN content_speedup_last INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN content_bonus_last INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN evo_hardness_mult REAL DEFAULT 1.0",
        "ALTER TABLE users ADD COLUMN rebirth_hardness_mult REAL DEFAULT 1.0",
    ):
        try:
            await db_exec(stmt)
        except Exception:
            pass

async def get_user(user_id: int):
    if user_id in _user_cache:
        return _user_cache[user_id]
    row = await db_query_one(f"SELECT {USER_COLUMNS} FROM users WHERE user_id = ?", (user_id,))
    if row is not None:
        _user_cache[user_id] = row
    return row

async def get_user_by_username(username: str):
    return await db_query_one(f"SELECT {USER_COLUMNS} FROM users WHERE lower(username) = lower(?)", (username,))

async def ensure_user(user_id: int, username: str):
    row = await get_user(user_id)
    if row is None:
        now = int(time.time())
        await db_exec(
            "INSERT INTO users (user_id, username, score, first_seen) VALUES (?, ?, 0, ?)",
            (user_id, username, now),
        )
        # ВАЖНО: должен точно соответствовать порядку и количеству полей в USER_COLUMNS (55 полей) —
        # при добавлении новой колонки в USER_COLUMNS сюда тоже нужно дописать дефолт на том же месте.
        new_row = (
            user_id, username, 0, 0, 0, 0, None, 0, 0, 0, 0, 1, 0, "", 0, 0, "", now, "", None, 0, 0, 0, "",
            None, 0, "", 0, "", 0, 0, "", 0, "", 100, 0, 0, 0, 0, "", 0,
            0, "", "", 0, 0, now, 0, 0, 0, 0, 0, 0, 1.0, 1.0,
        )
        _user_cache[user_id] = new_row
        return new_row
    if row[1] != username:
        await db_exec("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
    return row

async def get_inventory(user_id: int):
    return await db_query("SELECT item_key, qty FROM inventory WHERE user_id = ? AND qty > 0", (user_id,))

async def add_item(user_id: int, item_key: str, qty: int = 1):
    await db_exec(
        "INSERT INTO inventory (user_id, item_key, qty) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id, item_key) DO UPDATE SET qty = qty + excluded.qty",
        (user_id, item_key, qty),
    )

PROMO_TYPE_ALIASES = {
    "ноги": "legs", "нога": "legs", "ног": "legs",
    "эво": "evo", "эволюция": "evo",
    "коин": "coin", "коины": "coin", "монеты": "coin",
    "очкп": "rebirth", "перерождение": "rebirth",
    "крафт": "craft", "очкк": "craft",
}
PROMO_TYPE_COLUMN = {
    "legs": "score",
    "evo": "evolution_level",
    "coin": "coins",
    "rebirth": "rebirth_points",
    "craft": "craft_points",
}
PROMO_TYPE_LABEL = {
    "legs": "🦵 очков ноги",
    "evo": "🧬 очков эволюции",
    "coin": "🪙 монет",
    "rebirth": "🉑 очков перерождения",
    "craft": "💠 очков крафта",
}
# Соответствие внутреннего типа промокода ключу в ADMIN_GIVE_LIMITS (см. Этап 4 системы
# титулов) — для проверки лимита на amount, если промокод создаёт роль Админ, а не Разработчик.
PROMO_TYPE_TO_ADMIN_LIMIT_KEY = {
    "legs": "ноги",
    "evo": "эво",
    "coin": "коин",
    "rebirth": "очкп",
    "craft": "очкк",
}

PROMO_BADGES = {
    "tester":       (PREMIUM_BADGE_TESTER, "Фанат Мику"),
    "support":      (PREMIUM_BADGE_SUPPORT, "Сапорт"),
    "power":        (PREMIUM_BADGE_POWER, "Потужность"),
    "top1_past":    (PREMIUM_BADGE_TOP1_PAST, "Топ 1 в прошлом"),
    "chaos_master": (PREMIUM_BADGE_CHAOS_MASTER, "Мастер Хаоса⚡️"),
    "investor":     (PREMIUM_BADGE_INVESTOR, "Инвестировал в #####"),
}
PROMO_BADGE_ALIASES = {
    "фанат мику": "tester",
    "сапорт": "support",
    "потужность": "power",
    "топ1 в прошлом": "top1_past",
    "топ 1 в прошлом": "top1_past",
    "мастер хаоса": "chaos_master",
    "инвестировал в #####": "investor",
}

# Справочник для команды «помощь бейдж <название>»: ключ (как в badge_list/PROMO_BADGES) ->
# (эмодзи, русские алиасы для поиска, текст объяснения). Алиасы через запятую в подсказке —
# просто самый первый считается «каноничным» именем бейджа.
HELP_BADGES = {
    "owner":       (PREMIUM_OWNER_BADGE, ["владелец", "овнер", "admin", "админ"],
                    "Этот бейдж есть только у владельца бота — выдаётся автоматически по нику, вручную получить нельзя."),
    "vip":         (PREMIUM_VIP_BADGE, ["vip", "вип"],
                    "Этот бейдж даётся всем игрокам у кого есть VIP-статус. Пропадает, если VIP закончился."),
    "evo":         (PREMIUM_BADGE_EVO, ["1+ эволюция", "эволюция", "эво"],
                    "Даётся за первую эволюцию (39 уровень ноги, «ногу мгг»). Один раз пройдёшь эволюцию — бейдж останется навсегда."),
    "case":        (PREMIUM_BADGE_CASE, ["5+ кейсов", "кейсы", "кейс"],
                    "Даётся за открытие 5 или более кейсов (любых, суммарно)."),
    "farm":        (PREMIUM_BADGE_FARM, ["30k нафармлено", "ферма", "фарм"],
                    f"Даётся, когда суммарно нафармлено {BADGE_EVO_TOTAL} очков ноги (считается всё время, не сбрасывается)."),
    "evo5":        (PREMIUM_BADGE_EVO5, ["5 эволюция", "5эво", "5 эво"],
                    "Даётся по достижению 5 уровня эволюции."),
    "tester":      (PREMIUM_BADGE_TESTER, ["фанат мику"],
                    "Выдаётся вручную админом или по промокоду преданным фанатам Мику."),
    "support":     (PREMIUM_BADGE_SUPPORT, ["сапорт", "support"],
                    "Выдаётся вручную админом или по промокоду тем, кто помогает с поддержкой игроков."),
    "power":       (PREMIUM_BADGE_POWER, ["потужность"],
                    "Выдаётся вручную админом или по промокоду — почётный значок за вклад в развитие бота."),
    "top1_past":   (PREMIUM_BADGE_TOP1_PAST, ["топ1 в прошлом", "топ 1 в прошлом", "топ1"],
                    "Выдаётся тем, кто когда-то был на первом месте в топе игроков."),
    "chaos_master": (PREMIUM_BADGE_CHAOS_MASTER, ["мастер хаоса"],
                    "Редкий бейдж, связанный с Шаром Хаоса и Хроносом — выдаётся вручную или по промокоду."),
    "investor":    (PREMIUM_BADGE_INVESTOR, ["инвестировал в #####"],
                    "Выдаётся вручную админом или по промокоду за поддержку проекта."),
}

def find_help_badge_key(query: str):
    """Ищет ключ HELP_BADGES по русскому названию/алиасу. Сначала точное совпадение,
    иначе — по вхождению подстроки в любой из алиасов (как find_item_by_name).
    Возвращает (key, None) при однозначном совпадении, (None, [варианты]) при неоднозначности,
    (None, []) если не найдено."""
    q = (query or "").strip().lower()
    if not q:
        return None, []
    for key, (_, aliases, _) in HELP_BADGES.items():
        if q == key.lower() or q in (a.lower() for a in aliases):
            return key, None
    matches = [key for key, (_, aliases, _) in HELP_BADGES.items() if any(q in a.lower() for a in aliases)]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        matches.sort(key=lambda k: HELP_BADGES[k][1][0])
        return None, matches
    return None, []

def parse_promo_badges(raw: str) -> set:
    return set(x for x in (raw or "").split(",") if x)

def format_promo_badges(badges: set) -> str:
    return ",".join(sorted(badges))

def find_promo_badge_key(name_raw: str):
    """Находит ключ PROMO_BADGES по русскому названию бейджа (из команды создания промокода)."""
    return PROMO_BADGE_ALIASES.get(name_raw.strip().lower())

async def add_promo_badge(user_id: int, badge_key: str):
    row = await db_query_one("SELECT promo_badges FROM users WHERE user_id = ?", (user_id,))
    current = parse_promo_badges(row[0] if row else "")
    current.add(badge_key)
    await db_exec("UPDATE users SET promo_badges = ? WHERE user_id = ?", (format_promo_badges(current), user_id))

def parse_promo_type(raw: str):
    """Разбирает строку типа награды из команды создания промокода.
    Возвращает (reward_type, reward_key) либо None, если тип не распознан.
    "предмет:<ключ>" -> ("item", "<ключ>"); "бейдж" обрабатывается отдельным синтаксисом
    (см. PROMO_CREATE_BADGE_RE); иначе алиас из PROMO_TYPE_ALIASES -> (type, "")."""
    raw = raw.strip().lower()
    if raw.startswith("предмет:") or raw.startswith("предмет "):
        item_key = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 1)[1].strip()
        if item_key not in ITEMS:
            return None
        return ("item", item_key)
    reward_type = PROMO_TYPE_ALIASES.get(raw)
    if not reward_type:
        return None
    return (reward_type, "")

async def apply_promo_reward(user_id: int, reward_type: str, reward_key: str, amount: int):
    """Выдаёт награду промокода игроку. Возвращает текст для показа в ответе (что именно выдано)."""
    if reward_type == "item":
        await add_item(user_id, reward_key, amount)
        emoji, name, _, _ = ITEMS[reward_key]
        return f"{emoji} {esc(name)} ×{amount}"

    if reward_type == "badge":
        await add_promo_badge(user_id, reward_key)
        emoji, name = PROMO_BADGES[reward_key]
        return f"{emoji} бейдж «{esc(name)}»"

    column = PROMO_TYPE_COLUMN[reward_type]
    await db_exec(
        f"UPDATE users SET {column} = {column} + ? WHERE user_id = ?",
        (amount, user_id),
    )
    return f"{amount} {PROMO_TYPE_LABEL[reward_type]}"

async def remove_item(user_id: int, item_key: str, qty: int = 1) -> bool:
    """Списывает qty предмета item_key из инвентаря. Если после списания у игрока не осталось
    ни одной штуки этого предмета, ОН ЖЕ снимается с экипировки (equipped_items) — иначе
    предмет пропадает из инвентаря, но продолжает считаться надетым и вечно давать буст
    (баг: "предмет пропадает с инвентаря, но остаётся экипирован"). Это касается ЛЮБОГО пути
    списания предмета — продажи, крафт-ингредиентов, кражи, admin !снять, команды "снять" — так
    как проверка теперь в самой remove_item, а не в каждом отдельном хендлере."""
    row = await db_query_one("SELECT qty FROM inventory WHERE user_id = ? AND item_key = ?", (user_id, item_key))
    if not row or row[0] < qty:
        return False
    new_qty = row[0] - qty
    await db_exec("UPDATE inventory SET qty = ? WHERE user_id = ? AND item_key = ?", (new_qty, user_id, item_key))
    if new_qty <= 0:
        user_row = await get_user(user_id)
        if user_row and len(user_row) > 18:
            equipped = parse_equipped(user_row[18])
            if item_key in equipped:
                new_equipped = unequip_item(user_row[18], item_key)
                await db_exec("UPDATE users SET equipped_items = ? WHERE user_id = ?", (format_equipped(new_equipped), user_id))
    return True

async def apply_farm_bonuses(user_id: int, active_items, inventory_map: dict, luck_mult: float = 1.0,
                              guaranteed_rebirth: bool = False, coin_magnet_flat: int = 0) -> dict:
    """Считает все монетные пассивки (Странная монета, Тёплая свеча, Монета боготворства) одним
    общим числом монет + бонус Эссенции Бога (монеты гарант, очки перерождения — шанс растёт с
    luck_mult при зелье удачи, luck_mult=1.0 без зелья). guaranteed_rebirth (зелье валюты
    перерождения, см. POTIONS['potion_rebirth_farm']) добавляет ГАРАНТ +1 🉑 за фарм, независимо
    от Эссенции Бога/шанса. coin_magnet_flat (ветка 'coin_magnet', категория 5) добавляет фикс.
    🪙 к каждому фарму, тоже независимо от предметов/шанса. Один UPDATE. Возвращает {'coins': N,
    'rebirth': N, 'evo': 0 (не используется), 'is_god': bool}."""
    coin_bonus = coin_magnet_flat
    if inventory_map.get("strange_coin", 0) > 0:
        coin_bonus += 5
    if inventory_map.get("warm_candle", 0) > 0:
        coin_bonus += 3
    if inventory_map.get("devotion_coin", 0) > 0:
        coin_bonus += 15
        if random.random() < 0.10:
            coin_bonus += 20

    rebirth_bonus = 1 if guaranteed_rebirth else 0
    tier = get_active_unique_tier(active_items)
    is_god = tier in GOD_TIER_LIKE
    if is_god:
        max_coin = 70 if tier == "koshko_amulet" else 50
        coin_bonus += random.randint(1, max_coin)
        rebirth_chance = min(1.0, 0.30 * luck_mult)
        if random.random() < rebirth_chance:
            rebirth_bonus += random.randint(1, 3)

    if coin_bonus or rebirth_bonus:
        await db_exec(
            "UPDATE users SET coins = coins + ?, rebirth_points = rebirth_points + ? "
            "WHERE user_id = ?",
            (coin_bonus, rebirth_bonus, user_id),
        )
    return {"coins": coin_bonus, "rebirth": rebirth_bonus, "evo": 0, "is_god": is_god, "tier": tier}

async def apply_vase_proc(user_id: int, inventory_map: dict, luck_mult: float = 1.0) -> str:
    """Проки пассивных ваз при фарме ног. Срабатывает только самая сильная имеющаяся ваза.
    luck_mult (зелье удачи, усиленное веткой 'potion_booster') делит эффективный ролл на
    luck_mult — то есть повышает шанс на каждый порог в luck_mult раз. luck_mult=1.0 без зелья."""
    roll_scale = 1.0 / luck_mult if luck_mult else 1.0
    if inventory_map.get("godly_vase", 0) > 0:
        roll = random.random() * roll_scale
        if roll < 0.002:
            await db_exec("UPDATE users SET rebirth_points = rebirth_points + 400 WHERE user_id = ?", (user_id,))
            return f"{PREMIUM_GODLY_VASE} СУПЕР УДАЧА! +400🉑"
        if roll < 0.022:
            await db_exec("UPDATE users SET rebirth_points = rebirth_points + 20 WHERE user_id = ?", (user_id,))
            return f"{PREMIUM_GODLY_VASE} +20🉑"
        if roll < 0.122:
            await db_exec("UPDATE users SET rebirth_points = rebirth_points + 10 WHERE user_id = ?", (user_id,))
            return f"{PREMIUM_GODLY_VASE} +10🉑"
        if roll < 0.322:
            await db_exec("UPDATE users SET rebirth_points = rebirth_points + 6 WHERE user_id = ?", (user_id,))
            return f"{PREMIUM_GODLY_VASE} +6🉑"
        if roll < 1.122:
            await db_exec("UPDATE users SET rebirth_points = rebirth_points + 2 WHERE user_id = ?", (user_id,))
            return f"{PREMIUM_GODLY_VASE} +2🉑"
        return ""
    if inventory_map.get("golden_vase", 0) > 0:
        if random.random() * roll_scale < 0.06:
            await db_exec("UPDATE users SET rebirth_points = rebirth_points + 1 WHERE user_id = ?", (user_id,))
            return f"{PREMIUM_GOLDEN_VASE} +1🉑"
        return ""
    if inventory_map.get("old_vase", 0) > 0:
        if random.random() * roll_scale < 0.05:
            await db_exec("UPDATE users SET rebirth_points = rebirth_points + 1 WHERE user_id = ?", (user_id,))
            return f"{PREMIUM_OLD_VASE} +1🉑"
        return ""
    return ""

def _random_booster_pool() -> list:
    """Все выбиваемые/крафтовые бустеры (boost_percent > 0), кроме предметов 1+ уровня крафта
    (см. RECIPES) и кроме любого предмета из NON_TRADABLE_ITEMS — используется шансом на выдачу
    бустера от 🔮 Хвоста Джевила.
    NON_TRADABLE_ITEMS уже помечает все эксклюзивные/уникальные амулеты, короны, кольца и
    эво-предметы (golda, karambit_gold, guitarist_crown, vilon_amulet, miku_ring, star_necklace
    и т.д.) — так что достаточно этой одной проверки, чтобы ни один из них никогда не выпал
    случайно через Хвост Джевила: получить их можно только крафтом или ручной выдачей админа."""
    pool = []
    for key, (_, _, boost_percent, _) in ITEMS.items():
        if boost_percent <= 0:
            continue
        if key in NON_TRADABLE_ITEMS:
            continue
        if key in CONTENT_BONUS_TEXT_ITEMS:
            continue
        recipe = RECIPES.get(key)
        if recipe and recipe.get("level", 0) >= 1:
            continue
        pool.append(key)
    return pool

async def apply_chaos_orb_proc(user_id: int, inventory_map: dict) -> str:
    """🌀 Шар хаоса: ПАССИВНЫЙ эффект — пока лежит в инвентаре (экипировать не нужно),
    шанс 2% при фарме ног поймать бонус-фарму (случайное количество очков ноги от 1 до 10 000 000)."""
    if inventory_map.get("chaos_orb", 0) <= 0:
        return ""
    if random.random() >= CHAOS_ORB_FARM_CHANCE:
        return ""
    bonus = random.randint(CHAOS_ORB_FARM_MIN, CHAOS_ORB_FARM_MAX)
    await db_exec("UPDATE users SET score = score + ? WHERE user_id = ?", (bonus, user_id))
    return f"\n🌀 Шар хаоса: РЕДКИЙ ПРОК! +{bonus} очков ноги!"

async def apply_blazing_necklace_proc(user_id: int, active_items) -> str:
    """🔥📿 Ожерелье пылающей звезды: пока экипировано, при фарме ног — шанс 1.7% дать
    1-15 очков перерождения и независимый шанс 1.2% дать 1-3 очка престижа."""
    if "blazing_star_necklace" not in set(_normalize_active_items(active_items)):
        return ""
    text = ""
    if random.random() < BLAZING_NECKLACE_REBIRTH_CHANCE:
        gained = random.randint(*BLAZING_NECKLACE_REBIRTH_RANGE)
        await db_exec("UPDATE users SET rebirth_points = rebirth_points + ? WHERE user_id = ?", (gained, user_id))
        text += f"\n{ITEMS['blazing_star_necklace'][0]} Ожерелье пылающей звезды: +{gained}🉑!"
    if random.random() < BLAZING_NECKLACE_PRESTIGE_CHANCE:
        gained = random.randint(*BLAZING_NECKLACE_PRESTIGE_RANGE)
        await db_exec("UPDATE users SET prestige_points = prestige_points + ? WHERE user_id = ?", (gained, user_id))
        text += f"\n{ITEMS['blazing_star_necklace'][0]} Ожерелье пылающей звезды: +{gained} очков престижа!"
    return text

async def apply_mastery_lover_proc(user_id: int, active_items) -> tuple[str, float]:
    """🤖 Любитель Мастерства: пока экипирован, при каждом фарме ног независимо проверяются
    5 эффектов — несколько могут сработать за один фарм одновременно:
    0.5% -> временный бонус +0.1% к шансу дропа биткоина (см. apply_bitcoin_proc);
    1% -> +15 очков крафта; 2% -> +200 очков перерождения; 1.5% -> +50 очков престижа;
    3% -> +1 предмет nano-IT.
    Возвращает (текст-приписка, бонус_к_шансу_биткоина_на_этот_фарм)."""
    if "mastery_lover_amulet" not in set(_normalize_active_items(active_items)):
        return "", 0.0
    text = ""
    bitcoin_bonus = 0.0
    if random.random() < MASTERY_LOVER_BITCOIN_CHANCE_CHANCE:
        bitcoin_bonus = MASTERY_LOVER_BITCOIN_CHANCE_BONUS
        text += f"\n{PREMIUM_MASTERY_LOVER_AMULET} Любитель Мастерства: шанс дропа Биткоина повышен на этот фарм!"
    if random.random() < MASTERY_LOVER_CRAFT_CHANCE:
        await db_exec("UPDATE users SET craft_points = craft_points + ? WHERE user_id = ?",
                      (MASTERY_LOVER_CRAFT_AMOUNT, user_id))
        text += f"\n{PREMIUM_MASTERY_LOVER_AMULET} Любитель Мастерства: +{MASTERY_LOVER_CRAFT_AMOUNT}💠 очков крафта!"
    if random.random() < MASTERY_LOVER_REBIRTH_CHANCE:
        await db_exec("UPDATE users SET rebirth_points = rebirth_points + ? WHERE user_id = ?",
                      (MASTERY_LOVER_REBIRTH_AMOUNT, user_id))
        text += f"\n{PREMIUM_MASTERY_LOVER_AMULET} Любитель Мастерства: +{MASTERY_LOVER_REBIRTH_AMOUNT}🉑 очков перерождения!"
    if random.random() < MASTERY_LOVER_PRESTIGE_CHANCE:
        await db_exec("UPDATE users SET prestige_points = prestige_points + ? WHERE user_id = ?",
                      (MASTERY_LOVER_PRESTIGE_AMOUNT, user_id))
        text += f"\n{PREMIUM_MASTERY_LOVER_AMULET} Любитель Мастерства: +{MASTERY_LOVER_PRESTIGE_AMOUNT}🔮 очков престижа!"
    if random.random() < MASTERY_LOVER_NANO_IT_CHANCE:
        await add_item(user_id, "nano_it", 1)
        text += f"\n{PREMIUM_MASTERY_LOVER_AMULET} Любитель Мастерства: +1 {PREMIUM_NANO_IT} nano-IT!"
    return text, bitcoin_bonus

async def apply_star_necklace_proc(user_id: int, active_items) -> str:
    """📿 Ожерелье из звёзд: пока экипировано, при фарме ног — шанс 2.5% выдать
    случайный предмет из Базового кейса (кейс 1, крафт-уровень 1)."""
    if "star_necklace" not in set(_normalize_active_items(active_items)):
        return ""
    if random.random() >= STAR_NECKLACE_CASE1_DROP_CHANCE:
        return ""
    item_key = random.choice(CASES[1]["pool"])
    await add_item(user_id, item_key)
    emoji, name, _, _ = ITEMS[item_key]
    return f"\n{ITEMS['star_necklace'][0]} Ожерелье из звёзд: выпал {emoji} {name}!"

async def apply_elemental_charm_proc(user_id: int, active_items) -> str:
    """🔥 Оберег стихий: пока экипирован, при фарме ног — шанс 3% дать небольшую
    бонус-фарму (5-50 очков ноги)."""
    if "elemental_charm" not in set(_normalize_active_items(active_items)):
        return ""
    if random.random() >= ELEMENTAL_CHARM_PROC_CHANCE:
        return ""
    bonus = random.randint(*ELEMENTAL_CHARM_PROC_RANGE)
    await db_exec("UPDATE users SET score = score + ? WHERE user_id = ?", (bonus, user_id))
    return f"\n{ITEMS['elemental_charm'][0]} Оберег стихий: вспышка стихий! +{bonus} очков ноги!"

async def apply_twilight_amulet_proc(user_id: int, active_items) -> str:
    """🕶️ Амулет сумерек: пока экипирован, при фарме ног — шанс 2% дать
    1 очко перерождения."""
    if "twilight_amulet" not in set(_normalize_active_items(active_items)):
        return ""
    if random.random() >= TWILIGHT_AMULET_PROC_CHANCE:
        return ""
    await db_exec("UPDATE users SET rebirth_points = rebirth_points + ? WHERE user_id = ?",
                  (TWILIGHT_AMULET_REBIRTH_AMOUNT, user_id))
    return f"\n{ITEMS['twilight_amulet'][0]} Амулет сумерек: тень шепчет... +{TWILIGHT_AMULET_REBIRTH_AMOUNT}🉑!"

async def apply_chaos_fang_proc(user_id: int, active_items) -> str:
    """🐺 Клык хаоса: пока экипирован, при фарме ног — шанс 3% дать небольшой
    бонус монет (10-40 🪙)."""
    if "chaos_fang" not in set(_normalize_active_items(active_items)):
        return ""
    if random.random() >= CHAOS_FANG_PROC_CHANCE:
        return ""
    bonus = random.randint(*CHAOS_FANG_COIN_RANGE)
    await db_exec("UPDATE users SET coins = coins + ? WHERE user_id = ?", (bonus, user_id))
    return f"\n{ITEMS['chaos_fang'][0]} Клык хаоса: хищный рывок! +{bonus}🪙!"

async def apply_leg_farm_steal(user_id: int, chat_id: int, active_items) -> str:
    """👑 Корона Гитариста: пока экипирована, шанс LEG_STEAL_CHANCE при фарме ног (🦵/🦿)
    украсть 1 случайный предмет из CASE_SELLABLE_ITEMS (только кейсы 1-2-3 — никогда
    крафтовые/уникальные/эво-предметы) у случайного другого игрока ЭТОГО ЖЕ чата.
    Если у жертвы нечего украсть — тихий промах."""
    if "guitarist_crown" not in set(_normalize_active_items(active_items)):
        return ""
    if random.random() >= LEG_STEAL_CHANCE:
        return ""

    candidates = await db_query(
        "SELECT user_id FROM chat_members WHERE chat_id = ? AND user_id != ?", (chat_id, user_id)
    )
    if not candidates:
        return ""

    victim_id = random.choice(candidates)[0]
    victim_inv = await get_inventory(victim_id)
    stealable = [k for k, q in victim_inv if k in CASE_SELLABLE_ITEMS and q > 0]
    if not stealable:
        return ""

    item_key = random.choice(stealable)
    removed = await remove_item(victim_id, item_key, 1)
    if not removed:
        return ""

    await add_item(user_id, item_key)

    victim_row = await get_user(victim_id)
    victim_name = "игрока" if victim_row is None else display_name(
        victim_row[1], victim_row[19] if len(victim_row) > 19 else None
    )
    emoji, name, _, _ = ITEMS[item_key]
    return f"\n🥷 Кража удалась! Стащено {emoji} {esc(name)} у {esc(victim_name)}!"

async def apply_vilon_amulet_trigger(user_id: int, active_items, vilon_streak: int) -> str:
    """🔱 Амулет Вилона: пока экипирован, каждый фарм ног (🦵/🦿) считается в персональный
    счётчик. На VILON_TRIGGER_EVERY-й раз счётчик сбрасывается и активируется x3 к добыче
    на VILON_BOOST_SECONDS секунд (см. apply_vilon_amulet_boost — сам множитель применяется
    отдельно, эта функция только считает и включает таймер)."""
    if "vilon_amulet" not in set(_normalize_active_items(active_items)):
        return ""

    new_streak = vilon_streak + 1
    if new_streak < VILON_TRIGGER_EVERY:
        await db_exec("UPDATE users SET vilon_streak = ? WHERE user_id = ?", (new_streak, user_id))
        return ""

    boost_until = int(time.time()) + VILON_BOOST_SECONDS
    await db_exec(
        "UPDATE users SET vilon_streak = 0, vilon_boost_until = ? WHERE user_id = ?",
        (boost_until, user_id),
    )
    return f"\n{ITEMS['vilon_amulet'][0]} Амулет Вилона: РЫВОК! x{VILON_BOOST_MULT} к добыче на {VILON_BOOST_SECONDS} сек!"

def apply_vilon_amulet_boost(total: int, vilon_boost_until: int) -> int:
    """Применяет активный x3 от Амулета Вилона к уже посчитанному total, если таймер ещё
    не истёк. Не требует экипировки в момент применения — буст, один раз запущенный,
    доигрывает своё время даже если амулет сняли (как и action-зелья)."""
    if vilon_boost_until and vilon_boost_until > int(time.time()):
        return round(total * VILON_BOOST_MULT)
    return total

async def apply_kotyara_amulet_trigger(user_id: int, active_items) -> str:
    """🐱 Амулет Котяры: пока экипирован, при каждом фарме ног — независимый шанс
    KOTYARA_BOOST_CHANCE (25%) включить x2 к добыче на KOTYARA_BOOST_SECONDS (10) секунд
    (см. apply_kotyara_amulet_boost — сам множитель применяется отдельно, эта функция
    только кидает шанс и включает таймер)."""
    if "kotyara_amulet" not in set(_normalize_active_items(active_items)):
        return ""
    if random.random() >= KOTYARA_BOOST_CHANCE:
        return ""
    boost_until = int(time.time()) + KOTYARA_BOOST_SECONDS
    await db_exec("UPDATE users SET kotyara_boost_until = ? WHERE user_id = ?", (boost_until, user_id))
    return f"{ITEMS['kotyara_amulet'][0]} Амулет Котяры: МУРЛЫК-РЫВОК! x{KOTYARA_BOOST_MULT} на {KOTYARA_BOOST_SECONDS} сек"

def apply_kotyara_amulet_boost(total: int, kotyara_boost_until: int) -> int:
    """Применяет активный x2 от Амулета Котяры к уже посчитанному total, если таймер ещё
    не истёк. Не требует экипировки в момент применения — буст, один раз запущенный,
    доигрывает своё время даже если амулет сняли (как и Амулет Вилона)."""
    if kotyara_boost_until and kotyara_boost_until > int(time.time()):
        return round(total * KOTYARA_BOOST_MULT)
    return total

def apply_coin_tree_farm_roll(gained: int, active_items) -> tuple:
    """🟤 Монета Ногости / 🔶 Монета Бога Ногости: независимый ролл на КАЖДОМ базовом фарме
    ног (после всех обычных множителей, включая x3/x6 boost_percent самих этих монет —
    те уже учтены в get_multiplier()). Срабатывает только самая сильная экипированная монета
    из пары (Бог > обычная), как и остальные парные бустеры в игре.
    Возвращает (новое gained, текст для ответа)."""
    equipped = set(_normalize_active_items(active_items))
    if "godly_nogost_coin" in equipped:
        roll = random.random()
        if roll < 0.10:
            bonus_gained = gained * 5
            return bonus_gained, f"\n{PREMIUM_GODLY_NOGOST_COIN} Монета Бога Ногости: x5 к фарму! +{bonus_gained - gained} очков ноги!"
        if roll < 0.30:
            bonus_gained = gained * 3
            return bonus_gained, f"\n{PREMIUM_GODLY_NOGOST_COIN} Монета Бога Ногости: x3 к фарму! +{bonus_gained - gained} очков ноги!"
        return gained, ""
    if "nogost_coin" in equipped:
        roll = random.random()
        if roll < 0.05:
            bonus_gained = gained * 5
            return bonus_gained, f"\n{PREMIUM_NOGOST_COIN} Монета Ногости: x5 к фарму! +{bonus_gained - gained} очков ноги!"
        if roll < 0.25:
            bonus_gained = gained * 3
            return bonus_gained, f"\n{PREMIUM_NOGOST_COIN} Монета Ногости: x3 к фарму! +{bonus_gained - gained} очков ноги!"
        return gained, ""
    return gained, ""

async def apply_godly_nogost_coin_case_proc(user_id: int, inventory_map: dict) -> str:
    """🔶 Монета Бога Ногости: пассивно (даже не экипирована — работает лёжа в инвентаре, как
    и остальные пассивные монеты) шанс 0.7% при базовом фарме ног дать +100 очков престижа
    и +5 000 000 (5кк) очков ноги одним общим проком за фарм."""
    if inventory_map.get("godly_nogost_coin", 0) <= 0:
        return ""
    if random.random() >= 0.007:
        return ""
    await db_exec(
        "UPDATE users SET score = score + 5000000, prestige_points = prestige_points + 100 WHERE user_id = ?",
        (user_id,),
    )
    return f"\n{PREMIUM_GODLY_NOGOST_COIN} УДАЧА! +100🔮 +5 000 000 👣"

async def apply_craft_coin_proc(user_id: int, inventory_map: dict) -> str:
    """🔘 Монета Крафта: пассивно (лёжа в инвентаре) шанс 5% при отправке в чат сообщения
    с эмодзи ноги (🦵/🦿) дать +1 💠 очко крафта."""
    if inventory_map.get("craft_coin", 0) <= 0:
        return ""
    if random.random() >= 0.05:
        return ""
    await db_exec("UPDATE users SET craft_points = craft_points + 1 WHERE user_id = ?", (user_id,))
    return f"\n{PREMIUM_CRAFT_COIN} +1💠"

async def apply_bitcoin_proc(user_id: int, inventory_map: dict, bonus_chance: float = 0.0) -> str:
    """🟠 Биткоин: пассивно (лёжа в инвентаре) шанс 0.05% при базовом фарме ног дать
    +15 000 000 (15кк) 🪙 монет. bonus_chance — временная прибавка к шансу (например,
    от проков 🤖 Любителя Мастерства) на этот конкретный фарм."""
    if inventory_map.get("bitcoin", 0) <= 0:
        return ""
    if random.random() >= 0.0005 + bonus_chance:
        return ""
    await db_exec("UPDATE users SET coins = coins + 15000000 WHERE user_id = ?", (user_id,))
    return f"\n{PREMIUM_BITCOIN} ДЖЕКПОТ! +15 000 000{PREMIUM_BITCOIN}"

async def apply_rebirth_coin_proc(user_id: int, inventory_map: dict) -> str:
    """🟣 Монета Перерождения: пассивно (лёжа в инвентаре) при КАЖДОМ базовом фарме ног
    даёт +2 🉑 очка перерождения гарантированно."""
    if inventory_map.get("rebirth_coin", 0) <= 0:
        return ""
    await db_exec("UPDATE users SET rebirth_points = rebirth_points + 2 WHERE user_id = ?", (user_id,))
    return f"{PREMIUM_REBIRTH_COIN} +2🉑"

async def apply_chronos_orb_procs(user_id: int, active_items) -> tuple:
    """🔮 Хвост Джевила: пока экипирован, при каждом фарме ног независимо проверяются все
    эффекты — несколько могут сработать за один фарм одновременно.
    Возвращает (текст_для_ответа, сбросить_кулдаун: bool, доп_множитель_фарма: float)."""
    if "chronos_orb" not in set(_normalize_active_items(active_items)):
        return "", False, 1.0

    lines = []
    reset_cd = False
    farm_extra_mult = random.uniform(CHRONOS_ORB_FARM_MULT_MIN, CHRONOS_ORB_FARM_MULT_MAX)
    lines.append(f"\n🔮 Хвост Джевила:")
    lines.append(f"x{farm_extra_mult:.2f}")

    if random.random() < CHRONOS_ORB_REBIRTH_CHANCE:
        amount = random.randint(CHRONOS_ORB_REBIRTH_MIN, CHRONOS_ORB_REBIRTH_MAX)
        await db_exec("UPDATE users SET rebirth_points = rebirth_points + ? WHERE user_id = ?", (amount, user_id))
        lines.append(f"+{amount} 🉑")

    if random.random() < CHRONOS_ORB_COIN_CHANCE:
        amount = random.randint(CHRONOS_ORB_COIN_MIN, CHRONOS_ORB_COIN_MAX)
        await db_exec("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, user_id))
        lines.append(f"+{amount} 🪙")

    if random.random() < CHRONOS_ORB_LEGS_CHANCE:
        amount = random.randint(CHRONOS_ORB_LEGS_MIN, CHRONOS_ORB_LEGS_MAX)
        await db_exec("UPDATE users SET score = score + ? WHERE user_id = ?", (amount, user_id))
        lines.append(f"+{amount} 👣")

    if random.random() < CHRONOS_ORB_NO_CD_CHANCE:
        reset_cd = True
        lines.append("кулдаун обнулён")

    if random.random() < CHRONOS_ORB_PRESTIGE_CHANCE:
        amount = random.randint(CHRONOS_ORB_PRESTIGE_MIN, CHRONOS_ORB_PRESTIGE_MAX)
        if amount > 0:
            await db_exec("UPDATE users SET prestige_points = prestige_points + ? WHERE user_id = ?", (amount, user_id))
            lines.append(f"+{amount} 🔮")

    if random.random() < CHRONOS_ORB_POTION_CHANCE:
        potion_pool = [k for k in POTION_ORDER if k not in ("potion_evo_reset", "potion_rebirth_reset", "potion_debuff")]
        potion_key = random.choice(potion_pool)
        stock_row = await db_query_one("SELECT potion_stock FROM users WHERE user_id = ?", (user_id,))
        stock = parse_potion_stock(stock_row[0] if stock_row else "")
        stock[potion_key] = stock.get(potion_key, 0) + 1
        await db_exec("UPDATE users SET potion_stock = ? WHERE user_id = ?", (format_potion_stock(stock), user_id))
        cfg = POTIONS[potion_key]
        lines.append(f"+1 {cfg['emoji']} {esc(cfg['name'])}")

    if random.random() < CHRONOS_ORB_BOOSTER_CHANCE:
        pool = _random_booster_pool()
        if pool:
            booster_key = random.choice(pool)
            await add_item(user_id, booster_key, 1)
            emoji, name, _, _ = ITEMS[booster_key]
            lines.append(f"+1 {emoji} {esc(name)}")

    if random.random() < CHRONOS_ORB_BADGE_CHANCE:
        await add_promo_badge(user_id, "chaos_master")
        emoji, name = PROMO_BADGES["chaos_master"]
        lines.append(f"БЕЙДЖ {emoji} «{esc(name)}»!!!")

    if random.random() < CHRONOS_ORB_STRANGE_COIN_CHANCE:
        await add_item(user_id, "strange_coin", 1)
        lines.append(f"+1 {ITEMS['strange_coin'][0]} Странная монета")

    if random.random() < CHRONOS_ORB_OLD_VASE_CHANCE:
        await add_item(user_id, "old_vase", 1)
        lines.append(f"+1 {ITEMS['old_vase'][0]} Старая ваза")

    if len(lines) == 2:
        # Только заголовок + множитель сработали, ни один из остальных бонусов не
        # выпал — держим их на одной строке, чтобы не плодить пустой перенос
        # "Хвост Джевила:" отдельно от "x2.50" без единого доп. эффекта рядом.
        return f"{lines[0]} {lines[1]}", reset_cd, farm_extra_mult
    return lines[0] + " " + " · ".join(lines[1:]), reset_cd, farm_extra_mult

async def chronos_orb_boost_loop():
    """Фоновый таск: раз в CHRONOS_BOOST_INTERVAL (5 мин) пересчитывает рандомный % буста
    (10-400%) для ВСЕХ игроков сразу — не только для тех, у кого экипирован Хвост Джевила
    (дёшево одним UPDATE, а не по каждому фарму), см. get_multiplier(). Первый пересчёт —
    сразу при старте бота, чтобы буст не простаивал на 0%/100% до первого 5-минутного тика."""
    while True:
        try:
            new_pct = random.randint(CHRONOS_BOOST_MIN, CHRONOS_BOOST_MAX)
            await db_exec("UPDATE users SET chronos_boost_pct = ?", (new_pct,))
        except Exception as e:
            print(f"chronos_orb_boost_loop ошибка: {e}")
        await asyncio.sleep(CHRONOS_BOOST_INTERVAL)

AUTO_LOG_CLEANUP_INTERVAL = 24 * 60 * 60
AUTO_AUDIT_LOG_DAYS = 7
AUTO_PLAYER_LOG_DAYS = 2

async def auto_log_cleanup_loop():
    """Фоновый таск: раз в сутки сам чистит старые записи логов — те же сроки,
    что и дефолты ручных команд !чистлоги / !чистлоги игроки. player_action_log
    пишется на КАЖДУЮ команду каждого игрока (см. ThrottleMiddleware) и без
    регулярной чистки растёт быстрее всего, раздувая БД и, как следствие, время
    отклика на запросы к ней. Первый прогон — не сразу при старте (сон в начале
    цикла), чтобы не толкаться с init_db на старте бота."""
    while True:
        await asyncio.sleep(AUTO_LOG_CLEANUP_INTERVAL)
        try:
            audit_cutoff = int(time.time()) - AUTO_AUDIT_LOG_DAYS * 86400
            await db_exec("DELETE FROM audit_log WHERE ts < ?", (audit_cutoff,))
            player_cutoff = int(time.time()) - AUTO_PLAYER_LOG_DAYS * 86400
            await db_exec("DELETE FROM player_action_log WHERE ts < ?", (player_cutoff,))
        except Exception as e:
            print(f"auto_log_cleanup_loop ошибка: {e}")

async def is_event_active() -> bool:
    active, _ = await get_event_state()
    return active

_event_state_cache = {"value": None, "until": 0.0}
_EVENT_STATE_TTL = 3.0

async def get_event_state():
    """Возвращает (активен: bool, множитель: float) с учётом автоистечения по времени.
    Кэшируется на _EVENT_STATE_TTL секунд — см. _event_state_cache."""
    now_mono = time.monotonic()
    if _event_state_cache["value"] is not None and now_mono < _event_state_cache["until"]:
        return _event_state_cache["value"]

    rows = await db_query(
        "SELECT key, value FROM settings WHERE key IN ('event_active', 'event_multiplier', 'event_until')"
    )
    d = {k: v for k, v in rows}
    if d.get("event_active") != "1":
        result = (False, 1.0)
    else:
        until = int(d.get("event_until") or 0)
        if until and int(time.time()) > until:
            await db_exec("UPDATE settings SET value = '0' WHERE key = 'event_active'")
            result = (False, 1.0)
        else:
            mult = float(d.get("event_multiplier") or 2)
            result = (True, mult)

    _event_state_cache["value"] = result
    _event_state_cache["until"] = now_mono + _EVENT_STATE_TTL
    return result

def _invalidate_event_state_cache():
    _event_state_cache["value"] = None

async def get_event_multiplier() -> float:
    active, mult = await get_event_state()
    return mult if active else 1.0

async def get_personal_multiplier(user_id: int) -> float:
    """Личный временный буст фермы игроку (!мультипликатор ферма), с автоистечением."""
    row = await db_query_one("SELECT multiplier, until FROM personal_boosts WHERE user_id = ?", (user_id,))
    if not row:
        return 1.0
    multiplier, until = row
    if until and int(time.time()) > until:
        await db_exec("DELETE FROM personal_boosts WHERE user_id = ?", (user_id,))
        return 1.0
    return float(multiplier)

async def log_admin_action(message: Message):
    admin_username = message.from_user.username or str(message.from_user.id)
    await db_exec(
        "INSERT INTO audit_log (ts, admin_username, command) VALUES (?, ?, ?)",
        (int(time.time()), admin_username, message.text.strip()[:200]),
    )

PLAYER_LOG_MIN_INTERVAL = 1.0
_player_log_last = {}
_player_log_skipped = {}
_player_log_calls_since_cleanup = 0
_PLAYER_LOG_CLEANUP_EVERY = 500

PLAYER_LOG_FLUSH_INTERVAL = 5.0
_player_log_buffer: list = []

def _cleanup_player_log_throttle(now: float):
    ttl = PLAYER_LOG_MIN_INTERVAL * 20
    stale = [uid for uid, t in _player_log_last.items() if now - t > ttl]
    for uid in stale:
        del _player_log_last[uid]
        _player_log_skipped.pop(uid, None)

async def _log_player_action(user_id: int, username: str, text: str):
    global _player_log_calls_since_cleanup
    now = time.monotonic()
    last = _player_log_last.get(user_id, 0)
    if now - last < PLAYER_LOG_MIN_INTERVAL:
        _player_log_skipped[user_id] = _player_log_skipped.get(user_id, 0) + 1
        return
    skipped = _player_log_skipped.pop(user_id, 0)
    _player_log_last[user_id] = now

    _player_log_calls_since_cleanup += 1
    if _player_log_calls_since_cleanup >= _PLAYER_LOG_CLEANUP_EVERY:
        _player_log_calls_since_cleanup = 0
        _cleanup_player_log_throttle(now)

    command = text.strip()[:200]
    if skipped:
        command = f"{command} [+{skipped} пропущено за <{PLAYER_LOG_MIN_INTERVAL:.0f}с]"
    _player_log_buffer.append((int(time.time()), user_id, username, command))

async def _flush_player_log_buffer():
    """Фоновый цикл: раз в PLAYER_LOG_FLUSH_INTERVAL сек сбрасывает накопленные
    записи player_action_log ОДНИМ запросом (executemany на стороне воркера),
    вместо отдельного INSERT на каждое действие игрока."""
    while True:
        await asyncio.sleep(PLAYER_LOG_FLUSH_INTERVAL)
        if not _player_log_buffer:
            continue
        batch, _player_log_buffer[:] = _player_log_buffer[:], []
        try:
            await db_exec_many(
                "INSERT INTO player_action_log (ts, user_id, username, command) VALUES (?, ?, ?, ?)",
                batch,
            )
        except Exception as e:
            print(f"_flush_player_log_buffer ошибка: {e}")

async def track_membership(user_id: int, chat_id: int):
    await db_exec("INSERT OR IGNORE INTO chat_members (user_id, chat_id) VALUES (?, ?)", (user_id, chat_id))

async def _has_been_seen_in_chat(user_id: int, chat_id: int) -> bool:
    """Уже писал ли этот юзер в ЭТОМ чате раньше (есть запись в chat_members).
    Используется SpamProtectionMiddleware ДО track_membership — если проверять
    после записи, 'новизна' юзера в чате терялась бы на первом же сообщении."""
    row = await db_query_one(
        "SELECT 1 FROM chat_members WHERE user_id = ? AND chat_id = ?", (user_id, chat_id)
    )
    return row is not None

async def get_all_chat_ids():
    rows = await db_query("SELECT DISTINCT chat_id FROM chat_members")
    return [r[0] for r in rows]

async def build_top(chat_id, order_column: str, limit: int = 10):
    if chat_id is None:
        rows = await db_query(
            f"SELECT username, score, evolution_level, coins, cases_opened, total_farmed, vip_until, shown_badges, rebirth_points, rebirth_count, nickname, ultra_rebirth, promo_badges, bonus_streak, prestige_points, crafts_done, evo_hardness_mult, rebirth_hardness_mult "
            f"FROM users WHERE (top_banned IS NULL OR top_banned = 0) AND (game_banned IS NULL OR game_banned = 0) ORDER BY {order_column} DESC LIMIT ?",
            (limit,),
        )
    else:
        rows = await db_query(
            f"""SELECT u.username, u.score, u.evolution_level, u.coins, u.cases_opened, u.total_farmed, u.vip_until, u.shown_badges, u.rebirth_points, u.rebirth_count, u.nickname, u.ultra_rebirth, u.promo_badges, u.bonus_streak, u.prestige_points, u.crafts_done, u.evo_hardness_mult, u.rebirth_hardness_mult
                FROM users u JOIN chat_members cm ON u.user_id = cm.user_id
                WHERE cm.chat_id = ? AND (u.top_banned IS NULL OR u.top_banned = 0) AND (u.game_banned IS NULL OR u.game_banned = 0) ORDER BY u.{order_column} DESC LIMIT ?""",
            (chat_id, limit),
        )
    return rows

def is_vip_active(vip_until: int) -> bool:
    return bool(vip_until) and vip_until > int(time.time())

def _percent_label(item_key: str, percent: int) -> str:
    """Подпись буста для кнопок/списков. chronos_orb — спец-случай: у него рандомный
    буст 10-400% (пересчитывается раз в 5 мин), фикс. число тут вводило бы в заблуждение."""
    if item_key == "chronos_orb":
        return "+10-400%, рандом"
    return f"+{percent}%"

def inventory_keyboard(inventory_rows, active_item: str, user_id: int) -> InlineKeyboardMarkup:
    rows = []
    for item_key, qty in inventory_rows:
        if item_key in PASSIVE_ITEMS:
            continue
        emoji, name, percent, _ = ITEMS[item_key]
        is_equipped = active_item == item_key
        mark = " ✅" if is_equipped else ""
        rows.append([InlineKeyboardButton(
            text=f"{name} {plain_emoji(emoji)} ({_percent_label(item_key, percent)}) x{qty}{mark}",
            callback_data=f"equip:{user_id}:{item_key}",
            style="success" if is_equipped else None,
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def get_chat(event):
    if isinstance(event, Message):
        return event.chat
    if isinstance(event, CallbackQuery) and event.message:
        return event.message.chat
    return None

_leg_farm_last: dict = {}

FLOOD_WINDOW_SECONDS = 3
FLOOD_MESSAGE_LIMIT = 10
_flood_timestamps: dict = {}

class FloodBanMiddleware(BaseMiddleware):
    """Защита от 'продвинутых' спам-плагинов, которые шлют произвольный текст без
    узнаваемых команд (в отличие от PluginSpamMiddleware, которая ловит именно
    '.spam'-подобные команды) — тут триггер чисто по ЧАСТОТЕ: FLOOD_MESSAGE_LIMIT
    сообщений за FLOOD_WINDOW_SECONDS от одного юзера = автобан, независимо от
    текста. Скользящее окно на deque timestamps в памяти (не в БД — на такой
    частоте лишний запрос в БД на каждое сообщение был бы дороже самой защиты).
    Стоит САМОЙ ПЕРВОЙ (даже раньше ChatBanMiddleware/GameBanMiddleware), чтобы
    считать вообще все входящие сообщения от юзера, а не только те, что прошли
    остальные фильтры — иначе флудер мог бы 'прятать' часть сообщений от счётчика.
    В отличие от остальных автобанов, юзер получает объяснение с контактом
    овнера (FLOOD_WINDOW_SECONDS достаточно мал, что случайный частый фарм
    маловероятен, но всё же не исключён — например, двойные тапы по кнопкам).

    Компромисс по памяти: _flood_timestamps не чистит записи неактивных юзеров
    (после окна там остаётся deque с 1 старым timestamp навсегда) — на масштабах
    этого бота это несколько байт на когда-либо писавшего юзера, не критично;
    если игроков станет на порядки больше, стоит добавить периодическую очистку
    по last-seen."""
    async def __call__(self, handler, event, data):
        if not isinstance(event, Message) or not event.from_user:
            return await handler(event, data)
        user = event.from_user
        if user.id == ADMIN_USER_ID or user.is_bot:
            return await handler(event, data)
        if user.id in _game_banned_ids:
            return await handler(event, data)

        now = time.monotonic()
        stamps = _flood_timestamps.get(user.id)
        if stamps is None:
            stamps = deque()
            _flood_timestamps[user.id] = stamps
        stamps.append(now)
        while stamps and now - stamps[0] > FLOOD_WINDOW_SECONDS:
            stamps.popleft()

        if len(stamps) < FLOOD_MESSAGE_LIMIT:
            return await handler(event, data)

        _flood_timestamps.pop(user.id, None)
        await _apply_game_ban(user.id, user.username)
        chat = event.chat
        if chat.type in ("group", "supergroup"):
            await track_membership(user.id, chat.id)
        try:
            await event.reply(TEXTS["flood_ban_1"].format(v0=ADMIN_USERNAME))
        except Exception:
            pass
        return

class ChatBanMiddleware(BaseMiddleware):
    """Полный чёрный список чатов (!бан чат "название"): бот вообще не реагирует
    ни на что из забаненного чата — ни командами, ни ответом на callback_query.
    Стоит ПЕРЕД GameBanMiddleware: если чат целиком в бане, даже не важно, кто
    именно в нём пишет — не тратим время на проверку конкретного юзера.
    Проверка по in-memory _banned_chat_ids, не по БД — как и у GameBanMiddleware,
    чтобы не делать SELECT на каждый апдейт."""
    async def __call__(self, handler, event, data):
        chat = get_chat(event)
        if chat is not None and chat.id in _banned_chat_ids:
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer()
                except Exception:
                    pass
            return
        return await handler(event, data)

class GameBanMiddleware(BaseMiddleware):
    """Полный игровой бан: бот вообще не реагирует на забаненного — ни командами,
    ни фолбэками, ни даже ответом на callback_query (иначе кнопка у него зависала
    бы с 'часиками' до таймаута Telegram). Стоит САМОЙ ПЕРВОЙ в цепочке (outer_
    middleware, до AliasNormalize), чтобы забаненный не долетал вообще ни до
    ThrottleMiddleware (не тратим место в _log_player_action), ни до самих
    хендлеров. Проверка по in-memory _game_banned_ids, а не по БД — чтобы не
    делать SELECT на каждый апдейт от каждого юзера в чате."""
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user is not None and user.id in _game_banned_ids:
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer()
                except Exception:
                    pass
            return
        return await handler(event, data)

class AliasNormalizeMiddleware(BaseMiddleware):
    """Переписывает message.text на канонический вид команды ДО того, как текст попадёт
    в остальные middleware/хендлеры (is_command_text, ThrottleMiddleware, сами @dp.message)."""
    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.text:
            new_text = apply_command_aliases(event.text)
            if new_text != event.text:
                event = event.model_copy(update={"text": new_text})
        return await handler(event, data)

class PrivateBlockMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        chat = get_chat(event)
        if chat is not None and chat.type == "private":
            user = event.from_user
            if not (user and (user.username or "").lower() == ADMIN_USERNAME.lower()):
                if isinstance(event, CallbackQuery):
                    try:
                        await event.answer()
                    except Exception:
                        pass
                return
        return await handler(event, data)

class SpamProtectionMiddleware(BaseMiddleware):
    """Автобан от спама в приватных супергруппах (по просьбе пользователя): если
    бота добавили в супергруппу БЕЗ публичной ссылки (chat.username is None —
    попасть можно только по инвайту вида t.me/+xxxx, а не t.me/name), то ПЕРВОЕ
    сообщение боту от любого юзера в этой группе (кроме овнера и других ботов)
    сразу даёт игровой бан (game_banned, НЕ Telegram-бан в самом чате — это
    оговорено отдельно). Публичные супергруппы (chat.username есть) не трогает.

    'Новый в чате' проверяем по chat_members (та же таблица, что и обычный
    учёт членства) — поэтому регистрируется ДО TrackMembershipMiddleware: если
    сначала записать юзера в chat_members, а потом проверять 'новый ли он',
    проверка всегда была бы False и защита никогда бы не сработала."""
    async def __call__(self, handler, event, data):
        if not isinstance(event, Message) or not event.from_user:
            return await handler(event, data)
        chat = event.chat
        user = event.from_user
        if chat.type not in ("group", "supergroup"):
            return await handler(event, data)
        if chat.username is not None:
            return await handler(event, data)
        if user.id == ADMIN_USER_ID or user.is_bot:
            return await handler(event, data)
        if user.id in _game_banned_ids:
            return await handler(event, data)
        already_seen = await _has_been_seen_in_chat(user.id, chat.id)
        if already_seen:
            return await handler(event, data)
        try:
            member = await bot.get_chat_member(chat.id, user.id)
            if member.status in ("creator", "administrator"):
                await track_membership(user.id, chat.id)
                return await handler(event, data)
        except Exception:
            pass

        await _apply_game_ban(user.id, user.username)
        await track_membership(user.id, chat.id)
        return

_PLUGIN_SPAM_RE = re.compile(r"spam|спам", re.IGNORECASE)

class PluginSpamMiddleware(BaseMiddleware):
    """Автобан за похожие на команды спам-плагинов сообщения (по просьбе
    пользователя): '.spam', '.flowspam' и т.п. — точка в начале сообщения И
    'spam'/'спам' где-то дальше в тексте (регистр не важен). НЕ триггерится
    словом с точки без spam/спам (например '.troll') — это осознанно узкое
    правило, широкое совпадение по одной точке банило бы слишком много
    случайных сообщений. Работает везде (не только в приватных супергруппах,
    в отличие от SpamProtectionMiddleware) и от кого угодно кроме овнера —
    команда плагина-спамера сама по себе однозначный сигнал, независимо от
    типа чата или того, писал ли юзер раньше."""
    async def __call__(self, handler, event, data):
        if not isinstance(event, Message) or not event.from_user or not event.text:
            return await handler(event, data)
        user = event.from_user
        if user.id == ADMIN_USER_ID or user.is_bot:
            return await handler(event, data)
        if user.id in _game_banned_ids:
            return await handler(event, data)
        text = event.text.strip()
        if not text.startswith(".") or not _PLUGIN_SPAM_RE.search(text[1:]):
            return await handler(event, data)

        await _apply_game_ban(user.id, user.username)
        chat = event.chat
        if chat.type in ("group", "supergroup"):
            await track_membership(user.id, chat.id)
        return

class TrackMembershipMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.chat.type in ("group", "supergroup") and event.from_user:
            await track_membership(event.from_user.id, event.chat.id)
        return await handler(event, data)

class ThrottleMiddleware(BaseMiddleware):
    """Троттлинг для текстовых команд."""
    def __init__(self, rate: float = 1.5):
        self.rate = rate
        self.last_call = {}

    async def __call__(self, handler, event, data):
        user_id = event.from_user.id if event.from_user else None
        if user_id is None:
            return await handler(event, data)

        text = getattr(event, "text", None)
        if not text or not is_command_text(text):
            return await handler(event, data)

        username = event.from_user.username or str(user_id)
        asyncio.create_task(_log_player_action(user_id, username, text))

        now = time.monotonic()
        key = (user_id, "cmd")
        if now - self.last_call.get(key, 0) < self.rate:
            return
        self.last_call[key] = now
        return await handler(event, data)

class CallbackThrottleMiddleware(BaseMiddleware):
    """Троттлинг для инлайн-кнопок. Короткий кулдаун (350-500мс) и, что критично,
    ВСЕГДА отвечает на callback_query — иначе Telegram держит кнопку в состоянии
    "загрузка" до собственного таймаута, что выглядит как зависшая/незажимаемая кнопка.

    ВАЖНО: ключ (user_id, callback_data) почти всегда уникален (страница/предмет/id
    внутри callback_data), поэтому last_call растёт без ограничений и никогда не
    чистится сам — за часы работы с активной аудиторией это утечка памяти и
    постепенное замедление (в т.ч. ощущается как "кнопки тормозят"). Раз в
    CLEANUP_EVERY вызовов выбрасываем протухшие записи (старше rate * 20)."""
    CLEANUP_EVERY = 500

    def __init__(self, rate: float = 0.4):
        self.rate = rate
        self.last_call = {}
        self._calls_since_cleanup = 0

    def _cleanup(self, now: float):
        ttl = self.rate * 20
        stale = [k for k, t in self.last_call.items() if now - t > ttl]
        for k in stale:
            del self.last_call[k]

    async def __call__(self, handler, event: CallbackQuery, data):
        user_id = event.from_user.id if event.from_user else None
        if user_id is None:
            return await handler(event, data)

        now = time.monotonic()
        key = (user_id, event.data)
        if now - self.last_call.get(key, 0) < self.rate:
            try:
                await event.answer()
            except Exception:
                pass
            return
        self.last_call[key] = now

        self._calls_since_cleanup += 1
        if self._calls_since_cleanup >= self.CLEANUP_EVERY:
            self._calls_since_cleanup = 0
            self._cleanup(now)

        return await handler(event, data)

class StaleCallbackGuardMiddleware(BaseMiddleware):
    """Многие callback-хендлеры делают callback.data.split(":") и int(parts[N]) без
    защиты, полагаясь на то, что бот сам генерирует callback_data. Это верно почти
    всегда — но если формат callback_data когда-нибудь поменяется (новая версия
    бота), кнопки под СТАРЫМИ сообщениями (отправленными до обновления) начнут
    падать с ValueError/IndexError прямо на парсинге, ДО вызова callback.answer().
    Без этой страховки такая кнопка виснет с "часиками" до таймаута Telegram —
    тот же симптом, что чинили в safe_edit_text, только с другим триггером.
    Ловим узко (только ValueError/IndexError) — остальные ошибки идут в общий
    @dp.errors() как и раньше, тут ничего не маскируем сверх этого."""
    async def __call__(self, handler, event: CallbackQuery, data):
        try:
            return await handler(event, data)
        except (ValueError, IndexError):
            try:
                await event.answer("Кнопка устарела, обнови меню заново.", show_alert=True)
            except Exception:
                pass
            return

dp.callback_query.outer_middleware(ChatBanMiddleware())
dp.callback_query.outer_middleware(GameBanMiddleware())
dp.callback_query.middleware(StaleCallbackGuardMiddleware())

dp.message.outer_middleware(FloodBanMiddleware())
dp.message.outer_middleware(ChatBanMiddleware())
dp.message.outer_middleware(GameBanMiddleware())
dp.message.outer_middleware(AliasNormalizeMiddleware())
dp.message.outer_middleware(SpamProtectionMiddleware())
dp.message.outer_middleware(PluginSpamMiddleware())
dp.message.middleware(TrackMembershipMiddleware())
dp.message.middleware(ThrottleMiddleware(0.6))
dp.callback_query.middleware(CallbackThrottleMiddleware(0.15))

_last_leg_reply = {}

def _fmt_chat(chat) -> str:
    if chat is None:
        return "?"
    title = getattr(chat, "title", None)
    if title:
        return f"{chat.id} ({title})"
    return str(chat.id)

def _fmt_user(user) -> str:
    if user is None:
        return "?"
    uname = f"@{user.username}" if getattr(user, "username", None) else "без username"
    return f"{user.id} ({uname})"

def _extract_error_context(update) -> dict:
    """Достаёт из Update максимум контекста для лога: кто, где, что именно
    отправил (текст команды / callback_data), чтобы по логу можно было сразу
    понять КАКАЯ команда и У КОГО упала, а не только сам traceback."""
    ctx = {
        "kind": "?", "user": "?", "chat": "?", "content": "?",
    }
    message = getattr(update, "message", None)
    if message is not None:
        ctx["kind"] = "message"
        ctx["user"] = _fmt_user(getattr(message, "from_user", None))
        ctx["chat"] = _fmt_chat(getattr(message, "chat", None))
        ctx["content"] = message.text or message.caption or "<без текста>"
        return ctx
    callback = getattr(update, "callback_query", None)
    if callback is not None:
        ctx["kind"] = "callback_query"
        ctx["user"] = _fmt_user(getattr(callback, "from_user", None))
        ctx["chat"] = _fmt_chat(getattr(callback.message, "chat", None)) if callback.message else "?"
        ctx["content"] = callback.data or "<без data>"
        return ctx
    pre_checkout = getattr(update, "pre_checkout_query", None)
    if pre_checkout is not None:
        ctx["kind"] = "pre_checkout_query"
        ctx["user"] = _fmt_user(getattr(pre_checkout, "from_user", None))
        ctx["content"] = f"invoice_payload={pre_checkout.invoice_payload!r}"
        return ctx
    return ctx

@dp.errors()
async def error_handler(event: ErrorEvent):
    """ВАЖНО (баг, который ломал ВСЕ текстовые команды молча): в aiogram 3.x хендлер
    @dp.errors() получает ОДИН аргумент — объект ErrorEvent (с .update и .exception
    внутри), а не два отдельных позиционных (event, exception), как было раньше в
    aiogram 2.x. Со старой сигнатурой def error_handler(event, exception) aiogram на
    каждый вызов бросал TypeError ("missing 1 required positional argument") ВНУТРИ
    самого обработчика ошибок — а это значит, что при любом исключении в любом
    хендляре (farm/эволюция/перерождение/...) юзер не получал вообще ничего: ни
    результата команды, ни даже фолбэк-сообщения "попробуй ещё раз", потому что
    сам механизм отправки этого фолбэка падал ещё до отправки. Симптом ровно такой,
    какой был на скрине: команда молчит всегда, при любом отдельном вызове, без
    исключений в логах (потому что traceback.print_exc() тоже не успевал выполниться
    в старой версии — TypeError происходил на уровне вызова хендлера aiogram'ом).
    Теперь сигнатура правильная: exception достаём из event.exception.

    РАСШИРЕННЫЙ ЛОГ: раньше лог был по сути только repr(exception) + голый traceback
    в stderr — по нему нельзя было понять КТО вызвал команду, КАКУЮ именно команду
    и в КАКОМ чате, а после появления DB_WORKER_COUNT (см. _pick_worker) ещё и на
    КАКОМ воркере БД это случилось (это ключевое для диагностики протухших
    соединений — см. _run_with_reconnect). Теперь одна строка лога содержит время,
    тип апдейта, юзера, чат, содержимое команды/callback_data, воркер БД (если
    применимо) и полный traceback — и всё это ещё и уходит админу в Telegram,
    а не только в консоль хостинга, которую не всегда удобно смотреть."""
    exception = event.exception

    if isinstance(exception, TelegramRetryAfter):
        await asyncio.sleep(exception.retry_after)
        return True

    import traceback
    tb_text = traceback.format_exc()
    ctx = _extract_error_context(event.update)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    worker_info = ""
    try:
        last_sql = getattr(exception, "_bot_last_sql", None)
        if last_sql is not None:
            worker_idx = getattr(exception, "_bot_worker_idx", "?")
            last_params = getattr(exception, "_bot_last_params", None)
            worker_info = f"\nDB воркер: {worker_idx}/{DB_WORKER_COUNT} | SQL: {last_sql[:200]!r} | params: {last_params!r}"
    except Exception:
        pass

    log_lines = [
        "=" * 70,
        f"[{ts}] Необработанная ошибка ({ctx['kind']})",
        f"Юзер: {ctx['user']} | Чат: {ctx['chat']}",
        f"Содержимое: {ctx['content']!r}",
        f"Исключение: {type(exception).__name__}: {exception!r}{worker_info}",
        tb_text.rstrip(),
        "=" * 70,
    ]
    log_text = "\n".join(log_lines)
    print(log_text)

    try:
        if ADMIN_USER_ID:
            import html as _html
            # bot работает с parse_mode=HTML (см. DefaultBotProperties выше) — без
            # экранирования '<'/'>'/'&' в traceback или в тексте команды сообщение
            # админу падало бы с TelegramBadRequest и лог до него бы не долетал.
            safe_content = _html.escape(str(ctx["content"]))
            safe_worker_info = _html.escape(worker_info)
            safe_tb = _html.escape(tb_text[-3500:])
            admin_report = (
                f"🛑 Ошибка [{ts}]\n"
                f"Тип: {ctx['kind']} | Юзер: {ctx['user']} | Чат: {ctx['chat']}\n"
                f"Содержимое: {safe_content}\n"
                f"{type(exception).__name__}: {_html.escape(str(exception))}{safe_worker_info}\n\n"
                f"<pre>{safe_tb}</pre>"
            )
            await bot.send_message(ADMIN_USER_ID, admin_report[:4090])
    except Exception as admin_log_e:
        print(f"Не удалось отправить лог ошибки админу: {admin_log_e!r}")

    try:
        message = getattr(event.update, "message", None)
        if message is not None:
            await message.reply("⚠️ Что-то пошло не так при обработке команды, попробуй ещё раз.")
    except Exception:
        pass

    return True

async def maybe_announce_levelup(message: Message, username: str, old_score: int, new_score: int,
                                  evolution_level: int, notify: bool, rebirth_count: int = 0,
                                  ultra_rebirth: bool = False, evo_mult: float = 1.0, rebirth_mult: float = 1.0):
    if not notify:
        return
    old_level = get_level_index(old_score, evolution_level, rebirth_count, ultra_rebirth, evo_mult, rebirth_mult)
    new_level = get_level_index(new_score, evolution_level, rebirth_count, ultra_rebirth, evo_mult, rebirth_mult)
    if new_level <= old_level:
        return
    emoji, name, show_level = get_level_visual(new_level)
    lvl_part = f" ({new_level} лвл)" if show_level else ""
    name_part = f" {esc(name)}" if name else ""
    await message.reply(TEXTS["maybe_announce_levelup_1"].format(v0=esc(username), v1=emoji, v2=name_part, v3=lvl_part))

@dp.message(F.text.lower() == "смс выкл")
async def notify_off(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    await ensure_user(user_id, username)
    await db_exec("UPDATE users SET levelup_notify = 0 WHERE user_id = ?", (user_id,))
    await message.reply(TEXTS["notify_off_1"])

@dp.message(F.text.lower() == "смс вкл")
async def notify_on(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    await ensure_user(user_id, username)
    await db_exec("UPDATE users SET levelup_notify = 1 WHERE user_id = ?", (user_id,))
    await message.reply(TEXTS["notify_on_1"])

@dp.message(F.text.lower() == "кратко выкл")
async def compact_mode_off(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    await ensure_user(user_id, username)
    await db_exec("UPDATE users SET compact_mode = 0 WHERE user_id = ?", (user_id,))
    await message.reply(TEXTS["compact_off_1"])

@dp.message(F.text.lower() == "кратко вкл")
async def compact_mode_on(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    await ensure_user(user_id, username)
    await db_exec("UPDATE users SET compact_mode = 1 WHERE user_id = ?", (user_id,))
    await message.reply(TEXTS["compact_on_1"])

@dp.message(F.text.regexp(r"(?i)^\+ник\s+.+$"))
async def set_nickname(message: Message):
    match = NICK_SET_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["nick_set_empty"])
        return

    nickname = match.group(1).strip().strip('"').strip("'").strip()
    if not nickname:
        await message.reply(TEXTS["nick_set_empty"])
        return
    if len(nickname) > 50:
        await message.reply(TEXTS["nick_set_too_long"].format(v0=len(nickname)))
        return

    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    await ensure_user(user_id, username)

    taken = await db_query_one(
        "SELECT user_id FROM users WHERE lower(nickname) = lower(?) AND user_id != ?",
        (nickname, user_id),
    )
    if taken:
        await message.reply(TEXTS["nick_set_taken"])
        return

    await db_exec("UPDATE users SET nickname = ? WHERE user_id = ?", (nickname, user_id))
    await safe_reply(message, TEXTS["nick_set_ok"].format(v0=esc(nickname)))

@dp.message(F.text.lower() == "-ник")
async def clear_nickname(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    await ensure_user(user_id, username)
    await db_exec("UPDATE users SET nickname = NULL WHERE user_id = ?", (user_id,))
    await message.reply(TEXTS["nick_clear_ok"])

def buy_vip_keyboard(user_id: int) -> InlineKeyboardMarkup:
    contact_text = quote("Привет! Хочу оформить VIP-статус")
    contact_url = f"https://t.me/{ADMIN_USERNAME}?text={contact_text}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ Написать админу", url=contact_url)],
    ])

@dp.message(F.text.lower() == "вип")
async def vip_info_command(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    row = await ensure_user(user_id, username)
    vip_until = row[12]

    if is_vip_active(vip_until):
        await message.reply(TEXTS["vip_info_command_1"])
        return

    await message.reply(
        TEXTS["vip_info_command_2"].format(v0=round(VIP_BOOST * 100), v1=VIP_STARS_PRICE),
        reply_markup=buy_vip_keyboard(user_id),
    )

@dp.message(F.text.lower().in_({"авто эво вкл", "авто эволюция вкл"}))
async def auto_evolve_on(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    row = await ensure_user(user_id, username)
    vip_until = row[12]

    if not is_vip_active(vip_until):
        await message.reply(TEXTS["auto_evolve_not_vip_1"])
        return

    await db_exec("UPDATE users SET auto_evolve = 1 WHERE user_id = ?", (user_id,))
    await message.reply(TEXTS["auto_evolve_on_1"])

@dp.message(F.text.lower().in_({"авто эво выкл", "авто эволюция выкл"}))
async def auto_evolve_off(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    await ensure_user(user_id, username)

    await db_exec("UPDATE users SET auto_evolve = 0 WHERE user_id = ?", (user_id,))
    await message.reply(TEXTS["auto_evolve_off_1"])

@dp.message(F.text.lower().in_({"авто перерождение вкл", "авто рб вкл", "авто ребёрт вкл", "авто реберт вкл"}))
async def auto_rebirth_on(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    row = await ensure_user(user_id, username)
    vip_until = row[12]

    if not is_vip_active(vip_until):
        await message.reply(TEXTS["auto_rebirth_not_vip_1"])
        return

    await db_exec("UPDATE users SET auto_rebirth = 1 WHERE user_id = ?", (user_id,))
    await message.reply(TEXTS["auto_rebirth_on_1"].format(v0=REBIRTH_MIN_EVO))

@dp.message(F.text.lower().in_({"авто перерождение выкл", "авто рб выкл", "авто ребёрт выкл", "авто реберт выкл"}))
async def auto_rebirth_off(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    await ensure_user(user_id, username)

    await db_exec("UPDATE users SET auto_rebirth = 0 WHERE user_id = ?", (user_id,))
    await message.reply(TEXTS["auto_rebirth_off_1"])

@dp.message(F.text.lower() == "пинг")
async def vip_ping(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    row = await ensure_user(user_id, username)
    vip_until = row[12]

    if not is_vip_active(vip_until):
        await message.reply(TEXTS["ping_not_vip_1"])
        return

    start = time.monotonic()
    sent = await message.reply("🏓 Понг...")
    delay_ms = round((time.monotonic() - start) * 1000)
    await sent.edit_text(f"🏓 Понг! Задержка: {delay_ms} мс")

@dp.message(F.text.lower() == "авто продажа вкл")
async def auto_sell_on(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    await ensure_user(user_id, username)

    await db_exec("UPDATE users SET auto_sell = 1 WHERE user_id = ?", (user_id,))
    await message.reply(TEXTS["auto_sell_on_1"])

@dp.message(F.text.lower() == "авто продажа выкл")
async def auto_sell_off(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    await ensure_user(user_id, username)

    await db_exec("UPDATE users SET auto_sell = 0 WHERE user_id = ?", (user_id,))
    await message.reply(TEXTS["auto_sell_off_1"])

@dp.message(F.text.lower().in_({"авто продажа настройка", "авто продажа конфиг", "авто продажа настройки"}))
async def auto_sell_config(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    row = await ensure_user(user_id, username)
    auto_sell_enabled = bool(row[30])
    auto_sell_items = parse_auto_sell_items(row[31])
    await message.reply(
        format_autosell_text(auto_sell_enabled, auto_sell_items),
        reply_markup=autosell_keyboard(auto_sell_enabled, auto_sell_items, user_id),
    )

@dp.callback_query(F.data.startswith("autosell_toggle:"))
async def autosell_toggle(callback: CallbackQuery):
    parts = callback.data.split(":")
    owner_id = int(parts[1])
    item_key = parts[2]
    page = int(parts[3]) if len(parts) > 3 else 0
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["inventory_open_category_1"], show_alert=True)
        return
    if item_key not in CASE_SELLABLE_ITEMS:
        await callback.answer()
        return
    await callback.answer()

    row = await get_user(owner_id)
    auto_sell_enabled = bool(row[30])
    auto_sell_items = parse_auto_sell_items(row[31])

    if item_key in auto_sell_items:
        auto_sell_items.discard(item_key)
    else:
        auto_sell_items.add(item_key)

    await db_exec("UPDATE users SET auto_sell_items = ? WHERE user_id = ?", (format_auto_sell_items(auto_sell_items), owner_id))
    await safe_edit_text(callback, 
        format_autosell_text(auto_sell_enabled, auto_sell_items, page),
        reply_markup=autosell_keyboard(auto_sell_enabled, auto_sell_items, owner_id, page),
    )

@dp.callback_query(F.data.startswith("autosell_switch:"))
async def autosell_switch(callback: CallbackQuery):
    parts = callback.data.split(":")
    owner_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["inventory_open_category_1"], show_alert=True)
        return

    row = await get_user(owner_id)
    auto_sell_enabled = not bool(row[30])
    auto_sell_items = parse_auto_sell_items(row[31])
    await callback.answer(TEXTS["auto_sell_on_1"] if auto_sell_enabled else TEXTS["auto_sell_off_1"])

    await db_exec("UPDATE users SET auto_sell = ? WHERE user_id = ?", (1 if auto_sell_enabled else 0, owner_id))
    await safe_edit_text(callback, 
        format_autosell_text(auto_sell_enabled, auto_sell_items, page),
        reply_markup=autosell_keyboard(auto_sell_enabled, auto_sell_items, owner_id, page),
    )

@dp.callback_query(F.data.startswith("autosell_page:"))
async def autosell_page_nav(callback: CallbackQuery):
    _, owner_str, page_str = callback.data.split(":")
    owner_id = int(owner_str)
    page = int(page_str)
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["inventory_open_category_1"], show_alert=True)
        return
    await callback.answer()

    row = await get_user(owner_id)
    auto_sell_enabled = bool(row[30])
    auto_sell_items = parse_auto_sell_items(row[31])
    await safe_edit_text(callback, 
        format_autosell_text(auto_sell_enabled, auto_sell_items, page),
        reply_markup=autosell_keyboard(auto_sell_enabled, auto_sell_items, owner_id, page),
    )

VIP_CASE_OPEN_RE = re.compile(r"^вип открыть кейс\s+(\d+)\s+(\d+)$", re.IGNORECASE)
VIP_CASE_OPEN_LIMIT = 20

@dp.message(F.text.regexp(r"(?i)^вип открыть кейс\s+"))
async def vip_open_case_bulk(message: Message):
    """VIP-версия owner-команды '!дать кейс' — открывает несколько кейсов разом,
    но платно (списывает монеты за каждый кейс) и только себе, лимит 20 за раз."""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"

    match = VIP_CASE_OPEN_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["vip_case_open_1"])
        return

    row = await ensure_user(user_id, username)
    vip_until = row[12]
    if not is_vip_active(vip_until):
        await message.reply(TEXTS["vip_case_open_2"])
        return

    case_num = int(match.group(1))
    count = int(match.group(2))
    case = CASES.get(case_num)
    if not case:
        await message.reply(TEXTS["vip_case_open_3"])
        return
    if count < 1 or count > VIP_CASE_OPEN_LIMIT:
        await message.reply(TEXTS["vip_case_open_4"])
        return

    coins = row[5]
    upgrades = parse_upgrades(row[16])
    auto_sell_enabled = bool(row[30])
    auto_sell_items = parse_auto_sell_items(row[31])
    unit_price = case_price_with_discount(case["price"], upgrades)
    total_price = unit_price * count

    if coins < total_price:
        await message.reply(TEXTS["vip_case_open_5"].format(v0=total_price, v1=coins))
        return

    won = {}
    sold = {}
    sold_coins_total = 0
    collector_chance = case_collector_chance(upgrades)
    collector_bonus_count = 0
    for _ in range(count):
        item_key = roll_case_item(case_num)
        if auto_sell_enabled and item_key in auto_sell_items and item_key not in NON_TRADABLE_ITEMS:
            price = SELL_PRICE.get(item_key, 1) + sell_bonus_coins(upgrades)
            sold[item_key] = sold.get(item_key, 0) + 1
            sold_coins_total += price
        else:
            won[item_key] = won.get(item_key, 0) + 1

        # Коллекционер кейсов (ветка 'case_collector', категория 5) — шанс доп. предмета
        # за каждый открытый кейс в партии, без доп. затраты монет.
        if collector_chance and random.random() < collector_chance:
            collector_bonus_count += 1
            bonus_item_key = roll_case_item(case_num)
            if auto_sell_enabled and bonus_item_key in auto_sell_items and bonus_item_key not in NON_TRADABLE_ITEMS:
                price = SELL_PRICE.get(bonus_item_key, 1) + sell_bonus_coins(upgrades)
                sold[bonus_item_key] = sold.get(bonus_item_key, 0) + 1
                sold_coins_total += price
            else:
                won[bonus_item_key] = won.get(bonus_item_key, 0) + 1

    # Вместо до 20 отдельных запросов в БД (один на предмет, как раньше через
    # apply_case_reward в цикле) — считаем всё в Python и пишем максимум 2
    # запроса: один executemany для инвентаря (все выигранные предметы разом,
    # ON CONFLICT суммирует qty построчно) и один UPDATE для монет/счётчиков
    # (списание цены + доход от авто-продажи + cases_opened — одной строкой).
    # Это и быстрее, и не держит DB-воркер занятым на 20+ round-trip'ов подряд,
    # блокируя остальных игроков, которые шардируются на тот же воркер.
    if won:
        await db_exec_many(
            "INSERT INTO inventory (user_id, item_key, qty) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, item_key) DO UPDATE SET qty = qty + excluded.qty",
            [(user_id, item_key, qty) for item_key, qty in won.items()],
            shard_key=user_id,
        )

    new_coins = coins - total_price + sold_coins_total
    await db_exec(
        "UPDATE users SET coins = coins - ? + ?, cases_opened = cases_opened + ? WHERE user_id = ?",
        (total_price, sold_coins_total, count, user_id),
    )

    loot_lines = "\n".join(f"● {ITEMS[k][0]} {esc(ITEMS[k][1])} × {qty}" for k, qty in won.items())
    if sold:
        sold_lines = ", ".join(f"{ITEMS[k][0]} {esc(ITEMS[k][1])} × {qty}" for k, qty in sold.items())
        loot_lines += f"\n💰 Авто-продано: {sold_lines} (+{sold_coins_total} 🪙)"
    if collector_bonus_count:
        loot_lines += f"\n✨ Коллекционер кейсов: +{collector_bonus_count} доп. предмет(ов) без затраты кейса!"
    await safe_reply(
        message,
        TEXTS["vip_case_open_6"].format(v0=count, v1=esc(case["name"]), v2=total_price, v3=new_coins, v4=loot_lines),
    )

@dp.callback_query(F.data.startswith("buy_vip:"))
async def buy_vip_invoice(callback: CallbackQuery):
    owner_id = int(callback.data.split(":")[1])
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["buy_vip_invoice_1"], show_alert=True)
        return

    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title="VIP статус навсегда",
        description=f"Постоянный буст +{round(VIP_BOOST * 100)}% к добыче ноги.",
        payload=f"vip:{owner_id}",
        currency="XTR",
        prices=[LabeledPrice(label="VIP навсегда", amount=VIP_STARS_PRICE)],
        provider_token="",
    )
    await callback.answer()

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    payload = pre_checkout_query.invoice_payload or ""
    if payload.startswith("vip:"):
        await pre_checkout_query.answer(ok=True)
    else:
        await pre_checkout_query.answer(ok=False, error_message="Неизвестный товар.")

@dp.message(F.successful_payment)
async def process_successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload or ""
    if not payload.startswith("vip:"):
        return
    target_id = int(payload.split(":")[1])
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    row = await ensure_user(target_id, username)

    was_vip_before = is_vip_active(row[12])
    new_vip_until = int(time.time()) + VIP_FOREVER_SECONDS
    await db_exec("UPDATE users SET vip_until = ? WHERE user_id = ?", (new_vip_until, target_id))
    if not was_vip_before:
        await add_item(target_id, "vip_charm")

    await message.reply(TEXTS["process_successful_payment_1"])

@dp.message(F.text.lower() == "бейджи")
async def badges_menu(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    row = await ensure_user(user_id, username)
    evolution_level, cases_opened, total_farmed, vip_until = row[3], row[7], row[8], row[12]
    coins = row[5]
    shown = parse_shown(row[39] if len(row) > 39 else "")
    promo_badges = parse_promo_badges(row[33] if len(row) > 33 else "")
    rebirth_points = row[14] if len(row) > 14 else 0
    ultra_rebirth = bool(row[21]) if len(row) > 21 else False
    bonus_streak = row[10] if len(row) > 10 else 0
    prestige_points = row[27] if len(row) > 27 else 0
    crafts_done = row[36] if len(row) > 36 else 0
    vip_active = is_vip_active(vip_until)

    earned = badge_list(username, evolution_level, cases_opened, total_farmed, vip_active, promo_badges,
                         coins, rebirth_points, ultra_rebirth, bonus_streak, crafts_done, prestige_points)
    if not earned:
        await message.reply(TEXTS["badges_menu_1"])
        return

    kb = badges_keyboard(earned, shown, user_id, page=0)
    await message.reply(TEXTS["badges_menu_2"], reply_markup=kb)

@dp.callback_query(F.data == "badge_noop")
async def badge_noop(callback: CallbackQuery):
    await callback.answer()

@dp.callback_query(F.data.startswith("badge_page:"))
async def badge_change_page(callback: CallbackQuery):
    _, owner_str, page_str = callback.data.split(":")
    owner_id = int(owner_str)
    page = int(page_str)
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["toggle_badge_1"], show_alert=True)
        return
    await callback.answer()

    row = await get_user(owner_id)
    username, evolution_level, cases_opened, total_farmed, vip_until = row[1], row[3], row[7], row[8], row[12]
    coins = row[5]
    shown = parse_shown(row[39] if len(row) > 39 else "")
    promo_badges = parse_promo_badges(row[33] if len(row) > 33 else "")
    rebirth_points = row[14] if len(row) > 14 else 0
    ultra_rebirth = bool(row[21]) if len(row) > 21 else False
    bonus_streak = row[10] if len(row) > 10 else 0
    prestige_points = row[27] if len(row) > 27 else 0
    crafts_done = row[36] if len(row) > 36 else 0
    vip_active = is_vip_active(vip_until)

    earned = badge_list(username, evolution_level, cases_opened, total_farmed, vip_active, promo_badges,
                         coins, rebirth_points, ultra_rebirth, bonus_streak, crafts_done, prestige_points)
    kb = badges_keyboard(earned, shown, owner_id, page=page)
    await safe_edit_text(callback, TEXTS["badges_menu_2"], reply_markup=kb)

@dp.callback_query(F.data.startswith("badge:"))
async def toggle_badge(callback: CallbackQuery):
    _, owner_str, page_str, key = callback.data.split(":")
    owner_id = int(owner_str)
    page = int(page_str)
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["toggle_badge_1"], show_alert=True)
        return

    row = await get_user(owner_id)
    username, evolution_level, cases_opened, total_farmed, vip_until = row[1], row[3], row[7], row[8], row[12]
    coins = row[5]
    shown = parse_shown(row[39] if len(row) > 39 else "")
    promo_badges = parse_promo_badges(row[33] if len(row) > 33 else "")
    rebirth_points = row[14] if len(row) > 14 else 0
    ultra_rebirth = bool(row[21]) if len(row) > 21 else False
    bonus_streak = row[10] if len(row) > 10 else 0
    prestige_points = row[27] if len(row) > 27 else 0
    crafts_done = row[36] if len(row) > 36 else 0

    if key in shown:
        shown.discard(key)
        await callback.answer(TEXTS["toggle_badge_2"])
    elif len(shown) >= BADGES_DISPLAY_LIMIT:
        await callback.answer(TEXTS["toggle_badge_3"], show_alert=True)
        return
    else:
        shown.add(key)
        await callback.answer(TEXTS["toggle_badge_2"])

    new_shown_str = ",".join(sorted(shown))
    await db_exec("UPDATE users SET shown_badges = ? WHERE user_id = ?", (new_shown_str, owner_id))

    vip_active = is_vip_active(vip_until)
    earned = badge_list(username, evolution_level, cases_opened, total_farmed, vip_active, promo_badges,
                         coins, rebirth_points, ultra_rebirth, bonus_streak, crafts_done, prestige_points)
    kb = badges_keyboard(earned, shown, owner_id, page=page)
    await safe_edit_text(callback, TEXTS["badges_menu_2"], reply_markup=kb)

@dp.message(F.text.regexp(r"[🦵🦿]"))
async def count_legs(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    text = message.text

    if user_id != ADMIN_USER_ID:
        now_mono = time.monotonic()
        last = _leg_farm_last.get(user_id, 0)
        if now_mono - last < LEG_FARM_COOLDOWN:
            return
        _leg_farm_last[user_id] = now_mono

    row = await ensure_user(user_id, username)
    score, evolution_level, active_item = row[2], row[3], row[6]
    levelup_notify, vip_until = row[11], row[12]
    rebirth_points, rebirth_count = row[14], row[15]
    upgrades = parse_upgrades(row[16])
    active_items = parse_equipped(row[18])
    ultra_rebirth = bool(row[21])
    auto_evolve_enabled = bool(row[22])
    auto_rebirth_enabled = bool(row[29])
    prestige_points = row[27]
    vip_active = is_vip_active(vip_until)
    inv_early = await get_inventory(user_id)
    inventory_map_early = {k: q for k, q in inv_early}
    potions = active_potions_now(row[23], active_items=active_items, inventory_map=inventory_map_early)
    prestige_upgrades = parse_prestige_upgrades(row[28])
    chronos_boost_pct = row[34] if len(row) > 34 else 100
    compact_mode = bool(row[35]) if len(row) > 35 else False
    vilon_streak = row[37] if len(row) > 37 else 0
    vilon_boost_until = row[38] if len(row) > 38 else 0
    kotyara_boost_until = row[40] if len(row) > 40 else 0
    flat_bonus = total_flat_bonus(active_items)
    limits = active_farm_limits(active_items, prestige_upgrades)

    legs = min(text.count("🦵"), limits["leg_limit"])
    gained = legs * LEG_POINT

    mek = 0
    if evolution_level >= 1:
        mek = min(text.count("🦿"), limits["mek_limit"])
        gained += mek * MEK_POINT

    evo_leg_counts = []
    for emoji, tier in EVO_LEG_TIERS.items():
        if evolution_level < tier["level"]:
            continue
        count = min(text.count(emoji), tier["limit"])
        if count:
            gained += count * round(MEK_POINT * (1 + tier["bonus_pct"] / 100))
            evo_leg_counts.append((emoji, count))

    paw = min(text.count("🐾"), limits["paw_limit"])
    gained += paw * MEK_POINT * PAW_POINT_MULTIPLIER

    galaxy = min(text.count("🌌"), limits["galaxy_limit"])
    star = min(text.count("⭐️"), limits["star_limit"])
    miku_note = 0
    if "miku_ring" in set(_normalize_active_items(active_items)):
        miku_note = min(text.count("🎶"), MIKU_RING_SYMBOL_LIMIT)
    kotyara_cat_note = 0
    if "kotyara_amulet" in set(_normalize_active_items(active_items)):
        kotyara_cat_note = min(text.count("😺"), KOTYARA_CAT_SYMBOL_LIMIT)

    if gained == 0:
        return

    gained += flat_bonus
    gained = round(gained * farm_yield_multiplier(upgrades))

    event_mult, personal_mult = await asyncio.gather(
        get_event_multiplier(), get_personal_multiplier(user_id)
    )
    inventory_map = inventory_map_early
    nano_it_count = inventory_map.get("nano_it", 0)
    mult = get_multiplier(evolution_level, active_items, vip_active, upgrades, ultra_rebirth, chronos_boost_pct, nano_it_count)
    p_yield_mult = 1 + 0.005 * prestige_bonus(prestige_upgrades, "p_farm_yield")
    total = round(gained * mult * event_mult * personal_mult * p_yield_mult)
    if galaxy:
        total = round(total * (1 + 0.20 * galaxy))
    if star:
        total = round(total * (2 ** star))
    if miku_note:
        total = round(total * MIKU_RING_FARM_MULT)
    kotyara_cat_coins = 0
    if kotyara_cat_note >= KOTYARA_CAT_SYMBOL_LIMIT:
        total = round(total * KOTYARA_CAT_FARM_MULT)
        if random.random() < KOTYARA_CAT_COIN_CHANCE:
            kotyara_cat_coins = random.randint(KOTYARA_CAT_COIN_MIN, KOTYARA_CAT_COIN_MAX)
            await db_exec("UPDATE users SET coins = coins + ? WHERE user_id = ?", (kotyara_cat_coins, user_id))
    if inventory_map.get("pocket_star", 0) > 0:
        total = round(total * POCKET_STAR_LEG_FARM_MULT)
    total = apply_vilon_amulet_boost(total, vilon_boost_until)
    total = apply_kotyara_amulet_boost(total, kotyara_boost_until)
    potion_text = ""
    if "potion_speed" in potions:
        base_speed_mult = DRAGON_CLAW_POTION_MULT if "dragon_claw" in set(_normalize_active_items(active_items)) else 2
        speed_mult = round(base_speed_mult * potion_boost_multiplier(upgrades), 2)
        total *= speed_mult
        potion_text += f"🧪⚡ x{speed_mult}"

    chronos_text, _chronos_reset_cd, chronos_farm_mult = await apply_chronos_orb_procs(user_id, active_items)
    if chronos_farm_mult != 1.0:
        total = round(total * chronos_farm_mult)

    echo_text = ""
    echo_chance = echo_farm_chance(upgrades)
    if echo_chance and random.random() < echo_chance:
        total *= 2
        echo_text = "✨ Эхо фарма: x2!"

    content_boost_until = row[50] if len(row) > 50 else 0
    content_boost_text = ""
    if content_boost_until and content_boost_until > int(time.time()):
        total = round(total * CONTENT_BOOST_MULT)
        content_boost_text = f"⚡ Буст x{CONTENT_BOOST_MULT:g}!"

    new_score = score + total

    await db_exec(
        "UPDATE users SET score = ?, total_farmed = total_farmed + ? WHERE user_id = ?",
        (new_score, total, user_id),
    )

    await maybe_announce_levelup(message, username, score, new_score, evolution_level, bool(levelup_notify), rebirth_count, ultra_rebirth, **hardness_kwargs(row))

    auto_evo_text = ""
    if vip_active and auto_evolve_enabled:
        evolution_level, new_score, auto_evo_text = await try_auto_evolve(user_id, new_score, evolution_level, rebirth_count, active_items, **hardness_kwargs(row))

    auto_rebirth_text = ""
    if vip_active and auto_rebirth_enabled:
        new_score, evolution_level, rebirth_count, rebirth_points, prestige_points, auto_rebirth_text = await try_auto_rebirth(
            user_id, new_score, evolution_level, rebirth_count, rebirth_points, prestige_points, prestige_upgrades, active_items
        )

    inventory_map = inventory_map_early
    luck_mult = (2.0 * potion_boost_multiplier(upgrades)) if "luck_x2" in potions else 1.0
    guaranteed_rebirth = has_potion_effect(potions, "rebirth_on_farm")
    vase_text = await apply_vase_proc(user_id, inventory_map, luck_mult)
    bonus = await apply_farm_bonuses(user_id, active_items, inventory_map, luck_mult, guaranteed_rebirth, coin_magnet_bonus(upgrades))
    chaos_text = await apply_chaos_orb_proc(user_id, inventory_map)
    necklace_text = (
        await apply_blazing_necklace_proc(user_id, active_items)
        + await apply_star_necklace_proc(user_id, active_items)
    )
    craft_charm_text = (
        await apply_elemental_charm_proc(user_id, active_items)
        + await apply_twilight_amulet_proc(user_id, active_items)
        + await apply_chaos_fang_proc(user_id, active_items)
    )
    mastery_text, mastery_bitcoin_bonus = await apply_mastery_lover_proc(user_id, active_items)
    rebirth_coin_text = await apply_rebirth_coin_proc(user_id, inventory_map)
    coin_tree_text = (
        await apply_godly_nogost_coin_case_proc(user_id, inventory_map)
        + await apply_bitcoin_proc(user_id, inventory_map, mastery_bitcoin_bonus)
        + await apply_craft_coin_proc(user_id, inventory_map)
    )
    steal_text = await apply_leg_farm_steal(user_id, message.chat.id, active_items)
    vilon_text = await apply_vilon_amulet_trigger(user_id, active_items, vilon_streak)
    kotyara_text = await apply_kotyara_amulet_trigger(user_id, active_items)

    now = time.monotonic()
    chat_id = message.chat.id
    if now - _last_leg_reply.get(chat_id, 0) < LEG_REPLY_COOLDOWN:
        return
    _last_leg_reply[chat_id] = now

    equipped_set = set(_normalize_active_items(active_items))

    tide_text = ""
    if "tide_wave" in equipped_set and random.random() < TIDE_WAVE_PROC_CHANCE:
        tide_item = roll_case_item(random.choice([1, 2]))
        await add_item(user_id, tide_item)
        tide_emoji, tide_name, _, _ = ITEMS[tide_item]
        tide_text = f"\n🌊 Прилив принёс: {tide_emoji} {esc(tide_name)}!"

    skull_prefix = "💀 Смерть близко.\n" if "warrior_skull" in equipped_set else ""

    parts = f"+{legs}🦵"
    if mek:
        parts += f" +{mek}🦿"
    for emoji, count in evo_leg_counts:
        parts += f" +{count}{emoji}"
    if paw:
        parts += f" +{paw}🐾"
    if galaxy:
        parts += f" +{galaxy}🌌"
    if star:
        parts += f" +{star}⭐️"

    miku_text = f"{ITEMS['miku_ring'][0]} Кольцо Мику: x{MIKU_RING_FARM_MULT}" if miku_note else ""
    kotyara_cat_text = ""
    if kotyara_cat_note >= KOTYARA_CAT_SYMBOL_LIMIT:
        kotyara_cat_text = f"{ITEMS['kotyara_amulet'][0]} Амулет Котяры: 😺 x{KOTYARA_CAT_FARM_MULT}"
        if kotyara_cat_coins:
            kotyara_cat_text += f" +{kotyara_cat_coins}🪙"

    coin_text = f" +{bonus['coins']}🪙" if bonus["coins"] else ""
    rebirth_farm_text = f"🧪🉑 +{bonus['rebirth']}🉑" if (bonus["rebirth"] and not bonus["is_god"]) else ""
    combo_bits = [b for b in (vase_text, potion_text, rebirth_coin_text, rebirth_farm_text, echo_text, content_boost_text) if b]
    combo_text = ("\n" + " · ".join(combo_bits)) if combo_bits else ""
    kotyara_bits = [b for b in (kotyara_text, kotyara_cat_text) if b]
    kotyara_combo_text = ("\n" + " · ".join(kotyara_bits)) if kotyara_bits else ""
    miku_combo_text = f"\n{miku_text}" if miku_text else ""
    bonus_text = "" if compact_mode else (combo_text + tide_text + chaos_text + chronos_text + coin_tree_text + necklace_text + craft_charm_text + mastery_text)
    extra_text = bonus_text + auto_evo_text + auto_rebirth_text + steal_text + vilon_text + ("" if compact_mode else kotyara_combo_text + miku_combo_text)
    chronos_equipped = "chronos_orb" in set(_normalize_active_items(active_items))

    content_phrase = content_bonus_text_override(active_items)
    if content_phrase:
        extra_text += f"\n{content_phrase}"

    if bonus["is_god"]:
        flavor = CHRONOS_ORB_FLAVOR if chronos_equipped else (KOSHKO_AMULET_FLAVOR if bonus.get("tier") == "koshko_amulet" else GOD_ESSENCE_FLAVOR)
        god_extra = f" +{bonus['rebirth']}🉑" if bonus["rebirth"] else ""
        await safe_reply(
            message,
            skull_prefix + TEXTS["count_legs_1"].format(v0=flavor, v1=parts, v2=total, v3=coin_text, v4=god_extra, v5=new_score, v6=extra_text)
        )
        return

    if chronos_equipped:
        await safe_reply(
            message,
            skull_prefix + TEXTS["count_legs_1"].format(v0=CHRONOS_ORB_FLAVOR, v1=parts, v2=total, v3=coin_text, v4="", v5=new_score, v6=extra_text)
        )
        return

    await message.reply(
        skull_prefix + TEXTS["count_legs_2"].format(v0=parts, v1=total, v2=coin_text, v3=new_score, v4=extra_text)
    )

@dp.message(F.text.lower() == "моя нога")
async def my_profile(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"

    row = await ensure_user(user_id, username)
    score, evolution_level, coins, active_item = row[2], row[3], row[5], row[6]
    cases_opened = row[7]
    last_bonus = row[9]
    vip_until = row[12]
    rebirth_points, rebirth_count = row[14], row[15]
    upgrades = parse_upgrades(row[16])
    active_items = parse_equipped(row[18])
    nickname = row[19] if len(row) > 19 else None
    ultra_rebirth = bool(row[21])
    craft_points = row[32] if len(row) > 32 else 0
    crafts_done = row[36] if len(row) > 36 else 0
    first_seen = row[46] if len(row) > 46 else None
    vip_active = is_vip_active(vip_until)
    shown_name = display_name(username, nickname)
    gc_row = await db_query_one("SELECT gold_coin, diamond_coin FROM users WHERE user_id = ?", (user_id,))
    gold_coin, diamond_coin = gc_row if gc_row else (0, 0)

    level = get_level_index(score, evolution_level, rebirth_count, ultra_rebirth, **hardness_kwargs(row))
    emoji, name, show_level = get_level_visual(level)
    display_level = level
    nxt = next_level_text(score, evolution_level, rebirth_count, ultra_rebirth, **hardness_kwargs(row))
    chronos_boost_pct = row[34] if len(row) > 34 else 100
    inv_rows_profile = await get_inventory(user_id)
    nano_it_count = {k: q for k, q in inv_rows_profile}.get("nano_it", 0)
    mult = get_multiplier(evolution_level, active_items, vip_active, upgrades, ultra_rebirth, chronos_boost_pct, nano_it_count)
    flat_bonus = total_flat_bonus(active_items)

    now = int(time.time())
    titles = get_active_titles(row)
    if is_developer_id(user_id):
        titles.add("developer")
    display_title = get_display_title(titles)
    title_line = f"● Титул: {title_emoji_badge(display_title)}\n"

    ultra_line, vip_line = status_lines(vip_active, vip_until, ultra_rebirth, now)

    lvl_line = f"● Уровень ноги: {display_level} лвл\n" if (show_level or ultra_rebirth) else ""
    name_part = f" {esc(name)}" if name else ""
    guarant_line = f"● Гарант-буст с предмета: +{flat_bonus} к итогу\n" if flat_bonus else ""
    rebirth_line = f"● Перерождений: {rebirth_count} (🉑 {rebirth_points}) (💠 {craft_points})\n" if rebirth_count else ""
    premium_coins_line = (
        f"● Голд коин: <code>{gold_coin}</code> 🌕 · Алмаз коин: <code>{diamond_coin}</code> 💎\n"
        if (gold_coin or diamond_coin) else ""
    )

    # Время в боте — на основе first_seen (NULL для игроков, мигрировавших до этого патча).
    if first_seen:
        elapsed = max(0, now - first_seen)
        days, rem_seconds = divmod(elapsed, 86400)
        hours = rem_seconds // 3600
        time_in_bot_line = f"● Время в боте: {days}д {hours}ч\n"
    else:
        time_in_bot_line = ""

    # Усложнение игры — итоговый множитель порога уровня от эво+перерождений (см. level_threshold),
    # показывается как проценты сверх базовой сложности (100% = без усложнения = +0%).
    hardness_pct = hardness_percent(evolution_level, rebirth_count, active_items, **hardness_kwargs(row))
    hardness_line = f"● Усложнение игры: +{hardness_pct}%\n" if hardness_pct else ""

    # До следующего бонуса — на основе last_bonus/DAILY_MIN_GAP (тот же интервал, что и в
    # команде "бонус").
    bonus_wait = DAILY_MIN_GAP - (now - last_bonus)
    if bonus_wait > 0:
        bh, bonus_rem = divmod(bonus_wait, 3600)
        bm = bonus_rem // 60
        next_bonus_line = f"● До следующего бонуса осталось {bh} часов {bm} минут\n"
    else:
        next_bonus_line = "● Бонус уже доступен — напиши «бонус»!\n"

    text = (
        f"👣 <b>ТВОЯ ЛЮТАЯ НОГОСТЬ, {esc(shown_name)}:</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{title_line}"
        f"{ultra_line}"
        f"● Очки: <code>{score}</code>\n"
        f"● Монеты: <code>{coins}</code> 🪙\n"
        f"{premium_coins_line}"
        f"● Вид ног: {emoji}{name_part}\n"
        f"{lvl_line}"
        f"● Уровень эволюции: {evolution_level}\n"
        f"{rebirth_line}"
        f"● Процентовый буст: +{round((mult - 1) * 100)}%\n"
        f"{guarant_line}"
        f"{vip_line}"
        f"{time_in_bot_line}"
        f"● Кейсов открыто: {cases_opened}\n"
        f"{hardness_line}"
        f"● Предметов скрафчено: {crafts_done}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"● {nxt}\n"
        f"{next_bonus_line}"
    )
    await message.reply(text)

@dp.message(F.text.regexp(r"(?i)^инфо\s+@?\w+$"))
async def info_player(message: Message):
    match = INFO_RE.match(message.text.strip())
    if not match:
        return
    target_username = match.group(1)

    row = await get_user_by_username(target_username)
    if not row:
        await message.reply(TEXTS["info_player_1"])
        return

    username = row[1]
    score, evolution_level, coins, active_item = row[2], row[3], row[5], row[6]
    cases_opened, total_farmed = row[7], row[8]
    vip_until = row[12]
    rebirth_count = row[15] if len(row) > 15 else 0
    rebirth_points = row[14] if len(row) > 14 else 0
    shown = parse_shown(row[39] if len(row) > 39 else "")
    promo_badges = parse_promo_badges(row[33] if len(row) > 33 else "")
    nickname = row[19] if len(row) > 19 else None
    ultra_rebirth = bool(row[21]) if len(row) > 21 else False
    bonus_streak = row[10] if len(row) > 10 else 0
    prestige_points = row[27] if len(row) > 27 else 0
    craft_points = row[32] if len(row) > 32 else 0
    crafts_done = row[36] if len(row) > 36 else 0
    active_items = parse_equipped(row[18]) if len(row) > 18 else []
    first_seen = row[46] if len(row) > 46 else None
    shown_name = display_name(username, nickname)
    vip_active = is_vip_active(vip_until)
    level = get_level_index(score, evolution_level, rebirth_count, ultra_rebirth, **hardness_kwargs(row))
    emoji, name, show_level = get_level_visual(level)
    lvl_part = f" ({level} лвл)" if show_level else ""
    name_part = f" {esc(name)}" if name else ""
    item_text = ITEMS[active_item][1] if active_item and active_item in ITEMS else "нет"
    badges = get_badges(username, evolution_level, cases_opened, total_farmed, vip_active, shown, promo_badges,
                         coins, rebirth_points, ultra_rebirth, bonus_streak, crafts_done, prestige_points)
    gc_row = await db_query_one("SELECT gold_coin, diamond_coin FROM users WHERE user_id = ?", (row[0],))
    gold_coin, diamond_coin = gc_row if gc_row else (0, 0)
    premium_coins_line = (
        f"● Голд коин: <code>{gold_coin}</code> 🌕 · Алмаз коин: <code>{diamond_coin}</code> 💎\n"
        if (gold_coin or diamond_coin) else ""
    )

    titles = get_active_titles(row)
    if is_developer_id(row[0]):
        titles.add("developer")
    display_title = get_display_title(titles)
    title_line = f"● Титул: {title_emoji_badge(display_title)}\n"

    rebirth_line = f"● Перерождений: {rebirth_count} (🉑 {rebirth_points}) (💠 {craft_points})\n" if rebirth_count else ""

    now = int(time.time())
    ultra_line, vip_line = status_lines(vip_active, vip_until, ultra_rebirth, now)
    if first_seen:
        elapsed = max(0, now - first_seen)
        days, rem_seconds = divmod(elapsed, 86400)
        hours = rem_seconds // 3600
        time_in_bot_line = f"● Время в боте: {days}д {hours}ч\n"
    else:
        time_in_bot_line = ""

    hardness_pct = hardness_percent(evolution_level, rebirth_count, active_items, **hardness_kwargs(row))
    hardness_line = f"● Усложнение игры: +{hardness_pct}%\n" if hardness_pct else ""

    text = (
        f"👣 <b>Инфо об игроке {esc(shown_name)}{badges}:</b>\n"
        f"{title_line}"
        f"{ultra_line}"
        f"● Нога: {emoji}{name_part}{lvl_part}\n"
        f"● Очки: <code>{score}</code>\n"
        f"● Монеты: <code>{coins}</code> 🪙\n"
        f"{premium_coins_line}"
        f"● Уровень эволюции: {evolution_level}\n"
        f"{rebirth_line}"
        f"{time_in_bot_line}"
        f"● Кейсов открыто: {cases_opened}\n"
        f"{hardness_line}"
        f"● Предметов скрафчено: {crafts_done}\n"
        f"{vip_line}"
    )
    await message.reply(text)

BAN_RE = re.compile(r"^!бан(?:\s+@?(\w+))?$", re.IGNORECASE)
UNBAN_RE = re.compile(r"^!разбан(?:\s+@?(\w+))?$", re.IGNORECASE)

async def _resolve_ban_target(message: Message, username_arg: str | None):
    """Цель бана/разбана: реплай ИЛИ !бан @username. Если юзера ещё нет в базе
    (никогда не писал боту, но упомянут по нику) — резолвим только по username
    из БД: угадать user_id по голому @username без Telegram-объекта нельзя,
    поэтому в этом случае просим ответить реплаем вместо @username."""
    if message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user
        return target.id, (target.username or target.first_name or str(target.id))
    if username_arg:
        row = await get_user_by_username(username_arg)
        if row:
            return row[0], row[1]
        return None, None
    return None, None

BAN_ROFL_VALUE = -9999999999
BAN_SNAPSHOT_COLUMNS = ("score", "coins", "evolution_level", "rebirth_points")

async def _wipe_stats_for_ban(target_id: int):
    """Рофл-часть бана: перед обнулением сохраняет текущие score/coins/evolution_level/
    rebirth_points в game_banned_snapshot (JSON), затем выставляет их всем в
    BAN_ROFL_VALUE — чтобы у забаненного в топах/инфо было эффектное дно. При разбане
    _restore_stats_after_unban читает этот снапшот и возвращает всё как было —
    поэтому обязательно снапшотим ДО перезаписи, а не полагаемся на _user_cache
    (он может быть протухшим/пустым)."""
    row = await db_query_one(
        "SELECT score, coins, evolution_level, rebirth_points FROM users WHERE user_id = ?",
        (target_id,),
    )
    snapshot = dict(zip(BAN_SNAPSHOT_COLUMNS, row)) if row else {c: 0 for c in BAN_SNAPSHOT_COLUMNS}
    await db_exec(
        "UPDATE users SET game_banned_snapshot = ?, score = ?, coins = ?, "
        "evolution_level = ?, rebirth_points = ? WHERE user_id = ?",
        (json.dumps(snapshot), BAN_ROFL_VALUE, BAN_ROFL_VALUE, BAN_ROFL_VALUE, BAN_ROFL_VALUE, target_id),
    )

async def _apply_game_ban(user_id: int, username: str | None = None):
    """Единая точка входа 'забанить игрока в игре' — переиспользуется !бан/swoon/
    snowgrave, !бан чат, SpamProtectionMiddleware и PluginSpamMiddleware, чтобы
    последовательность (ensure_user -> game_banned=1 -> снапшот+обнуление статов ->
    добавить в in-memory сет) не дублировалась и не расходилась между местами.
    username опционален: если юзера ещё нет в БД, а username неизвестен (например,
    он сам никогда не писал профиль), ensure_user всё равно создаст строку с
    user_id — просто без красивого имени."""
    await ensure_user(user_id, username or str(user_id))
    await db_exec("UPDATE users SET game_banned = 1 WHERE user_id = ?", (user_id,))
    await _wipe_stats_for_ban(user_id)
    _game_banned_ids.add(user_id)

async def _restore_stats_after_unban(target_id: int):
    """Возвращает score/coins/evolution_level/rebirth_points к значениям на момент
    бана. Если снапшота почему-то нет (например, game_banned=1 выставили руками
    в БД, минуя !бан) — ничего не трогаем, чтобы не обнулить игрока по ошибке."""
    row = await db_query_one("SELECT game_banned_snapshot FROM users WHERE user_id = ?", (target_id,))
    raw = row[0] if row else None
    if not raw:
        return
    try:
        snapshot = json.loads(raw)
    except Exception:
        snapshot = None
    if not snapshot:
        await db_exec("UPDATE users SET game_banned_snapshot = NULL WHERE user_id = ?", (target_id,))
        return
    await db_exec(
        "UPDATE users SET game_banned_snapshot = NULL, score = ?, coins = ?, "
        "evolution_level = ?, rebirth_points = ? WHERE user_id = ?",
        (
            snapshot.get("score", 0), snapshot.get("coins", 0),
            snapshot.get("evolution_level", 0), snapshot.get("rebirth_points", 0),
            target_id,
        ),
    )

@dp.message(F.text.regexp(r"(?i)^!бан(?:\s+@?\w+)?$"))
async def cmd_ban_player(message: Message):
    match = BAN_RE.match(message.text.strip())
    if not match:
        return
    chat = message.chat
    if chat.type not in ("group", "supergroup"):
        await message.reply(TEXTS["cmd_ban_player_1"])
        return
    if not await is_moderator_or_above(message):
        await message.reply(TEXTS["cmd_ban_player_2"])
        return

    target_id, target_username = await _resolve_ban_target(message, match.group(1))
    if target_id is None:
        await message.reply(TEXTS["cmd_ban_player_3"])
        return
    if target_id == message.from_user.id:
        await message.reply(TEXTS["cmd_ban_player_4"])
        return
    if target_id == ADMIN_USER_ID:
        await message.reply(TEXTS["cmd_ban_player_5"])
        return
    if target_id in _game_banned_ids:
        await message.reply(TEXTS["cmd_ban_player_7"].format(v0=esc(target_username)))
        return

    await _apply_game_ban(target_id, target_username)

    chat_ban_note = ""
    try:
        await bot.ban_chat_member(chat.id, target_id)
        chat_ban_note = " Также забанен в этом чате."
    except TelegramForbiddenError:
        chat_ban_note = " ⚠️ У бота нет прав банить в чате — забанен только в игре."
    except TelegramBadRequest:
        chat_ban_note = " ⚠️ Не удалось забанить в чате (возможно, уже вне чата) — забанен только в игре."
    except Exception:
        chat_ban_note = " ⚠️ Не удалось забанить в чате — забанен только в игре."

    await message.reply(TEXTS["cmd_ban_player_6"] + chat_ban_note)

@dp.message(F.text.regexp(r"(?i)^!разбан(?:\s+@?\w+)?$"))
async def cmd_unban_player(message: Message):
    match = UNBAN_RE.match(message.text.strip())
    if not match:
        return
    chat = message.chat
    if chat.type not in ("group", "supergroup"):
        await message.reply(TEXTS["cmd_ban_player_1"])
        return
    if not await is_moderator_or_above(message):
        await message.reply(TEXTS["cmd_ban_player_2"])
        return

    target_id, target_username = await _resolve_ban_target(message, match.group(1))
    if target_id is None:
        await message.reply(TEXTS["cmd_ban_player_3"])
        return
    if target_id not in _game_banned_ids:
        await message.reply(TEXTS["cmd_unban_player_2"].format(v0=esc(target_username)))
        return

    await db_exec("UPDATE users SET game_banned = 0 WHERE user_id = ?", (target_id,))
    await _restore_stats_after_unban(target_id)
    _game_banned_ids.discard(target_id)

    chat_unban_note = ""
    try:
        await bot.unban_chat_member(chat.id, target_id, only_if_banned=True)
        chat_unban_note = " Также разбанен в этом чате."
    except Exception:
        chat_unban_note = ""

    await message.reply(TEXTS["cmd_unban_player_1"].format(v0=esc(target_username)) + chat_unban_note)

async def send_legs_top(message: Message, chat_id, title: str):
    rows = await build_top(chat_id, "score")

    if not rows:
        await message.reply(TEXTS["send_legs_top_1"])
        return

    text = f"🏆 <b>{title}</b>\n\n"
    for i, (username, score, evolution_level, coins, cases_opened, total_farmed, vip_until, shown_badges, rebirth_points, rebirth_count, nickname, ultra_rebirth, promo_badges_raw, bonus_streak, prestige_points, crafts_done, evo_mult, rebirth_mult) in enumerate(rows, 1):
        level = get_level_index(score, evolution_level, rebirth_count, bool(ultra_rebirth), evo_mult or 1.0, rebirth_mult or 1.0)
        emoji, name, show_level = get_level_visual(level)
        badges = get_badges(username, evolution_level, cases_opened, total_farmed, is_vip_active(vip_until), parse_shown(shown_badges), parse_promo_badges(promo_badges_raw), coins, rebirth_points, bool(ultra_rebirth), bonus_streak, crafts_done, prestige_points)
        lvl_part = f" ({level} лвл)" if show_level else ""
        name_part = f" {esc(name)}" if name else ""
        text += f"{i}. {esc(display_name(username, nickname))}{badges} — <code>{score}</code>\n   └ {emoji}{name_part}{lvl_part} · эво {evolution_level}\n\n"

    await message.reply(text)

async def send_evo_top(message: Message, chat_id, title: str):
    rows = await build_top(chat_id, "evolution_level")

    if not rows:
        await message.reply(TEXTS["send_evo_top_1"])
        return

    text = f"🎆 <b>{title}</b>\n\n"
    for i, (username, score, evolution_level, coins, cases_opened, total_farmed, vip_until, shown_badges, rebirth_points, rebirth_count, nickname, ultra_rebirth, promo_badges_raw, bonus_streak, prestige_points, crafts_done, evo_mult, rebirth_mult) in enumerate(rows, 1):
        badges = get_badges(username, evolution_level, cases_opened, total_farmed, is_vip_active(vip_until), parse_shown(shown_badges), parse_promo_badges(promo_badges_raw), coins, rebirth_points, bool(ultra_rebirth), bonus_streak, crafts_done, prestige_points)
        text += f"{i}. {esc(display_name(username, nickname))}{badges} — эво {evolution_level} ({score} очков)\n"

    await message.reply(text)

async def send_coin_top(message: Message, chat_id, title: str):
    rows = await build_top(chat_id, "coins")

    if not rows:
        await message.reply(TEXTS["send_coin_top_1"])
        return

    text = f"🪙 <b>{title}</b>\n\n"
    for i, (username, score, evolution_level, coins, cases_opened, total_farmed, vip_until, shown_badges, rebirth_points, rebirth_count, nickname, ultra_rebirth, promo_badges_raw, bonus_streak, prestige_points, crafts_done, evo_mult, rebirth_mult) in enumerate(rows, 1):
        badges = get_badges(username, evolution_level, cases_opened, total_farmed, is_vip_active(vip_until), parse_shown(shown_badges), parse_promo_badges(promo_badges_raw), coins, rebirth_points, bool(ultra_rebirth), bonus_streak, crafts_done, prestige_points)
        text += f"{i}. {esc(display_name(username, nickname))}{badges} — {coins} 🪙\n"

    await message.reply(text)

async def send_rebirth_top(message: Message, chat_id, title: str):
    rows = await build_top(chat_id, "rebirth_points")

    if not rows:
        await message.reply(TEXTS["send_rebirth_top_1"])
        return

    text = f"🉑 <b>{title}</b>\n\n"
    for i, (username, score, evolution_level, coins, cases_opened, total_farmed, vip_until, shown_badges, rebirth_points, rebirth_count, nickname, ultra_rebirth, promo_badges_raw, bonus_streak, prestige_points, crafts_done, evo_mult, rebirth_mult) in enumerate(rows, 1):
        badges = get_badges(username, evolution_level, cases_opened, total_farmed, is_vip_active(vip_until), parse_shown(shown_badges), parse_promo_badges(promo_badges_raw), coins, rebirth_points, bool(ultra_rebirth), bonus_streak, crafts_done, prestige_points)
        text += f"{i}. {esc(display_name(username, nickname))}{badges} — {rebirth_points} 🉑 (перерождений: {rebirth_count})\n"

    await message.reply(text)

async def build_premium_coin_top(chat_id, column: str, limit: int = 10):
    """Топ по gold_coin/diamond_coin — эти поля вне USER_COLUMNS (см. комментарий у
    ALTER TABLE), поэтому не переиспользуем build_top как есть (он завязан на
    фиксированный SELECT без gold_coin/diamond_coin), а делаем отдельный запрос:
    та же колонка, что и build_top, плюс сама валюта — так топ гкоин/акоин может
    показывать бейджи так же, как остальные топы (топ коин и т.д.), а не выглядеть
    урезанной версией. Исключает забаненных (game_banned), как и build_top."""
    if chat_id is None:
        rows = await db_query(
            f"SELECT username, nickname, {column}, evolution_level, cases_opened, total_farmed, vip_until, "
            f"shown_badges, coins, rebirth_points, ultra_rebirth, bonus_streak, crafts_done, prestige_points, promo_badges "
            f"FROM users WHERE (game_banned IS NULL OR game_banned = 0) AND {column} > 0 "
            f"ORDER BY {column} DESC LIMIT ?",
            (limit,),
        )
    else:
        rows = await db_query(
            f"""SELECT u.username, u.nickname, u.{column}, u.evolution_level, u.cases_opened, u.total_farmed, u.vip_until,
                    u.shown_badges, u.coins, u.rebirth_points, u.ultra_rebirth, u.bonus_streak, u.crafts_done, u.prestige_points, u.promo_badges
                FROM users u
                JOIN chat_members cm ON u.user_id = cm.user_id
                WHERE cm.chat_id = ? AND (u.game_banned IS NULL OR u.game_banned = 0) AND u.{column} > 0
                ORDER BY u.{column} DESC LIMIT ?""",
            (chat_id, limit),
        )
    return rows

def _format_premium_coin_top_line(i, row, emoji):
    (username, nickname, coin_value, evolution_level, cases_opened, total_farmed, vip_until,
     shown_badges, coins, rebirth_points, ultra_rebirth, bonus_streak, crafts_done, prestige_points, promo_badges_raw) = row
    badges = get_badges(username, evolution_level, cases_opened, total_farmed, is_vip_active(vip_until),
                         parse_shown(shown_badges), parse_promo_badges(promo_badges_raw), coins, rebirth_points,
                         bool(ultra_rebirth), bonus_streak, crafts_done, prestige_points)
    return f"{i}. {esc(display_name(username, nickname))}{badges} — {coin_value} {emoji}\n"

async def send_gold_coin_top(message: Message, chat_id, title: str):
    rows = await build_premium_coin_top(chat_id, "gold_coin")
    if not rows:
        await message.reply(TEXTS["send_gold_coin_top_1"])
        return
    text = f"🌕 <b>{title}</b>\n\n"
    for i, row in enumerate(rows, 1):
        text += _format_premium_coin_top_line(i, row, "🌕")
    await message.reply(text)

async def send_diamond_coin_top(message: Message, chat_id, title: str):
    rows = await build_premium_coin_top(chat_id, "diamond_coin")
    if not rows:
        await message.reply(TEXTS["send_diamond_coin_top_1"])
        return
    text = f"💎 <b>{title}</b>\n\n"
    for i, row in enumerate(rows, 1):
        text += _format_premium_coin_top_line(i, row, "💎")
    await message.reply(text)

@dp.message(F.text.lower() == "топ гкоин")
async def top_gold_coin_local(message: Message):
    await send_gold_coin_top(message, message.chat.id, "ТОП ГКОИН ЭТОГО ЧАТА")

@dp.message(F.text.lower() == "гл топ гкоин")
async def top_gold_coin_global(message: Message):
    await send_gold_coin_top(message, None, "ТОП ГКОИН ВЕЗДЕ")

@dp.message(F.text.lower() == "топ гкоин вся")
async def top_gold_coin_global_suffix(message: Message):
    await send_gold_coin_top(message, None, "ТОП ГКОИН ВЕЗДЕ")

@dp.message(F.text.lower() == "топ акоин")
async def top_diamond_coin_local(message: Message):
    await send_diamond_coin_top(message, message.chat.id, "ТОП АКОИН ЭТОГО ЧАТА")

@dp.message(F.text.lower() == "гл топ акоин")
async def top_diamond_coin_global(message: Message):
    await send_diamond_coin_top(message, None, "ТОП АКОИН ВЕЗДЕ")

@dp.message(F.text.lower() == "топ акоин вся")
async def top_diamond_coin_global_suffix(message: Message):
    await send_diamond_coin_top(message, None, "ТОП АКОИН ВЕЗДЕ")

@dp.message(F.text.lower() == "топ ног")
async def top_legs_local(message: Message):
    await send_legs_top(message, message.chat.id, "ТОП-10 НОГ ЭТОГО ЧАТА")

@dp.message(F.text.lower() == "гл топ ног")
async def top_legs_global(message: Message):
    await send_legs_top(message, None, "ТОП-10 НОГ ВЕЗДЕ")

@dp.message(F.text.lower() == "топ эво")
async def top_evo_local(message: Message):
    await send_evo_top(message, message.chat.id, "ТОП ЭВОЛЮЦИЙ ЭТОГО ЧАТА")

@dp.message(F.text.lower() == "гл топ эво")
async def top_evo_global(message: Message):
    await send_evo_top(message, None, "ТОП ЭВОЛЮЦИЙ ВЕЗДЕ")

@dp.message(F.text.lower() == "топ коин")
async def top_coin_local(message: Message):
    await send_coin_top(message, message.chat.id, "ТОП МОНЕТ ЭТОГО ЧАТА")

@dp.message(F.text.lower() == "гл топ коин")
async def top_coin_global(message: Message):
    await send_coin_top(message, None, "ТОП МОНЕТ ВЕЗДЕ")

@dp.message(F.text.lower() == "топ очкп")
async def top_rebirth_local(message: Message):
    await send_rebirth_top(message, message.chat.id, "ТОП ОЧКОВ ПЕРЕРОЖДЕНИЯ ЭТОГО ЧАТА")

@dp.message(F.text.lower() == "гл топ очкп")
async def top_rebirth_global(message: Message):
    await send_rebirth_top(message, None, "ТОП ОЧКОВ ПЕРЕРОЖДЕНИЯ ВЕЗДЕ")

@dp.message(F.text.lower() == "топ ноги вся")
async def top_legs_global_suffix(message: Message):
    await send_legs_top(message, None, "ТОП-10 НОГ ВЕЗДЕ")

@dp.message(F.text.lower() == "топ коин вся")
async def top_coin_global_suffix(message: Message):
    await send_coin_top(message, None, "ТОП МОНЕТ ВЕЗДЕ")

@dp.message(F.text.lower() == "топ эво вся")
async def top_evo_global_suffix(message: Message):
    await send_evo_top(message, None, "ТОП ЭВОЛЮЦИЙ ВЕЗДЕ")

@dp.message(F.text.lower() == "топ очкп вся")
async def top_rebirth_global_suffix(message: Message):
    await send_rebirth_top(message, None, "ТОП ОЧКОВ ПЕРЕРОЖДЕНИЯ ВЕЗДЕ")

@dp.message(F.text.lower().in_({"топ вся", "гл топ"}))
async def top_overall_global(message: Message):
    await send_legs_top(message, None, "ОБЩИЙ ТОП ВЕЗДЕ (по очкам ноги)")

@dp.message(F.text.lower().in_({"ферма", "фарма"}))
async def farm(message: Message):
    if not await require_subscription(message):
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    now = int(time.time())

    row = await ensure_user(user_id, username)
    score, evolution_level, active_item = row[2], row[3], row[6]
    last_farm, levelup_notify, vip_until = row[4], row[11], row[12]
    rebirth_points, rebirth_count = row[14], row[15]
    upgrades = parse_upgrades(row[16])
    active_items = parse_equipped(row[18])
    ultra_rebirth = bool(row[21])
    auto_evolve_enabled = bool(row[22])
    auto_rebirth_enabled = bool(row[29])
    prestige_points = row[27]
    vip_active = is_vip_active(vip_until)
    inv_rows = await get_inventory(user_id)
    inventory_map = {k: q for k, q in inv_rows}
    potions = active_potions_now(row[23], now, active_items, inventory_map)
    prestige_upgrades = parse_prestige_upgrades(row[28])
    chronos_boost_pct = row[34] if len(row) > 34 else 100
    compact_mode = bool(row[35]) if len(row) > 35 else False
    vilon_boost_until = row[38] if len(row) > 38 else 0
    kotyara_boost_until = row[40] if len(row) > 40 else 0

    has_time_particle = inventory_map.get("time_particle", 0) > 0

    cooldown = farm_cd_seconds(upgrades, active_items, has_time_particle, prestige_upgrades)
    has_no_cd = NO_CD_CHARGES_KEY in potions
    if not has_no_cd and now - last_farm < cooldown:
        left = cooldown - (now - last_farm)
        m, s = divmod(left, 60)
        await message.reply(TEXTS["farm_1"].format(v0=m, v1=s))
        return

    auto_legs, auto_coins, auto_rebirth, auto_gold_coin, score, _coins_after = await claim_offline_auto_farm(user_id, row)
    if auto_rebirth:
        rebirth_points += auto_rebirth

    low, high = farm_range(evolution_level)
    nano_it_count = inventory_map.get("nano_it", 0)
    mult = get_multiplier(evolution_level, active_items, vip_active, upgrades, ultra_rebirth, chronos_boost_pct, nano_it_count)
    event_mult = await get_event_multiplier()
    personal_mult = await get_personal_multiplier(user_id)
    p_yield_mult = 1 + 0.005 * prestige_bonus(prestige_upgrades, "p_farm_yield")
    gained = round(random.randint(low, high) * farm_yield_multiplier(upgrades) * mult * event_mult * personal_mult * p_yield_mult)
    if evolution_level >= EVO_UNLOCK_MEK2_LEVEL:
        gained += EVO_FARM_BONUS_LVL10
    pocket_star_text = ""
    if inventory_map.get("pocket_star", 0) > 0:
        gained = round(gained * POCKET_STAR_FARM_CMD_MULT)
        rebirth_gain = random.randint(*POCKET_STAR_FARM_CMD_REBIRTH_RANGE)
        await db_exec(
            "UPDATE users SET rebirth_points = rebirth_points + ? WHERE user_id = ?",
            (rebirth_gain, user_id),
        )
        pocket_star_text = f"\n{ITEMS['pocket_star'][0]} Карманная звезда: +{rebirth_gain}🉑!"
    gained = apply_vilon_amulet_boost(gained, vilon_boost_until)
    gained = apply_kotyara_amulet_boost(gained, kotyara_boost_until)
    potion_bits = []
    if "potion_speed" in potions:
        base_speed_mult = DRAGON_CLAW_POTION_MULT if "dragon_claw" in set(_normalize_active_items(active_items)) else 2
        speed_mult = round(base_speed_mult * potion_boost_multiplier(upgrades), 2)
        gained *= speed_mult
        potion_bits.append(f"🧪⚡ x{speed_mult}")

    chronos_text, chronos_reset_cd, chronos_farm_mult = await apply_chronos_orb_procs(user_id, active_items)
    if chronos_farm_mult != 1.0:
        gained = round(gained * chronos_farm_mult)

    echo_text = ""
    echo_chance = echo_farm_chance(upgrades)
    if echo_chance and random.random() < echo_chance:
        gained *= 2
        echo_text = "✨ Эхо фарма: x2!"

    content_boost_until = row[50] if len(row) > 50 else 0
    content_boost_text = ""
    if content_boost_until and content_boost_until > now:
        gained = round(gained * CONTENT_BOOST_MULT)
        content_boost_text = f"⚡ Буст x{CONTENT_BOOST_MULT:g}!"

    gained, nogost_coin_text = apply_coin_tree_farm_roll(gained, active_items)
    new_score = score + gained

    new_last_farm = 0 if chronos_reset_cd else now
    await db_exec(
        "UPDATE users SET score = ?, last_farm = ?, total_farmed = total_farmed + ? WHERE user_id = ?",
        (new_score, new_last_farm, gained, user_id),
    )

    if has_no_cd:
        potions = await consume_no_cd_charge(user_id, potions)
        charges_left = potions.get(NO_CD_CHARGES_KEY, 0)
        potion_bits.append(f"🧪🌀 заряд использован ({charges_left} ост.)")

    luck_mult = (2.0 * potion_boost_multiplier(upgrades)) if "luck_x2" in potions else 1.0
    guaranteed_rebirth = has_potion_effect(potions, "rebirth_on_farm")
    vase_text = await apply_vase_proc(user_id, inventory_map, luck_mult)
    bonus = await apply_farm_bonuses(user_id, active_items, inventory_map, luck_mult, guaranteed_rebirth, coin_magnet_bonus(upgrades))
    chaos_text = await apply_chaos_orb_proc(user_id, inventory_map)
    necklace_text = (
        await apply_blazing_necklace_proc(user_id, active_items)
        + await apply_star_necklace_proc(user_id, active_items)
    )
    craft_charm_text = (
        await apply_elemental_charm_proc(user_id, active_items)
        + await apply_twilight_amulet_proc(user_id, active_items)
        + await apply_chaos_fang_proc(user_id, active_items)
    )
    mastery_text, mastery_bitcoin_bonus = await apply_mastery_lover_proc(user_id, active_items)
    rebirth_coin_text = await apply_rebirth_coin_proc(user_id, inventory_map)
    coin_tree_text = (
        nogost_coin_text
        + await apply_godly_nogost_coin_case_proc(user_id, inventory_map)
        + await apply_bitcoin_proc(user_id, inventory_map, mastery_bitcoin_bonus)
    )
    kotyara_text = await apply_kotyara_amulet_trigger(user_id, active_items)

    await maybe_announce_levelup(message, username, score, new_score, evolution_level, bool(levelup_notify), rebirth_count, ultra_rebirth, **hardness_kwargs(row))

    auto_evo_text = ""
    if vip_active and auto_evolve_enabled:
        evolution_level, new_score, auto_evo_text = await try_auto_evolve(user_id, new_score, evolution_level, rebirth_count, active_items, **hardness_kwargs(row))

    auto_rebirth_text = ""
    if vip_active and auto_rebirth_enabled:
        new_score, evolution_level, rebirth_count, rebirth_points, prestige_points, auto_rebirth_text = await try_auto_rebirth(
            user_id, new_score, evolution_level, rebirth_count, rebirth_points, prestige_points, prestige_upgrades, active_items
        )

    auto_text = ""
    if auto_legs or auto_coins or auto_rebirth or auto_gold_coin:
        bits = []
        if auto_legs:
            bits.append(f"+{auto_legs} очков")
        if auto_coins:
            bits.append(f"+{auto_coins} 🪙")
        if auto_rebirth:
            bits.append(f"+{auto_rebirth} 🉑")
        if auto_gold_coin:
            bits.append(f"+{auto_gold_coin} 🌕")
        auto_text = f"\n⚙️ Авто-Ферма накопила: {', '.join(bits)}"

    coin_text = f" +{bonus['coins']}🪙" if bonus["coins"] else ""
    rebirth_farm_text = f"🧪🉑 +{bonus['rebirth']}🉑" if (bonus["rebirth"] and not bonus["is_god"]) else ""
    combo_bits = [b for b in (vase_text, *potion_bits, rebirth_coin_text, rebirth_farm_text, echo_text, content_boost_text) if b]
    combo_text = ("\n" + " · ".join(combo_bits)) if combo_bits else ""
    bonus_text = "" if compact_mode else (combo_text + chaos_text + chronos_text + coin_tree_text + pocket_star_text + necklace_text + craft_charm_text + mastery_text)
    kotyara_combo_text = f"\n{kotyara_text}" if kotyara_text else ""
    extra_text = bonus_text + auto_evo_text + auto_rebirth_text + ("" if compact_mode else kotyara_combo_text)
    chronos_equipped = "chronos_orb" in set(_normalize_active_items(active_items))

    content_phrase = content_bonus_text_override(active_items)
    if content_phrase:
        extra_text += f"\n{content_phrase}"

    if bonus["is_god"]:
        flavor = CHRONOS_ORB_FLAVOR if chronos_equipped else GOD_ESSENCE_FLAVOR
        god_extra = f" +{bonus['rebirth']}🉑" if bonus["rebirth"] else ""
        await safe_reply(
            message,
            TEXTS["farm_2"].format(v0=flavor, v1=gained, v2=new_score, v3=coin_text, v4=god_extra, v5=auto_text, v6=extra_text)
        )
        return

    if chronos_equipped:
        await safe_reply(
            message,
            TEXTS["farm_2"].format(v0=CHRONOS_ORB_FLAVOR, v1=gained, v2=new_score, v3=coin_text, v4="", v5=auto_text, v6=extra_text)
        )
        return

    await message.reply(
        TEXTS["farm_3"].format(v0=gained, v1=new_score, v2=coin_text, v3=auto_text, v4=extra_text)
    )

@dp.message(F.text.lower() == "бонус")
async def daily_bonus(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    now = int(time.time())

    row = await ensure_user(user_id, username)
    score, evolution_level = row[2], row[3]
    last_bonus, bonus_streak, levelup_notify = row[9], row[10], row[11]

    elapsed = now - last_bonus
    if last_bonus and elapsed < DAILY_MIN_GAP:
        left = DAILY_MIN_GAP - elapsed
        h, rem = divmod(left, 3600)
        m = rem // 60
        await message.reply(TEXTS["daily_bonus_1"].format(v0=h, v1=m))
        return

    if last_bonus and elapsed <= DAILY_STREAK_LIMIT:
        streak = bonus_streak + 1
    else:
        streak = 1

    day_index = (streak - 1) % len(DAILY_TABLE)
    reward = DAILY_TABLE[day_index]
    new_score = score + reward

    await db_exec(
        "UPDATE users SET score = ?, total_farmed = total_farmed + ?, last_bonus = ?, bonus_streak = ? WHERE user_id = ?",
        (new_score, reward, now, streak, user_id),
    )

    item_text = ""
    if day_index == len(DAILY_TABLE) - 1:
        await add_item(user_id, "daily_charm")
        item_text = f"\n{PREMIUM_DAILY_CHARM} Плюс Дневной амулет (+15% буст) в инвентарь!"

    await maybe_announce_levelup(message, username, score, new_score, evolution_level, bool(levelup_notify), **hardness_kwargs(row))
    await message.reply(TEXTS["daily_bonus_2"].format(v0=streak, v1=reward, v2=new_score, v3=item_text))

# ==== Ютубер/Тиктокер команды (см. система титулов) ====
CONTENT_RESET_COOLDOWN = 20 * 60
CONTENT_BOOST_COOLDOWN = 30 * 60
CONTENT_BOOST_DURATION = 5 * 60
CONTENT_BOOST_MULT = 2.0
CONTENT_SPEEDUP_COOLDOWN = 8 * 3600
CONTENT_BONUS_COOLDOWN = 24 * 3600

CONTENT_RESET_ALIASES = {
    "кд": "cd", "фарм": "cd", "ферма": "cd",
    "эво": "evo", "эволюция": "evo", "эволюции": "evo",
    "перерождение": "rebirth", "перерождения": "rebirth", "перерождений": "rebirth",
}

@dp.message(F.text.regexp(r"(?i)^\?сброс\s+(\S+)$"))
async def content_reset(message: Message):
    role = await get_content_role(message)
    if not role:
        return
    match = re.match(r"(?i)^\?сброс\s+(\S+)$", message.text.strip())
    arg = match.group(1).lower()
    reset_kind = CONTENT_RESET_ALIASES.get(arg)
    if not reset_kind:
        await message.reply("Формат: ?сброс кд / ?сброс эво / ?сброс перерождение")
        return

    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    row = await ensure_user(user_id, username)

    if not is_developer(message):
        now = int(time.time())
        last_used = row[48] if len(row) > 48 else 0  # content_reset_last
        wait_left = CONTENT_RESET_COOLDOWN - (now - last_used)
        if wait_left > 0:
            wm, ws = divmod(wait_left, 60)
            await message.reply(f"КД на «?сброс»: подожди ещё {wm} мин {ws} сек.")
            return
        await db_exec("UPDATE users SET content_reset_last = ? WHERE user_id = ?", (now, user_id))

    if reset_kind == "cd":
        await db_exec("UPDATE users SET last_farm = 0 WHERE user_id = ?", (user_id,))
        await message.reply("⏱️ Кулдаун фермы сброшен!")
    elif reset_kind == "evo":
        old_evo = row[3]
        await db_exec("UPDATE users SET evolution_level = 0, evo_hardness_mult = 1.0 WHERE user_id = ?", (user_id,))
        await message.reply(f"🌑 Эволюция сброшена: {old_evo} → 0 (усложнение снято).")
    elif reset_kind == "rebirth":
        old_rebirth = row[15]
        await db_exec("UPDATE users SET rebirth_count = 0, rebirth_hardness_mult = 1.0 WHERE user_id = ?", (user_id,))
        await message.reply(f"🌘 Перерождения сброшены: {old_rebirth} → 0 (усложнение снято).")

@dp.message(F.text.lower() == "?буст")
async def content_boost(message: Message):
    role = await get_content_role(message)
    if not role:
        return

    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    row = await ensure_user(user_id, username)
    now = int(time.time())

    if not is_developer(message):
        last_used = row[49] if len(row) > 49 else 0  # content_boost_last
        wait_left = CONTENT_BOOST_COOLDOWN - (now - last_used)
        if wait_left > 0:
            wm, ws = divmod(wait_left, 60)
            await message.reply(f"КД на «?буст»: подожди ещё {wm} мин {ws} сек.")
            return
        await db_exec("UPDATE users SET content_boost_last = ? WHERE user_id = ?", (now, user_id))

    until = now + CONTENT_BOOST_DURATION
    await db_exec("UPDATE users SET content_boost_until = ? WHERE user_id = ?", (until, user_id))
    await message.reply(f"⚡ Буст x{CONTENT_BOOST_MULT:g} активирован на {CONTENT_BOOST_DURATION // 60} минут!")

CONTENT_SPEEDUP_ALIASES = {
    "зелье": "potion", "зелья": "potion",
    "бонус": "bonus",
}

@dp.message(F.text.regexp(r"(?i)^\?ускорение\s+(\S+)$"))
async def content_speedup(message: Message):
    role = await get_content_role(message)
    if not role:
        return
    match = re.match(r"(?i)^\?ускорение\s+(\S+)$", message.text.strip())
    arg = match.group(1).lower()
    kind = CONTENT_SPEEDUP_ALIASES.get(arg)
    if not kind:
        await message.reply("Формат: ?ускорение зелье / ?ускорение бонус")
        return

    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    row = await ensure_user(user_id, username)
    now = int(time.time())

    if not is_developer(message):
        last_used = row[51] if len(row) > 51 else 0  # content_speedup_last
        wait_left = CONTENT_SPEEDUP_COOLDOWN - (now - last_used)
        if wait_left > 0:
            wh, wrem = divmod(wait_left, 3600)
            wm = wrem // 60
            await message.reply(f"КД на «?ускорение»: подожди ещё {wh} ч {wm} мин.")
            return

    if kind == "potion":
        brewing_potion, brewing_until = row[24], row[25]
        if not brewing_potion or brewing_until <= now:
            await message.reply("Сейчас ничего не варится — нечего ускорять.")
            return
        await db_exec("UPDATE users SET brewing_until = 0 WHERE user_id = ?", (user_id,))
        cfg = POTIONS[brewing_potion]
        await message.reply(f"⚡ Варка {cfg['emoji']} {esc(cfg['name'])} завершена мгновенно!")
    elif kind == "bonus":
        last_bonus = row[9]
        if now - last_bonus >= DAILY_MIN_GAP:
            await message.reply("Бонус уже доступен — напиши «бонус», ускорять нечего.")
            return
        await db_exec("UPDATE users SET last_bonus = ? WHERE user_id = ?", (now - DAILY_MIN_GAP, user_id))
        await message.reply("⚡ Ежедневный бонус готов — напиши «бонус»!")

    if not is_developer(message):
        await db_exec("UPDATE users SET content_speedup_last = ? WHERE user_id = ?", (now, user_id))

CONTENT_BONUS_REWARDS = [
    ("legs", 2_500_000_000, "🦵 {v} очков ног"),
    ("coin", 500_000, "🪙 {v} монет"),
    ("rebirth", 2_500, "🉑 {v} очков перерождения"),
    ("prestige", 2_500, "🔮 {v} очков престижа"),
]
CONTENT_BONUS_ITEM_CHANCE = 0.025

@dp.message(F.text.lower() == "?бонус")
async def content_bonus(message: Message):
    role = await get_content_role(message)
    if not role:
        return

    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    row = await ensure_user(user_id, username)
    now = int(time.time())

    if not is_developer(message):
        last_used = row[52] if len(row) > 52 else 0  # content_bonus_last
        wait_left = CONTENT_BONUS_COOLDOWN - (now - last_used)
        if wait_left > 0:
            wh, wrem = divmod(wait_left, 3600)
            wm = wrem // 60
            await message.reply(f"КД на «?бонус»: подожди ещё {wh} ч {wm} мин.")
            return
        await db_exec("UPDATE users SET content_bonus_last = ? WHERE user_id = ?", (now, user_id))

    reward_type, amount, label_fmt = random.choice(CONTENT_BONUS_REWARDS)
    column = {"legs": "score", "coin": "coins", "rebirth": "rebirth_points", "prestige": "prestige_points"}[reward_type]
    await db_exec(f"UPDATE users SET {column} = {column} + ? WHERE user_id = ?", (amount, user_id))
    reward_text = label_fmt.format(v=amount)

    item_text = ""
    if random.random() < CONTENT_BONUS_ITEM_CHANCE:
        item_key = "youtube_button" if role == "youtuber" else "tiktok_legend"
        await add_item(user_id, item_key)
        emoji, name, percent, _ = ITEMS[item_key]
        item_text = f"\n✨ Плюс бустер {emoji} {esc(name)} (+{percent}%) в инвентарь!"

    await message.reply(f"🎁 Бонус за контент: +{reward_text}!{item_text}")

CONTENT_HELP_TEXT = (
    "📋 <b>Команды для контент-мейкеров</b>\n"
    "● ?сброс кд / эво / перерождение — сбрасывает кулдаун фермы или усложнение (КД 20 мин)\n"
    "● ?буст — буст x2 на 5 минут (КД 30 мин)\n"
    "● ?ускорение зелье / бонус — мгновенно завершает варку зелья или ежедневный бонус (КД 8 ч)\n"
    "● ?бонус — случайная награда: ноги, монеты, очкп или престиж, и небольшой шанс на "
    "уникальный бустер (КД 24 ч)\n"
    "● ?хелп / ?помощь — эта справка"
)

@dp.message(F.text.lower().in_({"?хелп", "?помощь"}))
async def content_help(message: Message):
    role = await get_content_role(message)
    if not role:
        return
    await message.reply(CONTENT_HELP_TEXT)

@dp.message(F.text.regexp(REVERSE_EXCHANGE_RE))
async def reverse_exchange(message: Message):
    """обменять <кол-во> коин -> списывает коины, начисляет очки ног (1 коин = 150 очков)."""
    match = REVERSE_EXCHANGE_RE.match(message.text.strip())
    coins_wanted = parse_amount(match.group(1))
    if not coins_wanted or coins_wanted <= 0:
        await message.reply(TEXTS["reverse_exchange_1"])
        return

    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"

    row = await ensure_user(user_id, username)
    score, coins, evolution_level = row[2], row[5], row[3]
    rebirth_count = row[15]
    levelup_notify = row[11]

    if coins_wanted > coins:
        await message.reply(TEXTS["reverse_exchange_2"].format(v0=coins))
        return

    gained = coins_wanted * REVERSE_EXCHANGE_RATE
    new_coins = coins - coins_wanted
    new_score = score + gained

    await db_exec("UPDATE users SET score = ?, coins = ? WHERE user_id = ?", (new_score, new_coins, user_id))

    await maybe_announce_levelup(message, username, score, new_score, evolution_level, bool(levelup_notify), rebirth_count, **hardness_kwargs(row))
    await message.reply(TEXTS["reverse_exchange_3"].format(v0=coins_wanted, v1=gained, v2=new_score))

@dp.message(F.text.regexp(CRAFT_EXCHANGE_RE))
async def craft_exchange(message: Message):
    """обменять <кол-во> крафт/очкк -> списывает очки перерождения, начисляет очки крафта
    (курс: CRAFT_POINTS_EXCHANGE_RATE 🉑 = 1 💠). <кол-во> здесь — это 🉑, которые отдаёшь."""
    match = CRAFT_EXCHANGE_RE.match(message.text.strip())
    rebirth_wanted = parse_amount(match.group(1))
    if not rebirth_wanted or rebirth_wanted <= 0:
        await message.reply("Количество очков перерождения должно быть больше нуля.")
        return
    if rebirth_wanted % CRAFT_POINTS_EXCHANGE_RATE != 0:
        await message.reply(
            f"Обменивать можно только кратно {CRAFT_POINTS_EXCHANGE_RATE} 🉑 "
            f"(например: обменять {CRAFT_POINTS_EXCHANGE_RATE} крафт).\n"
            f"Хочешь сразу задать нужное число очков крафта — пиши «обменять очкк <число>» "
            f"(например: обменять очкк 3 → спишет {3 * CRAFT_POINTS_EXCHANGE_RATE} 🉑)."
        )
        return

    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"

    row = await ensure_user(user_id, username)
    rebirth_points = row[14]
    craft_points = row[32]

    if rebirth_wanted > rebirth_points:
        await message.reply(
            f"Недостаточно очков перерождения. У тебя {rebirth_points} 🉑, "
            f"нужно {rebirth_wanted} 🉑 (= {rebirth_wanted // CRAFT_POINTS_EXCHANGE_RATE} 💠)."
        )
        return

    gained = rebirth_wanted // CRAFT_POINTS_EXCHANGE_RATE
    new_rebirth_points = rebirth_points - rebirth_wanted
    new_craft_points = craft_points + gained

    await db_exec(
        "UPDATE users SET rebirth_points = ?, craft_points = ? WHERE user_id = ?",
        (new_rebirth_points, new_craft_points, user_id),
    )

    await message.reply(
        f"Обменял {rebirth_wanted} 🉑 → +{gained} 💠 очков крафта (Всего: {new_craft_points})"
    )

@dp.message(F.text.regexp(CRAFT_EXCHANGE_TO_RE))
async def craft_exchange_to(message: Message):
    """обменять крафт/очкк <кол-во> -> удобный обратный формат: <кол-во> это то, сколько
    очков крафта 💠 хочешь ПОЛУЧИТЬ. Бот сам считает нужные 🉑 (по курсу) и списывает их."""
    match = CRAFT_EXCHANGE_TO_RE.match(message.text.strip())
    craft_wanted = parse_amount(match.group(1))
    if not craft_wanted or craft_wanted <= 0:
        await message.reply("Количество очков крафта должно быть больше нуля.")
        return

    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"

    row = await ensure_user(user_id, username)
    rebirth_points = row[14]
    craft_points = row[32]

    rebirth_cost = craft_wanted * CRAFT_POINTS_EXCHANGE_RATE

    if rebirth_cost > rebirth_points:
        max_affordable = rebirth_points // CRAFT_POINTS_EXCHANGE_RATE
        await message.reply(
            f"Недостаточно очков перерождения. У тебя {rebirth_points} 🉑, "
            f"нужно {rebirth_cost} 🉑 на {craft_wanted} 💠.\n"
            f"Сейчас можешь обменять максимум {max_affordable} 💠 "
            f"(обменять очкк {max_affordable})." if max_affordable > 0 else
            f"Недостаточно очков перерождения. У тебя {rebirth_points} 🉑, "
            f"нужно {rebirth_cost} 🉑 на {craft_wanted} 💠."
        )
        return

    new_rebirth_points = rebirth_points - rebirth_cost
    new_craft_points = craft_points + craft_wanted

    await db_exec(
        "UPDATE users SET rebirth_points = ?, craft_points = ? WHERE user_id = ?",
        (new_rebirth_points, new_craft_points, user_id),
    )

    await message.reply(
        f"Обменял {rebirth_cost} 🉑 → +{craft_wanted} 💠 очков крафта (Всего: {new_craft_points})"
    )

GOLD_COIN_RATE = 1000
DIAMOND_COIN_RATE = 1000

@dp.message(F.text.regexp(GOLD_COIN_EXCHANGE_RE))
async def gold_coin_exchange(message: Message):
    """обменять гкоин/голдкоин <кол-во> -> <кол-во> это сколько 🌕 гкоин хочешь ПОЛУЧИТЬ.
    Курс: GOLD_COIN_RATE 🪙 = 1 🌕. Требует обменник (exchanger) 1+ лвл — без него
    команда недоступна, апгрейд покупается в апгрейдах за 🉑+🪙 (см. UPGRADES['exchanger'])."""
    match = GOLD_COIN_EXCHANGE_RE.match(message.text.strip())
    gold_wanted = parse_amount(match.group(1))
    if not gold_wanted or gold_wanted <= 0:
        await message.reply(TEXTS["gold_coin_exchange_1"])
        return

    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"

    row = await ensure_user(user_id, username)
    coins = row[5]
    upgrades = parse_upgrades(row[16])
    if upgrade_level(upgrades, "exchanger") < 1:
        await message.reply(TEXTS["gold_coin_exchange_2"])
        return

    coin_cost = gold_wanted * GOLD_COIN_RATE
    if coin_cost > coins:
        max_affordable = coins // GOLD_COIN_RATE
        await message.reply(TEXTS["gold_coin_exchange_3"].format(v0=coins, v1=coin_cost, v2=gold_wanted, v3=max_affordable))
        return

    gc_row = await db_query_one("SELECT gold_coin FROM users WHERE user_id = ?", (user_id,))
    new_gold_coin = (gc_row[0] if gc_row else 0) + gold_wanted
    new_coins = coins - coin_cost
    await db_exec(
        "UPDATE users SET coins = ?, gold_coin = ? WHERE user_id = ?",
        (new_coins, new_gold_coin, user_id),
    )
    await message.reply(TEXTS["gold_coin_exchange_4"].format(v0=coin_cost, v1=gold_wanted, v2=new_gold_coin))

@dp.message(F.text.regexp(DIAMOND_COIN_EXCHANGE_RE))
async def diamond_coin_exchange(message: Message):
    """обменять акоин/алмкоин/алмазкоин <кол-во> -> <кол-во> это сколько 💎 акоин хочешь
    ПОЛУЧИТЬ. Курс: DIAMOND_COIN_RATE 🌕 = 1 💎. Требует обменник 2 лвл."""
    match = DIAMOND_COIN_EXCHANGE_RE.match(message.text.strip())
    diamond_wanted = parse_amount(match.group(1))
    if not diamond_wanted or diamond_wanted <= 0:
        await message.reply(TEXTS["diamond_coin_exchange_1"])
        return

    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"

    row = await ensure_user(user_id, username)
    upgrades = parse_upgrades(row[16])
    if upgrade_level(upgrades, "exchanger") < 2:
        await message.reply(TEXTS["diamond_coin_exchange_2"])
        return

    gc_row = await db_query_one("SELECT gold_coin, diamond_coin FROM users WHERE user_id = ?", (user_id,))
    gold_coin, diamond_coin = gc_row if gc_row else (0, 0)

    gold_cost = diamond_wanted * DIAMOND_COIN_RATE
    if gold_cost > gold_coin:
        max_affordable = gold_coin // DIAMOND_COIN_RATE
        await message.reply(TEXTS["diamond_coin_exchange_3"].format(v0=gold_coin, v1=gold_cost, v2=diamond_wanted, v3=max_affordable))
        return

    new_gold_coin = gold_coin - gold_cost
    new_diamond_coin = diamond_coin + diamond_wanted
    await db_exec(
        "UPDATE users SET gold_coin = ?, diamond_coin = ? WHERE user_id = ?",
        (new_gold_coin, new_diamond_coin, user_id),
    )
    await message.reply(TEXTS["diamond_coin_exchange_4"].format(v0=gold_cost, v1=diamond_wanted, v2=new_diamond_coin))

PRESTIGE_EXCHANGE_RATE = 30  # 🉑 очков перерождения за 1 🔮 очко престижа

@dp.message(F.text.regexp(PRESTIGE_EXCHANGE_RE))
async def prestige_exchange(message: Message):
    """обменять престиж <кол-во> -> <кол-во> это сколько 🔮 очков престижа хочешь ПОЛУЧИТЬ.
    Базовый курс PRESTIGE_EXCHANGE_RATE 🉑 = 1 🔮, снижается веткой 'fast_exchange' (категория 5,
    см. prestige_exchange_rate). Требует обменник 3 лвл (см. UPGRADES['exchanger'])."""
    match = PRESTIGE_EXCHANGE_RE.match(message.text.strip())
    prestige_wanted = parse_amount(match.group(1))
    if not prestige_wanted or prestige_wanted <= 0:
        await message.reply("Формат: обменять престиж <количество>. Курс: 30 🉑 = 1 🔮 (указывай сколько 🔮 хочешь получить).")
        return

    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"

    row = await ensure_user(user_id, username)
    rebirth_points = row[14]
    upgrades = parse_upgrades(row[16])
    if upgrade_level(upgrades, "exchanger") < 3:
        await message.reply("Нужен обменник 3 лвл, чтобы обменивать очкп на 🔮 престиж. Прокачай его в апгрейдах (апг).")
        return

    rate = prestige_exchange_rate(upgrades)
    rebirth_cost = prestige_wanted * rate
    if rebirth_cost > rebirth_points:
        max_affordable = rebirth_points // rate
        await message.reply(
            f"Недостаточно очков перерождения. У тебя {rebirth_points} 🉑, "
            f"нужно {rebirth_cost} 🉑 на {prestige_wanted} 🔮 (курс {rate} 🉑 = 1 🔮). "
            f"Максимум сейчас можешь получить {max_affordable} 🔮."
        )
        return

    pp_row = await db_query_one("SELECT prestige_points FROM users WHERE user_id = ?", (user_id,))
    prestige_points = pp_row[0] if pp_row else 0

    new_rebirth_points = rebirth_points - rebirth_cost
    new_prestige_points = prestige_points + prestige_wanted
    await db_exec(
        "UPDATE users SET rebirth_points = ?, prestige_points = ? WHERE user_id = ?",
        (new_rebirth_points, new_prestige_points, user_id),
    )
    await message.reply(f"Обменял {rebirth_cost} 🉑 → +{prestige_wanted} 🔮 престижа (Всего: {new_prestige_points})")

@dp.message(F.text.lower().startswith("обменять "))
async def exchange(message: Message):
    match = EXCHANGE_RE.match(message.text.strip().lower())
    if not match:
        await message.reply(TEXTS["exchange_1"].format(v0=EXCHANGE_RATE))
        return

    coins_wanted = parse_amount(match.group(1))
    if not coins_wanted or coins_wanted <= 0:
        await message.reply(TEXTS["exchange_2"])
        return

    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"

    row = await ensure_user(user_id, username)
    score, coins, evolution_level = row[2], row[5], row[3]
    rebirth_count = row[15]
    ultra_rebirth = bool(row[21])

    spent = coins_wanted * EXCHANGE_RATE
    if spent > score:
        max_coins = score // EXCHANGE_RATE
        await message.reply(TEXTS["exchange_3"].format(v0=score, v1=max_coins))
        return

    old_level = get_level_index(score, evolution_level, rebirth_count, ultra_rebirth, **hardness_kwargs(row))
    new_score = score - spent
    new_level = get_level_index(new_score, evolution_level, rebirth_count, ultra_rebirth, **hardness_kwargs(row))
    new_coins = coins + coins_wanted

    await db_exec("UPDATE users SET score = ?, coins = ? WHERE user_id = ?", (new_score, new_coins, user_id))

    warn = f"\n⚠️ Уровень упал с {old_level} до {new_level}!" if new_level < old_level else ""
    await message.reply(TEXTS["exchange_4"].format(v0=spent, v1=coins_wanted, v2=new_coins, v3=warn))

async def transfer_currency(message: Message, currency: str, amount: int):
    """currency: 'ног', 'коин' или 'очкп'. Общая логика для дать/передать <число> <валюта>.
    'очкп' требует прокачанную ветку apгрейда 'transfer' (см. UPGRADES['transfer'] — ветка 14,
    открывается на 2 ур. апгрейдера) — без неё команда 'дать очкп' недоступна."""
    if not message.reply_to_message:
        await message.reply(TEXTS["transfer_currency_1"])
        return

    receiver = message.reply_to_message.from_user
    sender = message.from_user
    if receiver.id == sender.id:
        await message.reply(TEXTS["transfer_currency_2"])
        return

    sender_username = sender.username or sender.first_name or "Без имени"
    receiver_username = receiver.username or receiver.first_name or "Без имени"

    sender_row = await ensure_user(sender.id, sender_username)
    if sender_row[3] < 1:
        await message.reply(TEXTS["transfer_currency_3"])
        return

    if currency == "ног":
        if sender_row[2] < amount:
            await message.reply(TEXTS["transfer_currency_4"].format(v0=sender_row[2]))
            return
        receiver_row = await ensure_user(receiver.id, receiver_username)
        new_sender = sender_row[2] - amount
        new_receiver = receiver_row[2] + amount
        await db_exec("UPDATE users SET score = ? WHERE user_id = ?", (new_sender, sender.id))
        await db_exec("UPDATE users SET score = ? WHERE user_id = ?", (new_receiver, receiver.id))
        await message.reply(TEXTS["transfer_currency_5"].format(v0=esc(sender_username), v1=amount, v2=esc(receiver_username)))
        await maybe_announce_levelup(message, receiver_username, receiver_row[2], new_receiver,
                                      receiver_row[3], bool(receiver_row[11]), receiver_row[15], **hardness_kwargs(receiver_row))
    elif currency == "очкп":
        sender_upgrades = parse_upgrades(sender_row[16])
        if upgrade_level(sender_upgrades, "transfer") < 1:
            await message.reply("Нужна ветка «Передача» (апгрейд) 1 лвл, чтобы передавать 🉑 очки перерождения. Прокачай её в апгрейдах (апг).")
            return
        sender_rebirth = sender_row[14]
        if sender_rebirth < amount:
            await message.reply(f"Недостаточно 🉑 очков перерождения. У тебя {sender_rebirth}.")
            return
        await ensure_user(receiver.id, receiver_username)
        await db_exec("UPDATE users SET rebirth_points = rebirth_points - ? WHERE user_id = ?", (amount, sender.id))
        await db_exec("UPDATE users SET rebirth_points = rebirth_points + ? WHERE user_id = ?", (amount, receiver.id))
        await message.reply(f"{esc(sender_username)} передал {amount} 🉑 игроку {esc(receiver_username)}")
    else:
        if sender_row[5] < amount:
            await message.reply(TEXTS["transfer_currency_6"].format(v0=sender_row[5]))
            return
        await ensure_user(receiver.id, receiver_username)
        await db_exec("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amount, sender.id))
        await db_exec("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, receiver.id))
        await message.reply(TEXTS["transfer_currency_7"].format(v0=esc(sender_username), v1=amount, v2=esc(receiver_username)))

async def transfer_item_direct(message: Message, item_query: str):
    """Прямой поиск предмета по вхождению строки, без разделения на бустеры/пассивки (п.2 ТЗ)."""
    if not message.reply_to_message:
        await message.reply(TEXTS["transfer_item_direct_1"])
        return

    item_key = find_item_by_name(item_query)
    if not item_key:
        await message.reply(TEXTS["transfer_item_direct_2"].format(v0=esc(item_query)))
        return

    if item_key in NON_TRADABLE_ITEMS:
        emoji, name, _, _ = ITEMS[item_key]
        await message.reply(TEXTS["transfer_item_direct_3"].format(v0=emoji, v1=esc(name)))
        return

    sender_id = message.from_user.id
    sender_username = message.from_user.username or message.from_user.first_name or "Без имени"
    receiver = message.reply_to_message.from_user
    receiver_username = receiver.username or receiver.first_name or "Без имени"

    if receiver.id == sender_id:
        await message.reply(TEXTS["transfer_item_direct_4"])
        return

    emoji, name, _, _ = ITEMS[item_key]

    await ensure_user(sender_id, sender_username)
    await ensure_user(receiver.id, receiver_username)

    removed = await remove_item(sender_id, item_key, 1)
    if not removed:
        await message.reply(TEXTS["transfer_item_direct_5"].format(v0=esc(name)))
        return

    sender_row = await get_user(sender_id)
    remaining = await get_inventory(sender_id)
    has_more = any(k == item_key and q > 0 for k, q in remaining)
    if not has_more:
        new_equipped = unequip_item(sender_row[18], item_key)
        await db_exec("UPDATE users SET equipped_items = ? WHERE user_id = ?", (format_equipped(new_equipped), sender_id))

    await add_item(receiver.id, item_key)

    await safe_reply(message, TEXTS["transfer_item_direct_6"].format(v0=emoji, v1=esc(name), v2=esc(receiver_username)))

_TRANSFER_CURRENCY_TOKENS = {"ног": "ног", "коин": "коин", "очкп": "очкп"}

@dp.message(F.text.regexp(r"(?i)^(дать|передать)\s+(.+)$"))
async def give_or_transfer(message: Message):
    """Умный хендлер: 'дать 888 коин' -> валюта, 'дать свеча' / 'передать свеча' -> предмет.
    Синтаксис определяется автоматически по структуре аргументов."""
    text = message.text.strip()
    verb, _, args = text.partition(" ")
    args = args.strip()
    if not args:
        await message.reply(TEXTS["give_or_transfer_1"])
        return

    parts = args.split(" ", 1)
    first_word = parts[0]
    rest = parts[1].strip() if len(parts) > 1 else ""

    if _AMOUNT_TOKEN_RE.match(first_word) and rest:
        currency_word = rest.split(" ", 1)[0].lower()
        if currency_word in _TRANSFER_CURRENCY_TOKENS:
            amount = parse_amount(first_word)
            if not amount or amount <= 0:
                await message.reply(TEXTS["give_or_transfer_2"])
                return
            await transfer_currency(message, _TRANSFER_CURRENCY_TOKENS[currency_word], amount)
            return
        else:
            await message.reply(TEXTS["give_or_transfer_3"].format(v0=esc(currency_word)))
            return

    if first_word.lower() in _TRANSFER_CURRENCY_TOKENS and rest and _AMOUNT_TOKEN_RE.match(rest.split(" ", 1)[0]):
        amount_word = rest.split(" ", 1)[0]
        amount = parse_amount(amount_word)
        if not amount or amount <= 0:
            await message.reply(TEXTS["give_or_transfer_4"])
            return
        await transfer_currency(message, _TRANSFER_CURRENCY_TOKENS[first_word.lower()], amount)
        return

    await transfer_item_direct(message, args)

async def sell_item(message: Message, prefix: str, only_passive: bool):
    raw = message.text[len(prefix):].strip()
    sell_all = False
    if raw.lower().endswith(" все"):
        sell_all = True
        raw = raw[:-len(" все")].strip()
    item_query = raw
    item_key = find_item_by_name(item_query, only_passive=only_passive)
    if not item_key:
        wrong_cmd = "продать п" if only_passive is False else "продать б"
        await message.reply(TEXTS["sell_item_1"].format(v0='предметов' if only_passive else 'бустеров', v1=wrong_cmd))
        return

    if item_key in NON_TRADABLE_ITEMS:
        emoji, name, _, _ = ITEMS[item_key]
        await message.reply(TEXTS["sell_item_2"].format(v0=emoji, v1=esc(name)))
        return

    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    await ensure_user(user_id, username)

    emoji, name, _, _ = ITEMS[item_key]

    if sell_all:
        owned_row = await db_query_one("SELECT qty FROM inventory WHERE user_id = ? AND item_key = ?", (user_id, item_key))
        qty = owned_row[0] if owned_row else 0
        if qty <= 0:
            await message.reply(TEXTS["sell_item_3"].format(v0=esc(name)))
            return
    else:
        qty = 1

    removed = await remove_item(user_id, item_key, qty)
    if not removed:
        await message.reply(TEXTS["sell_item_3"].format(v0=esc(name)))
        return

    row = await get_user(user_id)
    remaining = await get_inventory(user_id)
    has_more = any(k == item_key and q > 0 for k, q in remaining)
    if not has_more:
        new_equipped = unequip_item(row[18], item_key)
        await db_exec("UPDATE users SET equipped_items = ? WHERE user_id = ?", (format_equipped(new_equipped), user_id))

    upgrades = parse_upgrades(row[16])
    sell_lvl = upgrade_level(upgrades, "sell_boost")
    unit_price = SELL_PRICE.get(item_key, 1) + sell_bonus_coins(upgrades)
    price = unit_price * qty

    bonus_rebirth = 0
    if sell_lvl >= 3 and random.random() < 0.01:
        bonus_rebirth = 1

    if bonus_rebirth:
        await db_exec(
            "UPDATE users SET coins = coins + ?, rebirth_points = rebirth_points + ? WHERE user_id = ?",
            (price, bonus_rebirth, user_id),
        )
    else:
        await db_exec("UPDATE users SET coins = coins + ? WHERE user_id = ?", (price, user_id))

    bonus_text = " 🎉 Повезло! +1 🉑!" if bonus_rebirth else ""
    if sell_all and qty > 1:
        await safe_reply(message, TEXTS["sell_item_4_all"].format(v0=emoji, v1=esc(name), v2=qty, v3=price, v4=bonus_text))
    else:
        await safe_reply(message, TEXTS["sell_item_4"].format(v0=emoji, v1=esc(name), v2=price, v3=bonus_text))

@dp.message(F.text.lower().startswith("продать б "))
async def sell_booster(message: Message):
    await sell_item(message, "продать б ", only_passive=False)

@dp.message(F.text.lower().startswith("продать п "))
async def sell_passive(message: Message):
    await sell_item(message, "продать п ", only_passive=True)

@dp.message(F.text.regexp(r"(?i)^продать(\s+.*)?$"))
async def sell_wrong_format(message: Message):
    """Ловит 'продать <название>' без б/п (или вообще без аргумента) — чтобы не было тишины."""
    lower = message.text.lower()
    if lower.startswith("продать б ") or lower.startswith("продать п "):
        return
    await message.reply(
        TEXTS["sell_wrong_format_1"]
    )

async def destroy_item(message: Message, prefix: str, only_passive: bool):
    item_query = message.text[len(prefix):].strip()
    item_key = find_item_by_name(item_query, only_passive=only_passive)
    if not item_key:
        wrong_cmd = "уничтожение п" if only_passive is False else "уничтожение б"
        await message.reply(TEXTS["destroy_item_1"].format(v0='предметов' if only_passive else 'бустеров', v1=wrong_cmd))
        return

    if item_key in NON_TRADABLE_ITEMS:
        emoji, name, _, _ = ITEMS[item_key]
        await message.reply(TEXTS["destroy_item_2"].format(v0=emoji, v1=esc(name)))
        return

    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    await ensure_user(user_id, username)

    removed = await remove_item(user_id, item_key, 1)
    emoji, name, _, _ = ITEMS[item_key]
    if not removed:
        await message.reply(TEXTS["destroy_item_3"].format(v0=esc(name)))
        return

    row = await get_user(user_id)
    remaining = await get_inventory(user_id)
    has_more = any(k == item_key and q > 0 for k, q in remaining)
    if not has_more:
        new_equipped = unequip_item(row[18], item_key)
        await db_exec("UPDATE users SET equipped_items = ? WHERE user_id = ?", (format_equipped(new_equipped), user_id))

    await safe_reply(message, TEXTS["destroy_item_4"].format(v0=emoji, v1=esc(name)))

@dp.message(F.text.lower().startswith("уничтожение б "))
async def destroy_booster(message: Message):
    await destroy_item(message, "уничтожение б ", only_passive=False)

@dp.message(F.text.lower().startswith("уничтожение п "))
async def destroy_passive(message: Message):
    await destroy_item(message, "уничтожение п ", only_passive=True)

@dp.message(F.text.regexp(r"(?i)^уничтожение(\s+.*)?$"))
async def destroy_wrong_format(message: Message):
    lower = message.text.lower()
    if lower.startswith("уничтожение б ") or lower.startswith("уничтожение п "):
        return
    await message.reply(
        TEXTS["destroy_wrong_format_1"]
    )

def _format_equipped_item_line(item_key: str) -> str:
    emoji, name, boost_percent, _ = ITEMS[item_key]
    if item_key == "chronos_orb":
        return f"{emoji} {esc(name)} (+10-400%, рандом)"
    return f"{emoji} {esc(name)} (+{boost_percent}%)"

def format_inventory_menu_text(active_items, upgrades: dict = None, prestige_upgrades: dict = None, bonus_slots: int = 0):
    items = _normalize_active_items(active_items)
    max_slots = equipped_slots_max(upgrades or {}, prestige_upgrades or {}, bonus_slots)
    equipped = [_format_equipped_item_line(k) for k in items if k in ITEMS]
    equipped_header = f"Экипировано ({len(equipped)}/{max_slots}):"
    equipped_text = equipped_header + ("\n" + "\n".join(equipped) if equipped else " ничего")
    return f"🎒 <b>Твой инвентарь</b>\n{equipped_text}\n\nВыбери раздел:"

INV_PAGE_SIZE = 5
POTION_PAGE_SIZE = 6

def inventory_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧪 Бустеры", callback_data=f"inv_cat:{user_id}:boosters:0")],
        [InlineKeyboardButton(text="📦 Предметы", callback_data=f"inv_cat:{user_id}:items:0")],
        [InlineKeyboardButton(text="⚗️ Зелья", callback_data=f"inv_cat:{user_id}:potions:0")],
    ])

def _paginate(items: list, page: int, page_size: int = INV_PAGE_SIZE):
    """Возвращает (нарезка_страницы, страница_в_границах, всего_страниц)."""
    total_pages = max(1, (len(items) + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    start = page * page_size
    return items[start:start + page_size], page, total_pages

def _pagination_row(callback_prefix: str, user_id: int, page: int, total_pages: int, extra: str = "", counter_callback: str = "noop") -> list:
    """Строка навигации ◀️ n/N ▶️. extra — доп. часть callback_data (например поисковый запрос).
    counter_callback — что происходит по тапу на счётчик "n/N" (по умолчанию ничего, "noop";
    в каталоге бустеров туда подставляется открытие меню каталога)."""
    if total_pages <= 1 and counter_callback == "noop":
        return []
    suffix = f":{extra}" if extra else ""
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"{callback_prefix}:{user_id}:{page - 1}{suffix}", style="primary"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data=counter_callback))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"{callback_prefix}:{user_id}:{page + 1}{suffix}", style="primary"))
    return nav

# ==== Каталог бустеров (фильтр по категориям в меню инвентаря → бустеры) ====
# Хранится в памяти на пользователя (не в БД — это чисто UI-состояние навигации),
# сбрасывается при выходе в главное меню инвентаря или при повторном открытии раздела бустеров.
_booster_catalog_state: dict[int, str] = {}

BOOSTER_CATALOG_CATEGORIES = [
    ("all", "🗂 Все"),
    ("case1", "📦 Кейс 1"),
    ("case2", "📦 Кейс 2"),
    ("case3", "📦 Кейс 3"),
    ("craft1", "🔨 Крафты 1"),
    ("craft2", "🔨 Крафты 2"),
    ("craft3", "🔨 Крафты 3"),
    ("exclusive", "👑 Эксклюзив"),
    ("other", "❓ Другое"),
]
_BOOSTER_CATALOG_LABELS = dict(BOOSTER_CATALOG_CATEGORIES)

# Именные уникальные бустеры для категории «Эксклюзив» каталога — Голда, Керамбит, Мику
# и подобные "личности" (в отличие от UNIQUE_BOOSTER_TIERS — цепочки power/galaxy/god/koshko,
# которые остаются в своих обычных категориях «Крафты» по уровню).
EXCLUSIVE_BOOSTER_ITEMS = {
    "kotyara_amulet", "miku_amulet", "golda", "karambit_gold", "butterfly_legacy",
    "krest_amulet", "fati_amulet", "guitarist_crown", "vilon_amulet", "miku_ring",
    "miku_fan_amulet",
}

def _booster_categories_for(item_key: str) -> set:
    """Возвращает множество категорий каталога, которым принадлежит бустер item_key.
    Один бустер может состоять сразу в нескольких (кейс + крафт и т.п.) — тогда он
    показывается в каждой из них. 'Эксклюзив' (именные уникальные бустеры) исключает 'Крафты'."""
    cats = {"all"}
    if item_key in EXCLUSIVE_BOOSTER_ITEMS:
        cats.add("exclusive")
    else:
        recipe = RECIPES.get(item_key)
        if recipe is not None:
            level = recipe.get("level", 0)
            if level <= 1:
                cats.add("craft1")
            elif level == 2:
                cats.add("craft2")
            else:
                cats.add("craft3")
    for case_num, case_data in CASES.items():
        if item_key in case_data["pool"]:
            cats.add(f"case{case_num}")
    if cats == {"all"}:
        cats.add("other")
    return cats

def get_booster_catalog_category(user_id: int) -> str:
    return _booster_catalog_state.get(user_id, "all")

def set_booster_catalog_category(user_id: int, category: str) -> None:
    _booster_catalog_state[user_id] = category

def reset_booster_catalog_category(user_id: int) -> None:
    _booster_catalog_state.pop(user_id, None)

def filter_boosters_by_catalog(boosters: list, user_id: int) -> list:
    category = get_booster_catalog_category(user_id)
    if category == "all":
        return boosters
    return [(k, q) for k, q in boosters if category in _booster_categories_for(k)]

def booster_catalog_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Меню выбора категории каталога бустеров. Переключение категорий вытесняющее —
    выбор новой категории просто заменяет текущую (хранится ровно одна на пользователя)."""
    current = get_booster_catalog_category(user_id)
    kb_rows = []
    row_buf = []
    for cat_key, label in BOOSTER_CATALOG_CATEGORIES:
        mark = " ✅" if cat_key == current else ""
        row_buf.append(InlineKeyboardButton(
            text=f"{label}{mark}",
            callback_data=f"inv_boost_catalog_set:{user_id}:{cat_key}",
            style="success" if cat_key == current else None,
        ))
        if len(row_buf) == 2:
            kb_rows.append(row_buf)
            row_buf = []
    if row_buf:
        kb_rows.append(row_buf)
    kb_rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"inv_boost_catalog_back:{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)

def boosters_keyboard(rows, active_items, user_id: int, page: int = 0, query: str = None) -> InlineKeyboardMarkup:
    equipped = set(_normalize_active_items(active_items))
    inventory_keys = {k for k, q in rows}
    boosters = [(k, q) for k, q in rows if k not in PASSIVE_ITEMS]
    # Фантомные предметы: экипированы (equipped_items), но их 0 в инвентаре — раньше повисали
    # надетыми навсегда, потому что кнопка снятия строилась только по инвентарю и для них не
    # появлялась вообще. Добавляем такие отдельно (без учёта фильтра/поиска/каталога), чтобы их
    # всегда можно было снять через equip:... callback (toggle_equip снимает по item_key вне
    # зависимости от инвентаря).
    phantom_equipped = [k for k in equipped if k not in inventory_keys and k not in PASSIVE_ITEMS and k in ITEMS]
    if query:
        ql = query.lower()
        boosters = [(k, q) for k, q in boosters if ql in ITEMS[k][1].lower()]
    else:
        boosters = filter_boosters_by_catalog(boosters, user_id)
    page_items, page, total_pages = _paginate(boosters, page)

    kb_rows = []
    if not query and page == 0:
        for item_key in phantom_equipped:
            emoji, name, percent, _ = ITEMS[item_key]
            cb = f"equip:{user_id}:{item_key}:{page}"
            kb_rows.append([InlineKeyboardButton(
                text=f"⚠️ {name} {plain_emoji(emoji)} ({_percent_label(item_key, percent)}) x0 ✅ (снять)",
                callback_data=cb,
                style="danger",
            )])
    for item_key, qty in page_items:
        emoji, name, percent, _ = ITEMS[item_key]
        is_equipped = item_key in equipped
        mark = " ✅" if is_equipped else ""
        cb = f"equip:{user_id}:{item_key}:{page}"
        if query:
            cb += f":{quote(query)}"
        kb_rows.append([InlineKeyboardButton(
            text=f"{name} {plain_emoji(emoji)} ({_percent_label(item_key, percent)}) x{qty}{mark}",
            callback_data=cb,
            style="success" if is_equipped else None,
        )])

    if query:
        nav_row = _pagination_row("inv_boost_search_page", user_id, page, total_pages, extra=quote(query))
    else:
        nav_row = _pagination_row("inv_boost_page", user_id, page, total_pages, counter_callback=f"inv_boost_catalog_open:{user_id}")
    if nav_row:
        kb_rows.append(nav_row)
    kb_rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"inv_menu:{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)

def items_keyboard(user_id: int, rows=None, page: int = 0) -> InlineKeyboardMarkup:
    rows = rows or []
    passive = [(k, q) for k, q in rows if k in PASSIVE_ITEMS]
    _, page, total_pages = _paginate(passive, page)
    kb_rows = []
    nav_row = _pagination_row("inv_items_page", user_id, page, total_pages)
    if nav_row:
        kb_rows.append(nav_row)
    kb_rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"inv_menu:{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)

def format_autosell_text(auto_sell_enabled: bool, auto_sell_items: set, page: int = 0) -> str:
    _, page, total_pages = _paginate(CASE_SELLABLE_ITEMS, page, AUTOSELL_PAGE_SIZE)
    page_suffix = f" (стр. {page + 1}/{total_pages})" if total_pages > 1 else ""
    status = "включена ✅" if auto_sell_enabled else "выключена ❌"
    return (
        f"💰 <b>Авто-продажа дропа из кейсов 1/2/3</b>{page_suffix}\n"
        f"Статус: {status}\n"
        f"Отмечено предметов: {len(auto_sell_items)}\n\n"
        f"Жми на предмет, чтобы включить/выключить его авто-продажу:"
    )

def autosell_keyboard(auto_sell_enabled: bool, auto_sell_items: set, user_id: int, page: int = 0) -> InlineKeyboardMarkup:
    page_items, page, total_pages = _paginate(CASE_SELLABLE_ITEMS, page, AUTOSELL_PAGE_SIZE)
    kb_rows = []
    for item_key in page_items:
        emoji, name, _, _ = ITEMS[item_key]
        is_on = item_key in auto_sell_items
        mark = "✅" if is_on else "❌"
        kb_rows.append([InlineKeyboardButton(
            text=f"{name} {plain_emoji(emoji)} {mark}",
            callback_data=f"autosell_toggle:{user_id}:{item_key}:{page}",
            style="success" if is_on else "danger",
        )])

    nav_row = _pagination_row("autosell_page", user_id, page, total_pages)
    if nav_row:
        kb_rows.append(nav_row)

    switch_text = "🔴 Выключить авто-продажу" if auto_sell_enabled else "🟢 Включить авто-продажу"
    kb_rows.append([InlineKeyboardButton(
        text=switch_text, callback_data=f"autosell_switch:{user_id}:{page}",
        style="danger" if auto_sell_enabled else "success",
    )])
    kb_rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"inv_menu:{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)

def format_boosters_text(rows, max_slots: int = 1, page: int = 0, query: str = None, user_id: int = None):
    boosters = [(k, q) for k, q in rows if k not in PASSIVE_ITEMS]
    if query:
        ql = query.lower()
        boosters = [(k, q) for k, q in boosters if ql in ITEMS[k][1].lower()]
        if not boosters:
            return f"🔍 По запросу «{esc(query)}» бустеров не найдено."
        _, page, total_pages = _paginate(boosters, page)
        page_suffix = f" (стр. {page + 1}/{total_pages})" if total_pages > 1 else ""
        return f"🔍 Поиск «{esc(query)}»{page_suffix}:"
    catalog_suffix = ""
    if user_id is not None:
        category = get_booster_catalog_category(user_id)
        if category != "all":
            boosters = filter_boosters_by_catalog(boosters, user_id)
            catalog_suffix = f" [{_BOOSTER_CATALOG_LABELS[category]}]"
    if not boosters:
        return f"🧪 У тебя нет бустеров в этой категории каталога.{catalog_suffix}" if catalog_suffix else f"🧪 У тебя нет бустеров. Можно носить одновременно {max_slots}."
    _, page, total_pages = _paginate(boosters, page)
    page_suffix = f" (стр. {page + 1}/{total_pages})" if total_pages > 1 else ""
    return f"🧪 Твои бустеры (можно носить одновременно {max_slots}){catalog_suffix}{page_suffix}:"

def format_items_text(rows, page: int = 0):
    passive = [(k, q) for k, q in rows if k in PASSIVE_ITEMS]
    if not passive:
        return "📦 У тебя нет предметов."
    page_items, page, total_pages = _paginate(passive, page)
    page_suffix = f" (стр. {page + 1}/{total_pages})" if total_pages > 1 else ""
    lines = [f"📦 Твои предметы (нельзя экипировать, действуют пассивно){page_suffix}:\n"]
    for item_key, qty in page_items:
        emoji, name, _, _ = ITEMS[item_key]
        lines.append(f"{emoji} {esc(name)} x{qty}")
    return "\n".join(lines)

def format_time_left(seconds: int) -> str:
    seconds = max(0, seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}ч {m}м"
    if m:
        return f"{m}м {s}с"
    return f"{s}с"

# ---- Справочные тексты для «помощь зелье <название>» ----
def find_potion_key_by_name(query: str):
    """Ищет ключ POTIONS по русскому названию. Сначала точное совпадение, иначе — по
    вхождению подстроки (как find_item_by_name). Возвращает (key, None) при однозначном
    совпадении, (None, [варианты]) при неоднозначности, (None, []) если не найдено."""
    q = (query or "").strip().lower()
    if not q:
        return None, []
    for key, cfg in POTIONS.items():
        if cfg["name"].strip().lower() == q:
            return key, None
    matches = [key for key, cfg in POTIONS.items() if q in cfg["name"].lower()]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        matches.sort(key=lambda k: POTIONS[k]["name"])
        return None, matches
    return None, []

def format_help_potion_text(key: str) -> str:
    cfg = POTIONS[key]
    lines = [cfg["desc"] + "."]

    if cfg["effect"] == "no_cd":
        lines.append(f"Действует: {cfg['charges']} следующих использования фермы.")
    else:
        lines.append(f"Длительность эффекта: {format_time_left(cfg['duration_seconds'])} после выпития.")

    lines.append(
        f"Варка: {cfg['brew_cost']} 🪙, занимает {format_time_left(cfg['brew_seconds'])} "
        "— открой «мои зелья» и жми «⚗️ Варить»."
    )
    lines.append("Забрать готовое и выпить — тоже кнопками там же («✅ Забрать» / «▶️ Использовать»).")
    lines.append("Скорость и длительность варки можно улучшить в апгрейдах: «Скорость готовки зелья», «Длительность зелья».")
    return "\n".join(lines)

def format_potions_text(inventory_potions: dict, active_potions: dict, brewing_potion: str, brewing_until: int,
                         upgrades: dict, now: int = None, page: int = 0) -> str:
    now = now or int(time.time())
    _, page, total_pages = _paginate(POTION_ORDER, page, POTION_PAGE_SIZE)
    page_suffix = f" (стр. {page + 1}/{total_pages})" if total_pages > 1 else ""
    lines = [f"⚗️ <b>Зелья</b>{page_suffix}"]

    if brewing_potion and brewing_potion in POTIONS:
        cfg = POTIONS[brewing_potion]
        left = brewing_until - now
        if left > 0:
            lines.append(f"🔥 {cfg['emoji']} {esc(cfg['name'])} — готово через {format_time_left(left)}")
        else:
            lines.append(f"✅ {cfg['emoji']} {esc(cfg['name'])} готово — забери ниже")
    else:
        lines.append("🔥 Котёл свободен")

    for key, val in active_potions.items():
        cfg = POTIONS[key]
        if cfg["effect"] == "no_cd":
            lines.append(f"● {cfg['emoji']} {val} исп.")
        else:
            lines.append(f"● {cfg['emoji']} {format_time_left(val - now)}")

    owned = [f"{POTIONS[k]['emoji']}x{q}" for k, q in inventory_potions.items() if q > 0]
    if owned:
        lines.append("В запасе:")
        lines.extend(f"  {o}" for o in owned)
    else:
        lines.append("В запасе: пусто")

    return "\n".join(lines)

def potions_keyboard(inventory_potions: dict, brewing_potion: str, brewing_until: int, user_id: int,
                      upgrades: dict, now: int = None, prestige_upgrades: dict = None, page: int = 0,
                      active_items=None, inventory_map: dict = None) -> InlineKeyboardMarkup:
    now = now or int(time.time())
    kb_rows = []

    brewing_active = bool(brewing_potion) and brewing_until > now
    brewing_ready = bool(brewing_potion) and brewing_until <= now

    page_order, page, total_pages = _paginate(POTION_ORDER, page, POTION_PAGE_SIZE)

    if brewing_ready:
        cfg = POTIONS[brewing_potion]
        kb_rows.append([InlineKeyboardButton(
            text=f"✅ Забрать {cfg['emoji']} {cfg['name']}",
            callback_data=f"potion_collect:{user_id}",
        )])
    elif not brewing_active:
        for key in page_order:
            cfg = POTIONS[key]
            seconds = brew_seconds_for(key, upgrades, prestige_upgrades, inventory_map=inventory_map)
            extra_part = ""
            for component, amount in (cfg.get("extra_cost") or []):
                if component == "rebirth_points":
                    extra_part += f" + {amount}🉑"
                else:
                    item_emoji = ITEMS[component][0] if component in ITEMS else ""
                    extra_part += f" + {amount}{item_emoji}"
            kb_rows.append([InlineKeyboardButton(
                text=f"⚗️ Варить {cfg['emoji']} {cfg['name']} ({cfg['brew_cost']}🪙{extra_part}, {format_time_left(seconds)})",
                callback_data=f"potion_brew:{user_id}:{key}",
            )])

    for key in page_order:
        qty = inventory_potions.get(key, 0)
        if qty > 0:
            cfg = POTIONS[key]
            kb_rows.append([InlineKeyboardButton(
                text=f"▶️ Использовать {cfg['emoji']} {cfg['name']} (x{qty})",
                callback_data=f"potion_use:{user_id}:{key}",
            )])

    nav_row = _pagination_row("inv_potion_page", user_id, page, total_pages)
    if nav_row:
        kb_rows.append(nav_row)
    kb_rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data=f"inv_cat:{user_id}:potions:{page}")])
    kb_rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"inv_menu:{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)

@dp.message(F.text.lower().in_({"инвентарь", "мой инвентарь"}))
async def inventory(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"

    row = await ensure_user(user_id, username)
    upgrades = parse_upgrades(row[16])
    active_items = parse_equipped(row[18])
    prestige_upgrades = parse_prestige_upgrades(row[28])
    rows = await get_inventory(user_id)

    if not rows:
        await message.reply(TEXTS["inventory_1"])
        return

    inventory_map = {k: q for k, q in rows}
    await safe_reply(message, format_inventory_menu_text(active_items, upgrades, prestige_upgrades, coin_tree_slot_bonus(inventory_map)), reply_markup=inventory_menu_keyboard(user_id))

@dp.message(F.text.lower().in_({"мои предметы", "предметы"}))
async def my_items_tab(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    await ensure_user(user_id, username)
    rows = await get_inventory(user_id)
    await safe_reply(message, format_items_text(rows), reply_markup=items_keyboard(user_id, rows))

@dp.message(F.text.lower().in_({"мои бустеры", "бустеры"}))
async def my_boosters_tab(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    row = await ensure_user(user_id, username)
    upgrades = parse_upgrades(row[16])
    active_items = parse_equipped(row[18])
    prestige_upgrades = parse_prestige_upgrades(row[28])
    rows = await get_inventory(user_id)
    inventory_map = {k: q for k, q in rows}
    max_slots = equipped_slots_max(upgrades, prestige_upgrades, coin_tree_slot_bonus(inventory_map))
    reset_booster_catalog_category(user_id)
    await message.reply(format_boosters_text(rows, max_slots, user_id=user_id), reply_markup=boosters_keyboard(rows, active_items, user_id, 0))

@dp.message(F.text.lower().regexp(r"^бустеры поиск\s+.+$"))
async def my_boosters_search(message: Message):
    query = message.text.strip()[len("бустеры поиск"):].strip()
    if not query:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    row = await ensure_user(user_id, username)
    active_items = parse_equipped(row[18])
    rows = await get_inventory(user_id)
    await message.reply(
        format_boosters_text(rows, page=0, query=query),
        reply_markup=boosters_keyboard(rows, active_items, user_id, 0, query=query),
    )

@dp.message(F.text.lower().in_({"мои зелья", "зелья"}))
async def my_potions_tab(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    row = await ensure_user(user_id, username)
    upgrades = parse_upgrades(row[16])
    stock = parse_potion_stock(row[26])
    active_items = parse_equipped(row[18])
    inventory_map = {k: q for k, q in await get_inventory(user_id)}
    active = active_potions_now(row[23], active_items=active_items, inventory_map=inventory_map)
    brewing_potion, brewing_until = row[24], row[25]
    prestige_upgrades = parse_prestige_upgrades(row[28])
    await message.reply(
        format_potions_text(stock, active, brewing_potion, brewing_until, upgrades),
        reply_markup=potions_keyboard(stock, brewing_potion, brewing_until, user_id, upgrades, prestige_upgrades=prestige_upgrades, active_items=active_items, inventory_map=inventory_map),
    )

@dp.callback_query(F.data.startswith("inv_menu:"))
async def inventory_back_to_menu(callback: CallbackQuery):
    owner_id = int(callback.data.split(":")[1])
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["inventory_back_to_menu_1"], show_alert=True)
        return
    await callback.answer()
    reset_booster_catalog_category(owner_id)

    row = await get_user(owner_id)
    upgrades = parse_upgrades(row[16])
    active_items = parse_equipped(row[18])
    prestige_upgrades = parse_prestige_upgrades(row[28])
    rows = await get_inventory(owner_id)
    inventory_map = {k: q for k, q in rows}
    await safe_edit_text(callback, format_inventory_menu_text(active_items, upgrades, prestige_upgrades, coin_tree_slot_bonus(inventory_map)), reply_markup=inventory_menu_keyboard(owner_id))

@dp.callback_query(F.data.startswith("inv_cat:"))
async def inventory_open_category(callback: CallbackQuery):
    parts = callback.data.split(":")
    owner_id = int(parts[1])
    category = parts[2]
    page = int(parts[3]) if len(parts) > 3 else 0
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["inventory_open_category_1"], show_alert=True)
        return
    await callback.answer()

    if category == "boosters":
        rows = await get_inventory(owner_id)
        row = await get_user(owner_id)
        upgrades = parse_upgrades(row[16])
        active_items = parse_equipped(row[18])
        prestige_upgrades = parse_prestige_upgrades(row[28])
        inventory_map = {k: q for k, q in rows}
        max_slots = equipped_slots_max(upgrades, prestige_upgrades, coin_tree_slot_bonus(inventory_map))
        reset_booster_catalog_category(owner_id)
        await safe_edit_text(callback, format_boosters_text(rows, max_slots, page, user_id=owner_id), reply_markup=boosters_keyboard(rows, active_items, owner_id, page))
    elif category == "potions":
        row = await get_user(owner_id)
        upgrades = parse_upgrades(row[16])
        stock = parse_potion_stock(row[26])
        active_items = parse_equipped(row[18])
        inventory_map = {k: q for k, q in await get_inventory(owner_id)}
        active = active_potions_now(row[23], active_items=active_items, inventory_map=inventory_map)
        brewing_potion, brewing_until = row[24], row[25]
        prestige_upgrades = parse_prestige_upgrades(row[28])
        await safe_edit_text(
            callback,
            format_potions_text(stock, active, brewing_potion, brewing_until, upgrades, page=page),
            reply_markup=potions_keyboard(stock, brewing_potion, brewing_until, owner_id, upgrades, prestige_upgrades=prestige_upgrades, page=page, active_items=active_items, inventory_map=inventory_map),
        )
    else:
        rows = await get_inventory(owner_id)
        await safe_edit_text(callback, format_items_text(rows, page), reply_markup=items_keyboard(owner_id, rows, page))

@dp.callback_query(F.data.startswith("potion_brew:"))
async def potion_brew_start(callback: CallbackQuery):
    parts = callback.data.split(":")
    owner_id = int(parts[1])
    potion_key = parts[2]
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["inventory_open_category_1"], show_alert=True)
        return
    if potion_key not in POTIONS:
        await callback.answer()
        return

    now = int(time.time())
    row = await get_user(owner_id)
    coins = row[5]
    upgrades = parse_upgrades(row[16])
    active_items = parse_equipped(row[18])
    brewing_potion, brewing_until = row[24], row[25]
    prestige_upgrades = parse_prestige_upgrades(row[28])
    inventory_map = {k: q for k, q in await get_inventory(owner_id)}
    rebirth_points = row[14]

    if brewing_potion and brewing_until > now:
        await callback.answer(TEXTS["potion_brew_busy_1"], show_alert=True)
        return

    cfg = POTIONS[potion_key]
    if coins < cfg["brew_cost"]:
        await callback.answer(TEXTS["potion_brew_no_coins_1"].format(v0=cfg["brew_cost"], v1=coins), show_alert=True)
        return

    # extra_cost: список (component, amount) для зелий с составным рецептом (см. POTIONS
    # 'potion_evo_reset'/'potion_rebirth_reset'/'potion_debuff') — component либо ключ предмета
    # инвентаря (тратится через remove_item), либо 'rebirth_points' (тратится через UPDATE).
    extra_costs = cfg.get("extra_cost") or []
    for component, amount in extra_costs:
        if component == "rebirth_points":
            have = rebirth_points
        else:
            have = inventory_map.get(component, 0)
        if have < amount:
            item_name = ITEMS[component][1] if component in ITEMS else UPGRADE_EXTRA_CURRENCY_LABELS.get(component, component)
            await callback.answer(f"Не хватает компонентов: нужно {amount} {item_name}, у тебя {have}.", show_alert=True)
            return

    for component, amount in extra_costs:
        if component == "rebirth_points":
            await db_exec("UPDATE users SET rebirth_points = rebirth_points - ? WHERE user_id = ?", (amount, owner_id))
        else:
            await remove_item(owner_id, component, amount)

    seconds = brew_seconds_for(potion_key, upgrades, prestige_upgrades, inventory_map=inventory_map)
    new_until = now + seconds
    await db_exec(
        "UPDATE users SET coins = coins - ?, brewing_potion = ?, brewing_until = ? WHERE user_id = ?",
        (cfg["brew_cost"], potion_key, new_until, owner_id),
    )

    stock = parse_potion_stock(row[26])
    await safe_edit_text(
        callback,
        format_potions_text(stock, active_potions_now(row[23], now, active_items, inventory_map), potion_key, new_until, upgrades, now),
        reply_markup=potions_keyboard(stock, potion_key, new_until, owner_id, upgrades, now, prestige_upgrades, active_items=active_items, inventory_map=inventory_map),
    )
    await callback.answer(TEXTS["potion_brew_started_1"].format(v0=cfg["emoji"], v1=cfg["name"], v2=format_time_left(seconds)))

@dp.callback_query(F.data.startswith("potion_collect:"))
async def potion_collect(callback: CallbackQuery):
    owner_id = int(callback.data.split(":")[1])
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["inventory_open_category_1"], show_alert=True)
        return

    now = int(time.time())
    row = await get_user(owner_id)
    brewing_potion, brewing_until = row[24], row[25]
    upgrades = parse_upgrades(row[16])
    active_items = parse_equipped(row[18])
    prestige_upgrades = parse_prestige_upgrades(row[28])
    inventory_map = {k: q for k, q in await get_inventory(owner_id)}

    if not brewing_potion:
        await callback.answer(TEXTS["potion_collect_none_1"], show_alert=True)
        return
    if brewing_until > now:
        await callback.answer(TEXTS["potion_collect_not_ready_1"].format(v0=format_time_left(brewing_until - now)), show_alert=True)
        return

    stock = parse_potion_stock(row[26])
    stock[brewing_potion] = stock.get(brewing_potion, 0) + 1
    await db_exec(
        "UPDATE users SET brewing_potion = NULL, brewing_until = 0, potion_stock = ? WHERE user_id = ?",
        (format_potion_stock(stock), owner_id),
    )

    cfg = POTIONS[brewing_potion]
    await safe_edit_text(
        callback,
        format_potions_text(stock, active_potions_now(row[23], now, active_items, inventory_map), None, 0, upgrades, now),
        reply_markup=potions_keyboard(stock, None, 0, owner_id, upgrades, now, prestige_upgrades, active_items=active_items, inventory_map=inventory_map),
    )
    await callback.answer(TEXTS["potion_collect_ok_1"].format(v0=cfg["emoji"], v1=cfg["name"]))

@dp.callback_query(F.data.startswith("potion_use:"))
async def potion_use(callback: CallbackQuery):
    parts = callback.data.split(":")
    owner_id = int(parts[1])
    potion_key = parts[2]
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["inventory_open_category_1"], show_alert=True)
        return
    if potion_key not in POTIONS:
        await callback.answer()
        return

    now = int(time.time())
    row = await get_user(owner_id)
    upgrades = parse_upgrades(row[16])
    active_items = parse_equipped(row[18])
    stock = parse_potion_stock(row[26])
    prestige_upgrades = parse_prestige_upgrades(row[28])
    inventory_map = {k: q for k, q in await get_inventory(owner_id)}

    if stock.get(potion_key, 0) <= 0:
        await callback.answer(TEXTS["potion_use_none_1"], show_alert=True)
        return

    stock[potion_key] -= 1
    if stock[potion_key] <= 0:
        del stock[potion_key]

    cfg = POTIONS[potion_key]

    if cfg.get("instant"):
        # Мгновенные зелья (сброс эво/перерождения, дебафф усложнения) не кладутся в
        # active_potions — эффект применяется сразу и коммитится в БД одним запросом.
        evolution_level = row[3]
        rebirth_count = row[15]
        result_text = ""
        if cfg["effect"] == "reset_evo":
            await db_exec(
                "UPDATE users SET evolution_level = 0, evo_hardness_mult = 1.0, potion_stock = ? WHERE user_id = ?",
                (format_potion_stock(stock), owner_id),
            )
            result_text = f"Эволюция сброшена: {evolution_level} → 0 (усложнение снято полностью)."
        elif cfg["effect"] == "reset_rebirth":
            await db_exec(
                "UPDATE users SET rebirth_count = 0, rebirth_hardness_mult = 1.0, potion_stock = ? WHERE user_id = ?",
                (format_potion_stock(stock), owner_id),
            )
            result_text = f"Перерождения сброшены: {rebirth_count} → 0 (усложнение снято полностью)."
        elif cfg["effect"] == "hardness_debuff":
            current_mults = hardness_kwargs(row)
            before_pct = hardness_percent(evolution_level, rebirth_count, active_items, **current_mults)
            if before_pct <= 0:
                await callback.answer("Усложнения нет — зелье не потрачено.", show_alert=True)
                return
            new_evo_mult = current_mults["evo_mult"] * 0.5
            new_rebirth_mult = current_mults["rebirth_mult"] * 0.5
            await db_exec(
                "UPDATE users SET evo_hardness_mult = ?, rebirth_hardness_mult = ?, potion_stock = ? WHERE user_id = ?",
                (new_evo_mult, new_rebirth_mult, format_potion_stock(stock), owner_id),
            )
            after_pct = hardness_percent(evolution_level, rebirth_count, active_items, new_evo_mult, new_rebirth_mult)
            result_text = (
                f"Усложнение снижено на 50%: +{before_pct}% → +{after_pct}% "
                f"(эволюция {evolution_level} и перерождения {rebirth_count} не тронуты)."
            )

        brewing_potion, brewing_until = row[24], row[25]
        active = active_potions_now(row[23], now, active_items, inventory_map)
        await safe_edit_text(
            callback,
            format_potions_text(stock, active, brewing_potion, brewing_until, upgrades, now),
            reply_markup=potions_keyboard(stock, brewing_potion, brewing_until, owner_id, upgrades, now, prestige_upgrades, active_items=active_items, inventory_map=inventory_map),
        )
        await callback.answer(f"{cfg['emoji']} {cfg['name']} использовано! {result_text}", show_alert=True)
        return

    active = active_potions_now(row[23], now, active_items, inventory_map)
    if cfg["effect"] == "no_cd":
        active[potion_key] = cfg["charges"]
    else:
        duration = potion_duration_seconds(potion_key, upgrades)
        active[potion_key] = now + duration

    await db_exec(
        "UPDATE users SET potion_stock = ?, active_potions = ? WHERE user_id = ?",
        (format_potion_stock(stock), format_potions(active), owner_id),
    )

    brewing_potion, brewing_until = row[24], row[25]
    await safe_edit_text(
        callback,
        format_potions_text(stock, active, brewing_potion, brewing_until, upgrades, now),
        reply_markup=potions_keyboard(stock, brewing_potion, brewing_until, owner_id, upgrades, now, prestige_upgrades, active_items=active_items, inventory_map=inventory_map),
    )
    if cfg["effect"] == "no_cd":
        await callback.answer(TEXTS["potion_use_ok_charges_1"].format(v0=cfg["emoji"], v1=cfg["name"], v2=cfg["charges"]))
    else:
        await callback.answer(TEXTS["potion_use_ok_1"].format(v0=cfg["emoji"], v1=cfg["name"], v2=format_time_left(potion_duration_seconds(potion_key, upgrades))))

@dp.callback_query(F.data.startswith("inv_boost_page:"))
async def inventory_boosters_page(callback: CallbackQuery):
    _, owner_str, page_str = callback.data.split(":")
    owner_id = int(owner_str)
    page = int(page_str)
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["inventory_open_category_1"], show_alert=True)
        return
    await callback.answer()

    row = await get_user(owner_id)
    upgrades = parse_upgrades(row[16])
    active_items = parse_equipped(row[18])
    prestige_upgrades = parse_prestige_upgrades(row[28])
    rows = await get_inventory(owner_id)
    inventory_map = {k: q for k, q in rows}
    max_slots = equipped_slots_max(upgrades, prestige_upgrades, coin_tree_slot_bonus(inventory_map))
    await safe_edit_text(callback, format_boosters_text(rows, max_slots, page, user_id=owner_id), reply_markup=boosters_keyboard(rows, active_items, owner_id, page))

@dp.callback_query(F.data.startswith("inv_boost_catalog_open:"))
async def inventory_boosters_catalog_open(callback: CallbackQuery):
    """Открывает меню каталога — тап по счётчику страниц 'n/N' в разделе бустеров."""
    owner_id = int(callback.data.split(":")[1])
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["inventory_open_category_1"], show_alert=True)
        return
    await callback.answer()
    category = get_booster_catalog_category(owner_id)
    label = _BOOSTER_CATALOG_LABELS[category]
    await safe_edit_text(
        callback,
        f"🗂 <b>Каталог бустеров</b>\nТекущая категория: {label}\n\nВыбери категорию для фильтрации списка бустеров:",
        reply_markup=booster_catalog_keyboard(owner_id),
    )

@dp.callback_query(F.data.startswith("inv_boost_catalog_set:"))
async def inventory_boosters_catalog_set(callback: CallbackQuery):
    """Выбор категории каталога — вытесняющее переключение: новая категория заменяет
    предыдущую (хранится ровно одна активная категория на пользователя)."""
    parts = callback.data.split(":")
    owner_id = int(parts[1])
    category = parts[2]
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["inventory_open_category_1"], show_alert=True)
        return
    if category not in _BOOSTER_CATALOG_LABELS:
        await callback.answer()
        return
    set_booster_catalog_category(owner_id, category)
    await callback.answer(f"Категория: {_BOOSTER_CATALOG_LABELS[category]}")
    await safe_edit_text(
        callback,
        f"🗂 <b>Каталог бустеров</b>\nТекущая категория: {_BOOSTER_CATALOG_LABELS[category]}\n\nВыбери категорию для фильтрации списка бустеров:",
        reply_markup=booster_catalog_keyboard(owner_id),
    )

@dp.callback_query(F.data.startswith("inv_boost_catalog_back:"))
async def inventory_boosters_catalog_back(callback: CallbackQuery):
    """Возврат из меню каталога к списку бустеров, с уже применённым фильтром категории."""
    owner_id = int(callback.data.split(":")[1])
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["inventory_open_category_1"], show_alert=True)
        return
    await callback.answer()

    row = await get_user(owner_id)
    upgrades = parse_upgrades(row[16])
    active_items = parse_equipped(row[18])
    prestige_upgrades = parse_prestige_upgrades(row[28])
    rows = await get_inventory(owner_id)
    inventory_map = {k: q for k, q in rows}
    max_slots = equipped_slots_max(upgrades, prestige_upgrades, coin_tree_slot_bonus(inventory_map))
    await safe_edit_text(callback, format_boosters_text(rows, max_slots, 0, user_id=owner_id), reply_markup=boosters_keyboard(rows, active_items, owner_id, 0))

@dp.callback_query(F.data.startswith("inv_boost_search_page:"))
async def inventory_boosters_search_page(callback: CallbackQuery):
    parts = callback.data.split(":")
    owner_id = int(parts[1])
    page = int(parts[2])
    query = unquote(parts[3]) if len(parts) > 3 else ""
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["inventory_open_category_1"], show_alert=True)
        return
    await callback.answer()

    row = await get_user(owner_id)
    active_items = parse_equipped(row[18])
    rows = await get_inventory(owner_id)
    await safe_edit_text(callback, 
        format_boosters_text(rows, page=page, query=query),
        reply_markup=boosters_keyboard(rows, active_items, owner_id, page, query=query),
    )

@dp.callback_query(F.data.startswith("inv_items_page:"))
async def inventory_items_page(callback: CallbackQuery):
    _, owner_str, page_str = callback.data.split(":")
    owner_id = int(owner_str)
    page = int(page_str)
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["inventory_open_category_1"], show_alert=True)
        return
    await callback.answer()

    rows = await get_inventory(owner_id)
    await safe_edit_text(callback, format_items_text(rows, page), reply_markup=items_keyboard(owner_id, rows, page))

@dp.callback_query(F.data.startswith("inv_potion_page:"))
async def inventory_potions_page(callback: CallbackQuery):
    _, owner_str, page_str = callback.data.split(":")
    owner_id = int(owner_str)
    page = int(page_str)
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["inventory_open_category_1"], show_alert=True)
        return
    await callback.answer()

    row = await get_user(owner_id)
    upgrades = parse_upgrades(row[16])
    active_items = parse_equipped(row[18])
    stock = parse_potion_stock(row[26])
    inventory_map = {k: q for k, q in await get_inventory(owner_id)}
    active = active_potions_now(row[23], active_items=active_items, inventory_map=inventory_map)
    brewing_potion, brewing_until = row[24], row[25]
    prestige_upgrades = parse_prestige_upgrades(row[28])
    await safe_edit_text(
        callback,
        format_potions_text(stock, active, brewing_potion, brewing_until, upgrades, page=page),
        reply_markup=potions_keyboard(stock, brewing_potion, brewing_until, owner_id, upgrades, prestige_upgrades=prestige_upgrades, page=page, active_items=active_items, inventory_map=inventory_map),
    )

@dp.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery):
    await callback.answer()

@dp.callback_query(F.data.startswith("equip:"))
async def toggle_equip(callback: CallbackQuery):
    parts = callback.data.split(":")
    owner_id = int(parts[1])
    item_key = parts[2]
    page = int(parts[3]) if len(parts) > 3 else 0
    query = unquote(parts[4]) if len(parts) > 4 else None
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["toggle_equip_1"], show_alert=True)
        return
    if item_key in PASSIVE_ITEMS:
        await callback.answer(TEXTS["toggle_equip_2"], show_alert=True)
        return

    row = await get_user(owner_id)
    upgrades = parse_upgrades(row[16])
    prestige_upgrades = parse_prestige_upgrades(row[28])
    rows = await get_inventory(owner_id)
    inventory_map = {k: q for k, q in rows}
    max_slots = equipped_slots_max(upgrades, prestige_upgrades, coin_tree_slot_bonus(inventory_map))

    before = parse_equipped(row[18])

    if item_key in before:
        # Уже надет -> снимаем (как выключение бейджа).
        new_equipped = unequip_item(row[18], item_key)
        await db_exec("UPDATE users SET equipped_items = ? WHERE user_id = ?", (format_equipped(new_equipped), owner_id))
        await safe_edit_text(callback,
            format_boosters_text(rows, max_slots, page, query=query, user_id=owner_id),
            reply_markup=boosters_keyboard(rows, new_equipped, owner_id, page, query=query),
        )
        await callback.answer(TEXTS["toggle_equip_4"])
        return

    if len(before) >= max_slots:
        # Лимит слотов занят -> блокируем, как с бейджами ("сначала выключи один").
        await callback.answer(TEXTS["toggle_equip_5"].format(v0=max_slots), show_alert=True)
        return

    new_equipped = equip_item(row[18], item_key, max_slots)
    await db_exec("UPDATE users SET equipped_items = ? WHERE user_id = ?", (format_equipped(new_equipped), owner_id))

    await safe_edit_text(callback, 
        format_boosters_text(rows, max_slots, page, query=query, user_id=owner_id),
        reply_markup=boosters_keyboard(rows, new_equipped, owner_id, page, query=query),
    )
    await callback.answer(TEXTS["toggle_equip_4"])

CRAFT_RE = re.compile(r"^крафт(?:ы)?(?:\s+(.+))?$", re.IGNORECASE)

def craft_level_of(upgrades: dict) -> int:
    return upgrade_level(upgrades, "crafts")

def recipe_is_discovered(recipe: dict, inventory_map: dict) -> bool:
    """Как в Minecraft: рецепт «открыт» (виден в списке), если у игрока есть хотя бы
    1 шт. любого предметного ингредиента. Валюта (монеты/очки/💠/🉑) на открытие не влияет —
    только на возможность реально скрафтить (см. recipe_missing_ingredients)."""
    ingredients = recipe.get("ingredients", {})
    if not ingredients and not recipe.get("needs_all_amulets"):
        return True
    for ing_key in ingredients:
        if inventory_map.get(ing_key, 0) > 0:
            return True
    if recipe.get("needs_all_amulets"):
        if any(inventory_map.get(ing_key, 0) > 0 for ing_key in ALL_PLAYER_AMULETS):
            return True
    return False

def available_recipes(craft_level: int, inventory_map: dict, query: str = None) -> list:
    """Рецепты, доступные по уровню крафта игрока И уже «открытые» (есть хотя бы 1 нужный
    предмет в инвентаре — валюта не считается), отфильтрованные по подстроке в названии результата."""
    result = []
    for key, recipe in RECIPES.items():
        if recipe["level"] > craft_level:
            continue
        if not recipe_is_discovered(recipe, inventory_map):
            continue
        if query and query.lower() not in ITEMS[key][1].lower():
            continue
        result.append(key)
    return result

def crafts_keyboard(recipe_keys: list, user_id: int, page: int = 0, query: str = "") -> InlineKeyboardMarkup:
    page_items, page, total_pages = _paginate(recipe_keys, page)

    rows = []
    for key in page_items:
        emoji, name, _, _ = ITEMS[key]
        rows.append([InlineKeyboardButton(
            text=f"{plain_emoji(emoji)} Скрафтить {name}",
            callback_data=f"craft:{user_id}:{key}",
        )])

    nav_row = _pagination_row("craft_page", user_id, page, total_pages, extra=query)
    if nav_row:
        rows.append(nav_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)

def format_crafts_text(recipe_keys: list, craft_level: int, query: str, page: int = 0) -> str:
    if not recipe_keys:
        if query:
            return f"🔨 Нет доступных рецептов по запросу «{esc(query)}» (либо не хватает уровня крафта, либо нет ни одного нужного ингредиента в инвентаре)."
        return (
            f"🔨 Нет открытых рецептов ({craft_level}/{CRAFT_MAX_LEVEL} ур. крафта).\n"
            f"Рецепт появляется в списке, когда у тебя есть хотя бы 1 нужный предмет — "
            f"добывай ингредиенты в кейсах и качай апгрейд «Крафты» в прокачке!"
        )

    page_keys, page, total_pages = _paginate(recipe_keys, page)
    page_suffix = f" — стр. {page + 1}/{total_pages}" if total_pages > 1 else ""
    lines = [f"🔨 <b>Доступные рецепты</b> (уровень крафта {craft_level}/{CRAFT_MAX_LEVEL}){page_suffix}:\n"]
    for key in page_keys:
        emoji, name, _, _ = ITEMS[key]
        lines.append(f"{emoji} <b>{esc(name)}</b> = {esc(format_recipe_requirements(RECIPES[key]))}")
    return "\n".join(lines)

@dp.message(F.text.regexp(r"(?i)^крафт(ы)?(\s+.+)?$"))
async def crafts_command(message: Message):
    match = CRAFT_RE.match(message.text.strip())
    if not match:
        return
    query = (match.group(1) or "").strip() or None

    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    row = await ensure_user(user_id, username)
    upgrades = parse_upgrades(row[16])
    craft_level = craft_level_of(upgrades)
    inv_rows = await get_inventory(user_id)
    inventory_map = {k: q for k, q in inv_rows}

    recipe_keys = available_recipes(craft_level, inventory_map, query)
    await message.reply(
        format_crafts_text(recipe_keys, craft_level, query or "", 0),
        reply_markup=crafts_keyboard(recipe_keys, user_id, 0, query or "") if recipe_keys else None,
    )

@dp.callback_query(F.data.startswith("craft_page:"))
async def crafts_page_nav(callback: CallbackQuery):
    parts = callback.data.split(":", 3)
    owner_id = int(parts[1])
    page = int(parts[2])
    query = parts[3] if len(parts) > 3 and parts[3] else None
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["craft_do_1"], show_alert=True)
        return
    await callback.answer()

    row = await get_user(owner_id)
    upgrades = parse_upgrades(row[16])
    craft_level = craft_level_of(upgrades)
    inv_rows = await get_inventory(owner_id)
    inventory_map = {k: q for k, q in inv_rows}
    recipe_keys = available_recipes(craft_level, inventory_map, query)

    await safe_edit_text(callback, 
        format_crafts_text(recipe_keys, craft_level, query or "", page),
        reply_markup=crafts_keyboard(recipe_keys, owner_id, page, query or "") if recipe_keys else None,
    )

@dp.callback_query(F.data.startswith("craft:"))
async def craft_do(callback: CallbackQuery):
    _, owner_str, recipe_key = callback.data.split(":")
    owner_id = int(owner_str)
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["craft_do_1"], show_alert=True)
        return
    if recipe_key not in RECIPES:
        await callback.answer(TEXTS["craft_do_2"], show_alert=True)
        return

    row = await get_user(owner_id)
    upgrades = parse_upgrades(row[16])
    prestige_upgrades = parse_prestige_upgrades(row[28])
    craft_level = craft_level_of(upgrades)
    recipe = RECIPES[recipe_key]

    if recipe["level"] > craft_level:
        await callback.answer(TEXTS["craft_do_3"].format(v0=recipe['level'], v1=craft_level), show_alert=True)
        return

    coins, score = row[5], row[2]
    craft_points = row[32]
    rebirth_points = row[14]
    inv_rows = await get_inventory(owner_id)
    inventory_map = {k: q for k, q in inv_rows}

    missing = recipe_missing_ingredients(inventory_map, coins, score, recipe, prestige_upgrades, craft_points, rebirth_points)
    if missing:
        await callback.answer("Не хватает: " + "; ".join(missing), show_alert=True)
        return

    for ing_key, qty in recipe.get("ingredients", {}).items():
        await remove_item(owner_id, ing_key, qty)
    for ing_key, qty in recipe.get("refund_ingredients", {}).items():
        await add_item(owner_id, ing_key, qty)
    if recipe.get("needs_all_amulets"):
        for ing_key in ALL_PLAYER_AMULETS:
            await remove_item(owner_id, ing_key, 1)
    if recipe.get("coin_cost"):
        discounted_cost = craft_coin_cost_with_discount(recipe["coin_cost"], prestige_upgrades)
        await db_exec("UPDATE users SET coins = coins - ? WHERE user_id = ?", (discounted_cost, owner_id))
    if recipe.get("score_cost"):
        await db_exec("UPDATE users SET score = score - ? WHERE user_id = ?", (recipe["score_cost"], owner_id))
    if recipe.get("craft_points_cost"):
        await db_exec(
            "UPDATE users SET craft_points = craft_points - ? WHERE user_id = ?",
            (recipe["craft_points_cost"], owner_id),
        )
    if recipe.get("rebirth_cost"):
        await db_exec(
            "UPDATE users SET rebirth_points = rebirth_points - ? WHERE user_id = ?",
            (recipe["rebirth_cost"], owner_id),
        )

    await add_item(owner_id, recipe_key, 1)
    await db_exec("UPDATE users SET crafts_done = crafts_done + 1 WHERE user_id = ?", (owner_id,))

    emoji, name, _, _ = ITEMS[recipe_key]
    result_text = f"✅ Скрафтил {emoji} {name}!"

    await callback.message.reply(result_text)
    await callback.answer(TEXTS["craft_do_4"])

def case_offer_keyboard(case_num: int, user_id: int, price: int) -> InlineKeyboardMarkup:
    case = CASES[case_num]
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"🎁 Открыть {case['name']} ({price} 🪙)", callback_data=f"buy_case:{case_num}:{user_id}")
    ]])

def format_case_inspect_text(case_num: int, price: int, base_price: int) -> str:
    case = CASES[case_num]
    discount_line = f" (скидка, было {base_price} 🪙)" if price != base_price else ""
    lines = [f"📦 <b>{esc(case['name'])}</b>", f"Цена: {price} 🪙{discount_line}", "", "Возможный дроп:"]
    for _k, emoji, name, percent, chance in case_drop_table(case_num):
        boost_part = f" (+{percent}%)" if percent else ""
        lines.append(f"{emoji} {esc(name)}{boost_part} — {chance}%")
    return "\n".join(lines)

async def send_case_inspect(message: Message, case_num: int):
    """Меню осмотра кейса: список дропа с процентами + кнопка открытия."""
    case = CASES.get(case_num)
    if not case:
        await message.reply(TEXTS["send_case_inspect_1"])
        return
    row = await ensure_user(message.from_user.id, message.from_user.username or message.from_user.first_name or "Без имени")
    upgrades = parse_upgrades(row[16])
    price = case_price_with_discount(case["price"], upgrades)
    await message.reply(
        format_case_inspect_text(case_num, price, case["price"]),
        reply_markup=case_offer_keyboard(case_num, message.from_user.id, price),
    )

async def open_case_instant(message: Message, case_num: int):
    """'открыть кейс N' — мгновенная рулетка, минуя меню осмотра."""
    case = CASES.get(case_num)
    if not case:
        await message.reply(TEXTS["open_case_instant_1"])
        return

    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    row = await ensure_user(user_id, username)
    coins = row[5]
    upgrades = parse_upgrades(row[16])
    auto_sell_enabled = bool(row[30])
    auto_sell_items = parse_auto_sell_items(row[31])
    price = case_price_with_discount(case["price"], upgrades)

    if coins < price:
        await message.reply(TEXTS["open_case_instant_2"].format(v0=price, v1=coins))
        return

    item_key = roll_case_item(case_num)
    emoji, name, percent, _ = ITEMS[item_key]

    await db_exec(
        "UPDATE users SET coins = coins - ?, cases_opened = cases_opened + 1 WHERE user_id = ?",
        (price, user_id),
    )
    _sold_for, sold_text = await apply_case_reward(user_id, item_key, upgrades, auto_sell_enabled, auto_sell_items)
    new_coins = coins - price + _sold_for

    collector_text = ""
    collector_chance = case_collector_chance(upgrades)
    if collector_chance and random.random() < collector_chance:
        bonus_item_key = roll_case_item(case_num)
        bonus_emoji, bonus_name, bonus_percent, _ = ITEMS[bonus_item_key]
        bonus_sold_for, bonus_sold_text = await apply_case_reward(user_id, bonus_item_key, upgrades, auto_sell_enabled, auto_sell_items)
        new_coins += bonus_sold_for
        collector_text = f"\n✨ Коллекционер кейсов: доп. предмет {bonus_emoji} {esc(bonus_name)} (+{bonus_percent}%)!{bonus_sold_text}"

    await message.reply(TEXTS["open_case_instant_3"].format(v0=emoji, v1=esc(name), v2=percent, v3=new_coins) + sold_text + collector_text)

@dp.message(F.text.lower() == "кейс")
async def case_default(message: Message):
    await send_case_inspect(message, 1)

@dp.message(F.text.lower().regexp(r"^кейс \d+$"))
async def case_numbered(message: Message):
    match = CASE_NUM_RE.match(message.text.strip().lower())
    await send_case_inspect(message, int(match.group(1)))

@dp.message(F.text.lower().regexp(r"^(осмотреть кейс|осмотр кейс)\s+(\d+)$"))
async def case_inspect_command(message: Message):
    match = re.match(r"^(?:осмотреть кейс|осмотр кейс)\s+(\d+)$", message.text.strip().lower())
    await send_case_inspect(message, int(match.group(1)))

@dp.message(F.text.lower().regexp(r"^открыть кейс\s+(\d+)$"))
async def case_open_command(message: Message):
    match = re.match(r"^открыть кейс\s+(\d+)$", message.text.strip().lower())
    await open_case_instant(message, int(match.group(1)))

@dp.message(F.text.lower() == "кейсы")
async def case_list(message: Message):
    user_id = message.from_user.id
    row = await ensure_user(user_id, message.from_user.username or message.from_user.first_name or "Без имени")
    upgrades = parse_upgrades(row[16])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{case['name']} ({case_price_with_discount(case['price'], upgrades)} 🪙)",
            callback_data=f"inspect_case:{num}:{user_id}",
        )]
        for num, case in CASES.items()
    ])
    await message.reply(TEXTS["case_list_1"], reply_markup=kb)

@dp.callback_query(F.data.startswith("inspect_case:"))
async def inspect_case_callback(callback: CallbackQuery):
    _, case_num_str, owner_str = callback.data.split(":")
    case_num = int(case_num_str)
    owner_id = int(owner_str)
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["inspect_case_callback_1"], show_alert=True)
        return
    await callback.answer()

    row = await get_user(owner_id)
    upgrades = parse_upgrades(row[16])
    case = CASES[case_num]
    price = case_price_with_discount(case["price"], upgrades)

    await safe_edit_text(callback, 
        format_case_inspect_text(case_num, price, case["price"]),
        reply_markup=case_offer_keyboard(case_num, owner_id, price),
    )

@dp.callback_query(F.data.startswith("buy_case:"))
async def buy_case(callback: CallbackQuery):
    _, case_num_str, owner_str = callback.data.split(":")
    case_num = int(case_num_str)
    owner_id = int(owner_str)
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["buy_case_1"], show_alert=True)
        return

    case = CASES[case_num]

    row = await get_user(owner_id)
    coins = row[5]
    upgrades = parse_upgrades(row[16])
    auto_sell_enabled = bool(row[30])
    auto_sell_items = parse_auto_sell_items(row[31])
    price = case_price_with_discount(case["price"], upgrades)

    if coins < price:
        await callback.answer(TEXTS["buy_case_2"].format(v0=price), show_alert=True)
        return

    item_key = roll_case_item(case_num)
    emoji, name, percent, _ = ITEMS[item_key]

    await db_exec(
        "UPDATE users SET coins = coins - ?, cases_opened = cases_opened + 1 WHERE user_id = ?",
        (price, owner_id),
    )
    sold_for, sold_text = await apply_case_reward(owner_id, item_key, upgrades, auto_sell_enabled, auto_sell_items)
    new_coins = coins - price + sold_for

    # Коллекционер кейсов (ветка 'case_collector', категория 5) — шанс получить ДОП. предмет
    # из того же кейса, без затраты второго кейса. Кейс всё равно тратится один.
    collector_text = ""
    collector_chance = case_collector_chance(upgrades)
    if collector_chance and random.random() < collector_chance:
        bonus_item_key = roll_case_item(case_num)
        bonus_emoji, bonus_name, bonus_percent, _ = ITEMS[bonus_item_key]
        bonus_sold_for, bonus_sold_text = await apply_case_reward(owner_id, bonus_item_key, upgrades, auto_sell_enabled, auto_sell_items)
        new_coins += bonus_sold_for
        collector_text = f"\n✨ Коллекционер кейсов: доп. предмет {bonus_emoji} {esc(bonus_name)} (+{bonus_percent}%)!{bonus_sold_text}"

    await safe_edit_text(callback, 
        f"🎉 Выпало: {emoji} {esc(name)} (+{percent}%)!{sold_text}{collector_text}\nОстаток монет: {new_coins} 🪙",
        reply_markup=case_offer_keyboard(case_num, owner_id, price),
    )
    await callback.answer(TEXTS["buy_case_3"])

async def apply_coin_tree_save(user_id: int, inventory_map: dict, event: str, score: int, evolution_level: int) -> dict:
    """Гарантированный сейв % очков/эво при эволюции или перерождении от 🟢/🟣/⚪️ монет дерева.
    event: "evolution" или "rebirth". Работает пассивно (монеты лежат в инвентаре, экипировать
    не нужно). Если у игрока есть несколько подходящих монет — действует только САМАЯ СИЛЬНАЯ:
    ⚪️ Монета Пробуждения (работает и на эво, и на перерождение) > специфичная монета события
    (🟢 только эво, 🟣 только перерождение). При срабатывании 1% шанс +3 очка престижа и
    0.01% шанс на бейдж "Инвестировал в #####" — только у ⚪️ Монеты Пробуждения.
    Возвращает {"kept_score": int, "kept_evolution": int, "extra_text": str}."""
    kept_score = 0
    kept_evolution = 0
    extra_text = ""
    pct = 0.0
    coin_label = ""

    if inventory_map.get("awakening_coin", 0) > 0:
        pct = AWAKENING_COIN_SAVE_PCT
        coin_label = f"{PREMIUM_AWAKENING_COIN} Монета Пробуждения"
    elif event == "evolution" and inventory_map.get("evolution_coin", 0) > 0:
        pct = EVOLUTION_COIN_SAVE_PCT
        coin_label = f"{PREMIUM_EVOLUTION_COIN} Монета Эволюции"
    elif event == "rebirth" and inventory_map.get("rebirth_coin", 0) > 0:
        pct = REBIRTH_COIN_SAVE_PCT
        coin_label = f"{PREMIUM_REBIRTH_COIN} Монета Перерождения"

    if pct > 0:
        kept_score = round(score * pct)
        if event == "rebirth" or inventory_map.get("awakening_coin", 0) > 0:
            kept_evolution = round(evolution_level * pct)
        extra_text += f"\n{coin_label}: сохранено {round(pct * 100)}% ({kept_score} очков ноги{f' и {kept_evolution} ур. эво' if kept_evolution else ''})!"

        if inventory_map.get("awakening_coin", 0) > 0:
            if random.random() < AWAKENING_COIN_PRESTIGE_CHANCE:
                await db_exec(
                    "UPDATE users SET prestige_points = prestige_points + ? WHERE user_id = ?",
                    (AWAKENING_COIN_PRESTIGE_AMOUNT, user_id),
                )
                extra_text += f"\n{PREMIUM_AWAKENING_COIN} Монета Пробуждения: +{AWAKENING_COIN_PRESTIGE_AMOUNT}🔮 очка престижа!"
            if random.random() < AWAKENING_COIN_BADGE_CHANCE:
                await add_promo_badge(user_id, "investor")
                badge_emoji, badge_name = PROMO_BADGES["investor"]
                extra_text += f"\n{PREMIUM_AWAKENING_COIN} Монета Пробуждения: выпал бейдж {badge_emoji} «{badge_name}»!"

    return {"kept_score": kept_score, "kept_evolution": kept_evolution, "extra_text": extra_text}

async def evo_level_unlock_text(user_id: int, evolution_level: int) -> str:
    """Общая точка разблокировок за уровень эволюции — вызывается и из авто-эво (каскадно,
    на каждом промежуточном уровне), и из ручной «эволюция» (один уровень за раз), чтобы
    список разблокировок не расходился между ними."""
    if evolution_level == 1:
        return f"\nОткрыта фарма {FARM_EVOLVED[0]}-{FARM_EVOLVED[1]} очков и эмодзи 🦿 ({MEK_POINT} очков, до {MEK_LIMIT} раз в соо)!"
    if evolution_level == 2:
        await add_item(user_id, "star")
        return "\nПолучена ⭐️ Звезда перерождения — экипируй в инвентарь!"

    text = ""
    if evolution_level == EVO_UNLOCK_REBIRTH_SPARK_LEVEL:
        await add_item(user_id, "rebirth_spark")
        text += f"\nПолучена {ITEMS['rebirth_spark'][0]} Искра перерождения — сырьё для новых крафтов!"
    if evolution_level in EVO_LEG_UNLOCK_BY_LEVEL:
        emoji = EVO_LEG_UNLOCK_BY_LEVEL[evolution_level]
        tier = EVO_LEG_TIERS[emoji]
        text += f"\nОткрыты новые ноги {emoji} (+{tier['bonus_pct']}% к добыче робоног, лимит {tier['limit']} за сообщение)!"
    if evolution_level == EVO_UNLOCK_MEK2_LEVEL:
        text += f"\nДобыча команды «ферма» увеличена на +{EVO_FARM_BONUS_LVL10} очков!"
    if evolution_level == EVO_UNLOCK_NECKLACE_CRAFTS_LEVEL:
        text += "\nОткрыты новые крафты: Ожерелье из звёзд, Ожерелье пылающей звезды, Карманная звезда!"
    if evolution_level == EVO_FLOW_UNLOCK_LEVEL:
        text += f"\nОткрыт пассивный буст «Поток эволюции» — {round(EVO_FLOW_EXTRA_CHANCE * 100)}% шанс на доп. эволюцию сверху при каждой эволюции!"
    return text

async def try_auto_evolve(user_id: int, score: int, evolution_level: int, rebirth_count: int, active_items=None,
                          evo_mult: float = 1.0, rebirth_mult: float = 1.0) -> tuple[int, int, str]:
    """VIP авто-эво: каскадно эволюционирует, пока очков хватает на след. эволюцию —
    например, если фарм разом принёс очков на 2 эволюции вперёд, сработают обе.
    Возвращает (итоговый evolution_level, итоговый score, текст для добавления к ответу)."""
    evolutions_done = 0
    unlock_text = ""
    score_before_last_reset = score
    while True:
        required = level_threshold(EVO_REQUIRED_BASE_LEVEL + evolution_level, evolution_level, rebirth_count, active_items, evo_mult, rebirth_mult)
        if score < required:
            break
        score_before_last_reset = score
        score = 0
        evolution_level += 1
        evolutions_done += 1
        unlock_text += await evo_level_unlock_text(user_id, evolution_level)
        if evolution_level >= EVO_FLOW_UNLOCK_LEVEL and random.random() < EVO_FLOW_EXTRA_CHANCE:
            evolution_level += 1
            evolutions_done += 1
            unlock_text += "\n🌊 Поток эволюции: доп. эволюция сверху!"
            unlock_text += await evo_level_unlock_text(user_id, evolution_level)

    if evolutions_done == 0:
        return evolution_level, score, ""

    inv_rows = await get_inventory(user_id)
    inventory_map = {k: q for k, q in inv_rows}
    coin_save_text = ""
    if inventory_map.get("evolution_coin", 0) > 0 or inventory_map.get("awakening_coin", 0) > 0:
        evolution_level += 1
        coin_save_text += "\n🟢 Дерево монет: доп. эволюция сверху!"
    save_result = await apply_coin_tree_save(user_id, inventory_map, "evolution", score_before_last_reset, evolution_level)
    score = save_result["kept_score"]
    coin_save_text += save_result["extra_text"]

    await db_exec("UPDATE users SET score = ?, evolution_level = ? WHERE user_id = ?", (score, evolution_level, user_id))
    times = f" ×{evolutions_done}" if evolutions_done > 1 else ""
    text = f"\n\n⚙️💎 Авто-эволюция{times}! Теперь {evolution_level} уровень эволюции.{unlock_text}{coin_save_text}"
    return evolution_level, score, text

@dp.message(F.text.lower() == "эволюция")
async def evolve(message: Message):
    if not await require_subscription(message):
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"

    row = await ensure_user(user_id, username)
    score, evolution_level = row[2], row[3]
    rebirth_count = row[15]
    active_items = parse_equipped(row[18])

    required = level_threshold(EVO_REQUIRED_BASE_LEVEL + evolution_level, evolution_level, rebirth_count, active_items, **hardness_kwargs(row))
    if score < required:
        await message.reply(TEXTS["evolve_1"].format(v0=required))
        return

    new_evolution = evolution_level + 1

    ice_text = ""
    kept_score = 0
    if "ice_shard" in set(_normalize_active_items(active_items)) and random.random() < ICE_SHARD_SAVE_CHANCE:
        kept_score = score
        ice_text = "\n🧊 Ледяной осколок: очки ноги сохранены!"

    coin_save_text = ""
    if not kept_score:
        inv_rows = await get_inventory(user_id)
        inventory_map = {k: q for k, q in inv_rows}
        save_result = await apply_coin_tree_save(user_id, inventory_map, "evolution", score, evolution_level)
        kept_score = save_result["kept_score"]
        coin_save_text = save_result["extra_text"]
        if inventory_map.get("evolution_coin", 0) > 0 or inventory_map.get("awakening_coin", 0) > 0:
            new_evolution += 1
            coin_save_text += "\n🟢 Дерево монет: доп. эволюция сверху!"

    await db_exec("UPDATE users SET score = ?, evolution_level = ? WHERE user_id = ?", (kept_score, new_evolution, user_id))

    unlock_text = await evo_level_unlock_text(user_id, new_evolution)

    await message.reply(
        TEXTS["evolve_2"].format(v0=new_evolution, v1=round(EVO_HARDNESS_RATE * new_evolution * hardness_kwargs(row)["evo_mult"] * 100), v2=unlock_text + ice_text + coin_save_text)
    )

@dp.message(F.text.lower() == "!ивент ноги")
async def toggle_event(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)

    active = await is_event_active()
    new_value = "0" if active else "1"
    await db_exec(
        "INSERT INTO settings (key, value) VALUES ('event_active', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (new_value,),
    )
    if new_value == "1":
        for key, value in (("event_multiplier", "2"), ("event_until", "0")):
            await db_exec(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
    _invalidate_event_state_cache()

    if new_value == "1":
        await message.reply(TEXTS["toggle_event_1"])
    else:
        await message.reply(TEXTS["toggle_event_2"])

async def get_upgrader_and_diamond(user_id: int) -> tuple:
    """upgrader_level и diamond_coin не входят в USER_COLUMNS (как и gold_coin — см. комментарий
    у ALTER TABLE), поэтому читаем отдельным запросом, по тому же паттерну."""
    row = await db_query_one("SELECT upgrader_level, diamond_coin FROM users WHERE user_id = ?", (user_id,))
    if not row:
        return 1, 0
    return (row[0] or 1), (row[1] or 0)

def format_upgrade_page_text(upgrades: dict, rebirth_points: int, category: int, craft_points: int = 0,
                              coins: int = 0, gold_coin: int = 0, upgrader_lvl: int = 1,
                              diamond_coin: int = 0, prestige_points: int = 0) -> str:
    craft_line = f"💠 Очки крафта: <code>{craft_points}</code>\n" if category in (3, 4) else ""
    # Категория 3 (обменник) тратит 🪙/🌕 как доп. валюту, категория 4 (новые прокачки, ветки
    # 13-16) тратит 🌕/💎/🔮 (см. UPGRADES['auto_farm_gold_coin'], ['transfer'], ['exchanger']),
    # поэтому в этих вкладках показываем баланс нужных валют, иначе игрок не видит, хватает ли
    # ему монет/гкоин на следующий уровень, не открывая отдельно "баланс".
    coins_line = f"🪙 Монеты: <code>{coins}</code>\n🌕 Голд коин: <code>{gold_coin}</code>\n" if category == 3 else ""
    gold_line = f"🌕 Голд коин: <code>{gold_coin}</code>\n" if category == 4 else ""
    prestige_line = f"🔮 Престиж: <code>{prestige_points}</code>\n" if category in (3, 4) else ""
    can_lvl_up = upgrader_can_level_up(upgrades, upgrader_lvl)
    diamond_line = f"💎 Алмаз коин: <code>{diamond_coin}</code>\n" if (can_lvl_up or category == 4) else ""
    header = (
        f"⚙️ <b>МЕНЮ ПРОКАЧКИ</b> — {UPGRADE_CATEGORIES[category]}\n"
        f"🔺 Уровень апгрейдера: <code>{upgrader_lvl}/{UPGRADER_LEVEL_MAX}</code>\n"
        f"🉑 Очки перерождения: <code>{rebirth_points}</code>\n"
        f"{craft_line}"
        f"{coins_line}"
        f"{gold_line}"
        f"{prestige_line}"
        f"{diamond_line}"
        f"━━━━━━━━━━━━━━━━━━\n"
    )
    return header

UPGRADE_EXTRA_CURRENCY_EMOJI = {
    "craft_points": plain_emoji(PREMIUM_CRAFT_POINT),
    "coins": "🪙",
    "gold_coin": "🌕",
    "diamond_coin": "💎",
    "prestige_points": "🔮",
}

def upgrade_page_keyboard(upgrades: dict, user_id: int, category: int, upgrader_lvl: int = 1) -> InlineKeyboardMarkup:
    rows = []
    for key in UPGRADE_ORDER:
        cfg = UPGRADES[key]
        if cfg["category"] != category:
            continue
        level = upgrade_level(upgrades, key)
        max_lvl = effective_max_level(key, upgrader_lvl)
        if cfg.get("wip"):
            label = f"🔧 {cfg['name']} — {level}/{max_lvl} (в разработке)"
            rows.append([InlineKeyboardButton(text=label, callback_data="upg_noop")])
            continue
        cost = upgrade_next_cost(key, upgrades, upgrader_lvl)
        if cost is None:
            label = f"✅ {cfg['name']} — {level}/{max_lvl} (макс)"
            rows.append([InlineKeyboardButton(text=label, callback_data="upg_noop")])
        else:
            extras = upgrade_next_extra_costs(key, upgrades, upgrader_lvl)
            extra_part = "".join(
                f" + {amount} {UPGRADE_EXTRA_CURRENCY_EMOJI.get(currency, '')}" for currency, amount in extras
            )
            label = f"{cfg['name']} — {level}/{max_lvl} ({cost} 🉑{extra_part})"
            rows.append([InlineKeyboardButton(text=label, callback_data=f"upg_buy:{user_id}:{category}:{key}")])

    # Кнопка прокачки уровня апгрейдера — появляется только когда все ветки во всех
    # открытых на данном уровне апгрейдера категориях прокачаны до максимума.
    if upgrader_can_level_up(upgrades, upgrader_lvl):
        lvl_cost = upgrader_next_cost(upgrader_lvl)
        label = f"🔺 Апгрейд уровня апгрейдера ({upgrader_lvl}→{upgrader_lvl + 1}) — {lvl_cost} 💎"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"upg_lvlup:{user_id}:{category}")])

    nav = []
    for cat in unlocked_categories(upgrader_lvl):
        marker = "• " if cat == category else ""
        nav.append(InlineKeyboardButton(text=f"{marker}{cat}", callback_data=f"upg_page:{user_id}:{cat}"))
    rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.message(F.text.lower().in_({"апгрейд", "прокачка", "апг"}))
async def upgrade_menu(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"

    row = await ensure_user(user_id, username)
    upgrades = parse_upgrades(row[16])
    rebirth_points = row[14]
    craft_points = row[32]
    coins = row[5]
    prestige_points = row[27]
    upgrader_lvl, diamond_coin = await get_upgrader_and_diamond(user_id)
    gc_row = await db_query_one("SELECT gold_coin FROM users WHERE user_id = ?", (user_id,))
    gold_coin = gc_row[0] if gc_row else 0

    await message.reply(
        format_upgrade_page_text(upgrades, rebirth_points, 1, craft_points, coins, gold_coin,
                                  upgrader_lvl, diamond_coin, prestige_points),
        reply_markup=upgrade_page_keyboard(upgrades, user_id, 1, upgrader_lvl),
    )

@dp.callback_query(F.data == "upg_noop")
async def upgrade_noop(callback: CallbackQuery):
    await callback.answer()

@dp.callback_query(F.data.startswith("upg_page:"))
async def upgrade_change_page(callback: CallbackQuery):
    _, owner_str, category_str = callback.data.split(":")
    owner_id = int(owner_str)
    category = int(category_str)
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["upgrade_change_page_1"], show_alert=True)
        return
    await callback.answer()

    row = await get_user(owner_id)
    upgrades = parse_upgrades(row[16])
    rebirth_points = row[14]
    craft_points = row[32]
    coins = row[5]
    prestige_points = row[27]
    upgrader_lvl, diamond_coin = await get_upgrader_and_diamond(owner_id)
    if category not in unlocked_categories(upgrader_lvl):
        category = 1
    gc_row = await db_query_one("SELECT gold_coin FROM users WHERE user_id = ?", (owner_id,))
    gold_coin = gc_row[0] if gc_row else 0
    await safe_edit_text(callback, 
        format_upgrade_page_text(upgrades, rebirth_points, category, craft_points, coins, gold_coin,
                                  upgrader_lvl, diamond_coin, prestige_points),
        reply_markup=upgrade_page_keyboard(upgrades, owner_id, category, upgrader_lvl),
    )

@dp.callback_query(F.data.startswith("upg_lvlup:"))
async def upgrade_level_up(callback: CallbackQuery):
    _, owner_str, category_str = callback.data.split(":")
    owner_id = int(owner_str)
    category = int(category_str)
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["upgrade_buy_1"], show_alert=True)
        return

    row = await get_user(owner_id)
    upgrades = parse_upgrades(row[16])
    rebirth_points = row[14]
    craft_points = row[32]
    coins = row[5]
    prestige_points = row[27]
    upgrader_lvl, diamond_coin = await get_upgrader_and_diamond(owner_id)

    if not upgrader_can_level_up(upgrades, upgrader_lvl):
        await callback.answer(TEXTS["upgrade_buy_3"], show_alert=True)
        return

    lvl_cost = upgrader_next_cost(upgrader_lvl)
    if lvl_cost is None or diamond_coin < lvl_cost:
        await callback.answer(
            f"Нужно {lvl_cost} 💎 акоин, у тебя {diamond_coin}.", show_alert=True
        )
        return

    new_upgrader_lvl = upgrader_lvl + 1
    await db_exec(
        "UPDATE users SET upgrader_level = ?, diamond_coin = diamond_coin - ? WHERE user_id = ?",
        (new_upgrader_lvl, lvl_cost, owner_id),
    )
    _, new_diamond_coin = await get_upgrader_and_diamond(owner_id)

    if category not in unlocked_categories(new_upgrader_lvl):
        category = 1
    gc_row = await db_query_one("SELECT gold_coin FROM users WHERE user_id = ?", (owner_id,))
    gold_coin = gc_row[0] if gc_row else 0
    await safe_edit_text(callback,
        format_upgrade_page_text(upgrades, rebirth_points, category, craft_points, coins, gold_coin,
                                  new_upgrader_lvl, new_diamond_coin, prestige_points),
        reply_markup=upgrade_page_keyboard(upgrades, owner_id, category, new_upgrader_lvl),
    )
    await callback.answer(f"🔺 Апгрейдер прокачан до уровня {new_upgrader_lvl}!")

@dp.callback_query(F.data.startswith("upg_buy:"))
async def upgrade_buy(callback: CallbackQuery):
    _, owner_str, category_str, key = callback.data.split(":")
    owner_id = int(owner_str)
    category = int(category_str)
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["upgrade_buy_1"], show_alert=True)
        return
    if key not in UPGRADES or UPGRADES[key].get("wip"):
        await callback.answer(TEXTS["upgrade_buy_2"], show_alert=True)
        return

    row = await get_user(owner_id)
    upgrades = parse_upgrades(row[16])
    rebirth_points = row[14]
    craft_points = row[32]
    coins = row[5]
    prestige_points = row[27]
    upgrader_lvl, diamond_coin = await get_upgrader_and_diamond(owner_id)
    if category not in unlocked_categories(upgrader_lvl):
        await callback.answer(TEXTS["upgrade_buy_2"], show_alert=True)
        return
    cost = upgrade_next_cost(key, upgrades, upgrader_lvl)

    if cost is None:
        await callback.answer(TEXTS["upgrade_buy_3"], show_alert=True)
        return
    if rebirth_points < cost:
        await callback.answer(TEXTS["upgrade_buy_4"].format(v0=cost, v1=rebirth_points), show_alert=True)
        return

    extras = upgrade_next_extra_costs(key, upgrades, upgrader_lvl)
    # UPGRADE_EXTRA_CURRENCY_LABELS: описание для любой валюты, которая может
    # встретиться в extra_cost апгрейдов (не только craft_points, как было раньше
    # захардкожено) — эмодзи+название для алерта, и откуда брать текущий баланс.
    # gold_coin/diamond_coin/prestige_points не входят в USER_COLUMNS (см. комментарий
    # у ALTER TABLE), поэтому для них читаем баланс отдельным запросом, а не из row.
    async def _extra_balance(currency: str) -> int:
        if currency == "craft_points":
            return craft_points
        if currency == "coins":
            return coins
        if currency == "gold_coin":
            gc_row = await db_query_one("SELECT gold_coin FROM users WHERE user_id = ?", (owner_id,))
            return gc_row[0] if gc_row else 0
        if currency == "diamond_coin":
            return diamond_coin
        if currency == "prestige_points":
            pp_row = await db_query_one("SELECT prestige_points FROM users WHERE user_id = ?", (owner_id,))
            return pp_row[0] if pp_row else 0
        return 0

    # Сначала проверяем ВСЕ доп. валюты, прежде чем списывать хоть одну — иначе при
    # нехватке второй валюты первая уже была бы списана.
    for currency, amount in extras:
        balance = await _extra_balance(currency)
        if balance < amount:
            label = UPGRADE_EXTRA_CURRENCY_LABELS.get(currency, currency)
            await callback.answer(
                f"Нужно {amount} {label}, у тебя {balance}.", show_alert=True
            )
            return

    upgrades[key] = upgrade_level(upgrades, key) + 1
    new_points = rebirth_points - cost
    extra_amounts = {currency: amount for currency, amount in extras}
    new_craft_points = craft_points - extra_amounts.get("craft_points", 0)
    new_coins = coins - extra_amounts.get("coins", 0)
    new_diamond_coin = diamond_coin - extra_amounts.get("diamond_coin", 0)
    new_prestige_points = prestige_points - extra_amounts.get("prestige_points", 0)
    await db_exec(
        "UPDATE users SET rebirth_points = ?, upgrades = ?, craft_points = ? WHERE user_id = ?",
        (new_points, format_upgrades(upgrades), new_craft_points, owner_id),
    )
    if "coins" in extra_amounts:
        await db_exec("UPDATE users SET coins = coins - ? WHERE user_id = ?", (extra_amounts["coins"], owner_id))
    if "gold_coin" in extra_amounts:
        await db_exec("UPDATE users SET gold_coin = gold_coin - ? WHERE user_id = ?", (extra_amounts["gold_coin"], owner_id))
    if "diamond_coin" in extra_amounts:
        await db_exec("UPDATE users SET diamond_coin = diamond_coin - ? WHERE user_id = ?", (extra_amounts["diamond_coin"], owner_id))
    if "prestige_points" in extra_amounts:
        await db_exec("UPDATE users SET prestige_points = prestige_points - ? WHERE user_id = ?", (extra_amounts["prestige_points"], owner_id))

    gc_row = await db_query_one("SELECT gold_coin FROM users WHERE user_id = ?", (owner_id,))
    new_gold_coin = gc_row[0] if gc_row else 0

    await safe_edit_text(callback, 
        format_upgrade_page_text(upgrades, new_points, category, new_craft_points, new_coins, new_gold_coin,
                                  upgrader_lvl, new_diamond_coin, new_prestige_points),
        reply_markup=upgrade_page_keyboard(upgrades, owner_id, category, upgrader_lvl),
    )
    await callback.answer(TEXTS["upgrade_buy_5"].format(v0=UPGRADES[key]['name'], v1=upgrades[key]))

def format_prestige_page_text(prestige_upgrades: dict, prestige_points: int, page: int) -> str:
    total_pages = (len(PRESTIGE_ORDER) - 1) // PRESTIGE_PAGE_SIZE + 1
    header = (
        f"🔮 <b>ДЕРЕВО ПРЕСТИЖА</b> — стр. {page + 1}/{total_pages}\n"
        f"🔮 Очки престижа: <code>{prestige_points}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Ветки бесконечны — чем выше уровень, тем реже растёт эффект, а цена растёт всегда.\n"
    )
    start = page * PRESTIGE_PAGE_SIZE
    lines = [header]
    for key in PRESTIGE_ORDER[start:start + PRESTIGE_PAGE_SIZE]:
        cfg = PRESTIGE_UPGRADES[key]
        level = prestige_level(prestige_upgrades, key)
        bonus = prestige_bonus(prestige_upgrades, key)
        cost = prestige_next_cost(key, prestige_upgrades)
        lines.append(
            f"{cfg['emoji']} <b>{cfg['name']}</b> — ур. {level} (эффект: {bonus})\n"
            f"   {cfg['desc']}\n"
            f"   Следующий уровень: {cost} 🔮"
        )
    return "\n".join(lines)

def prestige_page_keyboard(prestige_upgrades: dict, user_id: int, page: int) -> InlineKeyboardMarkup:
    total_pages = (len(PRESTIGE_ORDER) - 1) // PRESTIGE_PAGE_SIZE + 1
    start = page * PRESTIGE_PAGE_SIZE
    rows = []
    for key in PRESTIGE_ORDER[start:start + PRESTIGE_PAGE_SIZE]:
        cfg = PRESTIGE_UPGRADES[key]
        level = prestige_level(prestige_upgrades, key)
        cost = prestige_next_cost(key, prestige_upgrades)
        label = f"⬆️ {cfg['emoji']} {cfg['name']} ({cost} 🔮)"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"pr_buy:{user_id}:{page}:{key}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"pr_page:{user_id}:{page - 1}", style="primary"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="pr_noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"pr_page:{user_id}:{page + 1}", style="primary"))
    rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.message(F.text.lower() == "престиж")
async def prestige_menu(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"

    row = await ensure_user(user_id, username)
    prestige_upgrades = parse_prestige_upgrades(row[28])
    prestige_points = row[27]

    await message.reply(
        format_prestige_page_text(prestige_upgrades, prestige_points, 0),
        reply_markup=prestige_page_keyboard(prestige_upgrades, user_id, 0),
    )

@dp.callback_query(F.data == "pr_noop")
async def prestige_noop(callback: CallbackQuery):
    await callback.answer()

@dp.callback_query(F.data.startswith("pr_page:"))
async def prestige_change_page(callback: CallbackQuery):
    _, owner_str, page_str = callback.data.split(":")
    owner_id = int(owner_str)
    page = int(page_str)
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["upgrade_change_page_1"], show_alert=True)
        return
    await callback.answer()

    row = await get_user(owner_id)
    prestige_upgrades = parse_prestige_upgrades(row[28])
    prestige_points = row[27]
    await safe_edit_text(callback, 
        format_prestige_page_text(prestige_upgrades, prestige_points, page),
        reply_markup=prestige_page_keyboard(prestige_upgrades, owner_id, page),
    )

@dp.callback_query(F.data.startswith("pr_buy:"))
async def prestige_buy(callback: CallbackQuery):
    _, owner_str, page_str, key = callback.data.split(":")
    owner_id = int(owner_str)
    page = int(page_str)
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["upgrade_buy_1"], show_alert=True)
        return
    if key not in PRESTIGE_UPGRADES:
        await callback.answer(TEXTS["upgrade_buy_2"], show_alert=True)
        return

    row = await get_user(owner_id)
    prestige_upgrades = parse_prestige_upgrades(row[28])
    prestige_points = row[27]
    cost = prestige_next_cost(key, prestige_upgrades)

    if prestige_points < cost:
        await callback.answer(TEXTS["prestige_buy_4"].format(v0=cost, v1=prestige_points), show_alert=True)
        return

    prestige_upgrades[key] = prestige_level(prestige_upgrades, key) + 1
    new_points = prestige_points - cost
    await db_exec(
        "UPDATE users SET prestige_points = ?, prestige_upgrades = ? WHERE user_id = ?",
        (new_points, format_prestige_upgrades(prestige_upgrades), owner_id),
    )

    await safe_edit_text(callback, 
        format_prestige_page_text(prestige_upgrades, new_points, page),
        reply_markup=prestige_page_keyboard(prestige_upgrades, owner_id, page),
    )
    await callback.answer(TEXTS["upgrade_buy_5"].format(v0=PRESTIGE_UPGRADES[key]['name'], v1=prestige_upgrades[key]))

async def compute_rebirth_result(user_id: int, score: int, evolution_level: int, rebirth_points: int, rebirth_count: int,
                                  prestige_points: int, prestige_upgrades: dict, active_items, inventory_map: dict) -> dict:
    """Считает результат перерождения (в т.ч. проки дерева монет, требующие БД) — общая логика
    для ручной команды «перерождение» и авто-перерождения (см. try_auto_rebirth)."""
    points_gained = (evolution_level // REBIRTH_EVO_STEP) * REBIRTH_POINTS_PER_STEP
    new_rebirth_points = rebirth_points + points_gained
    new_rebirth_count = rebirth_count + 1

    extra_text = ""
    echo_chance = 0.01 * prestige_bonus(prestige_upgrades, "p_echo")
    if echo_chance > 0 and random.random() < echo_chance:
        new_rebirth_points += 1
        extra_text += "\n🔮 Эхо сработало: +1 доп. Очко Перерождения!"

    new_prestige_points = prestige_points + PRESTIGE_PER_REBIRTH

    kept_evolution = 0
    kept_score = 0
    if "ice_shard" in set(_normalize_active_items(active_items)) and random.random() < ICE_SHARD_SAVE_CHANCE:
        kept_evolution = evolution_level
        extra_text += "\n🧊 Ледяной осколок: уровень эволюции сохранён!"
    else:
        save_result = await apply_coin_tree_save(user_id, inventory_map, "rebirth", score, evolution_level)
        kept_score = save_result["kept_score"]
        kept_evolution = save_result["kept_evolution"]
        extra_text += save_result["extra_text"]

    return {
        "points_gained": points_gained,
        "kept_evolution": kept_evolution,
        "kept_score": kept_score,
        "rebirth_points": new_rebirth_points,
        "rebirth_count": new_rebirth_count,
        "prestige_points": new_prestige_points,
        "extra_text": extra_text,
    }

async def try_auto_rebirth(user_id: int, score: int, evolution_level: int, rebirth_count: int,
                            rebirth_points: int, prestige_points: int, prestige_upgrades: dict,
                            active_items=None) -> tuple[int, int, int, int, int, str]:
    """VIP авто-перерождение: срабатывает само, как только эволюция достигает REBIRTH_MIN_EVO
    (см. auto_rebirth_on/off). Возвращает (score, evolution_level, rebirth_count, rebirth_points,
    prestige_points, текст для добавления к ответу)."""
    if evolution_level < REBIRTH_MIN_EVO:
        return score, evolution_level, rebirth_count, rebirth_points, prestige_points, ""

    inv_rows = await get_inventory(user_id)
    inventory_map = {k: q for k, q in inv_rows}
    result = await compute_rebirth_result(user_id, score, evolution_level, rebirth_points, rebirth_count, prestige_points, prestige_upgrades, active_items, inventory_map)
    await db_exec(
        "UPDATE users SET score = ?, evolution_level = ?, rebirth_points = ?, rebirth_count = ?, "
        "prestige_points = ? WHERE user_id = ?",
        (result["kept_score"], result["kept_evolution"], result["rebirth_points"], result["rebirth_count"], result["prestige_points"], user_id),
    )
    text = f"\n♻️ Авто-перерождение: +{result['points_gained']}🉑 (всего {result['rebirth_points']}🉑)" + result["extra_text"]
    return result["kept_score"], result["kept_evolution"], result["rebirth_count"], result["rebirth_points"], result["prestige_points"], text

@dp.message(F.text.lower() == "перерождение")
async def rebirth(message: Message):
    if not await require_subscription(message):
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"

    row = await ensure_user(user_id, username)
    score, evolution_level = row[2], row[3]
    rebirth_points, rebirth_count = row[14], row[15]
    prestige_points = row[27]
    prestige_upgrades = parse_prestige_upgrades(row[28])
    active_items = parse_equipped(row[18])

    if evolution_level < REBIRTH_MIN_EVO:
        await message.reply(
            TEXTS["rebirth_1"].format(v0=REBIRTH_MIN_EVO, v1=evolution_level, v2=REBIRTH_MIN_EVO)
        )
        return

    inv_rows = await get_inventory(user_id)
    inventory_map = {k: q for k, q in inv_rows}
    result = await compute_rebirth_result(user_id, score, evolution_level, rebirth_points, rebirth_count, prestige_points, prestige_upgrades, active_items, inventory_map)

    await db_exec(
        "UPDATE users SET score = ?, evolution_level = ?, rebirth_points = ?, rebirth_count = ?, "
        "prestige_points = ? WHERE user_id = ?",
        (result["kept_score"], result["kept_evolution"], result["rebirth_points"], result["rebirth_count"], result["prestige_points"], user_id),
    )

    new_hardness = round(REBIRTH_HARDNESS_STEP * result["rebirth_count"] * hardness_kwargs(row)["rebirth_mult"] * 100)
    await message.reply(
        TEXTS["rebirth_2"].format(v0=result["points_gained"], v1=result["rebirth_points"], v2=new_hardness, v3=PRESTIGE_PER_REBIRTH) + result["extra_text"]
    )

def ultra_rebirth_eligible(evolution_level: int, leg_level: int, rebirth_count: int,
                            has_awakening_coin: bool, has_chronos_orb: bool) -> bool:
    """Все пять условий обязательны одновременно (см. константы ULTRA_REQUIRED_*):
    эволюция, уровень ноги, число перерождений, а также владение Монетой Пробуждения
    и Хвостом Джевила (просто лежат в инвентаре — экипировать не нужно, не расходуются)."""
    return (
        evolution_level >= ULTRA_REQUIRED_EVO
        and leg_level >= ULTRA_REQUIRED_LEG_LEVEL
        and rebirth_count >= ULTRA_REQUIRED_REBIRTHS
        and has_awakening_coin
        and has_chronos_orb
    )

def ultra_rebirth_confirm_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🌌 Подтвердить", callback_data=f"ultra_ok:{user_id}", style="success"),
        InlineKeyboardButton(text="Отмена", callback_data=f"ultra_no:{user_id}", style="danger"),
    ]])

@dp.message(F.text.lower() == "ультра перерождение")
async def ultra_rebirth_info(message: Message):
    """Показывает статус условий и, если всё готово, просит подтверждение кнопкой —
    Ультра перерождение необратимо и выполняется только один раз за игру."""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"

    row = await ensure_user(user_id, username)
    score, evolution_level = row[2], row[3]
    rebirth_count = row[15]
    ultra_rebirth = bool(row[21])

    if ultra_rebirth:
        await message.reply(TEXTS["ultra_rebirth_already_1"])
        return

    leg_level = get_level_index(score, evolution_level, rebirth_count, **hardness_kwargs(row))

    inv_rows = await get_inventory(user_id)
    inventory_map = {k: q for k, q in inv_rows}
    has_awakening_coin = inventory_map.get("awakening_coin", 0) > 0
    has_chronos_orb = inventory_map.get("chronos_orb", 0) > 0

    if not ultra_rebirth_eligible(evolution_level, leg_level, rebirth_count, has_awakening_coin, has_chronos_orb):
        await message.reply(
            TEXTS["ultra_rebirth_locked_1"].format(
                v0=evolution_level, v1=ULTRA_REQUIRED_EVO,
                v2=leg_level, v3=ULTRA_REQUIRED_LEG_LEVEL,
                v4=rebirth_count, v5=ULTRA_REQUIRED_REBIRTHS,
                v6="✅" if has_awakening_coin else "❌",
                v7="✅" if has_chronos_orb else "❌",
            )
        )
        return

    await message.reply(
        TEXTS["ultra_rebirth_confirm_1"].format(
            v0=ULTRA_LEG_EMOJI, v1=esc(ULTRA_LEG_NAME), v2=ULTRA_LEG_LEVEL,
            v3=round(ULTRA_REBIRTH_BOOST * 100),
        ),
        reply_markup=ultra_rebirth_confirm_keyboard(user_id),
    )

@dp.callback_query(F.data.startswith("ultra_no:"))
async def ultra_rebirth_cancel(callback: CallbackQuery):
    owner_id = int(callback.data.split(":")[1])
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["ultra_rebirth_not_owner_1"], show_alert=True)
        return
    await callback.answer()
    await safe_edit_text(callback, TEXTS["ultra_rebirth_cancelled_1"])

@dp.callback_query(F.data.startswith("ultra_ok:"))
async def ultra_rebirth_confirm(callback: CallbackQuery):
    owner_id = int(callback.data.split(":")[1])
    if callback.from_user.id != owner_id:
        await callback.answer(TEXTS["ultra_rebirth_not_owner_1"], show_alert=True)
        return

    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name or "Без имени"

    row = await ensure_user(user_id, username)
    score, evolution_level = row[2], row[3]
    rebirth_count = row[15]
    ultra_rebirth = bool(row[21])

    if ultra_rebirth:
        await safe_edit_text(callback, TEXTS["ultra_rebirth_already_1"])
        await callback.answer()
        return

    leg_level = get_level_index(score, evolution_level, rebirth_count, **hardness_kwargs(row))

    inv_rows = await get_inventory(user_id)
    inventory_map = {k: q for k, q in inv_rows}
    has_awakening_coin = inventory_map.get("awakening_coin", 0) > 0
    has_chronos_orb = inventory_map.get("chronos_orb", 0) > 0

    if not ultra_rebirth_eligible(evolution_level, leg_level, rebirth_count, has_awakening_coin, has_chronos_orb):
        await safe_edit_text(
            callback,
            TEXTS["ultra_rebirth_locked_1"].format(
                v0=evolution_level, v1=ULTRA_REQUIRED_EVO,
                v2=leg_level, v3=ULTRA_REQUIRED_LEG_LEVEL,
                v4=rebirth_count, v5=ULTRA_REQUIRED_REBIRTHS,
                v6="✅" if has_awakening_coin else "❌",
                v7="✅" if has_chronos_orb else "❌",
            ),
        )
        await callback.answer()
        return

    prestige_points = row[27]
    new_prestige_points = prestige_points + PRESTIGE_PER_ULTRA_REBIRTH
    await db_exec(
        "UPDATE users SET score = 0, evolution_level = 0, rebirth_points = 0, rebirth_count = 0, "
        "evo_hardness_mult = 1.0, rebirth_hardness_mult = 1.0, "
        "ultra_rebirth = 1, prestige_points = ? WHERE user_id = ?",
        (new_prestige_points, user_id),
    )

    await safe_edit_text(
        callback,
        TEXTS["ultra_rebirth_success_1"].format(
            v0=ULTRA_LEG_EMOJI, v1=esc(ULTRA_LEG_NAME), v2=ULTRA_LEG_LEVEL,
            v3=round(ULTRA_REBIRTH_BOOST * 100), v4=PRESTIGE_PER_ULTRA_REBIRTH,
        ),
    )
    await callback.answer()

@dp.message(F.text.lower() == "баланс")
async def show_balance(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"

    row = await ensure_user(user_id, username)
    score, coins = row[2], row[5]
    vip_until = row[12]
    rebirth_points, rebirth_count = row[14], row[15]
    craft_points = row[32]
    vip_active = is_vip_active(vip_until)
    gc_row = await db_query_one("SELECT gold_coin, diamond_coin FROM users WHERE user_id = ?", (user_id,))
    gold_coin, diamond_coin = gc_row if gc_row else (0, 0)

    vip_line = f"{PREMIUM_VIP_BADGE} VIP активен" if vip_active else "VIP не активен"

    await message.reply(
        TEXTS["show_balance_1"].format(
            v0=score, v1=coins, v2=rebirth_points, v3=rebirth_count, v4=vip_line, v5=craft_points,
            v6=gold_coin, v7=diamond_coin,
        )
    )

HELP_SECTION_ALIASES = {
    "бейдж": "бейдж", "бейджи": "бейдж", "значок": "бейдж", "значки": "бейдж",
    "бустер": "бустер", "бустеры": "бустер",
    "предмет": "предмет", "предметы": "предмет",
    "зелье": "зелье", "зелья": "зелье", "зелий": "зелье",
    "команда": "команда", "команды": "команда",
}

# Справочник для «помощь команда <название>»: ключ -> (эмодзи, алиасы команды, описание).
# Первый алиас — «каноничное» отображаемое имя команды.
HELP_COMMANDS = {
    "farm": ("🦵", ["ферма", "фарма"],
             "Основная команда добычи очков ноги — жми регулярно (или отправляй 🦵/🦿), копится опыт для эволюций и перерождений."),
    "bonus": ("🎁", ["бонус"],
              "Ежедневная награда очками ноги — стрик за подряд идущие дни. На 5-й день серии дополнительно даёт Дневной амулет."),
    "upgrade": ("⬆️", ["апгрейд", "прокачка", "апг"],
                "Прокачка постоянных улучшений за очки перерождения/крафта: лимиты, скорость варки зелий, слоты бустеров и т.д."),
    "craft": ("🛠", ["крафт", "крафты"],
              "Меню крафта — соединяй предметы/бустеры по рецептам и получай более сильные вещи (вплоть до Эссенции Бога)."),
    "case": ("🎰", ["кейс", "кейсы"],
             "Открытие кейсов за монеты — выпадают случайные предметы и бустеры из пула конкретного кейса."),
    "evolution": ("🧬", ["эволюция"],
                  "Переход на новый уровень эволюции при достижении нужного количества очков ноги — открывает новые возможности."),
    "prestige": ("🌟", ["престиж"],
                 "Система престижа — сброс части прогресса ради постоянных бонусов более высокого порядка."),
    "rebirth": ("🉑", ["перерождение"],
                "Сбрасывает ногу и эволюцию, взамен даёт очки перерождения — их тратят на апгрейды и крафт уникальных бустеров."),
    "ultra_rebirth": ("💫", ["ультра перерождение"],
                       "Разовый необратимый прыжок за грань обычного мира: обнуляет ногу, эволюцию и перерождения, "
                       "но взамен открывает второй, ULTRA-мир уровней (потолок улетает с 20001 в астрономические дали), "
                       "даёт постоянный буст добычи и очки престижа (отдельная валюта для престиж-апгрейдов). "
                       "Условия: эволюция 50+, уровень ноги 20001+, 5+ перерождений, а также Монета Пробуждения и Хвост Джевила в инвентаре."),
    "exchange": ("💱", ["обменять"],
                 "Обменивает очки ноги на монеты по фиксированному курсу: «обменять <число>»."),
    "inventory": ("🎒", ["инвентарь", "мой инвентарь"],
                  "Общее меню инвентаря — оттуда переходишь в разделы Бустеры/Предметы/Зелья."),
    "boosters": ("🧪", ["бустеры", "мои бустеры"],
                 "Список твоих бустеров с возможностью экипировать/снять прямо из меню."),
    "items": ("📦", ["предметы", "мои предметы"],
              "Список твоих обычных предметов (сырьё для крафта, коллекционные вещи)."),
    "potions": ("⚗️", ["зелья", "мои зелья"],
                "Меню зелий — варка в котле, забор готового и использование, все кнопками."),
    "give": ("🤝", ["дать", "передать"],
             "Передать другому игроку (ответом на его сообщение) монеты, очки ноги или предмет из своего инвентаря: «дать 100 коин», «дать эссенция дружбы»."),
    "sell": ("💰", ["продать"],
             "Продажа бустеров/предметов из инвентаря за монеты по фиксированной цене: «продать б <название>» / «продать п <название>»."),
    "destroy": ("🗑", ["уничтожение"],
                "Безвозвратно уничтожает бустер/предмет из инвентаря (без монет взамен) — полезно для нетоварных вещей: «уничтожение б/п <название>»."),
    "balance": ("💳", ["баланс"],
                "Показывает текущий баланс: очки ноги, монеты, очки перерождения/крафта и статус VIP."),
    "vip": ("💎", ["вип"],
            "Информация о VIP-статусе и его покупке — постоянный сильный бустер и доступ к особым фичам."),
    "badges_toggle": ("🏷", ["бейджи"],
                       "Меню управления своими бейджами — какие показывать рядом с ником в топах."),
    "top": ("🏆", ["топ ног", "топ эво", "топ коин", "топ очкп"],
            "Топы игроков по разным метрикам (ноги/эволюция/монеты/очки перерождения), в своём чате или глобально («гл топ ...»)."),
    "info": ("ℹ️", ["инфо"],
             "Показывает игровую карточку другого игрока по юзернейму: «инфо @ник»."),
    "promo": ("🎟", ["промокод", "промо"],
              "Активирует промокод и выдаёт награду, если код существует и ещё не использован тобой: «промокод <код>»."),
    "nick": ("✏️", ["+ник", "-ник"],
             "Устанавливает или сбрасывает отображаемый игровой ник: «+ник <текст>» / «-ник»."),
    "help": ("❓", ["помощь"],
             "Эта самая справка — «помощь бустер/предмет/зелье/бейдж/команда <название>»."),
}

def find_help_command_key(query: str):
    """Ищет ключ HELP_COMMANDS по названию/алиасу команды. Сначала точное совпадение,
    иначе — по вхождению подстроки в любой алиас. Возвращает (key, None) при однозначном
    совпадении, (None, [варианты]) при неоднозначности, (None, []) если не найдено."""
    q = (query or "").strip().lower()
    if not q:
        return None, []
    for key, (_, aliases, _) in HELP_COMMANDS.items():
        if q in (a.lower() for a in aliases):
            return key, None
    matches = [key for key, (_, aliases, _) in HELP_COMMANDS.items() if any(q in a.lower() for a in aliases)]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        matches.sort(key=lambda k: HELP_COMMANDS[k][1][0])
        return None, matches
    return None, []

@dp.message(F.text.lower() == "помощь")
async def help_root(message: Message):
    await message.reply(TEXTS["help_root_1"])

@dp.message(F.text.regexp(r"(?i)^помощь\s+(\S+)(?:\s+(.+))?$"))
async def help_dispatch(message: Message):
    match = re.match(r"(?i)^помощь\s+(\S+)(?:\s+(.+))?$", message.text.strip())
    raw_section = match.group(1).strip().lower()
    query = (match.group(2) or "").strip()

    section = HELP_SECTION_ALIASES.get(raw_section)
    if not section:
        await message.reply(TEXTS["help_unknown_section_1"].format(v0=esc(match.group(1))))
        return

    if section == "бейдж":
        await help_badge(message, query)
        return

    if section == "бустер":
        await help_booster(message, query)
        return

    if section == "предмет":
        await help_item(message, query)
        return

    if section == "зелье":
        await help_potion(message, query)
        return

    if section == "команда":
        await help_command(message, query)
        return

    await message.reply(TEXTS["help_unknown_section_1"].format(v0=esc(raw_section)))

async def help_badge(message: Message, query: str):
    if not query:
        await message.reply(TEXTS["help_badge_general_1"])
        return

    key, matches = find_help_badge_key(query)
    if key:
        emoji, aliases, desc = HELP_BADGES[key]
        await message.reply(f"🏷 <b>{emoji} {esc(aliases[0].capitalize())}</b>\n{desc}")
        return

    if matches:
        options = "\n".join(f"• {HELP_BADGES[m][1][0]}" for m in matches)
        await message.reply(TEXTS["help_badge_ambiguous_1"].format(v0=esc(query), v1=options))
        return

    available = ", ".join(aliases[0] for _, aliases, _ in HELP_BADGES.values())
    await message.reply(TEXTS["help_badge_not_found_1"].format(v0=esc(query), v1=esc(available)))

async def help_booster(message: Message, query: str):
    if not query:
        await message.reply(TEXTS["help_booster_general_1"])
        return

    key, matches = find_item_key_by_name(query, HELP_BOOSTER_KEYS)
    if key:
        emoji, name, _, _ = ITEMS[key]
        await message.reply(TEXTS["help_booster_info_1"].format(v0=emoji, v1=esc(name), v2=format_help_booster_text(key)))
        return

    if matches:
        options = "\n".join(f"• {ITEMS[m][1]}" for m in matches)
        await message.reply(TEXTS["help_booster_ambiguous_1"].format(v0=esc(query), v1=options))
        return

    await message.reply(TEXTS["help_booster_not_found_1"].format(v0=esc(query)))

async def help_item(message: Message, query: str):
    if not query:
        await message.reply(TEXTS["help_item_general_1"])
        return

    key, matches = find_item_key_by_name(query, HELP_ITEM_KEYS)
    if key:
        emoji, name, _, _ = ITEMS[key]
        await message.reply(TEXTS["help_item_info_1"].format(v0=emoji, v1=esc(name), v2=format_help_item_text(key)))
        return

    if matches:
        options = "\n".join(f"• {ITEMS[m][1]}" for m in matches)
        await message.reply(TEXTS["help_item_ambiguous_1"].format(v0=esc(query), v1=options))
        return

    await message.reply(TEXTS["help_item_not_found_1"].format(v0=esc(query)))

async def help_potion(message: Message, query: str):
    if not query:
        await message.reply(TEXTS["help_potion_general_1"])
        return

    key, matches = find_potion_key_by_name(query)
    if key:
        cfg = POTIONS[key]
        await message.reply(TEXTS["help_potion_info_1"].format(v0=cfg["emoji"], v1=esc(cfg["name"]), v2=format_help_potion_text(key)))
        return

    if matches:
        options = "\n".join(f"• {POTIONS[m]['name']}" for m in matches)
        await message.reply(TEXTS["help_potion_ambiguous_1"].format(v0=esc(query), v1=options))
        return

    await message.reply(TEXTS["help_potion_not_found_1"].format(v0=esc(query)))

async def help_command(message: Message, query: str):
    if not query:
        await message.reply(TEXTS["help_command_general_1"])
        return

    key, matches = find_help_command_key(query)
    if key:
        emoji, aliases, desc = HELP_COMMANDS[key]
        await message.reply(TEXTS["help_command_info_1"].format(v0=emoji, v1=esc(aliases[0]), v2=desc))
        return

    if matches:
        options = "\n".join(f"• {HELP_COMMANDS[m][1][0]}" for m in matches)
        await message.reply(TEXTS["help_command_ambiguous_1"].format(v0=esc(query), v1=options))
        return

    available = ", ".join(aliases[0] for _, aliases, _ in HELP_COMMANDS.values())
    await message.reply(TEXTS["help_command_not_found_1"].format(v0=esc(query), v1=esc(available)))

@dp.message(F.text.lower().startswith("!дать очкп"))
async def admin_give_rebirth(message: Message):
    if not await is_admin_role_or_above(message):
        return
    await log_admin_action(message)
    match = ADMIN_GIVE_REBIRTH_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_give_rebirth_1"])
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply(TEXTS["admin_give_rebirth_2"])
        return

    amount = parse_amount(match.group(1))
    if not amount or amount <= 0:
        await message.reply(TEXTS["admin_give_rebirth_3"])
        return
    gate_err = await admin_role_gate(message, currency="очкп", amount=amount)
    if gate_err:
        await message.reply(gate_err)
        return
    target_username = target.username or target.first_name or "Без имени"

    row = await ensure_user(target.id, target_username)
    new_points = row[14] + amount
    await db_exec("UPDATE users SET rebirth_points = ? WHERE user_id = ?", (new_points, target.id))
    await message.reply(TEXTS["admin_give_rebirth_4"].format(v0=amount, v1=esc(target_username), v2=new_points))

@dp.message(F.text.regexp(r"(?i)^!дать (?:крафт|очкк)\b"))
async def admin_give_craft(message: Message):
    if not await is_admin_role_or_above(message):
        return
    await log_admin_action(message)
    match = ADMIN_GIVE_CRAFT_RE.match(message.text.strip())
    if not match:
        await message.reply("Формат: !дать крафт <количество> [себе] (в ответ на сообщение игрока). Алиас: !дать очкк")
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply("Ответь этой командой на сообщение игрока, либо допиши «себе».")
        return

    amount = parse_amount(match.group(1))
    if not amount or amount <= 0:
        await message.reply("Некорректное количество.")
        return
    gate_err = await admin_role_gate(message, currency="очкк", amount=amount)
    if gate_err:
        await message.reply(gate_err)
        return
    target_username = target.username or target.first_name or "Без имени"

    row = await ensure_user(target.id, target_username)
    new_points = row[32] + amount
    await db_exec("UPDATE users SET craft_points = ? WHERE user_id = ?", (new_points, target.id))
    await message.reply(f"Выдано {amount} 💠 очков крафта игроку {esc(target_username)} (Всего: {new_points})")

@dp.message(F.text.regexp(r"(?i)^!снять (?:крафт|очкк)\b"))
async def admin_take_craft(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_TAKE_CRAFT_RE.match(message.text.strip())
    if not match:
        await message.reply("Формат: !снять крафт <количество|все> [себе] (в ответ на сообщение игрока). Алиас: !снять очкк")
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply("Ответь этой командой на сообщение игрока, либо допиши «себе».")
        return
    target_username = target.username or target.first_name or "Без имени"

    if match.group(1) is None:
        await db_exec("UPDATE users SET craft_points = 0 WHERE user_id = ?", (target.id,))
        await message.reply(f"Снято все 💠 очки крафта у игрока {esc(target_username)} (Осталось: 0)")
        return

    amount = parse_amount(match.group(1))
    if not amount or amount <= 0:
        await message.reply("Некорректное количество.")
        return

    row = await ensure_user(target.id, target_username)
    new_points = max(0, row[32] - amount)
    await db_exec("UPDATE users SET craft_points = ? WHERE user_id = ?", (new_points, target.id))
    await message.reply(f"Снято {amount} 💠 очков крафта у игрока {esc(target_username)} (Осталось: {new_points})")

@dp.message(F.text.regexp(r"(?i)^!дать (?:гкоин|голдкоин)\b"))
async def admin_give_gold_coin(message: Message):
    if not await is_admin_role_or_above(message):
        return
    await log_admin_action(message)
    match = ADMIN_GIVE_GOLD_COIN_RE.match(message.text.strip())
    if not match:
        await message.reply("Формат: !дать гкоин <количество> [себе] (в ответ на сообщение игрока). Алиас: !дать голдкоин")
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply("Ответь этой командой на сообщение игрока, либо допиши «себе».")
        return

    amount = parse_amount(match.group(1))
    if not amount or amount <= 0:
        await message.reply("Некорректное количество.")
        return
    gate_err = await admin_role_gate(message, currency="гкоин", amount=amount)
    if gate_err:
        await message.reply(gate_err)
        return
    target_username = target.username or target.first_name or "Без имени"

    await ensure_user(target.id, target_username)
    gc_row = await db_query_one("SELECT gold_coin FROM users WHERE user_id = ?", (target.id,))
    new_amount = (gc_row[0] if gc_row else 0) + amount
    await db_exec("UPDATE users SET gold_coin = ? WHERE user_id = ?", (new_amount, target.id))
    await message.reply(f"Выдано {amount} 🌕 гкоин игроку {esc(target_username)} (Всего: {new_amount})")

@dp.message(F.text.regexp(r"(?i)^!снять (?:гкоин|голдкоин)\b"))
async def admin_take_gold_coin(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_TAKE_GOLD_COIN_RE.match(message.text.strip())
    if not match:
        await message.reply("Формат: !снять гкоин <количество|все> [себе] (в ответ на сообщение игрока). Алиас: !снять голдкоин")
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply("Ответь этой командой на сообщение игрока, либо допиши «себе».")
        return
    target_username = target.username or target.first_name or "Без имени"
    await ensure_user(target.id, target_username)

    if match.group(1) is None:
        await db_exec("UPDATE users SET gold_coin = 0 WHERE user_id = ?", (target.id,))
        await message.reply(f"Снято все 🌕 гкоин у игрока {esc(target_username)} (Осталось: 0)")
        return

    amount = parse_amount(match.group(1))
    if not amount or amount <= 0:
        await message.reply("Некорректное количество.")
        return

    gc_row = await db_query_one("SELECT gold_coin FROM users WHERE user_id = ?", (target.id,))
    new_amount = max(0, (gc_row[0] if gc_row else 0) - amount)
    await db_exec("UPDATE users SET gold_coin = ? WHERE user_id = ?", (new_amount, target.id))
    await message.reply(f"Снято {amount} 🌕 гкоин у игрока {esc(target_username)} (Осталось: {new_amount})")

@dp.message(F.text.regexp(r"(?i)^!дать (?:акоин|алмкоин|алмазкоин)\b"))
async def admin_give_diamond_coin(message: Message):
    if not await is_admin_role_or_above(message):
        return
    await log_admin_action(message)
    match = ADMIN_GIVE_DIAMOND_COIN_RE.match(message.text.strip())
    if not match:
        await message.reply("Формат: !дать акоин <количество> [себе] (в ответ на сообщение игрока). Алиасы: !дать алмкоин, !дать алмазкоин")
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply("Ответь этой командой на сообщение игрока, либо допиши «себе».")
        return

    amount = parse_amount(match.group(1))
    if not amount or amount <= 0:
        await message.reply("Некорректное количество.")
        return
    gate_err = await admin_role_gate(message, currency="акоин", amount=amount)
    if gate_err:
        await message.reply(gate_err)
        return
    target_username = target.username or target.first_name or "Без имени"

    await ensure_user(target.id, target_username)
    dc_row = await db_query_one("SELECT diamond_coin FROM users WHERE user_id = ?", (target.id,))
    new_amount = (dc_row[0] if dc_row else 0) + amount
    await db_exec("UPDATE users SET diamond_coin = ? WHERE user_id = ?", (new_amount, target.id))
    await message.reply(f"Выдано {amount} 💎 акоин игроку {esc(target_username)} (Всего: {new_amount})")

@dp.message(F.text.regexp(r"(?i)^!снять (?:акоин|алмкоин|алмазкоин)\b"))
async def admin_take_diamond_coin(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_TAKE_DIAMOND_COIN_RE.match(message.text.strip())
    if not match:
        await message.reply("Формат: !снять акоин <количество|все> [себе] (в ответ на сообщение игрока). Алиасы: !снять алмкоин, !снять алмазкоин")
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply("Ответь этой командой на сообщение игрока, либо допиши «себе».")
        return
    target_username = target.username or target.first_name or "Без имени"
    await ensure_user(target.id, target_username)

    if match.group(1) is None:
        await db_exec("UPDATE users SET diamond_coin = 0 WHERE user_id = ?", (target.id,))
        await message.reply(f"Снято все 💎 акоин у игрока {esc(target_username)} (Осталось: 0)")
        return

    amount = parse_amount(match.group(1))
    if not amount or amount <= 0:
        await message.reply("Некорректное количество.")
        return

    dc_row = await db_query_one("SELECT diamond_coin FROM users WHERE user_id = ?", (target.id,))
    new_amount = max(0, (dc_row[0] if dc_row else 0) - amount)
    await db_exec("UPDATE users SET diamond_coin = ? WHERE user_id = ?", (new_amount, target.id))
    await message.reply(f"Снято {amount} 💎 акоин у игрока {esc(target_username)} (Осталось: {new_amount})")

@dp.message(F.text.regexp(r"(?i)^!дать престиж\b"))
async def admin_give_prestige(message: Message):
    if not await is_admin_role_or_above(message):
        return
    await log_admin_action(message)
    match = ADMIN_GIVE_PRESTIGE_RE.match(message.text.strip())
    if not match:
        await message.reply("Формат: !дать престиж <количество> [себе] (в ответ на сообщение игрока)")
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply("Ответь этой командой на сообщение игрока, либо допиши «себе».")
        return

    amount = parse_amount(match.group(1))
    if not amount or amount <= 0:
        await message.reply("Некорректное количество.")
        return
    gate_err = await admin_role_gate(message, currency="престиж", amount=amount)
    if gate_err:
        await message.reply(gate_err)
        return
    target_username = target.username or target.first_name or "Без имени"

    row = await ensure_user(target.id, target_username)
    new_points = row[27] + amount
    await db_exec("UPDATE users SET prestige_points = ? WHERE user_id = ?", (new_points, target.id))
    await message.reply(f"Выдано {amount} 🔮 престижа игроку {esc(target_username)} (Всего: {new_points})")

@dp.message(F.text.regexp(r"(?i)^!снять престиж\b"))
async def admin_take_prestige(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_TAKE_PRESTIGE_RE.match(message.text.strip())
    if not match:
        await message.reply("Формат: !снять престиж <количество|все> [себе] (в ответ на сообщение игрока)")
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply("Ответь этой командой на сообщение игрока, либо допиши «себе».")
        return
    target_username = target.username or target.first_name or "Без имени"

    row = await ensure_user(target.id, target_username)
    if match.group(1) is None:
        await db_exec("UPDATE users SET prestige_points = 0 WHERE user_id = ?", (target.id,))
        await message.reply(f"Снято все 🔮 престижа у игрока {esc(target_username)} (Осталось: 0)")
        return

    amount = parse_amount(match.group(1))
    if not amount or amount <= 0:
        await message.reply("Некорректное количество.")
        return

    new_points = max(0, row[27] - amount)
    await db_exec("UPDATE users SET prestige_points = ? WHERE user_id = ?", (new_points, target.id))
    await message.reply(f"Снято {amount} 🔮 престижа у игрока {esc(target_username)} (Осталось: {new_points})")

@dp.message(F.text.lower().startswith("!снять очкп"))
async def admin_take_rebirth(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_TAKE_REBIRTH_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_take_rebirth_1"])
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply(TEXTS["admin_take_rebirth_2"])
        return
    target_username = target.username or target.first_name or "Без имени"

    if match.group(1) is None:
        await db_exec("UPDATE users SET rebirth_points = 0 WHERE user_id = ?", (target.id,))
        await message.reply(TEXTS["admin_take_rebirth_4"].format(v0="все", v1=esc(target_username), v2=0))
        return

    amount = parse_amount(match.group(1))
    if not amount or amount <= 0:
        await message.reply(TEXTS["admin_take_rebirth_3"])
        return

    row = await ensure_user(target.id, target_username)
    new_points = max(0, row[14] - amount)
    await db_exec("UPDATE users SET rebirth_points = ? WHERE user_id = ?", (new_points, target.id))
    await message.reply(TEXTS["admin_take_rebirth_4"].format(v0=amount, v1=esc(target_username), v2=new_points))

@dp.message(F.text.lower().startswith(NEWS_PREFIX))
async def broadcast_news(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    if message.chat.type != "private":
        return

    text = message.text[len(NEWS_PREFIX):].strip()
    if not text:
        await message.reply(TEXTS["broadcast_news_1"])
        return

    chat_ids = await get_all_chat_ids()
    sent = 0
    failed = 0
    body = f"📰 <b>Новость от разработчика:</b>\n\n{esc(text)}"

    for chat_id in chat_ids:
        try:
            await bot.send_message(chat_id, body)
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await bot.send_message(chat_id, body)
                sent += 1
            except Exception:
                failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    await message.reply(TEXTS["broadcast_news_2"].format(v0=sent, v1=failed))

@dp.message(F.text.regexp(r"(?i)^!дать ног(?!и лвл)"))
async def admin_give_legs(message: Message):
    if not await is_admin_role_or_above(message):
        return
    await log_admin_action(message)
    match = ADMIN_GIVE_LEGS_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_give_legs_1"])
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply(TEXTS["admin_give_legs_2"])
        return

    amount = parse_amount(match.group(1))
    if not amount or amount <= 0:
        await message.reply(TEXTS["admin_give_legs_3"])
        return
    gate_err = await admin_role_gate(message, currency="ноги", amount=amount)
    if gate_err:
        await message.reply(gate_err)
        return
    target_username = target.username or target.first_name or "Без имени"

    row = await ensure_user(target.id, target_username)
    new_score = row[2] + amount
    await db_exec("UPDATE users SET score = ? WHERE user_id = ?", (new_score, target.id))
    await maybe_announce_levelup(message, target_username, row[2], new_score, row[3], bool(row[11]), **hardness_kwargs(row))

    await message.reply(TEXTS["admin_give_legs_4"].format(v0=amount, v1=esc(target_username), v2=new_score))

@dp.message(F.text.lower().startswith("!снять ноги"))
async def admin_take_legs(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_TAKE_LEGS_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_take_legs_1"])
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply(TEXTS["admin_take_legs_2"])
        return
    target_username = target.username or target.first_name or "Без имени"

    if match.group(1) is None:
        await db_exec("UPDATE users SET score = 0 WHERE user_id = ?", (target.id,))
        await message.reply(TEXTS["admin_take_legs_4"].format(v0=esc(target_username), v1=0))
        return

    amount = parse_amount(match.group(1))
    if not amount or amount <= 0:
        await message.reply(TEXTS["admin_take_legs_3"])
        return

    row = await ensure_user(target.id, target_username)
    new_score = max(0, row[2] - amount)
    await db_exec("UPDATE users SET score = ? WHERE user_id = ?", (new_score, target.id))

    await message.reply(TEXTS["admin_take_legs_4"].format(v0=esc(target_username), v1=new_score))

@dp.message(F.text.lower().startswith("!дать эво"))
async def admin_give_evo(message: Message):
    if not await is_admin_role_or_above(message):
        return
    await log_admin_action(message)
    match = ADMIN_GIVE_EVO_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_give_evo_1"])
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply(TEXTS["admin_give_evo_2"])
        return

    amount = parse_amount(match.group(1))
    if not amount or amount <= 0:
        await message.reply(TEXTS["admin_give_evo_3"])
        return
    gate_err = await admin_role_gate(message, currency="эво", amount=amount)
    if gate_err:
        await message.reply(gate_err)
        return
    target_username = target.username or target.first_name or "Без имени"

    row = await ensure_user(target.id, target_username)
    new_evo = row[3] + amount
    await db_exec("UPDATE users SET evolution_level = ? WHERE user_id = ?", (new_evo, target.id))

    await message.reply(TEXTS["admin_give_evo_4"].format(v0=amount, v1=esc(target_username), v2=new_evo))

@dp.message(F.text.lower().startswith("!снять эво"))
async def admin_take_evo(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_TAKE_EVO_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_take_evo_1"])
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply(TEXTS["admin_take_evo_2"])
        return
    target_username = target.username or target.first_name or "Без имени"

    if match.group(1) is None:
        await db_exec("UPDATE users SET evolution_level = 0, evo_hardness_mult = 1.0 WHERE user_id = ?", (target.id,))
        await message.reply(TEXTS["admin_take_evo_4"].format(v0="все", v1=esc(target_username), v2=0))
        return

    amount = parse_amount(match.group(1))
    if not amount or amount <= 0:
        await message.reply(TEXTS["admin_take_evo_3"])
        return

    row = await ensure_user(target.id, target_username)
    new_evo = max(0, row[3] - amount)
    await db_exec("UPDATE users SET evolution_level = ? WHERE user_id = ?", (new_evo, target.id))

    await message.reply(TEXTS["admin_take_evo_4"].format(v0=amount, v1=esc(target_username), v2=new_evo))

@dp.message(F.text.lower().startswith("!дать коин"))
async def admin_give_coin(message: Message):
    if not await is_admin_role_or_above(message):
        return
    await log_admin_action(message)
    match = ADMIN_GIVE_COIN_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_give_coin_1"])
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply(TEXTS["admin_give_coin_2"])
        return

    amount = parse_amount(match.group(1))
    if not amount or amount <= 0:
        await message.reply(TEXTS["admin_give_coin_3"])
        return
    gate_err = await admin_role_gate(message, currency="коин", amount=amount)
    if gate_err:
        await message.reply(gate_err)
        return
    target_username = target.username or target.first_name or "Без имени"

    row = await ensure_user(target.id, target_username)
    new_coins = row[5] + amount
    await db_exec("UPDATE users SET coins = ? WHERE user_id = ?", (new_coins, target.id))

    await message.reply(TEXTS["admin_give_coin_4"].format(v0=amount, v1=esc(target_username), v2=new_coins))

@dp.message(F.text.lower().startswith("!снять коин"))
async def admin_take_coin(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_TAKE_COIN_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_take_coin_1"])
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply(TEXTS["admin_take_coin_2"])
        return
    target_username = target.username or target.first_name or "Без имени"

    if match.group(1) is None:
        await db_exec("UPDATE users SET coins = 0 WHERE user_id = ?", (target.id,))
        await message.reply(TEXTS["admin_take_coin_4"].format(v0="все", v1=esc(target_username), v2=0))
        return

    amount = parse_amount(match.group(1))
    if not amount or amount <= 0:
        await message.reply(TEXTS["admin_take_coin_3"])
        return

    row = await ensure_user(target.id, target_username)
    new_coins = max(0, row[5] - amount)
    await db_exec("UPDATE users SET coins = ? WHERE user_id = ?", (new_coins, target.id))

    await message.reply(TEXTS["admin_take_coin_4"].format(v0=amount, v1=esc(target_username), v2=new_coins))

@dp.message(F.text.lower().startswith("!дать б "))
async def admin_give_boost(message: Message):
    if not await is_admin_role_or_above(message):
        return
    await log_admin_action(message)
    match = ADMIN_GIVE_BOOST_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_give_boost_1"])
        return

    item_key = find_item_by_name(match.group(1), only_passive=False)
    if not item_key:
        await message.reply(TEXTS["admin_give_boost_2"])
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply(TEXTS["admin_give_boost_3"])
        return

    gate_err = await admin_role_gate(message)
    if gate_err:
        await message.reply(gate_err)
        return
    target_username = target.username or target.first_name or "Без имени"
    await ensure_user(target.id, target_username)
    await add_item(target.id, item_key)

    emoji, name, _, _ = ITEMS[item_key]
    await safe_reply(message, TEXTS["admin_give_boost_4"].format(v0=emoji, v1=esc(name), v2=esc(target_username)))

@dp.message(F.text.lower().startswith("!снять б "))
async def admin_take_boost(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_TAKE_BOOST_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_take_boost_1"])
        return

    item_key = find_item_by_name(match.group(1), only_passive=False)
    if not item_key:
        await message.reply(TEXTS["admin_take_boost_2"])
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply(TEXTS["admin_take_boost_3"])
        return

    target_username = target.username or target.first_name or "Без имени"
    await ensure_user(target.id, target_username)
    removed = await remove_item(target.id, item_key)

    emoji, name, _, _ = ITEMS[item_key]
    if removed:
        await safe_reply(message, TEXTS["admin_take_boost_4"].format(v0=emoji, v1=esc(name), v2=esc(target_username)))
    else:
        await message.reply(TEXTS["admin_take_boost_5"].format(v0=esc(target_username), v1=esc(name)))

@dp.message(F.text.lower().startswith("!дать п "))
async def admin_give_passive(message: Message):
    if not await is_admin_role_or_above(message):
        return
    await log_admin_action(message)
    match = ADMIN_GIVE_ITEM_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_give_passive_1"])
        return

    item_key = find_item_by_name(match.group(1), only_passive=True)
    if not item_key:
        await message.reply(TEXTS["admin_give_passive_2"])
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply(TEXTS["admin_give_passive_3"])
        return

    gate_err = await admin_role_gate(message)
    if gate_err:
        await message.reply(gate_err)
        return
    target_username = target.username or target.first_name or "Без имени"
    await ensure_user(target.id, target_username)
    await add_item(target.id, item_key)

    emoji, name, _, _ = ITEMS[item_key]
    await safe_reply(message, TEXTS["admin_give_passive_4"].format(v0=emoji, v1=esc(name), v2=esc(target_username)))

@dp.message(F.text.lower().startswith("!снять п "))
async def admin_take_passive(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_TAKE_ITEM_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_take_passive_1"])
        return

    item_key = find_item_by_name(match.group(1), only_passive=True)
    if not item_key:
        await message.reply(TEXTS["admin_take_passive_2"])
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply(TEXTS["admin_take_passive_3"])
        return

    target_username = target.username or target.first_name or "Без имени"
    await ensure_user(target.id, target_username)
    removed = await remove_item(target.id, item_key)

    emoji, name, _, _ = ITEMS[item_key]
    if removed:
        await safe_reply(message, TEXTS["admin_take_passive_4"].format(v0=emoji, v1=esc(name), v2=esc(target_username)))
    else:
        await message.reply(TEXTS["admin_take_passive_5"].format(v0=esc(target_username), v1=esc(name)))

@dp.message(F.text.lower().startswith("!дать вип"))
async def admin_give_vip(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_GIVE_VIP_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_give_vip_1"])
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply(TEXTS["admin_give_vip_2"])
        return

    days = parse_amount(match.group(1))
    if not days or days <= 0:
        await message.reply(TEXTS["admin_give_vip_3"])
        return
    target_username = target.username or target.first_name or "Без имени"
    row = await ensure_user(target.id, target_username)

    now = int(time.time())
    base = row[12] if row[12] and row[12] > now else now
    new_vip_until = base + days * 86400

    await db_exec("UPDATE users SET vip_until = ? WHERE user_id = ?", (new_vip_until, target.id))
    was_vip_before = is_vip_active(row[12])
    if not was_vip_before:
        await add_item(target.id, "vip_charm")

    await message.reply(TEXTS["admin_give_vip_4"].format(v0=days, v1=esc(target_username)))

@dp.message(F.text.lower().startswith("!снять вип"))
async def admin_take_vip(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_TAKE_VIP_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_take_vip_1"])
        return

    target = await resolve_target(message, bool(match.group(1)))
    if not target:
        await message.reply(TEXTS["admin_take_vip_2"])
        return

    target_username = target.username or target.first_name or "Без имени"
    await ensure_user(target.id, target_username)
    await db_exec("UPDATE users SET vip_until = 0 WHERE user_id = ?", (target.id,))

    await message.reply(TEXTS["admin_take_vip_3"].format(v0=esc(target_username)))

# ==== Команда выдачи титулов — ДОСТУПНА ТОЛЬКО Разработчику (is_developer), даже админы и
# модераторы не могут выдавать титулы себе или другим. ====
TITLE_GIVE_ALIASES = {
    "премиум": ("premium", None),
    "модератор": (None, "moderator"),
    "админ": (None, "admin"),
    "тиктокер": (None, "tiktoker"),
    "ютубер": (None, "youtuber"),
}
# первое значение пары: если это content_role, второе: если это admin_role. "premium" — особый
# случай (пишем в is_premium_title, а не в одну из двух ролевых колонок) — обрабатывается отдельно.

@dp.message(F.text.regexp(ADMIN_GIVE_TITLE_RE))
async def admin_give_title(message: Message):
    if not is_developer(message):
        return
    await log_admin_action(message)
    match = ADMIN_GIVE_TITLE_RE.match(message.text.strip())
    title_word = match.group(1).lower()
    if title_word not in TITLE_GIVE_ALIASES:
        await message.reply(
            "Формат: !дать титул <название> (в ответ на сообщение игрока). "
            "Доступные названия: премиум, модератор, админ, тиктокер, ютубер."
        )
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply("Ответь этой командой на сообщение игрока, либо допиши «себе».")
        return
    target_username = target.username or target.first_name or "Без имени"
    await ensure_user(target.id, target_username)

    if title_word == "премиум":
        await db_exec("UPDATE users SET is_premium_title = 1 WHERE user_id = ?", (target.id,))
        await message.reply(f"Титул «Премиум» выдан игроку {esc(target_username)}.")
        return

    if title_word in ("модератор", "админ"):
        # admin_role взаимоисключающий — выдача одного автоматически стирает другое (см. ТЗ:
        # "админ и модератор не могут быть вместе").
        new_role = "moderator" if title_word == "модератор" else "admin"
        await db_exec("UPDATE users SET admin_role = ? WHERE user_id = ?", (new_role, target.id))
        await message.reply(f"Титул «{TITLE_LABELS[new_role]}» выдан игроку {esc(target_username)} (предыдущая админ-роль, если была, снята).")
        return

    if title_word in ("тиктокер", "ютубер"):
        # content_role взаимоисключающий по той же логике, что и admin_role.
        new_role = "tiktoker" if title_word == "тиктокер" else "youtuber"
        await db_exec("UPDATE users SET content_role = ? WHERE user_id = ?", (new_role, target.id))
        await message.reply(f"Титул «{TITLE_LABELS[new_role]}» выдан игроку {esc(target_username)} (предыдущая контент-роль, если была, снята).")
        return

@dp.message(F.text.regexp(ADMIN_TAKE_TITLE_RE))
async def admin_take_title(message: Message):
    if not is_developer(message):
        return
    await log_admin_action(message)
    match = ADMIN_TAKE_TITLE_RE.match(message.text.strip())
    title_word = match.group(1).lower()
    if title_word not in TITLE_GIVE_ALIASES:
        await message.reply(
            "Формат: !снять титул <название> (в ответ на сообщение игрока). "
            "Доступные названия: премиум, модератор, админ, тиктокер, ютубер."
        )
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply("Ответь этой командой на сообщение игрока, либо допиши «себе».")
        return
    target_username = target.username or target.first_name or "Без имени"
    await ensure_user(target.id, target_username)

    if title_word == "премиум":
        await db_exec("UPDATE users SET is_premium_title = 0 WHERE user_id = ?", (target.id,))
    elif title_word in ("модератор", "админ"):
        await db_exec("UPDATE users SET admin_role = '' WHERE user_id = ?", (target.id,))
    elif title_word in ("тиктокер", "ютубер"):
        await db_exec("UPDATE users SET content_role = '' WHERE user_id = ?", (target.id,))

    await message.reply(f"Титул «{title_word.capitalize()}» снят у игрока {esc(target_username)}.")

@dp.message(F.text.lower().startswith("!сбросить"))
async def admin_reset(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_RESET_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_reset_1"])
        return

    target = await resolve_target(message, bool(match.group(1)))
    if not target:
        await message.reply(TEXTS["admin_reset_2"])
        return

    target_username = target.username or target.first_name or "Без имени"
    await ensure_user(target.id, target_username)

    await db_exec(
        "UPDATE users SET score = 0, evolution_level = 0, evo_hardness_mult = 1.0, coins = 0, active_item = NULL, equipped_items = '', "
        "cases_opened = 0, total_farmed = 0, last_bonus = 0, bonus_streak = 0, vip_until = 0 "
        "WHERE user_id = ?",
        (target.id,),
    )
    await db_exec("DELETE FROM inventory WHERE user_id = ?", (target.id,))

    await message.reply(TEXTS["admin_reset_3"].format(v0=esc(target_username)))

@dp.message(F.text.lower().startswith("!установить ног"))
async def admin_set_legs(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_SET_LEGS_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_set_legs_1"])
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply(TEXTS["admin_set_legs_2"])
        return

    amount = parse_amount(match.group(1))
    if amount is None or amount < 0:
        await message.reply(TEXTS["admin_set_legs_3"])
        return
    target_username = target.username or target.first_name or "Без имени"

    row = await ensure_user(target.id, target_username)
    old_score = row[2]
    await db_exec("UPDATE users SET score = ? WHERE user_id = ?", (amount, target.id))
    await maybe_announce_levelup(message, target_username, old_score, amount, row[3], bool(row[11]), **hardness_kwargs(row))

@dp.message(F.text.lower().startswith("!дать ноги лвл"))
async def admin_give_legs_level(message: Message):
    """Ставит игроку РОВНО указанный уровень ноги (не сырое число очков) — пересчитывает
    нужный score через level_threshold с учётом его эволюции/перерождений/ultra_rebirth.
    Для роли Админ это "инбаланс"-команда — ограничена только общим КД, отдельного числового
    лимита на сам уровень в ТЗ не было (в отличие от "!дать ноги", где лимит на очки есть)."""
    if not await is_admin_role_or_above(message):
        return
    await log_admin_action(message)
    match = ADMIN_GIVE_LEGS_LVL_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_give_legs_lvl_1"])
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply(TEXTS["admin_give_legs_lvl_2"])
        return

    level = int(match.group(1))
    gate_err = await admin_role_gate(message)
    if gate_err:
        await message.reply(gate_err)
        return
    target_username = target.username or target.first_name or "Без имени"

    row = await ensure_user(target.id, target_username)
    evolution_level, rebirth_count = row[3], row[15]
    ultra_rebirth = bool(row[21])
    cap = ULTRA_LEVEL_CAP if ultra_rebirth else ULTRA_REQUIRED_LEG_LEVEL

    if level < 0 or level > cap:
        await message.reply(TEXTS["admin_give_legs_lvl_3"].format(v0=cap))
        return

    old_score = row[2]
    new_score = level_threshold(level, evolution_level, rebirth_count, **hardness_kwargs(row))
    await db_exec("UPDATE users SET score = ? WHERE user_id = ?", (new_score, target.id))
    await maybe_announce_levelup(message, target_username, old_score, new_score, evolution_level, bool(row[11]), rebirth_count, ultra_rebirth, **hardness_kwargs(row))

    await message.reply(TEXTS["admin_give_legs_lvl_4"].format(v0=level, v1=esc(target_username), v2=new_score))

@dp.message(F.text.lower().startswith("!установить эво"))
async def admin_set_evo(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_SET_EVO_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_set_evo_1"])
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply(TEXTS["admin_set_evo_2"])
        return

    amount = parse_amount(match.group(1))
    if amount is None or amount < 0:
        await message.reply(TEXTS["admin_set_evo_3"])
        return
    target_username = target.username or target.first_name or "Без имени"

    row = await ensure_user(target.id, target_username)
    old_evo = row[3]
    await db_exec("UPDATE users SET evolution_level = ?, evo_hardness_mult = 1.0 WHERE user_id = ?", (amount, target.id))

    await message.reply(TEXTS["admin_set_evo_4"].format(v0=esc(target_username), v1=amount, v2=old_evo))

@dp.message(F.text.lower().startswith("!сброс кд"))
async def admin_reset_cd(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_RESET_CD_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_reset_cd_1"])
        return

    target = await resolve_target(message, bool(match.group(1)))
    if not target:
        await message.reply(TEXTS["admin_reset_cd_2"])
        return

    target_username = target.username or target.first_name or "Без имени"
    await ensure_user(target.id, target_username)
    await db_exec("UPDATE users SET last_farm = 0 WHERE user_id = ?", (target.id,))

    await message.reply(TEXTS["admin_reset_cd_3"].format(v0=esc(target_username)))

@dp.message(F.text.lower().startswith("!сброс бонус"))
async def admin_reset_bonus(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_RESET_BONUS_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_reset_bonus_1"])
        return

    target = await resolve_target(message, bool(match.group(1)))
    if not target:
        await message.reply(TEXTS["admin_reset_bonus_2"])
        return

    target_username = target.username or target.first_name or "Без имени"
    await ensure_user(target.id, target_username)
    await db_exec("UPDATE users SET last_bonus = 0 WHERE user_id = ?", (target.id,))

    await message.reply(TEXTS["admin_reset_bonus_3"].format(v0=esc(target_username)))

@dp.message(F.text.lower().startswith("!дать кейс"))
async def admin_give_case(message: Message):
    if not await is_admin_role_or_above(message):
        return
    await log_admin_action(message)
    match = ADMIN_GIVE_CASE_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_give_case_1"])
        return

    case_num = int(match.group(1))
    count = int(match.group(2))
    case = CASES.get(case_num)
    if not case:
        await message.reply(TEXTS["admin_give_case_3"])
        return
    if count < 1 or count > 100:
        await message.reply(TEXTS["admin_give_case_4"])
        return

    target = await resolve_target(message, bool(match.group(3)))
    if not target:
        await message.reply(TEXTS["admin_give_case_2"])
        return

    gate_err = await admin_role_gate(message)
    if gate_err:
        await message.reply(gate_err)
        return
    target_username = target.username or target.first_name or "Без имени"
    await ensure_user(target.id, target_username)

    won = {}
    for _ in range(count):
        item_key = roll_case_item(case_num)
        await add_item(target.id, item_key)
        won[item_key] = won.get(item_key, 0) + 1
    await db_exec("UPDATE users SET cases_opened = cases_opened + ? WHERE user_id = ?", (count, target.id))

    loot_lines = "\n".join(f"● {ITEMS[k][0]} {esc(ITEMS[k][1])} × {qty}" for k, qty in won.items())
    await safe_reply(
        message,
        TEXTS["admin_give_case_5"].format(v0=esc(target_username), v1=esc(case["name"]), v2=count, v3=loot_lines),
    )

@dp.message(F.text.regexp(r"(?i)^!дебаг\s+"))
async def admin_debug(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_DEBUG_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_debug_1"])
        return

    row = await get_user_by_username(match.group(1))
    if not row:
        await message.reply(TEXTS["admin_debug_2"])
        return

    fields = USER_COLUMNS.split(", ")
    dump = "\n".join(f"{name} = {value}" for name, value in zip(fields, row))
    await message.reply(TEXTS["admin_debug_3"].format(v0=esc(row[1]), v1=esc(dump)))

@dp.message(F.text.regexp(r"(?i)^!текст\s+"))
async def admin_show_text(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_SHOW_TEXT_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_show_text_1"])
        return

    key = match.group(1)
    if key not in TEXTS:
        await message.reply(TEXTS["admin_show_text_2"])
        return

    await message.reply(TEXTS["admin_show_text_3"].format(v0=esc(key), v1=esc(TEXTS[key])))

@dp.message(F.text.regexp(r"(?i)^!симулировать эволюция\s+"))
async def admin_simulate_evolution(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_SIMULATE_EVO_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_simulate_evo_1"])
        return

    row = await get_user_by_username(match.group(1))
    if not row:
        await message.reply(TEXTS["admin_simulate_evo_2"])
        return

    username, score, evolution_level = row[1], row[2], row[3]
    rebirth_count = row[15] if len(row) > 15 else 0
    required = level_threshold(EVO_REQUIRED_BASE_LEVEL + evolution_level, evolution_level, rebirth_count, **hardness_kwargs(row))
    verdict = TEXTS["admin_simulate_evo_ok"] if score >= required else TEXTS["admin_simulate_evo_fail"].format(v0=required - score)

    await message.reply(
        TEXTS["admin_simulate_evo_3"].format(v0=esc(username), v1=score, v2=required, v3=evolution_level, v4=verdict)
    )

@dp.message(F.text.lower() == "!стата")
async def admin_stats(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)

    row = await db_query_one(
        "SELECT COUNT(*), COALESCE(SUM(score),0), COALESCE(SUM(coins),0), COALESCE(SUM(rebirth_points),0), "
        "COALESCE(SUM(cases_opened),0), SUM(CASE WHEN vip_until > ? THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN top_banned = 1 THEN 1 ELSE 0 END) FROM users WHERE game_banned = 0 OR game_banned IS NULL",
        (int(time.time()),),
    )
    players, total_score, total_coins, total_rebirth, total_cases, vip_count, banned_count = row

    await message.reply(
        TEXTS["admin_stats_1"].format(
            v0=players, v1=total_score, v2=total_coins, v3=total_rebirth,
            v4=total_cases, v5=vip_count or 0, v6=banned_count or 0,
        )
    )

@dp.message(F.text.lower() == "стата")
async def vip_stats(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    row = await ensure_user(user_id, username)
    vip_until = row[12]

    if not is_vip_active(vip_until):
        await message.reply(TEXTS["vip_stats_not_vip_1"])
        return

    stats_row = await db_query_one(
        "SELECT COUNT(*), COALESCE(SUM(score),0), COALESCE(SUM(coins),0), COALESCE(SUM(rebirth_points),0), "
        "COALESCE(SUM(cases_opened),0), SUM(CASE WHEN vip_until > ? THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN top_banned = 1 THEN 1 ELSE 0 END) FROM users WHERE game_banned = 0 OR game_banned IS NULL",
        (int(time.time()),),
    )
    players, total_score, total_coins, total_rebirth, total_cases, vip_count, banned_count = stats_row

    await message.reply(
        TEXTS["admin_stats_1"].format(
            v0=players, v1=total_score, v2=total_coins, v3=total_rebirth,
            v4=total_cases, v5=vip_count or 0, v6=banned_count or 0,
        )
    )

@dp.message(F.text.lower() == "!рестарт")
async def admin_restart(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    await message.reply(TEXTS["admin_restart_1"])
    await bot.session.close()
    os._exit(0)

@dp.message(F.text.lower() == "!снять бейдж всем")
async def admin_unshow_all_badges(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    await db_exec("UPDATE users SET shown_badges = ''")
    await message.reply(TEXTS["admin_unshow_all_badges_1"])

@dp.message(F.text.regexp(r"(?i)^!ивент\s+х\d"))
async def admin_event_custom(message: Message):
    if not await is_moderator_or_above(message):
        return

    row = await ensure_user(message.from_user.id, message.from_user.username or message.from_user.first_name or "Без имени")
    admin_role = row[42] if len(row) > 42 else ""
    is_developer_user = is_developer(message)
    is_moderator_only = (not is_developer_user) and admin_role == "moderator"
    is_admin_role_user = (not is_developer_user) and admin_role == "admin"

    await log_admin_action(message)
    match = ADMIN_EVENT_CUSTOM_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_event_custom_1"])
        return

    mult = float(match.group(1))
    minutes = int(match.group(2))
    if mult <= 0 or minutes <= 0:
        await message.reply(TEXTS["admin_event_custom_2"])
        return

    if is_moderator_only:
        # Ограничения роли Модератор: макс x5 на 30 минут, КД на использование 4 часа.
        MODERATOR_EVENT_MAX_MULT = 5
        MODERATOR_EVENT_MAX_MINUTES = 30
        MODERATOR_EVENT_COOLDOWN = 4 * 3600
        now = int(time.time())
        last_used = row[47] if len(row) > 47 else 0
        wait_left = MODERATOR_EVENT_COOLDOWN - (now - last_used)
        if wait_left > 0:
            wh, wrem = divmod(wait_left, 3600)
            wm = wrem // 60
            await message.reply(f"КД на «!ивент» для модератора: подожди ещё {wh} ч {wm} мин.")
            return
        if mult > MODERATOR_EVENT_MAX_MULT:
            await message.reply(f"Модератору доступен буст не выше x{MODERATOR_EVENT_MAX_MULT}.")
            return
        if minutes > MODERATOR_EVENT_MAX_MINUTES:
            await message.reply(f"Модератору доступна длительность ивента не больше {MODERATOR_EVENT_MAX_MINUTES} минут.")
            return
        await db_exec("UPDATE users SET moderator_event_last = ? WHERE user_id = ?", (now, message.from_user.id))
    elif is_admin_role_user:
        # Ограничения роли Админ: макс x15, макс 3 часа (180 минут), общий КД на ивент — 2 часа
        # (отдельный от общего КД !дать-команд — тот КД не трогаем здесь).
        ADMIN_EVENT_MAX_MULT = 15
        ADMIN_EVENT_MAX_MINUTES = 180
        ADMIN_EVENT_COOLDOWN = 2 * 3600
        now = int(time.time())
        last_used = row[47] if len(row) > 47 else 0
        wait_left = ADMIN_EVENT_COOLDOWN - (now - last_used)
        if wait_left > 0:
            wh, wrem = divmod(wait_left, 3600)
            wm = wrem // 60
            await message.reply(f"КД на «!ивент» для админа: подожди ещё {wh} ч {wm} мин.")
            return
        if mult > ADMIN_EVENT_MAX_MULT:
            await message.reply(f"Админу доступен буст не выше x{ADMIN_EVENT_MAX_MULT}.")
            return
        if minutes > ADMIN_EVENT_MAX_MINUTES:
            await message.reply(f"Админу доступна длительность ивента не больше {ADMIN_EVENT_MAX_MINUTES} минут (3 часа).")
            return
        await db_exec("UPDATE users SET moderator_event_last = ? WHERE user_id = ?", (now, message.from_user.id))

    until = int(time.time()) + minutes * 60
    for key, value in (("event_active", "1"), ("event_multiplier", str(mult)), ("event_until", str(until))):
        await db_exec(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
    _invalidate_event_state_cache()

    await message.reply(TEXTS["admin_event_custom_3"].format(v0=mult, v1=minutes))

@dp.message(F.text.lower().startswith("!установить очкп"))
async def admin_set_rebirth(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_SET_REBIRTH_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_set_rebirth_1"])
        return

    target = await resolve_target(message, bool(match.group(2)))
    if not target:
        await message.reply(TEXTS["admin_set_rebirth_2"])
        return

    amount = parse_amount(match.group(1))
    if amount is None or amount < 0:
        await message.reply(TEXTS["admin_set_rebirth_3"])
        return
    target_username = target.username or target.first_name or "Без имени"

    row = await ensure_user(target.id, target_username)
    old_rp = row[14]
    await db_exec("UPDATE users SET rebirth_points = ? WHERE user_id = ?", (amount, target.id))

    await message.reply(TEXTS["admin_set_rebirth_4"].format(v0=esc(target_username), v1=amount, v2=old_rp))

@dp.message(F.text.regexp(r"(?i)^!обнулить экономику\s+"))
async def admin_wipe_economy(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_WIPE_ECONOMY_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_wipe_economy_1"])
        return

    row = await get_user_by_username(match.group(1))
    if not row:
        await message.reply(TEXTS["admin_wipe_economy_2"])
        return

    await db_exec(
        "UPDATE users SET score = 0, coins = 0, rebirth_points = 0 WHERE user_id = ?",
        (row[0],),
    )
    await message.reply(TEXTS["admin_wipe_economy_3"].format(v0=esc(row[1])))

@dp.message(F.text.regexp(r"(?i)^!мультипликатор ферма\s+"))
async def admin_personal_boost(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_PERSONAL_BOOST_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_personal_boost_1"])
        return

    target = await resolve_target(message, bool(match.group(3)))
    if not target:
        await message.reply(TEXTS["admin_personal_boost_2"])
        return

    mult = float(match.group(1))
    minutes = int(match.group(2))
    if mult <= 0 or minutes <= 0:
        await message.reply(TEXTS["admin_personal_boost_3"])
        return
    target_username = target.username or target.first_name or "Без имени"
    await ensure_user(target.id, target_username)

    until = int(time.time()) + minutes * 60
    await db_exec(
        "INSERT INTO personal_boosts (user_id, multiplier, until) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET multiplier = excluded.multiplier, until = excluded.until",
        (target.id, mult, until),
    )

    await message.reply(TEXTS["admin_personal_boost_4"].format(v0=esc(target_username), v1=mult, v2=minutes))

@dp.message(F.text.regexp(r"(?i)^!дать предмет\s+"))
async def admin_give_item(message: Message):
    if not await is_admin_role_or_above(message):
        return
    await log_admin_action(message)
    match = ADMIN_GIVE_ITEM_KEY_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_give_item_1"])
        return

    item_key = match.group(1)
    count = int(match.group(2))
    if item_key not in ITEMS:
        await message.reply(TEXTS["admin_give_item_3"])
        return
    if count < 1 or count > 1000:
        await message.reply(TEXTS["admin_give_item_4"])
        return

    target = await resolve_target(message, bool(match.group(3)))
    if not target:
        await message.reply(TEXTS["admin_give_item_2"])
        return

    gate_err = await admin_role_gate(message)
    if gate_err:
        await message.reply(gate_err)
        return
    target_username = target.username or target.first_name or "Без имени"
    await ensure_user(target.id, target_username)
    await add_item(target.id, item_key, count)

    emoji, name, _, _ = ITEMS[item_key]
    await message.reply(TEXTS["admin_give_item_5"].format(v0=esc(target_username), v1=emoji, v2=esc(name), v3=count))

@dp.message(F.text.regexp(r"(?i)^!дать ключ\s+"))
async def admin_give_key(message: Message):
    # ТЗ: "блок к выдаче через ключ" — эта команда для роли Админ полностью недоступна
    # (в отличие от !дать предмет, которая доступна с общим КД); только Разработчик.
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_GIVE_KEY_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_give_key_1"])
        return

    item_key = match.group(1)
    count = int(match.group(2))
    if item_key not in ITEMS:
        await message.reply(TEXTS["admin_give_key_3"])
        return
    if count < 1 or count > 1000:
        await message.reply(TEXTS["admin_give_key_4"])
        return

    target = await resolve_target(message, bool(match.group(3)))
    if not target:
        await message.reply(TEXTS["admin_give_key_2"])
        return

    target_username = target.username or target.first_name or "Без имени"
    await ensure_user(target.id, target_username)
    await add_item(target.id, item_key, count)

    emoji, name, _, _ = ITEMS[item_key]
    await message.reply(TEXTS["admin_give_key_5"].format(v0=esc(target_username), v1=emoji, v2=esc(name), v3=count))

@dp.message(F.text.regexp(r"(?i)^!очистить инвентарь\s+"))
async def admin_clear_inventory(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_CLEAR_INVENTORY_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_clear_inventory_1"])
        return

    row = await get_user_by_username(match.group(1))
    if not row:
        await message.reply(TEXTS["admin_clear_inventory_2"])
        return

    await db_exec("DELETE FROM inventory WHERE user_id = ?", (row[0],))
    await db_exec("UPDATE users SET equipped_items = '' WHERE user_id = ?", (row[0],))
    await message.reply(TEXTS["admin_clear_inventory_3"].format(v0=esc(row[1])))

@dp.message(F.text.regexp(r"(?i)^!дать апгрейд\s+"))
async def admin_set_upgrade(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_SET_UPGRADE_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_set_upgrade_1"])
        return

    upgrade_key = match.group(1)
    level = int(match.group(2))
    if upgrade_key not in UPGRADES:
        await message.reply(TEXTS["admin_set_upgrade_3"])
        return
    max_level = effective_max_level(upgrade_key, UPGRADER_LEVEL_MAX)
    if level < 0 or level > max_level:
        await message.reply(TEXTS["admin_set_upgrade_4"].format(v0=max_level))
        return

    target = await resolve_target(message, bool(match.group(3)))
    if not target:
        await message.reply(TEXTS["admin_set_upgrade_2"])
        return

    target_username = target.username or target.first_name or "Без имени"
    row = await ensure_user(target.id, target_username)
    upgrades = parse_upgrades(row[16])
    if level > 0:
        upgrades[upgrade_key] = level
    else:
        upgrades.pop(upgrade_key, None)
    await db_exec("UPDATE users SET upgrades = ? WHERE user_id = ?", (format_upgrades(upgrades), target.id))

    await message.reply(
        TEXTS["admin_set_upgrade_5"].format(v0=esc(target_username), v1=esc(UPGRADES[upgrade_key]["name"]), v2=level)
    )

@dp.message(F.text.lower().startswith("!вип навсегда"))
async def admin_vip_forever(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_VIP_FOREVER_RE.match(message.text.strip())
    target = await resolve_target(message, bool(match.group(1))) if match else None
    if not target:
        await message.reply(TEXTS["admin_vip_forever_1"])
        return

    target_username = target.username or target.first_name or "Без имени"
    row = await ensure_user(target.id, target_username)
    new_vip_until = int(time.time()) + VIP_FOREVER_SECONDS
    await db_exec("UPDATE users SET vip_until = ? WHERE user_id = ?", (new_vip_until, target.id))
    if not is_vip_active(row[12]):
        await add_item(target.id, "vip_charm")

    await message.reply(TEXTS["admin_vip_forever_2"].format(v0=esc(target_username)))

@dp.message(F.text.lower().startswith("!ультра навсегда"))
async def admin_ultra_rebirth_forever(message: Message):
    """Owner-инструмент для тестирования: выдаёт статус Ультра перерождения напрямую,
    БЕЗ сброса прогресса игрока (в отличие от реальной активации через игровую команду).
    Полезно для проверки пост-ультра контента ("тест ноги", буста) без реального гринда."""
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_ULTRA_REBIRTH_RE.match(message.text.strip())
    target = await resolve_target(message, bool(match.group(1))) if match else None
    if not target:
        await message.reply(TEXTS["admin_ultra_rebirth_1"])
        return

    target_username = target.username or target.first_name or "Без имени"
    await ensure_user(target.id, target_username)
    await db_exec("UPDATE users SET ultra_rebirth = 1 WHERE user_id = ?", (target.id,))

    await message.reply(TEXTS["admin_ultra_rebirth_2"].format(v0=esc(target_username)))

@dp.message(F.text.regexp(r"(?i)^!сброс ник\s+"))
async def admin_reset_nick(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = ADMIN_RESET_NICK_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_reset_nick_1"])
        return

    row = await get_user_by_username(match.group(1))
    if not row:
        await message.reply(TEXTS["admin_reset_nick_2"])
        return

    old_nick = row[19] if len(row) > 19 else None
    if not old_nick:
        await message.reply(TEXTS["admin_reset_nick_3"])
        return

    await db_exec("UPDATE users SET nickname = NULL WHERE user_id = ?", (row[0],))
    await message.reply(TEXTS["admin_reset_nick_4"].format(v0=esc(row[1]), v1=esc(old_nick)))

@dp.message(F.text.lower() == "!список вип")
async def admin_list_vip(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    now = int(time.time())
    rows = await db_query(
        "SELECT username, nickname, vip_until FROM users WHERE vip_until > ? ORDER BY vip_until DESC LIMIT 30",
        (now,),
    )
    if not rows:
        await message.reply(TEXTS["admin_list_vip_1"])
        return

    lines = []
    for username, nickname, vip_until in rows:
        left = vip_until - now
        if left > 50 * 365 * 86400:
            left_text = "навсегда"
        else:
            days = left // 86400
            left_text = f"{days} дн."
        lines.append(f"● {esc(display_name(username, nickname))} — {left_text}")

    await message.reply(TEXTS["admin_list_vip_2"].format(v0=len(rows), v1="\n".join(lines)))

@dp.message(F.text.lower() == "!список ников")
async def admin_list_nicknames(message: Message):
    if not await is_moderator_or_above(message):
        return
    await log_admin_action(message)
    rows = await db_query(
        "SELECT username, nickname FROM users WHERE nickname IS NOT NULL AND nickname != '' LIMIT 50"
    )
    if not rows:
        await message.reply(TEXTS["admin_list_nicknames_1"])
        return

    lines = [f"● {esc(nickname)} (@{esc(username)})" for username, nickname in rows]
    await message.reply(TEXTS["admin_list_nicknames_2"].format(v0=len(rows), v1="\n".join(lines)))

@dp.message(F.text.regexp(r"(?i)^!найти\s+"))
async def admin_find(message: Message):
    if not await is_moderator_or_above(message):
        return
    await log_admin_action(message)
    match = ADMIN_FIND_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["admin_find_1"])
        return

    row = await get_user_by_username(match.group(1))
    if not row:
        await message.reply(TEXTS["admin_find_2"])
        return

    chat_rows = await db_query("SELECT chat_id FROM chat_members WHERE user_id = ? LIMIT 20", (row[0],))
    if not chat_rows:
        await message.reply(TEXTS["admin_find_4"])
        return

    lines = []
    for (chat_id,) in chat_rows:
        try:
            chat = await bot.get_chat(chat_id)
            title = chat.title or chat.full_name or str(chat_id)
        except Exception:
            title = f"chat_id {chat_id} (недоступен)"
        lines.append(f"● {esc(title)}")

    await message.reply(TEXTS["admin_find_3"].format(v0=esc(row[1]), v1=len(chat_rows), v2="\n".join(lines)))

@dp.message(F.text.lower().startswith("!дать всё"))
async def admin_give_all(message: Message):
    """!дать всё [себе] — выдаёт целевому игроку все существующие предметы, бустеры
    (все ключи ITEMS, без исключений) и все зелья (все ключи POTIONS) по 1 штуке каждого.
    Полезно для тестирования — например прогона «помощь бустер/предмет/зелье» по реальному
    инвентарю. Для роли Админ это "инбаланс"-команда — ограничена только общим КД (ТЗ:
    "другие очень инбаланс команды надо ограничить хотя бы КД"), числового лимита тут нет."""
    if not await is_admin_role_or_above(message):
        return
    await log_admin_action(message)
    match = ADMIN_GIVE_ALL_RE.match(message.text.strip())
    target = await resolve_target(message, bool(match.group(1))) if match else None
    if not target:
        await message.reply(TEXTS["admin_give_all_1"])
        return

    gate_err = await admin_role_gate(message)
    if gate_err:
        await message.reply(gate_err)
        return
    target_username = target.username or target.first_name or "Без имени"
    row = await ensure_user(target.id, target_username)

    for item_key in ITEMS:
        await add_item(target.id, item_key, 1)

    stock = parse_potion_stock(row[26])
    for potion_key in POTIONS:
        stock[potion_key] = stock.get(potion_key, 0) + 1
    await db_exec("UPDATE users SET potion_stock = ? WHERE user_id = ?", (format_potion_stock(stock), target.id))

    await safe_reply(message, TEXTS["admin_give_all_2"].format(v0=esc(target_username), v1=len(ITEMS), v2=len(POTIONS)))

@dp.message(F.text.lower() == "!смс выкл всем")
async def admin_levelup_notify_off_all(message: Message):
    """!смс выкл всем — массово отключает показ уведомления о новом уровне (levelup_notify)
    у ВСЕХ игроков разом, одним UPDATE без WHERE (тот же паттерн, что chronos_orb_boost_loop)."""
    if not is_admin(message):
        return
    await log_admin_action(message)

    count_row = await db_query_one("SELECT COUNT(*) FROM users")
    total = count_row[0] if count_row else 0

    await db_exec("UPDATE users SET levelup_notify = 0")

    await message.reply(TEXTS["admin_levelup_notify_off_all_1"].format(v0=total))

@dp.message(F.text.lower() == "!игроки")
async def admin_list_players(message: Message):
    """!игроки — показ всех игроков (username/ник + основные показатели)."""
    if not is_admin(message):
        return
    await log_admin_action(message)
    rows = await db_query(
        "SELECT username, nickname, score, evolution_level FROM users "
        "WHERE (game_banned IS NULL OR game_banned = 0) "
        "ORDER BY evolution_level DESC, score DESC LIMIT 100"
    )
    if not rows:
        await message.reply(TEXTS["admin_players_1"])
        return

    lines = [
        f"● {esc(display_name(username, nickname))} — нога {score}, эво {evolution_level}"
        for username, nickname, score, evolution_level in rows
    ]
    await message.reply(TEXTS["admin_players_2"].format(v0=len(rows), v1="\n".join(lines)))

BAN_CHAT_RE = re.compile(r'^!бан чат\s+"([^"]+)"$', re.IGNORECASE)

@dp.message(F.text.regexp(r'(?i)^!бан чат\s+"[^"]+"$'))
async def cmd_ban_chat(message: Message):
    """!бан чат "префикс" — простой ПРЕФИКСНЫЙ поиск (не подстрока) по названиям
    всех чатов, где бот отметился (chat_members), регистронезависимо: 'ро' находит
    'Ронал Дом', но не 'Микро Ронал'. Если совпало несколько чатов (например,
    спам-копии 'MGG', 'MGG1', 'MGG2') — банятся ВСЕ совпавшие, как и просил
    пользователь. Для каждого найденного чата: (1) game_banned всем его участникам
    из chat_members, (2) chat_id уходит в чёрный список banned_chats/_banned_chat_ids
    (ChatBanMiddleware дальше не пустит туда бота вообще), (3) бот пытается сам
    выйти из чата (bot.leave_chat) — если это не выйдет (бота уже нет там, или API
    отказал), бан всё равно применяется, просто без выхода."""
    if not is_admin(message):
        return
    await log_admin_action(message)
    match = BAN_CHAT_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["cmd_ban_chat_1"])
        return
    query = match.group(1).strip().lower()
    if not query:
        await message.reply(TEXTS["cmd_ban_chat_1"])
        return

    chat_ids = await db_query("SELECT DISTINCT chat_id FROM chat_members")
    matched = []
    for (chat_id,) in chat_ids:
        if chat_id in _banned_chat_ids:
            continue
        try:
            chat = await bot.get_chat(chat_id)
            title = chat.title or chat.full_name or str(chat_id)
        except Exception:
            continue
        if title.lower().startswith(query):
            matched.append((chat_id, title))

    if not matched:
        await message.reply(TEXTS["cmd_ban_chat_2"].format(v0=esc(match.group(1))))
        return

    now = int(time.time())
    banned_by = message.from_user.username or str(message.from_user.id)
    total_users_banned = 0
    left_count = 0

    for chat_id, title in matched:
        member_rows = await db_query("SELECT user_id FROM chat_members WHERE chat_id = ?", (chat_id,))
        for (member_id,) in member_rows:
            if member_id == ADMIN_USER_ID or member_id in _game_banned_ids:
                continue
            await _apply_game_ban(member_id)
            total_users_banned += 1

        await db_exec(
            "INSERT OR REPLACE INTO banned_chats (chat_id, title, banned_by, banned_at) VALUES (?, ?, ?, ?)",
            (chat_id, title, banned_by, now),
        )
        _banned_chat_ids.add(chat_id)

        try:
            await bot.leave_chat(chat_id)
            left_count += 1
        except Exception:
            pass

    chat_list_text = "\n".join(f"● {esc(title)}" for _, title in matched)
    await message.reply(TEXTS["cmd_ban_chat_3"].format(
        v0=len(matched), v1=chat_list_text, v2=total_users_banned, v3=left_count,
    ))

@dp.message(F.text.lower() == "!список чат")
async def admin_list_chats(message: Message):
    """Список всех чатов, где бот отметился (из chat_members — Telegram Bot API не даёт
    метода 'дай все чаты бота' напрямую). Титул подтягивается свежим через bot.get_chat();
    если чат недоступен (бота уже выгнали), запись пропускается, а не показывается мёртвой
    строкой — так список честно отражает чаты, где бот РЕАЛЬНО сейчас состоит."""
    if not await is_moderator_or_above(message):
        return
    await log_admin_action(message)

    chat_ids = await db_query("SELECT DISTINCT chat_id FROM chat_members")

    lines = []
    for (chat_id,) in chat_ids:
        try:
            chat = await bot.get_chat(chat_id)
            title = chat.title or chat.full_name or str(chat_id)
        except Exception:
            continue
        lines.append(f"● {esc(title)}")

    if not lines:
        await message.reply(TEXTS["admin_list_chats_1"])
        return

    await message.reply(TEXTS["admin_list_chats_2"].format(v0=len(lines), v1="\n".join(lines)))

@dp.message(F.text.regexp(r'(?i)^!промокод создать бейдж\s+'))
async def admin_promo_create_badge(message: Message):
    """Короткий синтаксис для выдачи бейджа промокодом (см. PROMO_BADGES):
    !промокод создать бейдж "название_бейджа" "название_промокода".
    Зарегистрирован раньше admin_promo_create и матчится первым — aiogram
    останавливается на первом сработавшем хендлере для одного сообщения."""
    if not await is_admin_role_or_above(message):
        return
    await log_admin_action(message)
    match = PROMO_CREATE_BADGE_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["promo_create_badge_1"])
        return

    badge_name_raw, code_raw = match.groups()
    code = code_raw.strip()

    badge_key = find_promo_badge_key(badge_name_raw)
    if not badge_key:
        await message.reply(TEXTS["promo_create_badge_2"].format(v0=esc(badge_name_raw)))
        return

    gate_err = await admin_role_gate(message)
    if gate_err:
        await message.reply(gate_err)
        return
    existing = await db_query_one("SELECT code FROM promocodes WHERE code = ?", (code,))
    if existing:
        await message.reply(TEXTS["promo_create_badge_3"].format(v0=esc(code)))
        return

    admin_username = message.from_user.username or message.from_user.first_name or "admin"
    await db_exec(
        "INSERT INTO promocodes (code, reward_type, reward_key, amount, activations_left, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (code, "badge", badge_key, 1, 1, admin_username, int(time.time())),
    )

    emoji, name = PROMO_BADGES[badge_key]
    await message.reply(TEXTS["promo_create_badge_4"].format(v0=esc(code), v1=emoji, v2=esc(name)))

@dp.message(F.text.regexp(r'(?i)^!промокод создать\s+(?!бейдж\s)'))
async def admin_promo_create(message: Message):
    if not await is_admin_role_or_above(message):
        return
    await log_admin_action(message)
    match = PROMO_CREATE_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["promo_create_1"])
        return

    type_raw, amount_raw, activations_raw, code_raw = match.groups()
    code = code_raw.strip()

    parsed_type = parse_promo_type(type_raw)
    if not parsed_type:
        await message.reply(TEXTS["promo_create_2"].format(v0=esc(type_raw)))
        return
    reward_type, reward_key = parsed_type

    amount = parse_amount(amount_raw)
    if not amount or amount <= 0:
        await message.reply(TEXTS["promo_create_3"])
        return

    activations = parse_amount(activations_raw)
    if not activations or activations <= 0:
        await message.reply(TEXTS["promo_create_4"])
        return

    # Промокод может быть активирован МНОГО раз (activations раз) — суммарная выдача может
    # оказаться в activations раз больше amount, поэтому лимит для роли Админ проверяем на
    # amount * activations (худший случай, если все активации будут использованы).
    limit_key = PROMO_TYPE_TO_ADMIN_LIMIT_KEY.get(reward_type)
    gate_err = await admin_role_gate(message, currency=limit_key, amount=amount * activations if limit_key else None)
    if gate_err:
        await message.reply(gate_err)
        return

    existing = await db_query_one("SELECT code FROM promocodes WHERE code = ?", (code,))
    if existing:
        await message.reply(TEXTS["promo_create_5"].format(v0=esc(code)))
        return

    admin_username = message.from_user.username or message.from_user.first_name or "admin"
    await db_exec(
        "INSERT INTO promocodes (code, reward_type, reward_key, amount, activations_left, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (code, reward_type, reward_key, amount, activations, admin_username, int(time.time())),
    )

    if reward_type == "item":
        emoji, name, _, _ = ITEMS[reward_key]
        reward_label = f"{emoji} {esc(name)}"
    else:
        reward_label = PROMO_TYPE_LABEL[reward_type]

    await message.reply(TEXTS["promo_create_6"].format(v0=esc(code), v1=reward_label, v2=amount, v3=activations))

@dp.message(F.text.regexp(r'(?i)^!промокод удалить\s+'))
async def admin_promo_delete(message: Message):
    if not await is_admin_role_or_above(message):
        return
    await log_admin_action(message)
    match = PROMO_DELETE_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["promo_delete_1"])
        return

    code = match.group(1).strip()
    existing = await db_query_one("SELECT code FROM promocodes WHERE code = ?", (code,))
    if not existing:
        await message.reply(TEXTS["promo_delete_2"].format(v0=esc(code)))
        return

    await db_exec("DELETE FROM promocodes WHERE code = ?", (code,))
    await db_exec("DELETE FROM promocode_uses WHERE code = ?", (code,))
    await message.reply(TEXTS["promo_delete_3"].format(v0=esc(code)))

@dp.message(F.text.lower() == "!промокод список")
async def admin_promo_list(message: Message):
    if not await is_admin_role_or_above(message):
        return
    await log_admin_action(message)
    rows = await db_query(
        "SELECT code, reward_type, reward_key, amount, activations_left FROM promocodes ORDER BY created_at DESC LIMIT 50"
    )
    if not rows:
        await message.reply(TEXTS["promo_list_1"])
        return

    lines = []
    for code, reward_type, reward_key, amount, activations_left in rows:
        if reward_type == "item" and reward_key in ITEMS:
            emoji, name, _, _ = ITEMS[reward_key]
            reward_label = f"{emoji} {esc(name)}"
        elif reward_type == "badge" and reward_key in PROMO_BADGES:
            emoji, name = PROMO_BADGES[reward_key]
            reward_label = f"{emoji} бейдж «{esc(name)}»"
        else:
            reward_label = PROMO_TYPE_LABEL.get(reward_type, esc(reward_type))
        lines.append(f"● «{esc(code)}» — {reward_label} × {amount} (осталось активаций: {activations_left})")

    await message.reply(TEXTS["promo_list_2"].format(v0=len(rows), v1="\n".join(lines)))

@dp.message(F.text.regexp(r'(?i)^(?:промокод|промо)\s+\S+$'))
async def redeem_promo(message: Message):
    match = PROMO_REDEEM_RE.match(message.text.strip())
    if not match:
        await message.reply(TEXTS["promo_redeem_1"])
        return

    code = match.group(1).strip()
    promo = await db_query_one(
        "SELECT reward_type, reward_key, amount, activations_left FROM promocodes WHERE code = ?", (code,)
    )
    if not promo:
        await message.reply(TEXTS["promo_redeem_2"])
        return

    reward_type, reward_key, amount, activations_left = promo
    if activations_left <= 0:
        await message.reply(TEXTS["promo_redeem_3"].format(v0=esc(code)))
        return

    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Без имени"
    already_used = await db_query_one(
        "SELECT 1 FROM promocode_uses WHERE user_id = ? AND code = ?", (user_id, code)
    )
    if already_used:
        await message.reply(TEXTS["promo_redeem_4"])
        return

    await ensure_user(user_id, username)

    await db_exec(
        "UPDATE promocodes SET activations_left = activations_left - 1 "
        "WHERE code = ? AND activations_left > 0",
        (code,),
    )
    check = await db_query_one("SELECT activations_left FROM promocodes WHERE code = ?", (code,))
    if check is None:
        await message.reply(TEXTS["promo_redeem_2"])
        return
    if check[0] < activations_left:
        pass
    else:
        await message.reply(TEXTS["promo_redeem_3"].format(v0=esc(code)))
        return

    await db_exec(
        "INSERT INTO promocode_uses (user_id, code, used_at) VALUES (?, ?, ?)",
        (user_id, code, int(time.time())),
    )
    reward_label = await apply_promo_reward(user_id, reward_type, reward_key, amount)
    await message.reply(TEXTS["promo_redeem_5"].format(v0=esc(code), v1=reward_label))

@dp.message(F.text.lower() == "!логи")
async def admin_logs(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    rows = await db_query("SELECT ts, admin_username, command FROM audit_log ORDER BY id DESC LIMIT 20")
    if not rows:
        await message.reply(TEXTS["admin_logs_1"])
        return

    lines = []
    for ts, admin_username, command in rows:
        dt = datetime.fromtimestamp(ts).strftime("%d.%m %H:%M")
        lines.append(f"● [{dt}] @{esc(admin_username)}: {esc(command)}")

    await message.reply(TEXTS["admin_logs_2"].format(v0=len(rows), v1="\n".join(lines)))

@dp.message(F.text.lower().startswith("!топ спам"))
async def admin_top_spam(message: Message):
    """!топ спам        -> топ-20 игроков по числу команд за последний час
    !топ спам 30        -> тот же топ, но за последние 30 минут

    Источник — player_action_log (пишется в ThrottleMiddleware ДО rate-limit,
    см. _log_player_action), так что здесь видно и то, что троттлинг заглушил.
    Для каждого игрока также берём минимальный интервал между двумя ЕГО
    последовательными командами за то же окно — человек физически не может
    слать команды каждые доли секунды подолгу, поэтому маленький минимальный
    интервал при большом числе команд — сигнал на бота/скрипт, а не флуд руками.
    """
    if not await is_moderator_or_above(message):
        return
    await log_admin_action(message)

    parts = message.text.strip().split(maxsplit=2)
    minutes = 60
    if len(parts) > 2:
        try:
            minutes = max(1, int(parts[2]))
        except ValueError:
            minutes = 60

    since = int(time.time()) - minutes * 60
    rows = await db_query(
        "SELECT user_id, username, ts FROM player_action_log WHERE ts >= ? ORDER BY user_id, ts",
        (since,),
    )
    if not rows:
        await message.reply(TEXTS["admin_top_spam_1"])
        return

    per_user = {}
    for user_id, username, ts in rows:
        entry = per_user.setdefault(user_id, {"username": username, "count": 0, "min_gap": None, "last_ts": None})
        entry["username"] = username
        entry["count"] += 1
        if entry["last_ts"] is not None:
            gap = ts - entry["last_ts"]
            if entry["min_gap"] is None or gap < entry["min_gap"]:
                entry["min_gap"] = gap
        entry["last_ts"] = ts

    ranked = sorted(per_user.items(), key=lambda kv: kv[1]["count"], reverse=True)[:20]

    leg_by_user = {}
    if ranked:
        ids = [user_id for user_id, _ in ranked]
        placeholders = ",".join("?" for _ in ids)
        leg_rows = await db_query(
            f"SELECT user_id, score, evolution_level, rebirth_count, ultra_rebirth, evo_hardness_mult, rebirth_hardness_mult "
            f"FROM users WHERE user_id IN ({placeholders})",
            tuple(ids),
        )
        for uid, score, evo, rebirth_count, ultra, evo_mult, rebirth_mult in leg_rows:
            level = get_level_index(score or 0, evo or 0, rebirth_count or 0, bool(ultra), evo_mult or 1.0, rebirth_mult or 1.0)
            emoji, name, _ = get_level_visual(level)
            leg_by_user[uid] = f"{emoji} ур.{level}" + (f" ({name})" if name else "")

    lines = []
    for user_id, info in ranked:
        gap = info["min_gap"]
        suspicious = gap is not None and gap <= PLAYER_LOG_MIN_INTERVAL + 1
        marker = " ⚠️ подозрение на бота" if suspicious else ""
        gap_text = f"{gap}с" if gap is not None else "—"
        leg_text = leg_by_user.get(user_id, "—")
        lines.append(
            f"● @{esc(info['username'])} (id {user_id}), {leg_text}: "
            f"{info['count']} команд, мин. интервал {gap_text}{marker}"
        )

    await message.reply(TEXTS["admin_top_spam_2"].format(v0=minutes, v1=len(ranked), v2="\n".join(lines)))

@dp.message(F.text.lower() == "!логи вся")
async def admin_logs_all(message: Message):
    """!логи вся — вся история audit_log без ограничения в 20 записей.
    Telegram-сообщение ограничено ~4096 символами, поэтому шлём частями."""
    if not is_admin(message):
        return
    await log_admin_action(message)
    rows = await db_query("SELECT ts, admin_username, command FROM audit_log ORDER BY id DESC")
    if not rows:
        await message.reply(TEXTS["admin_logs_all_1"])
        return

    lines = []
    for ts, admin_username, command in rows:
        dt = datetime.fromtimestamp(ts).strftime("%d.%m %H:%M")
        lines.append(f"● [{dt}] @{esc(admin_username)}: {esc(command)}")

    total = len(rows)
    header = TEXTS["admin_logs_all_2"].format(v0=total, v1="")
    chunk_limit = 3800
    chunk_lines = []
    chunk_len = len(header)
    chunks = []
    for line in lines:
        if chunk_len + len(line) + 1 > chunk_limit and chunk_lines:
            chunks.append(chunk_lines)
            chunk_lines = []
            chunk_len = 0
        chunk_lines.append(line)
        chunk_len += len(line) + 1
    if chunk_lines:
        chunks.append(chunk_lines)

    for i, chunk in enumerate(chunks):
        if i == 0:
            await message.reply(TEXTS["admin_logs_all_2"].format(v0=total, v1="\n".join(chunk)))
        else:
            await message.answer("\n".join(chunk))

@dp.message(F.text.lower().startswith("!чистлоги"))
async def admin_clear_logs(message: Message):
    if not is_admin(message):
        return

    parts = message.text.strip().split(maxsplit=2)
    if len(parts) > 1 and parts[1].strip().lower() == "игроки":
        await _admin_clear_player_logs_impl(message, parts[2].strip().lower() if len(parts) > 2 else "")
        return

    parts = message.text.strip().split(maxsplit=1)
    arg = parts[1].strip().lower() if len(parts) > 1 else ""

    if arg in ("все", "всё", "all"):
        before_row = await db_query_one("SELECT COUNT(*) FROM audit_log")
        before = before_row[0] if before_row else 0
        await db_exec("DELETE FROM audit_log")
        await log_admin_action(message)
        await message.reply(TEXTS["admin_logs_clear_1"].format(v0=before, v1=0))
        return

    days = 7
    if arg:
        try:
            days = max(0, int(arg))
        except ValueError:
            days = 7

    cutoff = int(time.time()) - days * 86400
    before_row = await db_query_one("SELECT COUNT(*) FROM audit_log WHERE ts < ?", (cutoff,))
    before = before_row[0] if before_row else 0
    await db_exec("DELETE FROM audit_log WHERE ts < ?", (cutoff,))
    await log_admin_action(message)
    after_row = await db_query_one("SELECT COUNT(*) FROM audit_log")
    after = after_row[0] if after_row else 0
    await message.reply(TEXTS["admin_logs_clear_1"].format(v0=before, v1=after))

async def _admin_clear_player_logs_impl(message: Message, arg: str):
    if arg in ("все", "всё", "all"):
        before_row = await db_query_one("SELECT COUNT(*) FROM player_action_log")
        before = before_row[0] if before_row else 0
        await db_exec("DELETE FROM player_action_log")
        await log_admin_action(message)
        await message.reply(TEXTS["admin_logs_clear_1"].format(v0=before, v1=0))
        return

    days = 2
    if arg:
        try:
            days = max(0, int(arg))
        except ValueError:
            days = 2

    cutoff = int(time.time()) - days * 86400
    before_row = await db_query_one("SELECT COUNT(*) FROM player_action_log WHERE ts < ?", (cutoff,))
    before = before_row[0] if before_row else 0
    await db_exec("DELETE FROM player_action_log WHERE ts < ?", (cutoff,))
    await log_admin_action(message)
    after_row = await db_query_one("SELECT COUNT(*) FROM player_action_log")
    after = after_row[0] if after_row else 0
    await message.reply(TEXTS["admin_logs_clear_1"].format(v0=before, v1=after))

@dp.message(F.text.lower() == "!пинг")
async def admin_ping(message: Message):
    """!пинг — админский пинг (замер задержки БД). Если пишет НЕ овнер — раньше
    тут было тихое `return` без единого сообщения: для обычного игрока это
    выглядело неотличимо от 'бот завис', особенно для VIP, которые по привычке
    писали !пинг (с !) вместо VIP-команды 'пинг' (без !, см. vip_ping) и получали
    полную тишину. Теперь не-админ прозрачно попадает в тот же путь, что и VIP-
    команда 'пинг': с активным VIP получает обычный понг, без VIP — понятное
    сообщение вместо молчания."""
    if not is_admin(message):
        await vip_ping(message)
        return
    await log_admin_action(message)
    start = time.monotonic()
    await db_query_one("SELECT 1")
    elapsed_ms = round((time.monotonic() - start) * 1000)
    await message.reply(TEXTS["admin_ping_1"].format(v0=elapsed_ms))

@dp.message(F.text.lower() == "!пинг5")
async def admin_ping5(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    samples = []
    for _ in range(5):
        start = time.monotonic()
        await db_query_one("SELECT 1")
        samples.append(round((time.monotonic() - start) * 1000))
    samples_text = ", ".join(str(s) for s in samples)
    await message.reply(
        TEXTS["admin_ping_2"].format(
            v0=samples_text, v1=min(samples), v2=round(sum(samples) / len(samples)), v3=max(samples)
        )
    )

@dp.message(F.text.lower() == "!ивент стоп")
async def admin_event_stop(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    active = await is_event_active()
    await db_exec(
        "INSERT INTO settings (key, value) VALUES ('event_active', '0') "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
    )
    _invalidate_event_state_cache()
    await message.reply(TEXTS["admin_event_stop_1"] if active else TEXTS["admin_event_stop_2"])

@dp.message(F.text.lower() == "!ивент статус")
async def admin_event_status(message: Message):
    if not is_admin(message):
        return
    await log_admin_action(message)
    active, mult = await get_event_state()
    if not active:
        await message.reply(TEXTS["admin_event_status_2"])
        return

    row = await db_query_one("SELECT value FROM settings WHERE key = 'event_until'")
    until = int(row[0]) if row and row[0] else 0
    if until:
        left = max(0, until - int(time.time()))
        m, s = divmod(left, 60)
        left_text = f"{m} мин. {s} сек."
    else:
        left_text = TEXTS["admin_event_status_forever"]

    await message.reply(TEXTS["admin_event_status_1"].format(v0=mult, v1=left_text))

async def handle(request):
    return web.Response(text="Бот Нога Работает!")

async def keep_alive():
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        domain = os.environ.get("KOYEB_PUBLIC_DOMAIN")
        if domain:
            url = f"https://{domain}"
    if not url:
        print("Ни RENDER_EXTERNAL_URL, ни KOYEB_PUBLIC_DOMAIN не заданы, self-ping отключён")
        return

    async with aiohttp.ClientSession() as session:
        while True:
            await asyncio.sleep(PING_INTERVAL)
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    print(f"Self-ping: {resp.status}")
            except Exception as e:
                print(f"Self-ping не удался: {e}")

async def main():
    await init_db()
    await _load_game_banned_ids()
    await _load_banned_chat_ids()

    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

    asyncio.create_task(keep_alive())
    asyncio.create_task(chronos_orb_boost_loop())
    asyncio.create_task(auto_log_cleanup_loop())
    asyncio.create_task(_flush_player_log_buffer())

    print("Бот НОГА запущен!")
    try:
        await dp.start_polling(bot, drop_pending_updates=False)
    finally:
        if _player_log_buffer:
            try:
                batch, _player_log_buffer[:] = _player_log_buffer[:], []
                await db_exec_many(
                    "INSERT INTO player_action_log (ts, user_id, username, command) VALUES (?, ?, ?, ?)",
                    batch,
                )
            except Exception as e:
                print(f"Финальный flush player_action_log не удался: {e}")
        await bot.session.close()
        await runner.cleanup()

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("Установи переменную окружения BOT_TOKEN")
    if not TURSO_URL or not TURSO_TOKEN:
        raise RuntimeError("Установи переменные окружения TURSO_DATABASE_URL и TURSO_AUTH_TOKEN")
    asyncio.run(main())