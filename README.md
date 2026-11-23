# OnlineCompiler.io for Dify

**Author:** RunCode Inc.
**Type:** tool
**Source:** https://github.com/onlinecompiler-io/dify-plugin-onlinecompiler
**Contact:** hello@onlinecompiler.io

A [Dify](https://dify.ai) tool plugin that lets workflows and agents run and judge code with
[OnlineCompiler.io](https://onlinecompiler.io). Send a program in one of 46 languages and get its standard output,
standard error, exit code, run time and memory back, or check it against test cases and get a verdict per test and
a score.

Every run happens on OnlineCompiler.io's servers, in a fresh sandbox with no network access. The plugin itself runs
no code inside Dify; it only calls the OnlineCompiler.io API.

## Install

In Dify, open **Plugins**, click **Install plugin** and pick one:

- **Marketplace**: search for `OnlineCompiler.io`.
- **Local Package File**: a `.difypkg` built from this repository (see [Packaging](#packaging)). A self-hosted Dify
  installs an unsigned local package only with `FORCE_VERIFYING_SIGNATURE=false` in its `.env`.

The plugin needs Dify 1.10.0 or newer.

## Setup

1. Sign in at [api.onlinecompiler.io](https://api.onlinecompiler.io/compilers/api-keys/?utm_source=dify) with Google or
   email and copy the key shown on the API Keys page: every new account already has one. The key is free: the Free plan includes 100,000 runs a month, commercial use
   allowed, no credit card.
2. In Dify, open **Plugins**, select **OnlineCompiler.io** and click **Authorize**.
3. Paste the key and save.

Dify checks the key once with `GET /api/usage/`, which counts no run. A wrong or disabled key is refused at this
step with the API's reason.

## Connection requirements

The plugin makes HTTPS requests (port 443) to `api.onlinecompiler.io` only. The Dify plugin runtime must be able to
reach that host; on a self-hosted Dify behind a proxy or firewall, allow it. If you restricted the API key to an IP
address in the OnlineCompiler.io dashboard, allow your Dify server's address.

## Tools

| Tool | What it does | API |
|---|---|---|
| Run Code | Runs one program and returns its output, errors, exit code, time and memory, plus any files it wrote. | `POST /api/run-code-sync/` |
| Run Tests | Runs one program against a list of tests and returns an overall verdict, a score and a verdict per test. | `POST /api/run-tests/` |
| List Compilers | Lists every compiler id, its language name and the packages installed with it. Needs no key. | `GET /api/compilers/` |

### Run Code

| Parameter | Type | Required | Meaning |
|---|---|---|---|
| `compiler` | select | yes | Compiler id, default `python-3.14`. For example `nodejs-24`, `typescript-deno`, `gcc-15` (C), `g++-15` (C++), `openjdk-25` (Java), `go-1.26`, `rust-1.93`, `dotnet-csharp-10` (C#), `php-8.5`, `ruby-4.0`, `bash-5.2`, `sqlite-3`. All ids: [onlinecompiler.io/docs/compilers](https://onlinecompiler.io/docs/compilers). |
| `code` | string | yes | The whole program, as one source file. |
| `input` | string | no | Standard input for the program. |
| `time_limit` | number | no | Seconds the program may run, above 0 and at most 30. Empty (or 0) means 30. Compiling before the run does not count. |

Result:

- **Text**: a short summary, such as `Ran python-3.14: success, exit code 0, time 0.0248 s, memory 8192 KB.`, with
  the first 500 characters of the output and errors.
- **JSON**: the API's result: `output`, `error`, `status` (`success` or `error`), `exit_code`, `signal`, `time`
  (seconds), `total`, `memory` (KB), `truncated`, `time_limit`, `memory_limit`, and `files` listed by `name`, `mime`,
  `size` and `url` (a CSV, JSON or text file also carries its `text`).
- **Variables**: `output`, `error`, `status`, `exit_code`, `time`, `memory` and `truncated`, so a later workflow node
  can use the tool node's `output` directly.
- **Files**: every file the program wrote to the directory in `$OUTPUT_DIR` (PNG, SVG, CSV, JSON or text, up to 8
  files and 2 MB). Images show as images in chat. In `python-3.14`, `plt.show()` saves each open matplotlib figure,
  so a chart comes back without extra code.

Exit code 124 means the time limit was reached, 137 the memory limit, 153 an output flood, 71 too many processes.

### Run Tests

| Parameter | Type | Required | Meaning |
|---|---|---|---|
| `compiler` | select | yes | Compiler id, as for Run Code. |
| `code` | string | yes | The program. It reads each test's input from standard input and prints its answer. |
| `tests` | string (JSON) | yes | A JSON list of tests: `[{"input": "2 3", "expected_output": "5"}, {"input": "10 -4", "expected_output": "6"}]`. Add `"hidden": true` to a test to get back only its verdict. |
| `checker` | select | no | How output is compared: `trim` (default, ignores trailing whitespace), `exact`, `tokens`, `float`, `rows`, `table` or `table_ordered`. |
| `time_limit` | number | no | Seconds each test may take, above 0 and at most 30. Empty means 2. |

The plugin sends `"scoring": "percent"`, so every test runs and `score` is the percentage of tests passed (0 to 100).

Result:

- **Text**: the overall verdict and score, the API's one-line `summary`, and any compiler output.
- **JSON**: `verdict` (`accepted`, `wrong_answer`, `time_limit_exceeded`, `memory_limit_exceeded`,
  `output_limit_exceeded`, `runtime_error`, `compilation_error`, `internal_error` or `incomplete`), `score`, `passed`,
  `total`, `time_limit`, `memory_limit`, `compile_error`, `summary`, `submission` (the id the result is stored under)
  and `tests`, one entry per test in the order sent. A visible test has its `verdict`, `output`, `error`, `exit_code`,
  `time` and `memory`; a hidden test has only its `verdict`. The signed receipt is left out.
- **Variables**: `verdict`, `score`, `passed`, `total`, `summary`, `compile_error` and `submission`.

### List Compilers

No parameters. Returns `compilers` (each with `id`, `name` and, where there are any, `packages`) and `retired` (old
ids that still run on their successors). The test-pack ids (`python-3.14-tests` and similar) are left out: they serve
test suites, which this plugin does not send.

## Usage

### Example workflow: check code a model wrote

1. Create a **Workflow** app. In the **Start** node add two inputs: `task` (paragraph) and `tests` (paragraph).
2. Add an **LLM** node that writes a Python program for `{{task}}` which reads standard input and prints the answer.
   Tell it to reply with the code only.
3. Add a **Tool** node, pick **OnlineCompiler.io** and **Run Tests**. Set `compiler` to `python-3.14`, `code` to the
   LLM node's `text`, and `tests` to the Start node's `tests`.
4. Add an **End** node that outputs the tool's `verdict`, `score` and `summary`.
5. Run it with, for example, `task` = "Print the sum of two integers given on one line" and `tests` =
   `[{"input": "2 3", "expected_output": "5"}, {"input": "-1 1", "expected_output": "0"}]`. The result is
   `verdict` = `accepted` and `score` = `100` when the model's code is right.

To handle a failure, add an **IF/ELSE** node on `verdict` after the tool, for example to ask the LLM again with
`summary`.

### Agent app

In an **Agent** app (or a chatflow with an Agent node), add **Run Code** and **Run Tests** under **Tools**. The
agent can then compute exact answers ("What is the 100th prime?"), test the code it writes before showing it, and
draw charts with matplotlib, which appear in the chat as images.

## Limits

- 46 languages, in 48 compiler ids with the `python-3.14-pandas2` and `g++-15-cpp20` variants. Python 3.14 comes
  with numpy, pandas, scipy, scikit-learn, matplotlib, seaborn, statsmodels, sympy, polars, nltk and more (see
  **List Compilers**).
- The sandbox has **no network**: code cannot download packages or call other services, and nothing can be installed
  at run time.
- Per run: 30 seconds, 512 MB of memory and 2 CPUs. Output and errors are each cut at 64 KB (`truncated` is then
  true). Source code up to 100,000 bytes and standard input up to 5 MB.
- Each Run Code call counts as one run, and each test of a Run Tests call counts as one run, toward your plan's
  monthly allowance. The Free plan has 100,000 runs a month; plans also limit runs per minute and how many tests one
  request may hold.

Current values for your account: `GET https://api.onlinecompiler.io/api/usage/` with your key, and the defaults at
[api.onlinecompiler.io/api/limits/](https://api.onlinecompiler.io/api/limits/).

## Errors

A run that fails (a compile error, an exception, a time limit) is a normal result, with `status` = `error` and the
details in `error`. The tool itself fails only when the API refuses the request:

| HTTP | Meaning |
|---|---|
| 400 | The request is invalid, for example an unknown compiler id or a bad `tests` list. The message says what to fix. |
| 403 | The key is not a REST API key (widget keys are refused), or it is limited to another IP address. |
| 404 | The key does not exist or was disabled. |
| 413 | The request body is over 32 MB. |
| 429 | A limit was reached: too many runs a minute, too many at once, or the month's allowance. Nothing ran and nothing was counted. |

The API key never appears in an error message.

## Privacy

Code, input and tests are sent to OnlineCompiler.io to run, and are kept in your account's run history. See
[PRIVACY.md](PRIVACY.md) and the full policy at https://onlinecompiler.io/privacy.

## Development

Unit tests mock the HTTP layer; the live tests call the real API when `ONLINECOMPILER_API_KEY` is set.

```bash
python3 -m venv /tmp/dify-venv
/tmp/dify-venv/bin/pip install -r requirements.txt pytest pyyaml
/tmp/dify-venv/bin/python -m pytest -q
ONLINECOMPILER_API_KEY=your-key /tmp/dify-venv/bin/python -m pytest -q tests/test_live.py
```

### Packaging

Build the package with the [Dify plugin CLI](https://github.com/langgenius/dify-plugin-daemon/releases) (the release
binary `dify-plugin-<os>-<arch>`, often renamed to `dify`), from the folder above this one:

```bash
dify plugin package ./dify-plugin-onlinecompiler -o onlinecompiler-0.0.2.difypkg
unzip -l onlinecompiler-0.0.2.difypkg
```

The package holds `manifest.yaml`, `main.py`, `_onlinecompiler.py`, `provider/`, `tools/`, `_assets/icon.svg`,
`requirements.txt`, `README.md`, `PRIVACY.md` and `LICENSE`; `.difyignore` keeps the tests and development files
out.

## Links

- Documentation: https://onlinecompiler.io/docs
- Compiler ids: https://onlinecompiler.io/docs/compilers
- Run tests: https://onlinecompiler.io/docs/run-tests
- API keys: https://api.onlinecompiler.io/compilers/api-keys/

## License

MIT, see [LICENSE](LICENSE). Copyright RunCode Inc.
