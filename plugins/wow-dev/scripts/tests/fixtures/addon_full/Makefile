FAIL_TARGETS ?=
RUN = @case " $(FAIL_TARGETS) " in *" $@ "*) echo "boom $@" >&2; exit 1 ;; esac; echo "ok $@"

help:
	@echo "fixture makefile"

test:
	$(RUN)

test-file:
	$(RUN)

test-pattern:
	$(RUN)

all_checks:
	$(RUN)

i18n_check:
	$(RUN)

i18n_fmt:
	$(RUN)

toc_check:
	$(RUN)

check_untracked_files:
	$(RUN)

dev:
	$(RUN)

build:
	$(RUN)
