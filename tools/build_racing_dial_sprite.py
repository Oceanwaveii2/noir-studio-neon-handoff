"""Make the Racing dial sprite from the supplied track-loader GIF.

Each tile is an unmodified crop of a composited source frame. The loader text
is outside the crop; source animation and timings are otherwise untouched.
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tools/assets/noir-track-loader.gif'
OUTPUT = ROOT / 'tools/assets/noir-track-dial-frames.png'
BOX = (175, 115, 335, 295)
FILL_FRAMES = [27, 28, 29, 30, 31, 32, 33, 34, 35, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
TARGETS = {25: 6, 50: 9, 75: 12, 100: 18}


def main():
    with Image.open(SOURCE) as source:
        if source.n_frames != 36:
            raise ValueError('The Racing dial expects the 36-frame reference animation')
        sprite = Image.new('RGB', (6 * (BOX[2] - BOX[0]), 6 * (BOX[3] - BOX[1])))
        for index in range(36):
            source.seek(index)
            tile = source.convert('RGB').crop(BOX)
            sprite.paste(tile, ((index % 6) * tile.width, (index // 6) * tile.height))
        if not OUTPUT.exists():
            sprite.save(OUTPUT, optimize=True)
        for weight, final_index in TARGETS.items():
            output = ROOT / f'tools/assets/noir-track-dial-{weight}-once.gif'
            if output.exists():
                raise FileExistsError(f'Refusing to overwrite {output}')
            frames = []
            for source_frame in FILL_FRAMES[:final_index + 1]:
                source.seek(source_frame)
                frame = source.convert('RGB').crop(BOX)
                frame.info.clear()  # Do not inherit the original GIF's infinite loop.
                frames.append(frame)
            # Omitting the loop extension makes the animation play once and
            # leaves the final filled frame on screen.
            frames[0].save(output, format='GIF', save_all=True,
                           append_images=frames[1:], duration=70,
                           disposal=2, optimize=False)


if __name__ == '__main__': main()
