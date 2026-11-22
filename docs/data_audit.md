# Auditoria da base de dados

A inspeção dos arquivos brutos em [`data/raw/`](../data/raw/) revelou inconsistências silenciosas tanto nos seis CSVs operacionais quanto no manual em PDF. Se esses dados fossem enviados diretamente ao LLM sem curadoria, o assistente anunciaria especificações falsas, ofereceria instrumentos fora de linha, somaria descontos proibidos ou vazaria pedidos de contas erradas.

Todo ajuste acontece na ingestão em [`src/emporio/etl/loader.py`](../src/emporio/etl/loader.py) sem alterar os arquivos originais. Cada anomalia detectada gera um registro auditável na tabela `etl_audit_log`, somando 11 registros automáticos (9 nos CSVs e 2 no PDF).

## Resumo da base bruta versus curada

| Fonte | Volume bruto | Estado após ETL | Armadilhas tratadas |
| --- | --- | --- | --- |
| `products.csv` | 65 produtos | 61 vendáveis (`is_sellable=True`) | 6 descrições trocadas, 1 descontinuado com estoque fantasma, 1 pré-lançamento em pedido histórico, 2 sem estoque |
| `promotions.csv` | 25 promoções | 4 ativas e 21 expiradas | 21 descontos encerrados (incluindo itens fora de linha ou esgotados) |
| `customers.csv` | 50 cadastros | 49 e-mails únicos no login | 1 e-mail compartilhado por 2 clientes distintos (`11` e `43`) |
| `orders.csv` e `order_items.csv` | 20 pedidos | 20 pedidos preservados | Pedido `#3` contém item marcado como `coming_soon` (`130`) |
| `políticas_da_loja.pdf` | 26 trechos por seção | 26 embeddings `gemini-embedding-001` | 2 telefones conflitantes e 1 e-mail com acento inválido |

## 1. Descrições de produto com marca ou ficha técnica trocada

Seis produtos em `products.csv` trazem texto de descrição pertencente a outro instrumento, em contradição direta com o campo `name` e o JSON de `specs`. O ETL compara as marcas citadas no nome com as marcas na descrição e confere atributos numéricos como número de cordas e teclas. Quando encontra conflito, preserva o texto original em `raw_description`, substitui `description` por uma ficha factual gerada a partir de `name` e `specs` e grava `description_mismatch` em `etl_audit_log`.

| ID | Produto (`name`) | Preço | Erro na descrição bruta | Valor curado (`specs`) |
| --- | --- | --- | --- | --- |
| `135` | Music Man Bass 1X Electric Bass | R$ 8.732,00 | Descreve um Fender Jazz Bass em Alder com captadores single-coil | Corpo Ash, braço Maple, 4 cordas, Red |
| `137` | Yamaha Bass 3X Electric Bass | R$ 11.445,00 | Descreve um Ibanez ativo de 5 cordas | Corpo Ash, braço Maple, 4 cordas, Black |
| `139` | Bateria Acústica Yamaha Kit 1 Studio | R$ 4.439,00 | Descreve uma Pearl Export em Poplar e mogno asiático | Cascos Maple, 5 peças, ferragens inclusas, Blue |
| `140` | Bateria Acústica Pearl Kit 2 Studio | R$ 13.285,00 | Descreve uma Tama 100% Birch com Star-Mount | Cascos Maple, 5 peças, ferragens inclusas, Black |
| `142` | Teclado Sintetizador Korg Synth 1 Pro | R$ 1.127,00 | Descreve um Roland workstation de 88 teclas pesadas | 61 teclas, Synthesizer, polifonia 128, Black |
| `144` | Teclado Sintetizador Roland Synth 3 Pro | R$ 9.351,00 | Descreve um teclado arranjador Yamaha | 61 teclas, Synthesizer, polifonia 128, Black |

## 2. Armadilhas de disponibilidade e estoque fantasma

Quatro produtos não podem aparecer como disponíveis para compra imediata, cada um por um motivo diferente. O ETL deriva a coluna booleana `is_sellable` exigindo simultaneamente `status == "active"` e `stock_quantity > 0`.

- **Produto descontinuado com estoque positivo (`136`, Ibanez Bass 2X Electric Bass, R$ 441,00).** O CSV bruto registra `status=discontinued` junto com `stock_quantity=13`. Na ingestão, o ETL zera o estoque para `0`, marca `is_sellable=False` e registra `discontinued_nonzero_stock`.
- **Pré-lançamento em pedidos históricos (`130`, Kala KA-ABP-CTG Barítono Cedar, R$ 1.749,00).** O produto aparece como `status=coming_soon` com `stock_quantity=2`, mas consta em pedidos já entregues (como o pedido `#3` de Isabela Moreira Cunha). O ETL preserva o registro para manter a integridade do histórico de pedidos, define `is_sellable=False` e grava `coming_soon_in_orders`.
- **Ativo porém esgotado (`96`, Giannini GF-3D Dreadnought Sunburst, R$ 799,90).** Está com `status=active`, mas `stock_quantity=0`. Como custa abaixo de R$ 1.000,00, um filtro apenas por status incluiria o item em buscas de violões baratos. Ele permanece com `is_sellable=False` e, quando consultado diretamente, aciona sugestão automática de alternativas em estoque na mesma faixa de preço.
- **Descontinuado abaixo de R$ 1.000,00 (`113`, Shelby SN-7C 7 Cordas Nylon Natural, R$ 749,00).** Tem `status=discontinued` e `stock_quantity=0`. Também fica fora de qualquer busca de itens disponíveis.

## 3. Promoções expiradas e bloqueio de acúmulo com PIX

A tabela `promotions.csv` possui 25 registros, mas apenas 4 têm `is_active=1`. As outras 21 são campanhas encerradas (como Black Friday e Semana do Músico) que continuam no arquivo.

| Promoção ativa | Produto | Tabela | Desconto | Preço promocional |
| --- | --- | --- | --- | --- |
| `#12` | Kalani KAL-700T Tenor Natural (`127`) | R$ 359,00 | 10% | R$ 323,10 |
| `#14` | Ohana CK-20 Concert Natural (`121`) | R$ 549,00 | 20% | R$ 439,20 |
| `#19` | Crafter HT-100 Folk Aço Natural (`90`) | R$ 2.399,00 | 18% | R$ 1.967,18 |
| `#24` | Taylor 110e Dreadnought Natural (`94`) | R$ 5.999,00 | 8% | R$ 5.519,08 |

- **Promoções expiradas usadas como pegadinha.** O Takamine GD20 (`95`, R$ 2.199,00) tem a promoção `#4` de 12% marcada como `is_active=0`. Há também campanhas expiradas associadas a produtos fora de linha ou esgotados (`#8` e `#22` no Giannini GF-3D `96`, `#16` no Shelby SN-7C `113`). O repositório separa `active_promotion` de `expired_promotions` para que o agente nunca aplique desconto vencido e saiba explicar quando uma oferta já encerrou.
- **Não cumulatividade do PIX.** Pelas regras do manual, o desconto de 5% no PIX nunca soma com promoções ativas. No Crafter HT-100 (`90`), o valor final com 18% é R$ 1.967,18 mesmo no PIX, e não R$ 1.868,82. Todo cálculo roda em Python determinístico em [`src/emporio/domain/rules.py`](../src/emporio/domain/rules.py).

## 4. E-mail duplicado em clientes

Dois cadastros diferentes em `customers.csv` compartilham o mesmo e-mail `bruno.martins@jmail.com`, ambos em Três Lagoas.

- **Cliente `11` (Bruno Carvalho Martins).** Telefone `(67) 98543-2109`, titular do pedido `#10` (Music Man Bass 1X, status `confirmed`, R$ 8.732,00).
- **Cliente `43` (Bruno Martins).** Telefone `(67) 99456-3456`, sem pedidos registrados.

O ETL preserva os dois cadastros e registra `duplicate_customer_email`. Na criação automática de contas de login, o seed deduplica o e-mail para não violar a chave única de `users`. Em tempo de consulta (`lookup_order`), o gateway de segurança conta quantos clientes compartilham aquele e-mail. Quando o resultado é maior que 1, a consulta na sessão autenticada exige um step-up de confirmação por telefone antes de exibir qualquer pedido, e em canais sem login o par `order_id` mais e-mail ou telefone valida o titular exato do pedido.

## 5. Inconsistências no manual de políticas (PDF)

O parser do PDF em `parse_policy_pdf_bytes` detecta duas contradições internas no texto de [`políticas_da_loja.pdf`](../data/raw/pol%C3%ADticas_da_loja.pdf) e registra ambas em `etl_audit_log`.

- **Telefones divergentes (`conflicting_phone_numbers`).** A capa e a seção 1.2 informam `(67) 3341-4444`, enquanto a seção 7 (WhatsApp) informa `(67) 3321-4500`. A orientação curada prioriza `(67) 3341-4444` e menciona também `(67) 3321-4500` para evitar contradição com o manual.
- **E-mail com acento (`accented_email_typo`).** A seção 1.2 grafa `contato@empóriodamusica.com.br` (domínio inválido com acento), enquanto a capa traz `contato@emporiodamusica.com.br`. Toda resposta e tela do sistema padroniza o domínio sem acento.
- **Escopo sem acessórios.** A seção 7.1 define que a loja vende apenas instrumentos musicais e o catálogo não tem nenhum acessório cadastrado (cordas, palhetas, cabos, cases, pedais ou amplificadores). Pedidos exclusivos de acessórios são bloqueados antes do LLM principal pelo guardrail System One (Jev) e reforçados pelas regras do agente.

## Cobertura automática na suíte de evals

Cada classe de armadilha acima tem ao menos um cenário dedicado em [`evals/dataset.jsonl`](../evals/dataset.jsonl) validando tanto o trace das ferramentas quanto a resposta final.

- **Descrições trocadas.** `catalog_curated_description_135` verifica que o Music Man Bass 1X não menciona Fender nem Jazz Bass.
- **Disponibilidade e estoque fantasma.** `catalog_guitars_under_1000`, `availability_out_of_stock_96`, `availability_discontinued_136` e `availability_coming_soon_130`.
- **Promoções e PIX.** `payment_promo_no_pix_stacking`, `payment_regular_pix_and_installments` e `payment_expired_promo_transparency`.
- **E-mail duplicado e LGPD.** `lgpd_block_without_second_factor`, `lgpd_verified_return_eligible_order_7` e `lgpd_duplicate_email_order_10`.
- **Contatos do PDF e acessórios.** `policy_warranty_and_contacts` e `scope_refuse_accessories`.
