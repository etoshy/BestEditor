"""
v84_61 — "se eu te enviar um vídeo de um criador, consegue criar um modelo de vídeo e uma direção pro editor?"
Vídeo analisado: canal Mistere (rabbit holes). Viraram:
  - 🕵️ Modelo de vídeo "🕳 Rabbit holes bizarros" (dossies.MODELOS["rabbit_holes"]);
  - 🎬 Direção "Rabbit hole sombrio (estilo Mistere)" (direcoes_canais.MISTERE, id sys_mistere),
    que o modelo sugere sozinho quando o vídeo vem de um projeto dele.
"""
import os

import pytest

import dossies as ds


def test_modelo_gera_prompt_com_ritmo_do_canal():
    m = ds.MODELOS["rabbit_holes"]
    assert set(m["formatos"]) == {"compilado", "caso_unico", "arquivo_oficial", "tutorial_ironico", "curto"}
    p = {"tema": "Casos bizarros", "config": {"modelo": "rabbit_holes", "formato": "compilado", "minutos": 20},
         "fontes": [], "midias": [], "roteiro_base": "anotações"}
    pr = ds.prompt_roteiro(p)
    assert "~3400 palavras" in pr  # 170 palavras/min (narração rápida do canal), não 150
    assert "Tu sabia que" in pr and "abre aspas" in pr and m["regras"][0][:30] in pr
    for fk in m["formatos"]:
        p["config"]["formato"] = fk
        assert m["formatos"][fk]["nome"].split(" ", 1)[1] in ds.prompt_roteiro(p)


def test_outros_modelos_continuam_a_150_por_minuto():
    p = {"tema": "T", "config": {"modelo": "misterios", "formato": "investigacao", "minutos": 10}, "fontes": [], "midias": [],
         "roteiro_base": "x"}
    assert "~1500 palavras" in ds.prompt_roteiro(p)


def test_direcao_entra_na_lista_e_planeja_no_estilo():
    import dp_direcao
    ids = [d["id"] for d in dp_direcao.direcoes(com_usuario=False)]
    assert ids[:4] == ["sys_tudo", "sys_doc_classico", "sys_cinema", "sys_dinamico"] and "sys_mistere" in ids
    d = dp_direcao.direcao("sys_mistere")
    assert d["ritmo"] == "dinamico" and d["legenda"] is None
    # todos os ids usados existem no catálogo (nada some em silêncio)
    import dp_visual
    efeitos_ok = set(dp_visual.EFEITO_PARA_ZOOM) | {e["id"] for e in dp_visual.efeitos()}
    for eixo in ("filtros", "transicoes", "entradas", "templates"):
        validos = dp_direcao._ids_validos(eixo)
        assert all(i["id"] in validos for i in d[eixo]["itens"]), eixo
    assert all(i["id"] in efeitos_ok for i in d["efeitos"]["itens"])
    import dp_destaques
    assert all(e in dp_destaques.catalogo() for e in d["destaques"]["estilos"])
    segs = [{"start": i * 3.0, "end": i * 3.0 + 3, "foto": i % 4 == 0} for i in range(40)]
    plano = dp_direcao.planejar(segs, "sys_mistere", semente=3)
    trans = [t["transition"] for t in plano["trechos"] if t.get("transition") not in (None, "none")]
    assert plano["filtro_cor"] in {i["id"] for i in d["filtros"]["itens"]}
    assert trans and len(trans) < len(segs) * 0.6  # maioria corte seco
    assert all(t.replace("dp:", "") in {i["id"] for i in d["transicoes"]["itens"]} for t in trans)
    ed = dp_direcao.para_edicao("sys_mistere")
    assert ed["overlays"]["itens"] and all(not dp_visual.efeito_e_movimento(i["id"]) for i in ed["overlays"]["itens"])


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def test_projeto_do_modelo_sugere_a_direcao_no_editor(A):
    p = ds.criar(A.BASE_DIR, "Rabbit holes teste", modelo="rabbit_holes")
    try:
        job = {"job_id": "mistere-1", "media_library": []}
        assert A._ligar_projeto(job, "dossie", p["id"])
        assert job["direcao_do_projeto"] == "sys_mistere"
        job["pending_segments"] = [{"start": i * 3.0, "end": i * 3.0 + 3, "provider": "pexels", "query": "q", "media_type": "video"}
                                   for i in range(10)]
        from prompt_builder import ParsedAIResponse
        A._aplicar_extras_dp(job, ParsedAIResponse(segments=[]))
        assert job["editor_defaults"]["direcao"] == "sys_mistere"
        assert any(s.get("efeito") for s in job["pending_segments"])
        # a IA escolheu outra direção: vale a da IA
        job2 = {"job_id": "mistere-2", "media_library": [], "direcao_do_projeto": "sys_mistere",
                "pending_segments": [{"start": 0.0, "end": 3.0, "provider": "pexels", "query": "q", "media_type": "video"}]}
        A._aplicar_extras_dp(job2, ParsedAIResponse(segments=[], direcao="sys_cinema"))
        assert job2["editor_defaults"]["direcao"] == "sys_cinema"
        # outro modelo: nenhuma sugestão
        p2 = ds.criar(A.BASE_DIR, "Outro", modelo="true_crime")
        assert A._ligar_projeto(job, "dossie", p2["id"]) and "direcao_do_projeto" not in job
    finally:
        import shutil
        for pid in [p["id"]] + ([p2["id"]] if "p2" in dir() else []):
            shutil.rmtree(os.path.join(A.BASE_DIR, "dossies", pid), ignore_errors=True)


def test_formatos_dos_videos_2_e_3():
    """v84_62: caso de arquivo oficial (CIA/Guarulhos) e “tutorial” irônico (Stasi)."""
    base = {"tema": "T", "fontes": [], "midias": [], "roteiro_base": "x"}
    pr = ds.prompt_roteiro(dict(base, config={"modelo": "rabbit_holes", "formato": "arquivo_oficial"}))
    assert "AS EXPLICAÇÕES" in pr and "conhecer as pessoas" in pr and "Parte 1" in pr
    pr = ds.prompt_roteiro(dict(base, config={"modelo": "rabbit_holes", "formato": "tutorial_ironico"}))
    assert "LIÇÕES numeradas" in pr and "nunca escreva um passo a passo" in pr
