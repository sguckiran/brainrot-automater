"""Pure-helper tests: build_srt timing + build_ffmpeg_command argv."""

from __future__ import annotations

from social_video_factory.render import (
    TARGET_HEIGHT,
    TARGET_WIDTH,
    build_ffmpeg_command,
    build_srt,
)


def test_build_srt_splits_evenly():
    script = "line one\nline two\nline three\nline four"
    srt = build_srt(script, total_seconds=12.0)
    # Four cues, each 3 seconds.
    assert "00:00:00,000 --> 00:00:03,000" in srt
    assert "00:00:03,000 --> 00:00:06,000" in srt
    assert "00:00:06,000 --> 00:00:09,000" in srt
    assert "00:00:09,000 --> 00:00:12,000" in srt
    # Cue indices and text present.
    assert srt.startswith("1\n")
    assert "line four" in srt
    assert srt.count(" --> ") == 4


def test_build_srt_empty_input():
    assert build_srt("") == ""
    assert build_srt("   \n  \n") == ""


def test_build_ffmpeg_command_contains_required_filters():
    argv = build_ffmpeg_command(
        input_path="in.mp4",
        srt_path="subs.srt",
        output_path="out.mp4",
        hook_text="HOOK",
        watermark_text="@wm",
    )
    assert argv[0] == "ffmpeg"
    assert "in.mp4" in argv
    assert "out.mp4" in argv

    # The single -vf filtergraph holds scale, subtitles, drawtext, watermark.
    vf_index = argv.index("-vf")
    vf = argv[vf_index + 1]
    assert f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}" in vf
    assert "subtitles=" in vf
    assert "subs.srt" in vf
    assert "drawtext=" in vf
    assert "HOOK" in vf
    assert "@wm" in vf


def test_build_ffmpeg_command_scales_to_portrait():
    argv = build_ffmpeg_command("i.mp4", "s.srt", "o.mp4", "h", "w")
    vf = argv[argv.index("-vf") + 1]
    assert "1080:1920" in vf
