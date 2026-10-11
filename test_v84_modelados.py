"""Testes da aba 🎞️ Vídeos modelados (v84): estilos, prompt master, roteiro,
áudio com tempos exatos + .srt, ajuste de tempos, Flow (falso) e envio pro Estúdio."""
import json
import os
import subprocess
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))

import modelados as md  # noqa: E402
import multivoz  # noqa: E402

TAGS = {"whispering", "gasp", "fear", "narration", "laugh", "sigh"}


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(multivoz, "ARQUIVO", str(tmp_path / "vozes.json"))
    monkeypatch.setattr(md, "ARQUIVO_ESTILOS", str(tmp_path / "estilos.json"))
    monkeypatch.setattr(md, "_tags_turbo", lambda: set(TAGS))
    multivoz.salvar({"nome": "Narrador", "motor": "piper", "config": {"voz": "pt_BR-faber-medium"}, "genero": "masculino",
                     "descricao": "grave"})
    multivoz.salvar({"nome": "Yuki", "motor": "chatterbox", "config": {}, "genero": "f"})
    multivoz.salvar({"nome": "Ghost", "motor": "chatterbox_turbo", "config": {}})
    return tmp_path


def _tom(saida, dur):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono:d=0.3",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}:sample_rate=24000",
                    "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono:d=0.3",
                    "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1", "-ac", "1", saida], check=True)


ROTEIRO = {
    "titulo": "A noiva do poço", "sinopse": "x",
    "personagens": [{"nome": "Narrador", "voz": "narrador", "genero": "masculino"},
                    {"nome": "Yuki", "voz": "yuki", "genero": "feminino", "aparencia": "pale girl, white kimono"}],
    "falas": [
        {"id": 1, "tipo": "narracao", "personagem": "Narrador", "voz": "narrador", "texto": "Era uma noite fria. [gasp] Algo se moveu.", "tags": ["narration", "xyz"], "emocao": 0.4, "pausa_depois": 0.3},
        {"id": 2, "tipo": "dialogo", "personagem": "Yuki", "voz": "yuki", "texto": "Você está me ouvindo?", "tags": ["whispering"], "emocao": 0.8, "pausa_depois": 0.5},
        {"id": 3, "tipo": "narracao", "personagem": "Narrador", "voz": "Narrador", "texto": "Ninguém respondeu.", "pausa_depois": 0.2},
    ],
    "cenas": [
        {"id": 1, "falas": [1], "cena": "A dark well at night", "movimento": "Camera panning slowly from left to right"},
        {"id": 2, "falas": [2, 3], "cena": "Yuki, pale girl, white kimono, by the well", "movimento": "Slow push-in"},
    ],
}


def test_estilo_embutido_e_edicao(ambiente):
    ids = [e["id"] for e in md.listar_estilos()]
    assert "kamishibai" in ids
    k = md.obter_estilo("kamishibai")
    assert "{cena}" in k["prompt_imagem"] and "{ar}" in k["prompt_imagem"] and k["formato"] == "9:16"
    novo = md.salvar_estilo({"nome": "Aquarela", "prompt_imagem": "{cena}, watercolor --ar {ar}",
                             "prompt_animacao": "{movimento}, gentle", "flow": {"duracao_video": "auto"}})
    assert novo["id"] == "aquarela" and md.duracao_max_clipe(novo) == 10
    assert md.duracao_clipe_para(novo, 5.1) == "6s"
    with pytest.raises(md.ModeladoError):
        md.salvar_estilo({"nome": "Ruim", "prompt_imagem": "sem placeholder", "prompt_animacao": "{movimento}"})
    edit = dict(k, descricao="editado", id="kamishibai")
    md.salvar_estilo(edit, id_antigo="kamishibai")
    assert md.obter_estilo("kamishibai")["descricao"] == "editado"
    md.apagar_estilo("kamishibai")
    assert md.obter_estilo("kamishibai")["descricao"] != "editado"


def test_genero_das_vozes(ambiente):
    v = multivoz.por_slug()
    assert v["narrador"]["genero"] == "masculino" and v["yuki"]["genero"] == "feminino" and v["ghost"]["genero"] == ""
    multivoz.definir_genero("ghost", "neutral", "fantasma")
    assert multivoz.por_slug()["ghost"]["genero"] == "neutro"
    assert "voz neutra" in multivoz.instrucao_para_ia()
    with pytest.raises(multivoz.MultiVozError):
        multivoz.definir_genero("ghost", "xpto")


def test_prompt_master_lista_vozes_genero_e_tags(ambiente):
    proj = md.criar_projeto(str(ambiente), "", "kamishibai", "A lenda do poço", 40)
    texto = md.prompt_roteiro(proj, md.obter_estilo("kamishibai"), multivoz.listar(), TAGS)
    assert '"narrador" = Narrador — voz masculina — grave' in texto
    assert '"yuki" = Yuki — voz feminina' in texto
    assert "ACEITA tags" in texto and "whispering" in texto
    assert "cerca de 10 cenas" in texto and "9:16" in texto and "A lenda do poço" in texto
    assert "estas vozes não têm gênero definido" in texto and "ghost" in texto
    assert "🏷 Títulos" in texto and "O Mistério de [caso]" in texto  # v84_52: título numa das fórmulas
    assert "🧭 Método de roteiro" in texto and "FORMATO CURTO" in texto  # 40 s: versão curta do método
    assert md.obter_estilo("kamishibai")["idioma"] == "English"


def test_sem_vozes_usa_chatterbox_turbo_padrao(tmp_path, monkeypatch):
    monkeypatch.setattr(multivoz, "ARQUIVO", str(tmp_path / "vozes.json"))  # nenhuma voz cadastrada
    monkeypatch.setattr(md, "ARQUIVO_ESTILOS", str(tmp_path / "estilos.json"))
    monkeypatch.setattr(md, "_tags_turbo", lambda: set(TAGS))
    base = str(tmp_path)
    proj = md.criar_projeto(base, "", "kamishibai", "The well bride", 20)
    texto = md.prompt_roteiro(proj, md.obter_estilo("kamishibai"), multivoz.listar(), TAGS)
    assert '"narrator" = Narrator (voz embutida)' in texto and "ENGLISH" in texto and "Só existe UMA voz" in texto
    rot = {"falas": [{"id": 1, "voz": "narrator", "texto": "It was a cold night. [gasp] Something moved.", "tags": ["whispering"]},
                     {"id": 2, "tipo": "dialogo", "personagem": "Yuki", "voz": "narrator", "texto": "Can you hear me?"}],
           "cenas": [{"falas": [1, 2], "cena": "A dark well", "movimento": "Slow push-in"}]}
    md.aplicar_roteiro(base, proj["id"], json.dumps(rot), multivoz.listar(), TAGS)
    chamadas = []

    def gerar_fn(motor, texto, saida, **kw):
        chamadas.append((motor, texto, kw))
        _tom(saida, 1.0)
    md.gerar_audio(base, proj["id"], gerar_fn=gerar_fn, normalizar=False)
    assert [c[0] for c in chamadas] == ["chatterbox_turbo", "chatterbox_turbo"]
    assert chamadas[0][1].startswith("[whispering]") and "[gasp]" in chamadas[0][1]
    assert "voice_profile" not in chamadas[0][2]  # voz embutida do Turbo

    criadas = md.criar_vozes_padrao(["Velha Bruxa"])
    assert [v["slug"] for v in criadas] == ["narrator", "velha_bruxa"]
    vb = multivoz.por_slug()["velha_bruxa"]
    assert vb["motor"] == "chatterbox_turbo" and vb["config"]["vozPerfil"] == "Velha Bruxa"
    assert md.criar_vozes_padrao(["Velha Bruxa"]) == []  # não duplica
    assert all(not v.get("virtual") for v in md.vozes_efetivas())


def test_extrair_json_tolerante():
    assert md.extrair_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert md.extrair_json('Claro! Aqui está:\n{"a": [1, 2,], "b": "x}"} fim') == {"a": [1, 2], "b": "x}"}
    with pytest.raises(md.ModeladoError):
        md.extrair_json('{"a": [1, 2')


def test_validar_roteiro(ambiente):
    rot, avisos = md.validar_roteiro(ROTEIRO, multivoz.listar(), TAGS)
    f1, f2, f3 = rot["falas"]
    assert f1["tags"] == ["narration"] and "[gasp]" in f1["texto"]
    assert any("xyz" in a for a in avisos)
    assert f3["voz"] == "narrador"  # nome da voz em vez do slug
    assert f2["tipo"] == "dialogo" and rot["cenas"][1]["falas"] == [2, 3]
    ruim = json.loads(json.dumps(ROTEIRO))
    ruim["falas"][1]["voz"] = "inexistente"
    ruim["personagens"] = []
    with pytest.raises(md.ModeladoError, match="inexistente"):
        md.validar_roteiro(ruim, multivoz.listar(), TAGS)


def test_texto_para_tts():
    f = {"texto": "Eu vi... [gasp] ela.", "tags": ["whispering"]}
    t = md.texto_para_tts(f, "chatterbox_turbo")
    assert t.startswith("[whispering]") and "[gasp]" in t
    t2 = md.texto_para_tts(f, "piper")
    assert "[" not in t2 and "gasp" not in t2


def test_fluxo_completo(ambiente, monkeypatch):
    base = str(ambiente)
    proj = md.criar_projeto(base, "", "kamishibai", "A lenda do poço", 30)
    pid = proj["id"]
    md.aplicar_roteiro(base, pid, json.dumps(ROTEIRO), multivoz.listar(), TAGS)
    chamadas = []

    def gerar_fn(motor, texto, saida, **kw):
        chamadas.append((motor, texto, kw))
        _tom(saida, 1.0 + 0.5 * len(chamadas))
    audio = md.gerar_audio(base, pid, gerar_fn=gerar_fn, normalizar=False)
    assert len(chamadas) == 3
    # agrupado por personagem: as 2 do narrador (modelo carregado uma vez), depois a da Yuki
    assert [c[1][:8] for c in chamadas] == ["Era uma ", "Ninguém ", "Você est"]
    assert chamadas[2][0] == "chatterbox" and chamadas[2][2]["exaggeration"] == pytest.approx(0.73)
    f = audio["falas"]
    # pontas cortadas: cada fala dura ~ o tom, e a próxima começa depois da pausa pedida
    assert f[0]["inicio"] == 0 and f[0]["fim"] == pytest.approx(1.54, abs=0.05)
    assert f[1]["inicio"] == pytest.approx(f[0]["fim"] + 0.3, abs=0.02)
    assert audio["duracao"] == pytest.approx(f[-1]["fim"], abs=0.1)
    srt = (md.pasta_projeto(base, pid) / "legenda_personagens.srt").read_text(encoding="utf-8")
    assert "NARRADOR: Era uma noite fria" in srt and "YUKI: Você está me ouvindo?" in srt and "[gasp]" not in srt
    limpa = (md.pasta_projeto(base, pid) / "legenda.srt").read_text(encoding="utf-8")
    assert "— Você está me ouvindo?" in limpa
    # 2ª geração: nada mudou -> reaproveita
    md.gerar_audio(base, pid, gerar_fn=gerar_fn, normalizar=False)
    assert len(chamadas) == 3

    p = md.carregar_projeto(base, pid)
    pa = md.prompt_ajuste(p, md.obter_estilo("kamishibai"))
    assert "1: 0.00s →" in pa and "no MÁXIMO 4s" in pa
    total = audio["duracao"]
    resposta = {"cenas": [
        {"id": 1, "inicio": 0.3, "fim": 3.0, "falas": [1], "cena": "A dark well at night", "movimento": "Camera panning slowly from left to right"},
        {"id": 2, "inicio": 3.0, "fim": 5.5, "falas": [2], "cena": "Yuki by the well", "movimento": "Slow push-in"},
        {"id": 3, "inicio": 5.5, "fim": total, "falas": [3], "cena": "Empty well, fog", "movimento": "Static, fog drifts"},
    ]}
    p = md.aplicar_ajuste(base, pid, json.dumps(resposta))
    cenas = p["cenas"]
    assert cenas[0]["inicio"] == 0 and cenas[-1]["fim"] == pytest.approx(total)
    assert all(a["fim"] == b["inicio"] for a, b in zip(cenas, cenas[1:]))

    auto, _av = md.distribuir_automatico(p, md.obter_estilo("kamishibai"))
    assert all(c["duracao"] <= 4.05 for c in auto) and auto[-1]["fim"] == pytest.approx(total)

    # Flow falso
    class Foto:
        def __init__(self, caminho):
            self.local_path = caminho
    pasta_fake = ambiente / "fake"
    pasta_fake.mkdir()

    class Cliente:
        pedidos = []

        def preparar_trabalho(self, t):
            return dict(t, chave=t["id"])

        def gerar_lote(self, fila, abas=2, cooldown=(2, 9), on_evento=None, cancelar=None):
            self.abas_pedidas = abas
            while fila:
                t = fila.popleft()
                self.pedidos.append(t)
                on_evento({"tipo": "aba", "aba": 1, "estado": "gerando"})
                on_evento({"tipo": "inicio", "trab": t, "aba": 1})
                p = md.carregar_projeto(base, pid)
                c = next(x for x in p["cenas"] if x["id"] == t["cena"])
                assert c["status"] in ("gerando_frame", "animando") and c["aba"] == 1 and c["gerando_desde"] > 1e9
                assert c["inicio"] < 100  # o tempo da cena no vídeo não é tocado
                arq = str(pasta_fake / f"{len(self.pedidos)}.{'mp4' if t['tipo'] == 'animar' else 'png'}")
                if t["tipo"] == "animar":
                    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=90x160:d=2",
                                    "-pix_fmt", "yuv420p", arq], check=True)
                else:
                    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=90x160",
                                    "-frames:v", "1", arq], check=True)
                on_evento({"tipo": "fim", "trab": t, "arquivo": arq, "aba": 1, "segundos": 3})
    cli = Cliente()
    # ⚡ tudo: cada frame pronto já põe a animação daquela cena na fila
    md.gerar_flow(base, pid, cli, "tudo", abas=3)
    tipos = [(x["tipo"], x["cena"]) for x in cli.pedidos]
    assert tipos[0] == ("imagem", 1) and ("animar", 1) in tipos and len(tipos) == 2 * len(md.carregar_projeto(base, pid)["cenas"])
    img = cli.pedidos[0]
    assert img["prompt"].startswith("A dark well at night, Japanese kamishibai") and img["prompt"].endswith("--ar 9:16")
    assert img["modelo"] == "Nano Banana 2.1" and img["proporcao"] == "9:16" and cli.abas_pedidas == 3
    vid = [x for x in cli.pedidos if x["tipo"] == "animar"][0]
    assert "low frame rate 2D cutout animation" in vid["prompt"] and vid["duracao"] == "4s" and vid["modelo"] == "Omni 1.1 Flash"
    assert os.path.basename(vid["imagem"]).startswith("cena_001_")
    p = md.carregar_projeto(base, pid)
    assert p["etapa"] == "pronto" and all(c["video"] and c["status"] == "video" for c in p["cenas"])
    # erro numa cena: marca a cena e o resto continua
    class ClienteErro(Cliente):
        def gerar_lote(self, fila, abas=2, cooldown=(2, 9), on_evento=None, cancelar=None):
            while fila:
                t = fila.popleft()
                on_evento({"tipo": "erro", "trab": t, "erro": "O Flow recusou"})
    md.gerar_flow(base, pid, ClienteErro(), "frames", indices=[1])
    c1 = md.carregar_projeto(base, pid)["cenas"][0]
    assert c1["status"] == "erro" and "recusou" in c1["erro"] and c1["imagem"]  # o frame antigo continua
    md.gerar_flow(base, pid, cli, "frames", indices=[1])
    c1 = md.carregar_projeto(base, pid)["cenas"][0]
    assert c1["status"] == "frame" and not c1["video"]  # frame novo descarta a animação antiga
    md.gerar_flow(base, pid, cli, "animar", indices=[1])

    # mudar só o movimento mantém o frame e descarta o vídeo
    md.editar_cena(base, pid, 2, movimento="Fast zoom")
    c2 = md.carregar_projeto(base, pid)["cenas"][1]
    assert c2["imagem"] and not c2["video"]

    # roteiro reaplicado depois do áudio: não deixa mandar áudio velho pro Estúdio
    p_tmp = md.carregar_projeto(base, pid); p_tmp["audio_desatualizado"] = True; md.salvar_projeto(base, p_tmp)
    with pytest.raises(md.ModeladoError, match="gere o áudio de novo"):
        md.pacote_para_editor(base, pid, str(ambiente / "job"))
    p_tmp["audio_desatualizado"] = False; md.salvar_projeto(base, p_tmp)
    pac = md.pacote_para_editor(base, pid, str(ambiente / "job"))
    assert os.path.isfile(pac["audio_path"]) and pac["orientation"] == "9:16" and pac["legendas"]["ativa"]
    segs = pac["pending_segments"]
    assert segs[0]["override_source"]["kind"] == "video" and segs[1]["override_source"]["kind"] == "image"
    assert pac["sem_video"] == [2]
    # vídeo de 2s numa cena maior foi desacelerado
    assert segs[0]["override_source"]["value"].endswith("_ajustado.mp4")
    assert pac["segments"][1]["text"] == "Você está me ouvindo?"


def test_rotas(ambiente, monkeypatch):
    from flask import Flask
    import modelados_rotas
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates"))
    jobs = {}

    @app.route("/job/<job_id>/edit-segments")
    def edit_segments_page(job_id):
        return "ok"
    for nome in ("gerar_voz_page", "narracoes_page", "perfis_de_voz_page", "capturar_pagina_page", "cortar_youtube_page",
                 "redes_sociais_page", "extrair_links_canal_page", "transcrever_page", "contas_google_page",
                 "jobs_history_page", "textos_avulsos_page", "roteiros_yt_page", "vendas_page", "dossies_page", "guia_page", "settings_page", "ia_page"):
        app.add_url_rule("/" + nome, nome, lambda: "")
    modelados_rotas.registrar(app, str(ambiente), jobs, lambda j: None, lambda j: str(ambiente / "jobs" / j), lambda: {})
    c = app.test_client()
    assert c.get("/modelados").status_code == 200
    r = c.post("/modelados/novo", data={"tema": "Lenda", "estilo_id": "kamishibai", "duracao_alvo": "30"})
    assert r.status_code == 302
    pid = r.headers["Location"].rstrip("/").split("/")[-1]
    assert c.get(f"/modelados/{pid}").status_code == 200
    assert "Kamishibai" in c.get(f"/modelados/{pid}/prompt-roteiro").get_json()["prompt"]
    r = c.post(f"/modelados/{pid}/roteiro", json={"json": json.dumps(ROTEIRO)})
    assert r.status_code == 200 and len(r.get_json()["projeto"]["roteiro"]["falas"]) == 3
    r = c.post(f"/modelados/{pid}/fala/2", json={"texto": "Está me ouvindo?", "pausa_depois": "0.9"})
    f2 = r.get_json()["projeto"]["roteiro"]["falas"][1]
    assert f2["texto"] == "Está me ouvindo?" and f2["pausa_depois"] == 0.9
    assert not r.get_json()["projeto"].get("audio_desatualizado")  # sem áudio ainda, nada a avisar
    assert c.post(f"/modelados/{pid}/ajuste-auto").status_code == 400  # sem áudio ainda
    r = c.post("/modelados/estilos", json={"nome": "Neon", "prompt_imagem": "{cena} neon --ar {ar}", "prompt_animacao": "{movimento}"})
    assert r.get_json()["estilo"]["id"] == "neon"
