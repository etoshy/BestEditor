"""v84_183: 🧍 Personagens no pod — JSON de poses + referências → mestre → resto com a mestre → aprovar/refazer →
zip das aprovadas. O teste de ponta a ponta sobe o pod de verdade (personagens-pod, MOCK=1) se o código dele estiver
por perto (PERSONAGENS_POD_CODIGO ou ../personagens-pod)."""
import io
import json
import os
import socket
import subprocess
import sys
import time
import zipfile

import pytest
from PIL import Image

import personagens_pod as pp

AQUI = os.path.dirname(os.path.abspath(__file__))

JSON_POSES = {
    "formato": "personagens_pod_v1", "personagem": "vanta", "nome": "Vanta",
    "descricoes_referencias": {"ficha.png": "the official character reference sheet of Vanta"},
    "texto_fixo": {"trava": "VANTA LOCK", "estilo": "ART STYLE", "regras": "flat chroma-key GREEN background"},
    "fundo": "verde",
    "geracao": {"largura": 512, "altura": 768, "passos": 4, "cfg": 4.0}, "canvas": [600, 900],
    "poses": [
        {"arquivo": "vanta_neutra_esq.png", "tipo": "pose", "prioridade": 1, "mestre": True, "grupo": "reacao", "prompt": "neutral"},
        {"arquivo": "vanta_neutra_esq_boca.png", "tipo": "boca", "base": "vanta_neutra_esq.png", "prioridade": 1, "grupo": "boca", "prompt": "mouth open"},
        {"arquivo": "vanta_cetica_esq.png", "tipo": "pose", "prioridade": 1, "grupo": "reacao", "prompt": "arms crossed"},
        {"arquivo": "vanta_cetica_esq_boca.png", "tipo": "boca", "base": "vanta_cetica_esq.png", "prioridade": 1, "grupo": "boca", "prompt": "mouth open"},
        {"arquivo": "vanta_relogio_esq.png", "tipo": "pose", "prioridade": 2, "grupo": "objeto", "prompt": "holding a pocket watch"},
    ],
}


def _png() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (300, 400), (30, 30, 60)).save(b, "PNG")
    return b.getvalue()


def test_json_validado():
    with pytest.raises(pp.PersErro):
        pp.ler_json("{}")
    with pytest.raises(pp.PersErro):
        pp.ler_json(json.dumps({"poses": [{"arquivo": "a", "prompt": "x"}, {"arquivo": "a.png", "prompt": "y"}]}))
    with pytest.raises(pp.PersErro):
        pp.ler_json(json.dumps({"poses": [{"arquivo": "b", "tipo": "boca", "prompt": "x"}]}))
    assert pp.ler_json(json.dumps({"poses": [{"arquivo": "../fora", "prompt": "x"}]}))["poses"][0]["arquivo"] == "fora.png"
    d = pp.ler_json(json.dumps({"poses": [{"arquivo": "a", "prompt": "x"}]}))
    assert d["poses"][0]["arquivo"] == "a.png" and d["poses"][0]["tipo"] == "pose"


def _codigo_do_pod():
    for c in (os.environ.get("PERSONAGENS_POD_CODIGO"), os.path.join(AQUI, "..", "personagens-pod"),
              os.path.join(AQUI, "..", "..", "personagens-pod"), os.path.join(AQUI, "..", "..", "..", "personagens-pod")):
        if c and os.path.isfile(os.path.join(c, "app", "main.py")):
            return os.path.abspath(c)
    return None


@pytest.fixture()
def pod(tmp_path):
    cod = _codigo_do_pod()
    if not cod:
        pytest.skip("código do personagens-pod não está aqui (PERSONAGENS_POD_CODIGO)")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta = s.getsockname()[1]
    s.close()
    env = dict(os.environ, MOCK="1", DATA_DIR=str(tmp_path / "pod"), PORT=str(porta), PYTHONPATH=cod)
    proc = subprocess.Popen([sys.executable, "-m", "app.main"], cwd=cod, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{porta}"
    import requests
    for _ in range(100):
        try:
            requests.get(url + "/status", timeout=1)
            break
        except requests.RequestException:
            time.sleep(0.1)
    yield url
    proc.terminate()
    proc.wait(10)


def _esperar(c, pid, segundos=20):
    fim = time.time() + segundos
    while time.time() < fim:
        d = c.get(f"/personagens-pod/{pid}/estado").get_json()
        if not d["esperando"]:
            return d
        time.sleep(0.2)
    raise AssertionError("o pod não terminou")


def test_ponta_a_ponta(pod, tmp_path, monkeypatch):
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(tmp_path / "pp"))
    import app as A
    c = A.app.test_client()
    r = c.post("/personagens-pod/criar", data={"nome": "Vanta", "pod_url": pod, "motor": "pod", "json": json.dumps(JSON_POSES),
                                                "refs": [(io.BytesIO(_png()), "ficha.png")]}, content_type="multipart/form-data")
    assert r.status_code == 302
    pid = r.headers["Location"].rstrip("/").split("/")[-1]
    assert c.get(f"/personagens-pod/{pid}").status_code == 200
    st = c.get(f"/personagens-pod/{pid}/pod-status").get_json()
    assert st["mock"] is True
    # ⭐ mestre
    assert c.post(f"/personagens-pod/{pid}/gerar", json={"arquivos": ["vanta_neutra_esq.png"]}).get_json()["com_mestre"] is False
    d = _esperar(c, pid)
    it = next(x for x in d["itens"] if x["arquivo"] == "vanta_neutra_esq.png")
    assert it["estado"] == "pronta" and it["versoes"] == 1
    img = Image.open(io.BytesIO(c.get(f"/personagens-pod/{pid}/img/{it['img']}").data))
    assert img.size == (600, 900) and img.mode == "RGBA"
    import numpy as np
    px = np.asarray(img).astype(int)
    visivel = px[..., 3] > 128
    assert visivel.any() and not (visivel & (px[..., 1] > np.maximum(px[..., 0], px[..., 2]) + 25)).any()  # 🟩 nada de verde
    assert not visivel[:5].any()  # o fundo verde virou transparente
    stj0 = json.loads(sorted((tmp_path / "pod" / "jobs").iterdir())[-1].joinpath("status.json").read_text(encoding="utf-8"))
    assert stj0["itens"]["vanta_neutra_esq.png"]["limpeza"]["verde_px"] > 0
    assert c.post(f"/personagens-pod/{pid}/mestre", json={"arquivo": "vanta_neutra_esq.png"}).get_json()["ok"]
    # ▶ o resto: a boca da mestre (base fora do lote: sobe a imagem) e a cética + a boca dela (base no lote)
    r = c.post(f"/personagens-pod/{pid}/gerar", json={"arquivos": ["vanta_neutra_esq_boca.png", "vanta_cetica_esq.png",
                                                                   "vanta_cetica_esq_boca.png"]}).get_json()
    assert r["com_mestre"] and r["enviadas"] == 3
    d = _esperar(c, pid)
    por = {x["arquivo"]: x for x in d["itens"]}
    assert all(por[a]["estado"] == "pronta" for a in ("vanta_neutra_esq_boca.png", "vanta_cetica_esq.png", "vanta_cetica_esq_boca.png"))
    assert d["mestre"]["arquivo"] == "vanta_neutra_esq.png" and por["vanta_neutra_esq.png"]["estado"] == "aprovada"
    # o pedido que o pod recebeu: a mestre foi de referência, com a trava e a correção
    pedidos = sorted((tmp_path / "pod" / "jobs").iterdir())
    ped = json.loads((pedidos[-1] / "pedido.json").read_text(encoding="utf-8"))
    assert ped["mestre"].startswith("MESTRE_") and ped["referencias"] == ["ficha.png"] and ped["fundo"] == "verde"
    assert (pedidos[-1] / "refs" / "vanta_neutra_esq.png").exists()  # a base da _boca subiu
    stj = json.loads((pedidos[-1] / "status.json").read_text(encoding="utf-8"))
    assert "APPROVED MASTER" in stj["itens"]["vanta_cetica_esq.png"]["prompt"] and "VANTA LOCK" in stj["itens"]["vanta_cetica_esq.png"]["prompt"]
    # 🔁 refazer com correção → versão 2; ◀ voltar pra 1
    c.post(f"/personagens-pod/{pid}/gerar", json={"arquivos": ["vanta_cetica_esq.png"], "extra": "no cigarette"})
    d = _esperar(c, pid)
    cet = next(x for x in d["itens"] if x["arquivo"] == "vanta_cetica_esq.png")
    assert cet["versoes"] == 2 and cet["atual"] == 1
    pedidos = sorted((tmp_path / "pod" / "jobs").iterdir())
    stj = json.loads((pedidos[-1] / "status.json").read_text(encoding="utf-8"))
    assert "CORRECTION FOR THIS ATTEMPT: no cigarette" in stj["itens"]["vanta_cetica_esq.png"]["prompt"]
    c.post(f"/personagens-pod/{pid}/versao", json={"arquivo": "vanta_cetica_esq.png", "idx": 0})
    c.post(f"/personagens-pod/{pid}/aprovar", json={"arquivo": "vanta_cetica_esq.png"})
    c.post(f"/personagens-pod/{pid}/descartar", json={"arquivo": "vanta_cetica_esq_boca.png"})
    # ⬇ zip das aprovadas (a mestre + a cética, v1)
    r = c.get(f"/personagens-pod/{pid}/aprovadas.zip")
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert sorted(z.namelist()) == ["poses.json", "vanta_cetica_esq.png", "vanta_neutra_esq.png"]
    p = pp.carregar(pid)
    v1 = os.path.join(pp._pasta(pid), "imagens", p["imagens"]["vanta_cetica_esq.png"]["versoes"][0]["local"])
    assert z.read("vanta_cetica_esq.png") == open(v1, "rb").read()
    # pod trocado: o job antigo some → erro claro
    c.post(f"/personagens-pod/{pid}/gerar", json={"arquivos": ["vanta_relogio_esq.png"]})
    c.post(f"/personagens-pod/{pid}/pod-url", json={"pod_url": pod})
    assert c.get("/personagens-pod").status_code == 200


def test_boca_sem_base_pronta_avisa(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(tmp_path / "pp"))
    p = pp.criar("V", json.dumps(JSON_POSES), [("ficha.png", _png())], "http://127.0.0.1:9", motor="pod")
    with pytest.raises(pp.PersErro, match="gere \\(ou aprove\\) primeiro"):
        pp.enviar(p["id"], ["vanta_neutra_esq_boca.png"])
    with pytest.raises(pp.PersErro, match="não respondeu"):
        pp.enviar(p["id"], ["vanta_neutra_esq.png"])


def test_trocar_json_mantem_imagens(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(tmp_path / "pp"))
    p = pp.criar("V", json.dumps(JSON_POSES), [("ficha.png", _png())], "http://127.0.0.1:9")
    p = pp.carregar(p["id"])
    p["imagens"]["vanta_neutra_esq.png"].update(estado="aprovada", versoes=[{"local": "x.png"}], atual=0)
    pp.salvar(p)
    novo = json.loads(json.dumps(JSON_POSES))
    novo["poses"] = [dict(novo["poses"][0], prompt="NEW PROMPT"), {"arquivo": "vanta_feliz_esq", "prompt": "happy"}]
    r = pp.trocar_json(p["id"], json.dumps(novo))
    assert r == {"ok": True, "poses": 2, "novas": 1, "sairam": 4}
    q = pp.carregar(p["id"])
    assert q["imagens"]["vanta_neutra_esq.png"]["estado"] == "aprovada"
    assert q["imagens"]["vanta_feliz_esq.png"]["estado"] == "nova"
    assert "vanta_cetica_esq.png" not in q["imagens"]
    assert pp.pose(q, "vanta_neutra_esq.png")["prompt"] == "NEW PROMPT"
    with pytest.raises(pp.PersErro):
        pp.trocar_json(p["id"], "{}")
    q["imagens"]["vanta_feliz_esq.png"]["estado"] = "fila"
    pp.salvar(q)
    with pytest.raises(pp.PersErro, match="ainda estão no pod"):
        pp.trocar_json(p["id"], json.dumps(JSON_POSES))


def test_qualidade_vai_no_pedido(pod, tmp_path, monkeypatch):
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(tmp_path / "pp"))
    import app as A
    c = A.app.test_client()
    p = pp.criar("V", json.dumps(JSON_POSES), [("ficha.png", _png())], pod, motor="pod")
    assert c.get(f"/personagens-pod/{p['id']}/json").get_json()["json"].startswith("{")
    r = c.post(f"/personagens-pod/{p['id']}/gerar", json={"arquivos": ["vanta_neutra_esq.png"], "qualidade": "alta", "passos": 35}).get_json()
    assert r["ok"]
    _esperar(c, p["id"])
    ped = json.loads(sorted((tmp_path / "pod" / "jobs").iterdir())[-1].joinpath("pedido.json").read_text(encoding="utf-8"))
    assert ped["geracao"]["qualidade"] == "alta" and ped["geracao"]["passos"] == 35
    stj = json.loads(sorted((tmp_path / "pod" / "jobs").iterdir())[-1].joinpath("status.json").read_text(encoding="utf-8"))
    assert stj["itens"]["vanta_neutra_esq.png"]["passos"] == 35


def test_animar_todas_cria_a_boca_de_cada_pose(tmp_path, monkeypatch):
    """v84_209: 👄 Animar todas = a _boca de toda pose entra no JSON (a animação de fala) e vai pra geração."""
    import json
    import personagens_pod as pp
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(tmp_path / "pp"))
    dados = {"formato": "personagens_pod_v1", "nome": "M", "poses": [
        {"arquivo": "m_a.png", "prompt": "a"}, {"arquivo": "m_b.png", "prompt": "b"},
        {"arquivo": "m_a_boca.png", "tipo": "boca", "base": "m_a.png", "prompt": "x"}]}
    p = pp.criar("M", json.dumps(dados), [], "", str(tmp_path))
    novas = pp.criar_bocas(p["id"], str(tmp_path))
    assert novas == ["m_b_boca.png"]
    assert pp.criar_bocas(p["id"], str(tmp_path)) == []  # não duplica
    enviados = []
    monkeypatch.setattr(pp, "enviar", lambda pid, arqs, *a, **k: enviados.append(arqs) or {"ok": True})
    monkeypatch.setattr(pp, "arquivo_atual", lambda p_, a, b=None: "/x.png" if a == "m_b.png" else None)
    r = pp.animar_todas(p["id"], str(tmp_path))
    assert r["enviadas"] == 1 and enviados == [["m_b_boca.png"]]
