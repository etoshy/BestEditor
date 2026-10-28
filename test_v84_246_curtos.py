"""v84_246: ⚡ Vídeos curtos — referências medidas (cortes a 8 q/s, folhas a 4 q/s), perfil do canal, roteiro,
voz gravada alinhada ao roteiro (pausas/repetições cortadas), sons e o projeto do Estúdio."""
import io
import json
import os
import subprocess

import pytest

import curtos as CT


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "curtos"))
    return str(tmp_path)


def _video_com_cortes(caminho, cores=("red", "blue", "green", "yellow"), dur_cada=1.5):
    partes = []
    for k, c in enumerate(cores):
        partes += ["-f", "lavfi", "-i", f"color=c={c}:s=180x320:d={dur_cada}:r=24"]
    n = len(cores)
    filtro = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *partes, "-f", "lavfi", "-i", f"sine=f=440:d={n * dur_cada}",
                    "-filter_complex", filtro, "-map", "[v]", "-map", f"{n}:a", "-shortest", caminho], check=True)
    return caminho


BLOCOS = [
    {"id": "B1", "funcao": "gancho", "fala": "O presidente anunciou HOJE um corte de impostos.",
     "cenas": [{"layout": "foto_real", "query": "president speech", "alternativas": ["press conference"], "visual": "", "material": "",
                "palavra": "", "efeito": "zoom_in", "entrada": "punch_in", "composicao": ""},
               {"layout": "cartao_cinza", "query": "tax cut", "alternativas": [], "visual": "", "material": "", "palavra": "corte",
                "efeito": "", "entrada": "none", "composicao": ""}],
     "texto_tela": {"texto": "CORTE DE IMPOSTOS", "estilo": "", "palavra": "corte"},
     "sfx": [{"tipo": "whoosh", "palavra": "", "busca": "whoosh"}, {"tipo": "impacto", "palavra": "corte", "busca": "hit"}]},
    {"id": "B2", "funcao": "fato", "fala": "A medida vale a partir de janeiro e custa três bilhões.",
     "cenas": [{"layout": "video", "query": "money counting", "alternativas": ["cash"], "visual": "", "material": "", "palavra": "",
                "efeito": "", "entrada": "none", "composicao": ""}],
     "texto_tela": {"texto": "", "estilo": "", "palavra": ""}, "sfx": []},
    {"id": "B3", "funcao": "cta", "fala": "Segue o canal pra mais.",
     "cenas": [{"layout": "meme", "query": "dog side eye meme", "alternativas": [], "visual": "", "material": "", "palavra": "",
                "efeito": "", "entrada": "pop", "composicao": ""}],
     "texto_tela": {"texto": "", "estilo": "", "palavra": ""}, "sfx": []},
]


def _palavras(frase, t=0.3, passo=0.35, pausa_depois=None):
    ws = []
    for w in frase.split():
        ws.append({"word": w, "start": round(t, 3), "end": round(t + 0.3, 3)})
        t += passo + (0.9 if pausa_depois and w == pausa_depois else 0)
    return ws


# ------------------------------------------------------------------ medição
def test_cortes_e_folhas(tmp_path):
    v = _video_com_cortes(str(tmp_path / "v.mp4"))
    cortes = CT.detectar_cortes(v)
    assert len(cortes) == 3
    assert all(abs(c - e) < 0.3 for c, e in zip(cortes, (1.5, 3.0, 4.5)))
    folhas = CT.folhas_densas(v, str(tmp_path / "q"), 6.0)
    assert folhas and all(os.path.isfile(f) for f in folhas)
    folha, quadros = CT.folha_de_contato(v, CT.planos(cortes, 6.0), str(tmp_path / "q"))
    assert os.path.isfile(folha) and len(quadros) == 4


def test_movimento_nao_vira_corte(tmp_path):
    v = str(tmp_path / "m.mp4")  # pan contínuo: muda todo quadro, mas sem pico
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:d=4:r=24", "-vf",
                    "crop=180:180:x='t*30':y=0,scale=180:320", v], check=True)
    assert len(CT.detectar_cortes(v)) <= 1


def test_metricas_audio_e_fala():
    ws = _palavras("um dois três quatro cinco seis")
    m = CT.metricas_fala(ws, 4.0)
    assert m["palavras"] == 6 and m["primeira_fala_s"] == 0.3 and m["gancho"].startswith("um dois")
    env = [-60.0] * 80
    env[40] = -10.0  # pico junto do corte em 2.0 s
    a = CT.metricas_audio(env, [], [2.0, 3.0])
    assert a["sfx_nos_cortes"] == 0.5


def test_canal_referencia_e_perfil(base, tmp_path):
    c = CT.criar_canal(base, "Laestro")
    v = _video_com_cortes(str(tmp_path / "ref.mp4"))
    r = CT.adicionar_referencia(base, c, arquivo=v, titulo="ref")
    CT.salvar_canal(base, c)

    def transcrever(audio, language=None, word_timestamps=True, info=None):
        return [{"start": 0.3, "end": 3.0, "text": "pois é gente", "words": _palavras("pois é gente olha isso")}]
    chamadas = []

    def chamar(recurso, system, conteudo, schema=None, **kw):
        chamadas.append((recurso, schema))
        if schema is CT.FICHA_SCHEMA:
            assert any(b.get("type") == "image" for b in conteudo)  # folha de contato + densas
            return {"resumo": "memes e cartão cinza", "gancho": {"texto": "x", "tipo": "pergunta", "visual": "meme", "por_que_prende": "y"},
                    "estrutura": [], "composicoes": [], "legenda": {"tem": True, "descricao": "", "posicao": "meio", "maiusculas": False,
                                                                     "palavras_por_vez": 3, "cor_texto": "#F2A81E", "cor_destaque": "#F2A81E"},
                    "textos_tela": {"tem": False, "descricao": "", "exemplos": []}, "movimento": "", "tom": "", "cta": "", "pontos_fortes": []}
        return {"resumo": "canal de memes", "ritmo": {"cortes": "seco"}, "legenda": {"estilo": "contorno", "posicao": "meio", "cor_texto": "#F2A81E"},
                "composicoes": [{"id": "Cartão Cinza", "nome": "cartão", "layout": "cartao_cinza", "descricao": "", "quando": ""}],
                "sfx": {"usa": True, "nos_cortes": True, "descricao": "", "tipos_preferidos": ["whoosh", "inexistente"]}}
    CT.analisar_referencia(base, c["id"], r["id"], transcrever, chamar, True)
    c = CT.carregar_canal(base, c["id"])
    ref = c["referencias"][0]
    assert ref["estado"] == "pronta" and ref["medidas"]["n_planos"] == 4 and ref["densas"] and ref["ficha"]["resumo"]
    assert ref["medidas"]["palavras_por_s"] > 0
    perfil = CT.gerar_perfil(base, c["id"], chamar)
    assert perfil["legenda"]["estilo"] == "contorno" and perfil["legenda"]["cor_texto"] == "#F2A81E"
    assert perfil["composicoes"][0]["id"] == "cartao_cinza"
    assert perfil["sfx"]["tipos_preferidos"] == ["whoosh"]
    assert perfil["duracao_alvo_s"] == 10  # mediana real (6 s) presa no mínimo
    assert "canal de memes" in CT.texto_do_perfil(perfil)
    assert "Responda APENAS" in CT.prompt_perfil(c)


# ------------------------------------------------------------------ roteiro
def test_ler_roteiro_normaliza(base):
    p = CT.criar(base, "", "teste")
    p["midias"] = [{"id": "I1", "arquivo": "x.jpg", "tipo": "foto", "descricao": "foto"}]
    r = CT.ler_roteiro({"blocos": [
        {"fala": "Olá", "cenas": [{"layout": "materia", "material": "I9", "query": "x"},  # ID que não existe → foto_real
                                  {"layout": "cartao_cinza", "material": "I1"}, {"layout": "xxx", "query": "y"}],
         "sfx": [{"tipo": "whoosh"}, {"tipo": "naoexiste"}], "texto_tela": "OI"},
        {"fala": ""}, "Segue o canal"]}, p, ["K1"])
    assert [b["id"] for b in r["blocos"]] == ["B1", "B2"]
    cenas = r["blocos"][0]["cenas"]
    assert cenas[0]["layout"] == "foto_real" and cenas[0]["material"] == ""
    assert cenas[1]["layout"] == "cartao_cinza" and cenas[1]["material"] == "I1"
    assert cenas[2]["layout"] == "video"
    assert len(r["blocos"][0]["sfx"]) == 1 and r["blocos"][0]["texto_tela"]["texto"] == "OI"
    assert r["blocos"][1]["cenas"]  # bloco sem cena ganha uma
    with pytest.raises(CT.CurtoErro):
        CT.ler_roteiro({"blocos": []}, p)


def test_prompt_roteiro_tem_noticia_e_estilo(base):
    c = CT.criar_canal(base, "Laestro")
    c["perfil"]["resumo"] = "memes rápidos"
    CT.salvar_canal(base, c)
    p = CT.criar(base, c["id"], "x", texto="O Lula ganhou a eleição.")
    pr = CT.prompt_roteiro(base, p)
    assert "O Lula ganhou" in pr and "memes rápidos" in pr and "cartao_cinza" in pr and "MAIÚSCULAS" in pr


# ------------------------------------------------------------------ voz
def test_alinhar_repeticoes_e_cortes():
    falado = "é o presidente anun o presidente anunciou hoje um corte de impostos ahn a medida vale a partir de janeiro e custa três bilhões segue o canal pra mais"
    ws = _palavras(falado, pausa_depois="impostos")
    rep = CT.repeticoes(BLOCOS, ws)
    tiradas = [" ".join(ws[k]["word"] for k in range(i, j + 1)) for i, j in rep]
    assert "é o presidente anun" in tiradas and "ahn" in tiradas
    dur = ws[-1]["end"] + 1.0
    cortes = CT.intervalos_de_corte(ws, dur, 0.3, repetidas=rep)
    novas = CT.palavras_remapeadas(ws, cortes)
    texto = " ".join(w["word"] for w in novas)
    assert texto.startswith("o presidente anunciou") and "ahn" not in texto.split()
    gap = [round(novas[i + 1]["start"] - novas[i]["end"], 2) for i in range(len(novas) - 1)]
    assert max(gap) <= 0.31  # a pausa de 0,9 s depois de "impostos" encolheu
    al = CT.alinhar(BLOCOS, novas, CT.remapear(dur, cortes))
    assert [a["bloco"] for a in al["blocos"]] == ["B1", "B2", "B3"]
    assert al["blocos"][1]["falado"].startswith("a medida") and al["blocos"][1]["similaridade"] == 1.0
    assert al["blocos"][0]["start"] == 0.0 and al["blocos"][1]["start"] == al["blocos"][0]["end"]
    t = CT.tempo_da_palavra(BLOCOS, 1, "janeiro", novas, al["mapa"], al["blocos"])
    assert t == next(w["start"] for w in novas if w["word"] == "janeiro")


def test_e_conjuncao_nao_e_cortado():
    blocos = [{"id": "B1", "fala": "Ele chegou cedo", "cenas": []}]
    ws = _palavras("ele chegou e cedo", passo=0.32)  # "e" a mais, sem pausa: é fala, não muleta
    assert CT.repeticoes(blocos, ws) == []


def test_cortar_audio(tmp_path):
    ent = str(tmp_path / "a.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=300:d=5", ent], check=True)
    sai = CT.cortar_audio(ent, str(tmp_path / "b.wav"), [(1.0, 2.0), (3.0, 3.5)], 5.0)
    assert abs(CT.duracao_audio(sai) - 3.5) < 0.05
    assert CT.remapear(4.0, [(1.0, 2.0), (3.0, 3.5)]) == 2.5


def test_caixa_da_legenda():
    ws = _palavras("o presidente anunciou hoje um corte de impostos a medida vale a partir de janeiro e custa três bilhões segue o canal pra mais")
    al = CT.alinhar(BLOCOS, ws)
    out = CT.caixa_da_legenda(BLOCOS, ws, al["mapa"], al["blocos"], gancho_maiusculas=False)
    assert next(w for w in out if w["word"].lower() == "hoje")["word"] == "HOJE"
    assert next(w for w in out if w["word"].lower() == "medida")["word"] == "medida"
    out2 = CT.caixa_da_legenda(BLOCOS, ws, al["mapa"], al["blocos"], gancho_maiusculas=True)
    assert out2[1]["word"] == "PRESIDENTE" and out2[-1]["word"] == "mais"


def _projeto_gravado(base, tmp_path, canal_id=""):
    p = CT.criar(base, canal_id, "Impostos")
    p["roteiro"] = {"titulo_video": "t", "titulos_alt": [], "descricao": "", "hashtags": [], "blocos": json.loads(json.dumps(BLOCOS))}
    CT.salvar(base, p)
    falado = "o presidente anunciou hoje um corte de impostos a medida vale a partir de janeiro e custa três bilhões segue o canal pra mais"
    ws = _palavras(falado, pausa_depois="impostos")
    aud = str(tmp_path / "voz.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f=200:d={ws[-1]['end'] + 0.8}", aud], check=True)

    def transcrever(audio, language=None, word_timestamps=True, info=None):
        return [{"start": ws[0]["start"], "end": ws[-1]["end"], "text": falado, "words": ws}]
    g = CT.processar_gravacao(base, p["id"], transcrever, aud)
    return p["id"], g


def test_gravacao_planos_destaques_sons(base, tmp_path, monkeypatch):
    monkeypatch.setenv("DP_EXTRAS_DIR", str(tmp_path / "extras"))
    import dp_extras
    dp_extras.recarregar()
    pid, g = _projeto_gravado(base, tmp_path)
    assert g["dur"] < g["dur_original"] and len(g["alinhamento"]) == 3
    d = CT.montar_dados_editor(base, pid, ["pexels", "bing", "youtube"])
    segs = d["resposta"]["segments"]
    assert segs[0]["start"] == 0.0 and abs(segs[-1]["end"] - d["dur"]) < 0.01
    assert all(abs(segs[i]["end"] - segs[i + 1]["start"]) < 0.001 for i in range(len(segs) - 1))
    assert segs[0]["provider"] == "bing" and segs[0]["media_type"] == "image" and segs[0].get("entrada") == "punch_in"
    cinza = [s for s in segs if s.get("template") == CT.CENA_CARTAO_CINZA]
    assert cinza, "o cartão cinza vira a cena dos extras"
    import cenas_dp
    assert cenas_dp.template(CT.CENA_CARTAO_CINZA)
    corte_t = next(w["start"] for w in d["palavras"] if w["word"] == "corte")
    assert abs(cinza[0]["start"] - corte_t) < 0.01  # o 2º plano começa na palavra dele
    assert any(s["provider"] == "pexels" and s["query"] == "money counting" for s in segs)
    hl = d["resposta"]["highlights"]
    assert hl and hl[0]["texto"] == "CORTE DE IMPOSTOS"
    assert len(d["sfx"]) >= 2 and all(s["som"] for s in d["sfx"])
    assert d["legendas"]["ativa"] is True
    assert any(w["word"] == "HOJE" for w in d["palavras"])
    import prompt_builder as PB
    parsed = PB.parse_ai_response(d["resposta_json"], valid_providers=["pexels", "bing", "youtube", "material"], total_duration=d["dur"])
    assert len(parsed.segments) == len(segs)


def test_usar_o_que_falei(base, tmp_path):
    p = CT.criar(base, "", "x")
    p["roteiro"] = {"blocos": [{"id": "B1", "funcao": "gancho", "fala": "Ele chegou ontem à noite", "cenas": [{"layout": "video", "query": "q", "alternativas": [],
                                "visual": "", "material": "", "palavra": "", "efeito": "", "entrada": "none", "composicao": ""}],
                                "texto_tela": {"texto": "", "estilo": "", "palavra": ""}, "sfx": []}]}
    CT.salvar(base, p)
    ws = _palavras("ele chegou hoje cedo à noite")
    aud = str(tmp_path / "v.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=200:d=3", aud], check=True)
    CT.processar_gravacao(base, p["id"], lambda *a, **k: [{"start": 0, "end": 2, "text": "", "words": ws}], aud,
                          {"cortar_pausas": False, "cortar_repeticoes": False})
    assert CT.usar_o_que_falei(base, p["id"]) == 1
    q = CT.carregar(base, p["id"])
    assert q["roteiro"]["blocos"][0]["fala"] == "ele chegou hoje cedo à noite"
    assert q["gravacao"]["alinhamento"][0]["similaridade"] == 1.0


def test_sons_do_tipo_e_escolha():
    sons = [{"id": "variados/whoosh_1"}, {"id": "variados/whoosh_3"}, {"id": "pop/pop_1"},
            {"id": "pixabay/123", "nome": "Swoosh rápido", "tags": ["whoosh"]}]
    assert [s["id"] for s in CT.sons_do_tipo("whoosh", sons)] == ["variados/whoosh_1", "variados/whoosh_3", "pixabay/123"]
    assert CT.escolher_som("whoosh", "x", sons=sons) == "pixabay/123"  # os do Pixabay têm a preferência
    assert CT.escolher_som("pop", "a", sons=sons) == "pop/pop_1"
    assert CT.escolher_som("riser", "a", sons=sons) is None


def test_midias_do_editor_inclui_canal(base, tmp_path):
    c = CT.criar_canal(base, "Laestro")
    img = tmp_path / "k.png"
    from PIL import Image
    Image.new("RGB", (300, 300), "white").save(img)
    CT.adicionar_midia_canal(base, c, str(img), "foto", "gato pensando — no contraponto")
    CT.salvar_canal(base, c)
    p = CT.criar(base, c["id"], "x")
    ms = CT.midias_para_editor(base, p)
    assert [m["id"] for m in ms] == ["K1"] and os.path.isfile(ms[0]["caminho"])
    assert "K1" in CT.prompt_roteiro(base, p)


# ------------------------------------------------------------------ rotas + Estúdio
@pytest.fixture
def cliente(base, tmp_path, monkeypatch):
    monkeypatch.setenv("DP_EXTRAS_DIR", str(tmp_path / "extras"))
    import dp_extras
    dp_extras.recarregar()
    import app as A
    monkeypatch.setattr(A, "BASE_DIR", base)
    monkeypatch.setattr(A, "_fetch_previews", lambda *a, **k: None)
    monkeypatch.setattr(A, "_job_dir", lambda j: os.path.join(base, "jobs", j))
    A.app.config["TESTING"] = True
    return A, A.app.test_client()


def test_paginas_abrem(cliente, base):
    _A, cl = cliente
    assert cl.get("/curtos").status_code == 200
    r = cl.post("/curtos/canal/novo", data={"nome": "Laestro"})
    cid = r.headers["Location"].rsplit("/", 1)[1]
    assert cl.get(f"/curtos/canal/{cid}").status_code == 200
    assert cl.get(f"/curtos/canal/{cid}/estado").get_json()["nome"] == "Laestro"
    r = cl.post("/curtos/novo", data={"canal_id": cid, "titulo": "Teste", "texto": "aconteceu"})
    pid = r.headers["Location"].rsplit("/", 1)[1]
    html = cl.get(f"/curtos/{pid}").get_data(as_text=True)
    assert "Teleprompter" in html or "teleprompter" in html
    e = cl.get(f"/curtos/{pid}/estado").get_json()
    assert e["titulo"] == "Teste" and e["palavras_alvo"] > 0
    assert "aconteceu" in cl.get(f"/curtos/{pid}/roteiro/prompt").get_json()["prompt"]
    resp = json.dumps({"blocos": [{"fala": "Oi gente", "cenas": [{"layout": "meme", "query": "cat meme"}]}]})
    assert cl.post(f"/curtos/{pid}/roteiro", json={"resposta": resp}).get_json()["ok"]
    assert cl.get("/curtos/sons/whoosh").get_json()["sons"]
    assert "⚡ Vídeos curtos" in cl.get("/modelos-video").get_data(as_text=True)


def test_vai_pro_estudio(cliente, base, tmp_path):
    A, cl = cliente
    pid, _g = _projeto_gravado(base, tmp_path)
    r = cl.post(f"/curtos/{pid}/previa", json={"providers": ["pexels", "bing"]}).get_json()
    assert r["ok"] and r["planos"]
    r = cl.post(f"/curtos/{pid}/editor", json={"providers": ["pexels", "bing", "youtube"]}).get_json()
    assert r["ok"], r
    job = A._JOBS[r["job_id"]]
    assert job["curto_id"] == pid and job["orientation"] == "9:16"
    assert job["legendas"]["ativa"] and job["sfx"] and job["word_timestamps"]
    assert job["pending_segments"] and job["destaques"]
    assert any(s.get("template") == CT.CENA_CARTAO_CINZA and (s.get("template_campos") or {}).get("_fala") is False
               for s in job["pending_segments"])
    assert CT.carregar(base, pid)["editor"]["job_id"] == r["job_id"]


def test_pixabay_para_a_base(base, tmp_path, monkeypatch):
    monkeypatch.setenv("DP_EXTRAS_DIR", str(tmp_path / "extras"))
    import dp_extras
    import dp_sons
    import curtos_rotas as R
    monkeypatch.setattr(dp_sons, "SONS_DIR", str(tmp_path / "sons"))
    os.makedirs(tmp_path / "sons", exist_ok=True)
    import shutil
    shutil.copy(os.path.join(os.path.dirname(CT.__file__), "assets", "sons", "sons.json"), tmp_path / "sons" / "sons.json")
    px = tmp_path / "px"
    px.mkdir()
    som = px / "123456_whoosh_cortado.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=900:d=0.4", str(som)], check=True)
    meta = {"id": "123456", "titulo": "Whoosh", "busca": "whoosh", "arquivo_cortado": str(som), "dur": 0.4, "inicio_som": 0.0,
            "pico": 0.1, "fim_som": 0.4, "nivel_db": -6, "tags": ["whoosh"]}
    (px / "catalogo.json").write_text(json.dumps([meta]), encoding="utf-8")
    assert R._resultados_pixabay(str(px), "whoosh")[0]["id"] == "123456"
    sid = R.importar_pixabay(base, "123456", str(px))
    assert sid == "pixabay/123456" and dp_sons.som(sid)
    assert "pixabay/123456" in [s["id"] for s in CT.sons_do_tipo("whoosh")]
    dp_extras.recarregar()


def test_perfil_pronto_laestro(cliente, base):
    _A, cl = cliente
    assert "laestro" in CT.perfis_prontos()
    r = cl.post("/curtos/canal/novo", data={"nome": "Laestro", "pronto": "laestro"})
    cid = r.headers["Location"].rsplit("/", 1)[1]
    c = CT.carregar_canal(base, cid)
    assert c["perfil"]["legenda"]["cor_texto"] == "#F2A81E" and c["perfil"]["gancho_maiusculas"] is True
    assert any(x["layout"] == "cartao_cinza" for x in c["perfil"]["composicoes"])
    assert any("curso" in e for e in c["perfil"]["evitar"])
    p = CT.criar(base, cid, "x", texto="notícia")
    assert "NÃO usa texto grande" in CT.prompt_roteiro(base, p)


# ------------------------------------------------------------------ v84_247: 🚀 fazer tudo e 🔁 trocar a voz no editor
def _tts_falso(motor, texto, saida, **kw):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f=300:d={0.33 * len(texto.split()) + 0.2:.2f}", saida], check=True)


def _whisper_do_roteiro(base, pid, ritmo=0.33):
    """Whisper falso: lê o roteiro atual do projeto, palavra a palavra, no ritmo pedido."""
    def tr(audio, language=None, word_timestamps=True, info=None):
        p = CT.carregar(base, pid)
        ws, t = [], 0.1
        for b in p["roteiro"]["blocos"]:
            for w in b["fala"].split():
                ws.append({"word": w.strip(".,?!").lower(), "start": round(t, 3), "end": round(t + ritmo * 0.8, 3)})
                t += ritmo
            t += 0.12
        return [{"start": 0, "end": t, "text": "", "words": ws}]
    return tr


def _job_do_curto(A, cl, base, pid):
    r = cl.post(f"/curtos/{pid}/editor", json={"providers": ["pexels", "bing"]}).get_json()
    assert r["ok"], r
    return A._JOBS[r["job_id"]], r["job_id"]


def _esperar(pid):
    import time
    import curtos_rotas as R
    for _ in range(200):
        t = R.TAREFAS.get(pid) or {}
        if t.get("fim"):
            return t
        time.sleep(0.05)
    raise AssertionError("a tarefa não terminou")


def test_fazer_tudo(cliente, base, monkeypatch):
    A, cl = cliente
    import curtos_rotas as R
    p = CT.criar(base, "", "Impostos", texto="O governo anunciou corte de impostos.")
    monkeypatch.setitem(R.CB, "tts", _tts_falso)
    monkeypatch.setitem(R.CB, "transcrever", _whisper_do_roteiro(base, p["id"]))
    original = CT.gerar_roteiro
    monkeypatch.setattr(CT, "gerar_roteiro", lambda b, pid, chamar=None: original(b, pid, lambda *a, **k: {"blocos": json.loads(json.dumps(BLOCOS))}))
    import anime2d
    monkeypatch.setattr(anime2d, "vozes_disponiveis", lambda mp="xtts": [{"slug": "perfil:teste", "nome": "t", "grupo": "g"}])
    r = cl.post(f"/curtos/{p['id']}/fazer-tudo", json={}).get_json()
    assert r["ok"], r
    t = _esperar(p["id"])
    assert not t["erro"], t["erro"]
    q = CT.carregar(base, p["id"])
    assert q["roteiro"]["blocos"] and q["tts"]["arquivo"] and q["gravacao"]["fonte"] == "guia"
    job = A._JOBS[q["editor"]["job_id"]]
    assert job["pending_segments"] and all(s.get("curto_chave") for s in job["pending_segments"])
    assert job["curto_alinhamento"][0]["bloco"] == "B1"


def test_trocar_voz_mantem_as_midias(cliente, base, tmp_path, monkeypatch):
    A, cl = cliente
    import curtos_rotas as R
    pid, _g = _projeto_gravado(base, tmp_path)
    job, job_id = _job_do_curto(A, cl, base, pid)
    with CT._TRAVA:
        q = CT.carregar(base, pid)
        q["editor"] = {"job_id": job_id}
        CT.salvar(base, q)
    pend = job["pending_segments"]
    n0 = len(pend)
    # você escolheu uma mídia no 1º trecho, dividiu o 2º no editor e pôs um som seu
    pend[0]["override_source"] = {"source": "local_file", "value": "/x/minha.jpg", "kind": "image"}
    job["segment_previews"] = [{"ok": True, "label": f"p{i}"} for i in range(n0)]
    s1 = pend[1]
    meio = round((s1["start"] + s1["end"]) / 2, 3)
    pend[1:2] = [dict(s1, end=meio), dict(s1, start=meio, override_source={"source": "url", "value": "u2", "kind": "video"})]
    job["segment_previews"].insert(2, {"ok": True, "label": "dividido"})
    job["sfx"].append({"id": "meu", "som": job["sfx"][0]["som"], "start": float(job["curto_alinhamento"][1]["start"]) + 0.2, "volume": 1})
    dur_velha = job["total_duration"]
    # a sua voz: mais lenta
    monkeypatch.setitem(R.CB, "transcrever", _whisper_do_roteiro(base, pid, ritmo=0.5))
    aud = str(tmp_path / "minha.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=250:d=16", aud], check=True)
    with open(aud, "rb") as f:
        r = cl.post(f"/curtos/{pid}/trocar-voz", data={"audio": (f, "minha.wav"), "cortar_pausas": "true"},
                    content_type="multipart/form-data").get_json()
    assert r["ok"], r
    t = _esperar(pid)
    assert not t["erro"], t["erro"]
    job = A._JOBS[job_id]
    assert job["total_duration"] > dur_velha
    novos = job["pending_segments"]
    assert novos[0]["override_source"]["value"] == "/x/minha.jpg"  # a sua escolha ficou
    assert any((s.get("override_source") or {}).get("value") == "u2" for s in novos)  # o pedaço que você dividiu também
    assert novos[0]["start"] == 0.0 and abs(novos[-1]["end"] - job["total_duration"]) < 0.01
    assert all(abs(novos[i]["end"] - novos[i + 1]["start"]) < 0.001 for i in range(len(novos) - 1))
    assert len(job["segment_previews"]) == len(novos)
    meu = next(s for s in job["sfx"] if s["id"] == "meu")
    assert meu["start"] > float(job["curto_alinhamento"][1]["start"])  # foi junto pro tempo novo do bloco
    assert job["audio_path"].endswith(".wav") and os.path.isfile(job["audio_path"])


def test_reencaixar_bloco_novo():
    pend = [{"start": 0, "end": 2, "provider": "bing", "query": "a", "curto_chave": "B1:0:0", "override_source": {"value": "x"}}]
    novos = [{"start": 0, "end": 3, "bloco": "B1", "cena": 0, "parte": 0, "provider": "bing", "query": "a"},
             {"start": 3, "end": 4, "bloco": "B1", "cena": 0, "parte": 1, "provider": "bing", "query": "a"},
             {"start": 4, "end": 6, "bloco": "B2", "cena": 0, "parte": 0, "provider": "pexels", "query": "b"}]
    s, p, sem = CT.reencaixar_planos(pend, [{"ok": 1}], novos)
    assert [x["end"] for x in s] == [3, 4, 6] and s[0]["override_source"] == {"value": "x"}
    assert "override_source" not in s[1] and s[2]["query"] == "b" and sem == [1, 2] and p[0] == {"ok": 1}
    assert CT.mapear_tempo(1.0, [{"bloco": "B1", "start": 0, "end": 2}], [{"bloco": "B1", "start": 0, "end": 4}]) == 2.0


def test_laestro_ja_vem_como_canal(cliente, base):
    _A, cl = cliente
    html = cl.get("/curtos").get_data(as_text=True)
    cs = [c for c in CT.listar_canais(base) if c["nome"] == "Laestro"]  # (v84_253: o 💬 comentário também vem pronto)
    assert len(cs) == 1 and f'<option value="{cs[0]["id"]}">Laestro</option>' in html
    c = CT.carregar_canal(base, cs[0]["id"])
    assert c["perfil"]["legenda"]["cor_texto"] == "#F2A81E" and c["perfil_origem"] == "laestro"
    n = len(CT.listar_canais(base))
    cl.get("/curtos")
    assert len(CT.listar_canais(base)) == n  # não duplica
    CT.excluir_canal(base, cs[0]["id"])
    cl.get("/curtos")
    assert not [c for c in CT.listar_canais(base) if c["nome"] == "Laestro"]  # apagou? não volta



def test_contraponto_e_reflexao_no_roteiro(base):
    c = CT.criar_canal(base, "X")
    p = CT.criar(base, c["id"], "x", texto="notícia")
    pr = CT.prompt_roteiro(base, p)
    assert "contraponto" in pr and "reflexao" in pr and "PONTO DE VISTA" in pr
    c["perfil"]["ponto_de_vista"]["usa"] = False
    CT.salvar_canal(base, c)
    assert "9b. PONTO DE VISTA" not in CT.prompt_roteiro(base, p)
    r = CT.ler_roteiro({"blocos": [{"funcao": "contraponto", "fala": "mas pensa comigo"}, {"funcao": "reflexao", "fala": "fica a dica"}]}, p)
    assert [b["funcao"] for b in r["blocos"]] == ["contraponto", "reflexao"]


def test_laestro_v2_sem_bordao_e_atualiza_canal_antigo(base):
    import json as _j
    pr = CT.perfis_prontos()["laestro"]
    assert "agacha" not in _j.dumps(pr["perfil"]["estrutura"]) + _j.dumps(pr["perfil"]["composicoes"]) + pr["perfil"]["linguagem"]
    assert any(e["funcao"] == "contraponto" for e in pr["perfil"]["estrutura"]) and pr["perfil"]["ponto_de_vista"]["usa"]
    # canal criado com a v1 (com o bordão) e uma legenda que você mudou
    c = CT.criar_canal(base, "Laestro")
    c["perfil"]["estrutura"] = [{"funcao": "pergunta", "descricao": "relaxa e agacha", "segundos": 3}]
    c["perfil"]["legenda"]["cor_texto"] = "#123456"
    c["perfil_origem"], c["perfil_versao"] = "laestro", 1
    CT.salvar_canal(base, c)
    os.makedirs(CT.raiz(base), exist_ok=True)
    with open(os.path.join(CT.raiz(base), "prontos_criados.json"), "w") as f:
        _j.dump(["laestro"], f)
    CT.garantir_canais_prontos(base)
    c = CT.carregar_canal(base, c["id"])
    assert c["perfil_versao"] == 2 and "agacha" not in _j.dumps(c["perfil"]["estrutura"])
    assert c["perfil"]["legenda"]["cor_texto"] == "#123456"  # o que você ajustou ficou
    assert [x["nome"] for x in CT.listar_canais(base)].count("Laestro") == 1  # (o 💬 comentário é outro canal pronto)


# ------------------------------------------------------------------ v84_250: 🎌 modo anime
def test_modo_anime_prompt(base):
    c = CT.criar_canal(base, "X")
    p = CT.criar(base, c["id"], "x", texto="notícia")
    assert "NÃO use os layouts 'anime_reacao'" in CT.prompt_roteiro(base, p)
    p["config"].update(modo_anime="reacoes", anime_obras="Naruto, Jujutsu Kaisen")
    CT.salvar(base, p)
    pr = CT.prompt_roteiro(base, p)
    assert "MODO ANIME" in pr and "anime_reacao" in pr and "Naruto, Jujutsu Kaisen" in pr and "DESCRIÇÃO VISUAL LITERAL" in pr
    c["perfil"]["anime"] = {"modo": "tudo", "obras": ""}  # o padrão do canal vale quando o projeto não escolhe
    CT.salvar_canal(base, c)
    p["config"]["modo_anime"] = ""
    CT.salvar(base, p)
    assert CT.anime_do(base, p)["modo"] == "tudo"
    r = CT.ler_roteiro({"blocos": [{"fala": "oi", "cenas": [{"layout": "anime_reacao", "query": "anime girl shocked", "emocao": "choque",
                                                            "obra": "Naruto", "personagem": "Sakura"}]}]}, p)
    cn = r["blocos"][0]["cenas"][0]
    assert cn["emocao"] == "choque" and cn["obra"] == "Naruto" and cn["personagem"] == "Sakura"


def test_modo_anime_na_montagem(base, tmp_path, monkeypatch):
    monkeypatch.setenv("DP_EXTRAS_DIR", str(tmp_path / "extras"))
    import dp_extras
    dp_extras.recarregar()
    pid, _g = _projeto_gravado(base, tmp_path)
    p = CT.carregar(base, pid)
    p["config"]["modo_anime"] = "reacoes"
    CT.salvar(base, p)
    d = CT.montar_dados_editor(base, pid, ["pexels", "bing", "animepexels"])
    ani = [s for s in d["resposta"]["segments"] if s["provider"] == "animepexels"]
    assert ani and ani[0]["query"] == "dog side eye meme"  # o meme de reação virou reação de anime, no acervo
    assert ani[0]["semantic_weight"] == 2 and ani[0]["keyword_weight"] == 0.5
    assert any(s["provider"] == "bing" and s.get("media_type") == "image" for s in d["resposta"]["segments"])  # fato real continua real
    import prompt_builder as PB
    PB.parse_ai_response(d["resposta_json"], valid_providers=["pexels", "bing", "animepexels", "material"], total_duration=d["dur"])
    # sem o acervo ligado: cai no YouTube com "anime" na busca
    d2 = CT.montar_dados_editor(base, pid, ["pexels", "bing", "youtube"])
    yt = [s for s in d2["resposta"]["segments"] if s["provider"] == "youtube"]
    assert yt and yt[-1]["query"].endswith(" anime")
    # modo "tudo": vídeo de banco também vira cena de anime
    p = CT.carregar(base, pid)
    p["config"]["modo_anime"] = "tudo"
    CT.salvar(base, p)
    d3 = CT.montar_dados_editor(base, pid, ["pexels", "bing", "animepexels"])
    assert not any(s["provider"] == "pexels" for s in d3["resposta"]["segments"])
    assert any(s["provider"] == "animepexels" and s["keyword_weight"] == 2 for s in d3["resposta"]["segments"])
