"""v84_168: 🎨 Identidade visual — prompt pelo JSON da marca, referências, paleta, folha mestra, poses novas, batidas,
textos em alemão e exportação (o pod é simulado)."""
import io
import json
import os
import shutil
import zipfile

import pytest
from PIL import Image

import marca_visual as mv

BASE = os.path.dirname(os.path.abspath(__file__))


@pytest.fixture()
def marca(tmp_path):
    """Uma cópia da marca oficial num base temporário (não suja a pasta de verdade)."""
    origem = os.path.join(BASE, "marcas", "dinge_erklaeren")
    destino = tmp_path / "marcas" / "dinge_erklaeren"
    shutil.copytree(origem, destino, ignore=shutil.ignore_patterns("projetos", "celulas", "estado.json"))
    os.makedirs(tmp_path / "assets" / "fonts" / "dp", exist_ok=True)
    for f in ("alfa-slab-one-Bold.ttf", "special-elite-Bold.ttf"):
        shutil.copy(os.path.join(BASE, "assets", "fonts", "dp", f), tmp_path / "assets" / "fonts" / "dp" / f)
    return str(tmp_path), mv.carregar(str(tmp_path), "dinge_erklaeren")


class _PodFalso:
    """Faz o papel do pod: guarda os pedidos e "gera" uma imagem cinza com um pouco de vermelho."""
    def __init__(self):
        self.pedidos = []

    def enviar_imagens_com_refs(self, itens, largura=1280, altura=720, nome="lote", cfg=None):
        self.pedidos.append({"itens": itens, "largura": largura, "altura": altura})
        return f"job{len(self.pedidos)}", False

    def esperar(self, jid, cfg=None, timeout_s=0, on_passo=None):
        itens = self.pedidos[int(jid[3:]) - 1]["itens"]
        return {"status": "concluido", "arquivos": [f"{i['nome']}.png" for i in itens] + ["metadados.json"], "erros": []}

    def job(self, jid, cfg=None):
        return self.esperar(jid)

    def baixar(self, jid, arquivo, destino, cfg=None):
        ped = self.pedidos[int(jid[3:]) - 1]
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        if arquivo == "metadados.json":
            with open(destino, "w") as f:
                json.dump([{"nome": i["nome"], "seed": i["seed"], "passos": 4 if i.get("referencias") else 9} for i in ped["itens"]], f)
            return destino
        im = Image.new("RGB", (ped["largura"], ped["altura"]), (20, 19, 18))
        im.paste((230, 220, 196), (ped["largura"] // 3, ped["altura"] // 4, ped["largura"] // 2, ped["altura"] // 2))
        im.paste((197, 31, 39), (10, 10, 60, 40))
        im.save(destino)
        return destino


def test_prompt_segue_o_json(marca):
    _b, m = marca
    g = m["guia"]
    refs = mv.referencias_para(m, {"mascote": "investigando"})
    assert [r[0] for r in refs] == ["mascote_pose", "mascote_proporcoes", "folha_mestra"]
    p = mv.montar_prompt(m, {"tipo": "cena", "mascote": "investigando", "assunto_en": "a 2,700-year-old tomb",
                             "composicao_en": "close-up"}, refs)
    assert p.startswith("Image 1 is the recurring mascot")
    assert "SUBJECT: a 2,700-year-old tomb" in p and "COMPOSITION: close-up" in p
    assert g["mascot"]["prompt_lock_en"].split(".")[0] in p  # o prompt_lock do mascote vai inteiro
    assert g["generation_system"]["style_lock_en"][:60] in p
    assert "Avoid:" in p and "[" not in p  # sem prompt negativo no klein/Z-Image: vai como "Avoid:"
    assert "PROPORTION LOCK" in p and "short legs" in p  # 🦵 a trava contra o fantasminha baixinho da outra IA
    assert "true proportions" in p
    sem = mv.montar_prompt(m, {"tipo": "cena", "assunto_en": "a map of the silk road"})
    assert "no mascot in this frame" in sem and not mv.referencias_para(m, {})
    assert len(mv.referencias_para(m, {"mascote": "normal"}, "flow")) == 1
    # 📷 foto sua (animal/estátua/pessoa): vai como referência + as características no prompt
    foto = os.path.join(m["dir"], "assets", "mascote_referencia_original.png")
    cena = {"tipo": "cena", "tipo_imagem": "ilustracao", "mascote": "observando", "assunto_en": "a marble statue",
            "refs_extras": [foto], "fotos_info": [{"descricao_en": "a bearded marble bust of a Greek philosopher", "estilo": "ilustracao"}]}
    refs = mv.referencias_para(m, cena)
    assert len(refs) == 4 and refs[-1][0] == "foto_1"
    p = mv.montar_prompt(m, cena, refs)
    assert "bearded marble bust" in p and "hand-inked editorial illustration" in p and "Image 4 is a photo of the real subject" in p
    assert mv.referencias_para(m, cena, "flow")[0][0] == "foto_1"  # Flow: 1 só — a cena é sobre a estátua
    assert mv.referencias_para(m, dict(cena, tipo_imagem="mascote"), "flow")[0][0] == "mascote_pose"


def test_paleta_e_grading(marca, tmp_path):
    _b, m = marca
    assert mv.validar_paleta(os.path.join(m["dir"], "assets", "painel_identidade_visual.png"), m)["status"] == "aprovada"
    cor = tmp_path / "cor.png"
    Image.new("RGB", (300, 200), (30, 90, 220)).save(cor)
    r = mv.validar_paleta(str(cor), m)
    assert r["status"] == "reprovar" and any("fora da paleta" in x for x in r["problemas"])
    mv.gradear(str(cor), str(tmp_path / "g.png"), m)
    assert mv.validar_paleta(str(tmp_path / "g.png"), m)["metricas"]["proibida_pct"] == 0


def test_folha_mestra_e_pose_nova(marca, monkeypatch):
    b, m = marca
    pod = _PodFalso()
    import pod_studio
    for k in ("enviar_imagens_com_refs", "esperar", "job", "baixar"):
        monkeypatch.setattr(pod_studio, k, getattr(pod, k))
    monkeypatch.setattr(mv, "traduzir_pose", lambda d: {"nome": "Comemorando", "en": "jumping with both arms raised in joy"})
    pid = mv.nova_pose(m, "comemorando, pulando de alegria")
    assert pid == "x_comemorando" and mv.pose_info(m, pid)["en"].startswith("jumping")
    ids = [c["id"] for c in mv.celulas_folha(m)]
    assert ids[:4] == ["frente", "perfil", "tres_quartos", "silhueta"] and pid in ids
    r = mv.gerar_celulas(m, ids, "pod", {}, variacoes=1)
    assert r["geradas"] == len(ids)
    it = pod.pedidos[0]["itens"][0]
    assert len(it["referencias"]) <= 4 and it["prompt"].startswith("Image 1 is") and "No text" in it["prompt"]
    with pytest.raises(mv.MarcaErro):
        mv.compor_folha_aprovada(m, b)  # nada aprovado ainda
    f = mv.estado_folha(m)
    for cid in ids:
        mv.aprovar_celula(m, cid, f["celulas"][cid]["candidatas"][0]["arquivo"])
    fa = mv.compor_folha_aprovada(m, b)
    assert fa["versao"] == 1 and os.path.isfile(mv.arquivo(m, fa["limpa"]))
    m2 = mv.carregar(b, "dinge_erklaeren")
    assert mv.folha_atual(m2).endswith("folha_mestra_v1_limpa.png")
    # a pose nova aprovada vira a referência dela mesma
    assert "celulas" in mv.ref_pose(m2, pid)
    reg = f["celulas"]["frente"]["candidatas"][0]
    assert reg["model_name"] == "FLUX.2 [klein] 4B" and reg["seed"] is not None and reg["style_lock_version"].startswith("sl-")


def test_batidas_gerar_texto_exportar(marca, monkeypatch):
    b, m = marca
    pod = _PodFalso()
    import pod_studio
    for k in ("enviar_imagens_com_refs", "esperar", "job", "baixar"):
        monkeypatch.setattr(pod_studio, k, getattr(pod, k))
    p = mv.criar_projeto(m, "Cannabis", "Vor 2700 Jahren wurde ein Mann begraben. Aber er war nicht der Erste.")
    resp = json.dumps({"batidas": [
        {"narracao": "Vor 2700 Jahren wurde ein Mann begraben.", "intencao_visual": "o túmulo", "tipo_imagem": "arquivo",
         "mascote": None, "assunto_en": "an ancient tomb", "texto_de": ["Vor *2.700* Jahren"], "anotacao": "circulo"},
        {"narracao": "Aber er war nicht der Erste.", "tipo_imagem": "mascote", "mascote": "dançando de alegria",
         "assunto_en": "the mascot", "texto_de": []}]})
    p["batidas"] = mv.ler_batidas(resp, m)
    assert p["batidas"][1]["mascote"] in mv.POSES and p["batidas"][1]["acao_mascote_en"] == "dançando de alegria"
    mv.salvar_projeto(m, p)
    r = mv.gerar_batidas(m, p["id"], ["c001", "c002"], "pod", {})
    assert r["geradas"] == 2
    itens = pod.pedidos[0]["itens"]
    assert "referencias" not in itens[0] and len(itens[1]["referencias"]) == 3  # Z-Image sem mascote; klein com
    mv.aplicar_texto_batida(b, m, p["id"], "c001")
    p = mv.carregar_projeto(m, p["id"])
    b1 = p["batidas"][0]
    assert b1["arquivo_master"] and b1["arquivo_texto"] and b1["paleta"]["score"] >= 0
    assert b1["geracoes"][0]["model_name"] == "Z-Image Turbo"
    reg = mv.registro_da_cena(m, p, p["batidas"][1])
    for k in ("scene_id", "narration_excerpt", "prompt_final", "reference_assets", "model_metadata", "output_file", "qa_status",
              "style_lock_version", "palette_version", "prompt_version", "postprocess_preset", "aspect_ratio"):
        assert k in reg
    z = zipfile.ZipFile(io.BytesIO(mv.exportar(m, p["id"])))
    nomes = z.namelist()
    assert "registro_cenas.json" in nomes and any(n.startswith("1_masters_sem_texto/") for n in nomes) \
        and any(n.startswith("3_com_texto_alemao/") for n in nomes)


def test_batidas_sem_ia():
    bs = mv.batidas_sem_ia(" ".join(["Das ist ein Satz mit mehreren Wörtern hier."] * 12))
    assert len(bs) >= 2 and bs[0]["mascote"]


def test_rotas():
    import app as a
    c = a.app.test_client()
    assert c.get("/marca/dinge_erklaeren").status_code == 200
    assert c.get("/marca/dinge_erklaeren/estado").get_json()["celulas"]
    r = c.post("/marca/dinge_erklaeren/projeto/novo", data={"titulo": "Teste", "narracao": "Ein Satz. Noch ein Satz?"})
    assert r.status_code == 302
    pid = r.headers["Location"].rstrip("/").split("/")[-1]
    m = mv.carregar(a.BASE_DIR, "dinge_erklaeren")
    try:
        assert c.get(f"/marca/dinge_erklaeren/p/{pid}").status_code == 200
        assert c.post(f"/marca/dinge_erklaeren/p/{pid}/batidas", json={"simples": True}).get_json()["batidas"] == 1
        d = c.get(f"/marca/dinge_erklaeren/p/{pid}/dados").get_json()
        assert d["batidas"][0]["_previa"]["prompt"]
        assert "NARRAÇÃO" in c.get(f"/marca/dinge_erklaeren/p/{pid}/prompt-batidas").get_json()["prompt"]
        assert c.post(f"/marca/dinge_erklaeren/p/{pid}/batida/c001", json={"mascote": "ideia", "texto_de": "Warum?"}).get_json()["ok"]
        assert c.get("/marca/dinge_erklaeren/arquivo/../app.py").status_code == 404
    finally:
        shutil.rmtree(mv._pasta_proj(m, pid), ignore_errors=True)


def test_elenco_do_modelo_de_video(marca):
    """🎭 Igual ao true crime: a pessoa do elenco entra com o rosto da foto mais perto da idade da cena."""
    b, m = marca
    import dossies as ds
    d = ds.criar(b, "Hanf", modelo="curiosidade_ia")
    os.makedirs(ds.pasta_midias(b, d["id"]), exist_ok=True)
    Image.new("RGB", (200, 200), (120, 110, 100)).save(os.path.join(ds.pasta_midias(b, d["id"]), "i1.jpg"))
    mid = ds.adicionar_midia(d, tipo="foto", arquivo="i1.jpg", nome="i1.jpg")["id"]
    d["elenco"] = {"pessoas": [{"nome": "Harry Anslinger", "papel": "chefe do FBN", "nascimento": 1892, "aparencia": "bald, round face",
                                "usar": True, "fotos": [{"midia": mid, "idade": 40, "ano": 1932, "so_ele": True, "rosto_visivel": True}]}],
                   "locais": [{"nome": "Washington", "tipo": "cidade", "descricao": "1930s government district", "fotos": [], "usar": True}]}
    ds.salvar(b, d)
    p = mv.criar_projeto(m, "Hanf", "Anslinger sprach 1937.", origem={"tipo": "dossie", "id": d["id"]})
    assert "Harry Anslinger" in mv.prompt_batidas(m, p["narracao"], elenco=mv.elenco_de(m, p)[1])
    bt = mv.ler_batidas(json.dumps({"batidas": [{"narracao": "Anslinger sprach 1937.", "tipo_imagem": "arquivo", "mascote": "explicando",
                                                  "assunto_en": "a man at a hearing", "pessoas": [{"nome": "Harry Anslinger"}],
                                                  "ano": 1952, "lugar": "Washington"}]}), m)[0]
    cena = mv.cena_da_batida(m, p, bt)
    refs = mv.referencias_para(m, cena)
    assert refs[-1][0] == "foto_1" and refs[0][0] == "mascote_pose" and len(refs) <= 4
    pr = mv.montar_prompt(m, cena, refs)
    assert "use the face and identity of the person" in pr and "about 60 years old" in pr and "20 years older" in pr
    assert "1930s government district" in pr  # 📍 lugar sem foto: pela descrição
    assert ds.nome_canal_cfg({"modelo": "curiosidade_ia", "nome_canal": ""}) == "Dinge erklären"
    assert ds.nome_canal_cfg({"modelo": "true_crime", "nome_canal": "X"}) == "X"
