FAIL_TARGETS ?=
RUN = @case " $(FAIL_TARGETS) " in *" $@ "*) echo "boom $@" >&2; exit 1 ;; esac; echo "ok $@"

help:
	@echo "fixture makefile"

test:
	$(RUN)

toc_check:
	$(RUN)
