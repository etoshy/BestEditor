"""v84_173: 🎭 canal com personagens — roteiro multi voz com emoção por fala, lore/continuidade/histórico no prompt,
vozes por personagem no Modelo de vídeo, [mira|curiosa] → voz escolhida no TTS, imagens com a ficha de cada personagem."""
import io
import json
import os
import zipfile

import numpy  # noqa: F401
import pytest

import canal_perfil as cp
import multivoz as mv
from test_v84_168_marca import pacote_zip

PERS = {
    "narrador": {"nome": "Narrador", "papel": "explica", "emocoes": {"tenso": {"exag": 0.6, "cfg": 0.45}},
                 "voz_sugerida": {"exag": 0.45, "cfg": 0.5, "vel": 0.95}},
    "personagens": [
        {"slug": "mira", "nome": "Mira", "epiteto": "Die Sternensucherin", "quando_aparece": "pergunta leiga",
         "quando_nao_aparece": "no meio do mecanismo", "segredo": "memória apagada",
         "emocoes": {"curiosa": {"exag": 0.6, "cfg": 0.45, "descricao": "pergunta"}},
         "voz_sugerida": {"exag": 0.55, "cfg": 0.45}, "visual_en": "Mira with blue tear marks.", "evitar_en": "short hair",
         "referencias": ["assets/mascote.png"]},
        {"slug": "vanta", "nome": "Vanta", "visual_en": "Vanta with an eclipse eye.", "referencias": ["assets/mascote.png"]}],
    "referencias_dupla": ["referencias/mascote_proporcoes.png"],
    "estilo_personagens_en": "simpler, less detailed characters",
    "relacao": {"dinamica": "Mira pergunta, Vanta contesta"},
}
CONT = {"pistas": [{"clue_id": "estrela_riscada", "simbolo": "Estrela riscada", "pergunta": "quem apagou?", "estado": "planned"}]}
MODELO = {"chave": "canal_teste", "nome": "🌌 Canal Teste", "nome_canal": "Canal Teste", "roteiro_exemplo": "docs/exemplo.md",
          "formatos": {"doc": {"nome": "Doc", "minutos": 6, "estrutura": ["Gancho", "Mecanismo", "Fim"]}}, "regras": ["Ciência primeiro."]}


def pacote_com_personagens(slug: str) -> bytes:
    z = zipfile.ZipFile(io.BytesIO(pacote_zip(slug)))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as out:
        for n in z.namelist():
            if not n.endswith("modelo_roteiro.json"):
                out.writestr(n, z.read(n))
        out.writestr(f"{slug}/modelo_roteiro.json", json.dumps(MODELO, ensure_ascii=False))
        out.writestr(f"{slug}/personagens.json", json.dumps(PERS, ensure_ascii=False))
        out.writestr(f"{slug}/continuidade.json", json.dumps(CONT, ensure_ascii=False))
        out.writestr(f"{slug}/lore.md", "# Bíblia\nVanta esconde o observatório.")
        out.writestr(f"{slug}/docs/exemplo.md", "## 00:00\n**NARRAÇÃO** Exemplo.\n**VISUAL** nebulosa")
    return buf.getvalue()


def test_multivoz_emocao_por_fala():
    vozes = {"mira": {"slug": "mira", "nome": "Mira", "motor": "chatterbox"}}
    d = mv.dividir("[mira|exag=0.8|cfg=0.3] Wirklich? [mira] Ja.", vozes)
    assert d["falas"][0]["ajustes"] == {"exag": 0.8, "cfg": 0.3} and "ajustes" not in d["falas"][1]
    kw = mv.aplicar_ajustes("chatterbox", {"exaggeration": 0.5, "cfg_weight": 0.5}, {"exag": 0.8, "vel": 1.1})
    assert kw == {"exaggeration": 0.8, "cfg_weight": 0.5}
    assert mv.aplicar_ajustes("piper", {"velocidade": 1.0}, {"exag": 0.8, "vel": 1.1}) == {"velocidade": 1.1}
    assert mv.ler_ajustes("exag=9|cfg=abc|vel=0.9") == {"exag": 1.5, "vel": 0.9}


@pytest.fixture()
def canal():
    import app as a
    import dossies as ds
    S = "canal_teste_pers"
    c = a.app.test_client()
    r = c.post("/marca/importar", data={"zip": (io.BytesIO(pacote_com_personagens(S)), "p.zip")}, content_type="multipart/form-data")
    assert r.status_code == 302
    yield a, c, S
    c.post(f"/marca/{S}/excluir")
    for k in [k for k, v in ds.MODELOS.items() if v.get("identidade_visual") == S]:
        ds.MODELOS.pop(k, None)


def test_roteiro_com_personagens_e_lore(canal):
    a, c, S = canal
    import dossies as ds
    chave = "marca_canal_teste"
    mod = ds.MODELOS[chave]
    assert mod["perfil_canal"] == S and "Exemplo." in mod["referencia_padrao"]
    p = ds.criar(a.BASE_DIR, "Was ist ein Schwarzes Loch?", modelo=chave)
    try:
        assert p["config"]["referencia_modo"] == "modelar" and p["config"]["nome_canal"] == "Canal Teste"
        p["roteiro_base"] = "Notizen."
        t = ds.prompt_roteiro(p, a.BASE_DIR)
        assert "[mira] = Mira" in t and "[mira|curiosa]" in t and "QUANDO NÃO APARECE: no meio do mecanismo" in t
        assert "Vanta esconde o observatório" in t and "estrela_riscada" in t and "lore_registro" in t
        assert "SEM indicações visuais" in t
        rot = "[narrador|tenso] Licht entkommt nicht.\n[mira|curiosa] Und dann?\n[vanta] Dann nichts."
        reg = {"pistas": [{"clue_id": "estrela_riscada", "o_que_aparece": "no fim", "estado": "used"}],
               "personagens": {"mira": "pergunta"}, "por_que": "bíblia §3"}
        p["resultado"] = ds.ler_resultado(json.dumps({"roteiro": rot, "titulos": ["x"], "lore_registro": reg}), p)
        ds.salvar(a.BASE_DIR, p)
        h = cp.historico(a.BASE_DIR, S)
        assert h[-1]["tipo"] == "episodio" and h[-1]["dossie"] == p["id"] and h[-1]["por_que"] == "bíblia §3"
        perfil = cp.carregar(a.BASE_DIR, S)
        assert perfil["continuidade"]["pistas"][0]["estado"] == "used"
        assert "pergunta" in cp.bloco_roteiro(perfil)  # o histórico volta no próximo prompt
        # vozes: escolher na página → [mira|curiosa] vira a voz cadastrada com a emoção
        r = c.post(f"/modelos-video/{p['id']}/config", json={"vozes_personagens": {
            "narrador": {"voz": "voz_n"}, "mira": {"voz": "voz_m", "exag": "0.5"}, "vanta": {"voz": ""}}}).get_json()
        vp = r["config"]["vozes_personagens"]
        texto, faltam = cp.converter_para_vozes(rot, perfil, vp)
        assert "[voz_n|exag=0.6|cfg=0.45|vel=0.95]" in texto and "[voz_m|exag=0.6|cfg=0.45]" in texto and faltam == ["vanta"]
        assert ds.vozes_lembradas(chave)["mira"]["voz"] == "voz_m"  # o próximo vídeo do canal já vem com elas
        h = c.get(f"/modelos-video/{p['id']}").get_data(as_text=True)
        assert 'id="vozBox"' in h and '"marca_canal_teste"' in h
        g = c.get(f"/gerar-voz?dossie={p['id']}").get_data(as_text=True)
        assert "Roteiro com personagens" in g and "Falta escolher a voz de: vanta" in g
        # o import de novo mantém o histórico e o estado das pistas
        c.post("/marca/importar", data={"zip": (io.BytesIO(pacote_com_personagens(S)), "p.zip")}, content_type="multipart/form-data")
        perfil = cp.carregar(a.BASE_DIR, S)
        assert perfil["historico"] and perfil["continuidade"]["pistas"][0]["estado"] == "used"
        pag = c.get(f"/marca/{S}").get_data(as_text=True)
        assert "Personagens, lore e histórico" in pag and "Die Sternensucherin" in pag
        assert c.post(f"/marca/{S}/historico/nota", json={"texto": "no ep. 5 a Vanta quase conta"}).get_json()["ok"]
        assert c.post(f"/marca/{S}/lore", json={"texto": "# Nova bíblia", "motivo": "teste"}).get_json()["ok"]
        h = cp.historico(a.BASE_DIR, S)
        assert h[-1]["tipo"] == "mudanca" and "Vanta esconde" in h[-1]["antes"] and h[-2]["tipo"] == "nota"
    finally:
        ds.excluir(a.BASE_DIR, p["id"])


def test_imagens_com_a_ficha_das_personagens(canal):
    a, _c, S = canal
    import marca_visual as m_v
    m = m_v.carregar(a.BASE_DIR, S)
    cena = {"tipo": "cena", "tipo_imagem": "ilustracao", "assunto_en": "a black hole",
            "personagens": [{"slug": "mira", "acao_en": "looking up"}, "vanta"]}
    refs = m_v.referencias_para(m, cena)
    assert [r[0] for r in refs] == ["personagem_mira", "personagem_vanta", "personagens_dupla"]
    pr = m_v.montar_prompt(m, cena, refs)
    assert "canonical character sheet of Mira" in pr and "exactly 2 characters" in pr and "MIRA: Mira with blue tear marks." in pr
    assert "Action: looking up." in pr and "simpler, less detailed characters" in pr and "short hair" in pr
    assert m_v.referencias_para(m, cena, "flow")[0][0] == "personagens_dupla"
    sem = m_v.montar_prompt(m, {"tipo": "cena", "assunto_en": "a nebula"})
    assert "no characters in this frame" in sem
    bs = m_v.batidas_sem_ia("[narrador] Erst Licht. [mira|curiosa] Und dann? Was passiert danach genau mit dem Licht im Loch?", m=m)
    assert bs[0]["personagens"] == [{"slug": "mira", "acao_en": ""}] and not bs[0]["mascote"] and bs[0]["tipo_imagem"] == "ilustracao"
    assert "PERSONAGENS DO CANAL" in m_v.prompt_batidas(m, "[mira] Hallo?")
    conf = {x["item"] for x in m_v.conferir_pacote(m)}
    assert "personagens.json" in conf and "referencias/mascote_proporcoes.png" not in conf  # coisas de mascote não se aplicam
