"""v84_111 — ⬛ trecho SEM CENA (nenhum banco achou mídia): a edição da IA cobre com um fundo gerado + o que a fala
pede, como se fosse escolha; quando a pessoa põe uma mídia ali e gera a edição de novo, ele volta a ser um clipe normal."""
import json
import os

import pytest

import prompt_edicao as pe


def _segs():
    return [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "farol", "media_type": "video"},
            {"start": 4.0, "end": 8.0, "provider": "pexels", "query": "mapa antigo", "media_type": "video", "sem_midia": True},
            {"start": 8.0, "end": 12.0, "provider": "pexels", "query": "navio", "media_type": "video", "sem_midia": True}]


JOB = {"total_duration": 12.0, "segments": [{"start": 0, "end": 12, "text": "Em 1850 o navio sumiu perto do farol."}]}


def test_prompt_marca_e_pede_cobertura_so_quando_tem_trecho_sem_cena():
    t = pe.montar_prompt(JOB, {"direcao": "sys_tudo", "segmentos": _segs()})
    assert "T2 [0:04.0→0:08.0] ⬛ SEM CENA — nenhuma mídia achada pra 'mapa antigo'" in t
    assert "13. TRECHOS SEM CENA (⬛: T2, T3)" in t and "ESCOLHA de edição" in t and "papel = papel de arquivo" in t
    assert '{"trecho": 2, "cobrir": {"fundo": "papel"' in t and "{regra_cobrir}" not in t and "{exemplo_cobrir}" not in t
    limpo = pe.montar_prompt(JOB, {"direcao": "sys_tudo", "segmentos": [dict(s, sem_midia=False) for s in _segs()]})
    assert "SEM CENA" not in limpo and "13. TRECHOS" not in limpo and "{regra_cobrir}" not in limpo and "{exemplo_cobrir}" not in limpo
    # a pessoa pôs uma mídia no T2 (que antes estava coberto): volta a ser um trecho normal
    segs = _segs()
    segs[1]["override_source"] = {"source": "local_file", "value": "/x/minha.mp4", "kind": "video"}
    segs[2]["override_source"] = {"source": "local_file", "value": "/j/coberturas/fundo_papel_1.png", "kind": "image",
                                  "cobertura": True, "fundo": "papel"}
    t = pe.montar_prompt(JOB, {"direcao": "sys_tudo", "segmentos": segs})
    assert "T2 [0:04.0→0:08.0] vídeo 'mapa antigo' (arquivo escolhido pela pessoa" in t
    assert "T3 [0:08.0→0:12.0] ⬛ SEM CENA — coberto na edição anterior (fundo papel)" in t and "(⬛: T3)" in t


def test_ler_resposta_cobrir_vira_foto():
    r = pe.ler_resposta(json.dumps({"trechos": [
        {"trecho": 2, "cobrir": {"fundo": "papel", "cor": "#aa0011"}, "camera": "in", "efeito": "zoom_in"},
        {"trecho": 3, "cobrir": "inexistente"}, {"trecho": 1, "camera": "in"}]}), 3, 12.0, [], foto=[False, False, False])
    t = {x["indice"]: x for x in r["trechos"]}
    assert t[1]["cobrir"] == {"fundo": "papel", "cor": "#AA0011"} and t[1]["camera"] == "in"  # coberto = foto: câmera vale
    assert t[2]["cobrir"] == {"fundo": "escuro"} and any("inexistente" in a for a in r["avisos"])
    assert 0 not in t  # trecho de vídeo: câmera não vale


@pytest.fixture
def A(monkeypatch, tmp_path):
    import app as _app
    _app.app.config["TESTING"] = True
    monkeypatch.setattr(_app, "_job_dir", lambda jid: str(tmp_path / "jobs" / jid))
    monkeypatch.setattr(_app, "_save_state", lambda jid: None)
    return _app


def test_resposta_gera_os_fundos_e_salvar_mantem_a_cobertura(A, monkeypatch):
    jid = "cobrir1"
    os.makedirs(A._job_dir(jid), exist_ok=True)
    A._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "created_at": 1.0, "total_duration": 12.0,
                    "pending_segments": [{k: v for k, v in s.items() if k != "sem_midia"} for s in _segs()],
                    "segment_previews": [None, None, None], "overlays": [], "cutaway_suggestions": [], "media_library": []}
    monkeypatch.setattr(A, "_start_assembly", lambda *a: pytest.fail("não deveria montar"))
    c = A.app.test_client()
    try:
        trechos = [{"trecho": 2, "cobrir": {"fundo": f}} for f in sorted(pe.IDS_COBERTURA)]
        # cada fundo da lista gera de verdade (um por vez no trecho 2)
        for t in trechos:
            r = c.post(f"/job/{jid}/edicao/resposta", json={"texto": json.dumps({"trechos": [t]}), "foto": [False] * 3}).get_json()
            cob = r["trechos"][0]["cobertura"]
            assert os.path.isfile(cob["value"]) and cob["fundo"] == t["cobrir"]["fundo"], (t, r.get("avisos"))
            assert os.path.dirname(cob["value"]) == os.path.join(A._job_dir(jid), "coberturas")
        # o Estúdio põe o fundo no trecho e salva: continua marcado como cobertura (o próximo prompt sabe)
        r = c.post(f"/job/{jid}/edicao/resposta", json={"texto": json.dumps({"trechos": [{"trecho": 2, "cobrir": {"fundo": "papel"}}]})}).get_json()
        caminho = r["trechos"][0]["cobertura"]["value"]
        d = c.post(f"/job/{jid}/confirm-segments", data={"acao": "salvar", "seg_1_source_mode": "upload", "seg_1_local_value": caminho,
                                                          "seg_1_zoom_direction": "in"}, headers={"X-Requested-With": "fetch"}).get_json()
        assert d["ok"]
        ov = A._JOBS[jid]["pending_segments"][1]["override_source"]
        assert ov["value"] == caminho and ov["cobertura"] is True and ov["fundo"] == "papel" and ov["kind"] == "image"
        p = c.post(f"/job/{jid}/edicao/prompt", json={"direcao": "sys_tudo"}).get_json()["prompt"]
        assert "coberto na edição anterior (fundo papel)" in p
        html = c.get(f"/job/{jid}/edit-segments").get_data(as_text=True)
        assert "sem_midia: !s.override_source" in html and "sem cena cobertos" in html
    finally:
        A._JOBS.pop(jid, None)
