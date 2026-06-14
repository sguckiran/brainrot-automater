"""Render stage — build a vertical 9:16 (1080x1920) MP4 with ffmpeg.

WHY a pure command-builder split out from the runner: the ffmpeg invocation is
the part worth unit-testing (scale filter, drawtext hook overlay, burned-in
subtitles, watermark), but actually *running* ffmpeg needs the binary installed.
``build_ffmpeg_command`` is pure (argv in/out) so tests assert on the command
without ffmpeg present; ``render_9x16`` does the side-effecting encode and
degrades gracefully when ffmpeg is missing (the mock pipeline skips the encode
rather than crashing — subtitles are burned from the generated *script*, no ASR).

Subtitle source: the generated script text, split into evenly-timed cues by
``build_srt`` (no speech recognition — Phase 1 has no audio analysis).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from social_video_factory import config
from social_video_factory.models import Job

# Target portrait canvas.
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920

# Default clip length (seconds) used to time subtitles when no probe duration
# is available — Phase 1 mock clips have no reliable duration.
DEFAULT_TOTAL_SECONDS = 12.0

_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("C:/Windows/Fonts/segoeui.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
)


def _format_srt_timestamp(seconds: float) -> str:
    """Format ``seconds`` as an SRT timestamp ``HH:MM:SS,mmm``."""
    if seconds < 0:
        seconds = 0.0
    millis_total = int(round(seconds * 1000))
    hours, millis_total = divmod(millis_total, 3_600_000)
    minutes, millis_total = divmod(millis_total, 60_000)
    secs, millis = divmod(millis_total, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def build_srt(script_text: str, total_seconds: float = DEFAULT_TOTAL_SECONDS) -> str:
    """Build an SRT subtitle document from ``script_text``.

    Pure function. Each non-empty line of the script becomes one cue, and the
    cues split ``total_seconds`` evenly. With N lines, cue *i* spans
    ``[i*total/N, (i+1)*total/N)``. Returns an empty string for empty input.
    """
    lines = [ln.strip() for ln in script_text.splitlines() if ln.strip()]
    if not lines:
        return ""
    per_cue = total_seconds / len(lines)
    blocks: list[str] = []
    for index, line in enumerate(lines):
        start = index * per_cue
        end = (index + 1) * per_cue
        blocks.append(
            f"{index + 1}\n"
            f"{_format_srt_timestamp(start)} --> {_format_srt_timestamp(end)}\n"
            f"{line}"
        )
    # Trailing newline terminates the final cue, as most SRT parsers expect.
    return "\n\n".join(blocks) + "\n"


def _escape_drawtext(text: str) -> str:
    """Escape text for ffmpeg's drawtext filter (colons, quotes, backslashes)."""
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )


def _escape_filter_path(path: str) -> str:
    """Escape a path used as an ffmpeg filter option.

    Filter arguments parse Windows backslashes and the drive-letter colon, so
    paths must use forward slashes and escape the colon.
    """
    return path.replace("\\", "/").replace(":", "\\:")


def _find_font_file() -> Path | None:
    """Return a stable system font for drawtext, if one is installed."""
    return next((path for path in _FONT_CANDIDATES if path.is_file()), None)


def build_ffmpeg_command(
    input_path: str | Path,
    srt_path: str | Path,
    output_path: str | Path,
    hook_text: str,
    watermark_text: str,
    font_path: str | Path | None = None,
    include_text_overlays: bool = False,
) -> list[str]:
    """Build the ffmpeg argv that renders a 1080x1920 MP4.

    Pure function (no I/O, no ffmpeg required) so it can be unit-tested. The
    filtergraph: scale+pad to 1080x1920, burn the SRT subtitles, draw the hook
    text near the top, and draw the watermark near the bottom.
    """
    input_path = str(input_path)
    output_path = str(output_path)
    srt_for_filter = _escape_filter_path(str(srt_path))
    hook = _escape_drawtext(hook_text)
    watermark = _escape_drawtext(watermark_text)
    font_option = ""
    if font_path is not None:
        font_option = f"fontfile='{_escape_filter_path(str(font_path))}':"

    scale_pad = (
        f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1"
    )
    filters = [scale_pad]
    if include_text_overlays:
        subtitles = f"subtitles='{srt_for_filter}'"
        hook_overlay = (
            f"drawtext={font_option}text='{hook}':fontcolor=white:fontsize=64:"
            f"borderw=4:bordercolor=black:x=(w-text_w)/2:y=h*0.08"
        )
        watermark_overlay = (
            f"drawtext={font_option}text='{watermark}':fontcolor=white@0.85:"
            f"fontsize=36:borderw=2:bordercolor=black:"
            f"x=(w-text_w)/2:y=h*0.90"
        )
        filters.extend([subtitles, hook_overlay, watermark_overlay])
    vf = ",".join(filters)

    return [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        output_path,
    ]


def render_9x16(job: Job) -> Path | None:
    """Render ``job``'s imported clip to a 9:16 MP4 with overlays + subtitles.

    Writes the SRT (from the job's script) and runs ffmpeg. Returns the output
    path on success. If ffmpeg is unavailable or the imported media is missing,
    returns ``None`` without raising so the mock pipeline can continue (the
    caller records a "render skipped" note). On an actual ffmpeg *failure* the
    error is recorded on the job and ``None`` is returned.
    """
    if not job.imported_media_path:
        return None
    input_path = Path(job.imported_media_path)
    if not input_path.exists():
        return None

    output_path = config.rendered_dir() / f"SVF_{job.id}_{job.template or 'clip'}_9x16.mp4"
    srt_path = config.rendered_dir() / f"SVF_{job.id}.srt"
    include_text_overlays = config.burn_text_overlays()
    if include_text_overlays:
        with srt_path.open("w", encoding="utf-8") as fh:
            fh.write(build_srt(job.script))

    if not shutil.which("ffmpeg"):
        # Caller (pipeline) marks this as a graceful skip; do not crash.
        return None

    hook_text = (job.script.splitlines() or ["Watch this"])[0]
    command = build_ffmpeg_command(
        input_path=input_path,
        srt_path=srt_path,
        output_path=output_path,
        hook_text=hook_text,
        watermark_text=config.WATERMARK_TEXT,
        font_path=_find_font_file(),
        include_text_overlays=include_text_overlays,
    )
    try:
        subprocess.run(command, capture_output=True, check=True)
    except (subprocess.SubprocessError, OSError) as exc:
        job.error = f"ffmpeg render failed: {exc}"
        return None

    job.rendered_path = str(output_path)
    return output_path
