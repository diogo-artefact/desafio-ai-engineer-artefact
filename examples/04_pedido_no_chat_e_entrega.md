# Exemplo 04. Pedido pelo chat (human-in-the-loop), entrega simulada e devolução

- **Cenário.** Cliente autenticada (`isabela.moreira@jmail.com`) compra um `Takamine GD20` pelo chat, confirma o pedido no card separado da interface, recebe a notificação automática de entrega após 5 minutos simulados e consulta imediatamente seu prazo legal de devolução.
- **Modelo.** `google:gemini-4-hydrogen` com guardrail `jev-1.14.0`.
- **Regras validadas.** Criação de rascunho validado em Python sem concluir compra automaticamente, baixa atômica de estoque na confirmação, código de rastreio `BR...BR`, transição automática para `delivered` após 5 minutos e cálculo determinístico de 7 dias corridos para arrependimento.

## Turno 1. Solicitação de pedido pelo chat

**Cliente**

Quero fazer o pedido de 1 Takamine GD20 pagando no PIX, com entrega em Campo Grande.

**Trace real de execução**

| Etapa | Ferramenta | Resumo | Duração |
| --- | --- | --- | --- |
| 1 | `jev_guardrail` (visível apenas ao gestor) | `Permitido (store_support, p=1.00) · jev-1.14.0` | 233 ms |
| 2 | `get_product_details` | `product_id_or_name="Takamine GD20"` -> estoque 5 | 7 ms |
| 3 | `prepare_order_draft` | `product="Takamine GD20 Dreadnought Natural", qty=1, payment="pix", city="Campo Grande"` -> rascunho `c42bd91e07e9` (`R$ 2.089,05`) | 16 ms |

**Evento `order_draft` enviado ao card de confirmação**

```json
{
  "draft_id": "c42bd91e07e9",
  "product_id": 95,
  "product_name": "Takamine GD20 Dreadnought Natural",
  "quantity": 1,
  "unit_price_brl": 2199.0,
  "discount_percent": 5.0,
  "subtotal_brl": 2089.05,
  "shipping_brl": 0.0,
  "shipping_note": "Campo Grande · Frete grátis (1 a 3 dias úteis)",
  "total_brl": 2089.05,
  "payment_method": "pix",
  "payment_label": "PIX à vista (5% de desconto)",
  "status": "pending"
}
```

**Assistente**

> Olá, Isabela. Preparei o rascunho do seu pedido com os dados informados:
>
> | Item | Detalhes |
> | --- | --- |
> | Instrumento | Takamine GD20 Dreadnought Natural (1 unidade) |
> | Preço de tabela | R$ 2.199,00 |
> | Pagamento | PIX à vista (5% de desconto) |
> | Entrega | Campo Grande — Frete grátis (1 a 3 dias úteis) |
> | Total | R$ 2.089,05 |
>
> O seu pedido ainda não foi finalizado. Revise os valores no card exibido no chat e clique em **Confirmar pedido** para concluir a compra. Se quiser ajustar algum detalhe antes de confirmar, é só me avisar.

## Ação na interface. Confirmação no card (`POST /api/orders/drafts/c42bd91e07e9/confirm`)

O clique em **Confirmar pedido** grava o pedido `#21` na tabela `orders`, baixa o estoque de 5 para 4 unidades, gera o rastreio `BRQ7O1WAOXMBR`, agenda `deliver_at` para 5 minutos depois e insere a confirmação no chat.

**Mensagem do sistema no chat**

> Pedido **#21** confirmado (1x Takamine GD20 Dreadnought Natural, total **R$ 2.089,05**, PIX à vista (5% de desconto)). Código de rastreio `BRQ7O1WAOXMBR`. Para fins de teste, este pedido será marcado automaticamente como entregue em 5 minutos.

## Notificação automática após 5 minutos (`finalize_due_deliveries`)

Decorridos 5 minutos, o watcher da API atualiza o pedido `#21` para `delivered` e publica a notificação de entrega na conversa.

**Mensagem do sistema no chat**

> Seu pedido **#21** (1x Takamine GD20 Dreadnought Natural) foi marcado como **entregue** (código de rastreio `BRQ7O1WAOXMBR`). Caso precise de ajuda, troca ou devolução dentro do prazo legal de 7 dias corridos, é só avisar por aqui.

## Turno 2. Consulta imediata de devolução dentro dos 7 dias

**Cliente**

Recebi o pedido #21 agora. Se eu precisar devolver por arrependimento, qual é o meu prazo?

**Trace real de execução**

| Etapa | Ferramenta | Resumo | Duração |
| --- | --- | --- | --- |
| 1 | `jev_guardrail` (visível apenas ao gestor) | `Permitido (store_support, p=1.00) · jev-1.14.0` | 231 ms |
| 2 | `lookup_order` | `order_id=21` -> Pedido `#21` entregue hoje, elegível por 7 dias corridos | 9 ms |
| 3 | `search_store_policies` | `devolução por arrependimento prazo` -> 4 trechos do manual | 472 ms |

**Assistente**

> Olá, Isabela. Para o seu pedido **#21** (Takamine GD20 Dreadnought Natural), entregue hoje (**22/11/2026**), o prazo para solicitar a devolução por arrependimento é de **7 dias corridos** a partir do recebimento — ou seja, você pode fazer a solicitação até **29/11/2026**, sem necessidade de justificativa.
>
> As condições da devolução por arrependimento são:
> - **Estado do produto:** o violão deve estar na embalagem original, sem sinais de uso, acompanhado de todos os itens e manuais.
> - **Frete:** o custo do frete de devolução é por conta da loja.
> - **Reembolso:** o valor pago (R$ 2.089,05) é devolvido na mesma forma de pagamento (PIX) em até **10 dias úteis**.
>
> Caso decida solicitar a devolução, você pode falar com a nossa equipe pelo telefone/WhatsApp **(67) 3341-4444** (ou **(67) 3321-4500**) e pelo e-mail **contato@emporiodamusica.com.br**. Como hoje é domingo, estamos fora do expediente (funcionamos de segunda a sexta, das 09:00 às 18:00, e aos sábados, das 09:00 às 13:00), e nosso atendimento retorna na **segunda-feira às 09:00**.
