# Empório da Música

Assistente de atendimento ao cliente em Python para a loja fictícia Empório da Música, em Campo Grande, MS. O projeto separa dados operacionais de texto livre desde a ingestão. Catálogo, promoções, clientes e pedidos ficam em SQLite acessado via SQLAlchemy ORM para consulta exata. O manual de políticas em PDF usa embeddings do Gemini e busca vetorial por similaridade de cosseno.

Feito por Diogo de Souza em [diogo.sh](https://diogo.sh).

## Como rodar

O projeto exige Python 3.12 ou superior, [uv](https://docs.astral.sh/uv/) e Node.js 20 ou superior.

1. Instale as dependências do backend e crie o arquivo de ambiente.

```bash
uv sync
cp .env.example .env
```

2. Preencha `GEMINI_API_KEY` no arquivo `.env` e inicie a API em FastAPI.

```bash
uv run uvicorn emporio.api:create_app --factory --host 127.0.0.1 --port 8000
```

3. Em outro terminal, instale as dependências da interface web e inicie o Vite.

```bash
cd web
npm install
npm run dev
```

4. Acesse `http://127.0.0.1:5173`.

### Perfis de acesso e carga inicial

O banco SQLite começa vazio na primeira execução e cria duas contas iniciais configuráveis pelo `.env`.

- Gestor (`admin@admin.com` e senha `admin123`). Acessa o chat de teste e a tela **Ajustes**, onde envia os arquivos da loja, escolhe qual modelo Gemini 4 responde no atendimento e liga ou desliga cada ferramenta do agente.
- Cliente (`user@user.com` e senha `user123`). Acessa apenas o chat e o modal **Sobre a loja**. Qualquer pessoa pode criar uma conta nova de cliente em **Criar conta**, sem confirmação por e-mail.

Antes de subir em produção, altere `SEED_ADMIN_EMAIL`, `SEED_ADMIN_PASSWORD`, `SEED_USER_EMAIL`, `SEED_USER_PASSWORD` e `AUTH_SECRET` no `.env`.

Para carregar a base da loja, entre como gestor, abra **Ajustes** e envie os arquivos originais de [`data/raw/`](data/raw/).

- Em **Base operacional (CSVs)**, envie os seis arquivos CSV de uma vez ou um `.zip` contendo os seis arquivos.
- Em **Manual de políticas (PDF)**, envie [`políticas_da_loja.pdf`](data/raw/pol%C3%ADticas_da_loja.pdf).

Enquanto os dois envios não forem concluídos, contas de cliente veem apenas a tela **Atendimento indisponível** com telefone e e-mail da equipe, sem expor detalhes internos da base.

### Testes e verificação

Execute os testes automatizados, o linter e o build do frontend a partir da raiz do repositório.

```bash
uv run pytest -v
uv run ruff check src tests
cd web && npm run build
```

## Decisões técnicas

- **Ingestão em dois slots independentes.** A base começa vazia e recebe os seis CSVs em `ingest_store_csvs` e o PDF em `ingest_policy_pdf`. Reenviar um conjunto não apaga o outro nem as conversas salvas. Os arquivos originais ficam intactos em [`data/raw/`](data/raw/).
- **Sanitização auditável.** Os CSVs brutos contêm seis produtos com marca ou ficha técnica trocada na descrição (`135`, `137`, `139`, `140`, `142` e `144`), um produto descontinuado com estoque 13 (`136`), um pré-lançamento presente em pedidos antigos (`130`), um item ativo sem estoque (`96`) e um e-mail repetido entre os clientes `11` e `43`. O PDF lista dois telefones diferentes, `(67) 3341-4444` e `(67) 3321-4500`, e um e-mail com acento. O ETL prioriza nome e `specs`, zera o estoque descontinuado, mantém itens históricos como não vendáveis e registra cada ajuste na tabela `etl_audit_log`.
- **ORM no catálogo e busca vetorial no manual.** Preço, estoque e pedidos saem de consultas tipadas no SQLAlchemy sobre SQLite. O manual em PDF é dividido em 26 trechos por seção e subseção, recebe embeddings `gemini-embedding-001` na ingestão e usa similaridade de cosseno na busca, com fallback por palavras em Python se a API falhar.
- **Regras de negócio fora do prompt.** O cálculo de 5% no PIX não cumulativo com promoções, os valores mínimos de parcela em até 12x sem juros, o frete para Campo Grande e outras cidades, a verificação LGPD de pedidos em dois fatores e o prazo legal de 7 dias para devolução rodam em Python determinístico em [`src/emporio/domain/rules.py`](src/emporio/domain/rules.py).
- **Modelos Gemini 4 e ferramentas controláveis.** O agente usa PydanticAI com streaming de raciocínio e chamadas de ferramenta. Apenas o gestor pode alternar o modelo ativo entre os quatro modelos Gemini 4 (`gemini-4-hydrogen`, `gemini-4-neon`, `gemini-4-carbon` e `gemini-4-argon`) e desativar qualquer uma das cinco ferramentas para testar limites de resposta sem invenção de dados.
- **Núcleo desacoplado de canal.** O agente depende apenas dos contratos em [`src/emporio/ports.py`](src/emporio/ports.py). A API FastAPI e o frontend React atuam como um adaptador fino de entrada e saída, o que permite adicionar ou remover canais como WhatsApp sem reescrever o núcleo.

## Evals

O projeto inclui uma suíte de avaliação em três camadas baseada em [diogo.sh/evals](https://diogo.sh/evals), detalhada em [`evals/README.md`](evals/README.md).

- **Camada determinística sobre o trace.** [`evals/dataset.jsonl`](evals/dataset.jsonl) reúne 16 casos em oito categorias de falha (catálogo curado, disponibilidade, matemática de PIX e frete, recusa de acessórios, LGPD em dois fatores, busca vetorial no manual, ferramenta desativada e isolamento entre perfis). Os avaliadores checam chamadas e argumentos reais no trace além do texto final.
- **Rótulos humanos e calibração do juiz-LLM.** [`evals/human_labels.jsonl`](evals/human_labels.jsonl) contém 14 exemplos rotulados manualmente (`7 PASS` reais e `7 FAIL` da taxonomia). Na calibração com `google:gemini-4-hydrogen`, o juiz binário atingiu 100,0% de concordância, TPR de 100,0%, TNR de 100,0% e kappa de Cohen `1.000`.

```bash
uv run python -m emporio.evals --model google:gemini-4-hydrogen
uv run python -m emporio.evals --validate-judge --model google:gemini-4-hydrogen
uv run python -m emporio.evals --model google:gemini-4-hydrogen --with-judge
```

## Limitações e próximos passos

- **Escala vetorial.** Guardar embeddings no SQLite funciona bem para poucos documentos e evita subir um serviço adicional. Para grandes volumes de texto, o mesmo contrato de busca migraria para um banco vetorial dedicado.
- **Expansão dos evals em produção.** A suíte atual cobre 36 testes unitários e de API mais 16 cenários de eval calibrados com 14 rótulos humanos. Em operação real, novos traces rotulados por humanos alimentariam continuamente a taxonomia e comparariam diferentes modelos Gemini 4 em latência e custo.
- **Autenticação em produção.** O login atual usa hash `scrypt` e token assinado com HMAC para simplificar a execução local. Em ambiente aberto, entrariam verificação de e-mail, revogação de sessão e limite de tentativas.
- **Novos canais.** A interface web cobre o fluxo completo de cliente e gestor. Integrar WhatsApp ou Telegram exigiria apenas um novo adaptador sobre `ConversationService`.

## Uso de assistentes de IA

Usei assistentes de IA no protótipo de interface no Paper, na implementação incremental dos módulos e testes e na revisão de texto. Defini e revisei manualmente a arquitetura, os cortes de escopo, o tratamento de cada anomalia nos dados e cada commit.
