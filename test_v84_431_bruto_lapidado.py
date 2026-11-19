"""v84_431 — base "lapidada": a aula é dividida entre os vídeos (um trecho → um vídeo) e cada parte é lapidada sem resumir."""
import temas_bruto as TB


def _modelo(monkeypatch):
    import dossies as ds
    monkeypatch.setitem(ds.MODELOS, "teste_fil", {"nome": "Teste", "formatos": {"ensaio": {"nome": "E", "minutos": 14}}})


def test_divisoes_novas_e_padrao(monkeypatch):
    _modelo(monkeypatch)
    assert TB.DIVISAO_PADRAO == "denso" and TB.DIVISOES["denso"]["faixa"] == (6, 8)
    assert "de 6 a 8" in TB.system_analise({"modelo": "teste_fil", "divisao": "denso"}, "t")
    assert "VOCÊ decide" in TB.system_analise({"modelo": "teste_fil", "divisao": "auto"}, "t")
    assert TB.base_video({}) == "lapidado" and TB.base_video({"base": "notas"}) == "notas"


def test_fatiar_corta_em_frases_e_nao_perde_nada():
    tx = " ".join(f"Frase número {i} sobre o assunto." for i in range(600))
    fz = TB.fatiar(tx, 100)
    assert len(fz) > 10 and all(f.endswith(".") for f in fz)
    assert " ".join(fz).split() == tx.split()


def test_distribuir_sem_sobreposicao_e_lapidar(monkeypatch, tmp_path):
    _modelo(monkeypatch)
    import ia_servico as ia
    tx = " ".join(("Virtude e caráter na ética antiga." if i < 300 else "Revolução e história moderna.") for i in range(600))
    a = TB.criar(str(tmp_path), "Aula", "teste_fil", tx.encode(), "aula.txt")
    TB.mexer(str(tmp_path), a["id"], lambda x: x.update(temas=[
        {"id": "t1", "titulo": "A virtude e o caráter", "tema": "ética", "pontos": ["virtude"]},
        {"id": "t2", "titulo": "Revolução moderna", "tema": "história", "pontos": ["revolução"]}]))
    pedidos = []

    def falso(recurso, system, conteudo, schema=None, **k):
        pedidos.append((system, conteudo, schema))
        if schema:  # divisão: deixa o último trecho sem resposta (vai pelas palavras-chave)
            ids = [l.split("]")[0][2:] for l in conteudo.split("\n\n") if l.startswith("[C")]
            out = []
            for n in ids[:-1]:
                trecho = conteudo.split(f"[C{n}]")[1][:60]
                out.append({"c": f"C{n}", "video": "t1" if "Virtude" in trecho else "t2"})
            return {"fatias": out}
        return conteudo.split("\n\n", 1)[1]  # "lapida" devolvendo o mesmo texto
    monkeypatch.setattr(ia, "chamar", falso)
    r = TB.distribuir(str(tmp_path), a["id"], ["t1", "t2"])
    assert r["adivinhados"] == 1 and all(v in ("t1", "t2") for v in r["dono"].values())
    a = TB.carregar(str(tmp_path), a["id"])
    b1, b2 = TB.bruto_do_tema(a, "t1"), TB.bruto_do_tema(a, "t2")
    assert "Virtude" in b1 and "Revolução" in b2
    assert len(b1.split()) + len(b2.split()) == len(TB.texto(str(tmp_path), a["id"]).split())  # nada perdido nem repetido
    lap = TB.lapidar(str(tmp_path), a, a["temas"][0])
    assert "NÃO RESUMA" in pedidos[-1][0] and len(lap.split()) >= len(b1.split()) * 0.9


def test_lapidar_tenta_de_novo_quando_resume(monkeypatch):
    import ia_servico as ia
    a = {"fatias": {"trechos": ["palavra " * 300], "dono": {"C1": "t1"}}}
    t = {"id": "t1", "titulo": "T"}
    respostas = iter(["curto demais " * 20, "bom " * 250])
    chamadas = []
    monkeypatch.setattr(ia, "chamar", lambda *a_, **k: (chamadas.append(k.get("cache_local")), next(respostas))[1])
    assert TB.lapidar("", a, t).count("bom") == 250 and chamadas == [True, False]


def test_pedacos_quebra_material_grande():
    txt = "\n\n".join("p " * 1000 for _ in range(12))
    assert len(TB._pedacos(txt, 5000)) == 3


def test_palavra_gigante_usa_o_estilo_marcado_ou_o_do_canal(monkeypatch):
    import estilos_arte
    import ia_servico as ia
    import thumbs_flow as tf
    e = list(estilos_arte.ESTILOS)[0]
    pedidos = []
    monkeypatch.setattr(ia, "motivo_desligado", lambda r: "")
    monkeypatch.setattr(ia, "chamar", lambda r, system, *a, **k: (pedidos.append(system), {"thumbnails": [
        {"ideia": "x", "texto": "MEDO", "prompt": "a man", "modo": "albert", "titulos": ["a", "b"]}]})[1])
    out = tf.pedir_ideias("T", "c", [], 0, estilos=[e], albert=1)
    assert out[0]["estilo_arte"] == e and estilos_arte.ESTILOS[e]["nome"] in pedidos[-1]
    out = tf.pedir_ideias("T", "c", [], 0, estilos=[e], albert=1, estilo_albert="canal")
    assert not out[0].get("estilo_arte") and estilos_arte.ESTILOS[e]["nome"] not in pedidos[-1]
