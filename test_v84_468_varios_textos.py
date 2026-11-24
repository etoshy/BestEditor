import temas_bruto as TB

AULA1 = ("A autossabotagem aparece quando o medo do sucesso fala mais alto que o desejo. " * 40)
AULA2 = ("A procrastinação é uma forma de regular emoções desagradáveis, não preguiça. " * 40)


def test_varios_textos_e_tempo(tmp_path):
    a = TB.criar(str(tmp_path), "Curso", "raciocinio_maldito", AULA1.encode(), "aula1.txt", "tempo",
                 extras=[(AULA2.encode(), "aula2.srt")], minutos_alvo_="12")
    assert a["textos"] == 2 and a["minutos_alvo"] == 12 and a["divisao"] == "tempo"
    tx = TB.texto(str(tmp_path), a["id"])
    assert "=== TEXTO 1 de 2: aula1 ===" in tx and "=== TEXTO 2 de 2: aula2 ===" in tx
    sys_ = TB.system_analise(a, tx)
    assert "2 TEXTOS" in sys_ and "~12 minutos" in sys_ and "entre 10 e 14" in sys_
    temas = TB.ler_temas({"temas": [{"titulo": "Por que você se sabota", "minutos": 30, "forca": 8}]}, a["modelo"], a)
    assert temas[0]["minutos"] == 12  # o tamanho escolhido manda
    assert TB.faixa_palavras(a) == (1620, 1980)


def test_um_video_so(tmp_path):
    a = TB.criar(str(tmp_path), "Tudo", "raciocinio_maldito", AULA1.encode(), "a.txt", "um")
    assert TB.DIVISOES[TB.divisao(a)]["faixa"] == (1, 1)
    s = TB.system_analise(a, "texto")
    assert "UM tema só" in s and "pode passar de 30 min" in s
    t = TB.ler_temas({"temas": [{"titulo": "Tudo", "minutos": 75}]}, a["modelo"], a)
    assert t[0]["minutos"] == 75  # sem o teto de 60 no vídeo único


def test_rota_varios_arquivos(monkeypatch):
    import io
    import app as A
    import ia_servico as ia
    A.app.config["TESTING"] = True
    monkeypatch.setattr(ia, "motivo_desligado", lambda r=None, c=None: "desligada no teste")
    c = A.app.test_client()
    r = c.post("/temas-bruto/novo", data={"modelo": "raciocinio_maldito", "divisao": "tempo", "minutos_alvo": "15",
                                          "arquivo": [(io.BytesIO(AULA1.encode()), "a1.txt"), (io.BytesIO(AULA2.encode()), "a2.txt")]},
               content_type="multipart/form-data")
    aid = r.headers["Location"].rsplit("/", 1)[-1]
    a = TB.carregar(A.BASE_DIR, aid)
    assert a["textos"] == 2 and a["minutos_alvo"] == 15 and "🧩 2 textos" in c.get(f"/temas-bruto/{aid}").get_data(as_text=True)
    TB.excluir(A.BASE_DIR, aid)
