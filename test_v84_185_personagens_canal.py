"""v84_185: 🧍 as personagens do zip do canal (personagens/<slug>.json) → criar a partir delas ou conectar um projeto
que já existe; a 1ª geração no Flow pode sair só do texto; com a mestre, ela vai sozinha de referência; folha/várias
figuras/fundo branco → refaz sozinho 1x."""
import io
import json
import os
import zipfile

from PIL import Image, ImageDraw

import marca_visual as mv
import personagens_pod as pp
from test_v84_183_personagens_pod import JSON_POSES, _png
from test_v84_184_personagens_flow import LoteFalso, _ok, _verde  # noqa: F401
import test_v84_184_personagens_flow as T184


def _pacote(com_poses=True):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("canal_x/brand_guide.json", json.dumps({"schema": mv.SCHEMA, "project": {"name": "Canal X"}}))
        z.writestr("canal_x/pacote.json", json.dumps({"formato": mv.FORMATO_PACOTE, "slug": "canal_x", "nome": "Canal X"}))
        z.writestr("canal_x/assets/logo.png", _png())
        z.writestr("canal_x/personagens.json", json.dumps({"personagens": [
            {"slug": "vanta", "nome": "Vanta", "poses_json": "personagens/vanta.json"}]}))
        if com_poses:
            z.writestr("canal_x/personagens/vanta.json", json.dumps(JSON_POSES))
            z.writestr("canal_x/personagens/ruim.txt", "x")
    return buf.getvalue()


def test_pacote_com_personagens_e_conexao(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(tmp_path / "pp"))
    base = str(tmp_path)
    slug = mv.importar_zip(base, _pacote())
    m = mv.carregar(base, slug)
    assert [c["slug"] for c in mv.personagens_png(m)] == ["vanta"]
    lista = pp.personagens_dos_canais(base)
    assert lista[0]["canal"] == "canal_x" and lista[0]["poses"] == 5 and lista[0]["projeto"] is None
    # ➕ criar a partir do canal, sem ficha (Flow)
    p = pp.criar_do_canal("canal_x", "vanta", [], base=base)
    assert p["refs"] == [] and p["canal"]["personagem"] == "vanta" and len(p["dados"]["poses"]) == 5
    assert pp.personagens_dos_canais(base)[0]["projeto"]["id"] == p["id"]
    assert pp.projeto_da_personagem("canal_x", "vanta", base)["id"] == p["id"]
    # 🔗 outro projeto conectado à mesma personagem: o primeiro fica solto
    q = pp.criar("Outro", json.dumps({"poses": [{"arquivo": "a", "prompt": "x"}]}), [("f.png", _png())], base=base)
    pp.ligar_canal(q["id"], "canal_x", "vanta", usar_json=True, base=base)
    assert pp.carregar(p["id"], base)["canal"] is None
    q2 = pp.carregar(q["id"], base)
    assert q2["canal"]["slug"] == "canal_x" and len(q2["dados"]["poses"]) == 5  # poses trocadas pelas do canal
    # importar o pacote de novo mantém a conexão
    mv.importar_zip(base, _pacote())
    assert pp.projeto_da_personagem("canal_x", "vanta", base)["id"] == q["id"]
    # o zip exportado não leva a conexão (é deste PC)
    nomes = zipfile.ZipFile(io.BytesIO(mv.exportar_pacote(mv.carregar(base, slug)))).namelist()
    assert "canal_x/personagens/vanta.json" in nomes and not any("personagens_ligados" in n for n in nomes)
    # desconectar / excluir soltam a personagem
    pp.desligar_canal(q["id"], base)
    assert pp.projeto_da_personagem("canal_x", "vanta", base) is None
    pp.ligar_canal(q["id"], "canal_x", "vanta", base=base)
    pp.excluir(q["id"], base)
    assert mv.ligacoes_personagens(mv.carregar(base, slug)) == {}


def test_rotas_canal(tmp_path, monkeypatch):
    import app as A
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(tmp_path / "pp"))
    monkeypatch.setattr(pp, "personagens_dos_canais", lambda base: [{"slug": "vanta", "nome": "Vanta", "canal": "canal_x",
                                                                   "canal_nome": "Canal X", "poses": 5, "projeto": None, "arquivo": "x"}])
    c = A.app.test_client()
    html = c.get("/personagens-pod").get_data(as_text=True)
    assert "Personagens dos canais" in html and "criar-do-canal" in html and "Canal X" in html
    p = pp.criar("V", json.dumps(JSON_POSES), [])
    html = c.get(f"/personagens-pod/{p['id']}").get_data(as_text=True)
    assert 'id="canalSel"' in html and "Canal X → Vanta" in html


def test_flow_sem_ficha_e_so_a_mestre(tmp_path, monkeypatch):
    import flow_estudio as FE
    import flow_lote
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(tmp_path / "pp"))
    falso = LoteFalso()
    monkeypatch.setattr(flow_lote, "lote", lambda: falso)
    gal = tmp_path / "gal"
    gal.mkdir()
    monkeypatch.setattr(FE, "pasta_galeria", lambda: str(gal))
    p = pp.criar("V", json.dumps(JSON_POSES), [])
    pp.enviar(p["id"], ["vanta_neutra_esq.png"])
    j = falso.fila[-1]
    assert not j.get("referencia_arquivo") and "reference image" not in j["prompt"] and "VANTA LOCK" in j["prompt"]
    _ok(falso, gal, j["id"])
    pp.sincronizar(p["id"])
    pp.usar_como_mestre(p["id"], "vanta_neutra_esq.png")
    pp.enviar(p["id"], ["vanta_cetica_esq.png"])
    j = falso.fila[-1]
    ref = Image.open(j["referencia_arquivo"])
    assert ref.width < ref.height  # só a mestre (não a colagem com a ficha)
    assert j["prompt"].startswith("The reference image is the APPROVED MASTER") and "no character sheet" in j["prompt"]


def test_folha_com_varias_poses_refaz(tmp_path, monkeypatch):
    import flow_estudio as FE
    import flow_lote
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(tmp_path / "pp"))
    falso = LoteFalso()
    monkeypatch.setattr(flow_lote, "lote", lambda: falso)
    gal = tmp_path / "gal"
    gal.mkdir()
    monkeypatch.setattr(FE, "pasta_galeria", lambda: str(gal))
    p = pp.criar("V", json.dumps(JSON_POSES), [("f.png", _png())])
    pp.enviar(p["id"], ["vanta_neutra_esq.png"])
    j = falso.fila[-1]
    im = Image.new("RGB", (900, 1200), (0, 255, 0))
    d = ImageDraw.Draw(im)
    for k in range(3):  # a folha: 3 painéis brancos com a personagem
        x = k * 300 + 10
        d.rectangle([x, 500, x + 280, 1200], fill=(255, 255, 255))
        d.ellipse([x + 90, 560, x + 190, 660], fill=(240, 220, 205), outline=0, width=4)
        d.polygon([(x + 60, 1200), (x + 100, 680), (x + 180, 680), (x + 220, 1200)], fill=(20, 20, 30))
    im.save(gal / "folha.png")
    j.update(estado="ok", resultados=[{"arquivo": "folha.png", "tipo": "imagem"}])
    pp.sincronizar(p["id"])
    it = pp.carregar(p["id"])["imagens"]["vanta_neutra_esq.png"]
    assert it["estado"] == "fila" and len(falso.fila) == 2 and "copied the reference sheet" in falso.fila[-1]["prompt"]
    assert it["versoes"][0]["defeito"] and "folha" in it["versoes"][0]["aviso"]


def test_zip_do_canal_leva_as_personagens(tmp_path, monkeypatch):
    """v84_188: o 📦 Zip do canal leva as poses aprovadas (e a mestre) das personagens conectadas; importar em outro
    PC recria o projeto já conectado; importar de novo junta (não duplica)."""
    pc1, pc2 = tmp_path / "pc1", tmp_path / "pc2"
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(pc1 / "pp"))
    b1 = str(pc1)
    mv.importar_zip(b1, _pacote())
    p = pp.criar_do_canal("canal_x", "vanta", [("ficha.png", _png())], base=b1)
    d = pp._pasta(p["id"], b1)
    q = pp.carregar(p["id"], b1)
    for a, estado in (("vanta_neutra_esq.png", "aprovada"), ("vanta_cetica_esq.png", "aprovada"), ("vanta_relogio_esq.png", "pronta")):
        Image.new("RGBA", (60, 90), (200, 0, 0, 255)).save(os.path.join(d, "imagens", a))
        q["imagens"][a].update(estado=estado, versoes=[{"local": a}], atual=0)
    q["mestre"] = {"arquivo": "vanta_neutra_esq.png", "local": "vanta_neutra_esq.png"}
    pp.salvar(q, b1)
    m1 = mv.carregar(b1, "canal_x")
    z = zipfile.ZipFile(io.BytesIO(mv.exportar_pacote(m1)))
    nomes = z.namelist()
    assert "canal_x/personagens_projetos/vanta/projeto.json" in nomes and "canal_x/personagens_projetos/vanta/refs/ficha.png" in nomes
    assert "canal_x/personagens_projetos/vanta/imagens/vanta_cetica_esq.png" in nomes
    assert not any("relogio" in n for n in nomes)  # pra revisar não vai (padrão)
    assert any("relogio" in n for n in zipfile.ZipFile(io.BytesIO(mv.exportar_pacote(m1, "tudo"))).namelist())
    assert not any("personagens_projetos" in n for n in zipfile.ZipFile(io.BytesIO(mv.exportar_pacote(m1, "nao"))).namelist())
    dados = mv.exportar_pacote(m1)
    # 💻 outro PC
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(pc2 / "pp"))
    b2 = str(pc2)
    mv.importar_zip(b2, dados)
    novo = pp.projeto_da_personagem("canal_x", "vanta", b2)
    assert novo and novo["canal"]["personagem"] == "vanta" and novo["refs"] == ["ficha.png"]
    assert novo["mestre"]["arquivo"] == "vanta_neutra_esq.png"
    assert {a for a, it in novo["imagens"].items() if it["estado"] == "aprovada"} == {"vanta_neutra_esq.png", "vanta_cetica_esq.png"}
    assert pp.arquivo_atual(novo, "vanta_cetica_esq.png", b2)
    # importar de novo: o mesmo projeto, sem versão duplicada
    mv.importar_zip(b2, dados)
    de_novo = pp.projeto_da_personagem("canal_x", "vanta", b2)
    assert de_novo["id"] == novo["id"] and len(de_novo["imagens"]["vanta_cetica_esq.png"]["versoes"]) == 1
    assert len(pp.listar(b2)) == 1
