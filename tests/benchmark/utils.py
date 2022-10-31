import dictdatabase as DDB
from path_dict import pd
import random
import time
import json


def make_table(recursion_depth=3, keys_per_level=50):
	d = {"key1": "val1", "key2": 2, "key3": [1, "2", [3, 3]]}
	for i in range(recursion_depth):
		d = {f"key{i}{j}": d for j in range(keys_per_level)}
	# print(f"Made table of size {len(json.dumps(d)) // 1e6}mb")
	return {"counter": {"counter": 0}, "big": d}


def print_stats(i, durations):
	avg = f"{sum(durations) / len(durations):.0f}"
	median = f"{sorted(durations)[len(durations) // 2]:.0f}"
	min_t = f"{min(durations):.0f}"
	max_t = f"{max(durations):.0f}"

	# print(f"{i}: total: {len(durations)}, avg: {avg}ms (med: {median}), {min_t}-{max_t}ms")


def print_and_assert_results(readers, writers, per_proc, tables, big_file, compression, t1, t2):
	ops = (writers + readers) * per_proc * tables
	ops_sec = f"{(ops / (t2 - t1)):.0f}"
	print(f"⏱️  {ops_sec} op/s ({ops} in {t2 - t1:.2f}s), {big_file = }, {compression = }")
	for t in range(tables):
		db = DDB.at(f"incr{t}").read()
		assert db["counter"]["counter"] == per_proc * writers
		# print(f"✅ counter={db['counter']}")


def random_reads(file_count):
	""" Read the n tables in random order """
	for t in sorted(range(file_count), key=lambda _: random.random()):
		DDB.at(f"incr{t}").read(key="counter")


def random_writes(file_count):
	""" Iterated the n tables in random order and increment the counter """
	for t in sorted(range(file_count), key=lambda _: random.random()):
		with DDB.at(f"incr{t}").session(key="counter", as_type=pd) as (session, d):
			d.at("counter").set(d.at("counter").get() + 1)
			session.write()


def db_job(mode="r", file_count=1, per_proc=1):
	durations = []
	for _ in range(per_proc):
		t_start = time.monotonic_ns()
		random_writes(file_count) if mode == "w" else random_reads(file_count)
		t_end = time.monotonic_ns()
		durations.append((t_end - t_start) / 1e6)
	print_stats(mode, durations)
