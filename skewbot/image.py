from __future__ import annotations

import asyncio as aio
import logging
import os
import shlex
import time
from asyncio.subprocess import PIPE
from io import BytesIO
from typing import Literal, Optional

import numpy as np
from PIL import Image

from .utils import semaphore


logger = logging.getLogger("image")


MAX_WIDTH = 480
MAX_HEIGHT = 480
MAX_SHEAR = 0.5  # angle in radians
MAX_WIDE = 2
MAX_OUTPUT_PIXELS = 480 * 480 * np.tan(MAX_SHEAR)

CONCURRENCY = int(os.getenv("CONCURRENCY", "1"))

pallete_name_counter = 0

@semaphore(CONCURRENCY)
async def skew_image(
        source_im: BytesIO | str, param: Optional[float] = None, mode: Literal["skew", "wide"] = "skew"
    ) -> BytesIO:

    start_time = time.perf_counter()

    TOTAL_FRAMES = 70
    FRAME_RATE = 50

    source_pil = Image.open(source_im)
    source_pil.thumbnail((MAX_WIDTH, MAX_HEIGHT), resample=Image.NEAREST)


    if mode == "skew":
        if not param or param <= 0 or param >= np.pi / 2 - 0.1:
            param = MAX_SHEAR
        expanded_size = (int(source_pil.size[0] + source_pil.size[1] * np.tan(param)), source_pil.size[1])


    elif mode == "wide":
        if not param or param < 1 or param > 20:
            param = MAX_WIDE
        expanded_size = (int(source_pil.size[0] * param), source_pil.size[1])

    else:
        raise ValueError()

    # Reduce the size if the params are too huge
    out_pixels = expanded_size[0] * expanded_size[1]
    if out_pixels > MAX_OUTPUT_PIXELS:
        reduce_factor = np.sqrt(MAX_OUTPUT_PIXELS / out_pixels)
        expanded_size = int(expanded_size[0] * reduce_factor), int(expanded_size[1] * reduce_factor)

    # We are doing two reductions instead of calculating the size beforehand.
    # This is inefficient but I'm lazy and it shouldn't matter much.
    source_pil.thumbnail((MAX_WIDTH, expanded_size[1]), resample=Image.NEAREST)

    expanded_im = Image.new(
        "RGBA",
        size=expanded_size, color=(0,0,0,0)
    )
    if mode == "skew":
        expanded_im.paste(source_pil, (0, 0, source_pil.size[0], source_pil.size[1]))
    else:
        expanded_im.paste(source_pil, ((expanded_size[0] - source_pil.size[0]) // 2, 0))

    source = np.array(expanded_im)

    if mode == "skew":
        # shear = a*t**2
        a = param / (TOTAL_FRAMES-1) ** 2
    else:
        # wide = a*t**2 + 1
        a = (param-1) / (TOTAL_FRAMES-1) ** 2

    frames = []

    # first create a palette
    # We create a palette based on only the original image, as the other frames will not contain any other colors.
    global pallete_name_counter
    pal_name = f"palette_{pallete_name_counter}.png"
    pallete_name_counter += 1

    try:
        pal_proc = await aio.create_subprocess_exec(
            *shlex.split(
                "ffmpeg -y -loglevel warning -hide_banner -f image2pipe"
                f" -i {source_im if isinstance(source_im, str) else '-'}"
                f" -vf palettegen=reserve_transparent=1 {pal_name}"),
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
            "-i", pal_name,
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


                if mode == "skew":
                    shear = a*t**2
                    skewed = _skew_image(source, shear)
                else:
                    wide = a*t**2 + 1
                    skewed = _wide_image(source, wide)

                    # For some reason, if we don't do this, the gif will have its last frame corrupted in some cases.
                    if t == TOTAL_FRAMES - 1:
                        skewed[5,5] = (1,1,1,1)   # type: ignore

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
    finally:
        try:
            os.remove(pal_name)
        except FileNotFoundError:
            pass


def _skew_image(img_arr: np.ndarray, x_angle: float) -> np.ndarray:
    x, y = np.ogrid[:img_arr.shape[0], :img_arr.shape[1]]

    y_tf = y - (np.tan(x_angle) * (img_arr.shape[0]-x)).astype(np.intp, copy=False)

    return img_arr[x, y_tf]


def _wide_image(img_arr: np.ndarray, x_ratio: float) -> np.ndarray:
    x, y = np.ogrid[:img_arr.shape[0], :img_arr.shape[1]]

    center_x = img_arr.shape[1] // 2

    # y_tf = (y - center) / scale + center
    y_tf = ((y - int(center_x * (1-x_ratio))) / x_ratio).astype(np.intp, copy=False)

    return img_arr[x, y_tf]
