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

DIRECOES: List[Dict[str, Any]] = [MISTERE]


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
