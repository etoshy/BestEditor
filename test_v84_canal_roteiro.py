"""v84_95 — 📺 nome do canal nos roteiros, ✍️ roteiro/referência como GUIA (storytelling próprio), 🕵️ true crime com
fato × alegação × interpretação (fonte por afirmação) e frases em unidades de sentido, 🎬🏁 vídeos de abertura e
encerramento do canal (como os de inscreva-se/venda)."""
import os
import subprocess

import pytest

import canal
import chamadas as ch
import dossies as ds
import metodo_roteiro as mr
import roteiros_yt as ry
import site_config


# ------------------------------------------------------------------ blocos
def test_blocos_do_metodo():
    g = mr.bloco_guia("o meu roteiro")
    assert "GUIA" in g and "NÃO siga ponto a ponto" in g and "📏" in g
    assert "Mantenha mais ou menos o tamanho" in mr.bloco_guia("x", tem_tamanho=False)
    c = mr.bloco_canal("Casos Arquivados")
    assert "Casos Arquivados" in c and "depois do gancho".upper() in c.upper() and "nunca na 1ª frase" in c
    assert "no fim" in mr.bloco_canal("X", curto=True) and mr.bloco_canal("  ") == ""
    assert "UMA IDEIA POR FRASE" in mr.bloco("longo")
    assert "o original é só um guia" in mr.bloco("reescrita")
    assert "não como molde" in mr.bloco_referencia("abc").lower() or "não um molde" in mr.bloco_referencia("abc").lower() \
        or "inspiração, não molde" in mr.bloco_referencia("abc")


def test_nome_do_canal(monkeypatch, tmp_path):
    monkeypatch.setattr(site_config, "CONFIG_PATH", str(tmp_path / "site_config.json"))
    assert canal.nome_global() == ""
    site_config.save_site_config({"nome_canal": "  Casos   Arquivados "})
    assert canal.nome_global() == "Casos Arquivados"
    assert canal.nome_do_projeto("") == "Casos Arquivados"
    assert canal.nome_do_projeto("Outro Canal") == "Outro Canal"
    assert canal.nome_do_projeto("-") == ""


# ------------------------------------------------------------------ 🕵️ true crime
def _proj(**cfg):
    p = {"id": "abcdef0123", "tema": "O caso X", "roteiro_base": "Meu roteiro: começa na infância.", "fontes": [], "midias": [],
         "config": dict(ds.CONFIG_PADRAO, **cfg)}
    return p


def test_prompt_true_crime(monkeypatch):
    monkeypatch.setattr(canal, "nome_global", lambda: "Casos Arquivados")
    t = ds.prompt_roteiro(_proj())
    assert "FATO, ALEGAÇÃO E INTERPRETAÇÃO" in t and "segundo os autos" in t
    assert "UNIDADES DE SENTIDO" in t and "INFÂNCIA" in t and "AVALIAÇÕES MÉDICAS" in t and "INVESTIGAÇÃO POLICIAL" in t
    assert '"afirmacoes"' in t
    assert "Sua própria linha de storytelling" in t and "GUIA" in t
    assert "📺 Nome do canal: Casos Arquivados" in t
    assert "📺" not in ds.prompt_roteiro(_proj(nome_canal="-"))
    assert "📺 Nome do canal: Meu Canal" in ds.prompt_roteiro(_proj(nome_canal="Meu Canal"))
    # outro modelo: sem a lista de afirmações
    assert '"afirmacoes"' not in ds.prompt_roteiro(_proj(modelo="historia", formato="documentario"))


def test_ler_afirmacoes():
    p = _proj()
    res = ds.ler_resultado('{"roteiro": "Era 1998. Ele tinha 12 anos.", "afirmacoes": ['
                           '{"trecho": "Era 1998", "tipo": "fato", "fonte": "F1 — autos"},'
                           '{"trecho": "ele alegou", "tipo": "Alegação", "fonte": "defesa"},'
                           '{"trecho": "tudo indica", "tipo": "interpretação"}, {"tipo": "fato"}]}', p)
    assert [a["tipo"] for a in res["afirmacoes"]] == ["fato", "alegacao", "interpretacao"]
    assert res["afirmacoes"][2]["fonte"] == ""


# ------------------------------------------------------------------ 📜 roteiro do YouTube
def _p_yt(**k):
    return dict({"transcricao": {"blocos": [{"inicio": 0, "texto": "olá pessoal hoje vamos falar do caso"}], "titulo": "Vídeo"},
                 "titulo": "Vídeo"}, **k)


def test_prompt_roteiro_yt_guia_e_canal(monkeypatch):
    monkeypatch.setattr(canal, "nome_global", lambda: "Meu Canal")
    t = ry.prompt_analise(_p_yt(), ry.MODELOS_FABRICA[0])
    assert "Sua própria linha de storytelling" in t and "📺 Nome do canal: Meu Canal" in t
    assert "Mantenha mais ou menos o tamanho" in t  # sem ⏱: o tamanho do original
    t2 = ry.prompt_analise(_p_yt(minutos_alvo=18, modo_partes="nao"), ry.MODELOS_FABRICA[0])
    assert "O TAMANHO pedido" in t2 and "TAMANHO DO ROTEIRO" in t2
    assert "SUA própria linha de storytelling" in ry.MODELOS_FABRICA[0]["texto"]
    so = next(m for m in ry.MODELOS_FABRICA if m["id"] == "so_cenas")
    assert "Sua própria linha" not in ry.prompt_analise(_p_yt(), so) and "📺 Nome do canal" not in ry.prompt_analise(_p_yt(), so)
    curto = next(m for m in ry.MODELOS_FABRICA if m["id"] == "reescrever_curto")
    assert "UMA vez, no fim" in ry.prompt_analise(_p_yt(), curto)
    assert "canal ORIGINAL" in ry.REGRA_SEM_EXPERIENCIAS


# ------------------------------------------------------------------ 🎬🏁 abertura / encerramento
def _video(caminho, dur, cor="red"):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={cor}:s=320x180:d={dur}:r=30",
                    "-f", "lavfi", "-i", f"sine=f=440:d={dur}", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", caminho], check=True)
    return caminho


@pytest.fixture
def padrao(monkeypatch, tmp_path):
    monkeypatch.setattr(ch, "PASTA_PADRAO", str(tmp_path / "padrao"))
    return tmp_path


def test_vinhetas_padrao_e_do_job(padrao):
    ab = _video(str(padrao / "ab.mp4"), 1.0)
    assert canal.do_job({})["abertura"]["usar"] is False
    canal.definir_padrao("abertura", ab)
    assert canal.clipe_padrao("abertura") and canal.clipe_padrao("abertura") != ab  # uma cópia
    job = {}
    v = canal.do_job(job)
    assert v["abertura"]["usar"] and not v["abertura"]["proprio"] and not v["encerramento"]["usar"]
    cortes = canal.cortes_para_montagem(job)
    assert len(cortes) == 1 and cortes[0]["insertion_point"] == 0.0 and cortes[0]["audio_mode"] == "pause"
    job["vinhetas"] = {"abertura": {"usar": False}}
    assert canal.cortes_para_montagem(job) == []
    en = _video(str(padrao / "en.mp4"), 1.0, "blue")
    canal.guardar_no_job(job, "encerramento", str(padrao / "job"), en, "en.mp4")
    v = canal.do_job(job)
    assert v["encerramento"]["proprio"] and v["encerramento"]["usar"]
    assert canal.cortes_para_montagem(job)[0]["insertion_point"] == canal.FIM
    canal.definir_padrao("abertura", None)
    assert canal.clipe_padrao("abertura") is None
    with pytest.raises(ValueError):
        canal.definir_padrao("venda_x", ab)


def test_montagem_poe_abertura_e_encerramento(padrao):
    import video_assembler as va
    base = _video(str(padrao / "base.mp4"), 2.0, "green")
    canal.definir_padrao("abertura", _video(str(padrao / "ab.mp4"), 1.0))
    canal.definir_padrao("encerramento", _video(str(padrao / "en.mp4"), 1.5, "blue"))
    dur = va._probe_duration(base)
    cortes = [dict(c, insertion_point=min(c["insertion_point"], dur)) for c in canal.cortes_para_montagem({})]
    saida = str(padrao / "final.mp4")
    va.insert_cutaways(base, cortes, saida, str(padrao), 320, 180)
    assert abs(va._probe_duration(saida) - 4.5) < 0.3
    # a legenda anda junto: a palavra do segundo 0.5 vai pra 1.5
    sh = va.shift_timestamps_for_cutaways([{"start": 0.5, "end": 0.9}], [dict(c, duration=va._probe_duration(c["resolved_path"])) for c in cortes])
    assert abs(sh[0]["start"] - 1.5) < 0.1


@pytest.fixture
def A(monkeypatch, padrao):
    import app as _app
    _app.app.config["TESTING"] = True
    monkeypatch.setattr(site_config, "CONFIG_PATH", str(padrao / "site_config.json"))
    return _app


def test_rotas_configuracoes_e_editor(A, padrao, monkeypatch):
    import io
    c = A.app.test_client()
    h = c.get("/settings").get_data(as_text=True)
    assert 'name="nome_canal"' in h and 'action="/vinhetas/abertura"' in h and 'action="/vinhetas/encerramento"' in h
    r = c.post("/settings", data={"nome_canal": "Casos Arquivados"})
    assert r.status_code == 200 and site_config.load_site_config()["nome_canal"] == "Casos Arquivados"
    dados = open(_video(str(padrao / "ab.mp4"), 1.0), "rb").read()
    r = c.post("/vinhetas/abertura", data={"arquivo": (io.BytesIO(dados), "abertura.mp4")}, content_type="multipart/form-data")
    assert r.status_code == 302 and canal.clipe_padrao("abertura")
    assert c.get("/vinhetas/abertura/arquivo").status_code == 200
    assert "✔" in c.get("/settings").get_data(as_text=True)
    # no editor (aba ✂️ Cortes)
    monkeypatch.setattr(A, "_save_state", lambda *_a, **_k: None)
    A._JOBS["vh-job"] = {"job_id": "vh-job", "pending_segments": [], "cutaway_suggestions": []}
    d = c.post("/job/vh-job/vinhetas/abertura", json={"usar": False}).get_json()
    assert d["ok"] and d["vinhetas"]["abertura"]["usar"] is False
    assert canal.cortes_para_montagem(A._JOBS["vh-job"]) == []
    monkeypatch.setattr(A, "_job_dir", lambda jid: str(padrao / "jobs" / jid))
    r = c.post("/job/vh-job/vinhetas/encerramento", data={"arquivo": (io.BytesIO(dados), "fim.mp4"), "padrao": "on"},
               content_type="multipart/form-data")
    assert r.status_code == 302
    v = canal.do_job(A._JOBS["vh-job"])
    assert v["encerramento"]["proprio"] and v["encerramento"]["usar"] and canal.clipe_padrao("encerramento")
    assert c.post("/job/vh-job/vinhetas/xyz", json={}).status_code == 404
    r = c.post("/vinhetas/abertura", data={"remover": "on"})
    assert r.status_code == 302 and canal.clipe_padrao("abertura") is None
    A._JOBS.pop("vh-job", None)


def test_paginas_tem_o_campo_do_canal(A, tmp_path, monkeypatch):
    import modelados_rotas  # noqa: F401
    src = open(os.path.join(os.path.dirname(ds.__file__), "templates", "dossie_detalhe.html"), encoding="utf-8").read()
    assert 'id="cCanal"' in src and "Fatos, alegações e interpretações" in src
    src = open(os.path.join(os.path.dirname(ds.__file__), "templates", "roteiro_yt_detalhe.html"), encoding="utf-8").read()
    assert 'id="nomeCanal"' in src
    src = open(os.path.join(os.path.dirname(ds.__file__), "templates", "modelado_detalhe.html"), encoding="utf-8").read()
    assert 'id="cfg-canal"' in src
    src = open(os.path.join(os.path.dirname(ds.__file__), "templates", "estudio.html"), encoding="utf-8").read()
    assert "function desenharVinhetas" in src
