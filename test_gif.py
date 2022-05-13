import asyncio as aio
import logging
from io import BytesIO

from skewbot.image import logger, skew_image


logger.setLevel(logging.DEBUG)
logger.addHandler(logging.StreamHandler())


async def _test():
    im_name = "test.png"
    with open(im_name, "rb") as im_file:
        im = im_file.read()
    gif = await skew_image(BytesIO(im))
    with open("test.gif", "wb") as gif_file:
        gif_file.write(gif.getbuffer())

if __name__ == "__main__":
    aio.run(_test())
