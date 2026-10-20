# tools

Ferramentas do benchmark da `embedded-unit-testing`. Os alvos e as referências ficam em
`benchmarks/targets.yaml`.

| Script | O que faz |
|---|---|
| `fetch_targets.py` | Baixa os checkouts fixados (Zephyr, ESP-IDF) em `benchmarks/.targets/` |
| `prepare_workspace.py <alvo> <dest>` | Monta o ambiente que a skill recebe num eval, **sem** a suíte humana |
| `measure.py <alvo> ...` | Mede uma suíte: cobertura + mutação (mull), com veredito contra a referência |

## Fluxo de um eval

```bash
python3 tools/fetch_targets.py
python3 tools/prepare_workspace.py net_buf ~/.cache/claude-skills-bench/run1   # FORA de repositório git
# ... a skill roda no workspace e gera a suíte ...
python3 tools/measure.py net_buf --root ~/.cache/claude-skills-bench/run1/zephyr \
    --suite tests/lib/net_buf_unit --label skill-v0.1.0
python3 tools/measure.py esp_partition --root ~/.cache/claude-skills-bench/run2/esp-idf \
    --suite components/esp_partition/test/host --cmd 'make -C {suite} test' --label skill-v0.1.0
```

Sem `--root` e `--suite`, o `measure.py` mede a suíte de referência no checkout fixado
(`--label ref`). Requisitos: `gcc`, `gcovr`, `clang-18` em `/usr/bin` (mesmo LLVM do plugin
do mull) e `dpkg-deb`. Para alvos Zephyr, use o venv do west ativo ou um `.venv` na raiz
(o workspace já traz um).

## `prepare_workspace.py`

- Extrai o SHA fixado com `git archive`: sem `.git`, então a suíte humana não pode ser
  recuperada pelo histórico.
- Exclui os caminhos `hidden` do alvo e copia os submodules.
- No Zephyr, cria um `.venv` apontando para o venv do west.
- O destino precisa ficar **fora** de qualquer repositório git: o CMake do ESP-IDF sobe os
  diretórios procurando `.git` e quebra se achar outro repositório.

## `measure.py`

**Dois tipos de alvo:**
- **`kind: zephyr`:** a suíte é um projeto twister.
  - Cobertura: twister `--coverage` em `native_sim` e `unit_testing` (gcc, 32 bits, igual à
    referência).
  - Mutação: build llvm em 64 bits (`native_sim/native/64`; `unit_testing` com `M64_MODE=1` e
    `--target=x86_64-linux-gnu`), porque o runtime do mull falha em `-m32`.
- **`kind: host`:** a suíte tem build próprio, e `--cmd` compila **e** roda os testes. Um
  *shim* na frente do `PATH` (`gcc`, `cc`, `g++`, `c++`, `clang`, `clang++`, mais `CC`/`CXX`)
  injeta o compilador:
  - Cobertura: `gcc --coverage`, depois `gcovr` com a exclusão de branches de log/assert.
  - Mutação: `clang-18` com o plugin do mull. O shim converte fontes para caminho absoluto e
    separa `cc a.c b.c -o x` em uma compilação por arquivo mais o link, porque o mull
    reprocessa o comando gravado e exige um arquivo por compilação.

  O mesmo vale para `cc -c a.c b.c`, que vira um `-c` por fonte.

  Entre cobertura e mutação, o diretório da suíte é restaurado de um snapshot.

**Mutação:** o `mull-runner` roda em cada executável de teste (o veredito é o exit code).
Os binários são combinados: um mutante morre se **qualquer** binário o mata, e timeout conta
como morto. O timeout por execução é o padrão do mull (3 s), ou o `mull_timeout_ms` do alvo
(o `log` usa 60 s). Um binário que falha ou estoura o timeout já sem mutação fica fora e aparece
em `excluded_binaries`; os mutantes que só ele mataria contam como vivos. Os mutantes de `benchmarks/equivalent-mutants.yaml` saem da conta.
**Score** = mortos / (mortos + vivos); um mutante em linha não executada conta como vivo.

**Guardas** (a medição é recusada, não só reprovada):
- os `sources` do checkout medido precisam ser byte a byte os do SHA fixado, antes e depois;
- cada `source` precisa ter cobertura e mutantes, senão a suíte compilou uma **cópia** do
  módulo.

**Saída:** `benchmarks/results/<alvo>-<label>.json`, com cobertura, mutação por arquivo,
status de cada mutante (id, arquivo, linha, operador, sem trechos de código), o `--cmd` usado
e `vs_ref`. O `vs_ref` traz o critério de aceite por arquivo:
- ≥ referência em linha, branch, função e mutação;
- ≥ `acceptance` do manifesto: 95/95/90 e 80% de mutação;
- o alvo 100/100/100 aparece como informação, sem reprovar.

`--sources` mede só parte dos arquivos, para diagnóstico; o resultado não vale como aceite.
`--runner-args` passa argumentos ao binário de teste. A referência do `log` usa
`--rng-seed 1`, porque o Catch2 v3 sorteia a ordem dos testes.

### Como comparar

- **Mutação:** é comparável **mutante a mutante** entre suítes. O conjunto de mutantes
  depende só da fonte: um build de host próprio gerou exatamente os mesmos IDs que o build
  `idf.py` da referência.
- **Cobertura:** é comparada em **porcentagem**. Os totais de linha e branch do gcov mudam
  com as flags de compilação (ex.: `util.c` tem 23 linhas no build `-Og` do ESP-IDF e 22
  num `gcc` sem otimização).

### Operadores (grupo `cxx_all` do mull 0.34.1)

- relacionais (`<`↔`<=`, `==`↔`!=`…);
- lógicos (`&&`↔`||`);
- aritméticos e de atribuição composta;
- `++`/`--`;
- remoção de chamada `void`;
- troca de retorno de chamada escalar;
- constante na atribuição ou inicialização.

Não tem "return de erro → 0" nem "constante ±1".

### Mutantes equivalentes

Só entra em `benchmarks/equivalent-mutants.yaml` o que é **comprovadamente** equivalente,
isto é, nenhum input observável distingue o mutante do original, sempre com justificativa no
próprio arquivo. Remover lock, `free` ou limpeza nunca é equivalente. IDs só com dígitos vão
entre aspas.

### Determinismo

Com `workers: 1`, três medições seguidas dão status idêntico em todos os mutantes, nos quatro
alvos. Com execução paralela, mutantes perto do limite de timeout mudavam de status.
