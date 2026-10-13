"""
Testa o extrator com várias perguntas reais no Modo IA do Google.

    python testar.py                     # roda todos os testes (com a instrução de JSON)
    python testar.py --sem-instrucao     # também testa cada pergunta SEM a instrução
    python testar.py --categorias video,imagem
    python testar.py --limite 5          # só os 5 primeiros (teste rápido)
    python testar.py --arquivo minhas.txt   # suas perguntas (uma por linha)
    python testar.py --invisivel         # navegador escondido (mais captcha)

Se alguma resposta vier num formato inesperado, cria a pasta  falhas_AAAAMMDD-HHMM/  com:
    RELATORIO.txt          o que deu errado em cada teste e qual arquivo é de qual teste
    01_video_xxx.html      HTML da página do Google naquele momento
    01_video_xxx.png       print da tela
    01_video_xxx.json      o JSON que o sistema gerou
e no final gera  falhas_AAAAMMDD-HHMM.zip  para você mandar.
Se tudo der certo, não cria nada: só avisa.

IMPORTANTE: feche o app.py antes (os dois usam o mesmo perfil do navegador).
"""
import argparse
import json
import re
import shutil
import sys
import time
import traceback
import zipfile
from pathlib import Path

from ia_google import GoogleIA, classificar_erro, link_do_google, SEL

BASE = Path(__file__).resolve().parent

# (categoria, pergunta)  — "conversa" usa uma lista: as perguntas seguem a mesma conversa
TESTES = [
    ("numero", "Qual o valor do dólar hoje?"),
    ("numero", "Quanto está o bitcoin agora?"),
    ("numero", "Qual a previsão do tempo para São Paulo amanhã?"),
    ("numero", "Que horas são em Tóquio agora?"),
    ("numero", "Quantos habitantes tem o Brasil?"),
    ("noticia", "Quais as principais notícias do Brasil hoje?"),
    ("noticia", "Últimas notícias sobre inteligência artificial"),
    ("noticia", "O que aconteceu na política brasileira esta semana?"),
    ("noticia", "Resultado do último jogo do Flamengo"),
    ("explicacao", "Como funciona o Pix?"),
    ("explicacao", "Diferença entre CLT e PJ"),
    ("explicacao", "O que é a reforma tributária e o que muda?"),
    ("tabela", "Compare iPhone 16 e Galaxy S25 em uma tabela"),
    ("tabela", "Tabela com os 10 maiores PIBs do mundo"),
    ("passo", "Como fazer bolo de cenoura passo a passo"),
    ("passo", "Como formatar um PC com Windows 11"),
    ("video", "Vídeos do Enéas Carneiro"),
    ("video", "Tutorial de Python para iniciantes no YouTube"),
    ("imagem", "Imagens do Enéas Carneiro"),
    ("imagem", "Fotos da Torre Eiffel à noite"),
    ("lugar", "Melhores restaurantes japoneses em Curitiba"),
    ("produto", "Melhor notebook custo-benefício 2026"),
    ("codigo", "Como ler um arquivo CSV em Python? Mostre o código"),
    ("conversa", ["Quem é o presidente da França?", "Quantos anos ele tem?", "E qual o partido dele?"]),
    ("limite", "Pix"),
    ("limite", "What is the capital of Australia?"),
    ("limite", "Qual será o dólar em 2030?"),
]

# textos que nunca deveriam aparecer na resposta (sobras da página do Google)
LIXO = ["Copiado para a área", "Compartilhar link público", "Boa resposta", "Resposta ruim",
        "Use o código com cuidado", "Agradecemos a informação", "O Google pode usar os dados",
        "Falha ao copiar", "Mostrar tudo", "Uma cópia desta conversa"]

# JS: texto visível da área da resposta (para medir se algo ficou de fora)
JS_TEXTO_AREA = r"""
(sel) => {
  const blocos = document.querySelectorAll(sel.bloco_resposta);
  if (!blocos.length) return {texto: '', imgs: 0, iframes: 0, tabelas: 0};
  const bloco = blocos[blocos.length - 1];
  const area = bloco.querySelector(sel.texto_resposta) || bloco;
  const imgs = [...area.querySelectorAll('img')].filter(i => i.width > 60 && i.height > 60 && !i.closest('[data-im]')).length;
  const links = [...area.querySelectorAll('a[href]')].filter(a => /\/goto\?|^https?:/.test(a.getAttribute('href') || '')
                   && !/policies\.google|support\.google/.test(a.href)).length
                + bloco.querySelectorAll(sel.fonte_item).length;
  return {texto: area.innerText || '', imgs, links,
          iframes: area.querySelectorAll('iframe').length,
          tabelas: area.querySelectorAll('table').length};
}
"""


def palavras(t):
    return {w for w in re.findall(r"[a-záéíóúâêôãõçà]{4,}", (t or "").lower())}


def verificar(r, cat, usar_instrucao, area):
    """Devolve a lista de problemas encontrados na resposta."""
    p = []
    obj, comp, bruto = r.get("resposta_objetiva", ""), r.get("resposta_completa", ""), r.get("resposta_bruta_md", "")
    midias = r.get("midias", {})
    tem_midia = any(midias.get(k) for k in ("videos", "imagens", "links_destaque"))

    if not r.get("completa", True):
        p.append("TEMPO_ESGOTADO: a IA não terminou dentro do tempo limite (resposta parcial)")
    if r.get("so_resultados_web"):
        p.append(f"SO_RESULTADOS_WEB: a IA do Google não respondeu (nem após {r.get('tentativas', 1)} tentativas); "
                 "a resposta foi montada com a lista de resultados da web")
    elif r.get("aviso"):
        p.append(f"RECUSA_COM_INSTRUCAO: o Google recusou {r.get('tentativas', 1) - 1}x com a instrução; "
                 "a resposta veio da tentativa sem ela")
    elif usar_instrucao and not r.get("formato_respeitado"):
        if "```" in bruto or '"resposta_objetiva"' in bruto:
            p.append("JSON_INVALIDO: a IA mandou um bloco JSON, mas não consegui ler")
        else:
            p.append("SEM_JSON: a IA ignorou a instrução e não respondeu em JSON")
    if not obj.strip():
        p.append("OBJETIVA_VAZIA: resposta objetiva vazia")
    elif len(obj) > 600:
        p.append(f"OBJETIVA_LONGA: resposta objetiva com {len(obj)} caracteres (esperado: 1-2 frases)")
    if len(comp.strip()) < 40 and not tem_midia:
        p.append(f"COMPLETA_CURTA: resposta completa com só {len(comp.strip())} caracteres")
    if '"resposta_objetiva"' in comp or comp.strip().startswith("{"):
        p.append("JSON_NO_TEXTO: o JSON bruto vazou para a resposta completa")
    sobras = [x for x in LIXO if x in comp or x in obj]
    if sobras:
        p.append("LIXO_NO_TEXTO: sobras da página do Google na resposta: " + ", ".join(sobras))
    if re.search(r"\]\(https?://(www\.)?google\.[^)]*/(goto|url)\?", comp):
        p.append("LINK_GOOGLE_NO_TEXTO: link de redirecionamento do Google na resposta completa (não resolveu a URL real)")

    fontes = r.get("fontes", [])
    pagina_sem_links = area is not None and not area.get("links")
    if not fontes and cat not in ("limite", "codigo") and not pagina_sem_links:
        p.append("SEM_FONTES: nenhuma fonte encontrada")
    for f in fontes:
        u = f.get("url", "")
        if not u.startswith("http"):
            p.append(f"FONTE_SEM_URL: fonte '{f.get('titulo')}' sem link válido ({u[:60]})")
        elif "/goto?" in u or "/url?" in u:
            p.append(f"FONTE_NAO_RESOLVIDA: fonte '{f.get('titulo')}' ficou com link do Google ({u[:60]}…)")
        elif link_do_google(u):
            p.append(f"FONTE_GOOGLE: fonte '{f.get('titulo')}' é um link do próprio Google")

    if cat == "video" and not midias.get("videos") and not any("youtu" in f.get("url", "") for f in fontes):
        p.append("SEM_VIDEOS: pergunta pedia vídeos e nenhum vídeo foi encontrado")
    if cat == "imagem" and not midias.get("imagens"):
        p.append("SEM_IMAGENS: pergunta pedia imagens e nenhuma imagem foi encontrada")
    if cat == "tabela" and "|" not in comp:
        p.append("SEM_TABELA: pergunta pedia tabela e a resposta completa não tem tabela")
    if cat == "codigo" and "```" not in comp and "    " not in comp:
        p.append("SEM_CODIGO: pergunta pedia código e a resposta não tem bloco de código")

    # cobertura: quanto do texto visível da página foi parar no resultado
    if area:
        # o texto da página termina onde começa o rodapé/feedback do Google
        texto_area = re.split(r"\n\s*(Copiado para a área|As respostas da IA podem|A IA pode cometer erros|"
                              r"Use o código com cuidado|Compartilhar link público|Boa resposta)", area.get("texto") or "")[0]
        visivel = palavras(texto_area)
        extraido = palavras(json.dumps(r, ensure_ascii=False))
        if len(visivel) >= 25:
            cobertura = len(visivel & extraido) / len(visivel)
            if cobertura < 0.6:
                faltando = sorted(visivel - extraido)[:15]
                p.append(f"CONTEUDO_PERDIDO: só {cobertura:.0%} das palavras visíveis foram extraídas "
                         f"(faltando, ex.: {', '.join(faltando)})")
        if area.get("imgs") and not midias.get("imagens") and not midias.get("videos"):
            p.append(f"IMAGENS_IGNORADAS: a página mostra {area['imgs']} imagem(ns) que não entraram em 'midias'")
        if area.get("iframes"):
            p.append(f"IFRAME: a resposta tem {area['iframes']} iframe(s) (conteúdo embutido não tratado)")
        if area.get("tabelas") and "|" not in bruto:
            p.append("TABELA_PERDIDA: a página tem tabela e ela não apareceu no markdown")
    return p


def slug(t):
    t = re.sub(r"[^a-z0-9]+", "-", t.lower().encode("ascii", "ignore").decode())
    return t.strip("-")[:40] or "pergunta"


def main():
    ap = argparse.ArgumentParser(description="Roda os testes do extrator do Modo IA do Google.")
    ap.add_argument("--sem-instrucao", action="store_true", help="também testa cada pergunta sem a instrução de JSON")
    ap.add_argument("--so-sem-instrucao", action="store_true", help="testa SÓ sem a instrução")
    ap.add_argument("--categorias", default="", help="ex.: video,imagem,tabela")
    ap.add_argument("--limite", type=int, default=0, help="roda só os N primeiros testes")
    ap.add_argument("--arquivo", default="", help="arquivo .txt com perguntas (uma por linha)")
    ap.add_argument("--pausa", type=float, default=6, help="segundos entre perguntas (evita captcha)")
    ap.add_argument("--invisivel", action="store_true", help="navegador escondido")
    ap.add_argument("--timeout", type=int, default=120, help="tempo limite de cada resposta (s)")
    ap.add_argument("--conversas-separadas", action="store_true",
                    help="abre uma conversa nova para cada teste (padrão: tudo numa conversa só, menos captcha)")
    ap.add_argument("--max-por-conversa", type=int, default=25, help="perguntas por conversa antes de abrir outra")
    a = ap.parse_args()

    testes = TESTES
    if a.arquivo:
        linhas = Path(a.arquivo).read_text(encoding="utf-8").splitlines()
        testes = [("arquivo", l.strip()) for l in linhas if l.strip() and not l.startswith("#")]
    if a.categorias:
        cats = {c.strip() for c in a.categorias.split(",")}
        testes = [t for t in testes if t[0] in cats]
    if a.limite:
        testes = testes[:a.limite]

    modos = [False] if a.so_sem_instrucao else ([True, False] if a.sem_instrucao else [True])
    execucoes = [(cat, q, modo) for cat, q in testes for modo in modos]
    total = sum(len(q) if isinstance(q, list) else 1 for _, q, _ in execucoes)

    pasta = BASE / f"falhas_{time.strftime('%Y%m%d-%H%M')}"
    falhas, ok, n = [], 0, 0
    inicio = time.time()

    print(f"\n🔎 {total} perguntas ({len(execucoes)} testes). Navegador {'invisível' if a.invisivel else 'visível'}.")
    print(f"   Modo: {'uma conversa por teste' if a.conversas_separadas else 'conversa única (menos captcha)'}.")
    print("   Se aparecer CAPTCHA, resolva na janela do navegador: o teste espera e continua sozinho.")
    print("   Ctrl+C para parar.\n")

    ia = GoogleIA(headless=a.invisivel, timeout_resposta=a.timeout, interativo=False, espera_captcha=0,
                  max_perguntas_conversa=a.max_por_conversa,
                  log=lambda msg, nivel="info": print(f"      · {msg}")
                  if nivel in ("aviso", "erro") or "aptcha" in msg else None)
    try:
        ia.abrir()
    except Exception as e:
        err = classificar_erro(e)
        print(f"❌ Não consegui abrir o navegador: [{err.codigo}] {err.mensagem}\n   {err.dica}")
        if err.codigo == "PERFIL_EM_USO":
            print("   (Feche o app.py e outras janelas do programa antes de rodar os testes.)")
        sys.exit(1)

    def salvar_falha(nome, r, problemas, pergunta, cat, modo, erro_tb=""):
        pasta.mkdir(exist_ok=True)
        arqs = ia.salvar_print(pasta / nome)
        if r is not None:
            (pasta / f"{nome}.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
            arqs["json"] = str(pasta / f"{nome}.json")
        falhas.append({"nome": nome, "pergunta": pergunta, "categoria": cat,
                       "modo": "com instrução JSON" if modo else "sem instrução",
                       "problemas": problemas, "arquivos": [Path(x).name for x in arqs.values()],
                       "erro": erro_tb})

    try:
        for cat, perguntas, modo in execucoes:
            sequencia = perguntas if isinstance(perguntas, list) else [perguntas]
            if a.conversas_separadas:
                ia.nova_conversa()
            for i, pergunta in enumerate(sequencia):
                n += 1
                rotulo = f"[{n}/{total}] ({cat}{'' if modo else ', sem instrução'}) {pergunta}"
                print(rotulo)
                nome = f"{n:02d}_{cat}{'' if modo else '_sem'}_{slug(pergunta)}"
                t0 = time.time()
                try:
                    r = ia.perguntar(pergunta, usar_instrucao=modo)
                    try:
                        area = ia.page.evaluate(JS_TEXTO_AREA, SEL)
                    except Exception:
                        area = None
                    problemas = verificar(r, cat, modo, area)
                    if i > 0 and cat == "conversa" and r.get("pergunta") == pergunta and not r.get("resposta_completa"):
                        problemas.append("CONVERSA: a pergunta de acompanhamento não teve resposta")
                    if problemas:
                        print(f"   ⚠️  {len(problemas)} problema(s) ({time.time() - t0:.0f}s):")
                        for prob in problemas:
                            print(f"      - {prob}")
                        salvar_falha(nome, r, problemas, pergunta, cat, modo)
                    else:
                        ok += 1
                        extra = f", {r['tentativas']} tentativas" if r.get("tentativas", 1) > 1 else ""
                        print(f"   ✅ ok ({time.time() - t0:.0f}s, {len(r['fontes'])} fontes{extra})")
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    err = classificar_erro(e)
                    print(f"   ❌ [{err.codigo}] {err.mensagem}")
                    salvar_falha(nome, None, [f"ERRO {err.codigo}: {err.mensagem}", f"Dica: {err.dica}"],
                                 pergunta, cat, modo, traceback.format_exc()[-3000:])
                    ia.nova_conversa()
                    if err.codigo in ("NAVEGADOR_FECHADO",):
                        ia.fechar()
                        ia.abrir()
                    break  # numa conversa, não adianta seguir se uma pergunta falhou
                if n < total:
                    time.sleep(a.pausa)
    except KeyboardInterrupt:
        print("\n⏹  Interrompido. Gerando relatório do que já foi testado…")
    finally:
        ia.fechar()

    dur = time.time() - inicio
    print("\n" + "=" * 60)
    if not falhas:
        print(f"✅ Tudo certo! {ok} de {n} perguntas passaram sem problemas ({dur / 60:.1f} min).")
        print("   Nenhum arquivo foi gerado.")
        return

    # ---- relatório ----
    linhas = [
        "RELATÓRIO DE TESTES — extrator do Modo IA do Google",
        f"Data: {time.strftime('%Y-%m-%d %H:%M')}   Duração: {dur / 60:.1f} min",
        f"Perguntas testadas: {n}   OK: {ok}   Com problema: {len(falhas)}",
        "",
        "Cada teste com problema tem arquivos com o mesmo prefixo (ex.: 03_numero_...):",
        "  .html = página do Google no momento   .png = print da tela   .json = resultado que o sistema gerou",
        "",
    ]
    contagem = {}
    for f in falhas:
        for prob in f["problemas"]:
            if prob.startswith("Dica:"):
                continue
            cod = prob.split(":")[0].replace("ERRO ", "")
            contagem[cod] = contagem.get(cod, 0) + 1
    linhas.append("RESUMO POR TIPO DE PROBLEMA:")
    for cod, qtd in sorted(contagem.items(), key=lambda x: -x[1]):
        linhas.append(f"  {qtd:3d}x  {cod}")
    linhas.append("")
    for f in falhas:
        linhas += [
            "-" * 70,
            f"TESTE: {f['nome']}",
            f"Pergunta:  {f['pergunta']}",
            f"Categoria: {f['categoria']}   Modo: {f['modo']}",
            "Problemas:",
            *[f"  - {p}" for p in f["problemas"]],
            "Arquivos:  " + ", ".join(f["arquivos"]),
        ]
        if f["erro"]:
            linhas += ["Traceback:", f["erro"]]
        linhas.append("")
    (pasta / "RELATORIO.txt").write_text("\n".join(linhas), encoding="utf-8")

    zip_path = pasta.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for arq in sorted(pasta.iterdir()):
            z.write(arq, f"{pasta.name}/{arq.name}")
    tamanho = zip_path.stat().st_size / 1024 / 1024

    print(f"⚠️  {len(falhas)} de {n} perguntas com formato inesperado ({dur / 60:.1f} min).")
    for cod, qtd in sorted(contagem.items(), key=lambda x: -x[1]):
        print(f"   {qtd}x {cod}")
    print(f"\n📦 Mande este arquivo: {zip_path}  ({tamanho:.1f} MB)")
    print(f"   (pasta com os arquivos: {pasta})")


if __name__ == "__main__":
    main()
