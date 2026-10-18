"""
perfis_pacote.py — 📦 exportar / importar PERFIS DE VOZ em .zip (levar pra outro PC)
=====================================================================================

EXPORTAR: junta um ou vários perfis num .zip com tudo o que é deles:
  manifesto.json                          ← nome, gênero/idade/descrição, 🎧 limpo×música, vozes com slug que usam o perfil
  perfis/<perfil>/ref_01.wav ...          ← os clipes de referência (o que a clonagem usa)
  perfis/<perfil>/_original/ref_01.wav    ← os áudios como vieram (se a voz foi limpa da música)

IMPORTAR aceita:
  1. um .zip exportado por aqui (com manifesto.json) — volta tudo como estava, no outro PC;
  2. um .zip "comum" só com áudios:
       - áudios soltos na raiz            → UM perfil (nome = o que você digitar, ou o nome do .zip);
       - uma pasta por pessoa (joao/*.wav) → um perfil por pasta.
     Esses áudios passam pelo mesmo processamento do "Novo perfil" (ffmpeg → wav mono 22 kHz, até 5 clipes).

Nome que já existe: vira "<nome>_2" (ou é substituído, se marcar "substituir").
Nada do .zip é extraído "às cegas": cada arquivo é lido pelo nome, com o caminho conferido (sem ../, sem absoluto).
"""
from __future__ import annotations

import io
import json
import os
import posixpath
import shutil
import sys
import tempfile
import time
import zipfile
from typing import Any, Dict, List, Optional

FORMATO = "narration_site/perfis_de_voz"
VERSAO = 1
PASTA_ORIGINAL = "_original"
EXT_AUDIO = (".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".opus", ".webm", ".mp4", ".mkv", ".mov", ".wma")
MAX_ARQUIVO = 200 * 1024 * 1024        # 200 MB por arquivo dentro do zip
MAX_TOTAL = 1024 * 1024 * 1024         # 1 GB descompactado no total


class PacoteErro(Exception):
    pass


def _vg():
    aqui = os.path.dirname(os.path.abspath(__file__))
    tk = os.path.join(aqui, "toolkit")
    if tk not in sys.path:
        sys.path.insert(0, tk)
    from tts import voice_generator
    return voice_generator


# ------------------------------------------------------------------ exportar
def _arquivos_do_perfil(nome: str) -> List[tuple]:
    """[(caminho_no_disco, caminho_relativo_no_zip_dentro_do_perfil)] — clipes + _original/."""
    vg = _vg()
    clipes = vg.caminho_perfil_de_voz(nome)  # levanta VoiceGeneratorError se não existir
    out = []
    for c in clipes:
        out.append((c, os.path.basename(c)))
        o = os.path.join(os.path.dirname(c), PASTA_ORIGINAL, os.path.basename(c))
        if os.path.isfile(o):
            out.append((o, f"{PASTA_ORIGINAL}/{os.path.basename(c)}"))
    if clipes:
        pr = os.path.join(os.path.dirname(clipes[0]), getattr(vg, "ARQ_PRINCIPAL", "_principal.txt"))
        if os.path.isfile(pr):  # ⭐ qual clipe é o principal (v84_174)
            out.append((pr, os.path.basename(pr)))
    return out


def _vozes_que_usam(nome: str) -> List[Dict[str, Any]]:
    try:
        import multivoz as mv
        return [{k: v[k] for k in ("slug", "nome", "motor", "config", "cor", "genero", "idade", "descricao") if k in v}
                for v in mv._ler() if (v.get("config") or {}).get("vozPerfil") == nome]
    except Exception:  # noqa: BLE001
        return []


def exportar(nomes: Optional[List[str]] = None) -> bytes:
    """Monta o .zip (em memória) com os perfis `nomes` (None/vazio = todos). Devolve os bytes."""
    import perfis_info
    vg = _vg()
    existentes = vg.listar_perfis_de_voz()
    nomes = [n for n in (nomes or existentes) if n]
    if not nomes:
        raise PacoteErro("Não há nenhum perfil de voz pra exportar.")
    faltando = [n for n in nomes if n not in existentes]
    if faltando:
        raise PacoteErro(f"Perfil não encontrado: {', '.join(faltando)}")
    manifesto: Dict[str, Any] = {"formato": FORMATO, "versao": VERSAO, "criado_em": time.strftime("%Y-%m-%d %H:%M:%S"), "perfis": []}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for nome in nomes:
            info = dict(perfis_info.obter(nome))
            lp = dict(info.get("limpeza") or {})
            if lp.get("estado") == "rodando":  # no outro PC não tem limpeza nenhuma rodando
                lp.update(estado="erro", erro="a limpeza não tinha terminado quando o perfil foi exportado — clique em 🧹 Limpar agora")
            if lp:
                info["limpeza"] = lp
            arquivos = []
            for disco, rel in _arquivos_do_perfil(nome):
                z.write(disco, f"perfis/{nome}/{rel}")
                arquivos.append(rel)
            manifesto["perfis"].append({"nome": nome, "info": info, "arquivos": arquivos, "vozes_slug": _vozes_que_usam(nome)})
        z.writestr("manifesto.json", json.dumps(manifesto, ensure_ascii=False, indent=1))
        z.writestr("LEIA-ME.txt", "Perfis de voz exportados do site de narração.\n"
                                  "Pra usar em outro PC: abra 🗣️ Perfis de voz → 📦 Importar perfis (.zip) e envie este arquivo.\n"
                                  "Não precisa descompactar.\n")
    return buf.getvalue()


# ------------------------------------------------------------------ importar
def _caminho_seguro(nome_zip: str) -> Optional[str]:
    """Normaliza um nome de dentro do zip; None se for perigoso (absoluto, ../) ou lixo de sistema."""
    n = nome_zip.replace("\\", "/")
    if n.startswith("/") or (len(n) > 1 and n[1] == ":"):
        return None
    n = posixpath.normpath(n)
    if n.startswith("..") or n in (".", ""):
        return None
    partes = n.split("/")
    if any(p in ("..",) for p in partes) or "__MACOSX" in partes or any(p.startswith("._") for p in partes) \
            or partes[-1] in (".DS_Store", "Thumbs.db", "desktop.ini"):
        return None
    return n


def _nome_livre(base: str, existentes: set) -> str:
    if base not in existentes:
        return base
    k = 2
    while f"{base}_{k}" in existentes:
        k += 1
    return f"{base}_{k}"


def _abrir(zip_path: str) -> zipfile.ZipFile:
    try:
        z = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise PacoteErro("Esse arquivo não é um .zip válido.") from exc
    total = 0
    for i in z.infolist():
        if i.file_size > MAX_ARQUIVO:
            z.close()
            raise PacoteErro(f"Arquivo grande demais dentro do zip: {i.filename}")
        total += i.file_size
    if total > MAX_TOTAL:
        z.close()
        raise PacoteErro("O zip descompactado passa de 1 GB — grande demais pra perfis de voz.")
    return z


def _extrair(z: zipfile.ZipFile, membro: str, destino: str) -> None:
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with z.open(membro) as src, open(destino, "wb") as dst:
        shutil.copyfileobj(src, dst)


def _preparar_destino(nome: str, substituir: bool, existentes: set) -> str:
    vg = _vg()
    if nome in existentes:
        if substituir:
            vg.excluir_perfil_de_voz(nome)
            try:
                import perfis_info
                perfis_info.remover(nome)
            except Exception:  # noqa: BLE001
                pass
        else:
            nome = _nome_livre(nome, existentes)
    return nome


def _importar_manifesto(z: zipfile.ZipFile, membros: Dict[str, str], manifesto: Dict[str, Any], substituir: bool,
                        renomear: Optional[str]) -> List[Dict[str, Any]]:
    import perfis_info
    vg = _vg()
    perfis = [p for p in (manifesto.get("perfis") or []) if isinstance(p, dict) and p.get("nome")]
    if not perfis:
        raise PacoteErro("O manifesto.json do zip não tem nenhum perfil.")
    existentes = set(vg.listar_perfis_de_voz())
    resultado = []
    for p in perfis:
        nome_orig = vg._nome_perfil_seguro(str(p["nome"]))
        desejado = vg._nome_perfil_seguro(renomear) if (renomear and len(perfis) == 1) else nome_orig
        prefixo = f"perfis/{p['nome']}/"
        arquivos = [(seg, membros[seg][len(prefixo):]) for seg in membros if membros[seg].startswith(prefixo)]
        clipes = [(seg, rel) for seg, rel in arquivos if "/" not in rel and rel.lower().endswith(".wav")]
        if not clipes:
            continue
        nome = _preparar_destino(desejado, substituir, existentes)
        pasta = vg._pasta_perfil(nome)
        os.makedirs(pasta, exist_ok=True)
        for seg, rel in arquivos:
            partes = rel.split("/")
            if rel == getattr(vg, "ARQ_PRINCIPAL", "_principal.txt"):
                _extrair(z, seg, os.path.join(pasta, rel))  # ⭐ o principal volta junto
                continue
            if not rel.lower().endswith(".wav") or len(partes) > 2 or (len(partes) == 2 and partes[0] != PASTA_ORIGINAL):
                continue
            _extrair(z, seg, os.path.join(pasta, *partes))
        info = p.get("info") if isinstance(p.get("info"), dict) else {}
        try:
            perfis_info.definir(nome, info.get("genero") or "", info.get("idade") or "", info.get("descricao") or "")
        except ValueError:
            pass
        extras = {k: info[k] for k in ("audio", "limpeza") if info.get(k)}
        if extras:
            perfis_info.atualizar(nome, **extras)
        existentes.add(nome)
        vozes = _importar_vozes_slug(p.get("vozes_slug") or [], nome_orig_manifesto=str(p["nome"]), nome_novo=nome)
        resultado.append({"nome": nome, "de": str(p["nome"]), "clipes": len(clipes), "vozes_slug": vozes,
                          "renomeado": nome != desejado})
    return resultado


def _importar_vozes_slug(vozes: List[Dict[str, Any]], nome_orig_manifesto: str, nome_novo: str) -> List[str]:
    """Traz as 🎭 vozes com slug que usavam o perfil — só as que ainda não existem neste PC (não sobrescreve)."""
    try:
        import multivoz as mv
    except Exception:  # noqa: BLE001
        return []
    ja = {v["slug"] for v in mv._ler()}
    feitas = []
    for v in vozes:
        if not isinstance(v, dict) or not v.get("slug") or mv.slugify(v["slug"]) in ja:
            continue
        d = dict(v)
        d["config"] = dict(v.get("config") or {}, vozPerfil=nome_novo)
        try:
            salva = mv.salvar(d)
            feitas.append(salva["slug"])
            ja.add(salva["slug"])
        except Exception:  # noqa: BLE001
            continue
    return feitas


def _importar_audios_soltos(z: zipfile.ZipFile, membros: Dict[str, str], nome_padrao: str, substituir: bool,
                            dividir: bool) -> List[Dict[str, Any]]:
    """Zip "comum": áudios na raiz → 1 perfil; uma pasta por pessoa → 1 perfil por pasta."""
    vg = _vg()
    grupos: Dict[str, List[str]] = {}
    for seg in sorted(membros, key=lambda s: membros[s]):
        rel = membros[seg]
        if not rel.lower().endswith(EXT_AUDIO):
            continue
        partes = rel.split("/")
        # ignora uma pasta "embrulho" única (ex.: zip de uma pasta "vozes/" com subpastas por pessoa) — tratado abaixo
        grupos.setdefault("/".join(partes[:-1]), []).append(seg)
    if not grupos:
        raise PacoteErro("Não achei nenhum áudio no zip (wav, mp3, m4a, ogg, flac… ou vídeo).")
    # se TODOS os grupos estão dentro de uma mesma pasta-embrulho, tira ela do nome
    chaves = list(grupos)
    if len(chaves) > 1:
        primeiros = {c.split("/")[0] for c in chaves}
        if len(primeiros) == 1 and all("/" in c for c in chaves):
            grupos = {c.split("/", 1)[1]: v for c, v in grupos.items()}
    existentes = set(vg.listar_perfis_de_voz())
    resultado = []
    with tempfile.TemporaryDirectory(prefix="import_perfil_") as tmp:
        for k, (grupo, segs) in enumerate(sorted(grupos.items())):
            base = (nome_padrao if (len(grupos) == 1 or not grupo) else posixpath.basename(grupo)) or nome_padrao
            nome = _preparar_destino(vg._nome_perfil_seguro(base), substituir, existentes)
            segs = segs[: vg.MAX_CLIPES_POR_PERFIL]
            caminhos = []
            for j, seg in enumerate(segs):
                destino = os.path.join(tmp, f"g{k}_{j}{os.path.splitext(membros[seg])[1].lower()}")
                _extrair(z, seg, destino)
                caminhos.append(destino)
            origem = caminhos[0] if len(caminhos) == 1 else caminhos
            salvos = vg.salvar_perfil_de_voz(nome, origem, dividir_audio_longo=dividir)
            existentes.add(nome)
            resultado.append({"nome": nome, "de": grupo or "(raiz do zip)", "clipes": len(salvos), "vozes_slug": [],
                              "renomeado": nome != vg._nome_perfil_seguro(base)})
    return resultado


def importar(zip_path: str, nome: str = "", substituir: bool = False, dividir: bool = True,
             nome_zip: str = "") -> List[Dict[str, Any]]:
    """Importa os perfis do .zip. Devolve [{nome, de, clipes, vozes_slug, renomeado}]."""
    z = _abrir(zip_path)
    try:
        membros: Dict[str, str] = {}
        for i in z.infolist():
            if i.is_dir():
                continue
            seguro = _caminho_seguro(i.filename)
            if seguro:
                membros[i.filename] = seguro
        manifesto = None
        man = next((s for s, r in membros.items() if r == "manifesto.json"), None)
        if man:
            try:
                manifesto = json.loads(z.read(man).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                manifesto = None
        if isinstance(manifesto, dict) and manifesto.get("formato") == FORMATO:
            res = _importar_manifesto(z, membros, manifesto, substituir, (nome or "").strip() or None)
        else:
            padrao = (nome or "").strip() or os.path.splitext(os.path.basename(nome_zip or zip_path))[0] or "perfil_importado"
            res = _importar_audios_soltos(z, membros, padrao, substituir, dividir)
    finally:
        z.close()
    if not res:
        raise PacoteErro("Nenhum perfil foi importado — o zip não tinha clipes de áudio.")
    return res
