# T-041 gate — not passed

Session `local-f02dceb3f5aa92e41efe039d1de9c48011e00836f667ab332103a3f09399e292` was started in `~/.hermes/cache/scratch/wow-gate/work` with skill `wow-addon-builder`. It could call `wow_env` (ok, fake root). The other eight plugin tools were not in that session's tool list. `tool_search` returned only `wow_env`. Calling them through `tool_call` failed: not a known tool name.

The host gateway loads plugin tools once. A reload reported the nine tools as deferred and said tool schemas apply on the next session; the next `hermes chat` still saw only `wow_env`. Restarting the gateway from this process is blocked, because the gateway would kill the command.

After the string-library fix, the same handlers against the fake install returned ok for wow_env, wow_api status, wow_api lookup, wow_new, wow_check pass, wow_test pass, wow_savedvars, wow_errors, wow_bridge pull, and wow_bridge push. wow_install then copied Throwaway into the fake `_forever_` AddOns folder and did not write `/Applications`. That is not the session the accept requires. Re-run `hermes chat` after the gateway is restarted from outside this process.
