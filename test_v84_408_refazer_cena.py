"""v84_408: 🎬 refazer cena (só Flow) — planos, análise da IA, quem entra no lugar de cada pessoa, quadro novo + vídeo
(Veo) por plano e juntar."""
import io
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))
import refazer_cena as RC  # noqa: E402


def _video(caminho, cores=(("red", 2), ("blue", 3), ("green", 10)), tam="320x180"):
    ins, f = [], []
    for k, (c, d) in enumerate(cores):
        ins += ["-f", "lavfi", "-i", f"color=c={c}:s={tam}:r=25:d={d}"]
        f.append(f"[{k}:v]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", "".join(f) + f"concat=n={len(cores)}:v=1:a=0",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(caminho)], check=True, capture_output=True)
    return str(caminho)


def test_planos_de():
    assert RC.planos_de([], 5) == [{"ini": 0.0, "fim": 5.0}]
    p = RC.planos_de([2.0, 2.4, 5.0], 15.0)  # 2.0–2.4 é curto: gruda no anterior; 5–15 (10 s) vira 2 de 5 s
    assert p == [{"ini": 0.0, "fim": 2.4}, {"ini": 2.4, "fim": 5.0}, {"ini": 5.0, "fim": 10.0}, {"ini": 10.0, "fim": 15.0}]
    assert RC.planos_de([0.5], 4.0) == [{"ini": 0.0, "fim": 4.0}]  # o primeiro curto gruda no próximo
    assert RC.proporcao_de(1080, 1920) == "9:16" and RC.proporcao_de(1920, 1080) == "16:9"


def _criado(tmp_path):
    base = str(tmp_path / "b")
    p = RC.criar(base, _video(tmp_path / "v.mp4"), "minha cena")
    assert [(round(x["ini"]), round(x["fim"])) for x in p["planos"]] == [(0, 2), (2, 5), (5, 10), (10, 15)]
    d = RC.pasta(base, p["id"])
    assert all(os.path.isfile(os.path.join(d, x["quadro"])) for x in p["planos"])
    assert p["proporcao"] == "16:9" and RC.listar(base)[0]["nome"] == "minha cena"
    with pytest.raises(RC.RefazerErro):
        RC.criar(base, str(tmp_path / "nada.txt"))
    return base, p


def _resp():
    return {"personagens": [{"id": "A", "descricao": "homem de terno"}, {"id": "b", "descricao": "mulher de vermelho"}],
            "cenario": "bar à noite",
            "planos": [{"n": 1, "pessoas": [{"id": "A", "x": 0.3, "y": 0.2, "emocao_en": "smug half-smile"}, {"id": "B", "x": 0.7, "y": 0.25, "emocao_en": ""}],
                        "acao_en": "The man raises his glass.", "camera_en": "static", "fala": [{"id": "A", "texto": "Saúde!"}]},
                       {"n": 2, "pessoas": [{"id": "B", "x": 0.5, "y": 0.3, "emocao_en": "laughing"}, {"id": "Z", "x": 0.1, "y": 0.1, "emocao_en": ""}],
                        "acao_en": "She laughs.", "camera_en": "slow push-in", "fala": []}]}


def _analisado(tmp_path):
    base, p = _criado(tmp_path)
    vistos = {}

    def chamar(recurso, sis, cont, **k):
        vistos["recurso"], vistos["n_img"] = recurso, sum(1 for c in cont if c.get("type") == "image")
        vistos["txt"] = [c["text"] for c in cont if c.get("type") == "text"]
        return _resp()
    q = RC.analisar(base, p["id"], chamar, lambda f: {"type": "image"},
                    lambda v: [{"start": 0.2, "end": 1.5, "text": "Saúde!"}])
    assert vistos["recurso"] == "refazer_cena" and vistos["n_img"] == 3 * len(p["planos"])
    assert "speech: Saúde!" in vistos["txt"][0] and "no speech" in vistos["txt"][2]
    assert [x["id"] for x in q["personagens"]] == ["A", "B"] and q["cenario"]["descricao"] == "bar à noite"
    assert q["planos"][1]["pessoas"] == [{"id": "B", "x": 0.5, "y": 0.3, "emocao_en": "laughing"}]  # o "Z" (que não existe) sai
    assert q["planos"][0]["fala_original"] == [{"id": "A", "texto": "Saúde!"}] and q["analisado"]
    # reanalisar não perde o que você escolheu
    RC._mudar(base, p["id"], lambda x: x["personagens"][0].update(nome="Ana", foto="fotos/a.png"))
    q2 = RC.analisar(base, p["id"], lambda *a, **k: _resp(), lambda f: None)
    assert q2["personagens"][0]["nome"] == "Ana" and q2["personagens"][0]["foto"] == "fotos/a.png"
    return base, q2


def _foto(c, cor="blue"):
    from PIL import Image
    Image.new("RGB", (64, 64), cor).save(c)
    return str(c)


def test_pacote_prompt_e_gerar(tmp_path):
    base, p = _analisado(tmp_path)
    d = RC.pasta(base, p["id"])
    os.makedirs(os.path.join(d, "fotos"), exist_ok=True)
    _foto(os.path.join(d, "fotos", "a.png"))
    p = RC._mudar(base, p["id"], lambda x: (x["cenario"].update(novo="praia"), x.update(estilo="anime", falas_modo="novas")))
    gal = str(tmp_path / "gal")
    pac = RC.pacote_do_plano(base, p, p["planos"][0], gal)
    assert [r["papel"] for r in pac["refs"]] == ["base", "personagem"]  # B sem nome/foto: fica como está (sem foto extra)
    assert "figura 1 (pessoa" in pac["refs"][0]["obs"] and "= Ana" in pac["refs"][0]["obs"] and "trocar por: praia" in pac["refs"][0]["obs"]
    assert "MESMA expressão/emoção do original: smug half-smile" in pac["refs"][0]["obs"]
    pv = RC.prompt_video(p, p["planos"][0])
    assert "Facial expressions exactly as in the original scene — Ana: smug half-smile" in pv
    assert 'Ana says: "Saúde!"' in pv and "The man raises his glass." in pv and "Setting: praia." in pv and "anime" in pv
    p["estilo"] = ""
    assert "Keep exactly the art style of the first frame." in RC.prompt_video(p, p["planos"][0])
    p["falas_modo"] = "sem"
    assert "No dialogue." in RC.prompt_video(p, p["planos"][0]) and "says" not in RC.prompt_video(p, p["planos"][0])
    # gerar com o Flow falso: quadro (imagem com as referências) e depois o vídeo começando nele
    pedidos = []

    def rodar(ped):
        pedidos.append(ped)
        if ped["tipo"] == "imagem":
            return [{"tipo": "imagem", "caminho": _foto(tmp_path / f"q{len(pedidos)}.png", "red")}]
        return [{"tipo": "video", "caminho": _video(tmp_path / f"v{len(pedidos)}.mp4", (("yellow", 8),))}]
    q = RC.gerar(base, gal, p["id"], [1], "tudo", rodar, montar=lambda pac: {"prompt": "P"})
    assert [x["tipo"] for x in pedidos] == ["imagem", "video"]
    assert len(pedidos[0]["referencias"]) == 2 and pedidos[1]["inicio"]["arquivo"].endswith(q["planos"][0]["quadro_novo"].split("/")[-1])
    assert q["planos"][0]["quadro_novo"] and q["planos"][0]["video_novo"] and not q["planos"][1]["quadro_novo"]
    # um plano com erro não para os outros
    q = RC.gerar(base, gal, p["id"], [2, 3], "quadro", lambda ped: (_ for _ in ()).throw(RuntimeError("Flow caiu")),
                 montar=lambda pac: {"prompt": "P"})
    assert q["planos"][1]["erro"] == "Flow caiu" and q["planos"][2]["erro"] == "Flow caiu"
    # juntar: o plano 1 vem do vídeo novo (cortado em 2 s), os outros do original
    final = RC.juntar(base, p["id"])
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                os.path.join(d, final)], capture_output=True, text=True).stdout)
    assert abs(dur - 15.0) < 0.5


@pytest.fixture
def ctx(monkeypatch, tmp_path):
    import app as A
    import flow_estudio as FE
    from googleflow import googleflow_client as gf
    A.app.config["TESTING"] = True
    monkeypatch.setitem(FE._BASE, "dir", str(tmp_path))
    monkeypatch.setattr(gf, "pasta_dados", lambda: tmp_path / "flow_dados")
    return A.app.test_client(), FE


def test_rotas(ctx, monkeypatch, tmp_path):
    c, FE = ctx
    monkeypatch.setattr(RC, "analisar", lambda base, pid, **k: RC._mudar(base, pid, lambda q: RC.ler_analise(q, _resp())))
    v = open(_video(tmp_path / "v.mp4"), "rb").read()
    j = c.post("/flow/refazer/novo", data={"video": (io.BytesIO(v), "cena.mp4"), "nome": "Bar"}, content_type="multipart/form-data").get_json()
    pid = j["projeto"]["id"]
    import time
    for _ in range(50):
        pj = c.get(f"/flow/refazer/{pid}").get_json()["projeto"]
        if pj["analisado"] and not pj["estado"]["rodando"]:
            break
        time.sleep(0.1)
    assert pj["analisado"] and pj["planos"][0]["quadro_url"].startswith(f"/flow/refazer/{pid}/arq/")
    assert c.get(pj["planos"][0]["quadro_url"]).status_code == 200
    assert c.get(f"/flow/refazer/{pid}/arq/projeto.json").status_code == 400
    r = c.post(f"/flow/refazer/{pid}/foto", data={"alvo": "personagem:A", "foto": (io.BytesIO(open(_foto(tmp_path / "a.png"), "rb").read()), "a.png")},
               content_type="multipart/form-data").get_json()
    assert r["projeto"]["personagens"][0]["foto_url"]
    r = c.post(f"/flow/refazer/{pid}/salvar", json={"personagens": [{"id": "A", "nome": "Ana"}], "cenario": {"novo": "praia"},
                                                   "estilo": "manga", "falas_modo": "novas", "planos": [{"n": 1, "fala": [{"id": "A", "texto": "Oi!"}], "emocoes": {"A": "furious"}}]}).get_json()
    pj = r["projeto"]
    assert pj["personagens"][0]["nome"] == "Ana" and pj["estilo"] == "manga" and pj["planos"][0]["fala"] == [{"id": "A", "texto": "Oi!"}]
    assert pj["planos"][0]["pessoas"][0]["emocao_en"] == "furious"
    # gerar: usa o rodar_e_esperar do Flow (falso aqui)
    pedidos = []
    monkeypatch.setattr(FE, "rodar_e_esperar", lambda ped, **k: pedidos.append(ped) or (
        [{"tipo": "imagem", "caminho": _foto(tmp_path / "n.png", "red")}] if ped["tipo"] == "imagem" else
        [{"tipo": "video", "caminho": _video(tmp_path / f"n{len(pedidos)}.mp4", (("yellow", 3),))}]))
    import flow_montar as FM
    monkeypatch.setattr(FM, "montar_prompt", lambda pac: {"prompt": "P"})
    assert c.post(f"/flow/refazer/{pid}/gerar", json={"etapa": "quadro", "planos": [1]}).status_code == 200
    for _ in range(100):
        pj = c.get(f"/flow/refazer/{pid}").get_json()["projeto"]
        if not pj["estado"]["rodando"]:
            break
        time.sleep(0.1)
    assert pj["planos"][0]["quadro_novo_url"] and pedidos[0]["tipo"] == "imagem" and not pj["estado"]["erro"]
    h = c.get("/flow/refazer").get_data(as_text=True)
    assert 'id="rfPessoas"' in h and "o mesmo dos personagens novos" in h
    assert c.post(f"/flow/refazer/{pid}/apagar").get_json()["ok"] and not c.get("/flow/refazer/lista").get_json()["projetos"]


def test_criar_acha_os_cortes(tmp_path):
    _criado(tmp_path)


def test_analisar_quem_e_quem(tmp_path):
    _analisado(tmp_path)
