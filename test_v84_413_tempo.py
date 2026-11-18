"""v84_413 — data e hora (criado / editado) em tudo que é listado."""
import time

import tempo_ui as T


def test_formata_e_escolhe_as_chaves():
    agora = time.time()
    h = str(T.tempo({"criado": agora - 7200, "atualizado": agora - 300}))
    assert "criado" in h and "editado há 5 min" in h and 'class="be-tempo"' in h and "data-ts" in h
    assert "editado" not in str(T.tempo({"criado": agora, "atualizado": agora + 10}))  # mesmo momento: só "criado"
    assert "criado" in str(T.tempo({"criadoEm": "2026-11-18T10:37:00"}))
    assert "criado" in str(T.tempo({"created_at": (agora - 60) * 1000}))  # milissegundos
    assert str(T.tempo({"nome": "sem data"})) == ""
    assert T.ha_quanto(agora - 3 * 86400) == "há 3 dias" and T.ha_quanto(agora) == "agora"
    assert T.data_hora(1700000000, True).endswith("2023 " + time.strftime("%H:%M", time.localtime(1700000000)))


def test_paginas_de_lista_abrem_com_o_selo(monkeypatch):
    import app as A
    import dossies as ds
    monkeypatch.setattr(ds, "listar", lambda base: [{"id": "x1", "nome": "Vídeo teste", "modelo": "M", "fontes": 1, "midias": 0,
                                                     "tem_roteiro": True, "criado": time.time() - 3600,
                                                     "atualizado": time.time() - 120}])
    c = A.app.test_client()
    h = c.get("/modelos-video").get_data(as_text=True)
    assert "Vídeo teste" in h and "be-tempo" in h and "editado há 2 min" in h
    assert "ui/tempo.js" in c.get("/jobs").get_data(as_text=True)
    for url in ("/jobs", "/temas-bruto", "/vendas", "/narracoes", "/modelados", "/explicador", "/achar-fonte",
                "/busca-lista", "/thumbs-avulsas", "/criador-personagens", "/producao-pod", "/pesquisas", "/publicacoes",
                "/personagens-pod", "/curtos", "/roteiros-yt", "/sound-design", "/conversas", "/marcas", "/flow",
                "/flow/refazer", "/curtos/link", "/historico", "/espaco"):
        r = c.get(url)
        assert r.status_code < 500, (url, r.status_code)
