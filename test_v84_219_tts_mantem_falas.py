"""v84_219: a limpeza / adaptação pro TTS não tira as tags de quem fala ([narrador|…], [mira|curiosa])."""
import adaptar_tts as at
import marcas_seguras as ms
import roteiros_yt as ry

VOZES = ["narrador", "mira", "vanta"]
ORIG = ("[narrador|contemplativo] Stell dir vor, du fällst in ein Schwarzes Loch.\n\n[mira|curiosa] Also ein Loch im Weltraum?\n\n"
        "[I3]\n\n[vanta|seca] Nein. Eher eine Region.\n\n[[INSCREVA]]\n\n[narrador] Weiter geht es.")


def test_limpeza_sem_ia_mantem(monkeypatch):
    import canal_perfil
    monkeypatch.setattr(canal_perfil, "slugs_de_voz", lambda *a, **k: VOZES)
    t = ry.limpar_para_tts(ORIG, "de")["texto"]
    for tag in ("[narrador|contemplativo]", "[mira|curiosa]", "[vanta|seca]", "[narrador]", "[[INSCREVA]]"):
        assert tag in t
    assert "[sussurrando]" not in ry.limpar_para_tts("[sussurrando] Hallo.", "de")["texto"]


def test_prompt_pede_pra_manter():
    p = at.prompt(ORIG, "de", "documentario", vozes=VOZES)
    assert "tags de QUEM FALA" in p and "[mira|curiosa]" in p
    assert "QUEM FALA" not in at.prompt("Nur Text hier.", "de", "documentario", vozes=VOZES)


def test_ia_tirou_as_tags_voltam():
    resp = ("Stell dir vor, du fällst in ein Schwarzes Loch!\n\nAlso ein Loch im Weltraum?\n\n[I3]\n\nNein. Eher eine Region.\n\n"
            "[[INSCREVA]]\n\nWeiter geht's.")
    r = at.ler_resposta(resp, ORIG, vozes=VOZES)
    t = r["texto"]
    assert t.startswith("[narrador|contemplativo] Stell")
    assert "[mira|curiosa] Also" in t and "[vanta|seca] Nein" in t and "[narrador] Weiter" in t
    assert not r["colchetes"]
    assert any("quem fala" in a for a in r["avisos"])


def test_ia_manteve_nao_mexe():
    novo, n = ms.restaurar_vozes(ORIG, ORIG.replace("Weiter geht es", "Weiter"), VOZES)
    assert n == 0
