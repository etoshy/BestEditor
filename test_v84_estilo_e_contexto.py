"""v84_92 — 🎞️ vídeo de imagens REAIS sem desenho no meio + 🧭 buscas com o contexto da fala de antes e de depois.

Antes: num vídeo quase todo de fotos reais, o Pexels trazia boneco 3D em fundo branco, seta de gráfico desenhada,
dinheiro 3D em fundo preto, hospital vetorial… e as buscas da IA saíam de palavras soltas da frase.
Agora: (1) a miniatura de cada candidato é olhada (sem IA) e desenho/3D/vetor/recorte vai pro fim da fila — se a busca
só tem isso, tenta a próxima busca e os outros bancos; (2) a ficha da IA diz o estilo do vídeo e o juiz dá no máximo 2
pra ilustração; (3) quem escreve as buscas recebe a fala de antes e a de depois."""
import json

import numpy as np
import pytest
from PIL import Image, ImageDraw

import estilo_imagem as ei
import ia_midia
import video_assembler as va
from prompt_builder import VideoSegment, build_prompt


# ------------------------------------------------------------------ imagens de teste
def _recorte_branco():
    im = Image.new("RGB", (400, 260), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.ellipse((150, 40, 250, 140), fill=(230, 180, 140))
    d.rectangle((140, 140, 260, 250), fill=(40, 90, 160))
    return im


def _recorte_preto():
    im = Image.new("RGB", (400, 260), (0, 0, 0))
    ImageDraw.Draw(im).rectangle((120, 90, 280, 170), fill=(90, 160, 90))
    return im


def _vetor():
    im = Image.new("RGB", (400, 260), (230, 230, 230))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 200, 400, 260), fill=(245, 190, 120))
    d.rectangle((60, 120, 300, 150), fill=(130, 180, 210))
    d.rectangle((310, 60, 360, 200), fill=(60, 70, 80))
    return im


def _foto():
    rng = np.random.default_rng(1)
    y, x = np.mgrid[0:260, 0:400]
    base = np.stack([x * 0.5 + 40, y * 0.6 + 60, (x + y) * 0.2 + 30], -1)
    return Image.fromarray(np.clip(base + rng.normal(0, 18, base.shape), 0, 255).astype("uint8"))


def _foto_escura():  # céu noturno / espaço: borda preta mas com ruído e estrelas — é foto real
    rng = np.random.default_rng(2)
    a = np.clip(rng.normal(14, 9, (260, 400, 3)), 0, 255)
    for _ in range(300):
        a[rng.integers(0, 260), rng.integers(0, 400)] = 255
    return Image.fromarray(a.astype("uint8"))


def test_classifica_desenho_e_recorte_mas_nao_foto_real():
    assert ei.classificar(_recorte_branco()) == "recorte_fundo_branco"
    assert ei.classificar(_recorte_preto()) == "recorte_fundo_preto"
    assert ei.classificar(_vetor()) == "ilustracao_chapada"
    assert ei.classificar(_foto()) == "" and ei.classificar(_foto_escura()) == ""


def test_modo_real_pela_config_e_pela_ficha():
    assert ei.modo_real({}) and ei.modo_real({"estilo_imagens": "auto"}) and ei.modo_real({"estilo_imagens": "real"})
    assert not ei.modo_real({"estilo_imagens": "qualquer"})
    assert not ei.modo_real({"_estilo_ficha": "ilustracao"}) and not ei.modo_real({"_estilo_ficha": "misto"})
    assert ei.modo_real({"estilo_imagens": "real", "_estilo_ficha": "ilustracao"})  # "sempre real" vale mais


def test_ordena_os_candidatos_e_marca():
    cands = [{"id": "a", "thumbnail": "u/3d"}, {"id": "b", "thumbnail": "u/real"}, {"id": "c", "thumbnail": "u/vetor"},
             {"id": "d", "thumbnail": "u/real2"}]
    fn = lambda u: "recorte_fundo_branco" if u in ("u/3d", "u/vetor") else ""  # noqa: E731
    out = ei.ordenar_candidatos(cands, {}, classificar_fn=fn)
    assert [c["id"] for c in out] == ["b", "d", "a", "c"] and out[2]["estilo_problema"] == "recorte_fundo_branco"
    assert "estilo_problema" not in cands[0]  # não mexe na lista original
    assert ei.ordenar_candidatos(cands, {"estilo_imagens": "qualquer"}, classificar_fn=fn) == cands


def test_url_com_cache_e_erro_de_rede_nao_pune():
    import io
    buf = io.BytesIO()
    _recorte_branco().save(buf, "JPEG", quality=80)
    chamadas = []

    def baixar(url, t):
        chamadas.append(url)
        return buf.getvalue()
    url = "https://cdn.exemplo/x-%d.jpg" % id(chamadas)
    assert ei.classificar_url(url, baixar=baixar) == "recorte_fundo_branco"
    assert ei.classificar_url(url, baixar=baixar) == "recorte_fundo_branco" and len(chamadas) == 1

    def falha(url, t):
        raise OSError("sem rede")
    assert ei.classificar_url("https://cdn.exemplo/fora.jpg", baixar=falha) == ""


def _seg(**kw):
    d = dict(start=0.0, end=4.0, provider="pexels", query="men friends hugging")
    d.update(kw)
    return VideoSegment(**d)


def test_previa_pula_o_desenho(monkeypatch):
    tabela = {"men friends hugging": [{"id": "1", "thumbnail": "t/3d", "url": "http://p/3d", "label": "3d dance"},
                                      {"id": "2", "thumbnail": "t/real", "url": "http://p/real", "label": "friends hug"}],
              "friends hug real": [{"id": "3", "thumbnail": "t/real3", "url": "http://p/real3", "label": "hug"}],
              "so desenho": [{"id": "4", "thumbnail": "t/3d4", "url": "http://p/3d4", "label": "3d"}]}
    pedidos = []

    def busca(provider, query, max_results=1, **kw):
        pedidos.append((provider, query, max_results))
        return [dict(c) for c in tabela.get(query, [])]
    monkeypatch.setattr(va, "search_candidates", busca)
    monkeypatch.setattr(ei, "classificar_url", lambda u, t=6.0, baixar=None: "recorte_fundo_branco" if "3d" in u else "")
    r = va.fetch_segment_preview_lightweight(_seg(), site_cfg={"provider_priority": ["pexels"]})
    assert r["ok"] and r["result_url"] == "http://p/real" and not r["label"].startswith("⚠")
    assert pedidos[0][2] >= 6  # pede alguns a mais pra poder pular
    # a busca só tem desenho: tenta a próxima (alternativa) antes de aceitar
    monkeypatch.setattr(va, "_fallback_queries_for", lambda s: ["friends hug real"])
    r = va.fetch_segment_preview_lightweight(_seg(query="so desenho"), site_cfg={"provider_priority": ["pexels"]})
    assert r["result_url"] == "http://p/real3"
    # nada real em lugar nenhum: usa o desenho, com ⚠
    monkeypatch.setattr(va, "_fallback_queries_for", lambda s: [])
    r = va.fetch_segment_preview_lightweight(_seg(query="so desenho"), site_cfg={"provider_priority": ["pexels"]})
    assert r["ok"] and r["result_url"] == "http://p/3d4" and r["label"].startswith("⚠")
    # "qualquer estilo": como antes (1 resultado, o 1º)
    pedidos.clear()
    r = va.fetch_segment_preview_lightweight(_seg(), site_cfg={"provider_priority": ["pexels"], "estilo_imagens": "qualquer"})
    assert r["result_url"] == "http://p/3d" and pedidos[0][2] == 1


def test_acervo_de_anime_nao_passa_pelo_filtro(monkeypatch):
    monkeypatch.setattr(va, "search_candidates", lambda p, q, max_results=1, **kw: [
        {"id": "1", "thumbnail": "t/anime", "url": "http://a/1", "label": "Gojo"}])
    olhou = []
    monkeypatch.setattr(ei, "classificar_url", lambda u, t=6.0, baixar=None: olhou.append(u) or "ilustracao_chapada")
    r = va.fetch_segment_preview_lightweight(_seg(provider="animepexels", query="gojo"), site_cfg={"provider_priority": ["animepexels"]})
    assert r["result_url"] == "http://a/1" and not r["label"].startswith("⚠") and olhou == []
    assert va._ordenar_resultados_estilo([1, 2], "animepexels") == [1, 2]


def test_montagem_tambem_ordena(monkeypatch):
    class R:
        def __init__(self, i, thumb):
            self.id, self._t = i, thumb

        def to_dict(self):
            return {"id": self.id, "thumbnail": self._t}
    monkeypatch.setattr(va, "load_site_config", lambda: {"estilo_imagens": "auto"})
    monkeypatch.setattr(ei, "classificar_url", lambda u, t=6.0, baixar=None: "recorte_fundo_branco" if "3d" in u else "")
    out = va._ordenar_resultados_estilo([R("a", "t/3d"), R("b", "t/real")], "pexels")
    assert [r.id for r in out] == ["b", "a"]


# ------------------------------------------------------------------ IA: ficha, juiz e contexto
def test_ficha_e_juiz_sabem_do_estilo():
    assert "estilo_imagem" in ia_midia.SCHEMA_FICHA["properties"] and "estilo_imagem" in ia_midia.SCHEMA_FICHA["required"]
    assert "ilustracao_ou_3d" in ia_midia.PROBLEMAS
    assert "no MÁXIMO 2" in ia_midia._SYS_JUIZ and "boneco" in ia_midia._SYS_JUIZ
    assert "fala de ANTES e a de DEPOIS" in ia_midia._SYS_BUSCAS and '"cartoon"' in ia_midia._SYS_BUSCAS


def test_buscas_recebem_antes_e_depois(monkeypatch):
    enviados = []
    monkeypatch.setattr(ia_midia.ia, "ativo", lambda r=None: True)
    monkeypatch.setattr(ia_midia.ia, "chamar", lambda rec, system, txt, *a, **k: enviados.append(txt) or
                        {"trechos": [{"n": 2, "buscas": ["man counting cash at night"], "midia": "video", "real": False,
                                      "visual": "", "frase_tela": ""}]})
    out = ia_midia.buscas_melhores([{"n": 2, "fala": "ele ganhou 6 mil numa noite", "antes": "o golpista abriu a mesa",
                                     "depois": "e a polícia nem desconfiou"}], {"estilo_imagem": "real"})
    assert out[2]["buscas"] == ["man counting cash at night"]
    assert "antes: o golpista abriu a mesa | FALA: ele ganhou 6 mil numa noite | depois: e a polícia nem desconfiou" in enviados[0]


def test_preparar_buscas_manda_vizinhos(monkeypatch):
    import app as A
    import ia_servico
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: True)
    monkeypatch.setattr(ia_midia, "ficha_visual", lambda *a, **k: {"estilo_imagem": "real"})
    recebidos = []
    monkeypatch.setattr(ia_midia, "buscas_melhores", lambda trechos, *a, **k: recebidos.extend(trechos) or {})
    job = {"segments": [{"start": 0, "end": 4, "text": "O golpista abriu a mesa."}, {"start": 4, "end": 8, "text": "Ganhou seis mil."},
                        {"start": 8, "end": 12, "text": "Ninguém desconfiou."}],
           "pending_segments": [{"start": k * 4.0, "end": k * 4.0 + 4, "query": f"q{k}"} for k in range(3)]}
    segs = [_seg(start=k * 4.0, end=k * 4.0 + 4, query=f"q{k}") for k in range(3)]
    A._ia_preparar_buscas("jx", job, segs)
    meio = next(t for t in recebidos if t["n"] == 2)
    assert "golpista" in meio["antes"] and "seis mil" in meio["fala"] and "desconfiou" in meio["depois"]
    assert recebidos[0]["antes"] == "" and recebidos[-1]["depois"] == ""
    assert A._job_site_cfg(job)["_estilo_ficha"] == "real"


def test_prompt_principal_e_configuracoes():
    p = build_prompt([{"start": 0.0, "end": 4.0, "text": "teste"}], providers=["pexels"])
    assert "CENA daquele momento" in p and '"isolated on white"' in p
    import app as A
    import site_config
    assert site_config.DEFAULT_CONFIG["estilo_imagens"] == "auto"
    h = A.app.test_client().get("/settings").get_data(as_text=True)
    assert 'name="estilo_imagens"' in h
