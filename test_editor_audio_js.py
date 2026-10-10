"""
Testa a lógica PURA do editor de áudio por forma de onda
(templates/narracao_detalhe.html) -- as funções que não dependem de
DOM/canvas/Web Audio de verdade (`montarBufferEditado`,
`tempoPreviaParaTempoOriginal`, `audioBufferParaWavBlob`), rodando via
Node.js com um mock leve de AudioBuffer/AudioContext.createBuffer.

O resto do editor (arrastar handles, desenhar no canvas, tocar áudio de
verdade) precisa de um navegador de verdade (Selenium) pra testar —
essa suíte cobre a parte que DÁ pra testar sem isso: o cálculo de quais
trechos ficam/saem depois de um corte, e a codificação do WAV final.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node.js não disponível neste ambiente")

_TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "narracao_detalhe.html")


def _extrair_js_das_funcoes_puras():
    with open(_TEMPLATE_PATH, encoding="utf-8") as f:
        conteudo = f.read()
    inicio = conteudo.index("function audioBufferParaWavBlob")
    fim = conteudo.index("function abrirEditorAudio")
    return conteudo[inicio:fim]


def _rodar_script_node(corpo_js: str):
    """Roda um script Node.js com as funções puras do editor já
    carregadas, mais o `corpo_js` no final. Espera que o script termine
    com `console.log(JSON.stringify(resultado))` -- devolve o valor
    já decodificado."""
    funcoes = _extrair_js_das_funcoes_puras()
    script_completo = funcoes + "\n\n" + corpo_js
    resultado = subprocess.run(
        ["node", "-e", script_completo], capture_output=True, text=True, timeout=15,
    )
    if resultado.returncode != 0:
        raise AssertionError(f"script Node.js falhou:\n{resultado.stderr}")
    return json.loads(resultado.stdout.strip().splitlines()[-1])


class _FakeAudioBuffer:
    """Mock mínimo de AudioBuffer -- só o suficiente pra
    montarBufferEditado funcionar: canais de Float32Array simples."""


def _fake_audio_context_js():
    """Um `createBuffer` mínimo em JS puro, sem Web Audio real."""
    return """
    var fakeAudioContext = {
      createBuffer: function (numCanais, tamanho, sampleRate) {
        var canais = [];
        for (var i = 0; i < numCanais; i++) canais.push(new Float32Array(tamanho));
        return {
          numberOfChannels: numCanais,
          length: tamanho,
          sampleRate: sampleRate,
          getChannelData: function (c) { return canais[c]; },
        };
      },
    };
    """


def _buffer_original_js(amostras_por_segundo=10, duracao=10):
    """Um buffer "original" de teste: mono, `amostras_por_segundo`
    amostras por segundo (baixo de propósito, só pra facilitar
    verificar índice por índice), cada amostra vale o seu próprio
    índice (0, 1, 2, ...) -- assim dá pra conferir exatamente quais
    amostras sobreviveram ao corte."""
    total = amostras_por_segundo * duracao
    return f"""
    var bufferOriginal = (function () {{
      var dados = new Float32Array({total});
      for (var i = 0; i < {total}; i++) dados[i] = i;
      return {{
        numberOfChannels: 1,
        length: {total},
        sampleRate: {amostras_por_segundo},
        duration: {duracao},
        getChannelData: function (c) {{ return dados; }},
      }};
    }})();
    """


def test_montar_buffer_editado_sem_cortes_mantem_tudo():
    js = _fake_audio_context_js() + _buffer_original_js() + """
    var resultado = montarBufferEditado(fakeAudioContext, bufferOriginal, 0, 10, []);
    console.log(JSON.stringify({ length: resultado.length, primeira: resultado.getChannelData(0)[0], ultima: resultado.getChannelData(0)[resultado.length - 1] }));
    """
    r = _rodar_script_node(js)
    assert r["length"] == 100
    assert r["primeira"] == 0
    assert r["ultima"] == 99


def test_montar_buffer_editado_corta_inicio_e_fim():
    js = _fake_audio_context_js() + _buffer_original_js() + """
    var resultado = montarBufferEditado(fakeAudioContext, bufferOriginal, 2, 8, []);
    console.log(JSON.stringify({ length: resultado.length, primeira: resultado.getChannelData(0)[0], ultima: resultado.getChannelData(0)[resultado.length - 1] }));
    """
    r = _rodar_script_node(js)
    # de 2s a 8s, a 10 amostras/s -- amostras 20 a 79 (60 amostras)
    assert r["length"] == 60
    assert r["primeira"] == 20
    assert r["ultima"] == 79


def test_montar_buffer_editado_remove_trecho_do_meio():
    js = _fake_audio_context_js() + _buffer_original_js() + """
    // mantem 0-10s inteiro, mas remove o trecho de 3s a 5s do meio
    var resultado = montarBufferEditado(fakeAudioContext, bufferOriginal, 0, 10, [{ inicio: 3, fim: 5 }]);
    var dados = resultado.getChannelData(0);
    console.log(JSON.stringify({ length: resultado.length, amostras: Array.from(dados) }));
    """
    r = _rodar_script_node(js)
    # 100 amostras originais - 20 amostras removidas (3s-5s a 10/s) = 80
    assert r["length"] == 80
    amostras = r["amostras"]
    # as amostras 30..49 (o trecho de 3s-5s) NUNCA deveriam aparecer
    assert 30 not in amostras and 49 not in amostras
    # o que sobra e a concatenacao de [0..29] com [50..99], nessa ordem
    assert amostras[:30] == list(range(0, 30))
    assert amostras[30:] == list(range(50, 100))


def test_montar_buffer_editado_varios_cortes_fora_de_ordem():
    """Os cortes podem chegar fora de ordem (o usuário pode criar um
    corte no fim antes de um no começo) -- a função precisa ordenar
    sozinha antes de montar o resultado."""
    js = _fake_audio_context_js() + _buffer_original_js() + """
    var resultado = montarBufferEditado(fakeAudioContext, bufferOriginal, 0, 10,
      [{ inicio: 6, fim: 7 }, { inicio: 2, fim: 3 }]);
    var dados = resultado.getChannelData(0);
    console.log(JSON.stringify({ length: resultado.length, amostras: Array.from(dados) }));
    """
    r = _rodar_script_node(js)
    assert r["length"] == 80  # 100 - 10 - 10
    amostras = r["amostras"]
    assert amostras == list(range(0, 20)) + list(range(30, 60)) + list(range(70, 100))


def test_montar_buffer_editado_cortes_sobrepostos_nao_duplicam_nem_quebram():
    js = _fake_audio_context_js() + _buffer_original_js() + """
    var resultado = montarBufferEditado(fakeAudioContext, bufferOriginal, 0, 10,
      [{ inicio: 2, fim: 5 }, { inicio: 4, fim: 6 }]);  // sobrepostos -- 2-6 efetivamente
    var dados = resultado.getChannelData(0);
    console.log(JSON.stringify({ length: resultado.length, amostras: Array.from(dados) }));
    """
    r = _rodar_script_node(js)
    amostras = r["amostras"]
    assert amostras == list(range(0, 20)) + list(range(60, 100))


def test_montar_buffer_editado_corte_alem_das_bordas_e_limitado(tmp_path=None):
    """Um corte com uma ponta fora de [inicioSeg, fimSeg] (ex: um
    arrasto que passou da borda) é limitado pra dentro da área ativa,
    em vez de bagunçar a montagem."""
    js = _fake_audio_context_js() + _buffer_original_js() + """
    // area ativa e 2s-8s, mas o corte pede 0s-4s (passa da borda esquerda)
    var resultado = montarBufferEditado(fakeAudioContext, bufferOriginal, 2, 8, [{ inicio: 0, fim: 4 }]);
    var dados = resultado.getChannelData(0);
    console.log(JSON.stringify({ length: resultado.length, amostras: Array.from(dados) }));
    """
    r = _rodar_script_node(js)
    # area ativa: amostras 20-79 (60 amostras). corte efetivo: 2s-4s (limitado) -> amostras 20-39 removidas
    amostras = r["amostras"]
    assert amostras == list(range(40, 80))


def test_montar_buffer_editado_resultado_vazio_devolve_length_minimo_1():
    """Se o corte cobre TUDO, a função não deve quebrar (nem devolver
    um buffer de tamanho 0, que quebraria createBuffer de verdade) --
    o código JS usa Math.max(1, ...) de propósito."""
    js = _fake_audio_context_js() + _buffer_original_js() + """
    var resultado = montarBufferEditado(fakeAudioContext, bufferOriginal, 0, 10, [{ inicio: 0, fim: 10 }]);
    console.log(JSON.stringify({ length: resultado.length }));
    """
    r = _rodar_script_node(js)
    assert r["length"] == 1


def test_tempo_previa_para_tempo_original_sem_cortes():
    js = """
    var mantidos = [[0, 10]];
    console.log(JSON.stringify({
      inicio: tempoPreviaParaTempoOriginal(0, mantidos),
      meio: tempoPreviaParaTempoOriginal(5, mantidos),
      fim: tempoPreviaParaTempoOriginal(10, mantidos),
    }));
    """
    r = _rodar_script_node(js)
    assert r["inicio"] == 0
    assert r["meio"] == 5
    assert r["fim"] == 10


def test_tempo_previa_para_tempo_original_pula_trecho_cortado():
    """Com um corte no meio (removido 3s-5s de um audio de 10s), o
    tempo logo DEPOIS do fim do primeiro trecho mantido (na prévia)
    precisa corresponder ao início do PRÓXIMO trecho mantido no
    ORIGINAL (pulando o buraco do corte) -- é isso que faz a
    reprodução da prévia "pular" o trecho cortado."""
    js = """
    // original 0-10s, cortado 3-5s -- sobra [0,3] e [5,10]
    var mantidos = [[0, 3], [5, 10]];
    console.log(JSON.stringify({
      antes_do_corte: tempoPreviaParaTempoOriginal(1, mantidos),      // 1s na previa -- ainda no primeiro trecho
      exatamente_na_borda: tempoPreviaParaTempoOriginal(3, mantidos), // limite exato -- resolve no FIM do primeiro trecho (3s)
      logo_apos_a_borda: tempoPreviaParaTempoOriginal(3.01, mantidos),// passou da borda -- já é o INÍCIO do segundo trecho (~5s)
      dentro_do_segundo: tempoPreviaParaTempoOriginal(4, mantidos),   // 4s na previa = 1s dentro do segundo trecho = 6s no original
    }));
    """
    r = _rodar_script_node(js)
    assert r["antes_do_corte"] == 1
    assert r["exatamente_na_borda"] == 3
    assert abs(r["logo_apos_a_borda"] - 5.01) < 0.001
    assert r["dentro_do_segundo"] == 6


def test_tempo_previa_para_tempo_original_lista_vazia_devolve_zero():
    js = """
    console.log(JSON.stringify({ resultado: tempoPreviaParaTempoOriginal(5, []) }));
    """
    r = _rodar_script_node(js)
    assert r["resultado"] == 0


def test_audio_buffer_para_wav_blob_gera_cabecalho_riff_valido():
    js = _fake_audio_context_js() + """
    var buffer = fakeAudioContext.createBuffer(1, 4, 8000);
    var dados = buffer.getChannelData(0);
    dados[0] = 0; dados[1] = 0.5; dados[2] = -0.5; dados[3] = 1.0;
    var blob = audioBufferParaWavBlob(buffer);
    blob.arrayBuffer().then(function (ab) {
      var bytes = new Uint8Array(ab);
      var view = new DataView(ab);
      var riff = String.fromCharCode(bytes[0], bytes[1], bytes[2], bytes[3]);
      var wave = String.fromCharCode(bytes[8], bytes[9], bytes[10], bytes[11]);
      console.log(JSON.stringify({
        riff: riff, wave: wave,
        tamanhoTotal: ab.byteLength,
        sampleRate: view.getUint32(24, true),
        numCanais: view.getUint16(22, true),
        bitsPorAmostra: view.getUint16(34, true),
        // primeira amostra (0.0 -> int16 0)
        amostra0: view.getInt16(44, true),
        // segunda amostra (0.5 -> perto de 0.5*32767 = 16383)
        amostra1: view.getInt16(46, true),
      }));
    });
    """
    r = _rodar_script_node(js)
    assert r["riff"] == "RIFF"
    assert r["wave"] == "WAVE"
    assert r["sampleRate"] == 8000
    assert r["numCanais"] == 1
    assert r["bitsPorAmostra"] == 16
    assert r["tamanhoTotal"] == 44 + 4 * 2  # cabecalho de 44 bytes + 4 amostras de 16-bit
    assert r["amostra0"] == 0
    assert abs(r["amostra1"] - 16383) <= 1


def test_audio_buffer_para_wav_blob_limita_amostras_fora_da_faixa():
    """Amostras fora de [-1, 1] (podem acontecer depois de algum
    processamento) são limitadas (clamp), em vez de estourar o int16 e
    virar ruído digital."""
    js = _fake_audio_context_js() + """
    var buffer = fakeAudioContext.createBuffer(1, 2, 8000);
    var dados = buffer.getChannelData(0);
    dados[0] = 5.0;   // bem acima de 1.0
    dados[1] = -5.0;  // bem abaixo de -1.0
    var blob = audioBufferParaWavBlob(buffer);
    blob.arrayBuffer().then(function (ab) {
      var view = new DataView(ab);
      console.log(JSON.stringify({
        maxima: view.getInt16(44, true),
        minima: view.getInt16(46, true),
      }));
    });
    """
    r = _rodar_script_node(js)
    assert r["maxima"] == 0x7fff  # limitado no máximo positivo de int16
    assert r["minima"] == -0x8000  # limitado no máximo negativo de int16
