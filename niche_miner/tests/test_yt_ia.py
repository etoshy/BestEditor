"""Prompts e validadores das análises por IA (yt_ia.py), com dados no formato real (saída de yt_api contra a API falsa)."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import fake_yt_api as F
import yt_api as Y
import yt_ia as I

V = F.vid_id


def ida_e_volta(x):
    """O navegador devolve os dados ao servidor como JSON: simula essa viagem."""
    return json.loads(json.dumps(x))


class Base(unittest.TestCase):
    def setUp(self):
        self.f = F.mundo()
        p = mock.patch.object(Y, "_urlopen", self.f)
        p.start()
        self.addCleanup(p.stop)

    def cli(self):
        return Y.Cliente(F.CHAVE)

    def em_alta(self):
        return ida_e_volta(Y.em_alta(self.cli(), "BR", "", F.AGORA))


class PromptOportunidadesTests(Base):
    def test_lista_os_videos_com_indice_canal_views_engajamento_e_idade(self):
        p = I.prompt_oportunidades(self.em_alta())
        self.assertIn("canal dark (faceless)", p)
        self.assertIn("Vídeos em alta em BR", p)
        self.assertIn('1. "Trailer curto de Roma" — canal "Canal Beta" (120.000 inscritos) — 1.200.000 views — engajamento 5,42% — 0min58s — há 4 dias', p)
        self.assertIn('canal "Canal Gama" (inscritos ocultos)', p)                             # não "(? inscritos)"
        self.assertNotIn("(? inscritos)", p)
        self.assertIn("(5):", p)
        self.assertIn('"nichos_em_alta"', p)
        self.assertIn("SOMENTE com a lista abaixo", p)
        self.assertIn("sem evidência nos dados", p)
        self.assertIn("canais pequenos com views altas", p)

    def test_numeros_usam_ponto_de_milhar_e_virgula_decimal_sem_misturar(self):
        p = I.prompt_oportunidades(self.em_alta())
        self.assertNotRegex(p, r"engajamento \d+\.\d+%")

    def test_limita_a_40_videos_e_exige_pelo_menos_um(self):
        muitos = {"videos": [{"titulo": f"v{i}", "views": i} for i in range(80)], "canais": {}}
        p = I.prompt_oportunidades(muitos)
        self.assertIn("(40):", p)
        self.assertIn('\n40. "v39"', p)
        self.assertNotIn('41. "', p)
        for vazio in (None, {}, {"videos": []}, {"videos": "x"}, [1, 2], {"videos": [1, "a"]}):
            with self.assertRaises(ValueError, msg=repr(vazio)):
                I.prompt_oportunidades(vazio)

    def test_contexto_entra_e_e_cortado(self):
        p = I.prompt_oportunidades(self.em_alta(), "Quero um canal dark de história, 3 vídeos por semana")
        self.assertIn("Contexto que o usuário informou: Quero um canal dark de história", p)
        gigante = I.prompt_oportunidades(self.em_alta(), "x" * 9000)
        self.assertLess(len(gigante), len(p) + I.MAX_CONTEXTO + 5)
        self.assertNotIn("Contexto que o usuário informou", I.prompt_oportunidades(self.em_alta(), "   "))

    def test_dados_com_tipos_errados_nao_derrubam(self):
        sujo = {"videos": [{"titulo": None, "views": "abc", "engajamento": "x", "duracao_seg": "y", "idade_dias": None, "canal": 7, "canal_id": 5}], "canais": {"5": "lixo"}}
        p = I.prompt_oportunidades(sujo)
        self.assertIn("? views", p)


class PromptComparativoTests(Base):
    def dados(self):
        return ida_e_volta(Y.comparar(self.cli(), "@alfa", "@beta", F.AGORA))

    def test_traz_os_dois_canais_os_numeros_lado_a_lado_e_os_videos_mais_vistos(self):
        p = I.prompt_comparativo(self.dados())
        self.assertIn('CANAL A\nCanal: "Canal Alfa"; @alfa; inscritos: 8.500', p)
        self.assertIn('CANAL B\nCanal: "Canal Beta"; @beta; inscritos: 120.000', p)
        self.assertIn("- Inscritos: A = 8.500, B = 120.000", p)
        self.assertIn("- Tração (mediana ÷ inscritos): A = 0,88, B = 3,33", p)
        self.assertIn('1. "Sêneca em 45 segundos"', p)                                       # o mais visto de A vem primeiro
        self.assertIn("mediana, tração e engajamento", p)
        self.assertIn('"forcas_a"', p)

    def test_faltando_um_canal_da_erro(self):
        d = self.dados()
        for ruim in (None, {}, {"a": d["a"]}, {"a": d["a"], "b": {}}):
            with self.assertRaises(ValueError, msg=repr(ruim)):
                I.prompt_comparativo(ruim)


class PromptDossieEEngenhariaTests(Base):
    def test_dossie_leva_descricao_e_palavras_chave_e_avisa_que_nao_viu_os_videos(self):
        d = ida_e_volta(Y.analisar_canal(self.cli(), "@alfa", F.AGORA))
        p = I.prompt_dossie(d, "Quero entender se vale competir")
        self.assertIn('Canal: "Canal Alfa"', p)
        self.assertIn("views por vídeo (total ÷ vídeos): 10.000", p)
        self.assertIn("Inscritos por vídeo: 212", p)
        self.assertIn("Descrição do canal: Descrição de Canal Alfa", p)
        self.assertIn("Palavras-chave do canal: estoicismo, vida diária, calma", p)
        self.assertIn("Quero entender se vale competir", p)
        self.assertIn("você NÃO viu os vídeos", p)
        with self.assertRaises(ValueError):
            I.prompt_dossie({}, "")

    def test_engenharia_com_transcricao_e_cortada_no_limite(self):
        d = ida_e_volta(Y.analisar_video(self.cli(), V(2), F.AGORA))
        p = I.prompt_engenharia(d, "Olá pessoal, hoje vamos falar de estoicismo. " * 5)
        self.assertIn('Título: "12 lições estoicas para ouvir toda manhã"', p)
        self.assertIn("9.000 views, 700 likes, 90 comentários, engajamento 8,78%", p)
        self.assertIn("Duração: 10min00s; publicado em 2026-09-15", p)
        self.assertIn("Views ÷ inscritos do canal: 1,06", p)
        self.assertIn("Tópicos do YouTube: Philosophy, Knowledge", p)
        self.assertIn("Transcrição do vídeo:\nOlá pessoal", p)
        self.assertNotIn("SEM TRANSCRIÇÃO", p)
        longa = I.prompt_engenharia(d, "palavra " * 10000)
        self.assertLess(len(longa), I.MAX_TRANSCRICAO + 6000)

    def test_engenharia_sem_transcricao_manda_marcar_como_hipotese(self):
        d = ida_e_volta(Y.analisar_video(self.cli(), V(2), F.AGORA))
        for vazia in ("", "   ", None):
            p = I.prompt_engenharia(d, vazia)
            self.assertIn("SEM TRANSCRIÇÃO", p)
            self.assertIn("marque como hipótese", p)
        with self.assertRaises(ValueError):
            I.prompt_engenharia({}, "texto")


class PromptAuditoriaTests(Base):
    def test_historico_vai_do_mais_antigo_ao_mais_novo(self):
        d = ida_e_volta(Y.historico(self.cli(), "@alfa", 30, F.AGORA))
        p = I.prompt_auditoria(d, "Canal parado há um mês")
        historico = p.split("Histórico, do mais antigo ao mais novo (6 vídeos):\n")[1].split("\n\n")[0].splitlines()
        self.assertTrue(historico[0].startswith('1. "Como controlar suas emoções"'))         # 34 dias atrás
        self.assertTrue(historico[-1].startswith('6. "Como ter um dia mais produtivo"'))      # 3 dias atrás
        self.assertIn("Nos 6 vídeos lidos: mediana de views 7.500, média 9.400, engajamento médio 7,98%", p)
        self.assertIn("Canal parado há um mês", p)
        self.assertIn("Vídeos recentes ainda estão juntando views", p)

    def test_menos_de_3_videos_nao_da_auditoria(self):
        d = ida_e_volta(Y.historico(self.cli(), "@alfa", 30, F.AGORA))
        d["videos"] = d["videos"][:2]
        with self.assertRaisesRegex(ValueError, "pelo menos 3"):
            I.prompt_auditoria(d)
        with self.assertRaises(ValueError):
            I.prompt_auditoria(None)

    def test_datas_de_tipo_errado_nao_derrubam_a_ordenacao(self):
        d = ida_e_volta(Y.historico(self.cli(), "@alfa", 30, F.AGORA))
        d["videos"][0]["publicado"] = 123
        d["videos"][1]["views"] = "abc"
        self.assertIn("Histórico", I.prompt_auditoria(d))


class DespachoTests(Base):
    def test_montar_prompt_por_tipo_e_tipo_desconhecido(self):
        self.assertEqual(sorted(I.TIPOS), sorted(I.VALIDADORES))
        self.assertIn("nichos_em_alta", I.montar_prompt("oportunidades", self.em_alta()))
        with self.assertRaisesRegex(ValueError, "desconhecido"):
            I.montar_prompt("outro", {})

    def test_todo_prompt_manda_dizer_sem_evidencia_e_proibe_inventar_numero(self):
        entradas = {"oportunidades": self.em_alta(), "comparativo": ida_e_volta(Y.comparar(self.cli(), "@alfa", "@beta", F.AGORA)),
                    "dossie": ida_e_volta(Y.analisar_canal(self.cli(), "@alfa", F.AGORA)), "engenharia": ida_e_volta(Y.analisar_video(self.cli(), V(2), F.AGORA)),
                    "auditoria": ida_e_volta(Y.historico(self.cli(), "@alfa", 30, F.AGORA))}
        for tipo, dados in entradas.items():
            p = I.montar_prompt(tipo, dados)
            self.assertIn("sem evidência nos dados", p, tipo)
            self.assertIn("NÃO invente números", p, tipo)
            self.assertIn("ESTRITAMENTE em JSON", p, tipo)
            self.assertNotIn("Regras: Regras:", p, tipo)
            self.assertNotRegex(p, r"Regras:[^\n]*\bRegras:", tipo)


class ValidacaoTests(unittest.TestCase):
    def test_oportunidades_normaliza_indices_e_descarta_o_que_nao_e_da_lista(self):
        texto = "Segue:\n```json\n" + json.dumps({
            "Leitura_Geral": "Roma e filosofia dominam",
            "nichos_em_alta": [{"nicho": "História de Roma", "por_que": "3 vídeos com mais de 300 mil views", "evidencia": [1, "2", "vídeo 3", 99, 0, 1], "dificuldade": "media", "risco": "nicho cheio"}, {"nicho": ""}],
            "oportunidades_dark": [{"oportunidade": "Roma em animação", "formato": "animação 2D", "como_produzir": "IA + narração", "titulo": "Roma em 8 minutos", "evidencia": "2"}],
            "canais_pequenos_em_destaque": [{"indice": "vídeo 4", "por_que": "10 mil inscritos e 30 mil views"}, {"indice": 99, "por_que": "fora"}, {"por_que": "sem índice"}],
            "ressalvas": "amostra pequena; só 5 vídeos"}) + "\n```"
        o = I.validar_oportunidades(texto, n_videos=5)
        self.assertEqual(o["leitura_geral"], "Roma e filosofia dominam")
        self.assertEqual(o["nichos_em_alta"], [{"nicho": "História de Roma", "por_que_esta_em_alta": "3 vídeos com mais de 300 mil views", "dificuldade": "media", "risco": "nicho cheio", "evidencia": [1, 2, 3]}])
        self.assertEqual(o["oportunidades_dark"][0]["ideia"], "Roma em animação")
        self.assertEqual(o["oportunidades_dark"][0]["evidencia"], [2])
        self.assertEqual(o["canais_pequenos_em_destaque"], [{"indice": 4, "por_que_chama_atencao": "10 mil inscritos e 30 mil views"}])
        self.assertEqual(o["ressalvas"], ["amostra pequena", "só 5 vídeos"])

    def test_comparativo(self):
        c = I.validar_comparativo(json.dumps({"resumo": "B é maior", "forcas_a": ["engajamento"], "forcas_b": "alcance; frequência",
                                              "diferencas_de_estrategia": [{"tema": "Duração", "a": "10 min", "b": "35 min"}, {"tema": ""}, {"a": "sem tema"}],
                                              "oportunidades_para_competir": [{"oportunidade": "Roma curto", "como": "vídeos de 8 min"}], "veredito": "Copiar a frequência do B", "ressalvas": []}))
        self.assertEqual((c["forcas_a"], c["forcas_b"]), (["engajamento"], ["alcance", "frequência"]))
        self.assertEqual(c["diferencas_de_estrategia"], [{"tema": "Duração", "a": "10 min", "b": "35 min"}])
        self.assertEqual(c["oportunidades_para_competir"], [{"oportunidade": "Roma curto", "como": "vídeos de 8 min"}])
        self.assertEqual(c["veredito"], "Copiar a frequência do B")

    def test_dossie(self):
        d = I.validar_dossie(json.dumps({"resumo": "Canal de filosofia", "publico": "Adultos", "pontos_fortes": ["nicho claro"], "pontos_fracos": ["pouco volume"],
                                         "oportunidades": [{"oportunidade": "Séries", "como": "agrupar por tema"}, "Shorts"], "proximos_passos": ["testar 3 títulos"]}))
        self.assertEqual(d["publico"], "Adultos")
        self.assertEqual([o["oportunidade"] for o in d["oportunidades"]], ["Séries", "Shorts"])
        self.assertEqual(d["oportunidades"][0]["como_aproveitar"], "agrupar por tema")

    def test_engenharia_com_objeto_aninhado_e_estrutura(self):
        e = I.validar_engenharia(json.dumps({"resumo": "Lista numerada", "gancho": {"tecnica": "Pergunta", "como_funciona": "abre uma dúvida"}, "promessa": "12 lições",
                                             "estrutura": [{"trecho": "0:00 abertura", "funcao": "gancho", "tecnica": "pergunta"}, {"parte": "lições", "funcao": "entrega"}, {"funcao": "sem trecho"}],
                                             "retencao": ["loops abertos"], "tom": "calmo", "cta": "inscreva-se", "o_que_replicar": ["lista numerada"], "o_que_evitar": []}))
        self.assertEqual(e["gancho"], {"tecnica": "Pergunta", "como_funciona": "abre uma dúvida"})
        self.assertEqual([x["trecho"] for x in e["estrutura"]], ["0:00 abertura", "lições"])
        self.assertEqual(e["tom_e_ritmo"], "calmo")

    def test_auditoria_com_evidencias_numericas(self):
        a = I.validar_auditoria(json.dumps({"resumo": "Crescimento em degraus", "fases": [{"periodo": "abril a junho", "o_que_aconteceu": "canal pequeno", "evidencia": [1, 2, 60]}],
                                            "padroes": [{"padrao": "listas rendem mais", "evidencia": "3, 5"}], "pontos_de_virada": [{"quando": "julho", "o_que_mudou": "títulos com número", "evidencia": [4]}],
                                            "recomendacoes": [{"acao": "publicar 2 por semana", "por_que": "hoje é 1"}]}), n_videos=6)
        self.assertEqual(a["fases"][0]["evidencia"], [1, 2])                                    # 60 está fora da lista de 6
        self.assertEqual(a["padroes"][0]["evidencia"], [3])
        self.assertEqual(a["pontos_de_virada"][0]["quando"], "julho")
        self.assertEqual(a["recomendacoes"][0], {"acao": "publicar 2 por semana", "por_que": "hoje é 1"})

    def test_resposta_ruim_da_erro_em_portugues_em_todos_os_tipos(self):
        for tipo, validar in I.VALIDADORES.items():
            for lixo in ("", "isto não é json", "{}", '{"foo": 1}', "[1, 2]", '{"resumo": "", "ressalvas": []}'):
                with self.assertRaises(ValueError, msg=(tipo, lixo)):
                    validar(lixo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
