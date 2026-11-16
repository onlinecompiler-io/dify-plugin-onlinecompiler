## Privacy Policy for the OnlineCompiler.io Dify Plugin

This plugin connects Dify to the OnlineCompiler.io API (`api.onlinecompiler.io`), a service of RunCode Inc., to run and judge code. It sends data only to OnlineCompiler.io. The plugin itself stores nothing, keeps no logs and collects no personal data for itself.

### Data the plugin sends to OnlineCompiler.io

- **API key**: stored by Dify in the plugin's credentials and sent in the `Authorization` header of each request. It is never put into tool output or error messages.
- **Code and input**: the source code, the compiler id, the standard input and the time limit of each Run Code call.
- **Tests**: for Run Tests, the code, the compiler id, each test's input and expected output, the checker and the time limit.
- **Network details**: like any HTTPS request, the IP address of your Dify server and the plugin's name and version (`User-Agent`).

List Compilers sends no key and no user data.

### Data the plugin returns to Dify

The program's output and errors, its exit code, run time and memory, verdicts and scores, and the files the program wrote (for example charts). Dify stores those files as tool files in your workspace.

### Storage and retention at OnlineCompiler.io

Code runs in a fresh sandbox with no network access, so the code itself cannot send your data anywhere. OnlineCompiler.io keeps:

- **Execution history**: each run's code, input, output, errors and IP address, shown in your account's dashboard, for 365 days. After that only a record that the run happened (when, the language, how it ended and the country) stays with your account for usage figures. An input over 64 KB is kept apart from its run and deleted 7 days after it was last used.
- **Returned files**: files a program writes and returns are kept for 60 days, and only your account can fetch them with its API key.
- **Run Tests submissions**: each submission is kept with its result and signed receipt for your plan's retention: 90 days on Free, 1 year on Starter and 2 years on Pro.

Deleting your OnlineCompiler.io account deletes its execution history, files and submissions. The service runs on servers in the European Union. The full policy, including data requests, is at https://onlinecompiler.io/privacy.

### Third parties

The plugin talks only to OnlineCompiler.io. It shares no data with any other third party.

### Contact

Privacy questions and data requests: hello@runcode.io
