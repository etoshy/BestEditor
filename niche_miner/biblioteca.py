#!/usr/bin/env python3
"""
Biblioteca do Niche Miner
=========================

Guarda, em um arquivo SQLite local (``data/biblioteca.db``), cada busca feita:

* **tema**  = o nicho amplo digitado na interface (agrupa as buscas);
* **busca** = uma execução completa (vários termos, uma data);
* **canais** analisados nessa busca (inscritos, nº de vídeos, views totais do
  Sobre, datas do 1º/último vídeo, frequência, 5 mais antigos, 3 mais
  populares, 3 mais recentes, amostra dos últimos 50...);
* **vídeos** encontrados na busca (título, data, views, link e o canal).

Só usa a biblioteca padrão do Python (sqlite3), sem dependências extras. O
caminho do banco pode ser trocado com a variável de ambiente
``NICHE_MINER_DB`` (usada nos testes).
"""

import csv
import io
import json
import os
import re
import sqlite3
import unicodedata
from contextlib import closing
from datetime import datetime
from pathlib import Path

DB_PADRAO = Path(__file__).resolve().parent / "data" / "biblioteca.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS buscas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tema          TEXT NOT NULL,
    tema_norm     TEXT NOT NULL,
    criado_em     TEXT NOT NULL,
    termos_json   TEXT NOT NULL,
    termos_norm   TEXT NOT NULL,
    subnichos_json TEXT NOT NULL,
    filtros_json  TEXT NOT NULL,
    config_json   TEXT NOT NULL,
    n_canais      INTEGER NOT NULL DEFAULT 0,
    n_videos      INTEGER NOT NULL DEFAULT 0,
    n_verificados INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS canais (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    busca_id            INTEGER NOT NULL REFERENCES buscas(id) ON DELETE CASCADE,
    canal               TEXT,
    canal_norm          TEXT,
    canal_url           TEXT,
    inscritos_num       INTEGER,
    n_videos            INTEGER,
    views_totais        INTEGER,
    data_criacao_canal  TEXT,
    data_primeiro_video TEXT,
    data_ultimo_video   TEXT,
    frequencia_label    TEXT,
    frequencia_atividade TEXT,
    fora_da_janela      INTEGER,
    idade_desconhecida  INTEGER,
    score               REAL,
    dados_json          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS videos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    busca_id        INTEGER NOT NULL REFERENCES buscas(id) ON DELETE CASCADE,
    video_id        TEXT,
    titulo          TEXT,
    texto_norm      TEXT,
    data_publicacao TEXT,
    views_num       INTEGER,
    views_text      TEXT,
    url             TEXT,
    duracao         TEXT,
    canal           TEXT,
    canal_url       TEXT,
    canal_verificado INTEGER NOT NULL DEFAULT 0,
    termo_busca     TEXT,
    subnicho        TEXT,
    nicho           TEXT
);
CREATE INDEX IF NOT EXISTS idx_canais_busca ON canais(busca_id);
CREATE INDEX IF NOT EXISTS idx_videos_busca ON videos(busca_id);
"""


# --------------------------------------------------------------------------
# Utilitários
# --------------------------------------------------------------------------

def normalizar(texto) -> str:
    """Minúsculas, sem acentos e sem espaços repetidos (base da pesquisa)."""
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", t).casefold().strip()


def caminho_banco(db_path=None) -> Path:
    if db_path:
        return Path(db_path)
    return Path(os.environ.get("NICHE_MINER_DB") or DB_PADRAO)


def _conectar(db_path=None):
    caminho = caminho_banco(db_path)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(caminho), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    return con


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _int(valor):
    try:
        return None if valor is None or valor == "" else int(valor)
    except (TypeError, ValueError):
        return None


def _bool_int(valor):
    return None if valor is None else int(bool(valor))


def _data_primeiro_video(c: dict) -> str:
    """Data do 1º vídeo, ou "" se não foi possível confirmar qual é o primeiro."""
    if c.get("primeiro_video_confiavel") is False:
        return ""
    d = c.get("primeiro_video_data_publicacao") or ""
    if not d:
        lista = c.get("primeiros_5_videos") or []
        d = (lista[0].get("data") if lista else "") or ""
    return d


def _data_ultimo_video(c: dict) -> str:
    d = c.get("ultimo_video_data_publicacao") or ""
    if not d:
        lista = c.get("ultimos_3_videos") or []
        d = (lista[0].get("data") if lista else "") or ""
    return d


def _agrupar_videos(videos) -> list:
    """Um registro por vídeo; junta os termos que o encontraram."""
    mapa = {}
    for v in videos or []:
        chave = v.get("video_id") or v.get("url")
        if not chave:
            continue
        termo = str(v.get("termo_busca") or "").strip()
        atual = mapa.get(chave)
        if atual is None:
            item = dict(v)
            item["_termos"] = [termo] if termo else []
            mapa[chave] = item
            continue
        if termo and termo not in atual["_termos"]:
            atual["_termos"].append(termo)
        if (v.get("views_num") or 0) > (atual.get("views_num") or 0):
            termos = atual["_termos"]
            atual.update(v)
            atual["_termos"] = termos
    return list(mapa.values())


# --------------------------------------------------------------------------
# Gravação
# --------------------------------------------------------------------------

def salvar_busca(tema, termos, subnichos, filtros, config, canais, videos, db_path=None) -> int:
    """Grava uma busca completa e devolve o id dela."""
    tema = (tema or "").strip() or "Sem tema"
    termos = [t for t in dict.fromkeys(str(t).strip() for t in (termos or [])) if t]
    unicos = _agrupar_videos(videos)
    n_verificados = len({v.get("canal_url") for v in unicos if v.get("canal_verificado") and v.get("canal_url")})

    with closing(_conectar(db_path)) as con, con:
        cur = con.execute(
            "INSERT INTO buscas (tema, tema_norm, criado_em, termos_json, termos_norm, subnichos_json,"
            " filtros_json, config_json, n_canais, n_videos, n_verificados)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                tema, normalizar(tema), datetime.now().isoformat(timespec="seconds"),
                _json(termos), normalizar(" ".join(termos)), _json(subnichos or []),
                _json(filtros or {}), _json(config or {}),
                len(canais or []), len(unicos), n_verificados,
            ),
        )
        busca_id = cur.lastrowid

        con.executemany(
            "INSERT INTO canais (busca_id, canal, canal_norm, canal_url, inscritos_num, n_videos, views_totais,"
            " data_criacao_canal, data_primeiro_video, data_ultimo_video, frequencia_label, frequencia_atividade,"
            " fora_da_janela, idade_desconhecida, score, dados_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    busca_id, c.get("canal", ""), normalizar(c.get("canal", "")), c.get("canal_url", ""),
                    _int(c.get("inscritos_num")), _int(c.get("n_videos")), _int(c.get("views_totais")),
                    c.get("data_criacao_canal", ""), _data_primeiro_video(c), _data_ultimo_video(c),
                    c.get("frequencia_label", ""), c.get("frequencia_atividade", ""),
                    _bool_int(c.get("fora_da_janela")), _bool_int(c.get("idade_desconhecida")),
                    float(c.get("score") or 0), _json(c),
                )
                for c in (canais or [])
            ],
        )

        con.executemany(
            "INSERT INTO videos (busca_id, video_id, titulo, texto_norm, data_publicacao, views_num, views_text,"
            " url, duracao, canal, canal_url, canal_verificado, termo_busca, subnicho, nicho)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    busca_id, v.get("video_id", ""), v.get("titulo", ""),
                    normalizar(" ".join([v.get("titulo", ""), " ".join(v["_termos"]), v.get("subnicho", "")])),
                    v.get("data_publicacao", ""), _int(v.get("views_num")), v.get("views_text", ""),
                    v.get("url", ""), v.get("duracao", ""), v.get("canal", ""), v.get("canal_url", ""),
                    int(bool(v.get("canal_verificado"))), " | ".join(v["_termos"]),
                    v.get("subnicho", ""), v.get("nicho", ""),
                )
                for v in unicos
            ],
        )
    return busca_id


def excluir_busca(busca_id: int, db_path=None) -> bool:
    with closing(_conectar(db_path)) as con, con:
        cur = con.execute("DELETE FROM buscas WHERE id = ?", (int(busca_id),))
        return cur.rowcount > 0


# --------------------------------------------------------------------------
# Leitura
# --------------------------------------------------------------------------

def _meta(r) -> dict:
    return {
        "id": r["id"], "tema": r["tema"], "criado_em": r["criado_em"],
        "termos": json.loads(r["termos_json"] or "[]"),
        "n_canais": r["n_canais"], "n_videos": r["n_videos"], "n_verificados": r["n_verificados"],
    }


def listar_biblioteca(db_path=None) -> list:
    """Temas (mais recente primeiro), cada um com suas buscas."""
    with closing(_conectar(db_path)) as con:
        linhas = con.execute("SELECT * FROM buscas ORDER BY id DESC").fetchall()
    temas = {}
    for r in linhas:
        g = temas.setdefault(r["tema_norm"], {
            "tema": r["tema"], "n_buscas": 0, "n_canais": 0, "n_videos": 0,
            "ultima_busca": r["criado_em"], "buscas": [],
        })
        g["n_buscas"] += 1
        g["n_canais"] += r["n_canais"]
        g["n_videos"] += r["n_videos"]
        g["buscas"].append(_meta(r))
    return list(temas.values())


def obter_busca(busca_id: int, db_path=None):
    """Busca completa: metadados, canais (com todos os detalhes), vídeos e canais verificados."""
    with closing(_conectar(db_path)) as con:
        b = con.execute("SELECT * FROM buscas WHERE id = ?", (int(busca_id),)).fetchone()
        if b is None:
            return None
        canais = [json.loads(r["dados_json"]) for r in
                  con.execute("SELECT dados_json FROM canais WHERE busca_id = ? ORDER BY id", (b["id"],))]
        videos = [dict(r) for r in
                  con.execute("SELECT * FROM videos WHERE busca_id = ? ORDER BY COALESCE(views_num, -1) DESC, id",
                              (b["id"],))]
    meta = _meta(b)
    meta["subnichos"] = json.loads(b["subnichos_json"] or "[]")
    meta["filtros"] = json.loads(b["filtros_json"] or "{}")
    meta["config"] = json.loads(b["config_json"] or "{}")

    verificados = {}
    for v in videos:
        if v["canal_verificado"] and v["canal_url"] and v["canal_url"] not in verificados:
            verificados[v["canal_url"]] = {
                "canal": v["canal"], "canal_url": v["canal_url"], "termo_busca": v["termo_busca"],
                "nicho": v["nicho"], "subnicho": v["subnicho"], "video_exemplo": v["url"],
                "views_text_video_exemplo": v["views_text"],
            }
    for v in videos:
        v.pop("texto_norm", None)
    return {"busca": meta, "canais": canais, "videos": videos, "verificados": list(verificados.values())}


def _condicao_tokens(expressao: str, tokens: list):
    """AND de ``instr(expressao, token) > 0`` — evita curingas do LIKE."""
    sql = " AND ".join(f"instr({expressao}, ?) > 0" for _ in tokens)
    return sql, list(tokens)


def pesquisar(q: str, db_path=None, limite: int = 200) -> dict:
    """Pesquisa por palavras-chave (sem acento/caixa) em temas, termos, canais e títulos de vídeos."""
    tokens = normalizar(q).split()
    vazio = {"q": q, "buscas": [], "canais": [], "videos": []}
    if not tokens:
        return vazio
    with closing(_conectar(db_path)) as con:
        sql, p = _condicao_tokens("(tema_norm || ' ' || termos_norm)", tokens)
        buscas = [_meta(r) for r in con.execute(
            f"SELECT * FROM buscas WHERE {sql} ORDER BY id DESC LIMIT ?", (*p, limite))]

        sql, p = _condicao_tokens("c.canal_norm", tokens)
        canais = [dict(r) for r in con.execute(
            "SELECT c.busca_id, b.tema, b.criado_em, c.canal, c.canal_url, c.inscritos_num, c.n_videos,"
            " c.views_totais, c.data_primeiro_video, c.data_ultimo_video, c.frequencia_label, c.fora_da_janela,"
            " c.score FROM canais c JOIN buscas b ON b.id = c.busca_id"
            f" WHERE {sql} ORDER BY c.busca_id DESC, c.id LIMIT ?", (*p, limite))]

        sql, p = _condicao_tokens("v.texto_norm", tokens)
        videos = [dict(r) for r in con.execute(
            "SELECT v.busca_id, b.tema, b.criado_em, v.titulo, v.url, v.data_publicacao, v.views_num,"
            " v.views_text, v.canal, v.canal_url, v.termo_busca FROM videos v JOIN buscas b ON b.id = v.busca_id"
            f" WHERE {sql} ORDER BY COALESCE(v.views_num, -1) DESC LIMIT ?", (*p, limite))]
    return {"q": q, "buscas": buscas, "canais": canais, "videos": videos}


# --------------------------------------------------------------------------
# Exportação CSV (separador ";" e BOM, para abrir direto no Excel em português)
# --------------------------------------------------------------------------

def _texto_videos(lista) -> str:
    partes = []
    for v in lista or []:
        views = v.get("views_text") or (f"{v['views_num']} views" if v.get("views_num") is not None else "?")
        partes.append(f"{v.get('titulo', '')} ({views} · {v.get('data') or v.get('quando') or '?'})")
    return " | ".join(partes)


COLUNAS_CANAIS = [
    ("canal", "Canal"), ("canal_url", "Link do canal"), ("inscritos_num", "Inscritos"),
    ("n_videos", "Nº de vídeos"), ("views_totais", "Views totais (Sobre)"),
    ("data_criacao_canal", "Canal criado em"), ("data_primeiro_video", "Data do 1º vídeo"),
    ("data_ultimo_video", "Data do último vídeo"), ("frequencia_label", "Frequência de postagem"),
    ("frequencia_videos_por_semana", "Vídeos por semana"), ("frequencia_atividade", "Atividade"),
    ("videos_ultimos_30d", "Vídeos nos últimos 30 dias"), ("fora_da_janela", "Fora da janela"),
    ("meses_desde_primeiro_video", "Meses desde o 1º vídeo"), ("score", "Score"),
    ("pais_canal", "País"), ("idioma_canal", "Idioma"), ("nichos", "Nichos"),
    ("subnichos", "Subnichos"), ("termos_busca", "Termos"),
    ("primeiros_5_videos", "5 primeiros vídeos"), ("top_3_populares", "3 mais populares"),
    ("ultimos_3_videos", "3 mais recentes"),
]
COLUNAS_VIDEOS = [
    ("titulo", "Título"), ("data_publicacao", "Data"), ("views_num", "Views"), ("url", "Link"),
    ("canal", "Canal"), ("canal_url", "Link do canal"), ("canal_verificado", "Canal verificado"),
    ("termo_busca", "Termos"), ("subnicho", "Subnicho"), ("nicho", "Nicho"), ("duracao", "Duração"),
]


def _valor_canal(c: dict, chave: str):
    if chave == "data_primeiro_video":
        return _data_primeiro_video(c)
    if chave == "data_ultimo_video":
        return _data_ultimo_video(c)
    v = c.get(chave)
    if chave in ("primeiros_5_videos", "top_3_populares", "ultimos_3_videos"):
        return _texto_videos(v)
    if chave in ("nichos", "subnichos", "termos_busca"):
        return ", ".join(v or []) if isinstance(v, list) else (v or "")
    if isinstance(v, bool):
        return "sim" if v else "não"
    return "" if v is None else v


def exportar_csv(busca_id: int, tipo: str, db_path=None):
    """CSV (texto) de ``canais`` ou ``videos`` da busca; None se a busca não existe."""
    dados = obter_busca(busca_id, db_path)
    if dados is None:
        return None
    if tipo == "canais":
        colunas = COLUNAS_CANAIS
        linhas = [[_valor_canal(c, k) for k, _ in colunas] for c in dados["canais"]]
    elif tipo == "videos":
        colunas = COLUNAS_VIDEOS
        linhas = [["sim" if (k == "canal_verificado" and v[k]) else ("não" if k == "canal_verificado" else v.get(k, ""))
                   for k, _ in colunas] for v in dados["videos"]]
    else:
        raise ValueError("tipo deve ser 'canais' ou 'videos'")
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([rotulo for _, rotulo in colunas])
    w.writerows(linhas)
    return buf.getvalue()
