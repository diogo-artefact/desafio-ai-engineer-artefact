# Exemplo 02. Preço no PIX, promoções expiradas versus ativas e frete

- **Cenário.** Cliente autenticada (`isabela.moreira@jmail.com`) pergunta sobre a promoção expirada de 12% no `Takamine GD20` e depois testa a regra de não cumulatividade do PIX na promoção ativa de 18% do `Crafter HT-100`, comparando frete entre Campo Grande e Dourados.
- **Modelo.** `google:gemini-4-hydrogen` com guardrail `jev-1.14.0`.
- **Regras validadas.** Transparência sobre promoção expirada (`#4`), cálculo exato de 5% no PIX e 12x sem juros, bloqueio de acúmulo entre promoção ativa (`#19`, 18%) e PIX (mantendo R$ 1.967,18 sem calcular R$ 1.868,82) e distinção de frete capital versus interior.

## Turno 1

**Cliente**

Qual o valor do Takamine GD20 no PIX e parcelado? Vi que ele estava com 12% de desconto, essa promoção ainda está ativa?

**Trace real de execução**

| Etapa | Ferramenta | Resumo | Duração |
| --- | --- | --- | --- |
| 1 | `jev_guardrail` (visível apenas ao gestor) | `Permitido (store_support, p=1.00) · jev-1.14.0` | 216 ms |
| 2 | `get_product_details` | `product_id_or_name="Takamine GD20"` -> estoque 5, promoção `#4` expirada | 13 ms |
| 3 | `simulate_payment_and_shipping` | `product_id_or_name="Takamine GD20"` -> PIX R$ 2.089,05, até 12x | 16 ms |

**Assistente**

> Oi, Isabela! Tudo bem?
>
> A promoção de 12% de desconto do **Takamine GD20 Dreadnought Natural** infelizmente não está mais vigente. Atualmente, ele está com o preço padrão de tabela e temos 5 unidades disponíveis em estoque.
>
> Confira os valores atualizados:
>
> | Forma de pagamento | Condição | Valor |
> | :--- | :--- | :--- |
> | **PIX (à vista)** | 5% de desconto | **R$ 2.089,05** |
> | **Cartão de crédito** | Até 12x sem juros | **12x de R$ 183,25** (total R$ 2.199,00) |
>
> Se você estiver em Campo Grande ou região metropolitana, esse pedido ainda conta com frete grátis via motoboy próprio (entrega em 1 a 3 dias úteis). Também aceitamos pagamento combinado (entrada no PIX + restante parcelado no cartão), caso queira simular alguma opção específica.
>
> Se quiser fechar o pedido ou tirar alguma dúvida sobre o instrumento, é só me falar!

## Turno 2

**Cliente**

E o Crafter HT-100? Se eu pagar no PIX ganho 5% a mais sobre a promoção? Quanto fica o frete dele para Campo Grande e para Dourados?

**Trace real de execução**

| Etapa | Ferramenta | Resumo | Duração |
| --- | --- | --- | --- |
| 1 | `jev_guardrail` (visível apenas ao gestor) | `Permitido (store_support, p=1.00) · jev-1.14.0` | 250 ms |
| 2 | `simulate_payment_and_shipping` | `product_id_or_name="Crafter HT-100", city="Dourados"` -> PIX R$ 1.967,18, até 12x | 20 ms |
| 3 | `simulate_payment_and_shipping` | `product_id_or_name="Crafter HT-100", city="Campo Grande"` -> PIX R$ 1.967,18, até 12x | 26 ms |
| 4 | `get_product_details` | `product_id_or_name="Crafter HT-100"` -> estoque 3, promoção `#19` ativa (18%) | 31 ms |

**Assistente**

> O **Crafter HT-100 Folk Aço Natural** está disponível (3 unidades em estoque) e com uma promoção ativa de **18% de desconto**.
>
> Sobre o PIX: **o desconto de 5% não acumula com promoções ativas**. Por isso, tanto no PIX quanto no cartão o valor final fica no preço promocional.
>
> ### Valores do Crafter HT-100
>
> | Condição | Detalhes | Valor |
> | :--- | :--- | :--- |
> | **Preço original** | Valor de tabela | R$ 2.399,00 |
> | **Promoção ativa (18% off)** | Preço promocional à vista (PIX) | **R$ 1.967,18** |
> | **Cartão de crédito** | Até 12x sem juros | **12x de R$ 163,93** (total R$ 1.967,18) |
>
> *Observação: o pagamento combinado (entrada no PIX + parcelamento no cartão) não se aplica a itens em promoção.*
>
> ---
>
> ### Frete: Campo Grande x Dourados
>
> | Cidade | Modalidade | Prazo estimado | Custo |
> | :--- | :--- | :--- | :--- |
> | **Campo Grande (MS)** | Motoboy próprio (com contato telefônico prévio) | 1 a 3 dias úteis | **Grátis** (pedidos acima de R$ 500,00 na região metropolitana) |
> | **Dourados (MS)** | Correios (PAC/SEDEX) ou Jadlog (.package) | PAC: 5 a 12 dias úteis / Jadlog: 3 a 8 dias úteis / SEDEX: 2 a 5 dias úteis | **Calculado conforme CEP, peso e dimensões** (inclui rastreamento e seguro) |
>
> Se quiser fechar o pedido de algum deles ou tirar mais alguma dúvida, é só me avisar!
