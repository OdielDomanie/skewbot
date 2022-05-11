import asyncio as aio
from io import BytesIO
import logging
import os
import discord as dc
from discord import app_commands as ac
from discord.interactions import Interaction
import dotenv
from .image import skew_image
from .image import logger as image_logger


dotenv.load_dotenv()

app_id = os.getenv("APP_ID")
test_guild = os.getenv("TEST_GUILD")
log_file = os.getenv("LOG_FILE")


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
        guild = dc.Object(int(test_guild))
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
    else:
        await tree.sync()

client.setup_hook = setup_hook


@tree.command(name="skew")
async def skew(it: Interaction, att: dc.Attachment):
    "Picture, but in *italics*."

    # chn = it.channel

    # target_att = None
    # # Permision: read_message_history
    # async for msg in chn.history(limit=20):  # type: ignore
    #     br = False
    #     for att in reversed(msg.attachments):
    #         if (
    #             att.content_type and att.content_type.startswith("img")
    #             or att.filename.split(".")[-1] in ("png", "jpg", "bmp")
    #         ) and msg.author == it.client.user:
    #             target_att = att
    #         br = True
    #         break
    #     if br:
    #         break
    
    
    if not (
        att.content_type and att.content_type.startswith("img")
        or att.filename.split(".")[-1] in ("png", "jpg", "bmp")
    ):
        await it.response.send_message("Not a picture :(")
        return
    
    defer_task = aio.create_task(it.response.defer(thinking=True))
    
    att_data = await att.read()

    TIMEOUT = 5
    try:
        out: BytesIO = await aio.wait_for(skew_image(BytesIO(att_data)), TIMEOUT)
    except aio.TimeoutError:
        await defer_task
        await it.delete_original_message()
        return

    await defer_task

    await it.followup.send(
        file=dc.File(out, filename=att.filename + "  but in italics.gif", spoiler=att.is_spoiler())
    )


# @tree.command()
# async def test(it: Interaction, att: dc.Attachment):
#     pass
