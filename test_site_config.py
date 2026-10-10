"""
Teste automatizado de site_config.py: carregar/salvar configuração,
validação de cada campo, e mapeamento de orientação -> resolução.
"""
import os

import pytest

from site_config import (
    ALL_PROVIDERS,
    DEFAULT_CONFIG,
    SiteConfigError,
    VALID_TRANSITION_TYPES,
    load_site_config,
    resolution_for_orientation,
    save_site_config,
)


@pytest.fixture
def config_path(tmp_path):
    return str(tmp_path / "site_config.json")


class TestLoadSaveConfig:
    def test_load_returns_defaults_when_file_missing(self, config_path):
        assert load_site_config(config_path) == DEFAULT_CONFIG

    def test_save_partial_merges_with_rest(self, config_path):
        saved = save_site_config({"orientation": "9:16"}, config_path)
        assert saved["orientation"] == "9:16"
        assert saved["browser_visible"] is False  # resto continua default

    def test_load_reflects_what_was_saved(self, config_path):
        save_site_config({"orientation": "9:16"}, config_path)
        assert load_site_config(config_path)["orientation"] == "9:16"

    def test_load_ignores_corrupted_file(self, config_path):
        with open(config_path, "w") as f:
            f.write("isso não é json {{{")
        assert load_site_config(config_path) == DEFAULT_CONFIG


class TestValidation:
    def test_rejects_invalid_orientation(self, config_path):
        with pytest.raises(SiteConfigError, match="orientation"):
            save_site_config({"orientation": "4:3"}, config_path)

    def test_rejects_incomplete_provider_priority(self, config_path):
        with pytest.raises(SiteConfigError, match="faltando"):
            save_site_config({"provider_priority": ["pexels", "pixabay"]}, config_path)

    def test_rejects_unknown_provider_in_priority(self, config_path):
        with pytest.raises(SiteConfigError, match="desconhecido"):
            save_site_config(
                {"provider_priority": ["pexels", "pixabay", "magnific", "mixkit", "vistacreate", "youtube"]},
                config_path,
            )

    def test_rejects_invalid_browser_mode(self, config_path):
        with pytest.raises(SiteConfigError, match="browser_mode"):
            save_site_config({"browser_mode": "algo_invalido"}, config_path)

    def test_rejects_non_boolean_flag(self, config_path):
        with pytest.raises(SiteConfigError, match="browser_visible"):
            save_site_config({"browser_visible": "sim"}, config_path)

    def test_valid_full_config_saves_successfully(self, config_path):
        saved = save_site_config({
            "orientation": "9:16",
            "export_quality": "720p",
            "clip_trim_position": "middle",
            "provider_priority": ["mixkit", "pexels", "pixabay", "magnific", "vistacreate", "animepexels", "wikipedia"],
            "pexels_api_fallback_to_browser": False,
            "magnific_only_free": False,
            "evitar_repeticao_clipes": False,
            "browser_visible": True,
            "browser_shared_across_providers": False,
            "browser_mode": "close_each_download",
        }, config_path)
        assert saved["provider_priority"][0] == "mixkit"
        assert saved["browser_mode"] == "close_each_download"
        assert saved["export_quality"] == "720p"
        assert saved["clip_trim_position"] == "middle"
        assert saved["evitar_repeticao_clipes"] is False

    def test_evitar_repeticao_clipes_ligado_por_padrao(self, config_path):
        saved = save_site_config({}, config_path)
        assert saved["evitar_repeticao_clipes"] is True

    def test_rejects_non_boolean_evitar_repeticao_clipes(self, config_path):
        with pytest.raises(SiteConfigError, match="evitar_repeticao_clipes"):
            save_site_config({"evitar_repeticao_clipes": "sim"}, config_path)

    def test_transition_type_none_por_padrao(self, config_path):
        saved = save_site_config({}, config_path)
        assert saved["transition_type"] == "none"
        assert saved["transition_duration"] == 0.6

    def test_transition_type_valido_salva(self, config_path):
        saved = save_site_config({"transition_type": "wipeleft", "transition_duration": 1.2}, config_path)
        assert saved["transition_type"] == "wipeleft"
        assert saved["transition_duration"] == 1.2

    def test_transition_type_invalido_da_erro(self, config_path):
        with pytest.raises(SiteConfigError, match="transition_type"):
            save_site_config({"transition_type": "giratoria-3d"}, config_path)

    def test_todas_as_transicoes_nativas_do_ffmpeg_xfade_sao_aceitas(self, config_path):
        # essa lista é uma cópia intencional de video_assembler.TRANSICOES_VALIDAS
        # (ver comentário lá) -- esse teste garante que as duas nunca
        # fiquem fora de sincronia sem alguém perceber.
        import video_assembler as va
        assert VALID_TRANSITION_TYPES == va.TRANSICOES_VALIDAS
        for tipo in sorted(va.TRANSICOES_VALIDAS):
            saved = save_site_config({"transition_type": tipo}, config_path)
            assert saved["transition_type"] == tipo

    def test_transition_duration_fora_da_faixa_da_erro(self, config_path):
        with pytest.raises(SiteConfigError, match="transition_duration"):
            save_site_config({"transition_duration": 10.0}, config_path)
        with pytest.raises(SiteConfigError, match="transition_duration"):
            save_site_config({"transition_duration": 0.01}, config_path)

    def test_rejects_shared_browser_with_close_each_download(self, config_path):
        with pytest.raises(SiteConfigError, match="compartilhado"):
            save_site_config({
                "browser_shared_across_providers": True,
                "browser_mode": "close_each_download",
            }, config_path)

    def test_rejects_shared_browser_with_default_concurrency_above_one(self, config_path):
        """Regressão: o padrão de preview_fetch_concurrency e
        assembly_fetch_concurrency é 3 — ligar 'navegador compartilhado'
        sem MUDAR essas concorrências pra 1 abriria um navegador POR
        busca paralela, o oposto do que a opção promete (economizar
        recursos com um único navegador)."""
        with pytest.raises(SiteConfigError, match="navegador compartilhado"):
            save_site_config({"browser_shared_across_providers": True}, config_path)

    def test_rejects_shared_browser_with_only_one_concurrency_above_one(self, config_path):
        with pytest.raises(SiteConfigError, match="navegador compartilhado"):
            save_site_config({
                "browser_shared_across_providers": True,
                "preview_fetch_concurrency": 1,
                "assembly_fetch_concurrency": 2,
            }, config_path)

    def test_accepts_shared_browser_with_both_concurrencies_at_one(self, config_path):
        saved = save_site_config({
            "browser_shared_across_providers": True,
            "preview_fetch_concurrency": 1,
            "assembly_fetch_concurrency": 1,
        }, config_path)
        assert saved["browser_shared_across_providers"] is True

    def test_non_shared_browser_accepts_any_concurrency(self, config_path):
        saved = save_site_config({
            "browser_shared_across_providers": False,
            "preview_fetch_concurrency": 8,
            "assembly_fetch_concurrency": 10,
        }, config_path)
        assert saved["preview_fetch_concurrency"] == 8
        assert saved["assembly_fetch_concurrency"] == 10

    def test_rejects_invalid_export_quality(self, config_path):
        with pytest.raises(SiteConfigError, match="export_quality"):
            save_site_config({"export_quality": "4k"}, config_path)

    def test_rejects_invalid_trim_position(self, config_path):
        with pytest.raises(SiteConfigError, match="clip_trim_position"):
            save_site_config({"clip_trim_position": "end"}, config_path)

    def test_accepts_valid_whisper_devices(self, config_path):
        for device in ("auto", "cpu", "gpu"):
            saved = save_site_config({"whisper_device": device}, config_path)
            assert saved["whisper_device"] == device

    def test_rejects_invalid_whisper_device(self, config_path):
        with pytest.raises(SiteConfigError, match="whisper_device"):
            save_site_config({"whisper_device": "tpu"}, config_path)

    def test_default_whisper_device_is_auto(self):
        assert DEFAULT_CONFIG["whisper_device"] == "auto"

    def test_default_animepexels_base_url(self):
        assert DEFAULT_CONFIG["animepexels_base_url"] == "http://localhost:5000"

    def test_accepts_custom_animepexels_base_url(self, config_path):
        saved = save_site_config({"animepexels_base_url": "http://192.168.1.50:5000"}, config_path)
        assert saved["animepexels_base_url"] == "http://192.168.1.50:5000"

    def test_strips_trailing_slash_from_animepexels_base_url(self, config_path):
        saved = save_site_config({"animepexels_base_url": "http://localhost:5000/"}, config_path)
        assert saved["animepexels_base_url"] == "http://localhost:5000"

    def test_rejects_animepexels_base_url_without_scheme(self, config_path):
        with pytest.raises(SiteConfigError, match="animepexels_base_url"):
            save_site_config({"animepexels_base_url": "localhost:5000"}, config_path)

    def test_animepexels_is_a_valid_provider(self):
        assert "animepexels" in ALL_PROVIDERS
        assert "animepexels" in DEFAULT_CONFIG["provider_priority"]


class TestResolutionForOrientation:
    def test_landscape(self):
        assert resolution_for_orientation("16:9") == (1920, 1080)

    def test_portrait(self):
        assert resolution_for_orientation("9:16") == (1080, 1920)

    def test_unexpected_value_falls_back_to_landscape(self):
        assert resolution_for_orientation("algo-estranho") == (1920, 1080)

    def test_export_quality_scales_resolution_keeping_aspect_ratio(self):
        assert resolution_for_orientation("16:9", "720p") == (1280, 720)
        assert resolution_for_orientation("9:16", "720p") == (720, 1280)
        assert resolution_for_orientation("16:9", "480p") == (854, 480)
        assert resolution_for_orientation("16:9", "2160p") == (3840, 2160)

    def test_all_resolutions_have_even_width(self):
        for quality in ("480p", "720p", "1080p", "1440p", "2160p"):
            width, _ = resolution_for_orientation("16:9", quality)
            assert width % 2 == 0, f"{quality} gerou largura ímpar ({width}), inválida pra libx264"
