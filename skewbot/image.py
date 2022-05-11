from __future__ import annotations
import asyncio as aio
from asyncio.subprocess import PIPE
from io import BytesIO
import logging
import shlex
import time
from PIL import Image
import numpy as np


logger = logging.getLogger("image")


MAX_WIDTH = 512
MAX_HEIGHT = 480
MAX_SHEAR = 0.5


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

    # if source_pil.mode == "RGB":
    #     a_channel = Image.new('L', source_pil.size, 255)   # 'L' 8-bit pixels, black and white
    #     source_pil.putalpha(a_channel)
    source = np.array(expanded_im)

    # shear = a*t**2
    a = MAX_SHEAR / (TOTAL_FRAMES-1) ** 2

    frames = []

    # first create a palette
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
    except BaseException:
        try:
            pal_proc.kill()
        except:
            pass
        else:
            logger.warning("Killing palette process.")
        raise

    ffmpeg_args = (
        "ffmpeg -y -loglevel warning -hide_banner -thread_queue_size 32 -f rawvideo"
        f" -pix_fmt rgba -s {expanded_im.size[0]}x{expanded_im.size[1]} -r {FRAME_RATE}"
        " -i - -i palette.png -filter_complex"
        # fR' "scale=if(gte(iw\,ih)\,min({MAX_WIDTH}\,iw)\,-2):if(lt(iw\,ih)\,min({MAX_HEIGHT}\,ih)\,-2),paletteuse=alpha_threshold=128"'
        ' "paletteuse=alpha_threshold=128"'
        " -gifflags -offsetting -f gif -"
    )
    proc = await aio.create_subprocess_exec(*shlex.split(ffmpeg_args), stdin=PIPE, stdout=PIPE)  #, stdout=DEVNULL, stderr=DEVNULL)

    try:
        # Read simultaneously to prevent buffers from clogging up.
        read_from_proc = aio.create_task(proc.stdout.read())  # type: ignore

        for t in range(TOTAL_FRAMES):

            shear = a*t**2
            # skew_tf = tf.AffineTransform(translation=(shear * -source_pil.size[1], 0), shear=-shear)
            # , scale=(1, 1*(1+shear))

            # frame = tf.warp(source, inverse_map=skew_tf)
            # frames.append(frame)
            skewed = _skew_image(source, shear)

            
            await proc.stdin.drain()  # type: ignore
            proc.stdin.write(skewed.tobytes())  # type: ignore

            # io.imsave(f"test{t}.tiff", skewed)

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
    # x = np.arange(img_arr.shape[0], dtype=np.intp).reshape((img_arr.shape[0],1))
    # y = np.arange(img_arr.shape[1], dtype=np.intp).reshape((1, img_arr.shape[1]))
    x, y = np.ogrid[:img_arr.shape[0], :img_arr.shape[1]]
    # x = X[:img_arr.shape[0], :]
    # y = Y[:, :img_arr.shape[1]]

    y_tf = y - (np.tan(x_angle) * (img_arr.shape[0]-x)).astype(np.intp, copy=False)

    return img_arr[x, y_tf]


async def _test():
    im_name = "test.jpg"
    with open(im_name, "rb") as im_file:
        im = im_file.read()   
    await skew_image(BytesIO(im))

if __name__ == "__main__":
    # logger.addHandler(logging.StreamHandler())
    # logger.setLevel(logging.INFO)
    
    import cProfile
    cProfile.run(
        "aio.run(_test())"
    )
