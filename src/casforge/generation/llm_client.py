"""
llm/llm_client.py
-----------------
Thin wrapper around llama-cpp-python.

Loads the GGUF model once (lazy, on first call â€” model load is expensive)
and exposes a single chat() function for the rest of Phase 2.

Config (all from .env via config/settings.py):
    LLM_MODEL_PATH      â€” required: absolute path to the .gguf file
    LLM_CONTEXT_LENGTH  â€” default 8192
    LLM_GPU_LAYERS      â€” default 0 (CPU only)
    LLM_TEMPERATURE     â€” default 0.1
    LLM_MAX_TOKENS      â€” default 2048
"""

from __future__ import annotations

import atexit
import logging
import os

from casforge.shared.settings import (
    LLM_MODEL_PATH,
    LLM_CONTEXT_LENGTH,
    LLM_GPU_LAYERS,
    LLM_NUM_THREADS,
)

_log = logging.getLogger(__name__)
_llm = None  # singleton â€” loaded once, reused
_atexit_registered = False


def _close_llm_safely():
    global _llm
    if _llm is None:
        return
    try:
        _llm.close()
    except Exception:
        # llama-cpp cleanup can throw at interpreter shutdown on some builds.
        # Best-effort close keeps runtime clean for normal calls.
        pass
    finally:
        _llm = None


def _load():
    global _llm, _atexit_registered
    if _llm is not None:
        return _llm

    if not LLM_MODEL_PATH:
        raise RuntimeError(
            "LLM_MODEL_PATH is not set in .env\n"
            "Add a line like:  LLM_MODEL_PATH=D:\\Models\\llama-3.2-3b-instruct.Q4_K_M.gguf"
        )

    try:
        from llama_cpp import Llama
    except ImportError:
        raise ImportError(
            "llama-cpp-python is not installed.\n"
            "Run:  pip install llama-cpp-python"
        )

    _log.info("Loading LLM from %s ...", LLM_MODEL_PATH)
    # Thread count: use LLM_NUM_THREADS from .env, or default to physical core count.
    # os.cpu_count() returns logical threads (HT); //2 = physical cores.
    if LLM_NUM_THREADS > 0:
        _n_threads = LLM_NUM_THREADS
    else:
        _n_threads = max(1, (os.cpu_count() or 4) // 2)

    _log.info("LLM using %d CPU threads.", _n_threads)
    _llm = Llama(
        model_path=LLM_MODEL_PATH,
        n_ctx=LLM_CONTEXT_LENGTH,
        n_gpu_layers=LLM_GPU_LAYERS,
        n_threads=_n_threads,
        n_threads_batch=_n_threads,  # parallel prompt evaluation (prefill)
        verbose=False,
    )
    if not _atexit_registered:
        atexit.register(_close_llm_safely)
        _atexit_registered = True
    _log.info("LLM ready.")
    return _llm


def chat(
    system_prompt: str,
    user_prompt:   str,
    temperature:   float = 0.1,
    max_tokens:    int   = 2048,
) -> str:
    """
    Send a system + user message pair and return the assistant's text response.

    Parameters
    ----------
    system_prompt : str
        Instructions / persona for the model.
    user_prompt : str
        The actual request / input data.
    temperature : float
        Sampling temperature.  0.1 = near-deterministic (good for structured output).
    max_tokens : int
        Maximum tokens to generate in the response.

    Returns
    -------
    str
        The assistant's response, stripped of leading/trailing whitespace.
    """
    llm = _load()

    response = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )

    return response["choices"][0]["message"]["content"].strip()

