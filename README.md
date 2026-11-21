# Empório da Música

Assistente de atendimento ao cliente em Python para a loja fictícia Empório da Música, em Campo Grande, MS. O projeto separa dados operacionais de texto livre desde a ingestão. Catálogo, promoções, clientes e pedidos ficam em SQLite acessado via SQLAlchemy ORM para consulta exata. O manual de políticas em PDF usa embeddings do Gemini e busca vetorial por similaridade de cosseno.

Feito por Diogo de Souza em [diogo.sh](https://diogo.sh).

## Como rodar

O projeto exige Python 3.12 ou superior e [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env
```

Preencha `GEMINI_API_KEY` no arquivo `.env` e execute os testes.

```bash
uv run pytest -v
uv run ruff check src tests
```

## Como funciona

- **Ingestão por upload.** A base começa vazia e recebe os arquivos em dois envios independentes. Um envio carrega os seis CSVs operacionais em `ingest_store_csvs`. O outro carrega o PDF de políticas em `ingest_policy_pdf`. Reenviar um arquivo não apaga o outro nem as conversas salvas. Os arquivos originais permanecem intactos em [`data/raw/`](data/raw/).
- **Sanitização auditável.** Os CSVs brutos contêm seis produtos com marca ou ficha técnica trocada na descrição (`135`, `137`, `139`, `140`, `142` e `144`), um produto descontinuado com estoque 13 (`136`), um pré-lançamento em pedidos antigos (`130`) e um e-mail repetido entre os clientes `11` e `43`. O manual lista dois telefones diferentes, `(67) 3341-4444` e `(67) 3321-4500`, e um e-mail com acento. O ETL prioriza nome e `specs`, zera o estoque descontinuado, mantém itens históricos como não vendáveis e grava cada ajuste em `etl_audit_log`.
- **ORM no catálogo e RAG vetorial no manual.** Preço, estoque e pedido saem de consultas tipadas no SQLAlchemy sobre SQLite. O manual em PDF é dividido por seção e subseção, recebe embeddings do Gemini na ingestão e é consultado por similaridade de cosseno, com busca por palavras em Python como fallback se a API falhar.
- **Núcleo desacoplado.** Regras de PIX, parcelamento, frete, verificação de pedidos e prazo de devolução ficam em Python fora do prompt. O núcleo depende apenas de interfaces enxutas para armazenamento, embeddings e canais. Assim a equipe pode adicionar ou remover adaptadores como web ou WhatsApp sem alterar o agente.

## Limitações e próximos passos

- **Escala vetorial.** Guardar embeddings no SQLite funciona bem para poucos documentos e evita subir mais um serviço. Para grandes volumes, o mesmo contrato de busca migraria para um serviço especializado em vetores.
- **Avaliação automatizada.** Hoje o repositório cobre ETL, regras de negócio e repositório com testes unitários. Com mais tempo, entraria uma suíte fixa de cenários reais e adversariais para medir regressões.
- **Novos canais.** A interface web entra como adaptador fino sobre o núcleo do agente. Adicionar ou remover um canal como WhatsApp exige apenas um novo adaptador de entrada e saída.

## Uso de assistentes de IA

Usei assistentes de IA no design da interface no Paper, na escrita incremental de módulos e testes e na revisão de texto. Defini e revisei manualmente as decisões de arquitetura, os cortes de escopo e o tratamento de cada anomalia dos dados antes dos commits.
