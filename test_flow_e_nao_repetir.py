"""
Testes de três coisas novas (e como elas se encaixam no resto do site):

1. O provedor "flow" (imagens geradas por IA no Google Flow): registro nos
   bancos, config, prompt da IA, timeout próprio, e o que NÃO pode fazer
   (disparar geração de minutos numa cadeia de fallback de vídeo).
2. "Ocultar o navegador": config única (browser_visible) valendo pra buscas,
   captura de página e Flow; escolha por vídeo na página do prompt.
3. "Não repetir vídeos/imagens de banco de conteúdo": pula o que já foi usado
   e pega o 2º, 3º... melhor — na montagem E nas prévias; a Wikipedia é exceção.

Nada aqui abre navegador nem fala com o Google/bancos: tudo com fakes.
"""
import json
import os
import shutil
import subprocess
import sys
import time

import pytest

_TOOLKIT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit")
if _TOOLKIT not in sys.path:
    sys.path.insert(0, _TOOLKIT)

import site_config  # noqa: E402
from site_config import ALL_PROVIDERS, DEFAULT_CONFIG, SiteConfigError, load_site_config, save_site_config  # noqa: E402
from prompt_builder import (  # noqa: E402
    DEFAULT_PROVIDERS, PHOTO_SEARCH_PROVIDERS, VideoSegment, build_prompt, parse_ai_response,
)
import video_assembler as va  # noqa: E402
from video_assembler import (  # noqa: E402
    ClientFactory, NO_REPEAT_EXEMPT_PROVIDERS, UsedClipsTracker, VideoAssemblyError,
    _escolher_candidato_previa, _fallback_queries_for, _provider_timeout_seconds,
    _search_and_download_photo, _tracker_para, fetch_segment_preview_lightweight,
    photo_api_configuration_error,
)
from googleflow import googleflow_client as gf  # noqa: E402


# ======================================================================
# 1. Configuração: provedor "flow" + opções do Flow
# ======================================================================

@pytest.fixture
def config_path(tmp_path):
    return str(tmp_path / "site_config.json")


class TestConfigFlow:
    def test_flow_e_um_provedor_e_fica_por_ultimo_na_prioridade(self):
        assert "flow" in ALL_PROVIDERS
        assert DEFAULT_CONFIG["provider_priority"][-1] == "flow"

    def test_defaults_do_flow(self):
        assert DEFAULT_CONFIG["flow_navegador"] == "auto"
        assert DEFAULT_CONFIG["flow_exe"] == ""
        assert DEFAULT_CONFIG["flow_timeout_seconds"] == 300

    def test_config_antiga_sem_flow_ganha_flow_no_fim_ao_carregar(self, config_path):
        antiga = ["mixkit", "pexels", "pixabay", "magnific", "vistacreate", "animepexels", "wikipedia"]
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump({"provider_priority": antiga}, f)
        carregada = load_site_config(config_path)
        assert carregada["provider_priority"] == antiga + ["flow", "moviepexels", "animepexels_online", "moviepexels_online"]  # v84: moviepexels também completa sozinho

    def test_salvar_lista_antiga_sem_flow_completa_em_vez_de_dar_erro(self, config_path):
        antiga = ["mixkit", "pexels", "pixabay", "magnific", "vistacreate", "animepexels", "wikipedia"]
        salvo = save_site_config({"provider_priority": antiga}, config_path)
        assert salvo["provider_priority"] == antiga + ["flow", "moviepexels", "animepexels_online", "moviepexels_online"]  # v84: moviepexels também completa sozinho

    def test_lista_realmente_incompleta_continua_sendo_rejeitada(self, config_path):
        # falta "pixabay" etc — só o "flow" é completado sozinho
        with pytest.raises(SiteConfigError, match="faltando"):
            save_site_config({"provider_priority": ["pexels", "flow"]}, config_path)

    def test_defaults_da_sessao_unica_do_flow(self):
        assert DEFAULT_CONFIG["flow_configurar_projeto"] is True
        assert DEFAULT_CONFIG["flow_seletor_configuracoes"] == ""

    def test_configurar_projeto_precisa_ser_booleano(self, config_path):
        assert save_site_config({"flow_configurar_projeto": False}, config_path)["flow_configurar_projeto"] is False
        with pytest.raises(SiteConfigError, match="flow_configurar_projeto"):
            save_site_config({"flow_configurar_projeto": "sim"}, config_path)

    def test_seletor_das_configuracoes_e_texto_e_aparado(self, config_path):
        salvo = save_site_config({"flow_seletor_configuracoes": "  button.engrenagem  "}, config_path)
        assert salvo["flow_seletor_configuracoes"] == "button.engrenagem"
        with pytest.raises(SiteConfigError, match="flow_seletor_configuracoes"):
            save_site_config({"flow_seletor_configuracoes": 5}, config_path)

    def test_defaults_das_varias_contas(self):
        assert DEFAULT_CONFIG["flow_horas_ate_liberar"] == 24
        assert DEFAULT_CONFIG["flow_palavras_limite"] == ""

    @pytest.mark.parametrize("valor", [0, 721, "abc", None])
    def test_horas_ate_liberar_fora_do_intervalo(self, config_path, valor):
        with pytest.raises(SiteConfigError, match="flow_horas_ate_liberar"):
            save_site_config({"flow_horas_ate_liberar": valor}, config_path)

    def test_horas_ate_liberar_e_palavras_validas(self, config_path):
        salvo = save_site_config({"flow_horas_ate_liberar": "48", "flow_palavras_limite": "  zerou, acabou "}, config_path)
        assert salvo["flow_horas_ate_liberar"] == 48 and salvo["flow_palavras_limite"] == "zerou, acabou"
        with pytest.raises(SiteConfigError, match="flow_palavras_limite"):
            save_site_config({"flow_palavras_limite": 7}, config_path)

    @pytest.mark.parametrize("valor", ["netscape", "", "Chrome2"])
    def test_flow_navegador_invalido(self, config_path, valor):
        with pytest.raises(SiteConfigError, match="flow_navegador"):
            save_site_config({"flow_navegador": valor}, config_path)

    def test_flow_navegador_validos(self, config_path):
        for nome in ("auto", "chrome", "edge", "chromium", "firefox", "webkit", "cdp"):
            assert save_site_config({"flow_navegador": nome}, config_path)["flow_navegador"] == nome

    @pytest.mark.parametrize("valor", [10, 29, 1801, "abc", None])
    def test_flow_timeout_fora_do_intervalo(self, config_path, valor):
        with pytest.raises(SiteConfigError, match="flow_timeout_seconds"):
            save_site_config({"flow_timeout_seconds": valor}, config_path)

    def test_flow_timeout_e_convertido_pra_inteiro(self, config_path):
        assert save_site_config({"flow_timeout_seconds": "120"}, config_path)["flow_timeout_seconds"] == 120

    def test_flow_exe_precisa_ser_texto_e_e_aparado(self, config_path):
        assert save_site_config({"flow_exe": "  C:\\brave\\brave.exe  "}, config_path)["flow_exe"] == "C:\\brave\\brave.exe"
        with pytest.raises(SiteConfigError, match="flow_exe"):
            save_site_config({"flow_exe": 123}, config_path)


# ======================================================================
# 2. Prompt da IA
# ======================================================================

_TRANSCRICAO = [
    {"start": 0.0, "end": 4.0, "text": "Imagine uma cidade flutuando entre as nuvens."},
    {"start": 4.0, "end": 8.0, "text": "Ninguém nunca viu nada parecido."},
]


class TestPromptFlow:
    def test_flow_esta_nos_provedores_padrao_e_de_foto(self):
        assert "flow" in DEFAULT_PROVIDERS
        assert "flow" in PHOTO_SEARCH_PROVIDERS

    def test_regra_do_flow_so_aparece_quando_ele_esta_selecionado(self):
        com = build_prompt(_TRANSCRICAO, providers=["pexels", "flow"])
        sem = build_prompt(_TRANSCRICAO, providers=["pexels", "pixabay"])
        assert "GERA uma mídia inédita" in com
        assert "GERA uma mídia inédita" not in sem

    def test_regra_do_flow_diz_o_essencial(self):
        prompt = build_prompt(_TRANSCRICAO, providers=["pexels", "flow"])
        assert '"media_type": "image"' in prompt          # imagem é o normal
        assert '"media_type": "video"' in prompt          # vídeo (Veo) também, quando o movimento importa
        assert "MODERAÇÃO" in prompt                       # é lento/gasta créditos
        assert "DESCRIÇÃO DA CENA" in prompt               # query é um pedido, não termo de busca
        assert 'só funciona com "pexels" ou "flow"' in prompt  # nota de foto inclui o flow

    def test_exemplo_do_json_nao_usa_flow_como_provedor_de_exemplo(self):
        # o exemplo genérico ("sunrise over mountains") contradiria a regra
        # de usar o flow só com moderação
        prompt = build_prompt(_TRANSCRICAO, providers=["flow", "pexels"])
        exemplo = prompt.split("```json")[-1] if "```json" in prompt else prompt
        assert '"provider": "flow", "query": "sunrise' not in exemplo

    def test_resposta_da_ia_com_flow_e_imagem_e_aceita(self):
        resposta = json.dumps([
            {"start": 0.0, "end": 4.0, "provider": "flow", "media_type": "image",
             "query": "cidade flutuando entre nuvens douradas ao pôr do sol, estilo cinematográfico"},
            {"start": 4.0, "end": 8.0, "provider": "pexels", "query": "clouds"},
        ])
        parsed = parse_ai_response(resposta, valid_providers=["pexels", "flow"], total_duration=8.0)
        assert parsed.segments[0].provider == "flow"
        assert parsed.segments[0].media_type == "image"

    def test_resposta_com_flow_nao_selecionado_e_rejeitada(self):
        resposta = json.dumps([{"start": 0.0, "end": 8.0, "provider": "flow", "media_type": "image", "query": "x"}])
        with pytest.raises(Exception):
            parse_ai_response(resposta, valid_providers=["pexels"], total_duration=8.0)


# ======================================================================
# 3. Montagem: "não repetir" + Wikipedia como exceção
# ======================================================================

class _Foto:
    def __init__(self, id_):
        self.id = id_


@pytest.fixture
def imagem_valida(tmp_path):
    caminho = tmp_path / "fonte.jpg"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=320x240", "-frames:v", "1", str(caminho)],
        capture_output=True, check=True,
    )
    return str(caminho)


def _cliente_de_fotos(ids, imagem):
    class Cliente:
        def search_photos_all(self, query=None, max_pages=1, **kw):
            return [_Foto(i) for i in ids]

        def download_photo(self, photo, output_dir, **kw):
            os.makedirs(output_dir, exist_ok=True)
            destino = os.path.join(output_dir, f"{photo.id}.jpg")
            shutil.copy(imagem, destino)
            return destino
    return Cliente()


def _seg(provider):
    return VideoSegment(start=0.0, end=3.0, provider=provider, query="tema", media_type="image")


def _nomes_escolhidos(provider, ids, n, tmp_path, imagem):
    cliente = _cliente_de_fotos(ids, imagem)
    tracker = UsedClipsTracker()
    return [
        os.path.basename(_search_and_download_photo(_seg(provider), str(tmp_path / f"d{i}"), cliente, used_tracker=tracker))
        for i in range(n)
    ]


class TestNaoRepetirMontagem:
    def test_bancos_de_estoque_pegam_o_proximo_melhor_a_cada_repeticao(self, tmp_path, imagem_valida):
        assert _nomes_escolhidos("pexels", ["a", "b", "c"], 3, tmp_path, imagem_valida) == ["a.jpg", "b.jpg", "c.jpg"]

    def test_wikipedia_e_excecao_e_repete_a_mesma_foto(self, tmp_path, imagem_valida):
        assert _nomes_escolhidos("wikipedia", ["a", "b", "c"], 3, tmp_path, imagem_valida) == ["a.jpg"] * 3

    def test_o_flow_nao_e_excecao_repetir_o_pedido_rende_a_proxima_imagem_gerada(self, tmp_path, imagem_valida):
        assert _nomes_escolhidos("flow", ["g1", "g2"], 2, tmp_path, imagem_valida) == ["g1.jpg", "g2.jpg"]

    def test_quando_todas_ja_foram_usadas_repete_a_melhor_em_vez_de_ficar_sem_midia(self, tmp_path, imagem_valida):
        assert _nomes_escolhidos("pexels", ["a", "b"], 3, tmp_path, imagem_valida) == ["a.jpg", "b.jpg", "a.jpg"]

    def test_wikipedia_nao_consome_o_id_de_outro_banco(self, tmp_path, imagem_valida):
        # a foto "a" da Wikipedia não pode "queimar" o "a" do Pexels
        tracker = UsedClipsTracker()
        cliente = _cliente_de_fotos(["a", "b"], imagem_valida)
        _search_and_download_photo(_seg("wikipedia"), str(tmp_path / "w"), cliente, used_tracker=tracker)
        escolhida = _search_and_download_photo(_seg("pexels"), str(tmp_path / "p"), cliente, used_tracker=tracker)
        assert os.path.basename(escolhida) == "a.jpg"

    def test_mesmo_id_em_bancos_diferentes_nao_se_confunde(self, tmp_path, imagem_valida):
        tracker = UsedClipsTracker()
        cliente = _cliente_de_fotos(["123", "456"], imagem_valida)
        primeira = _search_and_download_photo(_seg("pexels"), str(tmp_path / "1"), cliente, used_tracker=tracker)
        outra_banco = _search_and_download_photo(_seg("flow"), str(tmp_path / "2"), cliente, used_tracker=tracker)
        assert os.path.basename(primeira) == os.path.basename(outra_banco) == "123.jpg"

    def test_reserva_de_download_que_falhou_e_liberada_com_o_provedor_certo(self, tmp_path, imagem_valida):
        class ClienteFalha(_cliente_de_fotos(["a", "b"], imagem_valida).__class__):
            def download_photo(self, photo, output_dir, **kw):
                if photo.id == "a":
                    raise RuntimeError("link quebrado")
                return super().download_photo(photo, output_dir, **kw)
        tracker = UsedClipsTracker()
        _search_and_download_photo(_seg("pexels"), str(tmp_path / "1"), ClienteFalha(), used_tracker=tracker)
        assert tracker.try_claim("a", "pexels") is True   # foi liberada
        assert tracker.try_claim("b", "pexels") is False  # essa foi de fato usada


class TestTracker:
    def test_chave_por_provedor(self):
        t = UsedClipsTracker()
        assert t.try_claim("1", "pexels") is True
        assert t.try_claim("1", "pixabay") is True
        assert t.try_claim("1", "pexels") is False

    def test_sem_provedor_continua_igual_a_antes(self):
        t = UsedClipsTracker()
        assert t.try_claim(12345) is True
        assert t.try_claim("12345") is False

    def test_release_respeita_o_provedor(self):
        t = UsedClipsTracker()
        t.try_claim("1", "pexels")
        t.release("1", "pixabay")               # outro banco: não libera
        assert t.try_claim("1", "pexels") is False
        t.release("1", "pexels")
        assert t.try_claim("1", "pexels") is True

    def test_excecoes_e_helper(self):
        assert NO_REPEAT_EXEMPT_PROVIDERS == frozenset({"wikipedia"})
        t = UsedClipsTracker()
        assert _tracker_para("wikipedia", t) is None
        assert _tracker_para("pexels", t) is t
        assert _tracker_para("flow", t) is t
        assert _tracker_para("pexels", None) is None


# ======================================================================
# 4. Prévias: pega o 2º, 3º... melhor quando o melhor já foi usado
# ======================================================================

class _Res:
    """Resultado de busca de foto (o que `search_candidates` lê)."""
    def __init__(self, id_, thumb=True):
        self.id = id_
        self.sizes = {"tiny": f"http://t/{id_}.jpg"} if thumb else {}
        self.description = f"foto {id_}"
        self.author = "autor"
        self.url = f"http://post/{id_}"


class _FabricaFalsa:
    def __init__(self, resultados):
        self.cfg = {}
        self.resultados = resultados
        self.pedidos = []

    def get_photo_client(self, provider):
        fabrica = self

        class Cliente:
            def search_photos_all(self, query=None, max_pages=1, **kw):
                fabrica.pedidos.append((provider, query))
                return list(fabrica.resultados)
        return Cliente()

    def close_all(self):
        pass


_CFG_PREVIA = {"provider_attempt_timeout_seconds": 5, "provider_priority": list(ALL_PROVIDERS)}


def _previa(provider, fabrica, tracker):
    seg = VideoSegment(start=0.0, end=3.0, provider=provider, query="tema", media_type="image")
    return fetch_segment_preview_lightweight(seg, site_cfg=_CFG_PREVIA, client_factory=fabrica, used_tracker=tracker)


class TestPreviasNaoRepetem:
    def test_sem_tracker_sempre_mostra_o_melhor(self):
        fabrica = _FabricaFalsa([_Res("a"), _Res("b")])
        assert [_previa("pexels", fabrica, None)["result_url"] for _ in range(3)] == ["http://post/a"] * 3

    def test_com_tracker_cada_trecho_mostra_o_proximo_melhor(self):
        fabrica = _FabricaFalsa([_Res("a"), _Res("b"), _Res("c")])
        tracker = UsedClipsTracker()
        urls = [_previa("pexels", fabrica, tracker)["result_url"] for _ in range(3)]
        assert urls == ["http://post/a", "http://post/b", "http://post/c"]

    def test_esgotou_os_candidatos_repete_o_melhor_em_vez_de_ficar_sem_previa(self):
        fabrica = _FabricaFalsa([_Res("a"), _Res("b")])
        tracker = UsedClipsTracker()
        urls = [_previa("pexels", fabrica, tracker)["result_url"] for _ in range(3)]
        assert urls == ["http://post/a", "http://post/b", "http://post/a"]
        assert _previa("pexels", fabrica, tracker)["ok"] is True

    def test_wikipedia_repete_a_mesma_foto_na_previa(self):
        fabrica = _FabricaFalsa([_Res("a"), _Res("b")])
        tracker = UsedClipsTracker()
        assert [_previa("wikipedia", fabrica, tracker)["result_url"] for _ in range(3)] == ["http://post/a"] * 3

    def test_candidato_sem_miniatura_e_pulado_com_tracker(self):
        fabrica = _FabricaFalsa([_Res("a", thumb=False), _Res("b")])
        assert _previa("pexels", fabrica, UsedClipsTracker())["result_url"] == "http://post/b"

    def test_thumbnail_devolvido_e_o_do_candidato_escolhido(self):
        fabrica = _FabricaFalsa([_Res("a"), _Res("b")])
        tracker = UsedClipsTracker()
        _previa("pexels", fabrica, tracker)
        assert _previa("pexels", fabrica, tracker)["thumbnail_url"] == "http://t/b.jpg"

    def test_escolher_candidato_sem_tracker_mantem_o_comportamento_antigo(self):
        assert _escolher_candidato_previa([{"id": "a", "thumbnail": "t"}], None, "pexels")["id"] == "a"
        assert _escolher_candidato_previa([{"id": "a", "thumbnail": ""}, {"id": "b", "thumbnail": "t"}], None, "pexels") is None
        assert _escolher_candidato_previa([], None, "pexels") is None

    def test_escolher_candidato_sem_id_nao_da_pra_deduplicar_e_aceita(self):
        t = UsedClipsTracker()
        assert _escolher_candidato_previa([{"id": "", "thumbnail": "t"}], t, "pexels") is not None

    def test_com_tracker_pede_varios_candidatos_e_sem_tracker_so_um(self, monkeypatch):
        pedidos = []
        real = va.search_candidates

        def espiao(provider, query, media_type="video", max_results=6, **kw):
            pedidos.append(max_results)
            return real(provider, query, media_type=media_type, max_results=max_results, **kw)

        monkeypatch.setattr(va, "search_candidates", espiao)
        fabrica = _FabricaFalsa([_Res("a")])
        _previa("pexels", fabrica, UsedClipsTracker())
        seg = VideoSegment(start=0.0, end=3.0, provider="pexels", query="tema", media_type="image")
        # (v84_92) sem tracker e com o filtro 🎞️ "imagens reais" desligado: só 1, como antes
        fetch_segment_preview_lightweight(seg, site_cfg=dict(_CFG_PREVIA, estilo_imagens="qualquer"), client_factory=fabrica)
        _previa("pexels", fabrica, None)  # filtro ligado (padrão): pede alguns a mais pra poder pular desenho/3D
        assert pedidos[0] > 1 and pedidos[1] == 1 and pedidos[2] >= 6


# ======================================================================
# 5. Provedor "flow" dentro do montador
# ======================================================================

class TestFlowNoMontador:
    def test_flow_agora_tem_cliente_de_video_mas_fica_fora_do_fallback(self, monkeypatch):
        # v80: o Flow também gera VÍDEO (Veo) quando o próprio trecho pede "flow";
        # nas cadeias de reserva de outros trechos ele continua de fora.
        monkeypatch.setattr(gf, "PLAYWRIGHT_DISPONIVEL", True)
        cli = ClientFactory({"orientation": "16:9"}).get_client("flow")
        assert hasattr(cli, "search_all") and hasattr(cli, "download_video")
        assert va._sem_flow_no_fallback(["pexels", "pixabay", "flow"], "pixabay") == ["pexels"]

    def test_sem_tentar_termos_alternativos(self):
        seg = VideoSegment(start=0.0, end=3.0, provider="flow", query="uma cidade flutuante entre nuvens", media_type="image")
        assert _fallback_queries_for(seg) == []
        seg_px = VideoSegment(start=0.0, end=3.0, provider="pexels", query="uma cidade flutuante entre nuvens")
        assert _fallback_queries_for(seg_px)  # os outros bancos continuam tendo

    def test_timeout_proprio_do_flow_e_bem_maior_que_o_dos_bancos(self):
        cfg = {"provider_attempt_timeout_seconds": 25, "flow_timeout_seconds": 300}
        assert _provider_timeout_seconds(cfg, "pexels") == 25
        # o mesmo limite cobre imagem e vídeo (Veo espera no mínimo 600 s) + 90 s de navegador/download
        assert _provider_timeout_seconds(cfg, "flow") == 690
        assert _provider_timeout_seconds({"provider_attempt_timeout_seconds": 25}, "flow") == 690
        assert _provider_timeout_seconds({"flow_timeout_seconds": 900}, "flow") == 990
        assert _provider_timeout_seconds({"flow_timeout_seconds": "lixo"}, "flow") >= 690

    def test_previa_do_flow_usa_o_timeout_longo(self, monkeypatch):
        usados = []
        monkeypatch.setattr(va, "_run_with_timeout", lambda func, t: (usados.append(t), func())[1])
        fabrica = _FabricaFalsa([_Res("g1")])
        cfg = dict(_CFG_PREVIA, flow_timeout_seconds=120)
        seg = VideoSegment(start=0.0, end=3.0, provider="flow", query="cidade", media_type="image")
        fetch_segment_preview_lightweight(seg, site_cfg=cfg, client_factory=fabrica)
        assert usados == [690]

    def test_video_com_provider_flow_cai_pra_outro_banco_sem_gerar_nada(self):
        # um segmento de VÍDEO marcado como "flow": a prévia tenta o flow (erro
        # imediato) e segue a prioridade — nunca dispara geração de minutos.
        class Fabrica:
            cfg = {}

            def get_client(self, provider):
                if provider == "flow":
                    raise VideoAssemblyError("só gera IMAGENS")
                raise VideoAssemblyError(f"{provider} indisponível no teste")

            def close_all(self):
                pass

        seg = VideoSegment(start=0.0, end=3.0, provider="flow", query="cidade")  # media_type padrão = video
        r = fetch_segment_preview_lightweight(seg, site_cfg=_CFG_PREVIA, client_factory=Fabrica())
        assert r["ok"] is False and "indisponível" in r["error"]

    def test_photo_client_do_flow_recebe_a_config_do_site(self, monkeypatch):
        monkeypatch.setattr(gf, "PLAYWRIGHT_DISPONIVEL", True)
        cfg = {"orientation": "9:16", "browser_visible": False}
        cliente = ClientFactory(cfg).get_photo_client("flow")
        assert isinstance(cliente, gf.GoogleFlowClient)
        assert cliente.proporcao == "9x16" and cliente.oculto is True

    def test_validacao_antecipada_avisa_que_falta_o_playwright(self, monkeypatch):
        monkeypatch.setattr(gf, "PLAYWRIGHT_DISPONIVEL", False)
        erro = photo_api_configuration_error(site_cfg={}, provider="flow")
        assert erro and "pip install playwright" in erro
        monkeypatch.setattr(gf, "PLAYWRIGHT_DISPONIVEL", True)
        assert photo_api_configuration_error(site_cfg={}, provider="flow") is None

    def test_search_candidates_de_imagem_aceita_flow(self, monkeypatch):
        class ClienteFlow:
            def search_photos_all(self, query=None, max_pages=1, **kw):
                return [_Res("g1"), _Res("g2")]

        class Fabrica:
            cfg = {}

            def get_photo_client(self, provider):
                assert provider == "flow"
                return ClienteFlow()

            def close_all(self):
                pass

        candidatos = va.search_candidates("flow", "cidade", media_type="image", max_results=6, client_factory=Fabrica())
        assert [c["id"] for c in candidatos] == ["g1", "g2"]


# ======================================================================
# 6. Páginas e rotas (Flask)
# ======================================================================

@pytest.fixture
def app_module():
    import app as app_module  # noqa: WPS433
    return app_module


@pytest.fixture
def client(app_module, tmp_path, monkeypatch):
    monkeypatch.setattr(site_config, "CONFIG_PATH", str(tmp_path / "site_config.json"))
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


@pytest.fixture
def job(app_module, monkeypatch, tmp_path):
    """Um job mínimo na memória, sem gravar estado em disco."""
    monkeypatch.setattr(app_module, "_save_state", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "_job_dir", lambda job_id: str(tmp_path / job_id))
    job_id = "jobteste0001"
    dados = {
        "job_id": job_id, "status": "aguardando_json", "prompt": "PROMPT DE TESTE",
        "providers": ["pexels", "flow"], "total_duration": 8.0, "audio_path": str(tmp_path / "a.wav"),
        "wikipedia_entidades": None,
    }
    app_module._JOBS[job_id] = dados
    yield dados
    app_module._JOBS.pop(job_id, None)


_JSON_OK = json.dumps([{"start": 0.0, "end": 8.0, "provider": "pexels", "query": "clouds"}])


class TestPaginaConfiguracoes:
    def test_mostra_ocultar_navegador_marcado_por_padrao_e_a_secao_do_flow(self, client):
        html = client.get("/settings").get_data(as_text=True)
        assert "Ocultar o navegador" in html
        assert 'name="ocultar_navegador" checked' in html
        assert 'name="flow_navegador"' in html and "Contas Google" in html

    def test_marcar_ocultar_salva_browser_visible_falso(self, client):
        r = client.post("/settings", data={"ocultar_navegador_enviado": "1", "ocultar_navegador": "on",
                                            "provider_priority": ALL_PROVIDERS})
        assert r.status_code == 200
        assert load_site_config()["browser_visible"] is False

    def test_desmarcar_ocultar_salva_browser_visible_verdadeiro(self, client):
        client.post("/settings", data={"ocultar_navegador_enviado": "1", "provider_priority": ALL_PROVIDERS})
        assert load_site_config()["browser_visible"] is True
        html = client.get("/settings").get_data(as_text=True)
        assert 'name="ocultar_navegador" checked' not in html

    def test_formulario_antigo_com_browser_visible_continua_funcionando(self, client):
        client.post("/settings", data={"browser_visible": "on", "provider_priority": ALL_PROVIDERS})
        assert load_site_config()["browser_visible"] is True
        client.post("/settings", data={"provider_priority": ALL_PROVIDERS})
        assert load_site_config()["browser_visible"] is False

    def test_salva_as_opcoes_do_flow(self, client):
        client.post("/settings", data={
            "ocultar_navegador_enviado": "1", "ocultar_navegador": "on", "provider_priority": ALL_PROVIDERS,
            "flow_navegador": "edge", "flow_exe": "", "flow_timeout_seconds": "180",
        })
        cfg = load_site_config()
        assert (cfg["flow_navegador"], cfg["flow_timeout_seconds"]) == ("edge", 180)

    def test_formulario_sem_campos_do_flow_nao_apaga_o_que_ja_estava_salvo(self, client):
        save_site_config({"flow_navegador": "firefox", "flow_timeout_seconds": 90})
        client.post("/settings", data={"provider_priority": ALL_PROVIDERS})
        cfg = load_site_config()
        assert (cfg["flow_navegador"], cfg["flow_timeout_seconds"]) == ("firefox", 90)

    def test_pagina_mostra_as_opcoes_da_sessao_unica(self, client):
        html = client.get("/settings").get_data(as_text=True)
        assert 'name="flow_configurar_projeto" checked' in html      # padrão: ligado
        assert 'name="flow_seletor_configuracoes"' in html
        assert "MESMA conversa" in html

    def test_desmarcar_configurar_projeto_salva_falso(self, client):
        client.post("/settings", data={"provider_priority": ALL_PROVIDERS, "flow_navegador": "auto",
                                        "flow_seletor_configuracoes": "button.engrenagem"})
        cfg = load_site_config()
        assert cfg["flow_configurar_projeto"] is False
        assert cfg["flow_seletor_configuracoes"] == "button.engrenagem"

    def test_marcar_configurar_projeto_salva_verdadeiro(self, client):
        client.post("/settings", data={"provider_priority": ALL_PROVIDERS, "flow_navegador": "auto",
                                        "flow_configurar_projeto": "on"})
        assert load_site_config()["flow_configurar_projeto"] is True

    def test_formulario_antigo_sem_secao_do_flow_nao_mexe_em_configurar_projeto(self, client):
        save_site_config({"flow_configurar_projeto": False})
        client.post("/settings", data={"provider_priority": ALL_PROVIDERS})
        assert load_site_config()["flow_configurar_projeto"] is False

    def test_navegador_do_flow_invalido_mostra_erro(self, client):
        r = client.post("/settings", data={"provider_priority": ALL_PROVIDERS, "flow_navegador": "netscape"})
        assert "flow_navegador" in r.get_data(as_text=True)

    def test_prioridade_antiga_sem_flow_salva_sem_erro(self, client):
        antiga = ["pexels", "pixabay", "magnific", "mixkit", "vistacreate", "animepexels", "wikipedia"]
        r = client.post("/settings", data={"provider_priority": antiga})
        assert r.status_code == 200 and load_site_config()["provider_priority"][-4:] == ["flow", "moviepexels", "animepexels_online", "moviepexels_online"]


class TestPaginaInicialEPrompt:
    def test_flow_aparece_na_lista_de_bancos_mas_desmarcado(self, client):
        html = client.get("/").get_data(as_text=True)
        assert 'value="flow"' in html
        trecho = html[html.index('value="flow"'):][:120]
        assert "checked" not in trecho.split(">")[0]
        assert "Google Flow" in html

    def test_prompt_mostra_as_duas_opcoes_por_video_com_os_padroes_da_config(self, client, job):
        html = client.get(f"/job/{job['job_id']}/prompt").get_data(as_text=True)
        assert "Opções só deste vídeo" in html
        assert 'name="ocultar_navegador" checked' in html       # padrão: oculto
        assert 'name="nao_repetir_midia" checked' in html       # padrão: não repetir
        assert "fotos da Wikipedia podem repetir" in html

    def test_prompt_respeita_a_config_do_site_como_valor_inicial(self, client, job):
        save_site_config({"browser_visible": True, "evitar_repeticao_clipes": False})
        html = client.get(f"/job/{job['job_id']}/prompt").get_data(as_text=True)
        assert 'name="ocultar_navegador" checked' not in html
        assert 'name="nao_repetir_midia" checked' not in html

    def test_escolha_por_video_e_guardada_no_job(self, client, app_module, job, monkeypatch):
        monkeypatch.setattr(app_module, "_fetch_previews", lambda *a, **k: None)
        r = client.post(f"/job/{job['job_id']}/submit-json", data={
            "ai_response": _JSON_OK, "opcoes_job_enviadas": "1",  # os dois desmarcados
        })
        assert r.status_code == 302
        assert job["cfg_overrides"] == {"browser_visible": True, "evitar_repeticao_clipes": False}

    def test_marcando_as_duas_opcoes(self, client, app_module, job, monkeypatch):
        monkeypatch.setattr(app_module, "_fetch_previews", lambda *a, **k: None)
        client.post(f"/job/{job['job_id']}/submit-json", data={
            "ai_response": _JSON_OK, "opcoes_job_enviadas": "1",
            "ocultar_navegador": "on", "nao_repetir_midia": "on",
        })
        assert job["cfg_overrides"] == {"browser_visible": False, "evitar_repeticao_clipes": True}

    def test_sem_o_marcador_nao_mexe_nas_opcoes(self, client, app_module, job, monkeypatch):
        monkeypatch.setattr(app_module, "_fetch_previews", lambda *a, **k: None)
        client.post(f"/job/{job['job_id']}/submit-json", data={"ai_response": _JSON_OK})
        assert "cfg_overrides" not in job

    def test_json_invalido_reexibe_a_pagina_mantendo_as_escolhas(self, client, job):
        r = client.post(f"/job/{job['job_id']}/submit-json", data={
            "ai_response": "isto não é json", "opcoes_job_enviadas": "1", "nao_repetir_midia": "on",
        })
        html = r.get_data(as_text=True)
        assert r.status_code == 200 and "Opções só deste vídeo" in html
        assert 'name="ocultar_navegador" checked' not in html    # desmarcou "ocultar"
        assert 'name="nao_repetir_midia" checked' in html


class TestOverridesDoJob:
    def test_job_site_cfg_aplica_so_as_chaves_permitidas(self, app_module):
        cfg = app_module._job_site_cfg({"cfg_overrides": {
            "browser_visible": True, "evitar_repeticao_clipes": False,
            "orientation": "9:16", "provider_priority": ["x"],   # NÃO podem ser sobrescritas
        }})
        assert cfg["browser_visible"] is True and cfg["evitar_repeticao_clipes"] is False
        assert cfg["orientation"] == load_site_config()["orientation"]

    def test_job_site_cfg_ignora_valor_que_nao_e_booleano(self, app_module):
        base = load_site_config()
        cfg = app_module._job_site_cfg({"cfg_overrides": {"browser_visible": "sim"}})
        assert cfg["browser_visible"] == base["browser_visible"]

    def test_job_sem_overrides_usa_a_config_do_site(self, app_module):
        assert app_module._job_site_cfg({}) == load_site_config()

    def test_previas_usam_a_config_do_job_e_um_tracker_compartilhado(self, app_module, job, monkeypatch):
        recebidos = []

        def previa_falsa(segment, site_cfg=None, client_factory=None, used_tracker=None):
            recebidos.append((site_cfg["browser_visible"], used_tracker))
            return {"ok": True, "thumbnail_url": "t", "result_url": "u", "label": "l", "error": None,
                    "video_preview_url": None, "provider": segment.provider}

        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", previa_falsa)
        monkeypatch.setattr(app_module, "generate_waveform_image", lambda *a, **k: None)
        job["cfg_overrides"] = {"browser_visible": True, "evitar_repeticao_clipes": True}
        segs = [VideoSegment(start=float(i), end=float(i + 1), provider="pexels", query="x") for i in range(3)]
        app_module._fetch_previews(job["job_id"], job, segs)
        _esperar(lambda: job["status"] == "pronto_para_editar")

        assert len(recebidos) == 3
        assert all(visivel is True for visivel, _ in recebidos)
        trackers = {id(t) for _, t in recebidos}
        assert len(trackers) == 1 and isinstance(recebidos[0][1], UsedClipsTracker)

    def test_previas_sem_tracker_quando_nao_repetir_esta_desligado(self, app_module, job, monkeypatch):
        recebidos = []

        def previa_falsa(segment, site_cfg=None, client_factory=None, used_tracker=None):
            recebidos.append(used_tracker)
            return {"ok": True, "thumbnail_url": "t", "result_url": "u", "label": "l", "error": None,
                    "video_preview_url": None, "provider": segment.provider}

        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", previa_falsa)
        monkeypatch.setattr(app_module, "generate_waveform_image", lambda *a, **k: None)
        job["cfg_overrides"] = {"evitar_repeticao_clipes": False}
        segs = [VideoSegment(start=0.0, end=1.0, provider="pexels", query="x")]
        app_module._fetch_previews(job["job_id"], job, segs)
        _esperar(lambda: job["status"] == "pronto_para_editar")
        assert recebidos == [None]

    def test_montagem_recebe_a_config_do_job(self, app_module, job, monkeypatch):
        capturado = {}

        def montagem_falsa(**kwargs):
            capturado.update(kwargs)
            raise VideoAssemblyError("parou de propósito, só queríamos ver os argumentos")

        monkeypatch.setattr(app_module, "assemble_video", montagem_falsa)
        job["cfg_overrides"] = {"browser_visible": True, "evitar_repeticao_clipes": False}
        segs = [VideoSegment(start=0.0, end=8.0, provider="pexels", query="x")]
        app_module._start_assembly(job["job_id"], job, segs)
        _esperar(lambda: "site_cfg" in capturado)
        assert capturado["site_cfg"]["browser_visible"] is True
        assert capturado["site_cfg"]["evitar_repeticao_clipes"] is False


class TestBuscaDoEditorRespeitaOVideo:
    def test_botao_buscar_do_editor_usa_a_config_do_video(self, client, app_module, job, monkeypatch):
        recebido = {}

        def busca_falsa(provider, query, media_type="video", max_results=6, site_cfg=None, **kw):
            recebido["cfg"] = site_cfg
            return []

        monkeypatch.setattr(app_module, "search_candidates", busca_falsa)
        job["cfg_overrides"] = {"browser_visible": True}
        r = client.post(f"/job/{job['job_id']}/search-candidates",
                        json={"query": "gato", "provider": "pexels", "media_type": "video"})
        assert r.status_code == 200
        assert recebido["cfg"]["browser_visible"] is True


def _esperar(condicao, limite=15):
    fim = time.time() + limite
    while time.time() < fim:
        if condicao():
            return
        time.sleep(0.05)
    raise TimeoutError("condição não ficou verdadeira a tempo")


class TestCapturaDePaginaOculta:
    def _iniciar(self, client, app_module, monkeypatch):
        chamadas = []

        def captura_falsa(url, pasta, headless=True, **kw):
            chamadas.append(headless)
            raise app_module.WebpageCaptureError("parou de propósito")

        monkeypatch.setattr(app_module, "capturar_pagina", captura_falsa)
        r = client.post("/capturar-pagina", data={"url": "https://exemplo.com"})
        assert r.status_code == 200
        _esperar(lambda: chamadas)
        return chamadas[0]

    def test_por_padrao_roda_oculta(self, client, app_module, monkeypatch):
        assert self._iniciar(client, app_module, monkeypatch) is True

    def test_janela_visivel_quando_a_config_manda(self, client, app_module, monkeypatch):
        save_site_config({"browser_visible": True})
        assert self._iniciar(client, app_module, monkeypatch) is False

    def test_capturar_pagina_repassa_headless_ao_playwright(self, monkeypatch):
        import types
        import webpage_capture as wc
        lancamentos = []

        class Chromium:
            def launch(self, headless=True, **kw):
                lancamentos.append(headless)
                raise RuntimeError("parou de propósito")

        class Manager:
            def __enter__(self):
                return types.SimpleNamespace(chromium=Chromium())

            def __exit__(self, *a):
                pass

        modulo = types.ModuleType("playwright.sync_api")
        modulo.sync_playwright = lambda: Manager()
        monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
        monkeypatch.setitem(sys.modules, "playwright.sync_api", modulo)
        for valor in (True, False):
            with pytest.raises(Exception):
                wc.capturar_pagina("https://exemplo.com", "/tmp/nao-usado", headless=valor)
        assert lancamentos == [True, False]
        with pytest.raises(Exception):
            wc.capturar_pagina("https://exemplo.com", "/tmp/nao-usado")  # padrão continua oculto
        assert lancamentos[-1] is True


class TestRotasDoFlow:
    def test_serve_imagem_gerada(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("GOOGLEFLOW_DATA_DIR", str(tmp_path / "flow_dados"))
        gf.pasta_imagens().mkdir(parents=True)
        (gf.pasta_imagens() / "flow_abc_1.png").write_bytes(b"PNGDADOS")
        r = client.get("/flow/imagens/flow_abc_1.png")
        assert r.status_code == 200 and r.data == b"PNGDADOS"

    def test_imagem_inexistente_da_404(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("GOOGLEFLOW_DATA_DIR", str(tmp_path / "flow_dados"))
        gf.pasta_imagens().mkdir(parents=True)
        assert client.get("/flow/imagens/nao_existe.png").status_code == 404

    def test_nao_deixa_sair_da_pasta_de_imagens(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("GOOGLEFLOW_DATA_DIR", str(tmp_path / "flow_dados"))
        gf.pasta_imagens().mkdir(parents=True)
        (tmp_path / "flow_dados" / "segredo.txt").write_text("sessao")
        assert client.get("/flow/imagens/../segredo.txt").status_code == 404
        assert client.get("/flow/imagens/..%2Fsegredo.txt").status_code == 404

    def test_login_abre_o_cliente_e_o_status_vira_ok(self, client, app_module, monkeypatch):
        chamadas = []

        class ClienteFalso:
            def __init__(self, site_cfg=None, **kw):
                chamadas.append(site_cfg)

            def login_interativo(self):
                return True

        monkeypatch.setattr(gf, "GoogleFlowClient", ClienteFalso)
        app_module._FLOW_LOGIN.update({"status": "ocioso", "erro": None})
        assert client.post("/flow/login").status_code == 200
        _esperar(lambda: app_module._FLOW_LOGIN["status"] == "ok")
        assert client.get("/flow/login/status").get_json()["status"] == "ok"
        assert len(chamadas) == 1

    def test_login_com_erro_aparece_no_status(self, client, app_module, monkeypatch):
        class ClienteFalso:
            def __init__(self, **kw):
                pass

            def login_interativo(self):
                raise gf.GoogleFlowLoginRequired("Tempo esgotado esperando o login")

        monkeypatch.setattr(gf, "GoogleFlowClient", ClienteFalso)
        app_module._FLOW_LOGIN.update({"status": "ocioso", "erro": None})
        client.post("/flow/login")
        _esperar(lambda: app_module._FLOW_LOGIN["status"] == "erro")
        assert "Tempo esgotado" in client.get("/flow/login/status").get_json()["erro"]

    def test_segundo_login_enquanto_o_primeiro_espera_da_409(self, client, app_module):
        app_module._FLOW_LOGIN.update({"status": "aguardando_login", "erro": None})
        try:
            assert client.post("/flow/login").status_code == 409
        finally:
            app_module._FLOW_LOGIN.update({"status": "ocioso", "erro": None})


# ======================================================================
# 7. Várias contas do Google Flow (tela + rotas)
# ======================================================================

@pytest.fixture
def dados_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLEFLOW_DATA_DIR", str(tmp_path / "flow_dados"))
    return tmp_path / "flow_dados"


class TestContasDoFlow:
    def test_settings_tem_os_campos_de_limite_e_um_link_pra_pagina_de_contas(self, client, dados_flow):
        html = client.get("/settings").get_data(as_text=True)
        assert 'name="flow_horas_ate_liberar"' in html and 'name="flow_palavras_limite"' in html
        assert 'href="/contas-google"' in html
        assert 'id="flow-contas"' not in html   # a tabela em si não mora mais aqui

    def test_pagina_contas_google_tem_a_tabela_e_as_acoes(self, client, dados_flow):
        html = client.get("/contas-google").get_data(as_text=True)
        assert 'id="flow-contas"' in html and 'id="flow-conta-add"' in html
        assert "termos do Google" in html   # o aviso de risco está na tela
        assert "e.preventDefault()" in html  # Enter no campo não envia o formulário inteiro

    def test_salva_horas_e_palavras_extras_pela_tela(self, client, dados_flow):
        client.post("/settings", data={"provider_priority": ALL_PROVIDERS, "flow_navegador": "auto",
                                        "flow_horas_ate_liberar": "12", "flow_palavras_limite": "zerou"})
        cfg = load_site_config()
        assert cfg["flow_horas_ate_liberar"] == 12 and cfg["flow_palavras_limite"] == "zerou"

    def test_lista_comeca_so_com_a_principal(self, client, dados_flow):
        contas = client.get("/flow/contas").get_json()
        assert [c["nome"] for c in contas] == ["principal"]
        assert contas[0]["esgotada"] is False and contas[0]["logada"] is False

    def test_adicionar_conta(self, client, dados_flow):
        r = client.post("/flow/contas", json={"nome": "maria@gmail.com"})
        assert r.status_code == 200
        assert [c["nome"] for c in r.get_json()] == ["principal", "maria@gmail.com"]
        assert [c["nome"] for c in client.get("/flow/contas").get_json()] == ["principal", "maria@gmail.com"]

    @pytest.mark.parametrize("corpo", [{"nome": ""}, {"nome": "tem espaço"}, {}, {"nome": "principal"}])
    def test_adicionar_conta_invalida_ou_duplicada_da_400(self, client, dados_flow, corpo):
        r = client.post("/flow/contas", json=corpo)
        assert r.status_code == 400 and r.get_json()["erro"]

    def test_remover_conta_e_proteger_a_principal(self, client, dados_flow):
        client.post("/flow/contas", json={"nome": "b"})
        r = client.post("/flow/contas/b/remover")
        assert r.status_code == 200 and [c["nome"] for c in r.get_json()] == ["principal"]
        assert client.post("/flow/contas/principal/remover").status_code == 400
        assert client.post("/flow/contas/fantasma/remover").status_code == 400

    def test_marcar_e_liberar_esgotada_a_mao(self, client, dados_flow):
        client.post("/flow/contas", json={"nome": "b"})
        r = client.post("/flow/contas/b/esgotada", json={"esgotada": True})
        por_nome = {c["nome"]: c for c in r.get_json()}
        assert por_nome["b"]["esgotada"] is True and por_nome["principal"]["esgotada"] is False
        r = client.post("/flow/contas/b/esgotada", json={"esgotada": False})
        assert {c["nome"]: c for c in r.get_json()}["b"]["esgotada"] is False
        assert client.post("/flow/contas/fantasma/esgotada", json={"esgotada": True}).status_code == 400

    def test_esgotada_a_mao_usa_as_horas_da_config(self, client, dados_flow):
        from datetime import datetime, timedelta
        save_site_config({"flow_horas_ate_liberar": 3})
        client.post("/flow/contas", json={"nome": "b"})
        r = client.post("/flow/contas/b/esgotada", json={"esgotada": True})
        ate = datetime.fromisoformat({c["nome"]: c for c in r.get_json()}["b"]["esgotada_ate"])
        assert timedelta(hours=2, minutes=59) < ate - datetime.now() < timedelta(hours=3, minutes=1)

    def test_login_de_uma_conta_especifica_passa_a_conta_ao_cliente(self, client, app_module, dados_flow, monkeypatch):
        client.post("/flow/contas", json={"nome": "b"})
        chamadas = []

        class ClienteFalso:
            def __init__(self, site_cfg=None, **kw):
                pass

            def login_interativo(self, conta="principal"):
                chamadas.append(conta)
                return True

        monkeypatch.setattr(gf, "GoogleFlowClient", ClienteFalso)
        app_module._FLOW_LOGIN.update({"status": "ocioso", "erro": None})
        assert client.post("/flow/login", json={"conta": "b"}).status_code == 200
        _esperar(lambda: app_module._FLOW_LOGIN["status"] == "ok")
        assert chamadas == ["b"]

    def test_login_de_conta_inexistente_da_400_e_nao_abre_navegador(self, client, app_module, dados_flow, monkeypatch):
        monkeypatch.setattr(gf, "GoogleFlowClient", lambda **kw: pytest.fail("não devia criar o cliente"))
        app_module._FLOW_LOGIN.update({"status": "ocioso", "erro": None})
        r = client.post("/flow/login", json={"conta": "fantasma"})
        assert r.status_code == 400 and app_module._FLOW_LOGIN["status"] == "ocioso"

    def test_login_sem_conta_continua_sendo_a_principal(self, client, app_module, dados_flow, monkeypatch):
        chamadas = []

        class ClienteFalso:
            def __init__(self, site_cfg=None, **kw):
                pass

            def login_interativo(self):        # assinatura antiga, sem "conta"
                chamadas.append("principal")
                return True

        monkeypatch.setattr(gf, "GoogleFlowClient", ClienteFalso)
        app_module._FLOW_LOGIN.update({"status": "ocioso", "erro": None})
        client.post("/flow/login")
        _esperar(lambda: app_module._FLOW_LOGIN["status"] == "ok")
        assert chamadas == ["principal"]


# ======================================================================
# 8. Login automático (e-mail por conta + senha no keyring)
# ======================================================================

class FakeKeyringSite:
    def __init__(self):
        self.dados = {}

    def set_password(self, s, c, senha):
        self.dados[(s, c)] = senha

    def get_password(self, s, c):
        return self.dados.get((s, c))

    def delete_password(self, s, c):
        self.dados.pop((s, c), None)


@pytest.fixture
def fake_keyring_site(monkeypatch):
    modulo = FakeKeyringSite()
    monkeypatch.setitem(sys.modules, "keyring", modulo)
    return modulo


class TestLoginAutomatico:
    def test_tela_explica_o_login_automatico_e_tem_campo_de_email(self, client, dados_flow):
        html = client.get("/contas-google").get_data(as_text=True)
        assert 'id="flow-conta-email"' in html
        assert "cofre de credenciais" in html and "nunca num arquivo do projeto" in html

    def test_adicionar_conta_com_email(self, client, dados_flow):
        r = client.post("/flow/contas", json={"nome": "maria", "email": "maria@gmail.com"})
        assert {c["nome"]: c for c in r.get_json()}["maria"]["email"] == "maria@gmail.com"

    def test_definir_email_de_conta_existente(self, client, dados_flow):
        client.post("/flow/contas", json={"nome": "b"})
        r = client.post("/flow/contas/b/email", json={"email": "b@gmail.com"})
        assert {c["nome"]: c for c in r.get_json()}["b"]["email"] == "b@gmail.com"

    def test_email_invalido_da_400(self, client, dados_flow):
        assert client.post("/flow/contas", json={"nome": "x", "email": "sem-arroba"}).status_code == 400

    def test_salvar_senha_sem_keyring_da_400(self, client, dados_flow):
        client.post("/flow/contas", json={"nome": "b"})
        r = client.post("/flow/contas/b/senha", json={"senha": "123"})
        assert r.status_code == 400 and "keyring" in r.get_json()["erro"]

    def test_salvar_e_remover_senha_via_rota(self, client, dados_flow, fake_keyring_site):
        client.post("/flow/contas", json={"nome": "b"})
        r = client.post("/flow/contas/b/senha", json={"senha": "abc123"})
        assert r.status_code == 200 and {c["nome"]: c for c in r.get_json()}["b"]["tem_senha_salva"] is True
        r = client.post("/flow/contas/b/senha/remover")
        assert {c["nome"]: c for c in r.get_json()}["b"]["tem_senha_salva"] is False

    def test_salvar_senha_sem_informar_da_400(self, client, dados_flow, fake_keyring_site):
        client.post("/flow/contas", json={"nome": "b"})
        assert client.post("/flow/contas/b/senha", json={}).status_code == 400

    def test_login_com_senha_chama_login_automatico_e_pode_salvar_a_senha(self, client, app_module, dados_flow, fake_keyring_site, monkeypatch):
        chamadas = []

        class ClienteFalso:
            def __init__(self, site_cfg=None, **kw):
                pass

            def login_automatico(self, conta, email, senha):
                chamadas.append((conta, email, senha))
                return True

        monkeypatch.setattr(gf, "GoogleFlowClient", ClienteFalso)
        client.post("/flow/contas", json={"nome": "b"})
        app_module._FLOW_LOGIN.update({"status": "ocioso", "erro": None})
        r = client.post("/flow/login", json={"conta": "b", "email": "b@gmail.com", "senha": "segredo", "salvar_senha": True})
        assert r.status_code == 200
        _esperar(lambda: app_module._FLOW_LOGIN["status"] == "ok")
        assert chamadas == [("b", "b@gmail.com", "segredo")]
        assert gf.obter_senha("b") == "segredo"

    def test_a_senha_digitada_nunca_aparece_na_resposta_da_rota(self, client, app_module, dados_flow, fake_keyring_site, monkeypatch):
        monkeypatch.setattr(gf, "GoogleFlowClient", lambda **kw: type("C", (), {"login_automatico": lambda self, *a: True})())
        client.post("/flow/contas", json={"nome": "b"})
        app_module._FLOW_LOGIN.update({"status": "ocioso", "erro": None})
        r = client.post("/flow/login", json={"conta": "b", "email": "b@gmail.com", "senha": "segredo-super-secreto"})
        assert "segredo-super-secreto" not in r.get_data(as_text=True)

    def test_login_sem_senha_e_sem_senha_salva_continua_manual(self, client, app_module, dados_flow, fake_keyring_site, monkeypatch):
        chamadas = []

        class ClienteFalso:
            def __init__(self, **kw):
                pass

            def login_interativo(self, conta):
                chamadas.append(conta)
                return True

        monkeypatch.setattr(gf, "GoogleFlowClient", ClienteFalso)
        client.post("/flow/contas", json={"nome": "b"})
        app_module._FLOW_LOGIN.update({"status": "ocioso", "erro": None})
        client.post("/flow/login", json={"conta": "b"})
        _esperar(lambda: app_module._FLOW_LOGIN["status"] == "ok")
        assert chamadas == ["b"]

    def test_login_sem_senha_mas_com_senha_salva_usa_login_automatico_sozinho(self, client, app_module, dados_flow, fake_keyring_site, monkeypatch):
        chamadas = []

        class ClienteFalso:
            def __init__(self, **kw):
                pass

            def login_automatico(self, conta, email, senha):
                chamadas.append((conta, email, senha))
                return True

        monkeypatch.setattr(gf, "GoogleFlowClient", ClienteFalso)
        client.post("/flow/contas", json={"nome": "b", "email": "b@gmail.com"})
        gf.salvar_senha("b", "senha-salva")
        app_module._FLOW_LOGIN.update({"status": "ocioso", "erro": None})
        client.post("/flow/login", json={"conta": "b"})   # só o nome da conta, nada mais
        _esperar(lambda: app_module._FLOW_LOGIN["status"] == "ok")
        assert chamadas == [("b", "b@gmail.com", "senha-salva")]

    def test_senha_sem_email_cadastrado_da_400(self, client, dados_flow, fake_keyring_site):
        client.post("/flow/contas", json={"nome": "b"})   # sem e-mail
        r = client.post("/flow/login", json={"conta": "b", "senha": "abc"})
        assert r.status_code == 400 and "e-mail cadastrado" in r.get_json()["erro"]


# ======================================================================
# 9. Página dedicada, troca de senha real e exportar/importar contas (JSON)
# ======================================================================

class TestPaginaContasGoogleNavegacao:
    def test_link_no_menu_global_aponta_pra_pagina(self, client, dados_flow):
        html = client.get("/").get_data(as_text=True)
        assert 'href="/contas-google"' in html and "Contas Google" in html

    def test_pagina_tem_o_aviso_de_exportar_texto_puro(self, client, dados_flow):
        html = client.get("/contas-google").get_data(as_text=True)
        assert "texto puro" in html
        assert 'href="/flow/contas/exportar"' in html
        assert 'id="flow-importar-btn"' in html


class TestTrocarSenhaReal:
    def test_troca_senha_chama_o_cliente_com_a_senha_atual_e_marca_status_ok(self, client, app_module, dados_flow, fake_keyring_site, monkeypatch):
        chamadas = []

        class ClienteFalso:
            def __init__(self, site_cfg=None, **kw):
                pass

            def trocar_senha(self, conta, senha_atual, nova_senha=None):
                chamadas.append((conta, senha_atual, nova_senha))
                return "novaSenha1"

        monkeypatch.setattr(gf, "GoogleFlowClient", ClienteFalso)
        client.post("/flow/contas", json={"nome": "b", "email": "b@gmail.com"})
        r = client.post("/flow/contas/b/trocar-senha", json={"senha_atual": "antiga123"})
        assert r.status_code == 200
        _esperar(lambda: app_module._FLOW_TROCAR_SENHA["status"] == "ok")
        assert chamadas == [("b", "antiga123", None)]
        assert app_module._FLOW_TROCAR_SENHA["conta"] == "b"

    def test_troca_senha_aceita_senha_nova_escolhida(self, client, app_module, dados_flow, fake_keyring_site, monkeypatch):
        chamadas = []
        monkeypatch.setattr(gf, "GoogleFlowClient", lambda **kw: type(
            "C", (), {"trocar_senha": lambda self, conta, senha_atual, nova_senha=None: chamadas.append((conta, senha_atual, nova_senha)) or (nova_senha or "x")}
        )())
        client.post("/flow/contas", json={"nome": "b", "email": "b@gmail.com"})
        client.post("/flow/contas/b/trocar-senha", json={"senha_atual": "antiga123", "nova_senha": "minhaescolhida1"})
        _esperar(lambda: app_module._FLOW_TROCAR_SENHA["status"] == "ok")
        assert chamadas == [("b", "antiga123", "minhaescolhida1")]

    def test_troca_senha_sem_senha_atual_da_400(self, client, dados_flow):
        client.post("/flow/contas", json={"nome": "b"})
        r = client.post("/flow/contas/b/trocar-senha", json={})
        assert r.status_code == 400 and "senha atual" in r.get_json()["erro"]

    def test_troca_senha_de_conta_inexistente_da_400(self, client, dados_flow):
        r = client.post("/flow/contas/fantasma/trocar-senha", json={"senha_atual": "x"})
        assert r.status_code == 400

    def test_erro_na_troca_aparece_no_status(self, client, app_module, dados_flow, fake_keyring_site, monkeypatch):
        class ClienteFalso:
            def __init__(self, **kw):
                pass

            def trocar_senha(self, conta, senha_atual, nova_senha=None):
                raise gf.GoogleFlowError("O Google pediu captcha.")

        monkeypatch.setattr(gf, "GoogleFlowClient", ClienteFalso)
        client.post("/flow/contas", json={"nome": "b", "email": "b@gmail.com"})
        client.post("/flow/contas/b/trocar-senha", json={"senha_atual": "x"})
        _esperar(lambda: app_module._FLOW_TROCAR_SENHA["status"] == "erro")
        assert "captcha" in client.get("/flow/trocar-senha/status").get_json()["erro"]

    def test_segunda_troca_enquanto_a_primeira_roda_da_409(self, client, app_module, dados_flow):
        client.post("/flow/contas", json={"nome": "b", "email": "b@gmail.com"})
        app_module._FLOW_TROCAR_SENHA.update({"status": "trocando", "erro": None, "conta": "b"})
        try:
            r = client.post("/flow/contas/b/trocar-senha", json={"senha_atual": "x"})
            assert r.status_code == 409
        finally:
            app_module._FLOW_TROCAR_SENHA.update({"status": "ocioso", "erro": None, "conta": None})

    def test_senha_atual_nunca_aparece_na_resposta_da_rota(self, client, app_module, dados_flow, fake_keyring_site, monkeypatch):
        monkeypatch.setattr(gf, "GoogleFlowClient", lambda **kw: type("C", (), {"trocar_senha": lambda self, *a, **k: "x"})())
        client.post("/flow/contas", json={"nome": "b", "email": "b@gmail.com"})
        r = client.post("/flow/contas/b/trocar-senha", json={"senha_atual": "segredo-super-secreto"})
        assert "segredo-super-secreto" not in r.get_data(as_text=True)


class TestExportarImportarContas:
    def test_exportar_so_inclui_contas_com_senha_salva(self, client, dados_flow, fake_keyring_site):
        client.post("/flow/contas", json={"nome": "com-senha", "email": "a@gmail.com"})
        client.post("/flow/contas", json={"nome": "sem-senha", "email": "b@gmail.com"})
        gf.salvar_senha("com-senha", "abc123senha")
        r = client.get("/flow/contas/exportar")
        assert r.status_code == 200
        dados = r.get_json()["contas"]
        assert dados == [{"nome": "com-senha", "email": "a@gmail.com", "senha": "abc123senha"}]

    def test_exportar_agora_inclui_a_principal_se_ela_tiver_senha_salva(self, client, dados_flow, fake_keyring_site):
        gf.definir_email(gf.CONTA_PADRAO, "eu@gmail.com")
        gf.salvar_senha(gf.CONTA_PADRAO, "senhaDaPrincipal1")
        dados = client.get("/flow/contas/exportar").get_json()["contas"]
        assert dados == [{"nome": "principal", "email": "eu@gmail.com", "senha": "senhaDaPrincipal1"}]

    def test_exportar_tem_content_disposition_de_download(self, client, dados_flow):
        r = client.get("/flow/contas/exportar")
        assert "attachment" in r.headers.get("Content-Disposition", "") and "contas_flow.json" in r.headers["Content-Disposition"]

    def test_importar_cria_contas_novas_com_email_e_senha(self, client, dados_flow, fake_keyring_site):
        r = client.post("/flow/contas/importar", json={"contas": [
            {"nome": "maria", "email": "maria@gmail.com", "senha": "s3nhaforte1"},
            {"nome": "joao", "email": "joao@gmail.com", "senha": "outraSenha2"},
        ]})
        assert r.status_code == 200
        body = r.get_json()
        assert set(body["importadas"]) == {"maria", "joao"} and body["erros"] == []
        por_nome = {c["nome"]: c for c in body["contas"]}
        assert por_nome["maria"]["email"] == "maria@gmail.com" and por_nome["maria"]["tem_senha_salva"] is True
        assert gf.obter_senha("maria") == "s3nhaforte1"

    def test_importar_conta_existente_so_atualiza_email_e_senha_sem_duplicar(self, client, dados_flow, fake_keyring_site):
        client.post("/flow/contas", json={"nome": "maria", "email": "velho@gmail.com"})
        r = client.post("/flow/contas/importar", json={"contas": [{"nome": "maria", "email": "novo@gmail.com", "senha": "abc"}]})
        contas = r.get_json()["contas"]
        assert [c["nome"] for c in contas].count("maria") == 1
        assert {c["nome"]: c for c in contas}["maria"]["email"] == "novo@gmail.com"

    def test_importar_sem_senha_so_atualiza_email(self, client, dados_flow, fake_keyring_site):
        r = client.post("/flow/contas/importar", json={"contas": [{"nome": "maria", "email": "maria@gmail.com"}]})
        assert r.get_json()["importadas"] == ["maria"]
        assert gf.obter_senha("maria") is None

    def test_importar_formato_invalido_da_400(self, client, dados_flow):
        r = client.post("/flow/contas/importar", json={"nao_e_contas": []})
        assert r.status_code == 400

    def test_importar_entrada_invalida_vai_pra_lista_de_erros_sem_parar_as_outras(self, client, dados_flow, fake_keyring_site):
        r = client.post("/flow/contas/importar", json={"contas": [
            {"nome": "sem-arroba", "email": "email-invalido"},  # e-mail inválido -- deve dar erro
            {"nome": "valida", "email": "v@gmail.com", "senha": "abc123senha"},
        ]})
        body = r.get_json()
        assert body["importadas"] == ["valida"]
        assert len(body["erros"]) == 1 and "sem-arroba" in body["erros"][0]

    def test_importar_conta_principal_funciona(self, client, dados_flow, fake_keyring_site):
        r = client.post("/flow/contas/importar", json={"contas": [
            {"nome": "principal", "email": "eu@gmail.com", "senha": "senhaDaPrincipal1"},
        ]})
        body = r.get_json()
        assert body["importadas"] == ["principal"] and body["erros"] == []
        assert gf.obter_senha("principal") == "senhaDaPrincipal1"
        assert {c["nome"]: c for c in body["contas"]}["principal"]["email"] == "eu@gmail.com"

    def test_importar_item_sem_nome_e_ignorado_silenciosamente(self, client, dados_flow, fake_keyring_site):
        r = client.post("/flow/contas/importar", json={"contas": [{"email": "sem-nome@gmail.com"}]})
        assert r.get_json() == {"contas": [c for c in r.get_json()["contas"]], "importadas": [], "erros": []}

    def test_ciclo_completo_exportar_e_importar_preserva_os_dados(self, client, dados_flow, fake_keyring_site):
        client.post("/flow/contas", json={"nome": "b", "email": "b@gmail.com"})
        gf.salvar_senha("b", "senhaOriginal1")
        exportado = client.get("/flow/contas/exportar").get_json()

        gf.remover_conta("b")  # simula "perdeu tudo" / outra máquina
        assert client.post("/flow/contas/importar", json=exportado).get_json()["importadas"] == ["b"]
        assert gf.obter_senha("b") == "senhaOriginal1"
        assert {c["nome"]: c for c in gf.listar_contas()}["b"]["email"] == "b@gmail.com"


# ======================================================================
# 10. Modelo padrão de vídeo do Flow (configuração, não geração)
# ======================================================================

class TestModeloVideoFlow:
    def test_default_e_veo_lite(self):
        assert DEFAULT_CONFIG["flow_modelo_video"] == "Veo 3.1 - Lite"

    def test_precisa_ser_texto(self, config_path):
        with pytest.raises(SiteConfigError, match="flow_modelo_video"):
            save_site_config({"flow_modelo_video": 5}, config_path)

    def test_e_aparado_e_vazio_e_permitido(self, config_path):
        assert save_site_config({"flow_modelo_video": "  Veo 3.1 - Quality  "}, config_path)["flow_modelo_video"] == "Veo 3.1 - Quality"
        assert save_site_config({"flow_modelo_video": ""}, config_path)["flow_modelo_video"] == ""

    def test_tela_tem_o_campo_com_as_sugestoes_conhecidas(self, client):
        html = client.get("/settings").get_data(as_text=True)
        assert 'name="flow_modelo_video"' in html
        assert "Veo 3.1 - Lite" in html and "Veo 3.1 - Quality" in html and "Omni 1.1 Flash" in html
        assert "ainda não gera vídeo pelo Flow" in html

    def test_salva_o_modelo_pela_tela(self, client):
        client.post("/settings", data={"provider_priority": ALL_PROVIDERS, "flow_navegador": "auto",
                                        "flow_modelo_video": "Veo 3.1 - Fast"})
        assert load_site_config()["flow_modelo_video"] == "Veo 3.1 - Fast"

    def test_formulario_antigo_sem_o_campo_nao_apaga_o_que_ja_estava_salvo(self, client):
        save_site_config({"flow_modelo_video": "Veo 3.1 - Quality"})
        client.post("/settings", data={"provider_priority": ALL_PROVIDERS})
        assert load_site_config()["flow_modelo_video"] == "Veo 3.1 - Quality"


# ======================================================================
# 11. Cadastrar conta + login automático num só formulário
# ======================================================================

class TestFormularioUnicoDeCadastroELogin:
    def test_pagina_tem_o_campo_de_senha_e_salvar_no_formulario_do_topo(self, client, dados_flow):
        html = client.get("/contas-google").get_data(as_text=True)
        assert 'id="flow-conta-senha"' in html
        assert 'id="flow-conta-salvar-senha"' in html
        assert "Adicionar conta" in html and "Adicionar e entrar" not in html  # rótulo não promete demais quando a senha fica em branco
        assert "cadastra a conta, faz o login sozinho" in html

    def test_rotulo_e_opcional_e_o_email_entra_como_rotulo_no_backend(self, client, dados_flow):
        # a página deixa o rótulo em branco por padrão possível (JS usa o e-mail);
        # aqui confirmamos que o backend aceita o e-mail como nome de conta direto,
        # que é exatamente o que o JS manda quando o campo de rótulo fica vazio.
        r = client.post("/flow/contas", json={"nome": "maria@gmail.com", "email": "maria@gmail.com"})
        assert r.status_code == 200
        por_nome = {c["nome"]: c for c in r.get_json()}
        assert por_nome["maria@gmail.com"]["email"] == "maria@gmail.com"

    def test_senha_no_cadastro_ainda_nao_e_salva_sem_a_pessoa_marcar_salvar(self, client, dados_flow, fake_keyring_site):
        # o cadastro em si (POST /flow/contas) nunca recebe nem guarda senha --
        # quem guarda é o /flow/login, chamado à parte pelo JS.
        client.post("/flow/contas", json={"nome": "maria@gmail.com", "email": "maria@gmail.com"})
        assert gf.obter_senha("maria@gmail.com") is None


# ======================================================================
# 12. Ver a senha salva (botão "👁 Ver senha") + conta principal com e-mail/senha
# ======================================================================

class TestVerSenhaSalva:
    def test_ver_senha_devolve_a_senha_salva(self, client, dados_flow, fake_keyring_site):
        client.post("/flow/contas", json={"nome": "b", "email": "b@gmail.com"})
        gf.salvar_senha("b", "abc123senha")
        r = client.get("/flow/contas/b/senha")
        assert r.status_code == 200 and r.get_json()["senha"] == "abc123senha"

    def test_ver_senha_sem_senha_salva_da_404(self, client, dados_flow, fake_keyring_site):
        client.post("/flow/contas", json={"nome": "b"})
        r = client.get("/flow/contas/b/senha")
        assert r.status_code == 404

    def test_ver_senha_de_conta_inexistente_da_400(self, client, dados_flow):
        assert client.get("/flow/contas/fantasma/senha").status_code == 400

    def test_ver_senha_da_principal_funciona_como_qualquer_outra(self, client, dados_flow, fake_keyring_site):
        gf.salvar_senha(gf.CONTA_PADRAO, "senhaDaPrincipal1")
        r = client.get("/flow/contas/principal/senha")
        assert r.status_code == 200 and r.get_json()["senha"] == "senhaDaPrincipal1"

    def test_status_da_troca_de_senha_devolve_a_senha_nova_gerada(self, client, app_module, dados_flow, fake_keyring_site, monkeypatch):
        monkeypatch.setattr(gf, "GoogleFlowClient", lambda **kw: type(
            "C", (), {"trocar_senha": lambda self, conta, senha_atual, nova_senha=None: "gerada1234"}
        )())
        client.post("/flow/contas", json={"nome": "b", "email": "b@gmail.com"})
        app_module._FLOW_TROCAR_SENHA.update({"status": "ocioso", "erro": None, "conta": None, "nova_senha": None})
        client.post("/flow/contas/b/trocar-senha", json={"senha_atual": "antiga123"})
        _esperar(lambda: app_module._FLOW_TROCAR_SENHA["status"] == "ok")
        assert client.get("/flow/trocar-senha/status").get_json()["nova_senha"] == "gerada1234"

    def test_pagina_tem_o_botao_de_ver_senha(self, client, dados_flow):
        html = client.get("/contas-google").get_data(as_text=True)
        assert "👁 Ver senha" in html


class TestContaPrincipalComoQualquerOutra:
    def test_email_da_principal_aparece_editavel_na_tela_em_vez_de_travessao(self, client, dados_flow):
        html = client.get("/contas-google").get_data(as_text=True)
        assert "—" not in html.split('id="flow-contas"')[1].split("</table>")[0]

    def test_botao_trocar_senha_no_google_aparece_tambem_pra_principal(self, client, app_module, dados_flow, monkeypatch):
        # a UI não filtra mais por nome -- confirma chamando a rota de troca pra "principal" direto
        monkeypatch.setattr(gf, "GoogleFlowClient", lambda **kw: type(
            "C", (), {"trocar_senha": lambda self, *a, **k: "x"}
        )())
        app_module._FLOW_TROCAR_SENHA.update({"status": "ocioso", "erro": None, "conta": None, "nova_senha": None})
        r = client.post("/flow/contas/principal/trocar-senha", json={"senha_atual": "x"})
        assert r.status_code == 200

    def test_definir_email_da_principal_pela_rota(self, client, dados_flow):
        r = client.post("/flow/contas/principal/email", json={"email": "eu@gmail.com"})
        assert {c["nome"]: c for c in r.get_json()}["principal"]["email"] == "eu@gmail.com"

    def test_arquivo_antigo_sem_a_principal_na_lista_continua_funcionando(self, client, dados_flow):
        import json as _json
        gf.pasta_dados().mkdir(parents=True, exist_ok=True)
        gf.arquivo_contas().write_text(_json.dumps({"contas": ["maria"], "esgotadas": {}}), encoding="utf-8")
        contas = client.get("/flow/contas").get_json()
        assert [c["nome"] for c in contas] == ["principal", "maria"]


class TestEstadoDeixaClaroQuandoNaoTemSenhaSalva:
    def test_conta_logada_sem_senha_avisa_na_tela(self, client, dados_flow):
        client.post("/flow/contas", json={"nome": "b", "email": "b@gmail.com"})
        (gf.pasta_perfis() / "chrome--b").mkdir(parents=True, exist_ok=True)
        (gf.arquivo_sessao("b")).write_text("{}", encoding="utf-8")
        html = client.get("/contas-google").get_data(as_text=True)
        assert "sem senha salva" in html


class TestSalvarSenhaVemMarcadoPorPadrao:
    def test_checkbox_do_formulario_do_topo_vem_marcado(self, client, dados_flow):
        html = client.get("/contas-google").get_data(as_text=True)
        trecho = html[html.index('id="flow-conta-salvar-senha"'):][:60]
        assert "checked" in trecho

    def test_js_do_mini_formulario_por_linha_tambem_marca_por_padrao(self, client, dados_flow):
        html = client.get("/contas-google").get_data(as_text=True)
        assert "cbSalvar.checked = true" in html


class TestAvisoDeKeyringAusente:
    def test_aviso_aparece_quando_keyring_nao_esta_instalado(self, client, dados_flow, monkeypatch):
        # simula a máquina sem o pacote keyring (em alguns ambientes ele vem
        # instalado como dependência de outra coisa)
        monkeypatch.setattr(gf, "keyring_disponivel", lambda: False)
        html = client.get("/contas-google").get_data(as_text=True)
        assert "pip install keyring" in html
        assert "não está instalado" in html

    def test_aviso_some_quando_keyring_esta_disponivel(self, client, dados_flow, fake_keyring_site):
        html = client.get("/contas-google").get_data(as_text=True)
        assert "pip install keyring" not in html
