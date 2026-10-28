"""v84_253: 💬 Vídeos curtos de COMENTÁRIO — clipe cru + o que acontece → roteiro em inglês (+ português) com 5 ganchos e
5 finais, tags do Chatterbox, 3 takes, edição no próprio clipe (sem silêncio, 1º plano < 3 s), 🎯 destaque rastreado."""
import json
import os
import subprocess
import time

import pytest

import curtos as CT
import curtos_comentario as CC


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "curtos"))
    monkeypatch.setenv("RASTREIO_DIR", str(tmp_path / "rastreios"))
    monkeypatch.setenv("DP_EXTRAS_DIR", str(tmp_path / "extras"))
    import dp_extras
    dp_extras.recarregar()
    return str(tmp_path)


def _clipe(caminho, dur=10):
    """Um quadrado branco andando num fundo escuro (dá pra rastrear) + som."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x202830:s=360x640:d={dur}:r=24",
                    "-f", "lavfi", "-i", f"sine=f=330:d={dur}", "-filter_complex",
                    "[0:v]drawbox=x='40+t*20':y=300:w=60:h=60:c=white:t=fill[v]", "-map", "[v]", "-map", "1:a",
                    "-shortest", "-pix_fmt", "yuv420p", caminho], check=True)
    return caminho


RESPOSTA = {
    "titulo_video": "The cyclist and the sign", "descricao": "d", "hashtags": ["#cycling"],
    "roteiro_en": "…", "roteiro_pt": "…",
    "ganchos": [{"en": "[gasp] Everyone thought this cyclist was being rude.", "pt": "Todo mundo achou que esse ciclista era grosso."}]
               + [{"en": f"Hook {k}", "pt": f"Gancho {k}"} for k in range(2, 6)],
    "finais": [{"en": "Would you have done the same?", "pt": "Você faria o mesmo?"}]
              + [{"en": f"End {k}?", "pt": f"Final {k}?"} for k in range(2, 6)],
    "blocos": [
        {"funcao": "gancho", "fala_en": "[gasp] Everyone thought this cyclist was being rude.", "fala_pt": "Todo mundo achou que esse ciclista era grosso.",
         "cenas": [{"material": "M1", "de": 0, "ate": 4, "palavra": "", "efeito": "zoom_in", "entrada": "punch_in",
                    "destaque": {"alvo": "", "tipo": "", "texto": ""}}],
         "sfx": [{"tipo": "whoosh", "palavra": "", "busca": "whoosh"}]},
        {"funcao": "virada", "fala_en": "But he grabbed the white sign and gave it back to a little fan.",
         "fala_pt": "Mas ele pegou a placa branca e devolveu pra um fã pequeno.",
         "cenas": [{"material": "M1", "de": 4, "ate": 8, "palavra": "", "efeito": "", "entrada": "flash",
                    "destaque": {"alvo": "the white square sign", "tipo": "circulo", "texto": ""}}],
         "sfx": [{"tipo": "pop", "palavra": "sign", "busca": "pop"}]},
        {"funcao": "pergunta", "fala_en": "Would you have done the same?", "fala_pt": "Você faria o mesmo?",
         "cenas": [{"material": "M1", "de": 8, "ate": 10, "palavra": "", "efeito": "zoom_out", "entrada": "none",
                    "destaque": {"alvo": ""}}], "sfx": []},
    ]}


def _ia(resp=RESPOSTA):
    def chamar(recurso, sistema, conteudo, **kw):
        chamar.vistos.append((sistema, conteudo, kw))
        return json.loads(json.dumps(resp))
    chamar.vistos = []
    return chamar


def _projeto(base, tmp_path, linhas="0:00 o ciclista passa\n0:04 ele pega a placa\n0:08 o fã sorri"):
    p = CT.criar(base, "", "Ciclista", modelo="comentario")
    v = _clipe(str(tmp_path / "clipe.mp4"))
    with CT._TRAVA:
        q = CT.carregar(base, p["id"])
        CT.adicionar_midia(base, q, v, "video", "ciclista na corrida")
        CT.salvar(base, q)
    if linhas:
        CC.salvar_texto_do_clipe(base, p["id"], linhas)
    return p["id"]


def _tts(motor, texto, saida, **kw):
    assert motor or True
    _tts.textos.append(texto)
    n = len(CT.sem_tags(texto).split())
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f=300:d={0.33 * n + 0.2:.2f}", saida], check=True)


_tts.textos = []


def _whisper(base, pid, ritmo=0.33):
    def tr(audio, language=None, word_timestamps=True, info=None):
        tr.idiomas.append(language)
        p = CT.carregar(base, pid)
        ws, t = [], 0.1
        for b in p["roteiro"]["blocos"]:
            for w in CT.sem_tags(b["fala"]).split():
                ws.append({"word": w.strip(".,?!").lower(), "start": round(t, 3), "end": round(t + ritmo * 0.8, 3)})
                t += ritmo
            t += 0.12
        return [{"start": 0, "end": t, "text": "", "words": ws}]
    tr.idiomas = []
    return tr


VOZ = {"slug": "v1", "nome": "v1", "motor": "chatterbox_turbo", "config": {}}


# ------------------------------------------------------------------ o que acontece no clipe
def test_ler_linhas_formatos():
    ls = CC.ler_linhas("0:03 ele pega a placa\n[0:07] todo mundo vaia\n12s - o fã sorri\n0:15-0:18 fim\ncontinua aqui")
    assert [l["t0"] for l in ls] == [3, 7, 12, 15]
    assert ls[0]["t1"] == 7 and ls[3]["t1"] == 18 and ls[3]["texto"].endswith("continua aqui")
    srt = CC.ler_linhas("1\n00:00:01,500 --> 00:00:03,000\nHello there\n\n2\n00:00:03,000 --> 00:00:05,000\nGeneral Kenobi")
    assert [(l["t0"], l["texto"]) for l in srt] == [(1.5, "Hello there"), (3.0, "General Kenobi")]
    yt = CC.ler_linhas("0:00\nthis guy\n0:02\ngrabbed the sign")
    assert [l["t0"] for l in yt] == [0, 2] and yt[1]["texto"] == "grabbed the sign"
    assert CC.duracao_da_referencia("0:00 a\n0:10 b\n0:31 c") == 33.5


def test_prompt_tem_linha_do_tempo_referencia_e_tags(base, tmp_path):
    pid = _projeto(base, tmp_path)
    with CT._TRAVA:
        p = CT.carregar(base, pid)
        CC.dados(p)["referencia"] = "0:00 This cyclist\n0:20 the end"
        CT.salvar(base, p)
    pr = CC.prompt_roteiro(base, CT.carregar(base, pid))
    assert "[4.0s-8.0s] (note) ele pega a placa" in pr and "M1 — ciclista na corrida" in pr
    assert "This cyclist" in pr and "close to the reference" in pr and "[gasp]" in pr and "QUESTION" in pr


# ------------------------------------------------------------------ roteiro
def test_roteiro_en_pt_ganchos_finais(base, tmp_path):
    pid = _projeto(base, tmp_path)
    ia = _ia()
    r = CC.gerar_roteiro(base, pid, ia)
    assert ia.vistos and "schema" in ia.vistos[0][2]
    b = r["blocos"]
    assert b[0]["fala"].startswith("[gasp]") and b[0]["fala_pt"].startswith("Todo mundo")
    c = b[1]["cenas"][0]
    assert c["material"] == "M1" and c["de"] == 4 and c["ate"] == 8 and c["destaque"]["alvo"] == "the white square sign"
    assert len(r["ganchos"]) == 5 and len(r["finais"]) == 5
    CC.escolher(base, pid, "ganchos", 2)
    q = CT.carregar(base, pid)["roteiro"]
    assert q["blocos"][0]["fala"] == "Hook 3" and q["blocos"][0]["fala_pt"] == "Gancho 3" and q["ganchos_escolhido"] == 2
    CC.escolher(base, pid, "finais", 1)
    assert CT.carregar(base, pid)["roteiro"]["blocos"][-1]["fala"] == "End 2?"
    CC.trocar_idioma(base, pid, "pt")
    q = CT.carregar(base, pid)
    assert q["roteiro"]["blocos"][1]["fala"].startswith("Mas ele") and q["comentario"]["idioma"] == "pt"
    CC.trocar_idioma(base, pid, "en")
    novas = CC.mais_opcoes(base, pid, "ganchos", _ia({"opcoes": [{"en": "New hook", "pt": "Novo"}] * 5}))
    assert len(novas) == 5 and len(CT.carregar(base, pid)["roteiro"]["ganchos"]) == 10


def test_tamanho_vem_do_conteudo(base, tmp_path):
    pid = _projeto(base, tmp_path)
    pr = CC.prompt_roteiro(base, CT.carregar(base, pid))
    assert "the clip(s) last 10 s" in pr and "what this story needs" in pr and "45 seconds" not in pr
    with CT._TRAVA:
        p = CT.carregar(base, pid)
        p["config"]["duracao_alvo_s"] = 50
        CT.salvar(base, p)
    assert "about 50 seconds" in CC.prompt_roteiro(base, CT.carregar(base, pid))


def test_sem_o_que_acontece_pede_antes(base, tmp_path):
    pid = _projeto(base, tmp_path, linhas="")
    with pytest.raises(CT.CurtoErro):
        CC.gerar_roteiro(base, pid, _ia())


# ------------------------------------------------------------------ voz, edição e destaque
def test_takes_e_edicao_no_clipe(base, tmp_path):
    pid = _projeto(base, tmp_path)
    CC.gerar_roteiro(base, pid, _ia())
    _tts.textos.clear()
    takes = CC.gerar_takes(base, pid, _tts, lambda t, m: t, VOZ, 3)
    assert [t["take"] for t in takes] == [1, 2, 3] and len({t["arquivo"] for t in takes}) == 3
    assert all(os.path.isfile(os.path.join(CT.pasta(base, pid), t["arquivo"])) for t in takes)
    assert any(t.startswith("[gasp]") for t in _tts.textos)  # a tag vai pro Chatterbox
    wh = _whisper(base, pid)
    g = CC.usar_take(base, pid, 2, wh)
    assert g["fonte"] == "guia" and CT.carregar(base, pid)["take_escolhido"] == 2 and wh.idiomas == ["en"]
    d = CT.montar_dados_editor(base, pid)
    planos = d["planos"]
    assert all(x["provider"] == "material" and x["query"].startswith("M1@") for x in planos)
    assert planos[0]["end"] - planos[0]["start"] <= 3.1 and planos[0]["entrada"] == "punch_in"  # 1º plano curto, com zoom
    assert abs(planos[-1]["end"] - d["dur"]) < 0.01  # termina junto com a voz
    ini, fim = (float(v) for v in planos[0]["query"][3:].split("-"))
    assert ini == 0.0 and fim <= 4.01
    viradas = [x for x in planos if x["bloco"] == "B2"]
    assert float(viradas[0]["query"][3:].split("-")[0]) == 4.0  # a frase mostra o pedaço que ela conta
    assert d["sfx"] and d["sfx"][0]["start"] < 0.3  # whoosh no começo
    assert d["legendas"]["estilo"] == "palavra_unica"
    assert not any("[" in w["word"] for w in d["palavras"])
    # cortes/zoom/sons pelo contexto: só os do roteiro (nada de som em todo corte nem zoom alternando sozinho)
    assert len(planos) == 3 and [x["efeito"] for x in planos] == ["zoom_in", "", "zoom_out"]
    assert sorted(s["start"] < 0.3 for s in d["sfx"]).count(True) == 1 and len(d["sfx"]) == 2


def test_destaque_rastreado(base, tmp_path):
    pid = _projeto(base, tmp_path)
    CC.gerar_roteiro(base, pid, _ia())
    CC.gerar_takes(base, pid, _tts, lambda t, m: t, VOZ, 1)
    CC.usar_take(base, pid, 1, _whisper(base, pid))

    def ia_caixa(recurso, sistema, conteudo, **kw):  # a IA "acha" o quadrado (posição em 0,25 s do pedaço que começa em 4 s)
        x = (40 + 4.25 * 20) / 360
        return {"achou": True, "x": x, "y": 300 / 640, "w": 60 / 360, "h": 60 / 640}
    r = CC.preparar_destaques(base, pid, chamar=ia_caixa)
    assert len(r["feitos"]) == 1 and not r["pendentes"], r
    p = CT.carregar(base, pid)
    rid = r["feitos"][0]
    assert rid.startswith("R") and list(p["destaques_prontos"].values()) == [rid]
    d = CT.montar_dados_editor(base, pid)
    assert any(x.get("destaque_pronto") == rid and x["query"] == rid for x in d["planos"])
    assert CC.preparar_destaques(base, pid, chamar=ia_caixa)["feitos"] == [rid]  # não refaz
    nao = CC.preparar_destaques  # sem IA: fica pendente com o pedaço pra fazer à mão
    with CT._TRAVA:
        q = CT.carregar(base, pid)
        q["destaques_prontos"] = {}
        CT.salvar(base, q)
    r2 = nao(base, pid, chamar=lambda *a, **k: None)
    assert r2["pendentes"] and r2["pendentes"][0]["mid"] == "M1"


# ------------------------------------------------------------------ rotas
@pytest.fixture
def cliente(base, monkeypatch):
    import app as A
    monkeypatch.setattr(A, "BASE_DIR", base)
    monkeypatch.setattr(A, "_fetch_previews", lambda *a, **k: None)
    monkeypatch.setattr(A, "_job_dir", lambda j: os.path.join(base, "jobs", j))
    A.app.config["TESTING"] = True
    return A, A.app.test_client()


def _esperar(pid):
    import curtos_rotas as R
    for _ in range(600):
        t = R.TAREFAS.get(pid) or {}
        if t.get("fim"):
            return t
        time.sleep(0.05)
    raise AssertionError("a tarefa não terminou")


def test_menu_hub_e_pagina(cliente, base, tmp_path):
    _A, cl = cliente
    html = cl.get("/curtos").get_data(as_text=True)
    assert "Vídeos curtos (Shorts, TikTok, Reels)" in html and "/curtos/modelo/comentario" in html
    assert "Novo vídeo de comentário" in cl.get("/curtos/modelo/comentario").get_data(as_text=True)
    assert cl.get("/curtos/modelo/xyz").status_code == 404
    assert CT.canal_do_modelo(base, "comentario")
    v = _clipe(str(tmp_path / "c.mp4"), 4)
    with open(v, "rb") as f:
        r = cl.post("/curtos/novo", data={"modelo": "comentario", "titulo": "Clipe", "clipe": (f, "c.mp4"), "idioma": "en",
                                          "linhas": "0:01 ele pega a placa", "referencia": "0:00 this guy\n0:20 end"},
                    content_type="multipart/form-data")
    pid = r.headers["Location"].rsplit("/", 1)[1]
    p = CT.carregar(base, pid)
    assert p["modelo"] == "comentario" and p["canal_id"] == CT.canal_do_modelo(base, "comentario")
    assert p["midias"][0]["id"] == "M1" and p["comentario"]["linhas"][0]["t0"] == 1 and "this guy" in p["comentario"]["referencia"]
    assert p["config"]["motor_perfil"] == "chatterbox_turbo"
    pg = cl.get(f"/curtos/{pid}").get_data(as_text=True)
    assert "Ganchos" in pg or "ganchos" in pg
    assert "[gasp]" in pg
    assert cl.post(f"/curtos/{pid}/comentario/linhas", json={"mid": "M1", "texto": "0:02 o fã sorri"}).get_json()["linhas"] == 1
    assert "o fã sorri" in cl.get(f"/curtos/{pid}/roteiro/prompt").get_json()["prompt"]
    assert cl.post(f"/curtos/{pid}/roteiro", json={"resposta": json.dumps(RESPOSTA)}).get_json()["ok"]
    assert cl.post(f"/curtos/{pid}/comentario/escolher", json={"qual": "finais", "i": 3}).get_json()["ok"]
    assert CT.carregar(base, pid)["roteiro"]["blocos"][-1]["fala"] == "End 4?"
    # salvar da tela mantém os ganchos/finais
    r = CT.carregar(base, pid)["roteiro"]
    assert cl.post(f"/curtos/{pid}/roteiro", json={"roteiro": {"titulo_video": "x", "blocos": r["blocos"]}}).get_json()["ok"]
    assert len(CT.carregar(base, pid)["roteiro"]["ganchos"]) == 5
    assert "💬 Clipe" in cl.get("/curtos/modelo/comentario").get_data(as_text=True)


def test_fazer_tudo_comentario(cliente, base, tmp_path, monkeypatch):
    A, cl = cliente
    import curtos_rotas as R
    pid = _projeto(base, tmp_path)
    with CT._TRAVA:
        q = CT.carregar(base, pid)
        q["canal_id"] = CT.canal_do_modelo(base, "comentario")
        CT.salvar(base, q)
    monkeypatch.setitem(R.CB, "tts", _tts)
    monkeypatch.setitem(R.CB, "transcrever", _whisper(base, pid))
    orig = CC.gerar_roteiro
    monkeypatch.setattr(CC, "gerar_roteiro", lambda b, p, chamar=None: orig(b, p, _ia()))
    import anime2d
    monkeypatch.setattr(anime2d, "vozes_disponiveis", lambda mp="xtts": [{"slug": "perfil:teste", "nome": "t", "grupo": "g"}])
    r = cl.post(f"/curtos/{pid}/fazer-tudo", json={}).get_json()
    assert r["ok"], r
    t = _esperar(pid)
    assert not t["erro"], t["erro"]
    q = CT.carregar(base, pid)
    assert len(q["takes"]) == 3 and q["gravacao"]["fonte"] == "guia" and q["roteiro"]["ganchos"]
    job = A._JOBS[q["editor"]["job_id"]]
    assert job["pending_segments"] and all(s["provider"] == "material" for s in job["pending_segments"])
    assert job["legendas"]["estilo"] == "palavra_unica"
    # escolher outro take e o "trocar no editor" seguem funcionando
    assert cl.post(f"/curtos/{pid}/comentario/take", json={"k": 3}).get_json()["ok"]
    assert not _esperar(pid)["erro"]
    assert CT.carregar(base, pid)["take_escolhido"] == 3


# ------------------------------------------------------------------ link do vídeo + transcrição sem tempos
TRANSCRICAO_CORRIDA = ("A young boy accepted the dare to walk through his school without moving out of anyone's way. As he marched down "
                       "the hallway, he kept crashing into classmates. When this guy decided to walk through school like nobody else "
                       "existed, he thought it would be easy. [music] [music] I'm up at the right time. Money crazy.")


def test_transcricao_sem_tempos_vira_referencia(base, tmp_path):
    pid = _projeto(base, tmp_path, linhas="")
    assert not CC.tem_tempos(TRANSCRICAO_CORRIDA) and CC.tem_tempos("0:03 ele pega a placa")
    r = CC.salvar_o_que_acontece(base, pid, TRANSCRICAO_CORRIDA)
    p = CT.carregar(base, pid)
    assert r == {"linhas": 0, "referencia": True} and "young boy" in p["comentario"]["referencia"] and not p["comentario"]["linhas"]
    assert CC.sem_linha_do_tempo(p, "M1")
    CC.salvar_o_que_acontece(base, pid, TRANSCRICAO_CORRIDA)  # colar de novo não duplica
    assert CT.carregar(base, pid)["comentario"]["referencia"].count("young boy") == 1
    pr = CC.prompt_roteiro(base, CT.carregar(base, pid))
    assert "LYRICS of the background song" in pr and "young boy" in pr
    CC.gerar_roteiro(base, pid, _ia())  # só com a referência já dá pra escrever


def _baixador(origem):
    def b(url, pasta):
        b.urls.append(url)
        destino = os.path.join(pasta, "original.mp4")
        import shutil
        shutil.copy(origem, destino)
        return destino
    b.urls = []
    return b


def test_baixar_clipe_do_link(base, tmp_path):
    p = CT.criar(base, "", "x", modelo="comentario")
    b = _baixador(_clipe(str(tmp_path / "o.mp4"), 3))
    mid = CC.baixar_clipe(base, p["id"], "https://www.tiktok.com/@a/video/1", b)
    q = CT.carregar(base, p["id"])
    assert mid == "M1" and q["midias"][0]["origem"].startswith("https://www.tiktok") and q["midias"][0]["dur"] > 2.5
    assert CC.baixar_clipe(base, p["id"], "https://www.tiktok.com/@a/video/1", b) == "M1" and len(CT.carregar(base, p["id"])["midias"]) == 1
    with pytest.raises(CT.CurtoErro):
        CC.baixar_link("não é link", str(tmp_path / "z"), b)


def test_novo_pelo_link_com_transcricao_corrida(cliente, base, tmp_path, monkeypatch):
    _A, cl = cliente
    import curtos_rotas as R
    b = _baixador(_clipe(str(tmp_path / "o.mp4"), 3))
    monkeypatch.setitem(R.CB, "baixar", b)
    r = cl.post("/curtos/novo", data={"modelo": "comentario", "link": "https://www.youtube.com/shorts/abc", "linhas": TRANSCRICAO_CORRIDA},
                content_type="multipart/form-data")
    pid = r.headers["Location"].rsplit("/", 1)[1]
    assert not _esperar(pid)["erro"]
    p = CT.carregar(base, pid)
    assert b.urls == ["https://www.youtube.com/shorts/abc"] and p["midias"][0]["id"] == "M1"
    assert "young boy" in p["comentario"]["referencia"] and not p["comentario"]["linhas"]
    d = cl.post(f"/curtos/{pid}/comentario/linhas", json={"mid": "M1", "texto": "outra transcrição sem tempo nenhum"}).get_json()
    assert d["referencia"] is True
    assert cl.post(f"/curtos/{pid}/comentario/baixar", json={"url": "https://vm.tiktok.com/x"}).get_json()["ok"]
    assert not _esperar(pid)["erro"]
    assert [m["id"] for m in CT.carregar(base, pid)["midias"]] == ["M1", "M2"]
