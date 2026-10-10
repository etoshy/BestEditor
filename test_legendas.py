"""Testes de legendas.py -- os 3 modos de quebra de legenda (tempo,
legenda/ritmo, palavra) e a montagem do .srt final."""

import pytest

import legendas as lg


def _palavra(texto, inicio, fim):
    return {"word": texto, "start": inicio, "end": fim}


def _segmento_com_palavras(*palavras):
    """Monta um segmento no formato que whisper_transcribe.transcribe_audio
    devolve quando word_timestamps=True: {"start","end","text","words":[...]}."""
    return {
        "start": palavras[0]["start"],
        "end": palavras[-1]["end"],
        "text": " ".join(p["word"] for p in palavras),
        "words": list(palavras),
    }


class TestFormatoDeTempoSrt:
    def test_segundos_simples(self):
        assert lg._tempo_srt(1.5) == "00:00:01,500"

    def test_com_horas_minutos_e_milissegundos(self):
        # 1h01m01.234s
        assert lg._tempo_srt(3661.234) == "01:01:01,234"

    def test_nunca_fica_negativo(self):
        assert lg._tempo_srt(-2.0) == "00:00:00,000"

    def test_arredonda_milissegundos_corretamente(self):
        # 0.9995s deveria virar 1000ms -> 00:00:01,000, não 00:00:00,9995 truncado errado
        assert lg._tempo_srt(0.9995) == "00:00:01,000"


class TestAchatarPalavras:
    def test_junta_palavras_de_varios_segmentos_em_ordem(self):
        seg1 = _segmento_com_palavras(_palavra("Olá", 0.0, 0.3), _palavra("mundo.", 0.3, 0.8))
        seg2 = _segmento_com_palavras(_palavra("Segunda", 1.0, 1.4), _palavra("fala.", 1.4, 1.9))
        palavras = lg._achatar_palavras([seg1, seg2])
        assert [p["word"] for p in palavras] == ["Olá", "mundo.", "Segunda", "fala."]

    def test_ignora_palavra_vazia_apos_strip(self):
        seg = {"start": 0.0, "end": 1.0, "text": "x", "words": [
            {"word": "  ", "start": 0.0, "end": 0.1},
            {"word": "real", "start": 0.1, "end": 0.5},
        ]}
        palavras = lg._achatar_palavras([seg])
        assert [p["word"] for p in palavras] == ["real"]

    def test_segmento_sem_chave_words_nao_quebra(self):
        seg = {"start": 0.0, "end": 1.0, "text": "sem palavras"}
        assert lg._achatar_palavras([seg]) == []


class TestModoPalavra:
    def test_quebra_em_grupos_de_tamanho_fixo(self):
        palavras = [_palavra(str(i), i, i + 0.5) for i in range(7)]
        blocos = lg._modo_palavra(palavras, palavras_por_linha=3)
        assert [b["text"] for b in blocos] == ["0 1 2", "3 4 5", "6"]

    def test_timing_do_bloco_vai_do_inicio_da_primeira_ao_fim_da_ultima(self):
        palavras = [_palavra("a", 0.0, 0.2), _palavra("b", 0.3, 0.6), _palavra("c", 0.7, 1.0)]
        blocos = lg._modo_palavra(palavras, palavras_por_linha=3)
        assert blocos[0]["start"] == 0.0
        assert blocos[0]["end"] == 1.0

    def test_ignora_pausas_naturais_completamente(self):
        # gap enorme entre "a" e "b" (10s) -- modo palavra não liga, agrupa do mesmo jeito
        palavras = [_palavra("a", 0.0, 0.2), _palavra("b", 10.0, 10.3), _palavra("c", 10.4, 10.6)]
        blocos = lg._modo_palavra(palavras, palavras_por_linha=3)
        assert len(blocos) == 1
        assert blocos[0]["text"] == "a b c"

    def test_palavras_por_linha_minimo_1(self):
        palavras = [_palavra("a", 0.0, 0.2)]
        blocos = lg._modo_palavra(palavras, palavras_por_linha=0)  # valor inválido -> vira 1
        assert len(blocos) == 1


class TestModoLegenda:
    def test_quebra_na_pausa_natural_mesmo_abaixo_do_maximo(self):
        # limiar padrão é 0.35s; gap de 0.5s entre "mundo." e "Segunda" tem que quebrar ali
        palavras = [
            _palavra("Olá", 0.0, 0.3), _palavra("mundo.", 0.3, 0.8),
            _palavra("Segunda", 1.3, 1.7), _palavra("fala.", 1.7, 2.0),
        ]
        blocos = lg._modo_legenda(palavras, max_palavras=10)
        assert [b["text"] for b in blocos] == ["Olá mundo.", "Segunda fala."]

    def test_quebra_no_maximo_de_palavras_mesmo_sem_pausa(self):
        palavras = [_palavra(str(i), i * 0.2, i * 0.2 + 0.15) for i in range(5)]  # sem gaps
        blocos = lg._modo_legenda(palavras, max_palavras=2)
        assert [b["text"] for b in blocos] == ["0 1", "2 3", "4"]

    def test_sem_pausa_e_sem_atingir_maximo_fica_tudo_num_bloco_so(self):
        palavras = [_palavra(str(i), i * 0.2, i * 0.2 + 0.15) for i in range(4)]
        blocos = lg._modo_legenda(palavras, max_palavras=10)
        assert len(blocos) == 1

    def test_limiar_de_pausa_customizado(self):
        # gap de 0.2s -- não quebra com limiar padrão (0.35), mas quebra se o limiar for 0.1
        palavras = [_palavra("a", 0.0, 0.3), _palavra("b", 0.5, 0.8)]
        assert len(lg._modo_legenda(palavras, max_palavras=10, limiar_pausa=0.35)) == 1
        assert len(lg._modo_legenda(palavras, max_palavras=10, limiar_pausa=0.1)) == 2

    def test_pausa_exatamente_igual_ao_limiar_ja_quebra(self):
        # gap EXATAMENTE igual ao limiar (>=, não >) -- fronteira importa.
        # usa o mesmo valor computado (0.65-0.3) como limiar_pausa pra
        # garantir igualdade bit-a-bit e não cair em imprecisão de float.
        palavras = [_palavra("a", 0.0, 0.3), _palavra("b", 0.65, 0.9)]
        limiar = palavras[1]["start"] - palavras[0]["end"]
        blocos = lg._modo_legenda(palavras, max_palavras=10, limiar_pausa=limiar)
        assert len(blocos) == 2


class TestModoTempo:
    def test_fecha_bloco_ao_atingir_duracao_alvo(self):
        # cada palavra dura 1s; com alvo de 2.5s, o bloco fecha assim que
        # (fim_da_palavra - inicio_do_bloco) >= 2.5
        palavras = [_palavra(str(i), float(i), float(i) + 1.0) for i in range(6)]
        blocos = lg._modo_tempo(palavras, duracao_alvo=2.5)
        # bloco 1: palavras 0,1,2 (fim=3.0, 3.0-0.0=3.0>=2.5) -- fecha na 3ª
        assert blocos[0]["text"] == "0 1 2"
        assert blocos[0]["start"] == 0.0
        assert blocos[0]["end"] == 3.0

    def test_ultimo_bloco_incompleto_ainda_e_incluido(self):
        palavras = [_palavra(str(i), float(i), float(i) + 1.0) for i in range(2)]
        blocos = lg._modo_tempo(palavras, duracao_alvo=100.0)  # nunca atinge o alvo
        assert len(blocos) == 1
        assert blocos[0]["text"] == "0 1"

    def test_duracao_alvo_minima_de_meio_segundo(self):
        palavras = [_palavra("a", 0.0, 0.1)]
        blocos = lg._modo_tempo(palavras, duracao_alvo=0.0)  # valor inválido -> vira 0.5
        assert len(blocos) == 1  # não quebra em zero blocos nem trava

    def test_duracao_exatamente_igual_ao_alvo_ja_fecha_o_bloco(self):
        # fim - início EXATAMENTE igual ao alvo (>=, não >) -- fronteira importa
        palavras = [_palavra("a", 0.0, 2.5), _palavra("b", 2.6, 2.9)]
        blocos = lg._modo_tempo(palavras, duracao_alvo=2.5)
        assert len(blocos) == 2
        assert blocos[0]["text"] == "a"


class TestGerarSrt:
    def _segmentos_exemplo(self):
        return [
            _segmento_com_palavras(_palavra("Olá", 0.0, 0.3), _palavra("mundo.", 0.3, 0.8)),
            _segmento_com_palavras(_palavra("Segunda", 1.3, 1.7), _palavra("fala.", 1.7, 2.0)),
        ]

    def test_formato_geral_do_srt(self):
        srt = lg.gerar_srt(self._segmentos_exemplo(), modo="legenda", max_palavras=10)
        linhas = srt.split("\n")
        assert linhas[0] == "1"
        assert linhas[1] == "00:00:00,000 --> 00:00:00,800"
        assert linhas[2] == "Olá mundo."
        assert linhas[3] == ""
        assert linhas[4] == "2"

    def test_modo_tempo_funciona_pelo_gerar_srt(self):
        srt = lg.gerar_srt(self._segmentos_exemplo(), modo="tempo", duracao_alvo_s=0.5)
        assert "Olá" in srt and "Segunda" in srt

    def test_modo_palavra_funciona_pelo_gerar_srt(self):
        srt = lg.gerar_srt(self._segmentos_exemplo(), modo="palavra", palavras_por_linha=1)
        # 4 palavras ao todo, 1 por linha -> 4 blocos numerados até "4"
        assert "\n4\n" in srt or srt.strip().endswith("fala.")
        assert srt.count("-->") == 4

    def test_modo_desconhecido_da_erro(self):
        with pytest.raises(lg.LegendaError):
            lg.gerar_srt(self._segmentos_exemplo(), modo="nao_existe")

    def test_sem_palavras_da_erro(self):
        seg_sem_palavras = [{"start": 0.0, "end": 1.0, "text": "oi"}]  # sem "words"
        with pytest.raises(lg.LegendaError):
            lg.gerar_srt(seg_sem_palavras, modo="legenda")

    def test_lista_de_segmentos_vazia_da_erro(self):
        with pytest.raises(lg.LegendaError):
            lg.gerar_srt([], modo="legenda")


class TestParseSrt:
    def test_formato_padrao_com_numero_de_bloco(self):
        srt = (
            "1\n00:00:00,000 --> 00:00:03,500\nOlá mundo.\n\n"
            "2\n00:00:03,500 --> 00:00:07,200\nSegunda linha aqui.\n"
        )
        segmentos = lg.parse_srt(srt)
        assert len(segmentos) == 2
        assert segmentos[0] == {"start": 0.0, "end": 3.5, "text": "Olá mundo."}
        assert segmentos[1] == {"start": 3.5, "end": 7.2, "text": "Segunda linha aqui."}

    def test_sem_numero_de_bloco_tambem_funciona(self):
        srt = "00:00:00,000 --> 00:00:02,000\nSem número antes.\n"
        segmentos = lg.parse_srt(srt)
        assert segmentos == [{"start": 0.0, "end": 2.0, "text": "Sem número antes."}]

    def test_texto_em_varias_linhas_vira_uma_string_so(self):
        srt = "1\n00:00:00,000 --> 00:00:02,000\nPrimeira linha\nSegunda linha\n"
        segmentos = lg.parse_srt(srt)
        assert segmentos[0]["text"] == "Primeira linha Segunda linha"

    def test_ordena_por_start_mesmo_que_arquivo_venha_fora_de_ordem(self):
        srt = (
            "2\n00:00:05,000 --> 00:00:07,000\nSegundo bloco no tempo.\n\n"
            "1\n00:00:00,000 --> 00:00:02,000\nPrimeiro bloco no tempo.\n"
        )
        segmentos = lg.parse_srt(srt)
        assert [s["text"] for s in segmentos] == ["Primeiro bloco no tempo.", "Segundo bloco no tempo."]

    def test_descarta_bloco_so_com_tempo_sem_texto(self):
        srt = (
            "1\n00:00:00,000 --> 00:00:02,000\n\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\nEsse tem texto.\n"
        )
        segmentos = lg.parse_srt(srt)
        assert len(segmentos) == 1
        assert segmentos[0]["text"] == "Esse tem texto."

    def test_tolera_crlf_e_bom(self):
        srt = "\ufeff1\r\n00:00:00,000 --> 00:00:02,000\r\nCom BOM e CRLF.\r\n"
        segmentos = lg.parse_srt(srt)
        assert segmentos == [{"start": 0.0, "end": 2.0, "text": "Com BOM e CRLF."}]

    def test_conteudo_vazio_da_erro(self):
        with pytest.raises(lg.LegendaError):
            lg.parse_srt("")

    def test_conteudo_nenhum_bloco_valido_da_erro(self):
        with pytest.raises(lg.LegendaError):
            lg.parse_srt("isso não é um srt de jeito nenhum")

    def test_none_da_erro(self):
        with pytest.raises(lg.LegendaError):
            lg.parse_srt(None)

    def test_round_trip_gerar_e_reler_preserva_tempos_e_texto(self):
        segmentos_originais = [
            _segmento_com_palavras(_palavra("Olá", 0.0, 0.3), _palavra("mundo.", 0.3, 0.8)),
            _segmento_com_palavras(_palavra("Segunda", 1.3, 1.7), _palavra("fala.", 1.7, 2.0)),
        ]
        srt = lg.gerar_srt(segmentos_originais, modo="legenda", max_palavras=10)
        relido = lg.parse_srt(srt)
        assert len(relido) == 2
        assert relido[0]["start"] == 0.0
        assert relido[0]["end"] == 0.8
        assert relido[0]["text"] == "Olá mundo."
        assert relido[1]["start"] == 1.3
        assert relido[1]["end"] == 2.0
        assert relido[1]["text"] == "Segunda fala."
