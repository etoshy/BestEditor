"""v84_178 — 🎯 o vídeo cobre SÓ o necessário pro título (o assunto vizinho é outro vídeo, prometido e lembrado no histórico
do canal); plano enxuto e sem fonte falada nos canais explicativos; 🎭 as tags que a IA erra ([narrator|contemplativ],
[vanta|neutral], tag sem fala) são consertadas."""
import json

import numpy  # noqa: F401

import canal_perfil as cp
from test_v84_173_canal_personagens import canal  # noqa: F401 (fixture)


def test_normalizar_falas(canal):  # noqa: F811
    a, _c, S = canal
    pf = cp.carregar(a.BASE_DIR, S)
    t = ("[narrator|contemplativ] Im Jahr 1054…\n\n[mira|curiosa] Wie geht das?\n[vanta|ironica] \n"
         "[Mira] Und dann? [I7] [mira|exag=0.8] Ja.\n\n[[INSCREVA]]\n\n[narrador|tensio] Kollaps.\n[mira]\n\n[vanta|provocadora] Ende.")
    out, cons = cp.normalizar_falas(t, pf)
    assert out.startswith("[narrador] Im Jahr 1054")  # narrator → narrador; "contemplativ" não existe no teste → sai
    assert "[narrador|tenso] Kollaps." in out and "[mira] Und dann? [I7] [mira|exag=0.8] Ja." in out
    assert "[vanta|ironica]" not in out and "[mira]\n" not in out and "[[INSCREVA]]" in out
    assert any("sem fala" in c for c in cons)
    # o conversor do TTS também conserta (roteiros antigos)
    txt, faltam = cp.converter_para_vozes("[narrator|tenso] Licht.", pf, {"narrador": {"voz": "voz_n"}})
    assert txt.startswith("[voz_n|") and not faltam


def test_prompt_escopo_e_plano_enxuto(canal):  # noqa: F811
    a, c, S = canal
    import dossies as ds
    import roteiro_partes as rp
    chave = "marca_canal_teste"
    assert ds.escopo_enxuto(ds.MODELOS[chave]) and not ds.escopo_enxuto(ds.MODELOS["true_crime"])
    p = ds.criar(a.BASE_DIR, "Supernova: Wie ein Stern stirbt", modelo=chave)
    try:
        p["roteiro_base"] = "Notizen."
        p["config"].update(minutos=8, modo_partes="sim", idioma="de")
        t = ds.prompt_roteiro(p, a.BASE_DIR)
        assert "🎯 ESCOPO — SÓ O NECESSÁRIO" in t and "darüber machen wir ein eigenes Video" in t
        assert "Fonte NÃO é dita em voz alta" in t and "3 a 7 pontos" in t and "8 a 15 fatos" not in t
        assert '"fica_para_outro_video"' in t
        plano = {"titulos": ["Supernova"], "escopo": {"pergunta_central": "Wie stirbt ein massereicher Stern?",
                 "precisa_para_entender": ["Gleichgewicht", "Eisenkern", "Kollaps", "Rest"],
                 "fica_para_outro_video": ["Supernova Typ Ia", "Beteigeuze"]},
                 "capitulos": [{"titulo": f"K{i}", "objetivo": "x", "fatos": [{"fato": "f", "fonte": "F1"}], "palavras": 150}
                               for i in range(4)], "lore_registro": {"por_que": "bíblia"}}
        p["resultado"] = ds.ler_resultado(json.dumps(plano), p)
        ds.salvar(a.BASE_DIR, p)
        assert p["resultado"]["escopo"]["fica_para_outro_video"] == ["Supernova Typ Ia", "Beteigeuze"]
        assert "🎬 Próximo vídeo (ficou de fora deste): Beteigeuze" in p["resultado"]["ideias"]
        h = cp.historico(a.BASE_DIR, S)
        assert h[-1]["proximos_videos"] == ["Supernova Typ Ia", "Beteigeuze"]
        assert "PROMETIDO PRA OUTROS VÍDEOS" in cp.bloco_roteiro(cp.carregar(a.BASE_DIR, S))
        tp = ds.prompt_parte(p, 2)
        assert "FICA DE FORA (é outro vídeo): Supernova Typ Ia; Beteigeuze" in tp
        assert "NÃO diga a fonte em voz alta" in tp and "diga a fonte no texto" not in tp
        # true crime continua denso, com a fonte no texto
        q = ds.criar(a.BASE_DIR, "Caso X", modelo="true_crime")
        try:
            q["roteiro_base"] = "Notas."
            q["config"].update(minutos=12, modo_partes="sim")
            tq = ds.prompt_roteiro(q, a.BASE_DIR)
            assert "8 a 15 fatos" in tq and "Fonte NÃO é dita" not in tq and "🎯 ESCOPO" in tq
        finally:
            ds.excluir(a.BASE_DIR, q["id"])
    finally:
        ds.excluir(a.BASE_DIR, p["id"])


def test_bloco_escopo_curto_e_idioma():
    import metodo_roteiro as mr
    assert "Uma pergunta, uma resposta" in mr.bloco_escopo("X", curto=True)
    assert "fica pra outro episódio" in mr.bloco_escopo("X")
    assert mr.ler_escopo({"fica_para_outro_video": ["a", " ", "b"]})["fica_para_outro_video"] == ["a", "b"]
    assert mr.ler_escopo("lixo") == {}
