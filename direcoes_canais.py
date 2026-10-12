"""
direcoes_canais.py
==================

🎬 Direções de edição tiradas de canais de referência. Cada uma foi montada
analisando um vídeo do canal (cortes, quadros, textos na tela, áudio) e
traduzida para o que o site já tem: filtros, movimentos, overlays,
transições, entradas, destaques e quadros editoriais.

Entram junto com as direções do sistema (dp_direcao.sistema()).
Copia-se o ESTILO, nunca a identidade do canal: sem logo, vinheta, nome
ou bordões do criador.
"""
from __future__ import annotations

from typing import Any, Dict, List

# ------------------------------------------------------------------ Mistere
# Análise (vídeo "Mistérios e Rabbit Holes Bizarros da Internet", 30 min, 1280×720):
# - 480 cortes em 30 min: plano médio 3,8 s, mediana 2,6 s; 58% dos planos ≤ 3 s, quase nenhum > 12 s.
# - Imagem: banco de vídeo "cinematográfico" + fotos de arquivo, sempre com VINHETA forte e cor
#   levemente dessaturada/fria; trechos históricos em P&B com grão e riscos de película.
# - Transição: quase tudo corte seco; nas viradas, ESTÁTICA de TV, barras de cor (SMPTE) e glitch RGB
#   por poucos quadros; às vezes um corte rápido pro preto.
# - Texto na tela: números e anos ENORMES em letra condensada branca (às vezes vermelha), nomes de
#   lugar sobre o vídeo, palavras-chave em máquina de escrever branca sobre fundo preto, título de cada
#   caso em serifada clássica (tipo Trajan) sobre imagem escura.
# - Fotos de pessoas reais em papel/polaroid sobre fundo preto, com tarja preta nos olhos.
# - Infográfico simples: silhuetas brancas (ex.: urso 2,7 m × pessoa 1,7 m) sobre preto.
# - Sem legenda queimada. Narração contínua, trilha de suspense baixa, "whoosh"/estática nas viradas.
# + 2 vídeos a mais (v84_62): "A CIA encontrou um fantasma no Brasil" (33 min, 573 planos, mediana 2,75 s) e
#   "Tutorial de como deixar alguém esquizofrênico" (34 min, 722 planos, mediana 1,96 s). Confirmaram o de cima e
#   mostraram: páginas de DOCUMENTO desclassificado em tela cheia (zoom lento, vinheta, título serifado por cima),
#   depoimento datilografado em papel, NOMES das pessoas em letra condensada gigante sobre a imagem, capítulos
#   numerados (algarismo romano / "Parte 2") entre BARRAS DE COR, arquivo P&B com vazamento de luz laranja e
#   moldura de película, e um "DÁ LIKE" com glitch logo depois da vinheta.
MISTERE: Dict[str, Any] = {
    "id": "sys_mistere",
    "nome": "Rabbit hole sombrio (estilo Mistere)",
    "descricao": "Mistérios, arquivos secretos e casos bizarros: cortes rápidos (~2–3 s), vinheta forte, cor fria, "
                 "estática/glitch de TV nas viradas, documentos em tela cheia, números e nomes gigantes, máquina de escrever.",
    "sistema": True,
    "v": 3,
    "intensidade": None,
    "conjuntos": {},
    "ritmo": "dinamico",
    "marca": None,
    "universo": "predef",
    "cores": {"ativa": True, "modo": "predef", "primaria": "#F2F2F2", "secundaria": "#9A9A9A", "acento": "#D7262E"},
    # cor do vídeo inteiro: frio/dessaturado de suspense; arquivo P&B e película nos trechos antigos
    "filtros": {"pct": 85, "itens": [
        {"id": "frio_true_crime", "peso": 4}, {"id": "thriller", "peso": 3}, {"id": "preto_frio", "peso": 2},
        {"id": "documentary", "peso": 2}, {"id": "old_film", "peso": 1}, {"id": "bw", "peso": 1}]},
    # câmera quase sempre andando devagar; vinheta e grão por cima (no JSON do sistema overlays vão em "efeitos")
    "efeitos": {"pct": 60, "itens": [
        {"id": "zoom_respiro", "peso": 4}, {"id": "zoom_in", "peso": 3}, {"id": "ken_burns_doc", "peso": 3},
        {"id": "pan_dir", "peso": 1}, {"id": "zoom_rapido", "peso": 1}, {"id": "travelling_arquivo", "peso": 1},
        # nos vídeos entra um overlay: quase sempre vinheta; grão/VHS/glitch RGB de vez em quando
        {"id": "vinheta_suspense", "peso": 4}, {"id": "grao_16mm", "peso": 1}, {"id": "vhs_desalinhado", "peso": 1},
        {"id": "mr_robot_scanlines", "peso": 1}, {"id": "pelicula_suja_arquivo", "peso": 1},
        {"id": "they_shall_manivela", "peso": 1},
        # da fábrica (valem mesmo sem o pacote de extras)
        {"id": "ov_vinheta_pulso", "peso": 3}, {"id": "ov_sujeira", "peso": 1}, {"id": "ov_scanlines", "peso": 1},
        {"id": "chroma", "peso": 1}]},
    # corte seco na maioria; estática/glitch de TV nas viradas
    "transicoes": {"pct": 22, "itens": [
        {"id": "gl_oss_tvstatic", "peso": 4}, {"id": "gl_glitch", "peso": 3}, {"id": "gl_oss_staticfade", "peso": 2},
        {"id": "chernobyl_ruido", "peso": 2}, {"id": "black_mirror_tela_falha", "peso": 2},
        {"id": "gl_oss_oldtvlostsignal", "peso": 2}, {"id": "glitch_mr_robot", "peso": 1},
        {"id": "caes_corte_preto_rapido", "peso": 2}, {"id": "noise_dissolve", "peso": 1},
        {"id": "gl_oss_glitchdisplace", "peso": 1}, {"id": "gl_oss_staticwipe", "peso": 1}, {"id": "ft_pk_glitch", "peso": 1},
        # trechos de arquivo: vazamento de luz laranja e queima de película
        {"id": "ft_pk_leak1", "peso": 1}, {"id": "ft_pk_leak3", "peso": 1}, {"id": "film_burn", "peso": 1}]},
    "entradas": {"pct": 12, "itens": [
        {"id": "tv_on", "peso": 2}, {"id": "mr_robot_falha", "peso": 2}, {"id": "foto_cai_mesa", "peso": 2},
        {"id": "foto_arquivo_lenta", "peso": 2}, {"id": "punch_in", "peso": 1}, {"id": "flash", "peso": 1}]},
    "saidas": {"pct": 0, "itens": []},
    # ficha/foto de arquivo, citação ("abre aspas… fecha aspas") e comparação (infográfico de silhuetas)
    "templates": {"pct": 6, "itens": [
        {"id": "ED_FICHA_ARQUIVO", "peso": 2}, {"id": "ED_CITACAO", "peso": 2}, {"id": "ED_COMPARACAO", "peso": 1},
        {"id": "ED_PERFIL", "peso": 1}]},
    "templatesAvatar": {"pct": 0, "itens": []},
    "overlays": {"pct": 0, "itens": [], "maxPorCena": 1},
    "pares": {"modo": "livre", "itens": []},
    "legenda": None,  # o canal não usa legenda queimada
    "destaques": {"ativo": True, "densidade": "dinamico", "estilos": [
        "estat", "impacto_red", "branco", "sugar_man_nome", "v2_maquina", "dossie_maquina_escrever",
        "twin_peaks_titulo", "glitch", "selo_ano", "arquivo", "trainspotting_nome", "carimbo_confidencial",
        "true_crime_linha_tempo", "se7en_creditos", "capitulo"]},
    "editoriais": {"ativo": True, "densidade": "equilibrado",
                   "tipos": ["pagina", "numero", "titulo_video", "nome", "ficha", "recortes", "linha_tempo", "reescrita"]},
    "som_transicoes": "auto",
    "referencia": {"canal": "Mistere", "url": "https://www.youtube.com/@Misterecore",
                   "videos_analisados": 3, "plano_mediana_s": [2.6, 2.75, 1.96]},
}

# ------------------------------------------------------------------ Dossiê de papel (v84_65)
# Vídeos de IA de true crime em capítulos ("O Caso de Idaho"): tudo é colagem de papel — fotos P&B recortadas,
# jornal e relatório policial ao fundo, linha vermelha, alfinetes, etiquetas de papel rasgado; cor sépia/creme com
# vermelho; nada de glitch. Cada cena fica ~4 s com a câmera chegando devagar; as peças entram deslizando e
# assentando; viradas como página/recorte. Sem legenda queimada nos shorts originais (aqui fica a "caixa", que
# combina com o papel). Usada pelos estilos de 🎞️ Vídeos modelados "Dossiê em colagem" e "Arquivo na mesa".
DOSSIE_PAPEL: Dict[str, Any] = {
    "id": "sys_dossie_papel",
    "nome": "Dossiê de papel (colagem true crime)",
    "descricao": "Colagem de papel envelhecido: cor sépia/creme com vermelho, câmera chegando devagar, peças que deslizam "
                 "e assentam, viradas de página, etiquetas de papel rasgado e máquina de escrever.",
    "sistema": True, "v": 3, "intensidade": None, "conjuntos": {}, "ritmo": "equilibrado", "marca": None, "universo": "predef",
    "cores": {"ativa": True, "modo": "predef", "primaria": "#F3E9D2", "secundaria": "#2B2B2B", "acento": "#B3261E"},
    "filtros": {"pct": 70, "itens": [{"id": "vintage", "peso": 3}, {"id": "sepia", "peso": 1}, {"id": "documentary", "peso": 2},
                                     {"id": "matte", "peso": 1}]},
    "efeitos": {"pct": 75, "itens": [
        {"id": "zoom_respiro", "peso": 4}, {"id": "zoom_in", "peso": 3}, {"id": "ken_burns_carta", "peso": 2},
        {"id": "pan_baixo", "peso": 1}, {"id": "zoom_pan_dir", "peso": 1},
        {"id": "ov_poeira", "peso": 2}, {"id": "ov_sujeira", "peso": 1}, {"id": "pelicula_suja_arquivo", "peso": 1}]},
    "transicoes": {"pct": 35, "itens": [
        {"id": "book_flip", "peso": 3}, {"id": "coverleft", "peso": 2}, {"id": "coverup", "peso": 2},
        {"id": "dp_shutter_dossie", "peso": 2}, {"id": "slideleft", "peso": 1}, {"id": "wipeleft", "peso": 1}]},
    "entradas": {"pct": 25, "itens": [
        {"id": "recorte_cai", "peso": 3}, {"id": "documento_desliza", "peso": 3}, {"id": "foto_cai_mesa", "peso": 2},
        {"id": "revela_documento", "peso": 2}, {"id": "assenta", "peso": 1}, {"id": "slide_left", "peso": 1}]},
    "saidas": {"pct": 0, "itens": []},
    "templates": {"pct": 8, "itens": [{"id": "ED_FICHA_ARQUIVO", "peso": 2}, {"id": "ED_ARTIGO", "peso": 2},
                                      {"id": "ED_MOSAICO", "peso": 1}, {"id": "C30_PAPEL_DESDOBRA", "peso": 1}]},
    "templatesAvatar": {"pct": 0, "itens": []},
    "overlays": {"pct": 0, "itens": [], "maxPorCena": 1},
    "pares": {"modo": "livre", "itens": []},
    "legenda": None,
    "destaques": {"ativo": True, "densidade": "equilibrado", "estilos": [
        "recorte", "v2_recorte_jornal", "carimbo", "carimbo_confidencial", "v2_maquina", "dossie_maquina_escrever",
        "true_crime_linha_tempo", "capitulo", "ed_selo_capitulo", "recorte_jornal_vox"]},
    "editoriais": {"ativo": True, "densidade": "dinamico",
                   "tipos": ["recortes", "pagina", "ficha", "mural", "bilhetes", "linha_tempo", "numero", "nome"]},
    "som_transicoes": "auto",
    "referencia": {"canal": "true crime em colagem (vídeos de IA)", "videos_analisados": 5},
}

# ------------------------------------------------------------------ Dallas (v84_66)
# 3 vídeos ("BONES", "CAPPERS", "EXPONDO a líder de um culto"), 12–16 min, 1920×804 (proporção de CINEMA 2,39:1),
# 160–194 planos por vídeo (mediana 3–5 s), narração ~170 palavras/min. Visual: notícia, entrevista, foto de arquivo,
# print de site/rede social e reconstituições em 3D/IA, quase sem filtro de cor; a cara do canal é o TEXTO:
#   • frase-chave da narração em letra de TERMINAL (mono, caixa alta) numa TARJA PRETA por cima do vídeo;
#   • cartela de terminal branca no PRETO pras viradas ("OU...", "PARTE MAIS BIZARRA DISSO TUDO?");
#   • cartela vermelha de NÍVEL ("NÍVEL 1 — SUBMUNDO DO CRIME");
#   • palavra/número enorme em letra condensada por cima da imagem ("SÉCULO 19", "CALCUTA", "5 MILHÕES");
#   • foto solta flutuando sobre fundo desfocado com partículas; documento com a frase grifada;
#   • palavras sensíveis escritas com símbolos na tela (4$$4$1N4D0, S#XUA!S) e rosto/nudez pixelado (🙈 censura).
# Transição: corte seco quase sempre; corte rápido pro preto antes da cartela; um glitch de vez em quando.
DALLAS: Dict[str, Any] = {
    "id": "sys_dallas",
    "nome": "Exposição da internet (estilo Dallas)",
    "descricao": "Quadro de cinema 2,39 com faixas pretas, frase da narração em tarja preta com letra de terminal, cartelas "
                 "brancas no preto, cartela vermelha de NÍVEL, foto flutuando com partículas, corte seco.",
    "sistema": True, "v": 3, "intensidade": None, "conjuntos": {}, "ritmo": "equilibrado", "marca": None, "universo": "predef",
    "cores": {"ativa": True, "modo": "predef", "primaria": "#FFFFFF", "secundaria": "#0B0B0B", "acento": "#A3121B"},
    # o "filtro" aqui é o quadro de cinema (faixas pretas); sem o pacote de extras, fica o cinematic sem faixas
    "filtros": {"pct": 100, "itens": [{"id": "cinemascope_dallas", "peso": 6}, {"id": "cinematic", "peso": 1}]},
    "efeitos": {"pct": 55, "itens": [
        {"id": "zoom_respiro", "peso": 4}, {"id": "zoom_in", "peso": 2}, {"id": "ken_burns_doc", "peso": 2},
        {"id": "ov_particulas_lentas", "peso": 3}, {"id": "ov_bokeh_suave", "peso": 1}, {"id": "grao_16mm", "peso": 1},
        {"id": "vhs_desalinhado", "peso": 1}]},
    "transicoes": {"pct": 15, "itens": [
        {"id": "caes_corte_preto_rapido", "peso": 4}, {"id": "corte_pro_preto_doc", "peso": 2}, {"id": "gl_glitch", "peso": 1},
        {"id": "ft_pk_glitch", "peso": 1}, {"id": "gl_fade_escuro", "peso": 1}]},
    "entradas": {"pct": 18, "itens": [
        {"id": "foto_arquivo_lenta", "peso": 3}, {"id": "ken_burns_foto", "peso": 2}, {"id": "documento_desliza", "peso": 2},
        {"id": "revela_documento", "peso": 1}, {"id": "punch_in", "peso": 1}]},
    "saidas": {"pct": 0, "itens": []},
    "templates": {"pct": 8, "itens": [{"id": "ED_PERFIL", "peso": 3}, {"id": "ED_ARTIGO", "peso": 2},
                                      {"id": "ED_CITACAO", "peso": 2}, {"id": "ED_LOWER_NOME", "peso": 1}]},
    "templatesAvatar": {"pct": 0, "itens": []},
    "overlays": {"pct": 0, "itens": [], "maxPorCena": 1},
    "pares": {"modo": "livre", "itens": []},
    "legenda": None,  # a frase-chave vai em tarja (destaque), não em legenda corrida
    "destaques": {"ativo": True, "densidade": "maximo", "estilos": [
        "dallas_tarja", "dallas_cartela", "dallas_nivel", "branco", "estat", "capitulo", "digitacao", "glitch_hacker"]},
    "editoriais": {"ativo": True, "densidade": "equilibrado",
                   "tipos": ["post", "pagina", "reescrita", "ficha", "nome", "numero", "terminal"]},
    "som_transicoes": "auto",
    "referencia": {"canal": "Dallas", "videos_analisados": 3, "proporcao": "2.39:1", "plano_mediana_s": [3.4, 3.0, 5.0],
                   "palavras_por_minuto": 170},
}

DIRECOES: List[Dict[str, Any]] = [MISTERE, DOSSIE_PAPEL, DALLAS]


def _so_o_que_existe(d: Dict[str, Any]) -> Dict[str, Any]:
    """Tira os ids que não estão no catálogo desta instalação (ex.: sem o pacote de extras) —
    a direção continua valendo com o que existe."""
    import dp_direcao
    import dp_visual
    for eixo in ("filtros", "transicoes", "entradas", "saidas", "templates"):
        cat = d.get(eixo)
        if isinstance(cat, dict) and cat.get("itens"):
            try:
                validos = dp_direcao._ids_validos(eixo)
            except Exception:  # noqa: BLE001
                continue
            cat["itens"] = [i for i in cat["itens"] if i["id"] in validos]
    if isinstance(d.get("efeitos"), dict):
        ok = set(dp_visual.EFEITO_PARA_ZOOM) | {e["id"] for e in dp_visual.efeitos()}
        d["efeitos"]["itens"] = [i for i in d["efeitos"]["itens"] if i["id"] in ok]
    if isinstance(d.get("destaques"), dict):
        import dp_destaques
        cat = dp_destaques.catalogo()
        d["destaques"]["estilos"] = [e for e in d["destaques"]["estilos"] if e in cat]
    return d


def todas() -> List[Dict[str, Any]]:
    import json
    return [_so_o_que_existe(json.loads(json.dumps(d))) for d in DIRECOES]
