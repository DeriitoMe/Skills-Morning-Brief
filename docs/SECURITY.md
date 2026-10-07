# Security and data boundaries

Skills Morning Brief 1.0.0 runs on the current user's machine and binds to `127.0.0.1`. Public Skills and news endpoints use explicit field allowlists. Private inventories, goals, feedback and reports require a launch session; changes additionally require a CSRF token and a local origin.

GitHub discovery forces public search and accepts only metadata explicitly declaring a public repository. Discovery caches and exported checkpoints retain only verified public entries; unknown legacy discovery entries are discarded. This gate applies before repository names and Stars enter distributable discovery metadata.

API keys entered in the page stay in server memory for that provider and workspace. Keys for scheduled operation are read from the user's environment. Requests carrying authorization refuse HTTP redirects. Model errors never include the provider's response body. The browser receives configuration availability, never the key itself.

Personal recommendations send capability names, descriptions and business goals to the selected model. Keep confidential business information out of those fields, or use a local compatible model. Public monitoring uses only public source material. Skills are inspected as documents; their scripts are never automatically executed or installed.

Private files remain in the OS user's data directory. The existing `AgentSkillShelf` directory identifier is retained for compatibility. Runtime logs, caches, prototype preferences and experiments are excluded from Git and release assets. Bundled public summaries include source links and timestamps; raw Skill instructions are downloaded from a pinned commit and checked against their fingerprint when needed.

The release audit scans staged files, history and ZIP entries for known local private values, common credential formats and private filenames. It reports only filenames and finding types. This is a scoped source and artifact audit, not a guarantee about all credentials, browser extensions, other applications or future changes. Audit again before publishing updated public seeds or assets.

This local Python server is not designed as a shared Internet service. A hosted multiuser version requires its own account authentication, authorization and deployment review.
