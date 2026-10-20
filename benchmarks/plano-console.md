# Plano: `console` como alvo de validação (ESP-IDF)

Etapa futura, ainda não executada. Escrito em 2026-10-20, junto com a skill 0.3.3.
Complementa o `plano-zbus.md`.

## Contexto

Na 0.3.3, o `log` saiu da validação e foi para o desenvolvimento, porque as regras novas
(teste lento e comprimento de entrada) saíram dele. A validação ficou sem alvo ESP-IDF:
`onoff` e `zbus` são Zephyr. O `console` preenche esse buraco.

| Alvo | Caminho | Conjunto | Eval | Forma do módulo |
|---|---|---|---|---|
| `net_buf` | A (Zephyr) | dev | 1 | pool de buffers, refcount, fragmentos |
| `esp_partition` | B (ESP-IDF) | dev | 2 | tabela de partições, verificação |
| `log` | B (ESP-IDF) | dev (desde a 0.3.3) | 102 | cache min-heap, lista, hexdump |
| `onoff` | A (Zephyr) | validação | 101, 103 (pt) | máquina de estados |
| `zbus` | A (Zephyr) | validação (a adicionar) | 104 (proposto) | barramento pub/sub com kernel |
| `console` | B (ESP-IDF) | validação (**a adicionar**) | 105 (proposto) | parser de strings e registro de comandos |

As regras do conjunto de validação estão em `plano-zbus.md` e valem aqui do mesmo jeito:
- só confirma uma versão e nunca guia mudanças;
- nada do `console` entra na skill;
- roda depois da iteração de desenvolvimento, na mesma versão.

## Por que o `console`

- **Diversidade:** o `esp_event` também seria um bom alvo, mas é um barramento com cópia de
  dados, timeouts e RTOS, o mesmo perfil do `zbus`. O `console` acrescenta uma forma de módulo
  que nenhum alvo atual tem.
- **A regra de comprimento numa forma diferente da do `log`:** a regra saiu de tags usadas
  como chave de lista. Aqui ela aparece como linha de comando longa, `argv_size` no limite e
  aspas/escapes que mudam o tamanho de cada argumento (`esp_console_split_argv`). Isso mede se
  a regra generaliza.
- **Partições de estado:** `esp_console_init/deinit`, registro, desregistro e re-registro de
  comandos, help ordenado e níveis de verbosidade.

## Escopo proposto do alvo

ESP-IDF v5.4.2, mesmo checkout do `esp_partition` e do `log` (sha `f5c3654a…`).

| Arquivo | Linhas | Observação |
|---|---|---|
| `components/console/split_argv.c` | 112 | `esp_console_split_argv`: aspas, escapes, limite de `argv` |
| `components/console/commands.c` | 388 | init/deinit, register/deregister, run, help e verbosidade |

**Fora do escopo:**
- `esp_console_repl_chip.c` e `esp_console_repl_linux.c`, que são REPL interativo de E/S;
- `esp_console_common.c`;
- os terceiros `argtable3/` e `linenoise/`.

## Referência humana

`components/console/test_apps/console`:
- 15 `TEST_CASE` Unity, com variante `linux` (`sdkconfig.ci.defaults.linux`) e
  `pytest_console.py` marcado como `host_test`;
- **8 dos 15 são `[ignore]`** (testes interativos de REPL e help).

Pontos a verificar **antes** de fechar o alvo. Se algum falhar, a alternativa é o `esp_event`.
1. **Força da referência:** com metade dos testes ignorados, a referência deve ser fraca.
   Medir cobertura e mutação. Superar a referência vai ser fácil, então o critério que pesa de
   verdade é o mínimo de 80% de mutação.
   - Decidir se os `[ignore]` rodam na referência. Proposta: rodar como o CI roda, ou seja,
     sem eles.
2. **Dependências no build de host:** o `commands.c` usa o `argtable3` para o help, e talvez o
   `linenoise`. Confirmar que o build de host compila só os dois arquivos do escopo e suas
   dependências, sem puxar o REPL.
3. **Comando da referência:** é um `test_apps`, não um `host_test`. O `baseline_cmd` segue o
   do `log`, apontando para `components/console/test_apps/console` com `sdkconfig.ci.defaults.linux`:
   `idf.py -B build-measure --preview set-target linux && idf.py -B build-measure build && ./build-measure/<elf>`.
4. **`hidden`:** `components/console/test_apps`. Os exemplos `examples/system/console/` também,
   se mostrarem demais o uso da API.

Decisões que precisam ser tomadas antes de medir, para não viciar a comparação:
- os `[ignore]` (item 1);
- o critério de aceite, igual ao dos outros alvos.

## Passos

1. Verificar os pontos 2 e 3 acima, com um build de host do `test_apps/console`.
2. **`targets.yaml`:** entrada `console` com `set: validation`, `path: B`, `kind: host`,
   `checkout: esp-idf`, `sources`, `hidden`, `baseline_suite` e `baseline_cmd`.
3. **Medir a referência:** `python3 tools/measure.py console` e registrar
   `baseline_coverage` e `baseline_mutation` com a data. Decidir o alvo aqui se a referência
   for fraca demais para dizer algo (ponto 1).
4. **Revisar sobreviventes da referência** e registrar os equivalentes comprovados em
   `equivalent-mutants.yaml` (seção `console`). Isso vale para a medição e não muda a skill.
5. **Eval 105 em `evals/validation-evals.json`:** prompt com os dois arquivos,
   `expected_output` com o resumo do módulo e a meta, e as 24 expectations atuais.
6. **Depois da iteração 5 de desenvolvimento:** 2 execuções junto com `onoff` e `zbus`, na
   mesma versão. No `console`, observar:
   - se linhas longas, `argv_size` no limite (0, 1, cheio, estourado) e argumentos com aspas
     e escapes viraram partições;
   - se a skill isolou o `argtable3`/E/S ou deixou rodar de verdade, e se declarou isso na
     linha Isolation;
   - se algum teste passou de 1 s (não deveria; não há espera nem contador);
   - se o seam apareceu (não deveria).
7. **README:** tabela de alvos, resultados de validação e limitações encontradas.

## Custo estimado

Cerca de 500 linhas de C. Deve ficar perto do `onoff` (~US$ 1,5 por execução, ~4,5 min),
mais a medição da referência com mull.
