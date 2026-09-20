# Benchmarks

An annotated corpus and a runner, for seeing what each review layer catches and
for noticing when a change to the rules breaks something. Read "What the corpus
is" below before quoting any result from it.

## Corpus

`cases.json` (v1.3) contains 76 labeled sentences drawn from typical Chinese
technical documentation issues:

- `terminology` — product-term misuse covered by the default rule set
  (帐号/账号, 登陆/登录, 轮循/轮询, ...)
- `typo` — spelling errors that require the model layer (按扭, 磁盤, 显箸, ...)
- `grammar` — sentence-level wording problems (duplicated particles, redundant
  地, causative-frame rewrites)
- `protection` — negative samples (whitelisted terms, URLs, inline commands,
  SQL fragments, image references) that must never be modified

Each case pairs the input text with the exact expected output. Cases where the
expected output equals the input are negative samples.

## Running

```bash
# Rule-preview path (no model dependencies required)
python3 benchmarks/run_benchmark.py

# Local small-model path (requires requirements-model.txt; fails instead of
# silently downgrading if the model runtime is unavailable)
python3 benchmarks/run_benchmark.py --model shibing624/chinese-text-correction-1.5b

# Remote backends: score any Ollama or OpenAI-compatible endpoint
python3 benchmarks/run_benchmark.py \
    --backend ollama --base-url http://127.0.0.1:11434 --model qwen2.5:1.5b

python3 benchmarks/run_benchmark.py \
    --backend openai --base-url https://api.example.com/v1 \
    --model vendor-model-id          # key read from OPENAI_API_KEY

# Machine-readable output
python3 benchmarks/run_benchmark.py --json results.json
```

A sentence counts as a true positive only when the reviewed output matches the
expected output exactly. Wrong fixes count as both a false positive and a false
negative, mirroring how a reviewer would treat an incorrect suggestion. A case
whose backend call fails is reported as an `error` failure and does not abort
the run.

## Published accuracy for the model itself

For how good the correction model is, use its own evaluation rather than this
corpus. The author of `shibing624/chinese-text-correction-1.5b` reports F1 on
three public sets — SIGHAN-2015, EC-LAW, MCSC — with the 1.5B model averaging
0.68 and the optional 7B variant 0.82, measured on a Tesla V100 at roughly 6
queries per second. CPU inference, which is what DocSifter defaults to, is
considerably slower than that. See the
[model card](https://huggingface.co/shibing624/chinese-text-correction-1.5b)
for the full table and the other models compared there.

Those numbers describe the model. What DocSifter adds around it — the rule
layer, whitelist and syntax protection, the false-positive filter — is what the
corpus below illustrates.

## What the corpus is

An illustrative set, not a statistical benchmark. 76 annotated cases across four
categories is enough to show what each layer catches and to catch regressions in
the shipped rules — it found a real gap in the `登录` rule — but far too small to
support a headline accuracy figure. With 13 `grammar` cases, one case moves that
category by eight points.

So the results below are reported as counts against their sample size rather
than as percentages. Read them as "this is the shape of the thing", not as a
number you can quote.

### Rule preview (no model dependencies)

| category    | corrected     | wrong fixes | negatives left alone |
| ----------- | ------------- | ----------- | -------------------- |
| terminology | 24 of 24      | 0           | 4 of 4               |
| typo        | 0 of 19       | 0           | —                    |
| grammar     | 1 of 13       | 0           | —                    |
| protection  | —             | 0           | 16 of 16             |

Rules are deterministic and conservative: they fix what they know and touch
nothing else. Every negative sample survives, and no case gets a wrong fix.

### Local small model (`shibing624/chinese-text-correction-1.5b`)

| category    | corrected     | wrong fixes | negatives left alone |
| ----------- | ------------- | ----------- | -------------------- |
| terminology | 24 of 24      | 0           | 4 of 4               |
| typo        | 15 of 19      | 3           | —                    |
| grammar     | 3 of 13       | 4           | —                    |
| protection  | —             | 0           | 16 of 16             |

What the two tables say together: `typo` is the category the model layer exists
for — rules cannot touch it at all, and the model gets most of it. `grammar` is
where the model is weakest, wrong about as often as it is right. Terminology the
rules already cover, and the model neither helps nor hurts there. Both layers
leave every protection sample alone. The model's cost is the wrong fixes column,
and that is why a finding carries its source in the report: a `model` finding is
a suggestion, a `rule` finding is deterministic.

One model failure is worth reading in full. On
`服务的部暑方式支持 Kubernetes 与虚机两种` the model fixes the typo and turns
`Kubernetes` into `V`. The default whitelist holds five terms — Markdown, API,
SQL, AsciiDoc, SampleProduct — so a product name you have not added to it is not
protected, and the model is free to damage it. Add your own product vocabulary
to `whitelist` before running the model layer over real documentation; that
list, not the model, is what keeps these names intact.

### What CI enforces

CI runs this corpus in rule-preview mode on every pull request. The corpus is
too small to gate on an accuracy figure, but two things hold regardless of
sample size, and `run_benchmark.py` exits non-zero on either:

- a `protection` negative was modified, in any mode;
- a rule produced a wrong fix, in rule-preview mode. Rules are deterministic, so
  a wrong fix is a bug in the rule. Model runs are exempt: a model may
  legitimately get a case wrong, and that belongs in the table above rather than
  in a failing build.

### Paired cases

Seven errors appear twice, once as plain prose and once with a single technical
token added (`paired-plain` / `paired-tech` in the case notes). Real Chinese
technical writing is full of sentences that merely name a technology, and guards
that skip "technically dense" text can suppress those without any signal in an
unpaired corpus. Keep the pairs together when editing the corpus.

### Where the headroom is

`grammar` is the weakest layer by a wide margin, and the false-positive records
the product already collects (`src/docsifter/false_positives.json`) are the
natural starting corpus for improving it through fine-tuning. Two conditions
apply before claiming any improvement: the fine-tuning corpus must be kept
separate from this one, and the result has to be re-measured here. Fine-tuning
is a direction with evidence behind it, not a promise that accuracy will rise.

## Recording your own results

This corpus reflects one team's terminology and one model. Run it against your
own backend, and against your own cases, before drawing conclusions for your
documentation.

```bash
python3 benchmarks/run_benchmark.py --json results.json
```
