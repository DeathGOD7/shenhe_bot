from datetime import datetime
import logging
import math
import re
from itertools import islice
from typing import Dict, List, Optional
from PIL import Image, ImageDraw
import aiosqlite
import discord
from sentry_sdk.integrations.logging import LoggingIntegration
from PIL.ImageFont import FreeTypeFont

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging

sentry_logging = LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)


def default_embed(title: str = "", message: str = ""):
    embed = discord.Embed(title=title, description=message, color=0xA68BD3)
    return embed


def error_embed(title: str = "", message: str = ""):
    embed = discord.Embed(title=title, description=message, color=0xFC5165)
    return embed


def time_in_range(start, end, x):
    """Return true if x is in the range [start, end]"""
    if start <= end:
        return start <= x <= end
    else:
        return start <= x or x <= end


def divide_chunks(l: List, n: int):
    for i in range(0, len(l), n):
        yield l[i : i + n]


def parse_HTML(HTML_string: str):
    HTML_string = HTML_string.replace("\\n", "\n")
    # replace tags with style attributes
    HTML_string = HTML_string.replace("</p>", "\n")
    HTML_string = HTML_string.replace("<strong>", "**")
    HTML_string = HTML_string.replace("</strong>", "**")

    # remove all HTML tags
    CLEANR = re.compile('<.*?>|&([a-z0-9]+|#[0-9]{1,6}|#x[0-9a-f]{1,6});') 
    HTML_string = re.sub(CLEANR, "", HTML_string)

    # remove time tags from mihoyo
    HTML_string = HTML_string.replace('t class="t_gl"', "")
    HTML_string = HTML_string.replace('t class="t_lc"', "")
    HTML_string = HTML_string.replace("/t", "")

    return HTML_string


def divide_dict(d: Dict, size: int):
    it = iter(d)
    for i in range(0, len(d), size):
        yield {k: d[k] for k in islice(it, size)}

def format_number(text: str) -> str:
    """Format numbers into bolded texts."""
    return re.sub("(\(?\d+.?\d+%?\)?)", r" **\1** ", text)

def get_weekday_int_with_name(weekday_name: str) -> int:
    weekday_name_dict = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    return weekday_name_dict.get(weekday_name, 0)


async def get_user_appearance_mode(user_id: int, db: aiosqlite.Connection) -> bool:
    c = await db.cursor()
    await c.execute("SELECT dark_mode FROM user_settings WHERE user_id = ?", (user_id,))
    mode = await c.fetchone()
    if mode is not None and mode[0] == 1:
        return True
    return False

def get_dt_now() -> datetime:
    """Get current datetime in UTC+8 timezone."""
    return datetime.now()