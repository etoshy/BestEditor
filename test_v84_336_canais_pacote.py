"""v84_336: 📦 exportar canais (ZIP com mídias + fontes enviadas + grupos, ou só JSON) e 📥 importar em outro PC."""
import io
import json
import os
import shutil
import zipfile

import canais_pacote as PK
import curtos as CT

RAIZ = os.path.dirname(os.path.abspath(CT.__file__))


def _pc(tmp_path, nome, monkeypatch):
    """Um "PC": a pasta dos curtos, a das fontes e a dos extras próprias."""
    import dp_destaques
    import dp_extras
    d = tmp_path / nome
    fontes = d / "fontes"
    if not fontes.exists():
        shutil.copytree(dp_destaques.FONTES_DIR, fontes)
    os.makedirs(d / "extras", exist_ok=True)
    monkeypatch.setenv("CURTOS_DIR", str(d / "c"))
    monkeypatch.setattr(dp_destaques, "FONTES_DIR", str(fontes))
    monkeypatch.setenv("DP_EXTRAS_DIR", str(d / "extras"))
    try:
        dp_extras.carregar.cache_clear()
    except AttributeError:
        pass
    return str(d)


def test_leva_o_canal_com_tudo_pra_outro_pc(tmp_path, monkeypatch):
    import acabamento_extra as AX
    a = _pc(tmp_path, "pcA", monkeypatch)
    fonte = AX.instalar_fonte(os.path.join(RAIZ, "assets", "fonts", "DejaVuSans-Bold.ttf"), "Minha Marca")
    c = CT.criar_canal(a, "PlaceWow", "", "lugares incríveis")
    c["voz_link"] = {"lingua_post": "en", "idioma": "en", "voz": "vX", "modo": "minha"}
    CT.salvar_canal(a, c)
    CT.salvar_acabamento(a, {"arroba": "@placewow", "marca_fonte": fonte["familia"], "marca_gradiente": True, "marca_cor2": "#FF0000",
                             "proporcao": "1:1"}, c["id"])
    os.makedirs(os.path.join(CT.pasta_canal(a, c["id"]), "midias"), exist_ok=True)
    open(os.path.join(CT.pasta_canal(a, c["id"]), "midias", "k1.mp4"), "wb").write(b"meme")
    outro = CT.criar_canal(a, "Fails")
    PK._gravar_grupos(a, {"lugares": {"nome": "Lugares", "canal_id": c["id"]}, "fails": {"nome": "Fails", "canal_id": outro["id"]}})
    CT.salvar_acabamento(a, {"legenda_estilo": "pop"})
    zdados, nome = PK.exportar(a, [c["id"]], "zip", com_padrao=True)
    assert nome.endswith(".zip")
    nomes = zipfile.ZipFile(io.BytesIO(zdados)).namelist()
    assert f"canais/{c['id']}/canal.json" in nomes and f"canais/{c['id']}/midias/k1.mp4" in nomes
    assert any(n.startswith("fontes/") for n in nomes)
    man = json.loads(zipfile.ZipFile(io.BytesIO(zdados)).read("manifesto.json"))
    assert list(man["grupos"]) == ["lugares"] and fonte["familia"] in man["fontes"]  # só o grupo e a fonte desse canal

    b = _pc(tmp_path, "pcB", monkeypatch)  # 💻 o outro PC
    r = PK.importar(b, zdados, nome, "copia", com_padrao=True)
    assert r["canais"][0]["id"] == c["id"] and r["canais"][0]["acao"] == "novo" and r["fontes"] == [fonte["familia"]] and r["grupos"] == 1
    cb = CT.carregar_canal(b, c["id"])
    assert cb["voz_link"]["modo"] == "minha" and cb["descricao"] == "lugares incríveis"
    ac = CT.acabamento(b, c["id"])
    assert ac["arroba"] == "@placewow" and ac["proporcao"] == "1:1" and ac["marca_fonte"] == fonte["familia"]
    assert CT.acabamento(b)["legenda_estilo"] == "pop"  # o padrão de todos foi junto
    assert open(os.path.join(CT.pasta_canal(b, c["id"]), "midias", "k1.mp4"), "rb").read() == b"meme"
    import dp_destaques
    assert fonte["familia"] in {v["familia"] for v in dp_destaques.fontes_json().values()}
    assert PK._grupos(b)["lugares"]["canal_id"] == c["id"]
    r2 = PK.importar(b, zdados, nome, "copia")  # de novo: vira cópia, e o grupo vai pra ela
    assert r2["canais"][0]["acao"] == "cópia" and r2["canais"][0]["id"] != c["id"]
    assert CT.carregar_canal(b, r2["canais"][0]["id"])["nome"] == "PlaceWow (importado)"
    assert PK._grupos(b)["lugares"]["canal_id"] == r2["canais"][0]["id"]
    r3 = PK.importar(b, zdados, nome, "substituir")
    assert r3["canais"][0] == {"id": c["id"], "nome": "PlaceWow", "acao": "substituído"}


def test_so_json_e_pacote_invalido(tmp_path, monkeypatch):
    a = _pc(tmp_path, "pcA", monkeypatch)
    c = CT.criar_canal(a, "Arte BR")
    CT.salvar_acabamento(a, {"arroba": "@arte"}, c["id"])
    j, nome = PK.exportar(a, [], "json")  # vazio = todos
    assert nome.endswith(".json") and json.loads(j)["dados_canais"][0]["nome"] == "Arte BR"
    b = _pc(tmp_path, "pcB", monkeypatch)
    assert PK.importar(b, j, nome)["canais"][0]["nome"] == "Arte BR" and CT.acabamento(b, c["id"])["arroba"] == "@arte"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:  # 🔒 caminho pra fora da pasta é ignorado
        z.writestr("manifesto.json", json.dumps({"tipo": "besteditor-canais"}))
        z.writestr(f"canais/{c['id']}/canal.json", json.dumps({"id": c["id"], "nome": "X"}))
        z.writestr(f"canais/{c['id']}/../../../fora.txt", "x")
    PK.importar(b, buf.getvalue(), "x.zip", "substituir")
    assert not os.path.exists(os.path.join(b, "fora.txt")) and not os.path.exists(tmp_path / "fora.txt")
    for ruim in (b"oi", json.dumps({"tipo": "outro"}).encode()):
        try:
            PK.importar(b, ruim, "x.json")
            assert False
        except CT.CurtoErro:
            pass
