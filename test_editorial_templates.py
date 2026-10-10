from pathlib import Path

from prompt_builder import VideoSegment
from template_library import list_templates, required_audio_names, get_template


def test_editorial_library_loaded_and_has_all_templates():
    templates = list_templates(include_manual=True)
    assert len(templates) == 167
    assert get_template("VIDEO_2")["nome"] == "Take - Lado a Lado"


def test_audio_manifest_names_are_unique_and_include_video2_sounds():
    names = required_audio_names()
    assert len(names) == len(set(names))
    assert "woosh_24.mp3" in names
    assert "click_ms_2.mp3" in names


def test_video_segment_roundtrip_keeps_template_id():
    seg = VideoSegment(
        start=0.0,
        end=4.0,
        provider="pexels",
        query="test",
        template_id="VIDEO_2",
    )
    data = seg.to_dict()
    assert data["template_id"] == "VIDEO_2"
