# Host build of the reference runtime: `make` -> build/jtalm
# -ffp-contract=off keeps every f32 multiply and add separately rounded, as in PyTorch.
CC ?= cc
CFLAGS ?= -O2
override CFLAGS += -std=c11 -Wall -Wextra -pedantic -ffp-contract=off
override LDLIBS += -lm

SRCS = model.c tokenizer.c grammar.c main.c
BUILD = build

$(BUILD)/jtalm: $(SRCS) jtalm.h
	@mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -o $@ $(SRCS) $(LDFLAGS) $(LDLIBS)

clean:
	rm -rf $(BUILD)

.PHONY: clean
