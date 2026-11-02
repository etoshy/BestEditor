"""v84_325: 🎤 canal de voz própria — o roteiro sai, você grava aos poucos (takes, editor, realce) e a edição continua."""
import os
import shutil
import subprocess
import time

import curtos as CT
import curtos_comentario as CC
import curtos_rotas as CR
import gravar_voz as GV
from test_v84_320_lote_por_etapa import _app, _espera, _falsos


def _som(caminho, dur=1.0, freq=440):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={dur}", caminho],
                   check=True, timeout=60)
    return caminho


def _projeto(base, n=2):
    p = CT.criar(base, "", "t", modelo="comentario")
    p["roteiro"] = {"idioma": "en", "blocos": [{"id": f"B{k}", "fala": f"line {k} [laugh]", "fala_en": f"line {k}", "fala_pt": f"linha {k}"}
                                               for k in range(1, n + 1)]}
    CT.salvar(base, p)
    return p["id"]


def test_takes_partes_juntar_e_realce(tmp_path, monkeypatch):
    base = str(tmp_path)
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    pid = _projeto(base)
    ps = GV.partes(CT.carregar(base, pid))
    assert ps[0]["texto"] == "line 1" and ps[0]["traducao"] == "linha 1"  # sem a tag de voz; tradução do lado
    a = GV.adicionar_take(base, pid, "B1", _som(str(tmp_path / "a.wav"), 1.0))
    GV.adicionar_take(base, pid, "B1", _som(str(tmp_path / "b.wav"), 0.6))
    assert GV.faltando(base, pid) == ["B2"]
    GV.usar_take(base, pid, "B1", a["takeId"])
    GV.adicionar_take(base, pid, "B2", _som(str(tmp_path / "c.wav"), 0.8))
    assert GV.faltando(base, pid) == []
    monkeypatch.setattr(GV, "_realcar", lambda o, d: shutil.copy(o, d))
    t = GV.realce(base, pid, "B1", a["takeId"], True)
    assert t["usar_realce"] and GV.caminho_take(base, pid, "B1", a["takeId"]).endswith("_realce.wav")
    final = GV.juntar(base, pid)
    assert abs(CT.duracao_audio(final) - (1.0 + 0.8 + 2 * GV.PAUSA_ENTRE_PARTES_S)) < 0.15
    r = GV.resumo(base, pid)
    assert r["partes"][0]["id"] == GV.TUDO and r["total_s"] == 1.8
    tudo = GV.adicionar_take(base, pid, GV.TUDO, _som(str(tmp_path / "d.wav"), 2.0))
    assert abs(CT.duracao_audio(GV.juntar(base, pid)) - 2.0) < 0.1  # o TUDO vale no lugar das partes
    GV.apagar_take(base, pid, GV.TUDO, tudo["takeId"])
    assert not GV.estado(base, pid)["partes"][GV.TUDO]["takes"]
    try:
        GV.adicionar_take(base, pid, "../x", str(tmp_path / "a.wav"))
        assert False
    except CT.CurtoErro:
        pass


def _canal_minha(cl, nome="Animal IQ", arroba="@AnimalIQ26"):
    cid = cl.post("/curtos/canais/novo", json={"nome": nome, "voz_link": {"modo": "minha"}}).get_json()["id"]
    cl.post("/curtos/acabamento", json={"canal_id": cid, "arroba": arroba})
    return cid


def test_link_para_no_roteiro_e_continua_depois_da_voz(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    log, _ = _falsos(base, monkeypatch)
    cid = _canal_minha(cl)

    def gravacao_falsa(b, pid, tr, arquivo, op, prog, fonte=""):
        log.append(("gravacao", pid, fonte))
        with CT._TRAVA:
            q = CT.carregar(b, pid)
            q["gravacao"] = {"arquivo": "g.wav", "chave_roteiro": CT.chave_roteiro(q["roteiro"])}
            CT.salvar(b, q)
    monkeypatch.setattr(CT, "processar_gravacao", gravacao_falsa)
    # o termo em cima dos links é o @ do canal (sem ligar o grupo à mão)
    r = cl.post("/curtos/link/novo", json={"link": "@AnimalIQ26:\nhttps://a.com/1\nOutro\nhttps://a.com/2", "iniciar": True,
                                           "exportar": False, "voz": "v1"}).get_json()
    meu, outro = r["criados"]
    assert CT.carregar(base, meu)["canal_id"] == cid and CT.carregar(base, meu)["config"]["voz_modo"] == "minha"
    _espera(r["criados"])
    lr = CT.carregar(base, meu)["link_rapido"]
    assert lr["aguardando_voz"] and lr["etapa"] == "🎤 grave a sua voz" and not CR.TAREFAS[meu]["erro"]
    assert ("voz", meu, "v1") not in log and not any(x[0] == "voz" and x[1] == meu for x in log)  # a IA não narrou
    assert any(x[0] == "editor" and x[1] == outro for x in log)  # o outro canal seguiu normal
    v = {x["id"]: x for x in cl.get("/curtos/link/estado").get_json()["videos"]}
    assert v[meu]["aguardando_voz"] and not v[meu]["pendente"]  # o vigia da retomada não pega
    pagina = cl.get(f"/curtos/{meu}/gravar")
    assert pagina.status_code == 200 and "editor_audio.js" in pagina.get_data(as_text=True)
    assert cl.post(f"/curtos/{meu}/voz/enviar", json={}).status_code == 400  # falta gravar
    for b in GV.partes(CT.carregar(base, meu)):
        with open(_som(str(tmp_path / f"{b['id']}.wav"), 0.5), "rb") as f:
            j = cl.post(f"/curtos/{meu}/voz/parte/{b['id']}", data={"audio": (f, "t.wav")}, content_type="multipart/form-data").get_json()
        assert j["ok"] and j["takeId"]
    assert cl.post(f"/curtos/{meu}/voz/enviar", json={}).get_json()["ok"]
    _espera([meu])
    assert not CR.TAREFAS[meu]["erro"], CR.TAREFAS[meu]
    assert ("gravacao", meu, "gravacao") in log and any(x[0] == "editor" and x[1] == meu for x in log)
    lr = CT.carregar(base, meu)["link_rapido"]
    assert not lr.get("aguardando_voz") and lr["etapa"] == "✅ no editor"


def test_lote_por_etapa_pula_quem_grava(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    log, _ = _falsos(base, monkeypatch)
    _canal_minha(cl, "Fails BR", "@failsbr")
    r = cl.post("/curtos/link/novo", json={"link": "Fails BR\nhttps://a.com/1\nhttps://a.com/2\nX\nhttps://a.com/3", "iniciar": True,
                                           "por_etapa": True, "exportar": False, "voz": "v1"}).get_json()
    a, b, c = r["criados"]
    _espera(r["criados"])
    for pid in (a, b):
        assert CT.carregar(base, pid)["link_rapido"]["aguardando_voz"] and not CR.TAREFAS[pid]["erro"]
        assert any(x[0] == "roteiro" and x[1] == pid for x in log) and not any(x[0] in ("voz", "editor") and x[1] == pid for x in log)
    assert any(x[0] == "editor" and x[1] == c for x in log)
    assert "esperando a sua voz" in (CR.TAREFAS.get("lote-etapa:" + a) or {}).get("msg", "")


def test_editor_de_audio_compartilhado(tmp_path, monkeypatch):
    cl = _app(tmp_path, monkeypatch)
    raiz = os.path.dirname(os.path.abspath(CT.__file__))
    with open(os.path.join(raiz, "static", "editor_audio.js"), encoding="utf-8") as f:
        js = f.read()
    assert "function abrirEditorAudio" in js and "urlGravar(indice)" in js
    with open(os.path.join(raiz, "templates", "curto_gravar.html"), encoding="utf-8") as f:
        t = f.read()
    for gancho in ("function urlGravar", "function urlGerarRealce", "var GRAVACOES", "function renderizarGravacoes", "function blocoDaFala"):
        assert gancho in t
    assert cl.get("/curtos/naoexiste/gravar").status_code == 404


def test_aba_avulsa_texto_livre(tmp_path, monkeypatch):
    """🎙 a aba separada: cola o texto, grava as partes, junta e baixa — sem curto nenhum."""
    cl = _app(tmp_path, monkeypatch)
    monkeypatch.setenv("GRAVAR_VOZ_DIR", str(tmp_path / "gv"))
    assert cl.get("/gravar-voz").status_code == 200
    r = cl.post("/gravar-voz/nova", data={"titulo": "teste mic", "texto": "Primeira frase. Segunda frase!", "separar": "frase"})
    assert r.status_code == 302
    sid = r.headers["Location"].rsplit("/", 1)[-1]
    assert sid.startswith("av_")
    pg = cl.get(f"/gravar-voz/{sid}").get_data(as_text=True)
    assert "Primeira frase." in pg and 'id="micSel"' in pg and 'id="bEnviar"' not in pg
    est = cl.get(f"/curtos/{sid}/voz/estado").get_json()["estado"]
    assert [x["id"] for x in est["partes"]] == ["TUDO", "P1", "P2"]
    assert cl.post(f"/curtos/{sid}/voz/juntar", json={}).status_code == 400  # falta gravar
    for k, parte in enumerate(("P1", "P2")):
        with open(_som(str(tmp_path / f"{parte}.wav"), 0.5 + k * 0.5), "rb") as f:
            assert cl.post(f"/curtos/{sid}/voz/parte/{parte}", data={"audio": (f, "t.webm")}, content_type="multipart/form-data").get_json()["ok"]
    j = cl.post(f"/curtos/{sid}/voz/juntar", json={}).get_json()
    assert j["ok"] and j["estado"]["final"]
    wav = cl.get(f"/curtos/{sid}/voz/final.wav?baixar=1")
    assert wav.status_code == 200 and wav.data[:4] == b"RIFF" and "attachment" in wav.headers.get("Content-Disposition", "")
    # trocar o texto: P1 mantém os takes, P3 é nova
    est = cl.post(f"/gravar-voz/{sid}/texto", json={"texto": "Um\nDois\nTrês", "separar": "linha"}).get_json()["estado"]
    assert [x["texto"] for x in est["partes"][1:]] == ["Um", "Dois", "Três"] and est["partes"][1]["ativo"] and est["faltando"] == ["P3"]
    assert "teste mic" in cl.get("/gravar-voz").get_data(as_text=True)
    assert cl.post(f"/gravar-voz/{sid}/apagar").status_code == 302
    assert cl.get(f"/gravar-voz/{sid}").status_code == 404
    assert cl.get("/gravar-voz/nao_existe").status_code == 404
