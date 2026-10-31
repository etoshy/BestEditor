"""🎥 v84_292 — câmera virtual: segue o principal, larga ele pra seguir a bola em voo até a cesta, volta; começa aberta."""
import os
import subprocess

import pytest

import camera_virtual as CV


def _cena(cam):
    """1280x720: robô vermelho à esquerda, cesta azul à direita; a bola laranja sai da mão em 2 s e chega na cesta em 3 s."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x606060:s=1280x720:r=25:d=6",
                    "-f", "lavfi", "-i", "color=c=red:s=100x260:r=25:d=6", "-f", "lavfi", "-i", "color=c=orange:s=40x40:r=25:d=6",
                    "-f", "lavfi", "-i", "color=c=blue:s=120x80:r=25:d=6", "-f", "lavfi", "-i", "sine=f=300:d=6",
                    "-filter_complex", "[0:v][1:v]overlay=x=160:y=370[a];[a][3:v]overlay=x=1100:y=170[b];"
                    "[b][2:v]overlay=x='if(lt(t,2),265,if(lt(t,3),265+(1140-265)*(t-2),1140))':y='if(lt(t,2),400,if(lt(t,3),400-330*sin(PI*(t-2))+(190-400)*(t-2),190+200*min(1,t-3)))'[v]",
                    "-map", "[v]", "-map", "4:a", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", cam],
                   check=True)


def _caixa_cor(img, f):
    from PIL import Image
    im = Image.open(img).convert("RGB")
    w, h = im.size
    pts = [(x, y) for x in range(0, w, 4) for y in range(0, h, 4) if f(im.getpixel((x, y)))]
    if not pts:
        return []
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return [(min(xs) / w, min(ys) / h, max(xs) / w, max(ys) / h)]


class VisaoCores:
    erro = ""

    def achar(self, img, o):
        cor = {"robot": lambda p: p[0] > 200 and p[1] < 60 and p[2] < 60, "ball": lambda p: p[0] > 200 and 120 < p[1] < 200 and p[2] < 60,
               "hoop": lambda p: p[2] > 200 and p[0] < 60 and p[1] < 60}[o]
        return _caixa_cor(img, cor)


def _centro_x(img, f):
    from PIL import Image
    im = Image.open(img).convert("RGB")
    xs = [x for x in range(0, im.width, 6) for y in range(0, im.height, 12) if f(im.getpixel((x, y)))]
    return sum(xs) / len(xs) if xs else None


def test_camera_segue_a_bola_ate_a_cesta_e_volta(tmp_path):
    cena = str(tmp_path / "cena.mp4")
    _cena(cena)
    out = str(tmp_path / "v.mp4")
    r = CV.seguir(VisaoCores(), cena, cena, 0, 6, out, {"principal": "robot", "acao": ["ball"], "destino": ["hoop"]}, [])
    assert [e["tipo"] for e in r["eventos"]] == ["lancamento", "chegada"]
    assert 1.6 <= r["eventos"][0]["t"] <= 2.3 and 2.4 <= r["eventos"][1]["t"] <= 3.3
    assert r["foco"].get("ball + hoop", 0) > 0.3 and r["foco"]["principal"] > 2
    assert set(r["rastros"]) >= {"robot", "ball"}
    q = {}
    for t in (0.1, 1.6, 2.9, 5.6):
        f = str(tmp_path / f"q{t}.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", out, "-frames:v", "1", f], check=True)
        q[t] = f
    from PIL import Image
    vermelho = lambda p: p[0] > 200 and p[1] < 60 and p[2] < 60  # noqa: E731
    azul = lambda p: p[2] > 200 and p[0] < 60 and p[1] < 60  # noqa: E731
    # SEM BARRAS: o vertical sempre preenche a tela (o cinza do cenário chega até as bordas de cima e de baixo, nunca o fundo
    # desfocado/escurecido)
    for f in q.values():
        im = Image.open(f).convert("RGB")
        for y in (3, 960, 1916):
            assert abs(im.getpixel((540, y))[0] - 96) < 25 or im.getpixel((540, y))[0] > 180 or im.getpixel((540, y))[2] > 180, (f, y)
    assert 300 < _centro_x(q[1.6], vermelho) < 780          # depois entra no robô (no meio)
    assert _centro_x(q[2.9], azul) is not None               # a bola chegando: a cesta aparece
    assert _centro_x(q[5.6], vermelho) is not None and _centro_x(q[5.6], azul) is None  # voltou pro robô
    assert Image.open(q[1.6]).size == (1080, 1920)


def test_sem_acao_so_segue_o_principal_e_o_zoom_acompanha_o_tamanho():
    tracks = {"robot": [(t / 2, (0.1, 0.2, 0.2, 0.9)) for t in range(10)]}
    p = CV.planejar(tracks, {"principal": "robot", "acao": [], "destino": []}, 4.5, [], 1920, 1080, abrir_inicio=False)
    assert not p["eventos"] and all(n == "principal" for _, n in p["foco"])
    cx, cy, vw = p["alvos"][20][1:]
    assert cx == pytest.approx(0.15 * 1920, abs=2) and vw >= 1080 * 0.7 * 1.3 * 9 / 16 * 0.99
    grande = {"robot": [(t / 2, (0.05, 0.0, 0.95, 1.0)) for t in range(10)]}  # assunto enorme (close) → abre
    assert CV.planejar(grande, {"principal": "robot"}, 4.5, [], 1920, 1080, abrir_inicio=False)["alvos"][20][3] == 1080 * 1080 / 1920  # nunca abre além da altura


def test_destaque_usa_o_rastro_do_objeto_certo():
    import curtos_comentario as CC
    p = {"rastros": {"M1": {"red humanoid robot": [[0.5, 100, 500, 300, 900]], "basketball": [[1.0, 600, 700, 80, 80], [1.5, 700, 400, 80, 80]],
                            "basketball hoop": [[1.5, 650, 200, 200, 120]]}}}
    assert CC.objeto_rastreado(p, "M1", "the ball") == "basketball"
    assert CC.objeto_rastreado(p, "M1", "the hoop") == "basketball hoop"
    assert CC.objeto_rastreado(p, "M1", "robot's legs") == "red humanoid robot"
    assert CC.chaves_dos_rastros(p, "M1", 0.9, 2.0, "ball") == [{"t": 0.1, "caixa": [600, 700, 80, 80]}, {"t": 0.6, "caixa": [700, 400, 80, 80]}]
    assert CC.objeto_rastreado(p, "M2", "ball") is None


def test_som_do_evento_cai_no_segundo_certo_do_video(monkeypatch):
    import curtos as CT
    import dp_sons
    monkeypatch.setattr(CT, "escolher_som", lambda tipo, sem, ev=None, sons=None: f"som/{tipo}")
    monkeypatch.setattr(dp_sons, "evento", lambda som, t, vol: {"inicio": round(t - 0.1, 3), "volume": vol})
    p = {"id": "x", "eventos_som": [{"mid": "M1", "t": 4.2, "tipo": "whoosh", "o_que": "lancamento"},
                                    {"mid": "M1", "t": 9.0, "tipo": "impacto", "o_que": "chegada"}]}
    planos = [{"start": 0.0, "end": 3.0, "clipe": {"mid": "M1", "ini": 3.0, "fim": 6.0}},
              {"start": 3.0, "end": 5.0, "clipe": {"mid": "M2", "ini": 0.0, "fim": 2.0}}]
    out = CT.sons_dos_eventos(p, planos, 0.8, [])
    assert [(e["som"], e["start"], e["curto"]) for e in out] == [("som/whoosh", 1.1, "evento:lancamento")]  # 9.0 s não aparece no vídeo


def test_moondream_carrega_no_transformers_5(tmp_path):
    """'HfMoondream' object has no attribute 'all_tied_weights_keys': código remoto feito pro transformers 4 no transformers 5."""
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    from transformers import PreTrainedModel, PretrainedConfig
    if not hasattr(PreTrainedModel, "get_expanded_tied_weights_keys"):
        pytest.skip("transformers 4 — o problema não existe")
    import momentos_yt as M

    class Cfg(PretrainedConfig):
        model_type = "md_teste"

    class Velho(PreTrainedModel):
        config_class = Cfg
        _tied_weights_keys = []

        def __init__(self, config):
            super().__init__(config)
            self.lin = torch.nn.Linear(2, 2)  # sem post_init(), como o HfMoondream
    Velho(Cfg()).save_pretrained(str(tmp_path / "m"))
    M._compat_transformers()
    assert isinstance(Velho.from_pretrained(str(tmp_path / "m")), Velho)


def test_moondream_sai_da_memoria_e_cpu_usa_bfloat16(monkeypatch):
    import momentos_yt as M
    pedidos = []

    class Falso:
        pass

    import types
    torch = pytest.importorskip("torch")
    fake_tf = types.SimpleNamespace(AutoModelForCausalLM=types.SimpleNamespace(from_pretrained=lambda nome, **kw: pedidos.append(kw) or Falso()),
                                    PreTrainedModel=object)
    monkeypatch.setitem(__import__("sys").modules, "transformers", fake_tf)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    M._MD.clear()
    M._MD["modelo"] = None
    assert isinstance(M._moondream_hf({"revisao_hf": ""}), Falso)
    assert pedidos[0]["dtype"] == torch.bfloat16 and pedidos[0]["low_cpu_mem_usage"] is True
    assert M.Visao.__dict__["passo"].fget(type("V", (), {"vc": {"backend": "hf"}})()) == 1.0  # CPU: procura a cada 1 s
    M.liberar_moondream()
    assert M._MD["modelo"] is None


def test_reloader_ignora_a_pasta_dos_momentos():
    src = open(os.path.join(os.path.dirname(CV.__file__), "app.py"), encoding="utf-8").read()
    ini = src.index("def _padroes_excluidos_do_reloader")
    trecho = src[ini:src.index("return [os.path.join(p, \"*\")", ini)]
    assert '"momentos_yt"' in trecho


def test_rota_testar_moondream(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMENTOS_YT_DIR", str(tmp_path / "my"))
    import momentos_yt as M
    from flask import Flask
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(M.__file__), "templates"))
    M.registrar(app, str(tmp_path))
    cl = app.test_client()
    for volta in ({"ok": True, "msg": "✅ funcionando"}, {"ok": False, "msg": "❌ não respondeu"}):
        monkeypatch.setattr(M.Visao, "testar", lambda self, v=volta: v)
        j = cl.post("/momentos-yt/visao/testar").get_json()
        assert j == {"ok": True, "funcionou": volta["ok"], "msg": volta["msg"]}

    def explode(self):
        raise RuntimeError("sem memória")
    monkeypatch.setattr(M.Visao, "testar", explode)
    assert cl.post("/momentos-yt/visao/testar").get_json()["msg"] == "❌ sem memória"


# ---------------------------------------------------------------------------------------------------- 🎥 v84_296: o roteiro decide o foco
def _mapa_da_cena(cena):
    r = CV.analisar(VisaoCores(), cena, 6, {"principal": "robot", "acao": ["ball"], "destino": ["hoop"]}, [], passo=0.5)
    return r


def test_mapa_e_pedaco_focando_o_objeto_da_fala(tmp_path):
    cena = str(tmp_path / "cena.mp4")
    _cena(cena)
    mapa = _mapa_da_cena(cena)
    assert [e["tipo"] for e in mapa["eventos"]] == ["lancamento", "chegada"]
    assert mapa["visivel"]["robot"] == [[0.0, 5.5]] and mapa["visivel"]["hoop"]
    vermelho = lambda p: p[0] > 200 and p[1] < 60 and p[2] < 60  # noqa: E731
    azul = lambda p: p[2] > 200 and p[0] < 60 and p[1] < 60  # noqa: E731
    # a fala é sobre o robô → o vertical fica nele, mesmo com a bola voando
    a = str(tmp_path / "a.mp4")
    CV.enquadrar_pedaco(cena, 1.5, 4.0, a, mapa["tracks"], "", "robot", [])
    # a fala é sobre a cesta → o vertical vai pra cesta
    b = str(tmp_path / "b.mp4")
    r = CV.enquadrar_pedaco(cena, 1.5, 4.0, b, mapa["tracks"], "hoop", "robot", [])
    assert r["foco"] == "hoop" and "hoop" in r["rastros"]
    for arq, cor_sim, cor_nao in ((a, vermelho, azul), (b, azul, vermelho)):
        f = str(tmp_path / "q.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1.8", "-i", arq, "-frames:v", "1", f], check=True)
        assert _centro_x(f, cor_sim) is not None and _centro_x(f, cor_nao) is None, arq


def test_foco_que_nao_aparece_cai_no_principal_e_camera_nao_passeia(tmp_path):
    tracks = {"robot": [[t / 2, 0.1, 0.4, 0.2, 0.9] if t not in (4, 5, 6) else [t / 2, None] for t in range(12)]}
    pts = CV.tracks_do_mapa(tracks)["robot"]
    # o robô some de 2,0 a 3,0 s: a câmera fica parada onde estava, não volta pro meio
    p = CV.planejar({"robot": pts}, {"principal": "robot"}, 5.5, [], 1920, 1080, abrir_inicio=False)
    xs = [cx for t, cx, cy, vw in p["alvos"] if 2.1 <= t <= 2.9]
    assert xs and all(abs(x - 0.15 * 1920) < 5 for x in xs)
    salto = [(0.0, (0.1, 0.4, 0.2, 0.9)), (0.5, (0.8, 0.1, 0.9, 0.3)), (1.0, (0.1, 0.4, 0.2, 0.9))]
    assert CV.limpar_saltos(salto, [])[1] == (0.5, None)  # o detector confundiu por 1 quadro


def test_enquadrar_planos_usa_o_foco_do_roteiro(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "curtos"))
    import curtos as CT
    import curtos_comentario as CC
    import shutil
    cena = str(tmp_path / "cena.mp4")
    _cena(cena)
    base = str(tmp_path)
    p = CT.criar(base, "", "t", [], "", modelo="comentario")
    cp = str(tmp_path / "c.mp4")
    shutil.copy(cena, cp)
    with CT._TRAVA:
        q = CT.carregar(base, p["id"])
        CT.adicionar_midia(base, q, cp, "video", "clipe", "M")
        q["rastros_h"] = {"M1": dict(_mapa_da_cena(cena), principal="robot", cenas=[])}
        CT.salvar(base, q)
    planos = [{"start": 0, "end": 2, "bloco": "B1", "cena": 0, "parte": 0, "clipe": {"mid": "M1", "de": 1.5, "ate": 3.5, "foco": "the hoop"}},
              {"start": 2, "end": 4, "bloco": "B2", "cena": 0, "parte": 0, "clipe": {"mid": "M1", "de": 0.0, "ate": 2.0, "foco": ""}}]
    monkeypatch.setattr(CT, "planos_do_video", lambda *a, **k: [dict(x, clipe=dict(x["clipe"])) for x in planos])
    assert CC.enquadrar_planos(base, p["id"]) == 2
    q = CT.carregar(base, p["id"])
    enq = list(q["enquadrados"].values())
    assert [e["foco"] for e in enq] == ["hoop", "robot"] and [e["mid"] for e in enq] == ["V1", "V2"]
    assert CC.enquadrar_planos(base, p["id"]) == 0  # já feito: não refaz
    assert CC.objeto_no_mapa(q["rastros_h"]["M1"], "basket hoop") == "hoop"
