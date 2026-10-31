"""Convert actual Playwright recordings into portable README demo media.

Requires a full FFmpeg build with libx264 and GIF filters. Recording originals stay
under ignored .local/demo-recordings; only optimized deliverables go in docs/demos.
"""

import argparse
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / "docs/demos"
    output.mkdir(parents=True, exist_ok=True)
    summaries = []
    for name, preview_start in [("keel-failure-discovery", 22), ("keel-payment-recovery", 24)]:
        source = root / ".local/demo-recordings" / f"{name}.webm"
        movie = output / f"{name}.mp4"
        preview = output / f"{name}.gif"
        subprocess.run(
            [
                args.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                "1",
                "-i",
                str(source),
                "-an",
                "-vf",
                "fps=20",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "24",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(movie),
            ],
            check=True,
        )
        subprocess.run(
            [
                args.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                str(preview_start),
                "-t",
                "10",
                "-i",
                str(movie),
                "-filter_complex",
                "fps=6,scale=800:-1:flags=lanczos,split[a][b];"
                "[a]palettegen=max_colors=96:stats_mode=diff[p];"
                "[b][p]paletteuse=dither=bayer:bayer_scale=3",
                "-loop",
                "0",
                str(preview),
            ],
            check=True,
        )
        subprocess.run(
            [
                args.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(movie),
                "-f",
                "null",
                "-",
            ],
            check=True,
        )
        summaries.append(
            f"{name}: MP4 {movie.stat().st_size:,} bytes; GIF {preview.stat().st_size:,} bytes"
        )
    print("\n".join(summaries))


if __name__ == "__main__":
    main()
