# 12 · Fontes

As fontes dos destaques, das legendas, das cenas e dos textos ficam em `assets/fonts/dp/`. Cada fonte tem a
**família interna** renomeada para `DP <Nome>` (por exemplo `DP Anton`). É assim que o libass (o ffmpeg) e o
navegador acham a **mesma** letra, e a prévia sai igual ao vídeo.

Lista (chave → família): `python dp_guia.py listar fontes`.

## Sem programar: um comando

Precisa do fontTools uma vez: `pip install fonttools`.

```bash
python dp_guia.py fonte "C:\Downloads\Kanit-Bold.ttf" --chave kanit --nome "Kanit"
python dp_guia.py fonte "C:\Downloads\Kanit-Regular.ttf" --chave kanit --nome "Kanit"
python dp_guia.py fonte "C:\Downloads\Kanit-Italic.ttf" --chave kanit --nome "Kanit"
```

O comando:

1. renomeia a família para **DP Kanit**;
2. salva em `assets/fonts/dp/kanit-Bold.ttf` (e -Regular, -Italic);
3. registra em `assets/darkplanner/extras/fontes.json`.

O estilo (Bold/Regular/Italic) é detectado pelo arquivo, ou você força com `--estilo Bold`. Os destaques usam o
**Bold** quando ele existe.

Depois, reinicie o site. A fonte já pode ser usada:

- num destaque seu: `"tipografia": {"fonte": "kanit"}`;
- no seletor de fonte da aba 📝 Legendas e no painel ✍ do destaque.

Use fontes com licença que permita usar em vídeo, como as do Google Fonts (OFL). Os `.ttf` e os `.otf` com contornos
TrueType funcionam melhor no libass.

## Com código (fonte "de fábrica")

1. Renomeie a família (o comando acima faz isso) e ponha o `.ttf` em `assets/fonts/dp`.
2. Acrescente em `assets/fonts/dp/fontes.json` e em `dp_destaques._FONTE` (`"chave": "DP Nome"`). Se for estreita,
   acrescente também em `_CONDENSADAS`.
