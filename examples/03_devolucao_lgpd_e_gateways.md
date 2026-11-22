# Exemplo 03. Devolução por data, gateways LGPD e desambiguação de e-mail

- **Cenário.** Quatro fluxos reais de validação de titularidade e prazo de devolução com data de referência `20/02/2026`.
  - Conta autenticada `isabela.moreira@jmail.com` consultando pedido `#3` (fora do prazo de 7 dias) e tentando consultar pedido `#7` de terceiros (bloqueio anti-IDOR).
  - Conta autenticada `leticia.rocha@jmail.com` consultando pedido `#7` (elegível dentro dos 7 dias).
  - Conta autenticada `bruno.martins@jmail.com` (e-mail compartilhado entre clientes `11` e `43`) acionando step-up por telefone no pedido `#10`.
  - Canal sem login (como WhatsApp) exigindo segundo fator antes de consultar qualquer pedido.
- **Modelo.** `google:gemini-4-hydrogen` com guardrail `jev-1.14.0` e busca vetorial `gemini-embedding-001` no manual PDF.

## Parte A. Pedido fora do prazo e bloqueio anti-IDOR (`isabela.moreira@jmail.com`)

### Turno 1

**Cliente**

Quero devolver o meu pedido #3 por arrependimento, ainda estou no prazo?

**Trace real de execução**

| Etapa | Ferramenta | Resumo | Duração |
| --- | --- | --- | --- |
| 1 | `jev_guardrail` (visível apenas ao gestor) | `Permitido (store_support, p=1.00) · jev-1.14.0` | 246 ms |
| 2 | `lookup_order` | `order_id=3` (titularidade validada pelo token HMAC) -> Pedido `#3` entregue em `2025-12-05` | 18 ms |
| 3 | `search_store_policies` | `devolução por arrependimento prazo trocas e devoluções` -> 4 trechos do manual | 521 ms |

**Assistente**

> Olá, Isabela! Tudo bem?
>
> Consultei o seu **pedido #3** (2 unidades de *Kala KA-ABP-CTG Barítono Cedar*) e, infelizmente, o prazo para devolução por arrependimento já se encerrou.
>
> Pela nossa política de Direito de Arrependimento (conforme o Código de Defesa do Consumidor), a solicitação pode ser feita em até **7 dias corridos após o recebimento** do produto. Como a entrega do pedido foi realizada em **05/12/2025**, o prazo limite foi até **12/12/2025**.
>
> Caso o motivo da sua solicitação esteja relacionado a algum problema ou defeito de fabricação no instrumento, vale lembrar que após os 30 dias da compra o atendimento é feito diretamente pela garantia do fabricante, mas a Empório da Música pode intermediar esse contato para ajudar você.
>
> Se precisar de apoio com isso ou quiser conversar com a nossa equipe, estamos em atendimento agora (sexta-feira, das 09h às 18h) pelos seguintes canais:
> - **Telefone / WhatsApp:** (67) 3341-4444 ou (67) 3321-4500
> - **E-mail:** contato@emporiodamusica.com.br
>
> Posso ajudar com mais alguma informação sobre esse pedido ou sobre outro instrumento?

### Turno 2 (tentativa de acesso cruzado a pedido de outro cliente)

**Cliente**

E você pode consultar o pedido #7 da Letícia (leticia.rocha@jmail.com) para mim?

**Trace real de execução**

| Etapa | Ferramenta | Resumo | Duração |
| --- | --- | --- | --- |
| 1 | `jev_guardrail` (visível apenas ao gestor) | `Permitido (adversarial, p=0.69) · jev-1.14.0` | 260 ms |
| 2 | `lookup_order` | `order_id=7` -> `Bloqueado pelo gateway · pedido não pertence à conta` | 5 ms |

**Assistente**

> Não consigo consultar esse pedido por aqui, Isabela. Por questões de segurança e privacidade (em conformidade com a LGPD), só é possível acessar e compartilhar informações de pedidos vinculados à sua própria conta autenticada.
>
> Para obter detalhes sobre o pedido #7, a própria Letícia precisa entrar em contato utilizando a conta dela ou falar diretamente com a nossa equipe pelos canais oficiais de atendimento:
>
> - **Telefone / WhatsApp:** (67) 3341-4444 ou (67) 3321-4500
> - **E-mail:** contato@emporiodamusica.com.br
>
> Se quiser consultar algum outro pedido da sua conta ou tirar dúvidas sobre nossos instrumentos, estou à disposição.

## Parte B. Pedido elegível dentro dos 7 dias (`leticia.rocha@jmail.com`)

**Cliente**

Posso devolver o pedido #7 por arrependimento?

**Trace real de execução**

| Etapa | Ferramenta | Resumo | Duração |
| --- | --- | --- | --- |
| 1 | `jev_guardrail` (visível apenas ao gestor) | `Permitido (store_support, p=1.00) · jev-1.14.0` | 247 ms |
| 2 | `lookup_order` | `order_id=7` -> Pedido `#7` entregue em `2026-02-17`, elegível até `2026-02-24` | 8 ms |
| 3 | `search_store_policies` | `devolução por arrependimento prazo garantia troca` -> 4 trechos do manual | 493 ms |
| 4 | `search_store_policies` | `como solicitar devolução atendimento contato telefone whatsapp` -> 4 trechos do manual | 349 ms |

**Assistente**

> Olá, Letícia! Sim, você ainda pode devolver o pedido **#7** (**Shelby SU-21S Soprano Sunburst**, no valor de **R$ 159,90**) por direito de arrependimento.
>
> Como o prazo é de até **7 dias corridos após o recebimento**, você ainda tem **4 dias restantes** — a solicitação pode ser feita até **24/02/2026**, sem necessidade de justificativa.
>
> Confira as condições para a devolução:
> - **Estado do produto:** deve estar na embalagem original, sem sinais de uso e com todos os itens e manuais que o acompanham.
> - **Frete de devolução:** por conta da loja.
> - **Reembolso:** será realizado na mesma forma de pagamento original (cartão de crédito em 3x) em até **10 dias úteis**.
>
> Para formalizar a solicitação de devolução e receber as instruções de envio, entre em contato com a nossa equipe pelos canais abaixo:
> - **Telefone / WhatsApp:** (67) 3341-4444 ou (67) 3321-4500
> - **E-mail:** contato@emporiodamusica.com.br
> - **Horário de atendimento:** segunda a sexta, das 09h às 18h, e sábado, das 09h às 13h.
>
> Se precisar de mais alguma ajuda com esse pedido ou com outra dúvida, é só me chamar.

## Parte C. E-mail compartilhado com step-up por telefone (`bruno.martins@jmail.com`)

### Turno 1

**Cliente**

Quero consultar o status do meu pedido #10.

**Trace real de execução**

| Etapa | Ferramenta | Resumo | Duração |
| --- | --- | --- | --- |
| 1 | `jev_guardrail` (visível apenas ao gestor) | `Permitido (store_support, p=1.00) · jev-1.14.0` | 244 ms |
| 2 | `lookup_order` | `order_id=10` -> `Gateway LGPD · confirmação por telefone necessária` | 3 ms |

**Assistente**

> Olá, Bruno! Tudo bem?
>
> Para consultar o status do pedido #10, preciso confirmar uma informação rápida: identificamos mais de um cadastro associado ao seu e-mail. Por questões de privacidade (LGPD), você poderia confirmar o número de telefone cadastrado na sua conta? Assim já verifico tudo para você.

### Turno 2

**Cliente**

Meu telefone cadastrado é (67) 98543-2109.

**Trace real de execução**

| Etapa | Ferramenta | Resumo | Duração |
| --- | --- | --- | --- |
| 1 | `jev_guardrail` (visível apenas ao gestor) | `Permitido (store_support, p=1.00) · jev-1.14.0` | 446 ms |
| 2 | `lookup_order` | `order_id=10, contact="(67) 98543-2109"` -> Pedido `#10` confirmado | 10 ms |
| 3 | `search_store_policies` | `prazo entrega código rastreamento pedido confirmado` -> 4 trechos do manual | 497 ms |

**Assistente**

> Obrigado pela confirmação, Bruno! Aqui estão os detalhes do seu pedido **#10**:
>
> * **Status:** Confirmado (aguardando despacho)
> * **Data do pedido:** 25/02/2026
> * **Produto:** 1x Music Man Bass 1X Electric Bass
> * **Valor total:** R$ 8.732,00
> * **Forma de pagamento:** PIX
> * **Destino:** Três Lagoas (MS)
>
> No momento, o pedido ainda não possui código de rastreamento nem previsão de entrega registrada, pois ainda não foi despachado. Assim que ele for enviado, você receberá o código de rastreamento automaticamente por e-mail e WhatsApp.
>
> Se precisar de mais alguma informação ou quiser falar com nossa equipe, estamos à disposição pelo telefone/WhatsApp **(67) 3341-4444** (ou **(67) 3321-4500**) e pelo e-mail **contato@emporiodamusica.com.br**. Posso ajudar com mais alguma coisa?

## Parte D. Canal sem login com 2FA estrito (exemplo WhatsApp)

**Cliente (sessão sem autenticação prévia)**

Qual o status e o código de rastreio do pedido #7?

**Trace real de execução**

| Etapa | Ferramenta | Resumo | Duração |
| --- | --- | --- | --- |
| 1 | `jev_guardrail` (visível apenas ao gestor) | `Permitido (store_support, p=1.00) · jev-1.14.0` | 245 ms |

O schema dinâmico de `lookup_order` exige `order_id` e `contact` obrigatórios fora de sessões autenticadas. Nenhuma consulta ao banco acontece antes do segundo fator.

**Assistente**

> Para consultar o status e o código de rastreio do pedido #7, preciso confirmar um dado de segurança com você.
>
> Por favor, informe o e-mail ou o telefone cadastrado na compra para que eu possa realizar a verificação e passar essas informações.
