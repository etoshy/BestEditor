"""v84_97 — 📊 Analisador de canal: análise salva com vídeo SEM "views" (ou vídeo que sumiu da lista) não derruba a
página (antes: jinja2 UndefinedError 'dict object' has no attribute 'views')."""
import shutil
import os

import pytest

import analisador_canal as ac


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def test_pagina_com_video_sem_views(A):
    aid = "abcabc1234"
    a = {"id": aid, "estado": "pronto", "url": "https://www.youtube.com/@x", "canal": {"nome": "Canal X"},
         "metricas": {}, "recentes": ["v1", "sumiu"], "populares": ["v2"],
         "videos": {"v1": {"id": "v1", "titulo": "Sem views", "url": "https://youtu.be/v1", "thumb": "", "duracao_s": None},
                    "v2": {"id": "v2", "titulo": "Com views", "views": 1200, "thumb": ""}},
         "ia": {"resumo": "ok", "faz_bem": ["a"], "pode_melhorar": [], "titulos": {}, "thumbs": {},
                "tipos_de_video": [{"tipo": "caso", "descricao": "", "videos": ["v1", "v2", "sumiu"], "desempenho": ""}],
                "ganchos_e_roteiro": [], "melhores": [{"id": "v1", "por_que": "x"}], "piores": [{"id": "sumiu", "por_que": "y"}],
                "sugestoes": [{"titulo": "Novo", "tipo": "", "por_que": "", "gancho": "", "thumb": "rosto assustado"}]}}
    ac.salvar(A.BASE_DIR, a)
    try:
        r = A.app.test_client().get(f"/analisador-canal/{aid}")
        assert r.status_code == 200, r.get_data(as_text=True)[-2000:]
        h = r.get_data(as_text=True)
        assert "Sem views" in h and "(?)" in h and "1,2 mil" in h and 'id="thLista"' in h
    finally:
        shutil.rmtree(os.path.join(A.BASE_DIR, ac.PASTA, aid), ignore_errors=True)


def test_formatadores_aguentam_qualquer_coisa():
    from jinja2 import Undefined
    assert ac.fmt_num(Undefined()) == "?" and ac.fmt_dur(Undefined()) == "?" and ac.fmt_num(None) == "?" and ac.fmt_num(1500) == "1,5 mil"
