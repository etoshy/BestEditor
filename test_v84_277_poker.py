"""v84_277: 🃏 Poker — motor da mão (pots, side pots, avaliador, modalidades), mesa animada (POV, zoom, emoções,
estéticas, moedas), 🏆 ranking e 🎬 roteiros com pesquisa/checagem."""
import json
import os
import re
import shutil
import subprocess

import pytest

import poker_doc as PD
import poker_mesa as PM
import poker_ranking as RK
import poker_render as PR


def _venc(r):
    return next(e for e in r["eventos"] if e["tipo"] == "vencedor")


# ------------------------------------------------------------------ motor
def test_exemplo_pot_e_showdown():
    r = PM.simular(PM.EXEMPLO)
    v = _venc(r)
    assert v["dados"]["pot"] == 138.5 and r["jogadores"][v["dados"]["quem"][0]]["nome"] == "NewSted"
    assert v["depois"]["jogos"][0] == "Flush, A alto" and r["duracao"] > 20
    assert [e["tipo"] for e in r["eventos"]].count("board") == 5


def test_avaliador_categorias():
    nome = lambda cs: PM.nome_jogo(PM.avaliar(PM.cartas(cs))[0])  # noqa: E731
    assert nome("As Ks Qs Js Ts 2c 3d") == "Royal flush"
    assert nome("Ah 2c 3d 4s 5h Kd Qc") == "Sequência até 5"
    assert nome("Kh Kd Kc 7s 7h 2c 3d").startswith("Full house")
    assert PM.avaliar(PM.cartas("Ah Ad Kc 8s 3h Jd 9c"))[0] > PM.avaliar(PM.cartas("Ac As Qc 8d 3c Jh 9d"))[0]  # kicker


def test_side_pot_e_empate():
    txt = """mesa: blinds=1/2
jogador: A 20 As Ah
jogador: B 100 Kd Kc
jogador: C 100 Qd Qc
botao: A
preflop: A allin; B raise 60; C call; B allin; C call
flop: 2s 7d 9c
turn: 3h
river: 4d"""
    r = PM.simular(txt)
    v = _venc(r)
    fim = v["depois"]
    assert fim["ganhos"][0] == pytest.approx(60) and fim["ganhos"][1] == pytest.approx(160)
    split = PM.simular("""mesa: blinds=1/2
jogador: A 50 2c 3d
jogador: B 50 7h 7s
botao: A
preflop: A raise 6; B allin; A call
flop: Ah Kh Qd
turn: Jc
river: Ts""")
    assert sorted(_venc(split)["dados"]["quem"]) == [0, 1]


def test_pokerstars_e_omaha():
    hh = """PokerStars Hand #1: Omaha Pot Limit ($0.50/$1.00 USD) - 2020/01/01
Table 'X' 6-max Seat #1 is the button
Seat 1: Ana ($100 in chips)
Seat 2: Bia ($100 in chips)
Ana: posts small blind $0.50
Bia: posts big blind $1
*** HOLE CARDS ***
Dealt to Ana [As Ad Kh Qh]
Ana: raises $2 to $3
Bia: calls $2
*** FLOP *** [Ah 6c 2s]
Bia: checks
Ana: bets $3
Bia: folds
"""
    m = PM.ler(hh)
    assert m["mesa"].get("jogo") == "omaha"
    r = PM.simular(hh)
    assert r["ncartas"] == 4 and r["variante"] == "omaha"
    with pytest.raises(PM.PokerErro):
        PM.simular("mesa: jogo=plo\njogador: A 10 As Kd\njogador: B 10\npreflop: A fold")


def test_omaha_exatamente_duas_e_short_deck():
    f, v, _ = PM.avaliar_mao(PM.cartas("Ah 9c 8d 7s"), PM.cartas("Kh Qh 5h 2h Tc"), "omaha")
    assert v[0] != 5  # um copas só na mão: não é flush no Omaha
    assert PM.avaliar_mao(PM.cartas("Ah 9c"), PM.cartas("Kh Qh 5h 2h Tc"), "holdem")[1][0] == 5
    fl = PM.avaliar_mao(PM.cartas("Ah 9h"), PM.cartas("Kh Th 7h Ts 6c"), "shortdeck")
    fu = PM.avaliar_mao(PM.cartas("Kc Kd"), PM.cartas("Kh Th 7h Ts 6c"), "shortdeck")
    assert fl[0] > fu[0]  # Short Deck: flush > full house
    assert PM.avaliar_mao(PM.cartas("Kc Kd"), PM.cartas("Kh Th 7h Ts 6c"), "holdem")[0] > PM.avaliar_mao(PM.cartas("Ah 9h"), PM.cartas("Kh Th 7h Ts 6c"), "holdem")[0]
    assert PM.nome_jogo(PM.avaliar_mao(PM.cartas("Ac 9d"), PM.cartas("6h 7s 8d Kc Qh"), "shortdeck")[1]) == "Sequência até 9"
    with pytest.raises(PM.PokerErro):
        PM.simular("mesa: jogo=6+\njogador: A 10 As 2d\njogador: B 10\npreflop: A fold")


def test_efeitos_narrativos_zoom_emocao_pov_pais_dinheiro():
    t = PM.EXEMPLO.replace(
        "river: 7c | FlipFlopidy check; NewSted allin; FlipFlopidy call",
        'river: 7c | FlipFlopidy check; [zoom: NewSted 1.5]; NewSted allin; [emocao: FlipFlopidy ansioso "ele tem?"]; '
        "[mostrar: pov]; FlipFlopidy call; [zoom: off]\nemocao: NewSted 😎")
    t = t.replace("jogador: NewSted 79 Ad 5d heroi", "jogador: NewSted 79 Ad 5d heroi pais=lt")
    t = t.replace("titulo=", 'dinheiro="US$ 1 mi em 2003" estetica=tv2000 titulo=')
    r = PM.simular(t)
    assert [z["alvo"] for z in r["zooms"]] == [0, "off"] and r["zooms"][0]["escala"] == 1.5
    assert r["emocoes"][0]["emoji"] == "😰" and r["emocoes"][0]["texto"] == "ele tem?" and r["emocoes"][1]["emoji"] == "😎"
    assert r["mostrares"][0]["modo"] == "pov" and r["jogadores"][0]["pais"] == "LT"
    assert r["dinheiro"].startswith("US$") and r["estetica"] == "tv2000"
    assert _venc(r)["dados"]["pot"] == 138.5  # os efeitos não mudam a mão
    with pytest.raises(PM.PokerErro):
        PM.simular(PM.EXEMPLO.replace("FlipFlopidy check; NewSted bet 20", "FlipFlopidy check; [voar: x]; NewSted bet 20"))


def test_shorts_ritmo_e_pov_auto():
    a = PM.simular(PM.EXEMPLO)
    b = PM.simular(PM.EXEMPLO, ritmo="shorts", pov="auto")
    assert b["ritmo"] == "shorts" and sum(e["tipo"] == "camera" for e in b["eventos"]) > sum(e["tipo"] == "camera" for e in a["eventos"])
    rv = lambda r: next(e for e in r["eventos"] if e["tipo"] == "board" and e["dados"]["pos"] == 4)["dur"]  # noqa: E731
    assert rv(b) > rv(a) * 2  # o river vira devagar


# ------------------------------------------------------------------ render
def _js_ok(html, tmp_path):
    if not shutil.which("node"):
        pytest.skip("sem node")
    for k, js in enumerate(re.findall(r"<script>(.*?)</script>", html, re.S)):
        f = tmp_path / f"p{k}.js"
        f.write_text(js, encoding="utf-8")
        r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-400:]


def test_pagina_mesa_e_ranking(tmp_path):
    d = PM.simular(PM.EXEMPLO)
    for est in PR.ESTETICAS:
        op = PR.normalizar({"estetica": est, "formato": "9:16", "mostrar": "pov", "estilo": "shorts", "emocoes": True})
        html = PR.pagina(d, op, "/f", lambda a: "", "previa")
        assert "__DADOS__" not in html and '"estetica"' in html
    _js_ok(html, tmp_path)
    for var in ("holdem", "plo", "6+"):
        rk = RK.montar({"variante": var, "formato": "1:1"})
        assert rk["cenas"][0]["tipo"] == "intro" and rk["cenas"][-1]["tipo"] == "final"
        assert sum(c["tipo"] == "cat" for c in rk["cenas"]) == 10 and RK.narracao(rk).count("Número") == 10
    _js_ok(RK.pagina(rk, "/f", "previa"), tmp_path)
    sd = RK.montar({"variante": "6+", "ordem": "decrescente"})
    nomes = [c["nome"] for c in sd["cenas"] if c["tipo"] == "cat"]
    assert nomes.index("Flush") < nomes.index("Full House") and nomes.index("Trinca") < nomes.index("Sequência")
    du = RK.montar({"duelos_texto": "Teste: Ah Kd vs Ac Qs | As 8d 5c 3h 2s"})
    duelo = next(c for c in du["cenas"] if c["tipo"] == "duelo")
    assert duelo["venc"] == "a" and duelo["titulo"] == "Teste"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg")
def test_gravar_mp4_curto(tmp_path):
    pytest.importorskip("playwright")
    d = PM.simular("""mesa: blinds=0.5/1 titulo="t"
jogador: A 10 As Ad heroi
jogador: B 10 Kd Kc
botao: A
preflop: A allin; B call
flop: 2s 7d 9c
turn: 3h
river: 4d""", velocidade=3)
    saida = str(tmp_path / "m.mp4")
    try:
        PR.gravar(d, {"formato": "1:1", "fps": 24, "estilo": "shorts", "estetica": "vegas70"}, saida)
    except Exception as exc:  # noqa: BLE001  (sem chromium no ambiente)
        if "Executable doesn't exist" in str(exc) or "playwright" in str(exc).lower():
            pytest.skip(str(exc)[:80])
        raise
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", saida],
                         capture_output=True, text=True).stdout
    assert "video" in out and "audio" in out


# ------------------------------------------------------------------ roteiros
ROTEIRO = {"titulo": "O gênio", "titulos": ["t1", "t2"], "blocos": [
    {"tipo": "narracao", "texto": "Era uma vez um garoto em Nova York.", "visual": "foto antiga",
     "mao": {k: "" for k in PD.MAO_SCHEMA["properties"]}},
    {"tipo": "mao", "texto": "E aí ele empurra tudo.", "visual": "", "mao": {
        "titulo": "A mão decisiva", "por_que": "virou a final", "contexto_antes": "mesa final", "contexto_depois": "ganhou",
        "estrategia": "pressão em stack curto", "status": "real", "fonte": "PokerNews", "mao": PM.EXEMPLO}},
    {"tipo": "mao", "texto": "x", "visual": "", "mao": {
        "titulo": "Mão quebrada", "por_que": "", "contexto_antes": "", "contexto_depois": "", "estrategia": "", "status": "inventado",
        "fonte": "", "mao": "jogador: A 10"}}]}


def test_doc_fluxo(tmp_path, monkeypatch):
    monkeypatch.setenv("POKER_DIR", str(tmp_path / "poker"))
    base = str(tmp_path)
    d = PD.novo(base, "o gênio do poker", "infância difícil", "documentario", moeda="R$")
    d = PD.pesquisar(base, d["id"], lambda q: {"resposta_completa": "nasceu em 1953", "fontes": [{"titulo": "Wiki", "url": "https://x"}]})
    assert d["pesquisa"]["fontes"][0]["url"] == "https://x"
    vistos = []

    def chamar(recurso, sistema, conteudo, **kw):
        vistos.append((sistema, conteudo))
        return json.loads(json.dumps(ROTEIRO))
    d = PD.escrever(base, d["id"], chamar=chamar)
    assert "nasceu em 1953" in vistos[0][1] and "mostrar: pov" in vistos[0][0] and "R$" in vistos[0][0]
    maos = [b for b in d["blocos"] if b["tipo"] == "mao"]
    assert maos[0]["validacao"]["ok"] and "NewSted" in maos[0]["validacao"]["resumo"]
    assert not maos[1]["validacao"]["ok"] and maos[1]["mao"]["status"] == "ilustrativa"
    txt = PD.texto_narracao(d)
    assert "mesa final" in txt and "Era uma vez" in txt
    p = PD.prompt_checagem(d)
    assert "AS MÃOS" in p and "A mão decisiva" in p
    # cola a resposta da outra IA e aplica
    resp = json.dumps({"correcoes": [{"de": "Nova York", "para": "Manhattan", "status": "corrigido", "item": "V1", "problema": "lugar"}],
                       "verificar": [], "inconsistencias": [], "resumo": "ok"})
    d = PD.ler_checagem(base, d["id"], resp)
    d = PD.aplicar_trocas(base, d["id"])
    assert "Manhattan" in d["blocos"][0]["texto"]
    # editar a mão invalida o vídeo e revalida
    bl = d["blocos"]
    bl[2]["mao"]["mao"] = PM.EXEMPLO
    d = PD.salvar_blocos(base, d["id"], bl)
    assert [b for b in d["blocos"] if b["tipo"] == "mao"][1]["validacao"]["ok"]


def test_mao_de_descricao_corrige_uma_vez():
    respostas = [{"mao": "jogador: A 10"}, {"mao": PM.EXEMPLO}]
    vistos = []

    def chamar(recurso, sistema, conteudo, **kw):
        vistos.append(conteudo)
        return respostas.pop(0)
    assert PD.mao_de_descricao("uma mão aí", chamar) == PM.EXEMPLO.strip()
    assert "deu erro no motor" in vistos[1]


# ------------------------------------------------------------------ rotas
@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setenv("POKER_DIR", str(tmp_path / "poker"))
    from flask import Flask
    import poker_rotas as R
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates"))
    R.registrar(app, str(tmp_path))
    R.CB.clear()
    return app.test_client(), R


def test_rotas_mesa(cliente, tmp_path):
    c, R = cliente
    r = c.post("/poker/simular", json={"texto": PM.EXEMPLO}).get_json()
    assert r["ok"] and "NewSted" in r["resumo"]
    assert c.post("/poker/simular", json={"texto": "jogador: A"}).status_code == 400
    p = c.post("/poker/previa", json={"texto": PM.EXEMPLO, "op": {"formato": "9:16"}}).get_json()
    assert "window.render" in p["html"] and "/poker/fontes/" in p["html"]
    # foto pelo nome
    from io import BytesIO
    from PIL import Image
    b = BytesIO()
    Image.new("RGB", (400, 300), "red").save(b, "PNG")
    b.seek(0)
    up = c.post("/poker/avatar", data={"nome": "NewSted", "arquivo": (b, "f.png")}, content_type="multipart/form-data").get_json()
    assert up["arquivo"] == "newsted.jpg"
    r = c.post("/poker/simular", json={"texto": PM.EXEMPLO}).get_json()
    assert r["jogadores"][0]["avatar"] == "newsted.jpg"
    assert c.get("/poker/avatar/newsted.jpg").status_code == 200
    m = c.post("/poker/mao/salvar", json={"titulo": "A5", "texto": PM.EXEMPLO}).get_json()["mao"]
    assert c.get(f"/poker/mao/{m['id']}").get_json()["mao"]["titulo"] == "A5"
    # exportar (gravar falso) → vídeo listado na mão
    R.CB["gravar"] = lambda d, op, saida, prog, pa, parar: open(saida, "wb").write(b"x")
    t = c.post("/poker/exportar", json={"id": m["id"], "texto": PM.EXEMPLO}).get_json()["tarefa"]
    import time
    for _ in range(50):
        tt = c.get("/poker/tarefa/" + t).get_json()["tarefa"]
        if not tt["rodando"]:
            break
        time.sleep(0.05)
    assert tt["res"]["video"].endswith(".mp4") and not tt["erro"]
    assert c.get("/poker/video/" + tt["res"]["video"]).status_code == 200
    assert R.carregar_mao(str(tmp_path), m["id"])["video"] == tt["res"]["video"]
    html = c.get("/poker").get_data(as_text=True)
    assert "A5" in html and "Ranking" in html
    _js_ok(html, tmp_path)
    rk = c.post("/poker/ranking/previa", json={"op": {"variante": "plo"}}).get_json()
    assert "Omaha" in rk["narracao"]


def test_rotas_doc(cliente, tmp_path):
    c, R = cliente
    loc = c.post("/poker/doc/novo", data={"tema": "Stu Ungar", "tipo": "documentario", "minutos": "6"}).headers["Location"]
    did = loc.rsplit("/", 1)[-1]
    R.CB["chamar"] = lambda *a, **k: json.loads(json.dumps(ROTEIRO))
    t = c.post(f"/poker/doc/{did}/escrever", json={}).get_json()["tarefa"]
    import time
    for _ in range(50):
        if not c.get("/poker/tarefa/" + t).get_json()["tarefa"]["rodando"]:
            break
        time.sleep(0.05)
    est = c.get(f"/poker/doc/{did}/estado").get_json()
    assert est["doc"]["titulo"] == "O gênio" and len(est["doc"]["blocos"]) == 3
    html = c.get(loc).get_data(as_text=True)
    _js_ok(html, tmp_path)
    bid = est["doc"]["blocos"][1]["id"]
    m = c.post(f"/poker/doc/{did}/mao/{bid}/abrir", json={}).get_json()["mao"]
    assert m["origem"] == f"{did}:{bid}"
    assert "AS MÃOS" in c.get(f"/poker/doc/{did}/checagem").get_json()["prompt"]
    assert "Era uma vez" in c.get(f"/poker/doc/{did}/texto").get_data(as_text=True)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg")
def test_sons_nao_saem_mudos(tmp_path, monkeypatch):
    """v84_277: o bandpass sem width_type=h deixava a carta quase muda (-70 dB) — os sons têm que ser audíveis."""
    monkeypatch.setenv("POKER_DIR", str(tmp_path / "pk"))
    for k in ("carta", "virar", "ficha", "fichas", "vitoria", "impacto", "suspense", "whoosh"):
        arq = PR._som(k, str(tmp_path / f"{k}.wav"))
        r = subprocess.run(["ffmpeg", "-i", arq, "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
        pico = float(re.search(r"max_volume: (-?[\d.]+) dB", r.stderr).group(1))
        assert pico > -40, (k, pico)


def test_camera_mover_e_muck():
    assert PR.normalizar({})["camera"] == "mover" and PR.normalizar({"camera": "girar"})["camera"] == "girar"
    html = PR.pagina(PM.simular(PM.EXEMPLO), PR.normalizar({}), "/f", lambda a: "", "gravar")
    assert "camEm(" in html and "PSI" in html and "noMuck" in html and "_verso.style.visibility" in html


# ------------------------------------------------------------------ acordos, run it twice, 3D
BASE_AA_KK = """mesa: blinds=1/2
jogador: A 100 As Ah
jogador: B 100 Kd Kc
botao: A
preflop: A raise 6; B allin; A call
"""


def test_acordo_e_run_it_twice():
    r = PM.simular(BASE_AA_KK + "acordo: equidade\nflop: 2s 7d 9c\nturn: 3h\nriver: Kh\n")
    g = _venc(r)["depois"]["ganhos"]
    assert g[0] > g[1] > 0 and g[0] + g[1] == pytest.approx(200)
    assert any("Acordo" in e["dados"].get("texto", "") for e in r["eventos"] if e["tipo"] == "nota")
    r = PM.simular(BASE_AA_KK + "acordo: dividir\nflop: 2s 7d 9c\nturn: 3h\nriver: Kh\n")
    assert _venc(r)["depois"]["ganhos"] == {0: 100.0, 1: 100.0}
    r = PM.simular(BASE_AA_KK.replace("B allin; A call", "B call") + "flop: 2s 7d 9c | B check; A bet 10; B allin; A call; [acordo: A 70 B 30]\nturn: 3h\nriver: Kh\n")
    assert _venc(r)["depois"]["ganhos"] == {0: 140.0, 1: 60.0}
    # run it twice: cada board vale metade; A ganha o 1º (sem K), B o 2º
    r = PM.simular(BASE_AA_KK + "correr: 2\nflop: 2s 7d 9c\nturn: 3h\nriver: 4s\nboard2: 5c 6d Qs Ks 8h\n")
    v = _venc(r)["depois"]
    assert v["ganhos"] == {0: 100.0, 1: 100.0} and len(v["boards_x"]) == 1 and "2ª" in v["jogos"][0]
    with pytest.raises(PM.PokerErro):
        PM.simular(BASE_AA_KK + "correr: 2\nflop: 2s 7d 9c\nturn: 3h\nriver: 4s\nboard2: 5c 6d\n")


def test_modo_3d_pagina_e_mp4(tmp_path):
    import poker_3d as P3
    op = PR.normalizar({"modo": "3d", "estilo3d": "buckshot", "formato": "16:9", "mostrar": "pov", "logo": "X"})
    assert op["modo"] == "3d"
    html = P3.pagina(PM.simular(PM.EXEMPLO), op, "/f", lambda n: "", "previa")
    assert "__DADOS__" not in html and "function render" in html
    _js_ok(html, tmp_path)
    if not shutil.which("ffmpeg"):
        return
    pytest.importorskip("playwright")
    d = PM.simular(BASE_AA_KK + "flop: 2s 7d 9c\nturn: 3h\nriver: 4s\n", velocidade=3)
    saida = str(tmp_path / "m3d.mp4")
    P3.gravar(d, dict(op, formato="1:1", fps=24), saida)
    assert os.path.getsize(saida) > 10000


def test_rotas_personagens(cliente, tmp_path):
    c, R = cliente
    pedidos = []
    R.CB["pedir_personagem"] = lambda base, nome, desc, com_foto: (pedidos.append((nome, desc, com_foto)) or {"personagem": {}, "aviso": ""})
    assert c.post("/poker/personagem/gerar", json={"nome": "NewSted", "descricao": "velho de chapéu"}).get_json()["ok"]
    assert pedidos == [("NewSted", "velho de chapéu", True)]
    from io import BytesIO
    from PIL import Image
    b = BytesIO()
    Image.new("RGB", (200, 300), (0, 255, 0)).save(b, "PNG")
    b.seek(0)
    r = c.post("/poker/personagem/enviar", data={"nome": "NewSted", "arquivo": (b, "p.png"), "tirar_fundo": "0"},
               content_type="multipart/form-data").get_json()
    assert r["ok"] and "/poker/personagem/newsted.png" in r["url"]
    lst = c.get("/poker/personagens?nomes=NewSted|Outro").get_json()["personagens"]
    assert lst[0]["url"] and not lst[1]["url"]
    p = c.post("/poker/previa", json={"texto": PM.EXEMPLO, "op": {"modo": "3d"}}).get_json()
    assert "/poker/personagem/newsted.png" in p["html"]
    assert c.post("/poker/personagem/apagar", json={"nome": "NewSted"}).get_json()["ok"]


# ------------------------------------------------------------------ regras novas, estratégia, peças, montagem
def test_stud_draw_pot_limit_straddle():
    stud = """mesa: jogo=stud ante=1 unidade=fichas
jogador: Ana 200 As Ks Ah 7d 9c Kh 2s
jogador: Bia 200 Qd Qc 4h 4s Jd Qh 3c
jogador: Caio 200 2d 8h 5c
botao: Caio
3a: Caio bet 2; Ana raise 8; Bia call; Caio fold
4a: Ana bet 10; Bia call
5a: Ana check; Bia bet 20; Ana call
6a: Ana check; Bia check
7a: Ana bet 40; Bia raise 100; Ana call
"""
    r = PM.simular(stud)
    v = _venc(r)["depois"]
    assert v["jogos"][1].startswith("Full house") and v["ganhos"] == {1: 278.0} and r["abertas"] == [2, 3, 4, 5]
    assert sum(e["tipo"] == "carta_jogador" for e in r["eventos"]) == 3 * 3 + 2 * 4
    draw = """mesa: jogo=draw blinds=1/2
jogador: Ana 100 As Ah Kd 7c 2s
jogador: Bia 100 Qd Qc Qh 4s 9d
botao: Ana
preflop: Ana raise 6; Bia call
troca: Bia 4s 9d > Jh 3c; Ana 7c 2s > Ks 5d
pos: Bia check; Ana bet 10; Bia call
"""
    r = PM.simular(draw)
    v = _venc(r)["depois"]
    assert v["maos"][0] == ["As", "Ah", "Kd", "Ks", "5d"] and v["jogos"][1] == "Trinca de Q" and v["ganhos"] == {1: 32.0}
    with pytest.raises(PM.PokerErro):
        PM.simular(draw.replace("Ana 7c 2s > Ks 5d", "Ana 7h 2s > Ks 5d"))   # ela não tem 7h
    with pytest.raises(PM.PokerErro, match="pot-limit"):
        PM.simular("mesa: blinds=1/2 jogo=plo\njogador: A 500 As Ad Kh Qh\njogador: B 500 7c 8c 9d Td\nbotao: A\npreflop: A raise 6; B raise 50\n")
    r = PM.simular("mesa: blinds=1/2 jogo=plo\njogador: A 500 As Ad Kh Qh\njogador: B 500 7c 8c 9d Td\nbotao: A\npreflop: A raise 6; B allin; A fold\n")
    assert any(e["dados"].get("rotulo") == "RAISE 18 BB" for e in r["eventos"] if e["tipo"] == "acao")   # all-in no PL = o pote
    r = PM.simular("mesa: blinds=1/2 straddle=sim\njogador: A 100 As Ad\njogador: B 100 Kc Kd\njogador: C 100 Qc Qd\njogador: D 100\nbotao: A\npreflop: A fold; B fold; C fold\n")
    bl = next(e for e in r["eventos"] if e["tipo"] == "blinds")
    assert len(bl["dados"]["quem"]) == 3 and bl["depois"]["ultima"][3] == "STRADDLE" and _venc(r)["dados"]["quem"] == [3]


def test_ranges_e_decisao():
    assert set(PM.ler_range("AA-TT, AKs, AQo+")) == {"AA", "KK", "QQ", "JJ", "TT", "AKs", "AQo", "AKo"}
    assert PM.ler_range("22+")[-1] == "22" and len(PM.ler_range("22+")) == 13
    assert set(PM.ler_range("A5s-A2s")) == {"A5s", "A4s", "A3s", "A2s"}
    assert 14 < PM.pct_range(PM.ler_range("top 15%")) < 17 and PM.pct_range(PM.ler_range("any")) == 100.0
    with pytest.raises(PM.PokerErro):
        PM.ler_range("XYZ")
    r = PM.simular(PM.EXEMPLO.replace("flop: 3d Th 2d", "range: FlipFlopidy KQs, 22+\nflop: 3d Th 2d"), estrategia=True)
    rg = next(e for e in r["eventos"] if e["tipo"] == "range")
    assert rg["dados"]["mao"] == "KQs" and "KQs" in rg["dados"]["celulas"]
    dec = [e["dados"]["decisao"] for e in r["eventos"] if e["tipo"] == "pensa" and e["dados"].get("decisao") and e["depois"]["rua"] == "flop"]
    assert dec[0]["pagar"] == 4 and dec[0]["pote"] == 10 and dec[0]["precisa"] == pytest.approx(28.6) and dec[0]["eq"] is not None
    assert any(e["dur"] > 3 for e in r["eventos"] if e["tipo"] == "pensa")   # tempo pra ler o painel


def test_pecas_documentario(tmp_path):
    import poker_graficos as PG
    assert PG.numero("US$ 2,5 mi") == 2.5 and PG.numero("1.200.000") == 1200000 and PG.numero("34%") == 34
    op = PR.normalizar({"formato": "9:16"})
    for tipo in PG.TIPOS:
        g = {"tipo": tipo, "titulo": "Stu Ungar", "subtitulo": "The Kid", "texto": "uma frase", "numero": "US$ 1 milhão",
             "itens": [{"rotulo": "1980", "valor": "1,2 mi", "ano": "1980", "texto": "x"}, {"rotulo": "1981", "valor": "2", "ano": "1981", "texto": "y"}]}
        html = PG.pagina(g, op, 5, "/f", "", "", "frase", "previa")
        assert "__DADOS__" not in html
    _js_ok(html, tmp_path)
    assert PG.normalizar({"tipo": "Timeline"})["tipo"] == "linha_do_tempo"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg")
def test_montagem_completa(tmp_path, monkeypatch):
    pytest.importorskip("playwright")
    import poker_montagem as PMo
    monkeypatch.setenv("POKER_DIR", str(tmp_path / "poker"))
    base = str(tmp_path)
    d = PD.novo(base, "teste", minutos=2)
    PD.salvar_blocos(base, d["id"], [
        {"tipo": "narracao", "texto": "Era uma vez. Um jogador.", "grafico": {"tipo": "titulo", "titulo": "Capítulo um", "numero": "1"}},
        {"tipo": "mao", "texto": "Ele vai all-in.", "mao": {"titulo": "A mão", "contexto_antes": "Final.", "contexto_depois": "Campeão.",
                                                           "estrategia": "Pressão.", "status": "ilustrativa", "fonte": "", "por_que": "",
                                                           "mao": BASE_AA_KK + "flop: 2s 7d 9c\nturn: 3h\nriver: 4s\n"}}])

    def tts(motor, texto, saida, **kw):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f=300:d={max(0.6, len(texto) * 0.05)}", "-ar", "48000", saida], check=True)
    mt = PMo.Montador(base, d["id"], {"formato": "1:1", "fps": 24, "velocidade": 3}, tts, {"motor": "t"}, kwargs_voz=lambda v: ("t", {}))
    r = mt.montar(str(tmp_path / "f.mp4"))
    assert r["pedacos"] == 4 and os.path.getsize(tmp_path / "f.mp4") > 20000
    srt = (tmp_path / "f.srt").read_text(encoding="utf-8")
    assert "Era uma vez." in srt and "Campeão." in srt and "-->" in srt
    total = PMo.duracao(str(tmp_path / "f.mp4"))
    assert abs(total - r["duracao"]) < 1.0
    # de novo: tudo do cache (rápido) e o mesmo resultado
    import time
    t0 = time.time()
    r2 = PMo.Montador(base, d["id"], {"formato": "1:1", "fps": 24, "velocidade": 3}, tts, {"motor": "t"}, kwargs_voz=lambda v: ("t", {})).montar(str(tmp_path / "g.mp4"))
    assert r2["pedacos"] == 4 and time.time() - t0 < 30


def test_rotas_montagem_e_pecas(cliente, tmp_path):
    c, R = cliente
    did = c.post("/poker/doc/novo", data={"tema": "x"}).headers["Location"].rsplit("/", 1)[-1]
    assert "gerador de voz" in c.post(f"/poker/doc/{did}/montar", json={}).get_json()["erro"]
    assert c.get("/poker/vozes").get_json()["ok"]
    p = c.post("/poker/grafico/previa", json={"grafico": {"tipo": "fato", "numero": "US$ 1 milhão", "texto": "o prêmio"}, "op": {}}).get_json()
    assert "window.render" in p["html"]
    c.post(f"/poker/doc/{did}/salvar", json={"blocos": [{"tipo": "narracao", "texto": "oi", "grafico": {"tipo": "titulo", "titulo": "T"}}]})
    bid = c.get(f"/poker/doc/{did}/estado").get_json()["doc"]["blocos"][0]["id"]
    from io import BytesIO
    from PIL import Image
    b = BytesIO()
    Image.new("RGB", (64, 64), "red").save(b, "PNG")
    b.seek(0)
    r = c.post(f"/poker/doc/{did}/bloco/{bid}/midia", data={"arquivo": (b, "f.png")}, content_type="multipart/form-data").get_json()
    assert r["ok"] and r["doc"]["blocos"][0]["grafico"]["arquivo"] == r["arquivo"]
    assert r["doc"]["blocos"][0]["grafico"]["tipo"] == "titulo"   # já tinha tipo: não troca
    assert c.get(f"/poker/doc/{did}/midia/{r['arquivo']}").status_code == 200


def test_tempo_minimo_das_pecas():
    import poker_graficos as PG
    tl = {"tipo": "linha_do_tempo", "itens": [{"ano": str(1980 + k), "texto": "x"} for k in range(5)]}
    assert PG.tempo_minimo(tl) >= 10 and PG.tempo_minimo(tl, "", "calmo") > PG.tempo_minimo(tl) > PG.tempo_minimo(tl, "", "rapido")
    assert PG.tempo_minimo({"tipo": "titulo", "titulo": "x"}) >= 4.5
    longa = {"tipo": "citacao", "texto": "x" * 140}
    assert PG.tempo_minimo(longa) >= 12   # dá tempo de ler a frase inteira


MAO_MORTO = '''mesa: jogo=draw blinds=1/2 unidade=$ titulo="A Mão do Homem Morto" estetica=noir
jogador: Wild Bill 50 As Ac 8s 8c ?? heroi pais=US
jogador: Carl Mann 50
jogador: Charles Rich 50
botao: Carl Mann
preflop: Charles Rich call; Wild Bill call; Carl Mann check
troca: Wild Bill 1
fim: "Um tiro pelas costas. A mão nunca terminou."
'''


def test_fim_e_carta_desconhecida(tmp_path):
    r = PM.simular(MAO_MORTO)
    tipos = [e["tipo"] for e in r["eventos"]]
    assert "fim" in tipos and "vencedor" not in tipos and tipos[-1] == "final"
    assert r["jogadores"][0]["cartas"][-1] == "??" and r["eventos"][-1]["depois"]["pot"] > 0
    assert next(e for e in r["eventos"] if e["tipo"] == "fim")["dados"]["texto"].startswith("Um tiro")
    # sem o fim, a mão com ?? não dá pra decidir no showdown
    with pytest.raises(PM.PokerErro, match="desconhecida"):
        PM.simular(MAO_MORTO.replace('fim: "Um tiro pelas costas. A mão nunca terminou."\n', "pos: Charles Rich check; Wild Bill check; Carl Mann check\n")
                   .replace("jogador: Carl Mann 50", "jogador: Carl Mann 50 2c 3c 4d 5h 9s").replace("jogador: Charles Rich 50", "jogador: Charles Rich 50 Kc Kd Qs Js 2d"))
    # duas ?? não contam como carta repetida; inline no meio das ações também vale
    r = PM.simular("jogador: A 10 ?? ??\njogador: B 10 ?? ??\nbotao: A\npreflop: A raise 3; [fim: \"acabou a luz\"]; B call\n")
    assert [e["tipo"] for e in r["eventos"]].count("acao") == 1
    import poker_3d as P3
    _js_ok(PR.pagina(PM.simular(MAO_MORTO), PR.normalizar({"formato": "9:16"}), "/f", lambda a: "", "previa"), tmp_path)
    _js_ok(P3.pagina(PM.simular(MAO_MORTO), PR.normalizar({"modo": "3d"}), "/f", lambda n: "", "previa"), tmp_path)


def test_estrutura_shorts_poker(tmp_path, monkeypatch):
    import poker_graficos as PG
    import poker_montagem as PMo
    monkeypatch.setenv("POKER_DIR", str(tmp_path / "poker"))
    base = str(tmp_path)
    d = PD.novo(base, "A mão do homem morto", tipo="shorts")
    assert d["op"]["formato"] == "9:16" and d["ritmo_pecas"] == "rapido" and d["minutos"] <= 1
    vistos = []

    def chamar(recurso, sistema, conteudo, **kw):
        vistos.append(conteudo)
        return json.loads(json.dumps(ROTEIRO))
    PD.escrever(base, d["id"], chamar=chamar)
    assert "GANCHO" in vistos[0] and "FINAL" in vistos[0] and "prioridade" in vistos[0]
    g = {"tipo": "gancho", "titulo": "QUE BURRO.", "subtitulo": "foi o que disseram", "autor": ""}
    assert PG.tempo_minimo(g) >= 3
    _js_ok(PG.pagina(g, PR.normalizar({"formato": "9:16"}), 4, "/f", "", "", "", "previa"), tmp_path)
    # foto do jogador citado (pelo sobrenome) entra quando o bloco não tem dados
    import poker_rotas as R
    pa = R.pastas(base)["avatares"]
    from PIL import Image
    Image.new("RGB", (64, 64), "gray").save(os.path.join(pa, "wild_bill.jpg"))
    PD.salvar_blocos(base, d["id"], [{"tipo": "narracao", "texto": "Wild Bill sentou de costas pra porta.", "grafico": {"tipo": ""}},
                                     {"tipo": "mao", "texto": "x", "mao": {"titulo": "m", "mao": MAO_MORTO, "status": "ilustrativa"}}])
    mt = PMo.Montador(base, d["id"], d["op"], lambda *a, **k: None, {"motor": "t"}, pasta_avatares=pa, kwargs_voz=lambda v: ("t", {}))
    assert mt.foto_citada("E então Wild Bill sentou") .endswith("wild_bill.jpg")
    assert mt.foto_citada("ninguém sabia") == ""
