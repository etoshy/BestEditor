"""v84_179 — 🔁 a mesma informação contada em dois lugares (o Shelton de 1987 no cap. 3 e no cap. 5) é achada pela frase;
a repetição logo em seguida não escapa mais quando só uma das frases tem o ano; 🎯 revisão no modo escopo; as partes não
saúdam de novo nem citam “episódios anteriores”."""
import checagem_roteiro as ch
import metodo_roteiro as mr
import revisao_roteiro as rv

TXT = ("Am 24. Februar 1987 entdeckte der kanadische Astronom Ian Shelton die Explosion auf einer Fotoplatte.\n\n"
       "Die Neutrinos kamen früher an.\n\nDann kam die Sonne dran.\n\nUnd Betelgeuse.\n\n"
       "Fast zweitausend Jahre später, am 24. Februar 1987, stand der kanadische Astronom Ian Shelton auf dem Cerro Las "
       "Campanas in den chilenischen Anden.")


def test_mesma_informacao_longe():
    r = ch.frases_repetidas(TXT)
    assert len(r) == 1 and r[0]["a"] == 1 and r[0]["b"] == 9
    linhas = ch.resumo_texto(ch.analisar(TXT, "Supernova"), TXT)
    assert any("MESMA INFORMAÇÃO DUAS VEZES" in x for x in linhas)
    assert not ch.frases_repetidas("Der Stern explodierte 1054 am Himmel über China.\n\nDer Stern explodierte 1572 am Himmel über Dänemark.")


def test_repeticao_ao_lado():
    t, tir = mr.tirar_repeticoes("Im Jahr 1604 sah Kepler eine weitere helle Supernova am Himmel. Kepler sah eine weitere helle Supernova am Himmel.")
    assert t == "Im Jahr 1604 sah Kepler eine weitere helle Supernova am Himmel." and len(tir) == 1
    t, tir = mr.tirar_repeticoes("Kepler beobachtete eine weitere helle Supernova am Himmel. Kepler beobachtete eine weitere "
                                 "helle Supernova am Himmel, und das bedeutete: Es war kein Zufall, sondern Gesetz.")
    assert t.startswith("Kepler beobachtete eine weitere helle Supernova am Himmel, und das") and len(tir) == 1  # fica a mais completa
    t, tir = mr.tirar_repeticoes("Im Jahr 1937 heiratete Anna den Bäcker Karl Huber in Wien. Im Jahr 1970 heiratete Anna den Bäcker Karl Huber in Wien.")
    assert not tir  # anos diferentes: outra informação


def test_revisao_escopo():
    assert "escopo" in rv.MODOS
    t = rv.prompt("Ein Stern. " * 300, "alemão", "Supernova", modo="escopo", titulo="Supernova: Wie ein Stern stirbt",
                  alvo_palavras=400, minutos=3)
    assert "MODO ESCOPO" in t and "eigenes Video" in t and "FIO CONDUTOR" not in t and "pra APAGAR o assunto vizinho" in t


def test_parte_nao_saluda_de_novo():
    import roteiro_partes as rp
    partes = [{"k": i, "titulo": f"K{i}", "palavras": 150, "objetivo": "", "fatos": [], "midias": []} for i in (1, 2, 3)]
    ctx = {"tema": "Supernova", "idioma": "alemão", "canal": "ASTRANEBEL", "minutos": 8}
    t2 = rp.prompt_parte(ctx, partes, 2)
    assert "CONTINUA o MESMO vídeo" in t2 and "O nome do canal NÃO aparece" in t2
    assert "CONTINUA o MESMO" not in rp.prompt_parte(ctx, partes, 1)
    assert "O nome do canal NÃO aparece" not in rp.prompt_parte(ctx, partes, 3)
