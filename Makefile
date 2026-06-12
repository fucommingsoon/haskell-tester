PB_TASKS  := /Users/kangxin/.cache/uv/archive-v0/sTrhsMs9voIeKDQ8/programbench/data/tasks
HF_TESTS  := /Users/kangxin/.cache/huggingface/hub/datasets--programbench--ProgramBench-Tests/snapshots/de0ddfb637590c7ecb54fa0b5301f6dc7dfbcee5
OUT       := distill_out

TASK ?= eradman__entr.8e2e8b4

.PHONY: parse-one parse-all summarize classify-rules classify-hybrid clean

parse-one:
	@mkdir -p $(OUT)
	python3 scripts/parse_graders.py \
		--task $(TASK) \
		--tasks-dir $(PB_TASKS) \
		--hf-tests $(HF_TESTS) \
		--out $(OUT)/features.$(TASK).jsonl

parse-all:
	@mkdir -p $(OUT)
	python3 scripts/parse_graders.py \
		--all \
		--tasks-dir $(PB_TASKS) \
		--hf-tests $(HF_TESTS) \
		--out $(OUT)/features.all.jsonl

summarize:
	@mkdir -p $(OUT)
	python3 scripts/summarize_features.py \
		--features $(OUT)/features.all.jsonl \
		--out $(OUT)/summaries.jsonl

classify-rules:
	python3 scripts/classifier.py

classify-hybrid:
	uv run --with anthropic python scripts/classifier_llm.py $(ARGS)

clean:
	rm -rf $(OUT)/*.jsonl
