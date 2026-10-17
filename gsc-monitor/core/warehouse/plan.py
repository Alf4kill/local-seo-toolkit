"""
plan.py — Planejamento da ingestão do acervo (lógica PURA, sem rede e sem sqlite).

Concentra tudo que decide *o que pedir à API*: o registro de grãos, a matemática
de datas, o agrupamento em lotes e a montagem do corpo da searchanalytics.query.
Por ser puro, `acervo.py --dry-run` imprime o plano inteiro sem nunca construir
o objeto `service` — e os testes cobrem essa camada sem mock de rede.

Duas alavancas de desenho estão aqui:

1. `date` vem SEMPRE na frente das dimensões. É isso que colapsa N dias numa
   requisição: ["date","query"] sobre 30 dias devolve a série diária de 30 dias
   de uma vez, em vez de 30 chamadas.

2. O tamanho do lote é CONSERVADOR por default (config.ACERVO_DIAS_LOTE).
   A doc do Google diz que a API "exposes a maximum of 50K rows of data per day
   per search type", mas não diz se esse teto vale por dia DENTRO da consulta ou
   por consulta — e as fontes de terceiros se contradizem. `acervo.py aferir`
   mede isso empiricamente num site real antes de subir os lotes.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from config import (
    ACERVO_ASSENTAMENTO_DIAS,
    ACERVO_DIAS_BACKFILL,
    ACERVO_DIAS_LOTE,
    ACERVO_TETO_DIA_TIPO,
    GSC_DELAY_DAYS,
    ROW_LIMIT,
)

# ---------------------------------------------------------------------------
# Registro de grãos
# ---------------------------------------------------------------------------
#
# Chaves de cada grão:
#   dimensoes — o que vai em `dimensions` na requisição (date SEMPRE primeiro)
#   tabela    — tabela de fato destino
#   colunas   — colunas de chave além de (propriedade, tipo, data), na MESMA
#               ordem de dimensoes[1:] (mapeamento posicional com `keys`)
#   internar  — {coluna: dimensão internada} p/ dim_pagina / dim_query
#   fixo      — o valor da chave NÃO vem de `keys`, vem do filtro da requisição
#               (caso da aparência, que a API não deixa agrupar com outra
#               dimensão — ver `filtro_aparencia`)
#   primeiro  — ingerir antes dos outros (o total é a régua de cobertura)
#   sem_query — a API não aceita a dimensão `query` para estes `type`
GRAOS: dict = {
    "total": {
        "dimensoes": ("date",),
        "tabela": "fato_total",
        "colunas": (),
        "internar": {},
        "primeiro": True,
    },
    "pagina": {
        "dimensoes": ("date", "page"),
        "tabela": "fato_pagina",
        "colunas": ("pagina_id",),
        "internar": {"pagina_id": "pagina"},
    },
    "query": {
        "dimensoes": ("date", "query"),
        "tabela": "fato_query",
        "colunas": ("query_id",),
        "internar": {"query_id": "query"},
        "sem_query": True,
    },
    "query_pagina": {
        "dimensoes": ("date", "query", "page"),
        "tabela": "fato_query_pagina",
        "colunas": ("query_id", "pagina_id"),
        "internar": {"query_id": "query", "pagina_id": "pagina"},
        "sem_query": True,
    },
    "dispositivo": {
        "dimensoes": ("date", "device"),
        "tabela": "fato_dispositivo",
        "colunas": ("dispositivo",),
        "internar": {},
    },
    "pais": {
        "dimensoes": ("date", "country"),
        "tabela": "fato_pais",
        "colunas": ("pais",),
        "internar": {},
    },
    # Aparência é o único grão de 2 etapas: a doc oficial diz que
    # "Search appearance is not available as a column along with any other
    # dimensions". Etapa 1 lista os tipos (["searchAppearance"] sozinho), etapa 2
    # pede ["date"] filtrando por cada tipo. Por isso dimensoes é só ("date",) e
    # o valor da coluna vem do filtro (fixo=True).
    "aparencia": {
        "dimensoes": ("date",),
        "tabela": "fato_aparencia",
        "colunas": ("aparencia",),
        "internar": {},
        "fixo": True,
    },
}

# P7.1: os seis grãos que não precisam de dimensionFilterGroups. `aparencia`
# entra na P7.4 junto com o fan-out de `type`.
GRAOS_PADRAO = ("total", "pagina", "query", "query_pagina", "dispositivo", "pais")
GRAOS_TODOS = tuple(GRAOS)

# `type` aceitos pela API (confirmado na doc). NÃO existe valor de IA:
# o relatório de "desempenho de IA generativa" do GSC é só da interface.
TIPOS_VALIDOS = ("web", "image", "video", "news", "discover", "googleNews")
# discover e googleNews não suportam a dimensão `query`.
TIPOS_SEM_QUERY = ("discover", "googleNews")

ESTADO_FINAL = "final"
ESTADO_PROVISORIO = "final_provisorio"
ESTADO_FRESCO = "all"


@dataclass(frozen=True)
class Passo:
    """Uma unidade de trabalho: um grão, um tipo, um lote de dias contíguos.

    Tudo que toca a rede consome um Passo + `montar_corpo`, nunca argumentos
    soltos — é o que permite imprimir o plano sem executá-lo.
    """

    grao: str
    tipo: str
    dimensoes: tuple
    inicio: str
    fim: str
    dias: tuple
    data_state: str
    filtros: "list | None" = None
    aparencia: "str | None" = None


# ---------------------------------------------------------------------------
# Datas
# ---------------------------------------------------------------------------


def intervalo_datas(
    dias: int = ACERVO_DIAS_BACKFILL,
    *,
    hoje: "date | None" = None,
    atraso: int = GSC_DELAY_DAYS,
) -> tuple:
    """(inicio, fim) ISO da janela de backfill.

    `fim = hoje - atraso` pela mesma razão de
    fetchers/position_fetcher._build_date_range: o GSC atrasa 2-3 dias.
    `hoje` é injetável para os testes serem determinísticos e para um backfill
    iniciado antes da meia-noite não calcular duas janelas diferentes.
    """
    base = hoje or date.today()
    fim = base - timedelta(days=atraso)
    inicio = fim - timedelta(days=dias)
    return inicio.isoformat(), fim.isoformat()


def listar_dias(inicio: str, fim: str) -> list:
    """Todos os dias ISO de `inicio` a `fim`, INCLUSIVE nas duas pontas."""
    d0 = date.fromisoformat(inicio)
    d1 = date.fromisoformat(fim)
    if d1 < d0:
        return []
    return [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def agrupar_em_lotes(dias: list, tamanho: int) -> list:
    """Agrupa dias em lotes de no máximo `tamanho`, SEM juntar por cima de um gap.

    Um lote tem de ser um intervalo contíguo, porque a requisição é
    startDate..endDate: juntar 10/01 com 20/01 no mesmo lote traria os 10 dias
    do meio, que já estão ingeridos — gastando cota e sobrescrevendo sem motivo.
    """
    if tamanho < 1:
        raise ValueError("tamanho de lote tem de ser >= 1")

    lotes: list = []
    atual: list = []
    anterior: date | None = None

    for iso in sorted(dias):
        d = date.fromisoformat(iso)
        quebra_gap = anterior is not None and (d - anterior).days != 1
        if atual and (quebra_gap or len(atual) >= tamanho):
            lotes.append(atual)
            atual = []
        atual.append(iso)
        anterior = d

    if atual:
        lotes.append(atual)
    return lotes


def dia_definitivo(
    dia: str,
    *,
    hoje: "date | None" = None,
    atraso: int = GSC_DELAY_DAYS,
    assentamento: int = ACERVO_ASSENTAMENTO_DIAS,
) -> bool:
    """O GSC já parou de revisar este dia?

    O dado aparece com 2-3 dias de atraso e CONTINUA assentando depois. Só
    passada a soma (atraso + assentamento) ele é tratado como definitivo.
    """
    base = hoje or date.today()
    return (base - date.fromisoformat(dia)).days > atraso + assentamento


def estado_do_dia(
    dia: str,
    *,
    hoje: "date | None" = None,
    atraso: int = GSC_DELAY_DAYS,
    assentamento: int = ACERVO_ASSENTAMENTO_DIAS,
) -> str:
    """'final' se o dia já assentou, 'final_provisorio' se ainda pode mudar."""
    definitivo = dia_definitivo(dia, hoje=hoje, atraso=atraso, assentamento=assentamento)
    return ESTADO_FINAL if definitivo else ESTADO_PROVISORIO


def janela_assentamento(
    *,
    hoje: "date | None" = None,
    atraso: int = GSC_DELAY_DAYS,
    assentamento: int = ACERVO_ASSENTAMENTO_DIAS,
) -> tuple:
    """(inicio, fim) dos dias que o `diario` re-busca em toda execução.

    É EXATAMENTE o conjunto que `dia_definitivo` considera não-definitivo:
    fim    = hoje - atraso                 (o dia mais novo que a API expõe)
    inicio = hoje - atraso - assentamento  (o mais antigo ainda não definitivo)

    As duas funções têm de concordar. Se esta janela for mais larga, o `diario`
    re-pede dias que `dias_pendentes` já considera resolvidos — gasto de cota
    sem ganho; se for mais estreita, dia revisado pelo GSC nunca é corrigido.
    """
    return intervalo_datas(assentamento, hoje=hoje, atraso=atraso)


# ---------------------------------------------------------------------------
# Corpo da requisição
# ---------------------------------------------------------------------------


def montar_corpo(
    inicio: str,
    fim: str,
    dimensoes,
    *,
    tipo: str = "web",
    row_limit: int = ROW_LIMIT,
    start_row: int = 0,
    data_state: str = ESTADO_FINAL,
    filtros: "list | None" = None,
) -> dict:
    """Corpo da searchanalytics.query. Função PURA.

    `startRow` e `dimensionFilterGroups` só entram quando têm valor: 0 e ausente
    são os defaults da API, e enviar o default é ruído que atrapalha diff de
    corpo nos testes e na depuração.

    `dataState` é 'final' por default — o acervo é um arquivo, e dado fresco é
    volátil. A ponta fresca é uma passada separada e explicitamente marcada.
    """
    corpo: dict = {
        "startDate": inicio,
        "endDate": fim,
        "dimensions": list(dimensoes),
        "rowLimit": row_limit,
        "dataState": data_state,
        "type": tipo,
    }
    if start_row:
        corpo["startRow"] = start_row
    if filtros:
        corpo["dimensionFilterGroups"] = filtros
    return corpo


def filtro_aparencia(valor: str) -> list:
    """dimensionFilterGroups que isola um tipo de aparência na etapa 2."""
    return [
        {
            "filters": [
                {
                    "dimension": "searchAppearance",
                    "operator": "equals",
                    "expression": valor,
                }
            ]
        }
    ]


# ---------------------------------------------------------------------------
# Truncamento
# ---------------------------------------------------------------------------


def precisa_dia_a_dia(
    linhas_por_dia: dict,
    *,
    teto: int = ACERVO_TETO_DIA_TIPO,
    margem: float = 0.9,
) -> bool:
    """Algum dia do lote chegou perto do teto documentado (>= 90% de 50k)?

    Se chegou, o lote é refeito dia a dia: só assim dá para saber se o corte foi
    do dia ou da consulta. É o ÚNICO nível de fallback — nesta escala (~340
    linhas/dia) ele nunca dispara, e manter um só nível evita a bisecção
    recursiva que o desenho anterior tinha sem precisar.
    """
    if not linhas_por_dia:
        return False
    return max(linhas_por_dia.values()) >= teto * margem


def dias_no_teto(
    linhas_por_dia: dict,
    *,
    teto: int = ACERVO_TETO_DIA_TIPO,
    margem: float = 0.9,
) -> list:
    """Os dias que chegaram perto do teto — marcados status='teto' e reportados.

    Um dia no teto é um buraco PERMANENTE e VISÍVEL na cobertura, nunca
    silencioso: a cauda longa daquele dia não existe e nenhuma análise deve
    supor que existe.
    """
    return sorted(d for d, n in linhas_por_dia.items() if n >= teto * margem)


# ---------------------------------------------------------------------------
# Plano
# ---------------------------------------------------------------------------


def graos_aplicaveis(graos, tipo: str) -> list:
    """Filtra os grãos que fazem sentido para um `type`, mantendo o total primeiro.

    discover e googleNews não aceitam a dimensão `query`: pedir geraria 400.
    """
    nomes = [g for g in graos if not (tipo in TIPOS_SEM_QUERY and GRAOS[g].get("sem_query"))]
    return sorted(nomes, key=lambda g: (not GRAOS[g].get("primeiro"), list(GRAOS).index(g)))


def montar_passos(
    grao: str,
    tipo: str,
    dias: list,
    *,
    hoje: "date | None" = None,
    tamanho_lote: "int | None" = None,
    data_state: "str | None" = None,
) -> list:
    """Transforma uma lista de dias pendentes nos Passos que os cobrem.

    O `data_state` do passo é o do dia MAIS NOVO do lote: um lote que contém
    qualquer dia ainda assentando é, como um todo, provisório. Conservador de
    propósito — é melhor marcar um dia definitivo como provisório do que o
    contrário.
    """
    if grao not in GRAOS:
        raise ValueError(f"grao desconhecido: {grao}")

    spec = GRAOS[grao]
    tamanho = tamanho_lote or ACERVO_DIAS_LOTE.get(grao, 30)
    passos = []
    for lote in agrupar_em_lotes(dias, tamanho):
        estado = data_state or estado_do_dia(lote[-1], hoje=hoje)
        passos.append(
            Passo(
                grao=grao,
                tipo=tipo,
                dimensoes=spec["dimensoes"],
                inicio=lote[0],
                fim=lote[-1],
                dias=tuple(lote),
                data_state=estado,
            )
        )
    return passos


def estimar_requisicoes(passos: list, linhas_por_dia: "dict | None" = None) -> dict:
    """Estimativa para o --dry-run: requisições e linhas, por grão e total.

    `linhas_por_dia` ({grao: media}) vem da tabela `ingestao` quando o site já
    tem histórico; sem ele a estimativa é só o número de lotes (1 requisição por
    lote, sem paginação). O --dry-run diz qual dos dois usou, para ninguém
    tratar palpite como medição.
    """
    linhas_por_dia = linhas_por_dia or {}
    por_grao: dict = {}
    for p in passos:
        info = por_grao.setdefault(p.grao, {"lotes": 0, "dias": 0, "requisicoes": 0, "linhas": 0})
        media = linhas_por_dia.get(p.grao)
        linhas = int(media * len(p.dias)) if media else 0
        # 1 requisição por lote + as páginas extras de startRow que as linhas
        # estimadas exigirem.
        paginas = 1 + (linhas // ROW_LIMIT if linhas else 0)
        info["lotes"] += 1
        info["dias"] += len(p.dias)
        info["requisicoes"] += paginas
        info["linhas"] += linhas

    total = {
        "requisicoes": sum(i["requisicoes"] for i in por_grao.values()),
        "linhas": sum(i["linhas"] for i in por_grao.values()),
        "lotes": sum(i["lotes"] for i in por_grao.values()),
        "medido": bool(linhas_por_dia),
    }
    return {"por_grao": por_grao, "total": total}
