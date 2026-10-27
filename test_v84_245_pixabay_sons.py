"""v84_245: 🔊 teste dos efeitos sonoros do Pixabay — busca/paginação, leitura da página, forma de onda → onde está o
som, links .mp3 (JSON da página ou clicando no ▶), baixar, cortar o silêncio e a ficha no formato da base de sons.
+ 🎭 react: o personagem escuta a frase do vídeo até o fim antes de falar."""
import json
import os
import subprocess

import pytest

import pixabay_sons as PS

AQUI = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(AQUI, "testes_dados", "pixabay_busca.html")


def test_url_da_busca_e_paginas():
    assert PS.url_busca("whoosh tall") == "https://pixabay.com/pt/sound-effects/search/whoosh%20tall/"
    assert PS.url_busca("  whoosh   tall ", 3) == "https://pixabay.com/pt/sound-effects/search/whoosh%20tall/?pagi=3"
    assert PS.id_do_link("/pt/sound-effects/filme-e-efeitos-especiais-swoosh-1-376872/") == "376872"
    assert PS.slug("Whoosh Blow Flutter Short.wav") == "whoosh_blow_flutter_short_wav"


def test_le_as_linhas_da_pagina_real():
    r = PS.ler_resultados(open(FIXTURE, encoding="utf-8").read())
    assert [x["id"] for x in r] == ["376872", "386134", "376880"]
    a = r[0]
    assert a["titulo"] == "Swoosh 1" and a["autor"] == "DRAGON-STUDIO" and a["tema"] == "Filme e efeitos especiais"
    assert a["tags"] == ["Efeito Sonoro Whoosh"] and a["curtidas"] == 309 and a["capa"].startswith("https://cdn.pixabay.com/")
    assert len(a["onda"]) == PS.LARGURA_ONDA and 0.2 < a["onde"]["inicio"] < a["onde"]["pico"] < a["onde"]["fim"] < 0.4


def test_forma_de_onda_sintetica():
    # silêncio até x=100, som forte de 100 a 150, silêncio depois
    d = "M0 15L100 15L110 2L125 0L150 15L369 15L369 16L150 16L125 31L110 29L100 16L0 16Z"
    env = PS.envelope_da_onda(d)
    o = PS.onde_esta_o_som(env)
    assert env[50] == 0 and env[125] == 1.0
    assert abs(o["inicio"] - 101 / 369) < 0.01 and abs(o["pico"] - 125 / 369) < 0.01 and abs(o["fim"] - 150 / 369) < 0.01
    assert PS.onde_esta_o_som([0.0] * 10) is None


def test_mp3_no_json_da_pagina_em_qualquer_formato():
    dados = {"page": {"results": [{"id": 376872, "sources": {"src": "https://cdn.pixabay.com/audio/2025/07/18/audio_aaa.mp3"}},
                                   {"id": "386134", "x": [{"url": "https://cdn.pixabay.com/download/audio/2025/01/01/audio_bbb.mp3?filename=x"}]},
                                   {"id": "999", "src": "https://cdn.pixabay.com/audio/zzz.mp3"}]}}
    r = PS.mp3_por_id(dados, ["376872", "386134"])
    assert r == {"376872": "https://cdn.pixabay.com/audio/2025/07/18/audio_aaa.mp3",
                 "386134": "https://cdn.pixabay.com/download/audio/2025/01/01/audio_bbb.mp3"}


def _som(caminho, sil_ini=1.0, som=0.4, sil_fim=1.5):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={sil_ini}",
                    "-f", "lavfi", "-i", f"sine=frequency=800:sample_rate=44100:duration={som}", "-f", "lavfi",
                    "-i", f"anullsrc=r=44100:cl=stereo:d={sil_fim}", "-filter_complex",
                    "[1:a]aformat=channel_layouts=stereo[s];[0:a][s][2:a]concat=n=3:v=0:a=1", "-c:a", "libmp3lame", "-q:a", "4",
                    str(caminho)], check=True, capture_output=True)
    return str(caminho)


def test_corta_o_silencio_das_pontas(tmp_path):
    mp3 = _som(tmp_path / "s.mp3")
    m = PS.medir(mp3)
    assert abs(m["inicio_som"] - 1.0) < 0.06 and abs(m["fim_som"] - 1.4) < 0.08 and m["dur"] > 2.8
    f = PS.cortar_silencio(mp3, str(tmp_path / "c.m4a"))
    assert 0.45 < f["dur"] < 0.7 and f["inicio_som"] < 0.1 and abs(f["corte_de"] - 0.97) < 0.07
    assert os.path.isfile(PS.espectrograma(str(tmp_path / "c.m4a"), str(tmp_path / "e.png")))
    it = PS.item_da_base(dict(f, id="376872", titulo="Swoosh 1", tags=["Whoosh"], pagina="p", autor="a", mp3="u",
                              ficha={"nome": "Swoosh rápido", "categoria": "passagem", "descricao": "d", "usos": ["u"], "tags": ["t"]}), "x.m4a")
    assert it["id"] == "pixabay/376872" and it["categoria"] == "passagem" and it["nome"] == "Swoosh rápido" and it["arquivo"] == "x.m4a"
    assert set(("dur", "inicio_som", "pico", "fim_som", "nivel_db")) <= set(it)


def test_navegador_ponta_a_ponta_sem_internet(tmp_path):
    """O site é simulado (as requests do pixabay.com/cdn são respondidas aqui): o 1º som vem do JSON da página, os
    outros clicando no ▶ — baixa, corta e grava o catálogo."""
    pytest.importorskip("playwright")
    import pixabay_sons_teste as T
    mp3 = open(_som(tmp_path / "base.mp3", 0.5, 0.3, 0.8), "rb").read()
    html = open(FIXTURE, encoding="utf-8").read()
    pedidos = []

    def preparar(ctx):
        def pagina(route):
            pedidos.append(route.request.url)
            if "/bootstrap/" in route.request.url:
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps({"r": [{"id": 376872, "audio": "https://cdn.pixabay.com/audio/x/audio_boot.mp3"}]}))
            if "pagi=2" in route.request.url:
                return route.fulfill(status=200, content_type="text/html", body="<html><body>nenhum resultado</body></html>")
            return route.fulfill(status=200, content_type="text/html", body=html)
        ctx.route("https://pixabay.com/**", pagina)
        ctx.route("https://cdn.pixabay.com/**", lambda route: route.fulfill(status=200, content_type="audio/mpeg", body=mp3))

    pasta = tmp_path / "sons"
    rc = T.rodar(T.argparse.Namespace(termo="whoosh tall", paginas=2, limite=3, pasta=str(pasta), oculto=True, chrome=False,
                                      ia=False, sem_baixar=False, html=None), preparar_ctx=preparar)
    assert rc == 0
    assert any("search/whoosh%20tall/?pagi=2" in u for u in pedidos)
    cat = json.load(open(pasta / "catalogo.json", encoding="utf-8"))
    assert [x["id"] for x in cat] == ["376872", "386134", "376880"]
    assert cat[0]["mp3"].endswith("audio_boot.mp3") and cat[1]["mp3"].endswith("audio_teste1.mp3")
    assert all(os.path.isfile(x["arquivo_cortado"]) and x["dur"] < x["dur_original"] for x in cat)
    base = json.load(open(pasta / "base_sons.json", encoding="utf-8"))
    assert len(base) == 3 and base[0]["fonte"]["site"] == "pixabay"


# ------------------------------------------------------------------ 👂 react: escuta a frase até o fim antes de falar
def test_react_fala_depois_de_ouvir(tmp_path, monkeypatch):
    monkeypatch.setenv("REACT_PERSONAGENS_DIR", str(tmp_path / "react"))
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(tmp_path / "pod"))
    import react_personagens as R
    p = R.criar("Teste", str(tmp_path))
    R.novo_personagem(p, "Itachi", obra="Naruto")
    p["video"] = {"duracao": 60.0}
    p["transcricao"] = [{"ini": 10.0, "fim": 14.0, "texto": "mil anos de espera", "tipo": "fala"},
                        {"ini": 20.0, "fim": 40.0, "texto": "verso enorme", "tipo": "fala"},
                        {"ini": 5.0, "fim": 9.0, "texto": "Cantor X", "tipo": "credito"}]
    assert p["escutar"] is True
    R.aplicar_roteiro(p, {"falas": [{"tempo": 11.5, "personagem": "Itachi", "texto": "Arrepiei com esse verso.", "expressao": "chocado",
                                     "pedido_inscricao": True, "reacoes": []},
                                    {"tempo": 22, "personagem": "Itachi", "texto": "Longo demais pra esperar.", "expressao": "neutro",
                                     "pedido_inscricao": False, "reacoes": []},
                                    {"tempo": 6, "personagem": "Itachi", "texto": "Crédito não conta.", "expressao": "neutro",
                                     "pedido_inscricao": False, "reacoes": []}]})
    fs = {f["texto"]: f for f in p["roteiro"]["falas"]}
    assert fs["Arrepiei com esse verso."]["t"] == 14.3 and fs["Arrepiei com esse verso."]["t_ia"] == 11.5
    assert fs["Longo demais pra esperar."]["t"] == 22  # a frase é longa demais: não empurra 18 s
    assert fs["Crédito não conta."]["t"] == 6
    assert all(f["ouviu"] for f in p["roteiro"]["falas"])
    # 2ª passada não empurra de novo (é idempotente)
    assert [f["t"] for f in R.falas_no_tempo(p, p["roteiro"]["falas"], 60)] == [6, 14.3, 22]
    # projeto antigo (sem a marca): ajusta na hora de montar
    velhas = [dict(f, t=f.get("t_ia", f["t"])) for f in p["roteiro"]["falas"]]
    for f in velhas:
        f.pop("ouviu"), f.pop("t_ia", None)
    assert [f["t"] for f in R.falas_no_tempo(p, velhas, 60)] == [6, 14.3, 22]
    # desligado: volta pro segundo da IA
    p["escutar"] = False
    assert [f["t"] for f in R.falas_no_tempo(p, p["roteiro"]["falas"], 60)] == [6, 11.5, 22]
    assert "até o FIM" in R.sys_roteiro(p)
