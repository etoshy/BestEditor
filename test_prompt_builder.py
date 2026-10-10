"""
Teste offline de prompt_builder.py — geração do prompt e validação da
resposta colada da outra IA. Sem rede, sem dependências externas.
"""
from prompt_builder import PromptBuilderError, build_animepexels_prompt, build_buscadores_search_terms_prompt, build_prompt, build_wikipedia_search_terms_prompt, parse_ai_response, parse_wikipedia_search_terms_response
import json


def test_build_prompt_includes_transcript_and_instructions():
    segments = [
        {"start": 0.0, "end": 3.2, "text": "Bem-vindos ao vídeo de hoje sobre a natureza."},
        {"start": 3.2, "end": 7.5, "text": "Vamos explorar as montanhas ao amanhecer."},
        {"start": 7.5, "end": 12.0, "text": "E depois visitar uma cidade movimentada."},
    ]
    prompt = build_prompt(segments, interval_seconds=7, providers=["pexels", "pixabay", "mixkit"])
    assert "12.00 segundos" in prompt
    assert "pexels, pixabay, mixkit" in prompt
    assert "mixkit" in prompt and "categoria" in prompt.lower()
    print("OK: build_prompt inclui transcrição, duração total e instruções corretas.")


def test_parse_valid_response():
    resp = json.dumps([
        {"start": 0.0, "end": 6.8, "provider": "pexels", "query": "sunrise over mountains"},
        {"start": 6.8, "end": 12.0, "provider": "pixabay", "query": "busy city street"},
    ])
    result = parse_ai_response(resp, valid_providers=["pexels", "pixabay"], total_duration=12.0)
    segs = result.segments
    assert len(segs) == 2
    assert segs[0].provider == "pexels" and segs[0].duration == 6.8
    print("OK: resposta válida (formato legado, lista) é parseada corretamente.")


def test_parse_strips_markdown_code_fence():
    resp = "```json\n" + json.dumps([{"start": 0.0, "end": 12.0, "provider": "pexels", "query": "x"}]) + "\n```"
    result = parse_ai_response(resp, total_duration=12.0)
    assert len(result.segments) == 1
    print("OK: remove ```json automaticamente, sem exigir que o usuário limpe.")


def test_parse_new_envelope_format_with_soundtrack_suggestion():
    resp = json.dumps({
        "segments": [
            {"start": 0.0, "end": 6.8, "provider": "pexels", "query": "sunrise over mountains"},
            {"start": 6.8, "end": 12.0, "provider": "pixabay", "query": "busy city street", "on_screen_text": "3 passos"},
        ],
        "soundtrack_suggestion": "instrumental calmo e inspirador",
    })
    result = parse_ai_response(resp, total_duration=12.0)
    assert len(result.segments) == 2
    assert result.soundtrack_suggestion == "instrumental calmo e inspirador"
    assert result.segments[0].on_screen_text is None
    assert result.segments[1].on_screen_text == "3 passos"
    print("OK: formato novo (envelope com segments + soundtrack_suggestion) é parseado corretamente.")


def test_parse_envelope_without_soundtrack_suggestion_is_none():
    resp = json.dumps({"segments": [{"start": 0.0, "end": 12.0, "provider": "pexels", "query": "x"}]})
    result = parse_ai_response(resp, total_duration=12.0)
    assert result.soundtrack_suggestion is None
    print("OK: soundtrack_suggestion ausente vira None, sem quebrar.")


def test_parse_envelope_missing_segments_key_raises_clear_error():
    resp = json.dumps({"soundtrack_suggestion": "algo"})
    try:
        parse_ai_response(resp)
        raise AssertionError("deveria ter falhado")
    except PromptBuilderError as exc:
        assert "segments" in str(exc)
    print("OK: objeto sem a chave 'segments' gera erro claro.")


def test_on_screen_text_defaults_to_none_when_absent():
    resp = json.dumps([{"start": 0.0, "end": 12.0, "provider": "pexels", "query": "x"}])
    result = parse_ai_response(resp, total_duration=12.0)
    assert result.segments[0].on_screen_text is None
    print("OK: segmento sem on_screen_text não quebra, fica None.")


def test_media_type_image_accepted_with_supported_provider():
    resp = json.dumps({"segments": [{"start": 0.0, "end": 5.0, "provider": "pexels", "query": "vintage camera", "media_type": "image"}]})
    result = parse_ai_response(resp, total_duration=5.0)
    assert result.segments[0].media_type == "image"
    print("OK: media_type='image' com provider='pexels' é aceito.")


def test_media_type_image_rejected_with_unsupported_provider():
    resp = json.dumps({"segments": [{"start": 0.0, "end": 5.0, "provider": "pixabay", "query": "x", "media_type": "image"}]})
    try:
        parse_ai_response(resp, total_duration=5.0)
        raise AssertionError("deveria ter falhado")
    except PromptBuilderError:
        pass
    print("OK: media_type='image' com provedor sem suporte a fotos é rejeitado.")


def test_media_type_invalid_value_rejected():
    resp = json.dumps({"segments": [{"start": 0.0, "end": 5.0, "provider": "pexels", "query": "x", "media_type": "audio"}]})
    try:
        parse_ai_response(resp, total_duration=5.0)
        raise AssertionError("deveria ter falhado")
    except PromptBuilderError:
        pass
    print("OK: media_type com valor inválido é rejeitado.")


def test_media_type_defaults_to_video():
    resp = json.dumps({"segments": [{"start": 0.0, "end": 5.0, "provider": "pexels", "query": "x"}]})
    result = parse_ai_response(resp, total_duration=5.0)
    assert result.segments[0].media_type == "video"
    print("OK: sem media_type, o padrão continua sendo 'video' (retrocompatibilidade).")


def test_parse_rejects_invalid_json():
    try:
        parse_ai_response("isso não é json")
        raise AssertionError("deveria ter falhado")
    except PromptBuilderError:
        pass
    print("OK: JSON inválido gera erro claro.")


def test_parse_auto_repairs_unescaped_quotes_inside_string_value():
    """Bug real relatado: a IA às vezes escreve uma citação dentro de
    on_screen_text sem escapar as aspas internas (ex:
    `"on_screen_text": ""Ele se acha superior""`), quebrando o JSON.
    Corrige automaticamente, preservando as aspas como parte do texto."""
    raw_com_erro = (
        '{"segments": ['
        '{"start": 0.0, "end": 5.0, "provider": "pexels", "query": "x", "on_screen_text": "texto normal"},'
        '{"start": 5.0, "end": 10.0, "provider": "pexels", "query": "y", "on_screen_text": ""Ele se acha superior""}'
        ']}'
    )
    parsed = parse_ai_response(raw_com_erro, valid_providers=["pexels"], total_duration=10.0)
    assert parsed.segments[1].on_screen_text == '"Ele se acha superior"'
    print("OK: aspas duplicadas não-escapadas dentro de um valor são corrigidas automaticamente, preservando a citação.")


def test_parse_shows_context_snippet_when_repair_does_not_fix_it():
    """Quando a correção automática não resolve (JSON quebrado por
    outro motivo), o erro continua claro, agora com um trecho do JSON
    perto do problema pra facilitar achar o erro manualmente."""
    raw_quebrado = '{"segments": [{"start": 0.0, "end": 5.0, "provider": "pexels", "query": "x"'
    try:
        parse_ai_response(raw_quebrado)
        raise AssertionError("deveria ter falhado")
    except PromptBuilderError as e:
        assert "Trecho perto do erro" in str(e)
    print("OK: erro genuíno continua claro, com trecho de contexto do JSON.")


def test_parse_rejects_gap_between_segments():
    resp = json.dumps([
        {"start": 0.0, "end": 5.0, "provider": "pexels", "query": "x"},
        {"start": 6.0, "end": 10.0, "provider": "pexels", "query": "y"},
    ])
    try:
        parse_ai_response(resp)
        raise AssertionError("deveria ter falhado")
    except PromptBuilderError:
        pass
    print("OK: buraco entre segmentos é detectado.")


def test_parse_rejects_incomplete_coverage():
    resp = json.dumps([{"start": 0.0, "end": 5.0, "provider": "pexels", "query": "x"}])
    try:
        parse_ai_response(resp, total_duration=12.0)
        raise AssertionError("deveria ter falhado")
    except PromptBuilderError:
        pass
    print("OK: resposta que não cobre o áudio inteiro é detectada.")


def test_parse_rejects_invalid_provider():
    resp = json.dumps([{"start": 0.0, "end": 12.0, "provider": "youtube", "query": "x"}])
    try:
        parse_ai_response(resp, valid_providers=["pexels", "pixabay"])
        raise AssertionError("deveria ter falhado")
    except PromptBuilderError:
        pass
    print("OK: provedor fora da lista permitida é detectado.")


def test_parse_rejects_missing_field():
    resp = json.dumps([{"start": 0.0, "end": 12.0, "provider": "pexels"}])
    try:
        parse_ai_response(resp)
        raise AssertionError("deveria ter falhado")
    except PromptBuilderError:
        pass
    print("OK: campo obrigatório faltando é detectado.")


def test_parse_rejects_too_many_segments():
    resp = json.dumps([{"start": i * 0.5, "end": (i + 1) * 0.5, "provider": "pexels", "query": "x"} for i in range(600)])
    try:
        parse_ai_response(resp, max_segments=500)
        raise AssertionError("deveria ter falhado")
    except PromptBuilderError:
        pass
    print("OK: resposta com segmentos demais (acima do limite) é rejeitada antes de tentar buscar/baixar.")


def test_parse_rejects_segment_too_short():
    resp = json.dumps([{"start": 0.0, "end": 0.1, "provider": "pexels", "query": "x"}])
    try:
        parse_ai_response(resp, min_segment_duration=0.3)
        raise AssertionError("deveria ter falhado")
    except PromptBuilderError:
        pass
    print("OK: segmento mais curto que o mínimo permitido é rejeitado.")


def test_animepexels_note_absent_when_not_in_providers():
    segments = [{"start": 0.0, "end": 5.0, "text": "teste"}]
    prompt = build_prompt(segments, providers=["pexels", "pixabay"])
    assert "animepexels" not in prompt
    print("OK: sem animepexels na lista de provedores, o prompt não menciona ele.")


def test_animepexels_note_present_and_explains_usage_when_included():
    segments = [{"start": 0.0, "end": 5.0, "text": "teste"}]
    prompt = build_prompt(segments, providers=["pexels", "pixabay", "animepexels"])
    assert "animepexels" in prompt
    assert "acervo LOCAL de clipes de" in prompt
    assert "NUNCA escolha ele só porque" in prompt
    print("OK: com animepexels na lista, o prompt explica que é um banco de nicho e quando usar.")


def test_no_mention_of_unselected_specific_providers():
    """Regressão: as regras de "mixkit busca por categoria" e "pexels
    busca foto" apareciam no prompt MESMO quando esses bancos
    específicos não estavam selecionados — podendo confundir a IA a
    achar que estavam disponíveis. Também cobre a menção residual de
    "mixkit"/"magnific" dentro do texto genérico da regra principal.

    Nota: "media_type" não é mais exclusivo do Pexels — a regra de
    overlays (independente de provedor selecionado) também usa esse
    campo pra distinguir texto/imagem/vídeo, então não é mais um sinal
    válido de "pexels vazou pro prompt"."""
    segments = [{"start": 0.0, "end": 5.0, "text": "teste"}]
    prompt = build_prompt(segments, providers=["pixabay", "vistacreate"])
    assert "mixkit" not in prompt
    assert "magnific" not in prompt
    assert "animepexels" not in prompt
    print("OK: sem pexels/mixkit/magnific/animepexels selecionados, nenhuma menção específica deles aparece.")


def test_rule_numbering_stays_sequential_regardless_of_conditional_rules():
    """As regras condicionais (mixkit, magnific, pexels/foto,
    animepexels) não podem deixar buracos na numeração quando omitidas."""
    import re
    segments = [{"start": 0.0, "end": 5.0, "text": "teste"}]

    for providers in [["pexels"], ["mixkit"], ["pixabay", "vistacreate"],
                       ["pexels", "pixabay", "magnific", "mixkit", "vistacreate", "animepexels"]]:
        prompt = build_prompt(segments, providers=providers)
        numeros = [int(n) for n in re.findall(r"^(\d+)\. ", prompt, re.MULTILINE)]
        assert numeros == list(range(1, len(numeros) + 1)), f"numeração com buraco pra providers={providers}: {numeros}"
    print("OK: numeração das regras sempre sequencial, sem buracos, em qualquer combinação de provedores.")


def test_example_json_uses_actually_selected_providers():
    """O exemplo de JSON mostrado à IA usava sempre "pexels"/"pixabay"
    fixos — se nenhum dos dois estivesse selecionado, o próprio exemplo
    sugeriria bancos indisponíveis."""
    segments = [{"start": 0.0, "end": 5.0, "text": "teste"}]
    prompt = build_prompt(segments, providers=["magnific", "vistacreate"])
    assert '"provider": "magnific"' in prompt
    assert '"provider": "vistacreate"' in prompt
    print("OK: exemplo de JSON usa provedores de verdade da lista selecionada, não nomes fixos.")


def test_main_rule_explicitly_forbids_external_providers():
    segments = [{"start": 0.0, "end": 5.0, "text": "teste"}]
    prompt = build_prompt(segments, providers=["pexels"])
    assert "exclusivamente" in prompt
    assert any(name in prompt for name in ("Shutterstock", "Getty"))
    print("OK: regra principal reforça explicitamente que bancos fora da lista não podem ser usados.")


def test_animepexels_dedicated_prompt_covers_both_cases():
    """O prompt dedicado precisa orientar a IA a montar queries CONCRETAS
    e filmáveis (não conceitos abstratos soltos), mencionar nome de
    anime/personagem quando fizer sentido, e explicar os campos
    keyword_weight/semantic_weight."""
    segments = [{"start": 0.0, "end": 14.469, "text": "teste"}]
    prompt = build_animepexels_prompt(segments)
    assert "animepexels" in prompt
    assert "keyword_weight" in prompt and "semantic_weight" in prompt
    assert "Naruto" in prompt  # exemplo de anime especifico
    assert "CENA CONCRETA" in prompt  # orientacao central do prompt refinado
    print("OK: prompt dedicado do animepexels orienta pra queries concretas e explica os pesos.")


def test_animepexels_dedicated_prompt_example_json_is_valid():
    """O próprio exemplo de JSON mostrado no prompt dedicado precisa
    passar na validação real — sem isso, estaríamos ensinando a IA com
    um exemplo que o próprio site rejeitaria. Inclui keyword_weight/
    semantic_weight, os campos novos."""
    import json
    resposta_exemplo = json.dumps({
        "segments": [
            {"start": 0.0, "end": 4.2, "provider": "animepexels", "query": "ninja looking determined village"},
            {"start": 4.2, "end": 9.1, "provider": "animepexels", "query": "ninja training alone forest", "keyword_weight": 2, "semantic_weight": 0.5},
            {"start": 9.1, "end": 14.469, "provider": "animepexels", "query": "epic sword battle anime", "on_screen_text": "Batalhas épicas"},
        ],
        "soundtrack_suggestion": "instrumental épico e inspirador",
    })
    parsed = parse_ai_response(resposta_exemplo, total_duration=14.469, valid_providers=["animepexels"])
    assert len(parsed.segments) == 3
    assert parsed.segments[0].provider == "animepexels"
    assert parsed.segments[1].keyword_weight == 2.0
    assert parsed.segments[1].semantic_weight == 0.5
    assert parsed.segments[0].keyword_weight is None  # segmento sem os campos -- fica None, nao um default arbitrario
    print("OK: exemplo de JSON do prompt dedicado passa na validação real, com keyword_weight/semantic_weight.")


def test_animepexels_dedicated_prompt_rejects_empty_segments():
    try:
        build_animepexels_prompt([])
        raise AssertionError("deveria ter falhado")
    except PromptBuilderError:
        pass
    print("OK: lista vazia de segmentos dá erro claro no prompt dedicado, igual ao genérico.")


def test_keyword_weight_and_semantic_weight_optional_and_default_to_none():
    resp = json.dumps([{"start": 0.0, "end": 5.0, "provider": "animepexels", "query": "x"}])
    parsed = parse_ai_response(resp)
    assert parsed.segments[0].keyword_weight is None
    assert parsed.segments[0].semantic_weight is None
    print("OK: sem os campos, ficam None (não um valor arbitrário como 1.0).")


def test_keyword_weight_and_semantic_weight_parsed_when_present():
    resp = json.dumps([{"start": 0.0, "end": 5.0, "provider": "animepexels", "query": "x", "keyword_weight": 2, "semantic_weight": 0.5}])
    parsed = parse_ai_response(resp)
    assert parsed.segments[0].keyword_weight == 2.0
    assert parsed.segments[0].semantic_weight == 0.5
    print("OK: quando presentes, keyword_weight/semantic_weight são lidos e convertidos pra float corretamente.")


def test_keyword_weight_rejects_zero_or_negative():
    resp = json.dumps([{"start": 0.0, "end": 5.0, "provider": "animepexels", "query": "x", "keyword_weight": 0}])
    try:
        parse_ai_response(resp)
        raise AssertionError("deveria ter falhado")
    except PromptBuilderError as e:
        assert "keyword_weight" in str(e)
    print("OK: keyword_weight=0 é rejeitado com mensagem clara.")

    resp2 = json.dumps([{"start": 0.0, "end": 5.0, "provider": "animepexels", "query": "x", "semantic_weight": -1}])
    try:
        parse_ai_response(resp2)
        raise AssertionError("deveria ter falhado")
    except PromptBuilderError as e:
        assert "semantic_weight" in str(e)
    print("OK: semantic_weight negativo é rejeitado com mensagem clara.")


def test_keyword_weight_rejects_non_numeric():
    resp = json.dumps([{"start": 0.0, "end": 5.0, "provider": "animepexels", "query": "x", "keyword_weight": "muito"}])
    try:
        parse_ai_response(resp)
        raise AssertionError("deveria ter falhado")
    except PromptBuilderError as e:
        assert "keyword_weight" in str(e)
    print("OK: keyword_weight não-numérico é rejeitado com mensagem clara.")


def test_prompt_mentions_cutaway_suggestions():
    """Pedido do usuário: a IA sugerir pontos de CORTE REAL (não
    overlay — vídeo+áudio, com upload posterior) pra eventos reais
    (notícia, acontecimento) descritos na narração."""
    segments = [{"start": 0.0, "end": 50.0, "text": "teste"}]
    prompt = build_prompt(segments, providers=["pexels"])
    assert "cutaway_suggestions" in prompt
    assert "insertion_point" in prompt
    assert "audio_mode" in prompt
    print("OK: prompt genérico menciona cutaway_suggestions, insertion_point e audio_mode.")


def test_prompt_orients_clean_formatting_for_numeric_values():
    """Pedido do usuário: quando o momento importante for um valor
    numérico/financeiro, orientar a IA a formatar como destaque
    visual limpo (número + unidade), não a frase inteira da narração."""
    segments = [{"start": 0.0, "end": 10.0, "text": "teste"}]
    prompt = build_prompt(segments, providers=["pexels"])
    assert "VALOR NUMÉRICO" in prompt
    assert "R$ 1,78 milhão" in prompt
    print("OK: prompt orienta formatação limpa (número + unidade) pra valores numéricos/financeiros.")


def test_cutaway_suggestion_parsed_correctly():
    resp = json.dumps({
        "segments": [{"start": 0.0, "end": 50.0, "provider": "pexels", "query": "x"}],
        "cutaway_suggestions": [
            {"insertion_point": 45.2, "description": "Coletiva de imprensa real do prefeito", "audio_mode": "pause"},
        ],
    })
    parsed = parse_ai_response(resp, total_duration=50.0, valid_providers=["pexels"])
    assert len(parsed.cutaway_suggestions) == 1
    assert parsed.cutaway_suggestions[0]["insertion_point"] == 45.2
    assert parsed.cutaway_suggestions[0]["audio_mode"] == "pause"
    print("OK: corte sugerido pela IA é parseado corretamente.")


def test_cutaway_suggestion_defaults_to_none_when_absent():
    resp = json.dumps({"segments": [{"start": 0.0, "end": 5.0, "provider": "pexels", "query": "x"}]})
    parsed = parse_ai_response(resp)
    assert parsed.cutaway_suggestions == []
    print("OK: sem cutaway_suggestions no JSON, fica lista vazia.")


def test_cutaway_suggestion_rejects_empty_description():
    resp = json.dumps({
        "segments": [{"start": 0.0, "end": 5.0, "provider": "pexels", "query": "x"}],
        "cutaway_suggestions": [{"insertion_point": 2.0, "description": ""}],
    })
    try:
        parse_ai_response(resp)
        raise AssertionError("deveria ter falhado")
    except PromptBuilderError as e:
        assert "description" in str(e)
    print("OK: description vazio é rejeitado com mensagem clara.")


def test_cutaway_suggestion_rejects_invalid_audio_mode():
    resp = json.dumps({
        "segments": [{"start": 0.0, "end": 5.0, "provider": "pexels", "query": "x"}],
        "cutaway_suggestions": [{"insertion_point": 2.0, "description": "x", "audio_mode": "invalido"}],
    })
    try:
        parse_ai_response(resp)
        raise AssertionError("deveria ter falhado")
    except PromptBuilderError as e:
        assert "audio_mode" in str(e)
    print("OK: audio_mode inválido é rejeitado com mensagem clara.")


def test_cutaway_suggestion_rejects_insertion_point_beyond_duration():
    resp = json.dumps({
        "segments": [{"start": 0.0, "end": 5.0, "provider": "pexels", "query": "x"}],
        "cutaway_suggestions": [{"insertion_point": 99.0, "description": "x"}],
    })
    try:
        parse_ai_response(resp, total_duration=5.0)
        raise AssertionError("deveria ter falhado")
    except PromptBuilderError as e:
        assert "insertion_point" in str(e)
    print("OK: insertion_point além da duração do áudio é rejeitado com mensagem clara.")


def test_wikipedia_entidades_confirmadas_adds_rule_when_wikipedia_selected():
    segments = [{"start": 0.0, "end": 5.0, "text": "Albert Einstein nasceu na Alemanha."}]
    entidades = [
        {"termo": "Albert Einstein", "titulo_pagina": "Albert Einstein", "descricao": "físico alemão"},
        {"termo": "Alemanha", "titulo_pagina": "Alemanha", "descricao": ""},
    ]
    prompt = build_prompt(segments, providers=["pexels", "wikipedia"], wikipedia_entidades_confirmadas=entidades)
    assert "JÁ FOI PESQUISADO" in prompt
    assert '"Albert Einstein" (físico alemão)' in prompt
    assert '"Alemanha"' in prompt
    print("OK: entidades confirmadas da Wikipedia viram uma regra explícita no prompt.")


def test_wikipedia_entidades_confirmadas_absent_rule_when_wikipedia_not_selected():
    segments = [{"start": 0.0, "end": 5.0, "text": "Albert Einstein nasceu na Alemanha."}]
    entidades = [{"termo": "Albert Einstein", "descricao": "físico"}]
    prompt = build_prompt(segments, providers=["pexels"], wikipedia_entidades_confirmadas=entidades)
    assert "JÁ FOI PESQUISADO" not in prompt
    print("OK: entidades confirmadas são ignoradas se \"wikipedia\" não está nos providers selecionados.")


def test_wikipedia_entidades_confirmadas_absent_when_none_or_empty():
    segments = [{"start": 0.0, "end": 5.0, "text": "Texto qualquer aqui."}]
    prompt_sem_param = build_prompt(segments, providers=["pexels", "wikipedia"])
    prompt_lista_vazia = build_prompt(segments, providers=["pexels", "wikipedia"], wikipedia_entidades_confirmadas=[])
    assert "JÁ FOI PESQUISADO" not in prompt_sem_param
    assert "JÁ FOI PESQUISADO" not in prompt_lista_vazia
    print("OK: sem entidades confirmadas (None ou lista vazia), a regra extra não aparece.")


def test_wikipedia_entidades_confirmadas_ignora_itens_sem_termo():
    segments = [{"start": 0.0, "end": 5.0, "text": "Texto qualquer aqui."}]
    entidades = [{"termo": "", "descricao": "sem termo, deve ser ignorado"}]
    prompt = build_prompt(segments, providers=["pexels", "wikipedia"], wikipedia_entidades_confirmadas=entidades)
    assert "JÁ FOI PESQUISADO" not in prompt
    print("OK: item sem \"termo\" não gera a regra (lista efetivamente vazia).")


def test_buscadores_navegador_nota_geral_aparece_quando_selecionado():
    segments = [{"start": 0.0, "end": 5.0, "text": "Texto qualquer aqui."}]
    prompt = build_prompt(segments, providers=["pexels", "bing"])
    assert '"bing"' in prompt
    assert "buscadores de imagem de" in prompt
    print("OK: nota geral sobre buscadores de navegador aparece quando bing está nos providers.")


def test_buscadores_navegador_nota_geral_ausente_quando_nao_selecionado():
    segments = [{"start": 0.0, "end": 5.0, "text": "Texto qualquer aqui."}]
    prompt = build_prompt(segments, providers=["pexels"])
    assert "buscadores de imagem de" not in prompt
    print("OK: sem nenhum dos 4 buscadores nos providers, a nota geral não aparece.")


def test_buscadores_confirmados_adds_rule_when_algum_buscador_selecionado():
    segments = [{"start": 0.0, "end": 5.0, "text": "O Gojo Satoru é um personagem famoso."}]
    confirmados = [
        {"termo": "Gojo Satoru", "provider": "bing", "descricao": "personagem de anime"},
        {"termo": "Jujutsu Kaisen", "provider": "", "descricao": ""},
    ]
    prompt = build_prompt(segments, providers=["pexels", "bing"], buscadores_confirmados=confirmados)
    assert "CONFIRMADOS como tendo resultado de imagem disponível" in prompt
    assert '"Gojo Satoru" (via "bing": personagem de anime)' in prompt
    assert '"Jujutsu Kaisen"' in prompt
    print("OK: termos confirmados nos buscadores viram uma regra explícita no prompt.")


def test_buscadores_confirmados_absent_rule_when_nenhum_buscador_selecionado():
    segments = [{"start": 0.0, "end": 5.0, "text": "Texto qualquer aqui."}]
    confirmados = [{"termo": "Gojo Satoru", "provider": "bing", "descricao": "x"}]
    prompt = build_prompt(segments, providers=["pexels"], buscadores_confirmados=confirmados)
    assert "CONFIRMADOS como tendo resultado de imagem disponível" not in prompt
    print("OK: confirmados são ignorados se nenhum buscador de navegador está nos providers selecionados.")


def test_buscadores_confirmados_absent_when_none_or_empty():
    segments = [{"start": 0.0, "end": 5.0, "text": "Texto qualquer aqui."}]
    prompt_sem_param = build_prompt(segments, providers=["pexels", "brave"])
    prompt_lista_vazia = build_prompt(segments, providers=["pexels", "brave"], buscadores_confirmados=[])
    assert "CONFIRMADOS como tendo resultado de imagem disponível" not in prompt_sem_param
    assert "CONFIRMADOS como tendo resultado de imagem disponível" not in prompt_lista_vazia
    print("OK: sem confirmados (None ou lista vazia), a regra extra não aparece.")


def test_build_buscadores_search_terms_prompt_inclui_roteiro_e_formato_json():
    segments = [
        {"start": 0.0, "end": 5.0, "text": "O iPhone 15 Pro foi lançado esse ano."},
        {"start": 5.0, "end": 10.0, "text": "A Apple anunciou novidades."},
    ]
    prompt = build_buscadores_search_terms_prompt(segments)
    assert "O iPhone 15 Pro foi lançado esse ano." in prompt
    assert "A Apple anunciou novidades." in prompt
    assert '"termos"' in prompt
    assert "[00:00" in prompt and "[00:05" in prompt
    print("OK: prompt de busca de termos dos buscadores inclui roteiro e formato JSON esperado.")


def test_build_buscadores_search_terms_prompt_lista_vazia_de_segmentos_da_erro():
    try:
        build_buscadores_search_terms_prompt([])
        assert False, "deveria ter levantado PromptBuilderError"
    except PromptBuilderError:
        pass
    print("OK: lista de segmentos vazia levanta erro claro (buscadores).")


def test_build_wikipedia_search_terms_prompt_inclui_roteiro_e_formato_json():
    segments = [
        {"start": 0.0, "end": 5.0, "text": "Albert Einstein nasceu na Alemanha."},
        {"start": 5.0, "end": 10.0, "text": "Ele revolucionou a física."},
    ]
    prompt = build_wikipedia_search_terms_prompt(segments)
    assert "Albert Einstein nasceu na Alemanha." in prompt
    assert "Ele revolucionou a física." in prompt
    assert '"termos"' in prompt
    assert "[00:00" in prompt and "[00:05" in prompt
    print("OK: prompt de busca de termos wikipedia inclui roteiro e formato JSON esperado.")


def test_build_wikipedia_search_terms_prompt_lista_vazia_de_segmentos_da_erro():
    try:
        build_wikipedia_search_terms_prompt([])
        raise AssertionError("deveria ter levantado PromptBuilderError")
    except PromptBuilderError as e:
        assert "vazia" in str(e).lower()
    print("OK: lista de segmentos vazia dá erro claro.")


def test_parse_wikipedia_search_terms_response_formato_normal():
    termos = parse_wikipedia_search_terms_response('{"termos": ["Albert Einstein", "Torre Eiffel"]}')
    assert termos == ["Albert Einstein", "Torre Eiffel"]
    print("OK: parse do formato normal.")


def test_parse_wikipedia_search_terms_response_remove_duplicatas_case_insensitive():
    termos = parse_wikipedia_search_terms_response('{"termos": ["Einstein", "einstein", "EINSTEIN"]}')
    assert termos == ["Einstein"]
    print("OK: duplicatas (mesmo com maiúsculas diferentes) são removidas.")


def test_parse_wikipedia_search_terms_response_remove_cercas_markdown():
    termos = parse_wikipedia_search_terms_response('```json\n{"termos": ["Torre Eiffel"]}\n```')
    assert termos == ["Torre Eiffel"]
    print("OK: cercas de markdown (```json ... ```) são removidas.")


def test_parse_wikipedia_search_terms_response_aceita_lista_nua():
    termos = parse_wikipedia_search_terms_response('["A", "B"]')
    assert termos == ["A", "B"]
    print("OK: aceita uma lista JSON nua, sem o envelope {\"termos\": ...}.")


def test_parse_wikipedia_search_terms_response_lista_vazia_e_valida():
    termos = parse_wikipedia_search_terms_response('{"termos": []}')
    assert termos == []
    print("OK: lista vazia é uma resposta válida (roteiro sem entidades reais).")


def test_parse_wikipedia_search_terms_response_ignora_itens_nao_string():
    termos = parse_wikipedia_search_terms_response('{"termos": ["Válido", 123, null, "Outro"]}')
    assert termos == ["Válido", "Outro"]
    print("OK: itens que não são string na lista são ignorados, não quebram o parse.")


def test_parse_wikipedia_search_terms_response_json_invalido_da_erro_claro():
    try:
        parse_wikipedia_search_terms_response("isso não é json nenhum")
        raise AssertionError("deveria ter levantado PromptBuilderError")
    except PromptBuilderError as e:
        assert "JSON" in str(e)
    print("OK: JSON inválido dá erro claro, apontando o problema.")


def test_parse_wikipedia_search_terms_response_texto_vazio_da_erro():
    try:
        parse_wikipedia_search_terms_response("   ")
        raise AssertionError("deveria ter levantado PromptBuilderError")
    except PromptBuilderError as e:
        assert "vazia" in str(e).lower()
    print("OK: texto vazio colado dá erro claro.")


def test_parse_wikipedia_search_terms_response_sem_chave_termos_da_erro():
    try:
        parse_wikipedia_search_terms_response('{"outracoisa": ["X"]}')
        raise AssertionError("deveria ter levantado PromptBuilderError")
    except PromptBuilderError as e:
        assert "termos" in str(e)
    print("OK: JSON sem a chave \"termos\" dá erro claro.")


def test_parse_wikipedia_search_terms_response_termos_nao_e_lista_da_erro():
    try:
        parse_wikipedia_search_terms_response('{"termos": "Einstein"}')
        raise AssertionError("deveria ter levantado PromptBuilderError")
    except PromptBuilderError as e:
        assert "lista" in str(e).lower()
    print("OK: \"termos\" que não é uma lista dá erro claro.")


if __name__ == "__main__":
    test_build_prompt_includes_transcript_and_instructions()
    test_parse_valid_response()
    test_parse_strips_markdown_code_fence()
    test_parse_new_envelope_format_with_soundtrack_suggestion()
    test_parse_envelope_without_soundtrack_suggestion_is_none()
    test_parse_envelope_missing_segments_key_raises_clear_error()
    test_on_screen_text_defaults_to_none_when_absent()
    test_media_type_image_accepted_with_supported_provider()
    test_media_type_image_rejected_with_unsupported_provider()
    test_media_type_invalid_value_rejected()
    test_media_type_defaults_to_video()
    test_parse_rejects_invalid_json()
    test_parse_auto_repairs_unescaped_quotes_inside_string_value()
    test_parse_shows_context_snippet_when_repair_does_not_fix_it()
    test_parse_rejects_gap_between_segments()
    test_parse_rejects_incomplete_coverage()
    test_parse_rejects_invalid_provider()
    test_parse_rejects_missing_field()
    test_parse_rejects_too_many_segments()
    test_parse_rejects_segment_too_short()
    test_animepexels_note_absent_when_not_in_providers()
    test_animepexels_note_present_and_explains_usage_when_included()
    test_no_mention_of_unselected_specific_providers()
    test_rule_numbering_stays_sequential_regardless_of_conditional_rules()
    test_example_json_uses_actually_selected_providers()
    test_main_rule_explicitly_forbids_external_providers()
    test_animepexels_dedicated_prompt_covers_both_cases()
    test_animepexels_dedicated_prompt_example_json_is_valid()
    test_animepexels_dedicated_prompt_rejects_empty_segments()
    test_keyword_weight_and_semantic_weight_optional_and_default_to_none()
    test_keyword_weight_and_semantic_weight_parsed_when_present()
    test_keyword_weight_rejects_zero_or_negative()
    test_keyword_weight_rejects_non_numeric()
    test_prompt_mentions_cutaway_suggestions()
    test_prompt_orients_clean_formatting_for_numeric_values()
    test_cutaway_suggestion_parsed_correctly()
    test_cutaway_suggestion_defaults_to_none_when_absent()
    test_cutaway_suggestion_rejects_empty_description()
    test_cutaway_suggestion_rejects_invalid_audio_mode()
    test_cutaway_suggestion_rejects_insertion_point_beyond_duration()
    test_wikipedia_entidades_confirmadas_adds_rule_when_wikipedia_selected()
    test_wikipedia_entidades_confirmadas_absent_rule_when_wikipedia_not_selected()
    test_wikipedia_entidades_confirmadas_absent_when_none_or_empty()
    test_wikipedia_entidades_confirmadas_ignora_itens_sem_termo()
    test_build_wikipedia_search_terms_prompt_inclui_roteiro_e_formato_json()
    test_build_wikipedia_search_terms_prompt_lista_vazia_de_segmentos_da_erro()
    test_parse_wikipedia_search_terms_response_formato_normal()
    test_parse_wikipedia_search_terms_response_remove_duplicatas_case_insensitive()
    test_parse_wikipedia_search_terms_response_remove_cercas_markdown()
    test_parse_wikipedia_search_terms_response_aceita_lista_nua()
    test_parse_wikipedia_search_terms_response_lista_vazia_e_valida()
    test_parse_wikipedia_search_terms_response_ignora_itens_nao_string()
    test_parse_wikipedia_search_terms_response_json_invalido_da_erro_claro()
    test_parse_wikipedia_search_terms_response_texto_vazio_da_erro()
    test_parse_wikipedia_search_terms_response_sem_chave_termos_da_erro()
    test_parse_wikipedia_search_terms_response_termos_nao_e_lista_da_erro()
    print("\nTodos os testes de prompt_builder.py passaram.")
