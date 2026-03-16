# CASForge: Key Improvement Areas

This document outlines the key areas for improvement identified during the code review. These recommendations are prioritized based on their potential impact on maintainability, scalability, and developer experience.

## 1. Refactor Core Modules for Better Maintainability

**Area:** `generation` and `parsing` modules.
**Files:** `src/casforge/generation/forge.py`, `src/casforge/parsing/feature_parser.py`.

**Observation:**
The core logic for feature assembly (`forge.py`) and Gherkin parsing (`feature_parser.py`) is concentrated in large, complex files. While internally well-structured, their size makes them difficult to navigate and maintain.

**Proposed Improvements:**
- **Break down `forge.py`:** Extract the logic for building the different parts of a feature file (header, scenarios, examples tables) into a separate, dedicated `feature_builder.py` module. This would leave `forge.py` to focus on orchestrating the two-phase (Retrieval+LLM and Assembly) pipeline.
- **Modularize `feature_parser.py`:** While more challenging due to the nature of a state machine, consider extracting some of the helper functions (e.g., for parsing annotations, dicts, and tables) into a separate utility module.

**Benefit:**
Smaller, more focused modules are easier to understand, test, and maintain, especially for new developers joining the project.

## 2. Adopt a Robust Prompt Templating Engine

**Area:** `generation` module.
**Files:** `src/casforge/generation/intent_extractor.py`, `src/casforge/generation/forge.py`.

**Observation:**
LLM prompts are currently constructed using basic string replacement (`.replace()`). This is brittle and has already required workarounds to avoid conflicts with JSON syntax within the prompts.

**Proposed Improvement:**
- **Integrate Jinja2:** Replace the string replacement logic with a standard templating engine like Jinja2. The prompts (`.txt` files) can be converted to Jinja2 templates.

**Benefit:**
Jinja2 is more powerful, readable, and less error-prone. It would provide a clean separation between the prompt structure and the data being inserted, making the prompts easier to manage and evolve.

## 3. Refactor Web Endpoints to Reduce Code Duplication

**Area:** `web` module.
**File:** `src/casforge/web/app.py`.

**Observation:**
The streaming (`/api/generate/stream`) and non-streaming (`/api/generate`) endpoints contain nearly identical code for the feature generation pipeline.

**Proposed Improvement:**
- **Unify the logic:** Refactor the non-streaming endpoint to call the streaming one internally. It can simply collect all the events from the stream and return the final "feature" event as a single JSON response.

**Benefit:**
This would eliminate significant code duplication, making the API easier to maintain and ensuring that any changes to the generation logic are automatically reflected in both endpoints.

## 4. Implement a Database Connection Pool

**Area:** `storage` module.
**File:** `src/casforge/storage/connection.py`.

**Observation:**
The application creates a new database connection for every operation. This is not scalable and will become a performance bottleneck under concurrent load.

**Proposed Improvement:**
- **Use `psycopg2.pool`:** Replace the `get_conn()` function with a connection pool (e.g., `SimpleConnectionPool` or `ThreadedConnectionPool` from `psycopg2.pool`). The `get_conn()` function would then fetch a connection from the pool and `putconn()` would release it.

**Benefit:**
A connection pool dramatically improves the performance and scalability of the web application by reusing database connections and avoiding the high overhead of establishing new ones for each request.

## 5. Enhance the Logging Configuration

**Area:** Application-wide.

**Observation:**
The current logging setup is a basic `logging.basicConfig` call. This results in flat, unstructured logs that can be difficult to parse when debugging complex issues.

**Proposed Improvement:**
- **Implement structured logging:** Use a more advanced logging configuration, either through a `logging.conf` file or a library like `loguru`.
- **Add contextual information:** Add context to log messages, such as the current story key or request ID, to make it easier to trace the execution flow for a single operation.

**Benefit:**
A structured and configurable logging system is invaluable for debugging, monitoring, and understanding the behavior of a complex application in both development and production environments.
