# Plano: `zbus` como alvo de validação

Etapa futura, ainda não executada. Escrito em 2026-10-20, junto com a skill 0.3.3.

## Contexto

Na 0.3.3, o `log` (ESP-IDF) saiu do conjunto de validação e foi para o de
desenvolvimento. A análise da iteração 4 nele originou as duas regras novas da versão:

- **teste lento:** limite de 1 s por teste; o state seam fica como último recurso;
- **comprimento de entrada:** a partição "longo" para strings e buffers.

Um alvo que guiou mudanças na skill não serve mais para detectar overfitting. O `zbus` entra
no lugar dele como alvo de **validação**, nunca visto pela skill, para confirmar se as
regras da 0.3.3 generalizam fora dos alvos de onde saíram.

Conjuntos depois da mudança:

| Alvo | Caminho | Conjunto | Eval |
|---|---|---|---|
| `net_buf` | A (Zephyr) | dev | 1 |
| `esp_partition` | B (ESP-IDF) | dev | 2 |
| `log` | B (ESP-IDF) | dev (desde a 0.3.3) | 102 (id mantido) |
| `onoff` | A (Zephyr) | validação | 101, 103 (pt) |
| `zbus` | A (Zephyr) | validação (**a adicionar**) | 104 (proposto) |
| `console` | B (ESP-IDF) | validação (a adicionar) | 105 (proposto) |

**Alvo ESP-IDF de validação:** `onoff` e `zbus` são Zephyr. O lado ESP-IDF fica com o
`console`; ver `plano-console.md`.

## Regras do conjunto de validação (valem para o `zbus`)

- **Só confirma uma versão; nunca guia mudanças.** Um resultado ruim no `zbus` é registrado
  no README como limitação. A correção vem de um alvo de desenvolvimento que mostre o mesmo
  problema. Se só o `zbus` mostrar o problema e mesmo assim decidirmos corrigir, ele vai para
  desenvolvimento (como aconteceu com o `log`) e é preciso um alvo de validação novo.
- **Nada do `zbus` entra na skill**: nem exemplos, nem nomes de API, nem padrões tirados das
  suítes dele ou da análise dos mutantes.
- **Roda depois do desenvolvimento:** só depois que a 0.3.3 passar na iteração 5 dos alvos de
  desenvolvimento (`net_buf`, `esp_partition`, `log`), na mesma versão, sem mudar a skill no
  meio.

## Por que o `zbus`

O alvo é o `subsys/zbus/` do Zephyr v4.2.1, no mesmo checkout dos outros alvos Zephyr (sha
`64e98eb5…`), então não precisa de download novo. As regras da 0.3.3 vieram do `log`, mas o
`zbus` exercita as mesmas regras de outra forma:

- **Teste lento sem força bruta:** `zbus_chan_pub/read/notify/claim` recebem um `k_timeout_t`.
  Um teste de timeout que espera de verdade pode passar de 1 s. A regra precisa resolver isso
  pelos degraus 1 e 2 (timeouts curtos, `K_NO_WAIT`, fake de kernel), e **não** pelo seam.
  Se o seam aparecer aqui, a regra está sendo usada por conveniência.
- **Comprimento:** `zbus_chan_pub` e `zbus_chan_read` copiam `message_size` bytes, e o msg
  subscriber aloca `net_buf` pelo tamanho da mensagem (`_zbus_create_net_buf`).
- **Kernel de verdade, e muito:** `k_sem_take/give`, `k_msgq_put`,
  `k_thread_priority_set/get`, `k_current_get`, `k_is_in_isr`, `k_mem_slab_alloc`,
  `k_malloc`, `sys_timepoint_*`. Isso testa a regra de isolamento da 0.3.2: o que roda de
  verdade no `native_sim` e o que precisa de fake para forçar falha ou timeout.
- **Muitas configurações:** `ZBUS_RUNTIME_OBSERVERS` com alocação dinâmica, estática ou
  nenhuma, `ZBUS_MSG_SUBSCRIBER` com buffer dinâmico ou estático, `ZBUS_PRIORITY_BOOST`,
  `ZBUS_CHANNEL_ID`, `ZBUS_CHANNEL_PUBLISH_STATS`, `ZBUS_ASSERT_MOCK`. Isso exercita a linha
  "only one configuration tested" da saída final.
- **Seções iteráveis:** canais e observadores são definidos por macros que vão para seções do
  linker. Isso testa se a skill monta fixtures sem inventar API.

## Escopo proposto do alvo

| Arquivo | Linhas | Observação |
|---|---|---|
| `subsys/zbus/zbus.c` | 621 | núcleo: pub/read/notify/claim/finish, VDED, observers, máscara, priority boost |
| `subsys/zbus/zbus_runtime_observers.c` | 198 | add/rm de observers em runtime, 3 modos de alocação |
| `subsys/zbus/zbus_iterable_sections.c` | 50 | iteração de canais e observadores; trivial, **decidir se entra** |

## Referência humana

Suítes em `tests/subsys/zbus/`:
- `unittests`, `channel_id`, `dyn_channel`, `user_data` e `publish_stats`;
- `runtime_observers_registration` (alocação dinâmica e estática) e `_alloc_none`;
- `hlp_priority_boost`;
- `integration`.

Decisões a tomar **antes** de medir. Num alvo de validação, decidir depois de ver o resultado
vicia a comparação:
- **`integration` entra na referência?** Ela é de integração entre módulos, enquanto a skill
  só gera testes unitários. Proposta: deixar fora da referência, mas em `hidden`.
- **Quais variantes de configuração** (`extra_configs` dos `testcase.yaml`) entram. A skill
  testa uma configuração por padrão, e a referência humana cobre várias. Uma opção é comparar
  por variante, outra é comparar a união.
- **Critério de aceite** igual ao dos outros alvos (cobertura e mutação ≥ referência, mutação
  ≥ 80%), sem ajuste específico para o `zbus`.
- `hidden`: `tests/subsys/zbus` inteiro, e `samples/subsys/zbus` também, se os samples
  revelarem demais a forma de usar a API.

## Passos

1. **`targets.yaml`:** entrada `zbus` com `set: validation`, `path: A`, `kind: zephyr`,
   `checkout: zephyr`, `sources`, `hidden` e `baseline_suite` conforme as decisões acima.
2. **Medir a referência:** `python3 tools/measure.py zbus`. Registrar `baseline_coverage` e
   `baseline_mutation` com a data. Se a execução inicial do mull estourar o timeout por causa
   dos testes com espera, definir `mull_timeout_ms` e anotar o motivo.
3. **Revisar sobreviventes da referência** e registrar os equivalentes comprovados em
   `equivalent-mutants.yaml` (seção `zbus`). Isso vale para a medição e não muda a skill;
   separar os "equivalentes por código sem efeito" (observação para a futura skill de
   mutação).
4. **Eval 104 em `evals/validation-evals.json`:** prompt com os arquivos do escopo,
   `expected_output` com o resumo do módulo e a meta, e as 24 expectations atuais.
5. **Depois da iteração 5 de desenvolvimento** (0.3.3 aprovada em `net_buf`, `esp_partition`
   e `log`): 2 execuções no `zbus`, no `onoff` e no `console` com a mesma versão. No `zbus`, observar:
   - se a regra de teste lento disparou nos testes de timeout, e com qual degrau;
   - se o seam apareceu (não deveria, porque os degraus 1 e 2 bastam);
   - se as mensagens longas entraram como partição;
   - o que foi falsificado e o que rodou de verdade no kernel;
   - qual configuração foi testada e quais branches de outras ficaram de fora.
6. **README:** acrescentar o alvo na tabela, os resultados de validação e as limitações
   encontradas. Elas não viram mudança da skill por causa deste alvo.

## Custo estimado

O `zbus` tem cerca de 870 linhas nos três arquivos. A estimativa é ficar entre `onoff`
(~US$ 1,5) e `net_buf` (~US$ 2,5) por execução, mais a medição da referência com mull
(variável; depende do tempo dos testes com espera).
