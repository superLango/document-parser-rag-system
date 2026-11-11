"""Canonicalization package (M1.8)."""

from .align import align_inventory
from .dictionary import (
    DICTIONARY_FILENAMES,
    ApiDictionaryAdapter,
    DbDictionaryAdapter,
    DictionaryIndex,
    JsonDictionaryAdapter,
    dictionary_file_for_type,
    diff_dictionaries,
    load_dictionary,
    load_dictionary_path,
    merge_dictionaries,
    split_dictionary,
    write_dictionary_parts,
)
from .http_dictionary import BusinessApiError, HttpDictionaryAdapter
from .items import match_item, match_property
from .methods import match_method, match_method_cell
from .prompt import build_whitelist, prompt_terms, render_prompt
from .review import find_new_term, reapply_alignment, review_new_term
from .terms import (
    find_term,
    load_new_terms,
    merge_new_terms,
    promote_term,
    reject_term,
    save_new_terms,
)

__all__ = [
    "ApiDictionaryAdapter",
    "BusinessApiError",
    "DICTIONARY_FILENAMES",
    "DbDictionaryAdapter",
    "DictionaryIndex",
    "HttpDictionaryAdapter",
    "JsonDictionaryAdapter",
    "align_inventory",
    "build_whitelist",
    "dictionary_file_for_type",
    "diff_dictionaries",
    "find_term",
    "find_new_term",
    "load_dictionary",
    "load_dictionary_path",
    "load_new_terms",
    "match_item",
    "match_method",
    "match_method_cell",
    "match_property",
    "merge_dictionaries",
    "merge_new_terms",
    "prompt_terms",
    "promote_term",
    "reapply_alignment",
    "reject_term",
    "render_prompt",
    "review_new_term",
    "save_new_terms",
    "split_dictionary",
    "write_dictionary_parts",
]
