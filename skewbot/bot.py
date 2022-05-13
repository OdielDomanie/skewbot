import asyncio as aio
import functools
import logging
import os
from io import BytesIO
from typing import Union

import discord as dc
import dotenv
from discord import app_commands as ac
from discord.interactions import Interaction

from .image import CONCURRENCY
from .image import logger as image_logger
from .image import skew_image


dotenv.load_dotenv()

app_id = os.getenv("APP_ID")
test_guild_str = os.getenv("TEST_GUILD")
log_file = os.getenv("LOG_FILE")

test_guild: Union[None, dc.Object] = test_guild_str and dc.Object(int(test_guild_str))  # type: ignore

logger = logging.getLogger("discord")
logger.setLevel(logging.INFO)
if log_file:
    handler = logging.FileHandler(log_file)
else:
    handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

image_logger.setLevel(logging.INFO)
image_logger.addHandler(handler)


intents = dc.Intents()
intents.guilds = True

client = dc.Client(intents=intents, application_id=app_id)
tree = ac.CommandTree(client)


async def setup_hook():
    if test_guild:
        tree.copy_global_to(guild=test_guild)
        await tree.sync(guild=test_guild)
    else:
        await tree.sync()

client.setup_hook = setup_hook


skew_count = 0

def func_count(f):
    @functools.wraps(f)
    async def wrapped(*args, **kwargs):
        try:
            global skew_count
            skew_count += 1
            return await f(*args, **kwargs)
        finally:
            skew_count -= 1
    return wrapped


@tree.command(name="skew")
@ac.describe(
    image="You can use ctrl+v | If omitted, last image.",
)
@func_count
async def skew(it: Interaction, image: dc.Attachment):
    "Picture, but in *italics*."

    if not (
        image.content_type and image.content_type.startswith("img")
        or image.filename.split(".")[-1] in ("png", "jpg", "bmp")
    ):
        await it.response.send_message("Not a picture 😬", ephemeral=True)
        return

    defer_task = aio.create_task(it.response.defer(thinking=True))

    att_data = await image.read()

    TIMEOUT = 15
    timeout = TIMEOUT * max(1, (skew_count - CONCURRENCY))
    try:
        out: BytesIO = await aio.wait_for(skew_image(BytesIO(att_data)), timeout)
    except aio.TimeoutError:
        await defer_task
        await it.delete_original_message()
        await it.followup.send("It took too long, I couldn't do it 😖", ephemeral=True)
        return
    except Exception as e:
        logger.exception(e)
        await defer_task
        await it.delete_original_message()
        await it.followup.send("I couldn't do it 😖", ephemeral=True)
        return
    except BaseException:
        await defer_task
        await it.delete_original_message()
        raise

    await defer_task

    try:
        await it.followup.send(
            file=dc.File(
                out, filename=image.filename + "  but in italics.gif", spoiler=image.is_spoiler()
                )
        )
    except dc.HTTPException as e:
        if e.status == 413:
            await it.delete_original_message()
            await it.followup.send("The gif is too large to send 😵", ephemeral=True)
        else:
            logger.exception(e)
            await it.delete_original_message()
            await it.followup.send("I couldn't send it 😖", ephemeral=True)
    except BaseException as e:
        logger.exception(e)
        await it.delete_original_message()
        await it.followup.send("I couldn't send it 😖", ephemeral=True)
