CFLAGS ?= -Wall -Wextra -O2 -std=c11

.PHONY: test clean
test: test_leaf_gw test_gw_supervisor
	./test_leaf_gw
	./test_gw_supervisor
	python3 tools/mutate_supervisor.py
	python3 tools/leaf_iccan_check.py --self-test
	python3 openpilot/test_leaf_gw_long.py

test_leaf_gw: leaf_gw.c gw_engine.c test_leaf_gw.c leaf_gw.h gw_engine.h
	$(CC) $(CFLAGS) leaf_gw.c gw_engine.c test_leaf_gw.c -lm -o $@

test_gw_supervisor: gw_supervisor.c test_gw_supervisor.c gw_supervisor.h
	$(CC) $(CFLAGS) gw_supervisor.c test_gw_supervisor.c -o $@

clean:
	rm -f test_leaf_gw test_gw_supervisor
