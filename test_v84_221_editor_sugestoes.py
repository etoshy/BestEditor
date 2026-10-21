"""v84_221: a IA do editor pede pose nova / o visual do vídeo; o botão gera; a aparição troca quando fica pronta."""
import io
import json
import os

from PIL import Image

import personagens_editor as PE
import personagens_pod as pp
import personagens_sugestoes as PS
from test_v84_183_personagens_pod import JSON_POSES, _png
from test_v84_184_personagens_flow import LoteFalso, _ok, flow  # noqa: F401


def _png_em(cam, cor=(200, 50, 50)):
    Image.new("RGBA", (60, 90), cor + (255,)).save(cam)
    return cam


def _pers(tmp_path):
    poses = []
    for a, vis, pb in (("vanta_neutra_esq.png", "", ""), ("vanta_cetica_esq.png", "", ""),
                       ("vanta_cetica_esq__praia.png", "praia", "vanta_cetica_esq.png")):
        poses.append({"arquivo": a, "caminho": _png_em(str(tmp_path / a)), "aprovada": True, "lado": "esq", "descricao": a,
                      "grupo": "reacao", "texto": a, "mestre": False, "boca": None, "visual": vis, "pose_base": pb})
    return [{"slug": "vanta", "nome": "Vanta", "poses": poses, "projeto": {"id": "pid1", "nome": "Vanta"},
             "visuais": [{"slug": "praia", "nome": "Praia", "descricao_en": "beach"}]}]


def _momento(i, t):
    return {"id": i, "slug": "vanta", "start": t, "end": t + 2, "texto": "Ja.", "palavras": [[t, t + 1]], "emocao": "", "tipo": "fala"}


def test_ler_visuais():
    ps = [{"slug": "vanta", "nome": "Vanta", "visuais": [{"slug": "praia", "nome": "Praia"}]}]
    assert PE.ler_visuais([{"personagem": "Vanta", "visual": "praia"}], ps) == {"vanta": {"slug": "praia", "nome": "Praia"}}
    r = PE.ler_visuais([{"personagem": "vanta", "novo_nome": "Frio", "novo_descricao_en": "long wool coat, scarf"}], ps)
    assert r["vanta"]["novo"]["nome"] == "Frio"
    assert PE.ler_visuais([{"personagem": "vanta", "visual": "", "novo_nome": ""}], ps) == {}


def test_montar_usa_o_visual_e_sugere(tmp_path):
    pers = _pers(tmp_path)
    cfg = dict(PE.PADRAO, margem=2, antes=0.2, depois=0.3, boca=True, _visuais={"vanta": {"slug": "praia", "nome": "Praia"}})
    ia = {1: {"id": 1, "pose": "vanta_cetica_esq.png", "lado": "direita"},
          2: {"id": 2, "pose": "vanta_neutra_esq.png", "lado": "direita"},
          3: {"id": 3, "pose": "vanta_neutra_esq.png", "lado": "direita", "pose_nova": "pointing at a thermometer",
              "pose_nova_pt": "apontando o termômetro"}}
    out, _ = PE.montar([_momento(1, 1), _momento(2, 10), _momento(3, 20)], pers, cfg, 40, False, ia)
    assert out[0]["pose"] == "vanta_cetica_esq__praia.png" and not out[0]["sugestao"]  # a versão no visual já existe
    assert out[1]["sugestao"] == {"tipo": "visual", "pose_base": "vanta_neutra_esq.png", "visual": "praia"}
    assert out[2]["sugestao"]["tipo"] == "nova" and out[2]["sugestao"]["visual"] == "praia"
    # sem visual no vídeo: nunca usa pose de outro visual
    cfg["_visuais"] = {}
    out, _ = PE.montar([_momento(1, 1)], pers, cfg, 40, False, {1: {"id": 1, "pose": "vanta_cetica_esq__praia.png"}})
    assert out[0]["pose"] == "vanta_cetica_esq.png" and not out[0]["sugestao"]
    ov = PE.overlay_de(dict(out[0], sugestao={"tipo": "nova", "descricao_en": "x"}), str(tmp_path), PE.PADRAO | {"duracao_anim": 0.3}, "o1")
    assert ov["sugestao"]["tipo"] == "nova"


def test_gerar_e_trocar_quando_fica_pronta(flow, tmp_path):
    c, falso, gal = flow
    r = c.post("/personagens-pod/criar", data={"nome": "Vanta", "motor": "flow", "json": json.dumps(JSON_POSES),
                                                "refs": [(io.BytesIO(_png()), "ficha.png")]}, content_type="multipart/form-data")
    pid = r.headers["Location"].rstrip("/").split("/")[-1]
    c.post(f"/personagens-pod/{pid}/gerar", json={"arquivos": ["vanta_neutra_esq.png"]})
    _ok(falso, gal, falso.fila[-1]["id"])
    c.get(f"/personagens-pod/{pid}/estado")
    jd = tmp_path / "job"
    jd.mkdir()
    job = {"overlays": [
        {"id": "a1", "origem": "personagem", "personagem": "vanta", "nome_personagem": "Vanta", "lado": "direita", "start": 1,
         "end": 3, "pose": "vanta_neutra_esq.png", "projeto_id": pid,
         "sugestao": {"tipo": "nova", "descricao_en": "pointing at a thermometer, sweating", "descricao_pt": "termômetro",
                      "visual": "", "visual_novo": {"nome": "Praia", "descricao_en": "light summer dress, straw hat"}}},
        {"id": "a2", "origem": "personagem", "personagem": "vanta", "nome_personagem": "Vanta", "lado": "direita", "start": 9,
         "end": 11, "pose": "vanta_neutra_esq.png", "projeto_id": pid,
         "sugestao": {"tipo": "visual", "pose_base": "vanta_neutra_esq.png", "visual": "",
                      "visual_novo": {"nome": "Praia", "descricao_en": "light summer dress, straw hat"}}}]}
    assert PS.resumo(job)["n_sugeridas"] == 2
    g = PS.gerar(job, pp._BASE)
    assert g["poses"] == 2 and g["enviadas"] == 1 and "esperando" in " ".join(g["avisos"]), g
    p = pp.carregar(pid)
    assert pp.visual(p, "praia") and job["overlays"][0]["pendente"]["arquivo"].endswith("__praia.png")
    assert job["overlays"][1]["pendente"]["arquivo"] == "vanta_neutra_esq__praia.png"  # a mestra do visual
    assert not job["overlays"][0].get("sugestao")
    # a mestra do visual vai primeiro; a pose nova do visual ⏳ espera a mestra
    jm = falso.fila[-1]
    assert "Change ONLY the outfit" in jm["prompt"]
    assert PS.atualizar_pendentes(job, pp._BASE, str(jd)) == 0
    _ok(falso, gal, jm["id"])
    n = PS.atualizar_pendentes(job, pp._BASE, str(jd))  # sincroniza: a mestra ficou pronta → a aparição 2 troca
    assert n >= 1 and job["overlays"][1]["pose"] == "vanta_neutra_esq__praia.png"
    assert os.path.isfile(job["overlays"][1]["source"]["value"])
    jn = falso.fila[-1]  # a pose nova seguiu sozinha depois da mestra
    assert "pointing at a thermometer" in jn["prompt"]
    _ok(falso, gal, jn["id"])
    PS.atualizar_pendentes(job, pp._BASE, str(jd))
    assert job["overlays"][0]["pose"].startswith("ia_") and "pendente" not in job["overlays"][0] or \
        job["overlays"][0]["pendente"].get("so_boca")


def test_fantasia_de_piada(tmp_path):
    """🎭 v84_222: a fantasia vale só na aparição da piada; máx. 2 por vídeo; a que já existe é reusada."""
    pers = _pers(tmp_path)
    cfg = dict(PE.PADRAO, margem=2, antes=0.2, depois=0.3, boca=True, _visuais={})
    fan = {"fantasia_nome": "Esfinge", "fantasia_descricao_en": "a cute sphinx with her face", "fantasia_descricao_pt": "esfinge"}
    ia = {1: {"id": 1, "pose": "vanta_cetica_esq.png", **fan}, 2: {"id": 2, "pose": "vanta_neutra_esq.png"},
          3: {"id": 3, "pose": "vanta_neutra_esq.png", **fan}, 4: {"id": 4, "pose": "vanta_neutra_esq.png", **fan}}
    out, _ = PE.montar([_momento(i, i * 10) for i in (1, 2, 3, 4)], pers, cfg, 60, False, ia)
    assert out[0]["sugestao"]["tipo"] == "fantasia" and out[0]["sugestao"]["pose_base"] == "vanta_cetica_esq.png"
    assert not out[1]["sugestao"] and out[2]["sugestao"]["tipo"] == "fantasia" and not out[3]["sugestao"]  # só 2
    # já existe na galeria → usa direto
    a = "vanta_cetica_esq__esfinge.png"
    pers[0]["poses"].append({"arquivo": a, "caminho": _png_em(str(tmp_path / a)), "aprovada": True, "lado": "esq", "descricao": a,
                             "grupo": "", "texto": a, "mestre": False, "boca": None, "visual": "esfinge",
                             "pose_base": "vanta_cetica_esq.png"})
    pers[0]["visuais"].append({"slug": "esfinge", "nome": "Esfinge", "tipo": "fantasia"})
    out, _ = PE.montar([_momento(1, 1)], pers, cfg, 60, False, {1: ia[1]})
    assert out[0]["pose"] == a and not out[0]["sugestao"]


def test_fantasia_gera_na_pose_da_piada(flow, tmp_path):
    c, falso, gal = flow
    r = c.post("/personagens-pod/criar", data={"nome": "Vanta", "motor": "flow", "json": json.dumps(JSON_POSES),
                                                "refs": [(io.BytesIO(_png()), "ficha.png")]}, content_type="multipart/form-data")
    pid = r.headers["Location"].rstrip("/").split("/")[-1]
    for a in ("vanta_neutra_esq.png", "vanta_cetica_esq.png"):
        c.post(f"/personagens-pod/{pid}/gerar", json={"arquivos": [a]})
        _ok(falso, gal, falso.fila[-1]["id"])
        c.get(f"/personagens-pod/{pid}/estado")
    job = {"overlays": [{"id": "f1", "origem": "personagem", "personagem": "vanta", "lado": "direita", "start": 1, "end": 3,
                         "pose": "vanta_cetica_esq.png", "projeto_id": pid,
                         "sugestao": {"tipo": "fantasia", "pose_base": "vanta_cetica_esq.png",
                                      "visual_novo": {"nome": "Esfinge", "descricao_en": "a cute sphinx", "tipo": "fantasia"}}}]}
    g = PS.gerar(job, pp._BASE)
    assert g["enviadas"] == 1 and job["overlays"][0]["pendente"]["arquivo"] == "vanta_cetica_esq__esfinge.png"
    assert "Playful comic transformation" in falso.fila[-1]["prompt"] and "RECOGNIZABLE" in falso.fila[-1]["prompt"]
    assert pp.visual(pp.carregar(pid), "esfinge")["tipo"] == "fantasia"
