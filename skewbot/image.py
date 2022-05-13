from __future__ import annotations

import asyncio as aio
import logging
import os
import shlex
import time
from asyncio.subprocess import PIPE
from io import BytesIO

import numpy as np
from PIL import Image

from .utils import semaphore


logger = logging.getLogger("image")


MAX_WIDTH = 480
MAX_HEIGHT = 480
MAX_SHEAR = 0.5  # angle in radians

CONCURRENCY = int(os.getenv("CONCURRENCY", "1"))

@semaphore(CONCURRENCY)
async def skew_image(source_im: BytesIO | str) -> BytesIO:

    start_time = time.perf_counter()

    TOTAL_FRAMES = 70
    FRAME_RATE = 50

    source_pil = Image.open(source_im)
    source_pil.thumbnail((MAX_WIDTH, MAX_HEIGHT), resample=Image.NEAREST)

    expanded_im = Image.new(
        "RGBA",
        size=(int(source_pil.size[0] + source_pil.size[1] * np.tan(MAX_SHEAR)), source_pil.size[1]), color=(0,0,0,0)
    )
    expanded_im.paste(source_pil, (0, 0, source_pil.size[0], source_pil.size[1]))

    source = np.array(expanded_im)

    # shear = a*t**2
    a = MAX_SHEAR / (TOTAL_FRAMES-1) ** 2

    frames = []

    # first create a palette
    # We create a palette based on only the original image, as the other frames will not contain any other colors.
    pal_proc = await aio.create_subprocess_exec(
        *shlex.split(
            "ffmpeg -y -loglevel warning -hide_banner -f image2pipe"
            f" -i {source_im if isinstance(source_im, str) else '-'}"
            " -vf palettegen=reserve_transparent=1 palette.png"),
        stdin=PIPE,
    )
    try:
        if isinstance(source_im, str):
            await pal_proc.communicate()
        else:
            await pal_proc.communicate(source_im.getbuffer())
        if pal_proc.returncode:
            raise
    except BaseException:
        try:
            pal_proc.kill()
        except:
            pass
        else:
            logger.warning("Killing palette process.")
        raise Exception()

    ffmpeg_args_list = [
        "ffmpeg",
        "-y",
        "-loglevel", "warning",
        "-hide_banner",
        "-thread_queue_size", "32",
        "-f", "rawvideo",
        "-pix_fmt", "rgba",
        "-s", f"{expanded_im.size[0]}x{expanded_im.size[1]}",
        "-r", str(FRAME_RATE),
        "-i", "-",
        "-i", "palette.png",
        "-filter_complex",
        f"fps={FRAME_RATE},paletteuse=alpha_threshold=128,setpts='if(eq(N,{TOTAL_FRAMES}), PTS+{FRAME_RATE*4}, 1*PTS)'",
        "-gifflags", "-offsetting",
        "-f", "gif",
        "-",
    ]
    logger.debug(shlex.join(ffmpeg_args_list))

    proc = await aio.create_subprocess_exec(*ffmpeg_args_list, stdin=PIPE, stdout=PIPE)

    try:
        # Read simultaneously to prevent buffers from clogging up.
        read_from_proc = aio.create_task(proc.stdout.read())  # type: ignore

        for t in range(TOTAL_FRAMES):

            shear = a*t**2

            skewed = _skew_image(source, shear)

            await proc.stdin.drain()  # type: ignore
            proc.stdin.write(skewed.tobytes())  # type: ignore

        # Write the last frame again to fix the last frame timestamp.
        proc.stdin.write(skewed.tobytes())  # type: ignore
        await proc.stdin.drain()  # type: ignore

        proc.stdin.write_eof()  # type: ignore
        await proc.stdin.drain()  # type: ignore
        gif = await read_from_proc
        await proc.wait()

    except BaseException:
        try:
            proc.kill()
        except:
            pass
        else:
            logger.warning("Killing gif process.")
        raise

    result = BytesIO(gif)

    end_time = time.perf_counter()
    logger.info(f"skew_image took {end_time-start_time :4.3f} s, size {len(gif)/10**6 :4.3f} MB.")

    return result

# X = np.arange(MAX_HEIGHT, dtype=np.intp)[:, np.newaxis]
# Y = np.arange(MAX_WIDTH + int(MAX_HEIGHT * np.tan(MAX_SHEAR)), dtype=np.intp)[np.newaxis, :]

def _skew_image(img_arr: np.ndarray, x_angle: float) -> np.ndarray:
    x, y = np.ogrid[:img_arr.shape[0], :img_arr.shape[1]]

    y_tf = y - (np.tan(x_angle) * (img_arr.shape[0]-x)).astype(np.intp, copy=False)

    return img_arr[x, y_tf]
