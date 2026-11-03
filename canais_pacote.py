"""📦 v84_336: levar canais (com estilo e tudo) pra outro PC — exportar em ZIP (ou só JSON) e importar.

O pacote leva, de cada canal escolhido:
  • a pasta inteira dele: canal.json (nome, descrição, voz/idioma/quem narra, 🎨 acabamento, formato, perfil, memes…) e as
    mídias do canal (K1, K2…);
  • as FONTES QUE VOCÊ ENVIOU e que o canal usa (no @, na legenda ou no perfil) — .ttf + o registro;
  • os 📂 grupos (palavra → canal) ligados a ele;
  • opcional: o 🎨 acabamento "padrão de todos".
Só o JSON: os mesmos dados, sem mídias nem fontes (no outro PC a fonte que faltar cai na padrão).

Importar: o canal entra com o mesmo id (os grupos continuam apontando pra ele). Se já existir um canal com esse id:
"substituir" troca pelo do pacote; "copia" cria outro canal (id novo, nome "… (importado)") e os grupos vão pra cópia.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import time
import zipfile
from typing import Any, Dict, List, Optional, Tuple

import curtos as CT

VERSAO = 1
_ARQ_FONTE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.(ttf|otf)")


def _fontes_extras() -> Dict[str, Dict[str, Any]]:
    """As fontes que NÃO são de fábrica (as enviadas): {familia: {"chave", "arquivos"}}."""
    try:
        import dp_extras
        fs = dp_extras.carregar().get("fontes") or {}
    except Exception:  # noqa: BLE001
        fs = {}
    if not fs:  # (o registro pode estar só no arquivo, sem recarregar)
        try:
            import dp_extras
            with open(os.path.join(dp_extras.pasta(), "fontes.json"), encoding="utf-8") as f:
                fs = (json.load(f) or {}).get("fontes") or {}
        except (OSError, ValueError, ImportError):
            fs = {}
    return {str(v.get("familia")): {"chave": k, "arquivos": dict(v.get("arquivos") or {})} for k, v in fs.items()
            if isinstance(v, dict) and str(v.get("familia") or "").startswith("DP ")}


def _familias_usadas(c: Dict[str, Any], padrao: Optional[Dict[str, Any]] = None) -> set:
    fams = set()

    def varrer(x: Any) -> None:
        if isinstance(x, dict):
            for v in x.values():
                varrer(v)
        elif isinstance(x, list):
            for v in x:
                varrer(v)
        elif isinstance(x, str) and x.startswith("DP "):
            fams.add(x)
    varrer(c)
    if padrao:
        varrer(padrao)
    return fams


def _grupos(base: str) -> Dict[str, Dict[str, str]]:
    try:
        with open(os.path.join(CT.raiz(base), "grupos_link.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar_grupos(base: str, d: Dict[str, Dict[str, str]]) -> None:
    os.makedirs(CT.raiz(base), exist_ok=True)
    cam = os.path.join(CT.raiz(base), "grupos_link.json")
    with open(cam + ".tmp", "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(cam + ".tmp", cam)


def _acab_padrao(base: str) -> Optional[Dict[str, Any]]:
    try:
        with open(os.path.join(CT.raiz(base), "_acabamento.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------ exportar
def exportar(base: str, ids: List[str], formato: str = "zip", com_padrao: bool = False) -> Tuple[bytes, str]:
    """(bytes, nome do arquivo). ids vazio = todos os canais."""
    todos = [c["id"] for c in CT.listar_canais(base)]
    ids = [i for i in (ids or todos) if i in todos]
    if not ids:
        raise CT.CurtoErro("Nenhum canal pra exportar.")
    canais = [CT.carregar_canal(base, i) for i in ids]
    padrao = _acab_padrao(base) if com_padrao else None
    grupos = {k: g for k, g in _grupos(base).items() if g.get("canal_id") in ids}
    extras = _fontes_extras()
    usadas = set()
    for c in canais:
        usadas |= _familias_usadas(c)
    usadas |= _familias_usadas({}, padrao)
    fontes = {fam: extras[fam] for fam in sorted(usadas) if fam in extras}
    manifesto = {"tipo": "besteditor-canais", "versao": VERSAO, "gerado_em": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "canais": [{"id": c["id"], "nome": c.get("nome") or c["id"]} for c in canais], "grupos": grupos,
                 "acabamento_padrao": padrao, "fontes": fontes}
    sufixo = canais[0].get("nome") if len(canais) == 1 else f"{len(canais)}_canais"
    nome = "canais_" + re.sub(r"[^A-Za-z0-9_-]+", "_", str(sufixo))[:40] + ("." + ("json" if formato == "json" else "zip"))
    if formato == "json":
        manifesto["dados_canais"] = canais
        return json.dumps(manifesto, ensure_ascii=False, indent=1).encode("utf-8"), nome
    import dp_destaques
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifesto.json", json.dumps(manifesto, ensure_ascii=False, indent=1))
        for c in canais:
            raiz_c = CT.pasta_canal(base, c["id"])
            for dirpath, _dirs, files in os.walk(raiz_c):
                for n in files:
                    cam = os.path.join(dirpath, n)
                    rel = os.path.relpath(cam, raiz_c).replace("\\", "/")
                    z.write(cam, f"canais/{c['id']}/{rel}")
        for fam, info in fontes.items():
            for arq in info["arquivos"].values():
                cam = os.path.join(dp_destaques.FONTES_DIR, arq)
                if os.path.isfile(cam):
                    z.write(cam, f"fontes/{arq}")
    return buf.getvalue(), nome


# ------------------------------------------------------------------ importar
def _instalar_fontes(fontes: Dict[str, Any], arquivos: Dict[str, bytes]) -> List[str]:
    import dp_destaques
    import dp_extras
    ok = []
    if not fontes:
        return ok
    cam = os.path.join(dp_extras.pasta(), "fontes.json")
    try:
        with open(cam, encoding="utf-8") as f:
            reg = json.load(f)
    except (OSError, ValueError):
        reg = {}
    fs = reg.setdefault("fontes", {})
    for fam, info in fontes.items():
        if not str(fam).startswith("DP ") or not isinstance(info, dict):
            continue
        arqs = {k: v for k, v in (info.get("arquivos") or {}).items() if k in ("Bold", "Regular", "Italic") and _ARQ_FONTE.fullmatch(str(v))}
        if not arqs or not all(arquivos.get(v) or os.path.isfile(os.path.join(dp_destaques.FONTES_DIR, v)) for v in arqs.values()):
            continue  # (sem o arquivo da fonte não registra — o canal cai na fonte padrão)
        for v in arqs.values():
            dados = arquivos.get(v)
            if dados:
                os.makedirs(dp_destaques.FONTES_DIR, exist_ok=True)
                with open(os.path.join(dp_destaques.FONTES_DIR, v), "wb") as f:
                    f.write(dados)
        chave = re.sub(r"[^a-z0-9_]", "", str(info.get("chave") or "")) or "usr_importada"
        fs[chave] = {"familia": fam, "arquivos": arqs}
        ok.append(fam)
    os.makedirs(dp_extras.pasta(), exist_ok=True)
    with open(cam, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)
    try:
        dp_extras.carregar.cache_clear()
    except AttributeError:
        pass
    try:
        import dp_legendas
        dp_legendas._mapa_fontes.cache_clear()
    except Exception:  # noqa: BLE001
        pass
    return ok


def importar(base: str, dados: bytes, nome_arquivo: str = "", modo: str = "copia", com_padrao: bool = False) -> Dict[str, Any]:
    """Recebe o .zip ou o .json do exportar. Devolve {"canais": [{"id", "nome", "acao"}], "fontes": [...], "grupos": n}."""
    arquivos_canal: Dict[str, Dict[str, bytes]] = {}
    arquivos_fonte: Dict[str, bytes] = {}
    if dados[:2] == b"PK":
        try:
            z = zipfile.ZipFile(io.BytesIO(dados))
        except zipfile.BadZipFile as exc:
            raise CT.CurtoErro("Esse arquivo não é um ZIP válido.") from exc
        try:
            man = json.loads(z.read("manifesto.json").decode("utf-8"))
        except (KeyError, ValueError) as exc:
            raise CT.CurtoErro("Esse ZIP não é um pacote de canais (falta o manifesto.json).") from exc
        total = 0
        for info in z.infolist():
            if info.is_dir():
                continue
            n = info.filename.replace("\\", "/")
            total += info.file_size
            if total > 3 * 1024 ** 3:
                raise CT.CurtoErro("Pacote grande demais.")
            partes = n.split("/")
            if any(p in ("", ".", "..") for p in partes) or n.startswith("/") or ":" in partes[0]:
                continue  # 🔒 nada de caminho pra fora da pasta
            if partes[0] == "canais" and len(partes) >= 3 and CT._valido(partes[1]):
                arquivos_canal.setdefault(partes[1], {})["/".join(partes[2:])] = z.read(info)
            elif partes[0] == "fontes" and len(partes) == 2 and _ARQ_FONTE.fullmatch(partes[1]):
                arquivos_fonte[partes[1]] = z.read(info)
    else:
        try:
            man = json.loads(dados.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise CT.CurtoErro("Esse arquivo não é um pacote de canais (.zip ou .json).") from exc
        for c in man.get("dados_canais") or []:
            if isinstance(c, dict) and CT._valido(c.get("id")):
                arquivos_canal[c["id"]] = {"canal.json": json.dumps(c, ensure_ascii=False).encode("utf-8")}
    if not isinstance(man, dict) or man.get("tipo") != "besteditor-canais":
        raise CT.CurtoErro("Esse arquivo não é um pacote de canais do BestEditor.")
    existentes = {c["id"] for c in CT.listar_canais(base)}
    novos_ids: Dict[str, str] = {}
    out = []
    for cid, arqs in arquivos_canal.items():
        if "canal.json" not in arqs:
            continue
        try:
            c = json.loads(arqs["canal.json"].decode("utf-8"))
        except ValueError:
            continue
        destino_id, acao = cid, "novo"
        if cid in existentes:
            if modo == "substituir":
                acao = "substituído"
                shutil.rmtree(CT.pasta_canal(base, cid), ignore_errors=True)
            else:
                destino_id, acao = CT._novo_id(), "cópia"
                c["nome"] = (str(c.get("nome") or "canal") + " (importado)")[:80]
        c["id"] = destino_id
        pasta = CT.pasta_canal(base, destino_id)
        os.makedirs(pasta, exist_ok=True)
        for rel, conteudo in arqs.items():
            if rel == "canal.json":
                continue
            cam = os.path.normpath(os.path.join(pasta, rel))
            if not cam.startswith(os.path.normpath(pasta) + os.sep):
                continue
            os.makedirs(os.path.dirname(cam), exist_ok=True)
            with open(cam, "wb") as f:
                f.write(conteudo)
        with CT._TRAVA:
            CT.salvar_canal(base, c)
        novos_ids[cid] = destino_id
        out.append({"id": destino_id, "nome": c.get("nome") or destino_id, "acao": acao})
    if not out:
        raise CT.CurtoErro("O pacote não tem nenhum canal.")
    fontes = _instalar_fontes(man.get("fontes") or {}, arquivos_fonte)
    gs = _grupos(base)
    n_g = 0
    for k, g in (man.get("grupos") or {}).items():
        if isinstance(g, dict) and g.get("canal_id") in novos_ids:
            gs[str(k)[:60]] = {"nome": str(g.get("nome") or k)[:60], "canal_id": novos_ids[g["canal_id"]]}
            n_g += 1
    if n_g:
        _gravar_grupos(base, gs)
    if com_padrao and isinstance(man.get("acabamento_padrao"), dict):
        CT.salvar_acabamento(base, man["acabamento_padrao"])
    return {"canais": out, "fontes": fontes, "grupos": n_g, "padrao": bool(com_padrao and man.get("acabamento_padrao"))}
