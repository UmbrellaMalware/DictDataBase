from __future__ import annotations
from dataclasses import dataclass
import orjson
import json
import zlib
import os
import hashlib
from pathlib import Path
from . import config, utils, byte_codes



@dataclass(frozen=True)
class PartialDict:
	prefix: bytes
	key: str
	value: dict
	suffix: bytes


@dataclass(frozen=True)
class PartialFileHandle:
	db_name: str
	partial_dict: PartialDict
	indent_level: int
	indent_with: str
	index_data: dict


################################################################################
#### Reading
################################################################################


def read_bytes(db_name: str, start=None, end=None) -> bytes:
	"""
		Read the content of a db as a string, or as bytes if as_bytes=True.
		Reading works even when the config changes, so a compressed ddb file can
		also be read if compression is disabled, and vice versa.
	"""
	json_path, json_exists, ddb_path, ddb_exists = utils.db_paths(db_name)

	if json_exists:
		if ddb_exists:
			raise FileExistsError(f"DB Inconsistency: \"{db_name}\" exists as .json and .ddb")
		with open(json_path, "rb") as f:
			if start is not None:
				f.seek(start)
				if end is not None:
					return f.read(end - start)
				return f.read()
			return f.read()
	if not ddb_exists:
		raise FileNotFoundError(f"DB does not exist: \"{db_name}\"")
	with open(ddb_path, "rb") as f:
		json_bytes = zlib.decompress(f.read())
		if start is not None:
			if end is not None:
				return json_bytes[start:end]
			return json_bytes[start:]
		return json_bytes


def read(db_name: str) -> dict:
	"""
		Read the file at db_path from the configured storage directory.
		Make sure the file exists. If it does notnot a FileNotFoundError is
		raised.
	"""
	# Always use orjson to read the file, because it is faster
	return orjson.loads(read_bytes(db_name))



def read_index_file(db_name: str) -> dict:
	path = f"{config.storage_directory}/.ddb/{db_name.replace('/', '___')}.index"
	Path(path).parent.mkdir(parents=True, exist_ok=True)
	if not os.path.exists(path):
		return {}
	with open(path, "rb") as f:
		return orjson.loads(f.read())


def write_index_file(index_data: dict, db_name: str, key, start_index, end_index, indent_level, indent_with, value_hash):
	path = f"{config.storage_directory}/.ddb/{db_name.replace('/', '___')}.index"
	index_data[key] = [start_index, end_index, indent_level, indent_with, value_hash]
	with open(path, "wb") as f:
		f.write(orjson.dumps(index_data))




def try_read_by_index(index_data, db_name, key):

	if (index := index_data.get(key, None)) is None:
		return None

	start_index, end_index, indent_level, indent_with, value_hash = index
	partial_bytes = read_bytes(db_name, start_index, end_index)

	if value_hash != hashlib.sha256(partial_bytes).hexdigest():
		return None

	return orjson.loads(partial_bytes)





def partial_read_only(db_name: str, key: str) -> dict:
	"""
		Partially read a key from a db.
		The key MUST be unique in the entire db, otherwise the behavior is undefined.
		This is a lot faster than reading the entire db, because it does not parse
		the entire file, but only the part <value> part of the <key>: <value> pair.

		If the key is not found, a `KeyError` is raised.
	"""

	# data = read_bytes(db_name)

	# Search for key in the index file
	index_data = read_index_file(db_name)

	if (value_data := try_read_by_index(index_data, db_name, key)) is not None:
		return value_data

	file_bytes = read_bytes(db_name)

	# Not found in index file, search for key in the entire file
	key_start, key_end = utils.find_outermost_key_in_json_bytes(file_bytes, key)

	if key_end == -1:
		raise KeyError(f"Key \"{key}\" not found in db \"{db_name}\"")

	# Key found, now determine the bounds of the value
	space_after_semicolon = 1 if file_bytes[key_end] == byte_codes.SPACE else 0
	value_start = key_end + space_after_semicolon
	value_end = utils.seek_index_through_value_bytes(file_bytes, value_start)

	indent_level, indent_with  = utils.detect_indentation_in_json_bytes(file_bytes, key_start)
	value_bytes = file_bytes[value_start:value_end]

	# Write key info to index file
	write_index_file(
		index_data,
		db_name,
		key,
		value_start,
		value_end,
		indent_level,
		indent_with,
		hashlib.sha256(value_bytes).hexdigest()
	)

	return orjson.loads(value_bytes)



def get_partial_file_handle(db_name: str, key: str) -> PartialFileHandle | dict:
	"""
		Partially read a key from a db.
		The key MUST be unique in the entire db, otherwise the behavior is undefined.
		This is a lot faster than reading the entire db, because it does not parse
		the entire file, but only the part <value> part of the <key>: <value> pair.

		If the key is not found, a `KeyError` is raised.
	"""

	data = read_bytes(db_name)

	# Search for key in the index file
	index_data = read_index_file(db_name)
	index = index_data.get(key, None)
	if index is not None:
		start_index, end_index, indent_level, indent_with, value_hash = index
		partial_bytes = data[start_index:end_index]
		partial_bytes_hash = hashlib.sha256(partial_bytes).hexdigest()
		if value_hash == partial_bytes_hash:
			partial_value = orjson.loads(partial_bytes)
			partial_dict = PartialDict(data[:start_index], key, partial_value, data[end_index:])
			return PartialFileHandle(db_name, partial_dict, indent_level, indent_with, index_data)

	# Not found in index file, search for key in the entire file
	key_start, key_end = utils.find_outermost_key_in_json_bytes(data, key)

	if key_end == -1:
		raise KeyError(f"Key \"{key}\" not found in db \"{db_name}\"")

	# Key found, now determine the bounds of the value
	space_after_semicolon = 1 if data[key_end] == byte_codes.SPACE else 0
	value_start = key_end + space_after_semicolon
	value_end = utils.seek_index_through_value_bytes(data, value_start)

	indent_level, indent_with  = utils.detect_indentation_in_json_bytes(data, key_start)
	partial_bytes = data[value_start:value_end]

	# Write key info to index file
	write_index_file(
		index_data,
		db_name,
		key,
		value_start,
		value_end,
		indent_level,
		indent_with,
		hashlib.sha256(partial_bytes).hexdigest()
	)

	partial_value = orjson.loads(partial_bytes)

	partial_dict = PartialDict(data[:value_start], key, partial_value, data[value_end:])
	return PartialFileHandle(db_name, partial_dict, indent_level, indent_with, index_data)


################################################################################
#### Writing
################################################################################


def write_bytes(db_name: str, dump: bytes):
	"""
		Write the bytes to the file of the db_path.
		If the db was compressed but now config.use_compression is False,
		remove the compressed file, and vice versa.
	"""
	json_path, json_exists, ddb_path, ddb_exists = utils.db_paths(db_name)
	# Write bytes or string to file
	if config.use_compression:
		write_path = ddb_path
		if json_exists:
			os.remove(json_path)
	else:
		write_path = json_path
		if ddb_exists:
			os.remove(ddb_path)

	# Compress if required
	if config.use_compression:
		dump = zlib.compress(dump, 1)

	# Write bytes or string to file
	with open(write_path, "wb") as f:
		f.write(dump)


def write(db_name: str, data: dict):
	"""
		Write the dict db dumped as a json string
		to the file of the db_path.
	"""
	if config.use_orjson:
		option = orjson.OPT_INDENT_2 if config.indent else 0
		option |= orjson.OPT_SORT_KEYS if config.sort_keys else 0
		db_dump = orjson.dumps(data, option=option)
	else:
		db_dump = json.dumps(data, indent=config.indent, sort_keys=config.sort_keys)
		db_dump = db_dump.encode()

	write_bytes(db_name, db_dump)


def partial_write(pf: PartialFileHandle):
	"""
		Write a partial file handle to the db.
	"""

	if config.use_orjson:
		option = orjson.OPT_INDENT_2 if config.indent else 0
		option |= orjson.OPT_SORT_KEYS if config.sort_keys else 0
		partial_dump = orjson.dumps(pf.partial_dict.value, option=option)
	else:
		partial_dump = json.dumps(pf.partial_dict.value, indent=config.indent, sort_keys=config.sort_keys)
		partial_dump = partial_dump.encode()
	if pf.indent_level > 0 and pf.indent_with:
		replace_this = "\n".encode()
		replace_with = ("\n" + (pf.indent_level * pf.indent_with)).encode()
		partial_dump = partial_dump.replace(replace_this, replace_with)

	write_index_file(
		pf.index_data,
		pf.db_name,
		pf.partial_dict.key,
		len(pf.partial_dict.prefix),
		len(pf.partial_dict.prefix) + len(partial_dump),
		pf.indent_level,
		pf.indent_with,
		hashlib.sha256(partial_dump).hexdigest()
	)

	write_bytes(pf.db_name, pf.partial_dict.prefix + partial_dump + pf.partial_dict.suffix)
