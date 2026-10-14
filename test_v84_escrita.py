"""v84_94 — ✍️ quadro "escrita" (mão / máquina de escrever / computador em vários papéis), fontes de escrita (com
acento composto quando a fonte não tem), legenda com o texto do roteiro e idioma "auto" dos calendários."""
import pytest

import dp_calendario as C
import dp_editorial as E
import dp_escrita as ES
import dp_sons
import fontes_escrita as FE
import legenda_texto as LT


# ------------------------------------------------------------------ legenda com o texto do roteiro
def _w(*itens):
    out, t = [], 0.0
    for p in itens:
        out.append({"word": p, "start": t, "end": t + 0.3})
        t += 0.4
    return [{"start": 0, "end": t, "text": " ".join(itens), "words": out}]


def test_legenda_usa_as_palavras_do_roteiro_nos_tempos_do_audio():
    segs = _w("O", "zequiel", "chegou", "em", "mil", "novecentos", "e", "quarenta", "e", "dois", "ninguém", "sabia")
    novos, info = LT.com_texto(segs, "[[INSCREVA: ]] O Ezequiel chegou em 1942. [risos] Ninguém sabia!")
    assert info["usou_texto"] and info["casadas"] >= 60
    ws = [w for s in novos for w in s["words"]]
    assert [w["word"] for w in ws] == ["O", "Ezequiel", "chegou", "em", "1942.", "Ninguém", "sabia!"]
    assert ws[1]["start"] == pytest.approx(0.4)  # "Ezequiel" no tempo de "zequiel"
    assert ws[4]["start"] == pytest.approx(1.6) and ws[4]["end"] <= 4.0 + 1e-6  # 1942 = "mil novecentos e quarenta e dois"
    assert all(a["start"] <= b["start"] for a, b in zip(ws, ws[1:]))
    assert len(novos) == 2 and novos[0]["text"].endswith("1942.")


def test_audio_de_outro_texto_fica_com_o_whisper():
    segs = _w("bom", "dia", "a", "todos")
    novos, info = LT.com_texto(segs, "texto completamente diferente aqui")
    assert not info["usou_texto"] and novos is segs


def test_estimar_sem_whisper():
    s = LT.estimar("Olá, mundo. Tudo bem com você?", 4.0)
    ws = [w for x in s for w in x["words"]]
    assert [w["word"] for w in ws] == ["Olá,", "mundo.", "Tudo", "bem", "com", "você?"]
    assert ws[0]["start"] >= 0.1 and ws[-1]["end"] <= 4.0 and len(s) == 2


# ------------------------------------------------------------------ fontes
def test_catalogo_de_fontes_livres():
    c = FE.catalogo()
    for fid in ("special-elite", "courier-prime", "1942-report", "moms-typewriter", "kalam", "marcador", "shareit"):
        assert fid in c and c[fid]["licenca"] == "livre"
    assert c["special-elite"]["tipo"] == "maquina" and c["kalam"]["tipo"] == "manuscrita"
    assert FE.escolhas()[0] == "auto" and FE.resolver("nao-existe", "maquina") == "special-elite"
    for f in c.values():
        if f["licenca"] == "pessoal":
            assert "pessoais" in f["arquivo"] and "uso pessoal" in f["nome"]


def test_acento_composto_quando_a_fonte_nao_tem():
    L = FE.letra("1942-report", 48, "maquina")  # a 1942 report não tem acentos
    assert not FE.tem(L.caminho, "ã") and FE.tem(L.caminho, "a")
    g_a, _x, _y = L.glifo("a", (0, 0, 0, 255))
    g_at, _x2, _y2 = L.glifo("ã", (0, 0, 0, 255))
    bb_a, bb_at = g_a.getbbox(), g_at.getbbox()
    assert bb_at[1] < bb_a[1] - 3  # o til ficou EM CIMA do "a"
    assert L.avanco("ã") == pytest.approx(L.avanco("a"))
    assert FE.tem(FE.letra("kalam", 48).caminho, "ç")


def test_quebrar_linhas():
    L = FE.letra("courier-prime", 30, "maquina")
    linhas = L.quebrar("um dois três quatro cinco seis sete oito\nnove", L.largura("um dois três "))
    assert linhas[-1] == "nove" and all(L.largura(l) <= L.largura("um dois três ") + 1 for l in linhas[:-1])


# ------------------------------------------------------------------ o quadro
def test_registrado_com_sons_e_rotulos():
    assert "escrita" in E.TIPOS and "escrita" in E._DESENHOS and len(E.TIPOS) == 20
    ed = E.para_editor()["escrita"]
    fonte = [c for c in ed["campos"] if c["k"] == "fonte"][0]
    assert fonte["rotulos"]["special-elite"].startswith("Special Elite")
    for sid in ES.SONS.values():
        assert dp_sons.som(sid), sid
    assert len(dp_sons.sons()) == 128


def test_cronograma_termina_antes_e_erro_de_digitacao_se_corrige():
    it = E.normalizar({"tipo": "escrita", "start": 0, "end": 7, "texto": "Primeira linha comprida\nsegunda", "modo": "computador",
                       "erros": "sim"})
    cr = ES.cronograma(it, 7.0)
    assert cr["fim"] < 7.0 * 0.85
    assert any(tp == "bs" for _t, tp, _c in cr["eventos"])
    final, _env, _f = ES._visivel(cr["eventos"], 99)
    assert final == "Primeira linha comprida\nsegunda"
    msg = dict(it, programa="mensagem", erros="nao")
    s, env, _f = ES._visivel(ES.cronograma(msg, 7.0)["eventos"], 99)
    assert env == 2 and s.split("\x00")[:2] == ["Primeira linha comprida", "segunda"]


VARIANTES = ([{"modo": "mao", "papel": p} for p in ES.PAPEIS] +
             [{"modo": "maquina", "papel": "antigo", "titulo": "Relatório", "destaque": "linha"},
              {"modo": "maquina", "fonte": "1942-report"}] +
             [{"modo": "computador", "programa": p, "destaque": "linha"} for p in ES.PROGRAMAS] +
             [{"modo": "mao", "papel": "carta", "titulo": "Querida", "data": "12/03/1942", "assinatura": "Helena", "destaque": "linha",
               "fonte": "shareit"}])


@pytest.mark.parametrize("v", VARIANTES)
def test_desenha_todas_as_combinacoes(v):
    it = E.normalizar(dict(v, tipo="escrita", start=0, end=6, texto="Uma linha com ação,\noutra linha."))
    assert it
    for W, H in ((640, 360), (360, 640)):
        ctx = E.novo_ctx()
        for t in (0.0, 0.8, 2.5, 4.2, 5.9):
            q = E.desenhar(it, t, W, H, ctx)
            assert q.size == (W, H) and q.mode == "RGBA"
        assert E.desenhar(it, 3.0, W, H, ctx).getchannel("A").getextrema()[1] == 255


def test_maquina_escreve_aos_poucos():
    it = E.normalizar({"tipo": "escrita", "start": 0, "end": 6, "texto": "Uma frase datilografada.", "modo": "maquina"})
    a = E.desenhar(it, 1.0, 640, 360, E.novo_ctx())
    b = E.desenhar(it, 5.0, 640, 360, E.novo_ctx())
    assert a.tobytes() != b.tobytes()


def test_sons_da_escrita():
    for v in ({"modo": "maquina", "texto": "linha um\nlinha dois"}, {"modo": "computador", "programa": "mensagem", "texto": "oi\ntudo bem?"},
              {"modo": "mao", "assinatura": "H", "destaque": "linha"}):
        it = E.normalizar(dict({"texto": "uma linha"}, **v, tipo="escrita", start=0, end=7))
        b = E.batidas(it)
        assert b and all(0 <= x[0] <= 7 for x in b) and all(dp_sons.som(x[1]) for x in b)
    b = E.batidas(E.normalizar({"tipo": "escrita", "start": 0, "end": 7, "texto": "linha um\nlinha dois", "modo": "maquina"}))
    assert any("ding" in x[1] for x in b) and any("retorno" in x[1] for x in b)


def test_miniatura(tmp_path):
    assert E.gerar_miniaturas(str(tmp_path), so=["escrita"], W=160, H=90) == 1


# ------------------------------------------------------------------ 📅 idioma do calendário
def test_idioma_auto_segue_o_video():
    it = E.exemplo("calendario_mes")
    assert it["idioma"] == "auto" and C.idioma_de(it) == "pt"
    assert C.idioma_de(E.normalizar(dict(it, _idioma_video="fr"))) == "fr"
    assert C.idioma_de(dict(it, idioma="de", _idioma_video="fr")) == "de"
    assert E.com_idioma_do_video([{"tipo": "folhinha"}], "it")[0]["_idioma_video"] == "it"
    assert C._txt_passo("dia", __import__("datetime").date(2026, 10, 14), "it")[2].startswith("mercoledì")
    for lang in ("pt", "en", "es", "fr", "it", "de"):
        q = E.desenhar(E.normalizar(dict(it, idioma=lang)), 5.0, 480, 270, E.novo_ctx())
        assert q.size == (480, 270)


def test_letra_a_mao_escolhida_nos_calendarios_e_na_lista():
    for t in ("calendario_mes", "calendario_ano", "folhinha", "lista_riscar"):
        assert any(c[0] == "letra" for c in E.TIPOS[t]["campos"])
    it = E.normalizar(dict(E.exemplo("lista_riscar"), letra="shareit"))
    assert it["letra"] == "shareit"
    a = E.desenhar(it, 6.0, 480, 270, E.novo_ctx())
    b = E.desenhar(E.exemplo("lista_riscar"), 6.0, 480, 270, E.novo_ctx())
    assert a.tobytes() != b.tobytes()
