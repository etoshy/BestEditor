"""✍ v84_283 — roteiro de comentário só com o texto (sem vídeo)."""
import os

import pytest

import roteiro_comentario as RC

RESP = {
    "entendi_pt": "Um maratonista cai perto da chegada; outro para pra ajudar.", "tom": "esporte",
    "gancho": {"en": "[gasp] He was seconds from the finish line… and his legs gave out.", "pt": "Ele estava a segundos da chegada… e as pernas cederam."},
    "corpo": {"en": "A runner behind him stops to help. But then he sees someone catching up.", "pt": "Um corredor para pra ajudar. Mas aí vê alguém chegando."},
    "final": {"en": "So he lets go and runs. Was he wrong?", "pt": "Então ele solta e corre. Ele errou?"},
    "ganchos": [{"en": "Nobody expected what happened next.", "pt": "Ninguém esperava."}],
    "perguntas": [{"en": "Would you have stopped?", "pt": "Você teria parado?"}],
    "titulos": [{"en": "The finish line decision", "pt": "A decisão na chegada"}],
    "descricao": "A tough call at the finish line.", "hashtags": ["marathon", "#sports"], "conferir_pt": ["Não sei se era uma maratona oficial."],
}


def test_prompt_tem_a_formula_e_a_historia(tmp_path, monkeypatch):
    monkeypatch.setenv("ROTEIROS_COMENTARIO_DIR", str(tmp_path))
    r = RC.novo(str(tmp_path), "A marathon runner collapses seconds before the finish line.", "esporte", "en", 30, True)
    p = RC.prompt(r)
    assert "MOST SHOCKING OR EMOTIONAL MOMENT" in p and "REVEAL THE STORY QUICKLY" in p and "ONE STRONG LINE" in p
    assert "marathon runner" in p and "about 30 seconds" in p and "SPORTS" in p and "[gasp]" in p
    r2 = RC.novo(str(tmp_path), "Um homem pega peixes com a camisa.", "engracado", "pt", 0, True)
    p2 = RC.prompt(r2)
    assert "No brackets" in p2 and "BRAZILIAN PORTUGUESE" in p2 and "FUNNY" in p2
    with pytest.raises(RC.RoteiroErro):
        RC.novo(str(tmp_path), "curto")


def test_gerar_escolher_editar_mais(tmp_path, monkeypatch):
    monkeypatch.setenv("ROTEIROS_COMENTARIO_DIR", str(tmp_path))
    b = str(tmp_path)
    r = RC.novo(b, "A marathon runner collapses seconds before the finish line, another stops to help.")
    chamadas = []

    def falso(recurso, sys_, txt, schema=None, **kw):
        chamadas.append(txt)
        if "opcoes" in schema["properties"]:
            return {"opcoes": [{"en": f"Hook {i}", "pt": f"Gancho {i}"} for i in range(10)]}
        return RESP

    r = RC.gerar(b, r["id"], falso)
    res = r["res"]
    assert res["ganchos"][0]["en"].startswith("[gasp] He was")  # o usado entra como 1ª opção
    assert res["perguntas"][0]["en"] == "So he lets go and runs. Was he wrong?"
    assert res["hashtags"] == ["#marathon", "#sports"] and res["conferir_pt"]
    assert RC.texto(res).startswith("[gasp] He was") and "[gasp]" not in RC.texto(res, sem_tags=True)
    assert 5 < RC.segundos(res) < 15
    r = RC.escolher(b, r["id"], "ganchos", 1)
    assert r["res"]["gancho"]["en"] == "Nobody expected what happened next." and r["res"]["escolhido"]["ganchos"] == 1
    r = RC.editar(b, r["id"], {"corpo": {"en": "Edited body."}})
    assert r["res"]["corpo"]["en"] == "Edited body." and r["res"]["corpo"]["pt"]
    novas = RC.mais(b, r["id"], "ganchos", falso)
    assert len(novas) == 10 and len(RC.carregar(b, r["id"])["res"]["ganchos"]) == 12
    assert "Nobody expected" in chamadas[-1]  # pede DIFERENTES dos que já tem
    assert RC.listar(b)[0]["pronto"]


def test_colar_resposta_de_outra_ia(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("ROTEIROS_COMENTARIO_DIR", str(tmp_path))
    r = RC.novo(str(tmp_path), "A man catches fish with his shirt like a net and it works.")
    r = RC.colar(str(tmp_path), r["id"], "```json\n" + json.dumps(RESP) + "\n```")
    assert r["res"]["corpo"]["en"].startswith("A runner")
    with pytest.raises(RC.RoteiroErro):
        RC.colar(str(tmp_path), r["id"], '{"nada": 1}')


# ⛏ v84_284 — o que vem do minerador.py
def _pacote():
    op = lambda e, p: {"en": e, "pt": p}  # noqa: E731
    res = dict(RESP, angulo="decisão polêmica",
               angulo_b={"angulo": "emocionante", "gancho": op("Some races aren't about winning.", "Algumas corridas…"),
                         "corpo": op("He fell, and a stranger lifted him.", "Ele caiu…"), "final": op("Would you do the same?", "Você faria?")},
               reviravolta="parecia que ia ajudar até o fim", detalhe_escondido={"tempo_s": 9, "alvo_en": "runner in blue", "descricao": "o de azul"},
               discussao_principal="se ele devia ter ajudado até o fim",
               comentarios_relevantes=[{"indice": 1, "tipo": "pergunta", "uso": "vira o gancho"}],
               plano_edicao=[{"tempo_clipe": "0:07", "acao": "zoom", "alvo": "a queda", "detalhe": "1.4x"}],
               assunto_explicativo="", ideia_longa="", alertas=["dê crédito"])
    return {"origem": "minerador", "link": "https://www.tiktok.com/@r/video/1", "autor": "r", "modelo": "comentario", "nota": 8,
            "motivo": "divide opiniões", "historia": "Um maratonista cai perto da chegada e outro para pra ajudar.",
            "lingua_post": "en", "titulo": "A escolha na chegada", "momento_forte": {"tempo_s": 7, "descricao": "a queda"},
            "metricas": {"curtidas": "80K"}, "comentarios": [{"texto": "lol"}, {"texto": "why did he stop??", "pergunta": True, "curtidas": "12K"}],
            "res": res}


def test_importar_do_minerador_angulo_e_destino(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("ROTEIROS_COMENTARIO_DIR", str(tmp_path))
    b = str(tmp_path)
    r = RC.importar(b, _pacote())
    m = r["minerador"]
    assert m["comentarios_uteis"][0]["texto"] == "why did he stop??" and m["perguntas_publico"] == ["why did he stop??"]
    assert r["tom"] == "esporte" and "argue about" in r["extra"] and r["titulo"] == "A escolha na chegada"
    assert RC.destino(r)["url"].startswith("/curtos/modelo/comentario?roteiro=")
    # o mesmo link de novo atualiza (não duplica)
    r2 = RC.importar(b, dict(_pacote(), nota=9))
    assert r2["id"] == r["id"] and len(RC.listar(b)) == 1 and RC.listar(b)[0]["nota"] == 9
    # 🔀 outro ângulo
    r3 = RC.escolher(b, r["id"], "angulo", 0)
    assert r3["res"]["gancho"]["en"] == "Some races aren't about winning." and r3["res"]["angulo_b"]["angulo"] == "decisão polêmica"
    assert r3["res"]["ganchos"][r3["res"]["escolhido"]["ganchos"]]["en"] == "Some races aren't about winning."
    # explicativo → curto explicativo
    r4 = RC.importar(b, dict(_pacote(), link="https://x/2", modelo="explicativo"))
    assert "/curtos/modelo/explicativo" in RC.destino(r4)["url"]
    # aprovados.jsonl do minerador (formato bruto, uma linha por vídeo)
    p = _pacote()
    linha = {"video": {"link": "https://x/3", "autor_nome": "z", "duracao_s": 12}, "comentarios": p["comentarios"],
             "triagem": {"modelo": "comentario", "nota": 7, "motivo": "ok", "resumo_historia": "Um gato abre a porta sozinho e foge."},
             "roteiro": p["res"]}
    out = RC.importar_texto(b, json.dumps(linha) + "\n" + json.dumps({"itens": []})[:0])
    assert len(out["importados"]) == 1 and len(RC.listar(b)) == 3


def test_aba_minerador_filtros_status_e_miniatura(tmp_path, monkeypatch):
    import base64
    import minerador_rotas as MR
    monkeypatch.setenv("ROTEIROS_COMENTARIO_DIR", str(tmp_path / "rc"))
    b = str(tmp_path)
    a = RC.importar(b, dict(_pacote(), nicho="esportes", miniatura="image/jpeg;" + base64.b64encode(b"\xff\xd8x").decode()))
    e = RC.importar(b, dict(_pacote(), link="https://x/9", modelo="explicativo", nota=6, nicho="animais"))
    assert os.path.isfile(os.path.join(RC.raiz(b), a["id"] + ".jpg")) and a["minerador"]["miniatura"]
    assert {v["id"] for v in MR.videos(b, {})} == {a["id"], e["id"]}
    assert [v["id"] for v in MR.videos(b, {"nota": "7"})] == [a["id"]]
    assert [v["id"] for v in MR.videos(b, {"modelo": "explicativo"})] == [e["id"]]
    assert [v["id"] for v in MR.videos(b, {"nicho": "animais"})] == [e["id"]]
    RC.marcar(b, a["id"], "descartado")
    assert [v["id"] for v in MR.videos(b, {})] == [e["id"]]  # descartado some do padrão
    assert [v["id"] for v in MR.videos(b, {"status": "descartado"})] == [a["id"]]
    assert RC.importar(b, _pacote())["status"] == "descartado"  # reimportar não ressuscita
    with pytest.raises(RC.RoteiroErro):
        RC.marcar(b, a["id"], "xx")
    with pytest.raises(RC.RoteiroErro):
        MR.iniciar(b, str(tmp_path))  # sem tiktok_algo.py
