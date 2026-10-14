"""v84_96 — 🖼 thumbnails recomendadas pela IA geradas no Google Flow (texto por cima) e 🎙 adaptar o roteiro pro TTS
por idioma (alemão com regras próprias), com a direção narrativa do tipo de vídeo."""
import os
import time

import pytest
from PIL import Image

import adaptar_tts as at
import dossies as ds
import roteiros_yt as ry
import thumbs_flow as tf


# ------------------------------------------------------------------ 🎙 adaptar pro TTS
ROT = ("Era 1998.\n\n[I3] Die Polizei fand ihn am 12.03.1998 um 23:15 Uhr.\n\n[[INSCREVA]]\n\n"
       "Der Fall Nr. 4 Js 123/98 blieb offen. [CENA 2]\n\n[[VENDA]]\n\nEnde.")


def test_prompt_alemao_true_crime():
    p = at.prompt(ROT, "de", "true_crime", canal="Johans Akte", inicios_capitulos=["Era 1998."])
    assert "JOHANS AKTE" in p and "Hochdeutsch" in p and "ä, ö, ü e ß" in p
    assert "documentário criminal" in p and "Revelações importantes" in p
    assert "[[INSCREVA]]" in p and "[I3]" in p and "8.1 MARCAS DO SITE" in p and "“Era 1998.”" in p
    assert "Não traduza o roteiro para outro idioma" in p and "em alemão" in p
    assert p.rstrip().endswith("otimizado para o Chatterbox TTS.") and ROT in p
    assert at.regras_do_idioma("de")["especifico"] and "de" in at.idiomas_especificos()


def test_direcao_e_idioma_geral():
    p = at.prompt("Texto qualquer.", "pt", "historia")
    assert "documentário histórico" in p and "Hochdeutsch" not in p and "Português" in p or "português" in p.lower()
    assert not at.regras_do_idioma("pt")["especifico"]
    t = at.prompt("Hi [whispering] there.", "en", "misterio", motor="chatterbox_turbo")
    assert "TAGS DE VOZ do Chatterbox Turbo" in t and "[pausa], [sussurrando]" not in t
    with pytest.raises(ValueError):
        at.prompt("  ", "de")
    assert at.DIRECAO_DO_MODELO["true_crime"] == "true_crime" and set(at.DIRECAO_DO_MODELO.values()) <= set(at.DIRECOES)


def test_ler_resposta_confere_marcas_e_tamanho():
    ok = at.ler_resposta("```\n" + ROT.replace("Era 1998.", "Es war das Jahr neunzehnhundertachtundneunzig.") + "\n```", ROT)
    assert ok["avisos"] == [] and not ok["texto"].startswith("```")
    ruim = at.ler_resposta("Die Polizei fand ihn. Ende.", ROT)
    av = " ".join(ruim["avisos"])
    assert "[[INSCREVA]]" in av and "[[VENDA]]" in av and "[I3]" in av and "CENA 2" in av and "encolheu" in av
    assert at.ler_resposta('{"roteiro": "Hallo [pausa] Welt"}', "Hallo Welt")["colchetes"] == ["pausa"]
    with pytest.raises(ValueError):
        at.ler_resposta("   ", ROT)


# ------------------------------------------------------------------ 🖼 thumbnails
class _Foto:
    def __init__(self, cam):
        self.local_path = cam


class FlowFalso:
    def __init__(self, tmp):
        self.tmp, self.pedidos = tmp, []

    def gerar_imagem_prompt(self, prompt, forcar=False):
        self.pedidos.append((prompt, forcar))
        cam = os.path.join(self.tmp, f"flow_{len(self.pedidos)}.png")
        Image.new("RGB", (1376, 768), (40 * len(self.pedidos) % 255, 90, 140)).save(cam)
        return [_Foto(cam)]


def test_thumbs_sincronizar_gerar_e_compor(tmp_path):
    base = str(tmp_path)
    d = tf.sincronizar(base, "dossie", "abcdef0123", [{"ideia": "Detetive diante do mural", "texto": "o caso esquecido",
                                                       "prompt": "a detective in front of an evidence wall"}, "Uma casa vazia à noite"])
    assert [i["n"] for i in d["itens"]] == [1, 2] and d["itens"][1]["ideia"] == "Uma casa vazia à noite"
    # de novo: não duplica
    assert len(tf.sincronizar(base, "dossie", "abcdef0123", ["Uma casa vazia à noite"])["itens"]) == 2
    fl = FlowFalso(base)
    d = tf.gerar(base, "dossie", "abcdef0123", cliente=fl)
    assert len(fl.pedidos) == 2 and "no text" in fl.pedidos[0][0] and fl.pedidos[0][0].startswith("a detective")
    it = d["itens"][0]
    assert it["status"] == "pronto" and os.path.isfile(it["imagem"]) and Image.open(it["final"]).size == (1280, 720)
    # já tem: "as que faltam" não gera de novo; pedir a nº 1 gera outra (forcar)
    tf.gerar(base, "dossie", "abcdef0123", cliente=fl)
    assert len(fl.pedidos) == 2
    tf.gerar(base, "dossie", "abcdef0123", ns=[1], cliente=fl)
    assert len(fl.pedidos) == 3 and fl.pedidos[2][1] is True
    # mudar o texto refaz a final na hora
    antes = os.path.getmtime(tf.carregar(base, "dossie", "abcdef0123")["itens"][0]["final"])
    time.sleep(0.01)
    d = tf.editar(base, "dossie", "abcdef0123", 1, texto="NOVO TEXTO")
    assert d["itens"][0]["texto"] == "NOVO TEXTO"
    d = tf.editar(base, "dossie", "abcdef0123", 0, novo=True, ideia="minha ideia", texto="x")
    assert d["itens"][-1]["ideia"] == "minha ideia"
    d = tf.editar(base, "dossie", "abcdef0123", 2, apagar=True)
    assert [i["n"] for i in d["itens"]] == [1, 3]
    j = tf.para_json(d, "/thumbs/dossie/abcdef0123")
    assert j["itens"][0]["url_final"].startswith("/thumbs/dossie/abcdef0123/1/final") and "imagem" not in j["itens"][0]


def test_thumb_com_erro_nao_para_as_outras(tmp_path):
    base = str(tmp_path)
    tf.sincronizar(base, "roteiro_yt", "proj123", ["ideia 1", "ideia 2"])

    class Quebra(FlowFalso):
        def gerar_imagem_prompt(self, prompt, forcar=False):
            if "ideia 1" in prompt:
                raise RuntimeError("limite da conta")
            return super().gerar_imagem_prompt(prompt, forcar)
    d = tf.gerar(base, "roteiro_yt", "proj123", cliente=Quebra(base))
    assert [i["status"] for i in d["itens"]] == ["erro", "pronto"] and "limite" in d["itens"][0]["erro"]
    with pytest.raises(tf.ThumbErro):
        tf.pasta(base, "outra", "x/../y")


def test_compor_sem_texto_e_texto_longo(tmp_path):
    img = str(tmp_path / "a.png")
    Image.new("RGB", (800, 800), (200, 30, 30)).save(img)
    assert Image.open(tf.compor(img, "", str(tmp_path / "s.jpg"))).size == (1280, 720)
    assert Image.open(tf.compor(img, "uma frase bem comprida demais pra thumbnail", str(tmp_path / "l.jpg"))).size == (1280, 720)


def test_prompts_pedem_thumbnails():
    p = {"id": "abcdef0123", "tema": "Caso", "roteiro_base": "x", "fontes": [], "midias": [], "config": dict(ds.CONFIG_PADRAO)}
    t = ds.prompt_roteiro(p)
    assert '"thumbnails"' in t and "Google Flow" in t
    res = ds.ler_resultado('{"roteiro": "Texto.", "thumbnails": [{"ideia": "a", "texto": "B", "prompt": "c"}, "solta", 3]}', p)
    assert res["thumbnails"] == [{"ideia": "a", "texto": "B", "prompt": "c"}, {"ideia": "solta", "texto": "", "prompt": ""}]
    p["resultado"] = res
    assert ds.roteiro_editado(p, "Outro texto.")["thumbnails"] == res["thumbnails"]
    yt = {"analise": {"roteiro": "Oi.", "cenas": []}, "titulo": "V"}
    assert '"thumbnails"' in ry.prompt_acoes(yt, ["titulos"])
    assert ry.ler_resultado('{"roteiro_final": "Oi.", "thumbnails": [{"ideia": "x"}]}', yt)["thumbnails"][0]["ideia"] == "x"


# ------------------------------------------------------------------ rotas
@pytest.fixture
def A(monkeypatch, tmp_path):
    import app as _app
    import thumbs_tts_rotas  # noqa: F401
    _app.app.config["TESTING"] = True
    return _app


def test_rotas_tts_dossie(A, tmp_path):
    base = A.BASE_DIR
    p = ds.criar(base, "Caso de teste TTS")
    try:
        p["config"]["idioma"] = "de"
        p["resultado"] = ds.ler_resultado('{"roteiro": "' + ROT.replace("\n", "\\n") + '", "capitulos": [{"titulo": "A", "comeca_em": "Era 1998."}]}', p)
        ds.salvar(base, p)
        c = A.app.test_client()
        d = c.post(f"/tts-adaptar/dossie/{p['id']}/prompt", json={}).get_json()
        assert d["ok"] and d["especifico"] and d["direcao"] == "true_crime" and "“Era 1998.”" in d["prompt"]
        novo = ROT.replace("Ende.", "Das ist das Ende dieses Falls.")
        d = c.post(f"/tts-adaptar/dossie/{p['id']}/ler", json={"texto": novo}).get_json()
        assert d["ok"] and d["avisos"] == [] or all("🎙" not in a for a in d["avisos"])
        q = ds.carregar(base, p["id"])
        assert "Das ist das Ende" in q["resultado"]["roteiro"] and q["resultado"]["roteiro_antes_tts"].startswith("Era 1998.")
        assert "[I3]" not in q["resultado"]["roteiro_final"]  # a voz sai sem as marcas
        assert c.post(f"/tts-adaptar/dossie/{p['id']}/desfazer", json={}).get_json()["ok"]
        q = ds.carregar(base, p["id"])
        assert "Das ist das Ende" not in q["resultado"]["roteiro"] and not q["resultado"].get("roteiro_antes_tts")
        assert c.post(f"/tts-adaptar/dossie/{p['id']}/desfazer", json={}).status_code == 400
        assert c.post("/tts-adaptar/dossie/naoexiste1/prompt", json={}).status_code == 404
        o = c.get("/tts-adaptar/opcoes").get_json()
        assert "true_crime" in o["direcoes"] and "de" in o["especificos"]
        h = c.get(f"/modelos-video/{p['id']}").get_data(as_text=True)
        assert 'id="ttsGerar"' in h and 'id="thLista"' in h and "/tts-adaptar/dossie/" in h
    finally:
        ds.excluir(base, p["id"])


def test_rotas_tts_roteiro_yt(A):
    base = A.BASE_DIR
    p = ry.criar_projeto(base, texto="olá pessoal", titulo="Teste TTS YT")
    try:
        p["analise"] = {"roteiro": "Primeira frase.\n\n[[VENDA]]\n\nSegunda frase.", "idioma": "de", "cenas": []}
        ry.salvar_projeto(base, p)
        c = A.app.test_client()
        d = c.post(f"/tts-adaptar/roteiro_yt/{p['id']}/prompt", json={"direcao": "historia"}).get_json()
        assert d["ok"] and d["idioma"] == "de" and "documentário histórico" in d["prompt"]
        assert ry.carregar_projeto(base, p["id"])["tts_direcao"] == "historia"
        d = c.post(f"/tts-adaptar/roteiro_yt/{p['id']}/ler", json={"texto": "Erste Satz.\n\nZweiter Satz."}).get_json()
        assert d["ok"] and any("[[VENDA]]" in a for a in d["avisos"])
        q = ry.carregar_projeto(base, p["id"])
        assert q["analise"]["roteiro"].startswith("Erste") and q["analise"]["antes_do_tts"].startswith("Primeira")
        c.post(f"/tts-adaptar/roteiro_yt/{p['id']}/desfazer", json={})
        assert ry.carregar_projeto(base, p["id"])["analise"]["roteiro"].startswith("Primeira")
        h = c.get(f"/roteiros-yt/{p['id']}").get_data(as_text=True)
        assert 'id="ttsGerar"' in h and 'id="thLista"' in h
    finally:
        ry.excluir_projeto(base, p["id"])


def test_rotas_thumbs(A, monkeypatch, tmp_path):
    import tarefas_bg
    base = A.BASE_DIR
    p = ds.criar(base, "Caso thumbs")
    try:
        p["resultado"] = ds.ler_resultado('{"roteiro": "Texto.", "thumbnails": [{"ideia": "um mural", "texto": "O MURAL", "prompt": "a wall"}]}', p)
        ds.salvar(base, p)
        c = A.app.test_client()
        d = c.get(f"/thumbs/dossie/{p['id']}").get_json()
        assert d["ok"] and d["itens"][0]["texto"] == "O MURAL" and d["itens"][0]["url_final"] == ""
        monkeypatch.setattr(tf, "cliente_padrao", lambda: FlowFalso(str(tmp_path)))
        t = c.post(f"/thumbs/dossie/{p['id']}/gerar", json={}).get_json()
        assert t["ok"] and tarefas_bg.esperar(t["tarefa"], 20)["status"] == "pronto"
        d = c.get(f"/thumbs/dossie/{p['id']}").get_json()
        assert d["itens"][0]["status"] == "pronto" and d["itens"][0]["url_final"]
        r = c.get(d["itens"][0]["url_final"])
        assert r.status_code == 200 and r.mimetype == "image/jpeg"
        d = c.post(f"/thumbs/dossie/{p['id']}/editar", json={"n": 1, "texto": "OUTRO"}).get_json()
        assert d["itens"][0]["texto"] == "OUTRO"
        assert c.get("/thumbs/dossie/naoexiste1").status_code == 404
        assert c.get(f"/thumbs/dossie/{p['id']}/9/final").status_code == 404
    finally:
        ds.excluir(base, p["id"])
        import shutil
        shutil.rmtree(os.path.join(base, tf.PASTA, f"dossie_{p['id']}"), ignore_errors=True)
