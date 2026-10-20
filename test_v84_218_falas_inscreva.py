"""v84_218: cada parágrafo com quem fala; o canal pode pedir um único [[INSCREVA]]; regras do pacote além da 20ª."""
import canal_perfil as cp
import roteiro_partes as rp
import roteiros_yt as ry

PERFIL = {"nome": "X", "narrador": {"slug": "narrador", "nome": "Narrador", "emocoes": {"neutro": {}}},
          "personagens": [{"slug": "mira", "nome": "Mira", "emocoes": {"curiosa": {}}},
                          {"slug": "vanta", "nome": "Vanta", "emocoes": {"seca": {}}}]}


def test_paragrafos_sem_tag():
    t = "[narrador] Eins.\n\n[I3]\n\n[[INSCREVA]]\n\nAlso ein Loch?\n\n[I2] [vanta|seca] Nein.\n\nNoch was."
    assert cp.paragrafos_sem_tag(t, PERFIL) == 2


def test_limitar_inscreva_um_so():
    pars = [f"[narrador] Satz {i}." for i in range(10)]
    t = "\n\n".join(pars[:1] + ["[[INSCREVA]]"] + pars[1:3] + ["[[INSCREVA]]"] + pars[3:9] + ["[[INSCREVA]]"] + pars[9:])
    novo, n = cp.limitar_inscreva(t, 1)
    assert n == 2 and novo.count("[[INSCREVA]]") == 1
    assert novo.index("[[INSCREVA]]") > novo.index("Satz 2")  # a de ~30%, não a do gancho


def test_montar_uma_inscreva():
    partes = [{"k": i, "titulo": f"P{i}", "texto": "[narrador] " + "wort " * 200} for i in range(1, 8)]
    rot, _ = rp.montar(partes, True, 1400, max_inscreva=1)
    assert rot.count("[[INSCREVA]]") == 1
    antes = rot.split("[[INSCREVA]]")[0]
    assert antes.count("[narrador]") == 2  # depois da 2ª parte (~28%)
    rot2, _ = rp.montar(partes, True, 1400)
    assert rot2.count("[[INSCREVA]]") == 2  # sem pedido do canal: como antes


def test_regra_marcas_uma():
    assert "UMA SÓ" in ry.regra_marcas(1)
    assert ry.regra_marcas(None) == ry.REGRA_MARCAS
    assert "[[INSCREVA]] =" not in ry.regra_marcas(0)


def test_prompt_parte_pede_tags():
    partes = [{"k": 1, "titulo": "A", "palavras": 300}, {"k": 2, "titulo": "B", "palavras": 300}]
    txt = rp.prompt_parte({"personagens_bloco": "## 🎭 bloco", "idioma": "Deutsch"}, partes, 1)
    assert "TODO parágrafo começa com a tag" in txt
    assert "MULTI VOZ" not in rp.prompt_parte({"idioma": "Deutsch"}, partes, 1)


def test_bloco_tags():
    b = cp.bloco_tags(PERFIL)
    assert "[mira|…]: curiosa" in b and "[vanta]" in b
