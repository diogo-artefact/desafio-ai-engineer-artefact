# Exemplo 01. Catálogo curado e armadilhas de disponibilidade

- **Cenário.** Cliente autenticada (`isabela.moreira@jmail.com`) consulta violões disponíveis até R$ 1.000,00, tenta comprar um baixo descontinuado com estoque fantasma (`136`, Ibanez Bass 2X) e pede as especificações de um baixo cuja descrição bruta no CSV citava outra marca (`135`, Music Man Bass 1X).
- **Modelo.** `google:gemini-4-hydrogen` com guardrail `jev-1.14.0`.
- **Regras validadas.** Exclusão de itens não vendáveis (`Giannini GF-3D` esgotado e `Shelby SN-7C` descontinuado), estoque zerado no descontinuado `136`, sugestão automática de alternativas em estoque e ficha curada sem mencionar `Fender` ou `Jazz Bass`.

## Turno 1

**Cliente**

Quais violões disponíveis vocês têm até R$ 1.000?

**Trace real de execução**

| Etapa | Ferramenta | Resumo | Duração |
| --- | --- | --- | --- |
| 1 | `jev_guardrail` (visível apenas ao gestor) | `Permitido (store_support, p=1.00) · jev-1.14.0` | 356 ms |
| 2 | `search_catalog` | `query="violão", max_price=1000, only_available=true` -> 10 instrumento(s) | 17 ms |
| 3 | `search_catalog` | `category="Violões", only_promotions=true, only_available=true` -> 2 instrumento(s) | 21 ms |
| 4 | `search_catalog` | `category="Violões", max_price=1000, only_available=true, limit=50` -> 12 instrumento(s) | 22 ms |

**Assistente**

> Olá, Isabela! Temos 12 opções de violões disponíveis até R$ 1.000,00, incluindo modelos de nylon, aço, eletroacústico e até de 7 cordas. Confira a lista:
>
> | Modelo | Preço | Estoque |
> | :--- | :--- | :--- |
> | Tagima Memphis AC-39 Nylon Natural | R$ 429,90 | 15 unidades |
> | Rozini RC-104 Nylon Estudante | R$ 459,90 | 10 unidades |
> | Shelby SN-100 Folk Aço Preto | R$ 549,00 | 5 unidades |
> | Giannini GF-1R Aço Folk Sunburst | R$ 579,90 | 7 unidades |
> | Yamaha C40 Nylon Natural | R$ 599,90 | 12 unidades |
> | Giannini GN-15 Nylon Cedr Natural | R$ 689,00 | 6 unidades |
> | Yamaha F310 Aço Natural | R$ 699,90 | 14 unidades |
> | Tagima Dallas Tuner Aço Natural | R$ 749,00 | 9 unidades |
> | Shelby SGD-195E Elétrico Aço Sunburst | R$ 799,00 | 6 unidades |
> | Yamaha C70 Nylon Natural | R$ 849,00 | 8 unidades |
> | Tagima Woodstock Dreadnought Natural | R$ 899,00 | 11 unidades |
> | Tagima TW-7 7 Cordas Aço Natural | R$ 999,00 | 6 unidades |
>
> Como esses modelos não estão em promoção ativa, todos contam com 5% de desconto no pagamento via PIX.
>
> Se quiser ver a ficha técnica completa ou simular o valor no PIX, parcelamento e frete de algum deles, é só me falar qual modelo chamou mais a sua atenção!

## Turno 2

**Cliente**

E o Ibanez Bass 2X, tem quantas unidades em estoque hoje? Também quero ver as especificações do Music Man Bass 1X.

**Trace real de execução**

| Etapa | Ferramenta | Resumo | Duração |
| --- | --- | --- | --- |
| 1 | `jev_guardrail` (visível apenas ao gestor) | `Permitido (store_support, p=1.00) · jev-1.14.0` | 228 ms |
| 2 | `get_product_details` | `product_id_or_name="Music Man Bass 1X"` -> estoque 9 | 27 ms |
| 3 | `get_product_details` | `product_id_or_name="Ibanez Bass 2X"` -> estoque 0, 3 alternativas em estoque | 30 ms |

**Assistente**

> Sobre os dois modelos que você consultou:
>
> ### Ibanez Bass 2X Electric Bass
> No momento, o **Ibanez Bass 2X Electric Bass** está com **0 unidades em estoque** e encontra-se **descontinuado**, não estando mais disponível para venda.
>
> Como alternativas disponíveis em estoque na categoria de baixos, temos:
>
> | Modelo | Preço | Estoque |
> | :--- | :--- | :--- |
> | Music Man Bass 4X Electric Bass | R$ 7.157,00 | 9 unidades |
> | Music Man Bass 1X Electric Bass | R$ 8.732,00 | 9 unidades |
> | Yamaha Bass 3X Electric Bass | R$ 11.445,00 | 11 unidades |
>
> ---
>
> ### Especificações do Music Man Bass 1X Electric Bass
> Este modelo está ativo e conta com **9 unidades disponíveis em estoque**. Confira a ficha técnica e as condições:
>
> * **Categoria:** Baixos
> * **Corpo:** Ash
> * **Braço:** Maple
> * **Cordas:** 4
> * **Cor:** Red
> * **Preço:** R$ 8.732,00
> * **PIX (5% de desconto):** R$ 8.295,40
> * **Cartão:** até 12x de R$ 727,67 sem juros (com opção de pagamento combinado)
>
> Se quiser simular o frete para a sua cidade ou conferir os detalhes de outro baixo, é só avisar!
