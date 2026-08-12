# Can Collaborative Teams of Small Trained Specialists Outperform Frontier Generalists Under Equal Resource Ceilings?

**Status:** Draft proposal based on the approved study design  
**Date:** 2026-08-12  
**Primary modality:** Text  
**Execution harness:** Codex Conductor with Agent Harness peer collaboration  

## Abstract

This project will test whether heterogeneous teams of small, genuinely trained
specialist language models can outperform frontier generalist models when both
systems receive the same task, tools, time, monetary budget, token allowance,
concurrency, and compute ceiling. The comparison is between complete systems,
not between a fixed worker topology and a single model call. Each frontier
generalist may plan, use tools, revise its answer, and create eligible helper
sessions at its discretion. Each specialist team receives the same freedom and
works in an open peer room without a permanent leader, privileged synthesizer,
or semantic judge. All root and descendant activity counts against one shared
condition-wide resource envelope.

The confirmatory study will cross multiple specialist teams with multiple
frontier generalists on a common, hidden sample of text-only tasks. Model
eligibility will require published parameter counts and frozen versions;
specialists must additionally have documented domain-specific weight training.
Output quality will be measured by the original benchmark-native objective
scorers, orchestrated through Inspect AI. The primary outcome is item-level
correctness. No LLM-as-judge score and no project-specific quality index will be
used in the primary study. Efficiency, reliability, partial credit, and resource
use will be reported separately.

The confirmatory hypothesis is deliberately strong: under matched ceilings,
small specialist teams have higher mean correctness than frontier-generalist-led
systems. The protocol is designed so that a positive result supports that claim,
while a null or negative result remains interpretable rather than being obscured
by unequal budgets, undisclosed model size, an advantaged orchestrator, or a
subjective grader.

## 1. Motivation

Model scaling and multi-agent collaboration are often compared under different
resource assumptions. A team may receive several independent model calls while
the generalist receives one; alternatively, the generalist may be allowed a long
agentic trajectory while the team is constrained to fixed rounds. These designs
answer useful engineering questions, but they do not isolate whether learned
specialization plus peer collaboration can substitute for frontier scale.

This study asks a narrower causal question: if the task and the resource
opportunity are held as equal as practical, does the architecture of intelligence
matter? The independent variable is the system type:

1. a heterogeneous peer team of small trained specialists; or
2. a frontier-generalist-led system.

The dependent variable is output correctness. All other measurable dimensions
are controls, stratification factors, or secondary outcomes.

The proposed workbench will also produce reusable infrastructure for conducting
agent-system experiments. Codex Conductor will enforce admission and aggregate
resource ceilings. Agent Harness will provide a durable peer collaboration room.
The evaluator will freeze outputs and apply authoritative benchmark scorers after
the systems can no longer modify their answers.

## 2. Research questions and hypotheses

### 2.1 Primary research question

Under identical system-wide resource ceilings, do heterogeneous teams of small,
trained specialist models achieve higher item-level correctness than
frontier-generalist-led systems on a broad suite of objectively gradable text
tasks?

### 2.2 Confirmatory hypothesis

Let `Team` denote an eligible specialist-team system and `Frontier` denote an
eligible frontier-generalist-led system, averaged over the preregistered
distribution of tasks, systems, and repeated runs.

- **Null hypothesis (H0):** `mean correctness(Team) <= mean correctness(Frontier)`.
- **Alternative hypothesis (H1):** `mean correctness(Team) > mean correctness(Frontier)`.

The primary test will be one-sided at `alpha = 0.05` because superiority is the
preregistered claim. A two-sided 95% confidence interval will also be reported so
the magnitude and uncertainty remain visible.

### 2.3 Secondary research questions

- Does collaboration add value beyond running each specialist alone?
- Which task families benefit from specialist diversity, and which favor a
  frontier generalist?
- Do open peer rooms outperform non-communicating rosters and deterministic
  routing under the same ceilings?
- How often does each system fail operationally, abstain, or exhaust a ceiling?
- What correctness is achieved per dollar, second, token, and compute-proxy unit?
- Are results robust to alternate defensible accounting rules and the treatment
  of infrastructure failures?

Secondary analyses explain the primary outcome; none can replace a failed
primary test.

## 3. Scope

### 3.1 Included in the primary study

- Text input and text/code output only.
- Multiple independently constructed specialist teams.
- Multiple frontier generalist roots, evaluated individually.
- Genuine trained specialists obtained as frozen open-weight checkpoints,
  rented deployments, or versioned hosted APIs.
- Frontier models accessed through versioned APIs.
- Objective, benchmark-native grading.
- Agentic autonomy within identical system-wide ceilings.
- Tool-free and tool-enabled tasks where the benchmark protocol supports them.

### 3.2 Excluded from the primary study

- Image, audio, video, or mixed-modality tasks.
- Prompt-only personas labeled as specialists without relevant weight updates.
- Frontier APIs without citable parameter disclosure.
- Human preference grading or LLM-as-judge grading as a primary outcome.
- A learned router, manager, chair, or final-answer model with privileged control
  over a specialist team.
- Training or fine-tuning new specialists as part of this project.
- Per-system budget tuning on confirmatory items.

Multimodal work may follow as a separately preregistered extension after the text
study. It will not be pooled into the primary result.

## 4. Relation to prior work and the methodological gap

Prior multi-agent studies establish that repeated sampling, debate, aggregation,
and model mixtures can improve output quality. *More Agents Is All You Need*
studies sampling and voting; *Improving Factuality and Reasoning in Language
Models through Multiagent Debate* uses iterative debate; and
*Mixture-of-Agents Enhances Large Language Model Capabilities* uses layered
aggregation. These systems generally evaluate with task correctness for
structured benchmarks, while open-ended comparisons rely more heavily on model
or preference judges.

Recent work comes closer to the proposed comparison. *Can Small Agents
Collaborate to Beat a Single Large Language Model?* compares a small-agent system
with large models on tool-intensive tasks, but gives the system a single
orchestrator and attributes much of the gain to orchestrator capacity. *Capable
Language Models Can Outgrow the Benefits of Collaboration* compares systems
under matched per-system compute ceilings and finds that the value of
collaboration depends on model capability. *Small, Free, and Effective* examines
small-model orchestration for malware analysis. *Rethinking Scale* studies
small-model deployment under agent paradigms and reports task-native metrics.

This proposal differs in five linked ways:

1. specialists must have learned domain specialization, not merely prompted
   roles;
2. specialist teams have no permanent manager or privileged answer writer;
3. several teams and several frontier roots are crossed rather than treating one
   roster or one model as the entire population;
4. both sides receive autonomy under the same multi-dimensional ceilings; and
5. the primary inference uses native objective scorers without an invented
   aggregate quality formula.

The study therefore tests the combination of learned specialization and peer
collaboration, rather than only the benefit of extra samples, a strong
orchestrator, or a particular debate prompt.

## 5. Units, terminology, and estimand

- A **root** is the initial model session assigned a task.
- A **descendant** is any helper session created by a root or another descendant.
- A **condition run** is one system attempting one item under one resource
  envelope and one random seed.
- A **specialist** is a model with documented weight updates aimed at a declared
  domain or capability.
- A **specialist team** is a frozen roster of peer specialist roots plus any
  eligible descendants they create during a run.
- A **frontier-generalist-led system** is one frontier root plus any eligible
  descendants it creates during a run.
- A **ceiling** is a maximum opportunity, not a consumption target. A system may
  finish early and leave resources unused.

The primary estimand is the average difference in probability of an objectively
correct answer between eligible specialist-team systems and eligible
frontier-generalist-led systems over the preregistered task mixture, roster/model
sample, and run seeds. Each benchmark family contributes equal weight to this
average, and items contribute equal weight within a family. This prevents a
large benchmark from silently defining the cross-suite result.

This is a system-level estimand. It does not claim that every specialist team
beats every frontier model, or that a particular model remains frontier-class
outside its frozen study date.

## 6. Model eligibility and selection

### 6.1 Rules applying to every model

Every root and descendant used in a confirmatory run must appear in a frozen
eligible-model catalog. Each catalog entry must include:

- provider and immutable model/checkpoint identifier;
- release date and access method;
- license and usage restrictions;
- published, citable total parameter count;
- published active parameter count for mixture-of-experts models;
- context limit and supported inference controls;
- tokenizer or provider usage-accounting method;
- training and specialization evidence;
- price schedule or local-compute valuation rule;
- known model lineage and shared weights; and
- cryptographic hashes for local weights and configuration where available.

A parameter estimate inferred from latency, price, rumor, or third-party reverse
engineering is not sufficient. An API model whose provider does not disclose a
citable parameter count is ineligible for the confirmatory study. For a
mixture-of-experts model, both active and total parameters must be disclosed.

Versions are frozen before the confirmatory sample is opened. If a provider
silently changes or retires a model, runs after the change form a separately
labeled replication and are not silently pooled with the original study.

### 6.2 Specialist eligibility

A specialist must have documented domain-specific weight training relevant to
its declared capability. Acceptable evidence includes a model card, technical
report, or provider documentation describing supervised fine-tuning, continued
pretraining, preference optimization, adapter training, or another weight-update
process on domain-specific data.

Prompted roles, system prompts, retrieval collections, and tool access may shape
behavior but do not establish specialist eligibility. A general model told “you
are a mathematician” is an ablation, not a trained specialist.

Each specialist root must have fewer total parameters than every frontier root
in the confirmatory catalog. For each team, the total number of unique learned
parameters across its frozen root roster must not exceed the total parameter
count of the smallest eligible frontier root. Shared base weights are counted
once in this static roster rule; both the unique-parameter total and the sum of
independently callable model sizes are reported. Runtime compute is accounted per
call, so shared weights do not create unmetered inference.

Specialist descendants must also be smaller than every frontier root and must
come from the specialist-side eligible catalog. A specialist system may never
call a frontier model.

### 6.3 Frontier eligibility

A frontier generalist must be a broadly capable model, publicly available
through a versioned API, and among the strongest eligible generalists at the time
the protocol is frozen. Eligibility is based on model documentation and
independent broad-benchmark evidence available before the hidden test is opened,
not performance on confirmatory items.

The frontier root may create descendants, including differently specialized
eligible models, when its normal agentic interface supports doing so. The root is
not required to use helpers. Every descendant must be in the frozen frontier-side
catalog, and all of its usage counts against the same condition envelope. The
frontier system may not evade disclosure rules by calling an unidentified model
behind a router.

### 6.4 Team construction

The minimum confirmatory design contains three specialist teams and three
frontier generalists. The final count will be increased if the preregistered
power analysis requires it. Each specialist team will contain four root members
covering four capability slots relevant to the text study:

1. mathematics and formal reasoning;
2. code and algorithmic reasoning;
3. science or expert-domain question answering; and
4. retrieval, multi-hop reasoning, or instruction following.

Candidate specialists are ranked within a slot using documentation, independent
public evidence, and a disjoint development set. Roster construction will favor
strong candidates while avoiding four near-identical derivatives of one base
model. At least two distinct model lineages must appear in each team. The
selection algorithm, tie rules, and development results are published before
confirmatory testing.

Teams are fixed before testing. A poor confirmatory result cannot trigger a
roster substitution. No member is assigned permanent authority; slot labels
describe learned capability, not a chain of command.

Each root specialist will also run individually under a single-system version of
the same ceiling. These individual runs are an ablation and do not enter the
primary Team-versus-Frontier coefficient.

## 7. Tasks and benchmark suite

### 7.1 Selection principles

The primary suite will contain tasks with authoritative, deterministic, or
executable scorers. It will span domains in which complementary specialization
could plausibly matter while remaining broad enough that the result is not a
coding-only or mathematics-only claim.

Candidate families are:

| Capability family | Candidate source | Native primary score |
| --- | --- | --- |
| Competition mathematics | AIME or a current equivalent | symbolic/numeric equivalence |
| Expert science and knowledge | GPQA or a contamination-reviewed successor | multiple-choice accuracy |
| Code generation | LiveCodeBench or a current time-split equivalent | tests passed / accepted solution |
| Multi-hop reasoning | MuSiQue or an equivalent with authoritative answers | exact match and official F1 |
| Verifiable instruction following | IFEval or a current successor | official instruction checks |
| Broad reasoning | a contamination-reviewed, objectively scored suite | benchmark-native accuracy |

The final benchmark versions and item counts are selected through a documented
audit before preregistration. A candidate may be replaced only for licensing,
availability, contamination, scorer reproducibility, or fatal ceiling-compatibility
reasons. Replacement must preserve the capability family and objective-grading
requirement and must occur before any confirmatory output is observed.

Confirmatory sampling will balance family contributions directly where feasible.
If the powered sample requires unequal item counts, the locked analysis will use
inverse-family-size weights so that each family still contributes one sixth of
the primary task mixture.

### 7.2 Development and confirmatory partitions

Three data partitions are maintained:

- a **selection set** for model and roster construction;
- a **pilot set** for variance, ceiling feasibility, and power estimation; and
- a **confirmatory set** for the locked hypothesis test.

They are item-disjoint. Where a benchmark supplies private or time-split tests,
those mechanisms are preferred. Public-item contamination risk is documented by
comparing item release dates with model training cutoffs and by sensitivity
analysis on the lowest-risk subset. Confirmatory answers are never inserted into
model prompts, collaboration rooms, logs visible to later runs, or retrieval
indexes.

### 7.3 Tool profiles

Tools are benchmark-native rather than universally enabled. Closed-book tasks
remain closed-book for both systems. Code tasks receive the same sandbox,
language versions, dependency snapshot, and execution limits. Retrieval tasks
receive the same read-only corpus snapshot and query interface. The exact tool
schema, output truncation behavior, call limit, and error behavior are identical
across conditions and hashed in the run receipt.

Agentic autonomy means choosing how to use the available tools; it does not mean
changing the benchmark protocol or gaining access to the answer key.

## 8. Experimental conditions

### 8.1 Primary conditions

For every confirmatory item, all frozen specialist teams and all frozen frontier
roots attempt the same item. Order is randomized within provider and benchmark
blocks. Each pairing is repeated across the preregistered seed set.

- **Specialist peer team:** four trained specialist roots collaborate in an open
  peer room and may create eligible small descendants.
- **Frontier-generalist-led system:** one frontier root works autonomously and may
  create eligible descendants.

The frontier condition is intentionally not limited to a one-shot response. The
study compares what each system architecture can accomplish with the same
opportunity, not whether four calls beat one call.

### 8.2 Preregistered ablations

- each specialist run alone;
- the same specialist roster with no inter-model communication;
- a shared-evidence board without direct peer messages;
- the full open-peer room;
- generalist models assigned specialist roles by prompt only;
- deterministic task routing followed by a fixed answer-selection rule;
- tools enabled versus disabled where both are valid benchmark variants; and
- a counterfactual score that subtracts communication tokens from the observed
  envelope without changing the primary accounting.

Ablations identify mechanisms. They are not added to the primary condition after
results are known.

## 9. Controlled variables

Each row below is controlled at the complete condition-run level, including all
roots and descendants.

| Variable | Control rule | Recorded evidence |
| --- | --- | --- |
| Task | Same item and benchmark version | item and dataset hashes |
| User prompt | Byte-identical benchmark content | prompt hash |
| System instructions | Same task rules; only collaboration mechanics differ | versioned prompt hashes and diff |
| Context/examples | Identical benchmark-provided context and demonstrations | serialized context hash |
| Output contract | Same final schema and maximum answer length | schema/version hash |
| Tools | Same benchmark-native tools, permissions, versions, and results | tool manifest and call log |
| Retrieval | Same frozen corpus and query service | corpus/index hashes |
| Token opportunity | Same aggregate input, cached-input, reasoning, and output caps | provider and local usage events |
| Compute opportunity | Same active-parameter-times-processed-token cap; measured FLOPs when available | per-call compute ledger |
| Monetary opportunity | Same aggregate dollar cap | immutable price table and cost ledger |
| Time opportunity | Same monotonic wall-clock cap | start, stop, pause, and provider-wait events |
| Parallelism | Same maximum simultaneous model calls | admission log |
| Call opportunity | Same total model-call and tool-call caps | lifecycle log |
| Environment | Same sandbox image, hardware class where relevant, network policy, and locale | environment manifest |
| Sampling | Same declared temperature/top-p policy and matched seeds when supported | request parameters |
| Failure policy | Same timeout, retry, invalid-output, and outage rules | failure classification log |
| Stop information | Systems see remaining resources, never benchmark scores | harness transcript |
| Grader | Same frozen original scorer and scorer environment | scorer hash and raw result |

No single metric perfectly equates heterogeneous local and hosted inference. For
that reason the study imposes all major ceilings simultaneously. A run stops
when it finishes voluntarily or reaches the first ceiling. The common envelope
is chosen on the disjoint pilot set and frozen for all confirmatory systems; it is
not optimized separately for a team or model. During envelope selection,
correctness remains blinded. Researchers may inspect usage, cost, latency,
ceiling hits, valid-output rates, and infrastructure failures, but not which
answers were correct. This prevents selecting the cap at a point where one
condition happened to lead.

Unused capacity is reported. Models are never forced to consume budget merely to
make usage equal.

## 10. Resource accounting

### 10.1 Compute proxy

When measured inference FLOPs are not available for every provider, the primary
cross-provider compute proxy is:

```text
condition compute = sum over all model calls(
    disclosed active parameters * processed model tokens
)
```

Processed model tokens include uncached input, cached input, hidden reasoning
tokens when disclosed, and generated output. Cache categories are preserved so
alternate accounting can be reported. For providers that expose measured FLOPs,
both measured FLOPs and the common proxy are retained. Total rather than active
MoE parameters is used in a preregistered sensitivity analysis.

If a provider hides reasoning-token counts or any quantity needed to enforce a
cap prospectively, that model is ineligible unless the missing usage can be
bounded conservatively before the next call. Unknown usage is never treated as
zero.

### 10.2 Monetary accounting

Hosted APIs use the frozen provider price schedule effective on the protocol
date. Local and rented inference is not labeled free. It is valued using actual
rental charges where possible; otherwise the preregistered amortized hardware,
energy, and hosting schedule is used. Idle capacity reserved exclusively for a
condition counts during its wall-clock run.

Provider discounts, batch pricing, cache discounts, and failed-call charges are
recorded both as actually billed and under a normalized list-price sensitivity
schedule. The prospective cap uses the preregistered primary schedule.

### 10.3 Time and concurrency

Wall time starts when the task becomes available to the system and stops when a
valid final answer is irrevocably submitted. Model queue time and communication
time count. A verified platform-wide outage may pause the clock only under the
failure rule in Section 15; discretionary waiting does not.

Conductor admits calls atomically so concurrent descendants cannot collectively
overshoot a ceiling beyond one already-admitted call per slot. Reservations use
a conservative maximum charge; unused reservations are released after final
usage arrives.

## 11. Open-peer specialist collaboration

### 11.1 Design principles

The specialist room must not smuggle a frontier-quality decision maker into the
team. All root members have symmetric permissions and see the same durable room
state. There is no chair, fixed debate schedule, mandatory speaking order,
semantic judge, or privileged synthesizer.

Peers may:

- publish claims with confidence and scope;
- attach evidence or tool artifacts;
- challenge a claim and request a response;
- ask another peer a directed question;
- propose and revise final-answer candidates;
- endorse or withdraw endorsement from a candidate;
- remain silent when they judge their specialty irrelevant;
- use tools or create eligible descendants; and
- submit a private final ballot when the room closes.

Specialization is available to the models as metadata, but the harness does not
route an item based on a hand-authored domain label. The team decides who should
contribute.

### 11.2 Candidate lifecycle and finalization

Final answers are versioned candidate artifacts. A candidate records its author,
parent version, content hash, benchmark output-schema validation, supporting
claims, and endorsements.

The team can finish early when every active root independently endorses the same
valid candidate. If no unanimous candidate exists when a ceiling or inactivity
boundary closes the room, each root casts a private ballot over valid candidates.
A strict plurality selects the answer. An exact tie, no valid candidate, or no
ballots produces an unresolved run, which is incorrect for the primary outcome.
The harness never asks a model to break a tie and never evaluates candidate
meaning.

Private closing ballots reduce last-speaker and social-pressure effects. The full
public transcript and ballot commitments are released after scoring, subject to
provider-policy redactions declared in advance.

### 11.3 Liveness and fault handling

The room uses event-driven wakeups rather than fixed debate rounds. Backpressure
limits simultaneous unresolved requests. Heartbeats and leases distinguish a
quiet peer from a lost process. Durable events support resume after a harness
crash without replaying already billed model calls. Recovery preserves the
original condition ID, resource ledger, participant identity, candidate versions,
and remaining ceilings.

Inactivity thresholds are fixed before testing and identical at the system level.
Silence by one peer does not grant another permanent control.

## 12. Workbench architecture

The implementation creates a new independent Python project,
`specialist-workbench/`, for the experiment driver, protocol manifests, Inspect
tasks, receipt joins, and statistical analysis. It also extends existing
monorepo projects at their natural boundaries. No project imports another
project's package code: the workbench launches separately installed, versioned
commands and consumes documented JSON events and receipts.

### 12.1 Codex Conductor responsibilities

Codex Conductor is the executor governance layer. It will:

- bind every root and descendant to a condition ID;
- validate model admission against the frozen eligible-model catalog;
- add a versioned external-participant contract for specialist adapters that
  supplies pre-call admission, conservative reservation, post-call usage, and
  terminal lifecycle events without proxying model traffic;
- enforce shared token, compute, dollar, time, concurrency, and call ceilings;
- track root/descendant lineage and stable session identity;
- reserve and reconcile usage for concurrent calls;
- capture lifecycle, interruption, retry, and recovery events; and
- export an immutable resource receipt for evaluation.

Conductor governs execution but does not decide which answer is better.

### 12.2 Agent Harness responsibilities

Agent Harness is the collaboration layer. It will add:

- live, resumable provider and coding-CLI adapters;
- multiple ongoing responses per participant rather than one terminal response;
- typed claim, evidence, challenge, question, candidate, endorsement, and ballot
  events;
- a symmetric room-state projection;
- concurrent peer wakeups with backpressure and inactivity handling;
- candidate lineage and schema validation;
- deterministic finalization without semantic judging; and
- transcript and collaboration receipts.

Agent Harness will not import Codex Conductor or access its store. Its live
adapter interface will expose generic admission and usage callbacks rather than
Conductor-specific types. The research driver configures those callbacks at the
process boundary and correlates runs through stable condition/session identifiers
and versioned events. Agent Harness remains independently usable with a no-op or
different admission implementation.

### 12.3 Specialist Workbench responsibilities

The new Specialist Workbench research driver will:

- randomize and launch condition runs;
- coordinate the separately installed Conductor and Agent Harness processes
  through their public command/event protocols, without importing either
  package;
- provide benchmark items and benchmark-native tool profiles;
- accept only an irrevocably frozen final answer;
- blind system identity before scoring;
- call the original scorer in a pinned environment; and
- join the score with Conductor and Agent Harness receipts after grading.

Inspect AI supplies the evaluation structure and audit trail. Each benchmark
adapter delegates correctness to the benchmark's original scorer rather than a
generic Inspect model judge. The evaluator consumes package outputs through
documented process interfaces; it does not require one monorepo package to
become an imported runtime dependency of another.

### 12.4 Execution boundary

Frontier roots and Codex-supported descendants run through noninteractive,
resumable Codex sessions and Conductor's native lifecycle hooks. Open-weight
specialists may be served locally or on rented cloud compute; other specialists
may use versioned hosted APIs. Agent Harness live adapters call those endpoints
only after the external-participant contract returns a Conductor admission lease,
then reconcile actual usage and lifecycle state through that lease.

The study does not assume that Codex can natively host an arbitrary Hugging Face
or third-party model, and it will not label a synthetic wrapper as a native Codex
session. Conductor remains an admission and accounting guardrail, not a model
traffic proxy. A provider that cannot expose enough identity, usage, or lifecycle
information for prospective ceiling enforcement is excluded from the primary
catalog.

The data flow is:

```text
frozen item + envelope
        |
evaluation driver
        |
frontier: Codex root session ---- native Conductor lifecycle hooks
specialists: Agent Harness live adapters ---- external admission leases
        |                                      |
        +---------- Conductor resource ledger -+
        |
Agent Harness peer room (specialist condition)
        |
irrevocably frozen answer
        |
blinded benchmark-native scorer
        |
score + execution receipt + collaboration receipt
```

## 13. Grading and outcomes

### 13.1 Why benchmark-native grading is primary

Published work on structured reasoning, mathematics, code, and question answering
usually grades with authoritative answers or executable tests. LLM and preference
judges become common when the task itself is open-ended, as in conversational
helpfulness benchmarks. This study can avoid that validity risk by selecting
objectively gradable tasks.

Accordingly, Inspect AI is the evaluation framework, not the source of a new
quality rubric. Original benchmark scorers remain authoritative:

- exact match or multiple-choice accuracy;
- symbolic or numeric equivalence;
- official F1 where a benchmark defines partial answer overlap;
- executable unit/integration tests for code; and
- deterministic instruction-compliance checks.

This choice is more defensible than either a universal LLM judge or an invented
weighted score because it preserves the construct each benchmark was designed to
measure and makes replication possible with public scorer code.

### 13.2 Primary outcome

The primary outcome for item `i` and condition run `r` is binary:

```text
Y_ir = 1 if the frozen answer is correct under the native scorer
       0 otherwise
```

Benchmark-specific partial credit is retained as a secondary outcome, not folded
into a project-created composite. A benchmark with several official binary
checks uses its documented item-level aggregation rule.

Timeouts, refusals, malformed final outputs, cap exhaustion without a valid
answer, and unresolved team ballots score zero unless the original benchmark
defines another treatment.

### 13.3 Secondary outcomes

- native partial-credit score;
- dollars, wall seconds, tokens, and compute proxy actually consumed;
- correctness per resource unit, reported separately for each denominator;
- early-finish and ceiling-exhaustion rates;
- operational failure, retry, and unresolved-decision rates;
- calibration where a condition provides a valid confidence value; and
- tail measures, including worst-family and lower-quartile correctness.

There will be no single “quality-efficiency” number.

## 14. Randomization, blinding, and run procedure

For each item-system-seed cell:

1. The driver creates a fresh condition ID and pins the item, prompt, tool,
   environment, price, model-catalog, and envelope hashes.
2. Conductor admits the root session or specialist roots and starts the shared
   condition clock.
3. The system works autonomously. The driver exposes remaining ceilings but no
   score, reference answer, other condition transcript, or success signal.
4. The system finishes voluntarily or the first ceiling closes it.
5. The final answer is schema-validated, hashed, timestamped, and made
   irrevocable.
6. System and model identifiers are replaced with blind IDs.
7. The pinned native scorer runs in a fresh environment and stores raw scorer
   output.
8. Only after grading are the score, execution receipt, and collaboration receipt
   joined for analysis.

Condition order is block-randomized to spread provider drift, transient load,
and benchmark order effects. Seeds are matched where providers expose equivalent
controls; otherwise repeated runs and provider-level random effects absorb
uncontrolled sampling variance. Randomization code and its seed are frozen
before the confirmatory sample is opened.

## 15. Failure and missing-data policy

Failures attributable to the evaluated system are part of effectiveness:

- a model timeout within a healthy provider,
- refusal,
- invalid or missing answer,
- self-created deadlock,
- budget exhaustion, and
- an unresolved specialist vote

all score incorrect in the primary analysis.

A failure is classified as infrastructure-caused only when independent health
evidence shows that the evaluation platform, network, or provider was unavailable
outside the model's control. The classification is made without seeing answer
correctness. A verified infrastructure failure is rerun once from pristine state
with the same item, condition, envelope, and seed where supported. The failed
attempt and its cost remain in the audit log but are excluded from the primary
effectiveness cell. If the identical infrastructure class fails again, the cell
is marked infrastructure-missing under the preregistered missingness rule.

The primary model uses all observed cells. Sensitivity analyses (a) treat all
infrastructure-missing cells as incorrect and (b) use inverse-probability
weighting if missingness is nontrivial. Model-caused failures are never converted
to missing data.

## 16. Statistical analysis

### 16.1 Sample size

The pilot estimates baseline correctness, between-item variance, within-system
seed variance, intraclass correlation, and the feasible common resource envelope.
Before confirmatory testing, a simulation-based power analysis will select the
number of items and repetitions needed for at least 80% power at one-sided
`alpha = 0.05` to detect a five-percentage-point absolute increase in the
equal-family-weighted mean correctness. Five points is the minimum effect treated
as scientifically meaningful; it is fixed in this proposal rather than selected
from pilot performance.

The minimum of three teams and three frontier roots is a design floor, not a
claim that six systems guarantee precise population inference. If feasible
system counts limit power over model identity, the paper will narrow its claim
to the evaluated frozen systems and show that limitation explicitly.

### 16.2 Primary model

The primary analysis is a hierarchical logistic regression over binary item
correctness:

```text
logit(P(correct)) = beta_0
                  + beta_1 * specialist_team_condition
                  + benchmark-family random intercept and condition slope
                  + item random intercept
                  + system-identity random intercept
                  + repetition random intercept
```

The confirmatory test is `H0: beta_1 <= 0` versus `H1: beta_1 > 0`. The analysis
reports the coefficient, odds ratio, average marginal difference in correctness,
one-sided p-value, and two-sided 95% confidence interval.

The exact model parameterization, priors if a Bayesian robustness model is used,
optimizer, convergence rules, and fallback estimator are fixed in the
preregistration using pilot data only.

### 16.3 Supporting analyses

- cluster bootstrap intervals over items and system identities;
- correctness by benchmark family and every team-frontier pairing;
- Holm-adjusted pairwise comparisons;
- heterogeneity of the condition effect across benchmark families;
- lower-tail, failure-rate, and ceiling-hit comparisons;
- correctness-versus-cost, time, token, and compute Pareto frontiers;
- individual-specialist and communication ablations; and
- sensitivity to MoE total-parameter accounting, normalized prices, public-item
  contamination risk, and infrastructure missingness.

No favorable subgroup result will be presented as confirmation if the primary
cross-suite superiority test fails.

## 17. Preregistration and decision rules

Before opening the confirmatory set, the following artifacts are frozen and
published with hashes:

- research questions, hypotheses, and estimand;
- eligible-model catalogs and evidence dossiers;
- team-construction algorithm and final rosters;
- benchmark versions, partitions, exclusions, and scorers;
- task prompts, collaboration prompts, and tool profiles;
- all ceilings and reservation rules;
- randomization and seed plan;
- failure and missing-data policy;
- primary and secondary statistical models;
- minimum meaningful effect and power simulation; and
- code, container, dependency, and price-table versions.

Confirmatory success requires a favorable, statistically significant primary
condition effect under the locked analysis and a confidence interval whose
favorable bound excludes zero. This supports the bounded claim defined by the
frozen task and system populations. It does not justify an unrestricted claim
that specialists always beat frontier models.

A null or unfavorable result is reported as such. Changes made after seeing
confirmatory outcomes are labeled exploratory or replication changes and never
back-propagated into the original protocol.

## 18. Reproducibility and research receipts

Every condition run produces three joinable, append-only receipts:

1. an **execution receipt** from Conductor containing identities, lineage,
   admissions, calls, usage, costs, compute proxy, timings, ceilings, and failure
   events;
2. a **collaboration receipt** from Agent Harness containing room events,
   artifacts, candidate lineage, endorsements, ballots, and recovery events; and
3. an **evaluation receipt** containing item/scorer hashes, blinded answer,
   scorer environment, raw scorer output, and final native metrics.

Receipts share a condition ID but do not require one package to import another.
Secrets, private reasoning hidden by a provider, and prohibited benchmark content
are not fabricated or exposed. Redactions are machine-marked with a reason, and
their absence from the public artifact is documented.

The release package should include protocol and analysis code, frozen prompts,
catalog evidence, environment manifests, scorer adapters, aggregate receipts,
and all transcripts and outputs permitted by model, benchmark, and provider
licenses. Reproduction instructions must distinguish a bitwise replay from a
new run against a changing hosted service.

## 19. Threats to validity and mitigations

### Construct validity

**Threat:** “Output quality” is broader than objective correctness.  
**Mitigation:** The primary claim is explicitly about correctness on objectively
scored text tasks. Helpfulness, style, creativity, and multimodal quality are not
silently generalized from this study.

**Threat:** Parameter-times-token is an imperfect compute measure across
architectures and hardware.  
**Mitigation:** Impose simultaneous cost, time, token, concurrency, and compute
ceilings; report actual use; retain measured FLOPs where available; run
preregistered alternate accounting.

### Internal validity

**Threat:** An orchestrator or answer judge could be the true cause of a team
gain.  
**Mitigation:** Use symmetric peers, deterministic non-semantic finalization, and
no privileged synthesizer; compare against no-communication and routing
ablations.

**Threat:** The systems receive unequal agentic freedom.  
**Mitigation:** Allow both sides to decide whether to call helpers, use tools,
revise, or finish, with all activity charged to the same envelope.

**Threat:** Provider drift, queueing, or transient incidents favor one condition.  
**Mitigation:** Freeze model versions, block-randomize order, repeat seeds, log
health, blind failure classification, and separate replications after silent
model changes.

### External validity

**Threat:** Handpicked specialists or frontier models do not represent their
populations.  
**Mitigation:** Use multiple systems, publish deterministic selection rules and
all candidate evidence, include lineage diversity, and limit conclusions to the
frozen eligible population where system counts are small.

**Threat:** Public benchmarks are contaminated or narrow.  
**Mitigation:** Prefer hidden and time-split items, audit dates, span several
capability families, and report a lowest-contamination-risk sensitivity subset.

**Threat:** Text results may not transfer to images or other modalities.  
**Mitigation:** State text-only scope and require a new protocol for each added
modality.

### Conclusion validity

**Threat:** Multiple comparisons or favorable subgroup selection create a false
positive story.  
**Mitigation:** Use one locked primary test, adjust pairwise analyses, publish all
families and pairings, and prevent secondary results from substituting for the
primary outcome.

## 20. Safety, ethics, and operational constraints

The benchmark suite will exclude tasks that require deploying harmful code or
acting on live systems. Code execution occurs in a pinned, isolated sandbox with
no undeclared credentials. Retrieval corpora and transcripts are checked for
personal or licensed data restrictions before release.

Provider terms, model licenses, and benchmark licenses are recorded per artifact.
Secrets are passed through the existing execution environment and never written
to research receipts. Cost ceilings are hard stops with conservative concurrent
reservations. No run may publish, deploy, message external parties, or modify a
live user installation as part of a benchmark task.

The study reports energy or hardware usage when providers expose it, but will not
claim exact environmental equivalence from the compute proxy alone.

## 21. Implementation and study phases

### Phase 0: protocol and candidate audit (approximately 3 weeks)

- audit specialist and frontier candidates against disclosure rules;
- audit benchmark versions, scorers, licenses, and contamination risk;
- finalize the resource-accounting schema;
- publish selection, replacement, and preregistration procedures.

**Exit criterion:** at least three feasible teams and three feasible frontier
models, plus an objectively scored candidate suite.

### Phase 1: independent workbench extensions (approximately 6 weeks)

- add condition-wide admission, the external-participant contract, and receipt
  export to Conductor without turning it into a traffic proxy;
- add live peer sessions, typed artifacts, candidate finalization, and recovery
  to Agent Harness;
- scaffold `specialist-workbench/` and build its Inspect-based driver, protocol
  manifests, receipt joins, and native scorer adapters;
- add deterministic simulation tests for ceilings, crashes, ties, and overshoot.

**Exit criterion:** end-to-end fake-provider experiments replay deterministically
and cannot exceed a ceiling except for the documented final admitted-call bound.

### Phase 2: live pilot (approximately 3 weeks)

- validate local, rented, and API adapters;
- run only selection and pilot items;
- choose the common feasible envelope;
- estimate variance, effect threshold, item count, repetitions, and total cost;
- verify scorer blinding and receipt joins.

**Exit criterion:** complete preregistration and a funded confirmatory run plan.

### Phase 3: confirmatory execution (approximately 4–8 weeks)

- freeze all artifacts and hashes;
- execute randomized condition cells;
- monitor infrastructure health without viewing correctness by condition;
- score frozen outputs and lock the joined dataset.

**Exit criterion:** the preregistered completion and missing-data thresholds are
met without protocol-invalidating drift.

### Phase 4: analysis and release (approximately 3 weeks)

- execute the locked primary analysis;
- run labeled secondary and sensitivity analyses;
- release reproducible artifacts permitted by licenses;
- write the result regardless of whether H1 is supported.

The expected total duration is approximately 19–23 weeks. The monetary budget is
calculated from the pilot-selected envelope, powered cell count, provider prices,
and a preregistered infrastructure-failure reserve rather than guessed before
candidate APIs and model sizes are known.

## 22. Expected contributions

The project is intended to produce:

1. a controlled empirical answer about whether learned small-model
   specialization plus peer collaboration can beat frontier-generalist-led
   systems under equal ceilings;
2. a reusable experimental protocol for comparing agent systems without
   conflating quality with resource advantage;
3. an open-peer collaboration design that does not depend on a superior manager
   or judge model;
4. auditable multi-dimensional resource receipts spanning roots and descendants;
   and
5. evidence about when collaboration, specialization, or generalist scale is the
   better allocation of the same opportunity.

The most scientifically valuable result is a credible one. A specialist victory
would challenge the default assumption that frontier scale dominates under equal
resources. A frontier victory or null result would establish a useful boundary
on the value of heterogeneous specialist teams and identify whether the limiting
factor is specialist capability, coordination cost, or task coverage.

## References

1. Li, J., Zhang, Q., Yu, Y., Fu, Q., and Ye, D. (2024). [More Agents Is All You Need](https://arxiv.org/abs/2402.05120). *Transactions on Machine Learning Research*.
2. Du, Y., Li, S., Torralba, A., Tenenbaum, J. B., and Mordatch, I. (2023). [Improving Factuality and Reasoning in Language Models through Multiagent Debate](https://arxiv.org/abs/2305.14325).
3. Wang, J., Wang, J., Athiwaratkun, B., Zhang, C., and Zou, J. (2024). [Mixture-of-Agents Enhances Large Language Model Capabilities](https://arxiv.org/abs/2406.04692).
4. Żywot, A., Chen, X., Yuan, Y., Søgaard, A., and de Rijke, M. (2026). [Can Small Agents Collaborate to Beat a Single Large Language Model?](https://arxiv.org/abs/2601.11327).
5. Kim, Y., Gu, K., Park, C., et al. (2026). [Capable Language Models Can Outgrow the Benefits of Collaboration](https://www.nature.com/articles/s42256-026-01268-y). *Nature Machine Intelligence*.
6. ElZemity, A., Li, S., and Arief, B. (2026). [Small, Free, and Effective: Orchestrating Open-Weight Small Language Models to Outperform Single LLM for Malware Analysis](https://arxiv.org/abs/2607.20216).
7. Wang, X. and Brorsson, M. (2026). [Rethinking Scale: Deployment Trade-offs of Small Language Models under Agent Paradigms](https://arxiv.org/abs/2604.19299).
8. UK AI Security Institute. [Inspect AI evaluation framework](https://inspect.aisi.org.uk/).
9. EleutherAI. [Language Model Evaluation Harness](https://github.com/EleutherAI/lm-evaluation-harness).
